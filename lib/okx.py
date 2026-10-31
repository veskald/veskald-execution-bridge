import time
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from okx.Account import AccountAPI
from okx.PublicData import PublicAPI
from okx.Trade import TradeAPI

from config import (
    OKX_API_KEY,
    OKX_API_PASSPHRASE,
    OKX_API_SECRET,
    OKX_DEFAULT_ISOLATED,
    OKX_DEMO,
)
from lib.base_trader import (
    MAX_LIST_PAGES, BaseTrader, Direction, PositionMode, ProtectiveOrder,
    make_client_id,
)
from lib.symbols import to_exchange_symbol

_BENIGN_TEXTS = (
    "leverage not modified",
    "no need to change",
    "position mode is not modified",
    "the new leverage cannot be the same as the existing one",
    "you can't change the leverage",
)
_NON_RETRYABLE_TEXTS = (
    "insufficient",
    "balance is not enough",
    "exceed",
    "invalid",
    "not allowed",
    "not exist",
    "minimum",
    "maximum",
    "tick size",
    "lot size",
    "would trigger",
    "will be triggered immediately",
    "rejected",
    "the contract is being settled",
    "out of range",
    "parameter",
)
_RETRYABLE_TEXTS = (
    "timeout",
    "service unavailable",
    "system busy",
    "request timed out",
    "internal server error",
    "rate limit",
    "request too frequent",
    "operation failed",
)


def _classify(code: Optional[str], text: str = "") -> str:
    if code == "0":
        return "ok"
    t = (text or "").lower()
    for s in _BENIGN_TEXTS:
        if s in t:
            return "benign"
    for s in _NON_RETRYABLE_TEXTS:
        if s in t:
            return "non_retryable"
    for s in _RETRYABLE_TEXTS:
        if s in t:
            return "retryable"
    if code is None and not t:
        return "retryable"
    return "unknown"


class VeskaldOkx(BaseTrader):
    BROKER_NAME = "okx"
    INST_TYPE = "SWAP"
    _ALGO_PAGE_SIZE = 100

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        flag = "1" if OKX_DEMO else "0"
        self.trade = TradeAPI(
            api_key=OKX_API_KEY,
            api_secret_key=OKX_API_SECRET,
            passphrase=OKX_API_PASSPHRASE,
            use_server_time=False,
            flag=flag,
        )
        self.account = AccountAPI(
            api_key=OKX_API_KEY,
            api_secret_key=OKX_API_SECRET,
            passphrase=OKX_API_PASSPHRASE,
            use_server_time=False,
            flag=flag,
        )
        self.public = PublicAPI(flag=flag)

        self._ct_val_cache: Dict[str, float] = {}


    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "okx")

    @staticmethod
    def _okx_side(direction: str) -> str:
        return "buy" if direction.upper() == "LONG" else "sell"

    @staticmethod
    def _close_side(direction: str) -> str:
        return "sell" if direction.upper() == "LONG" else "buy"

    @staticmethod
    def _pos_side(direction: str, position_mode: PositionMode) -> str:
        if position_mode == "ONE_WAY":
            return "net"
        return "long" if direction.upper() == "LONG" else "short"

    def _td_mode(self) -> str:

        return "isolated" if OKX_DEFAULT_ISOLATED else "cross"

    def _ct_val(self, inst_id: str) -> float:

        if inst_id in self._ct_val_cache:
            return self._ct_val_cache[inst_id]
        resp = self._safe_call(
            self.public.get_instruments,
            instType=self.INST_TYPE, instId=inst_id,
        )
        rows = self._extract_data(resp) if resp else []
        if rows:
            try:
                ct_val = float(rows[0].get("ctVal", "1") or "1")
                self._ct_val_cache[inst_id] = ct_val
                return ct_val
            except (TypeError, ValueError):
                pass

        self._ct_val_cache[inst_id] = 1.0
        return 1.0

    def _coin_qty_to_contracts(self, inst_id: str, coin_qty: float) -> str:

        ct_val = self._ct_val(inst_id)
        if ct_val <= 0:
            return str(coin_qty)
        contracts = Decimal(str(coin_qty)) / Decimal(str(ct_val))
        # OKX expects a whole number of contracts as a string.
        # Round down so we never exceed the requested quantity.
        contracts_int = int(contracts)
        return str(max(contracts_int, 0))

    def _contracts_to_coin_qty(self, inst_id: str, contracts: float) -> float:
        ct_val = self._ct_val(inst_id)
        return float(Decimal(str(contracts)) * Decimal(str(ct_val)))



    def set_position_mode(self, mode: PositionMode) -> bool:
        pos_mode = "long_short_mode" if mode == "HEDGE" else "net_mode"
        try:
            resp = self.account.set_position_mode(posMode=pos_mode)
        except Exception as e:
            self.logger.error(
                f"OKX set_position_mode failed: {e}",
                extra={"broker": self.BROKER_NAME},
            )
            return False
        code = str(resp.get("code", "")) if isinstance(resp, dict) else ""
        msg = str(resp.get("msg", "")) if isinstance(resp, dict) else str(resp)
        if code == "0" or "not modified" in msg.lower():
            self._position_mode_cache = None
            return True
        self.logger.error(
            f"OKX set_position_mode rejected: [{code}] {msg}",
            extra={"broker": self.BROKER_NAME},
        )
        return False

    def get_position_mode(self) -> Optional[PositionMode]:
        if self._position_mode_cache is not None:
            return self._position_mode_cache
        resp = self._safe_call(self.account.get_account_config)
        rows = self._extract_data(resp) if resp else []
        if not rows:
            return None
        cfg = rows[0]
        pos_mode = str(cfg.get("posMode", "")).lower()
        if pos_mode == "long_short_mode":
            self._position_mode_cache = "HEDGE"
        else:
            self._position_mode_cache = "ONE_WAY"
        return self._position_mode_cache

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        inst_id = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.account.get_positions, instType=self.INST_TYPE, instId=inst_id,
        )
        rows = self._extract_data(resp) if resp else []
        if not rows:
            return False
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.warning(
                "Cannot resolve OKX position mode — assume EXISTS",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return True

        for r in rows:
            pos = float(r.get("pos", "0") or "0")
            if pos == 0.0:
                continue
            row_pos_side = str(r.get("posSide", "")).lower()
            if position_mode == "HEDGE":
                if (direction.upper() == "LONG" and row_pos_side == "long"
                        and pos > 0):
                    return True
                if (direction.upper() == "SHORT" and row_pos_side == "short"
                        and pos > 0):
                    return True
            else:
                # net mode — pos is signed (positive = long)
                if direction.upper() == "LONG" and pos > 0:
                    return True
                if direction.upper() == "SHORT" and pos < 0:
                    return True
        return False

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        inst_id = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.account.get_positions, instType=self.INST_TYPE, instId=inst_id,
        )
        rows = self._extract_data(resp) if resp else []
        position_mode = self.get_position_mode()
        if position_mode is None:
            return 0.0, "net", self._close_side(direction), 0.0

        amt_contracts = 0.0
        be = 0.0
        for r in rows:
            pos = float(r.get("pos", "0") or "0")
            if pos == 0.0:
                continue
            row_pos_side = str(r.get("posSide", "")).lower()
            if position_mode == "HEDGE":
                if direction.upper() == "LONG" and row_pos_side != "long":
                    continue
                if direction.upper() == "SHORT" and row_pos_side != "short":
                    continue
                amt_contracts = abs(pos)
            else:
                if (direction.upper() == "LONG" and pos > 0) or \
                   (direction.upper() == "SHORT" and pos < 0):
                    amt_contracts = abs(pos)
                else:
                    continue

            be = float(r.get("avgPx", "0") or "0")
            break

        amt_coins = self._contracts_to_coin_qty(inst_id, amt_contracts)
        position_side = self._pos_side(direction, position_mode)
        return amt_coins, position_side, self._close_side(direction), be

    def set_isolated_margin(self, symbol: str) -> bool:
        return True

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        inst_id = self._ex_symbol(symbol)
        position_mode = self.get_position_mode()
        mgn_mode = self._td_mode()  # 'isolated' | 'cross'

        # Hedge isolated needs leverage set for both long and short.
        # Cross or net mode needs a single call.
        results: List[bool] = []
        if position_mode == "HEDGE" and mgn_mode == "isolated":
            for ps in ("long", "short"):
                ok, _ = self._safe_call_with_meta(
                    self.account.set_leverage,
                    instId=inst_id, lever=str(int(leverage)),
                    mgnMode=mgn_mode, posSide=ps,
                )
                results.append(ok is not None)
        else:
            ok, _ = self._safe_call_with_meta(
                self.account.set_leverage,
                instId=inst_id, lever=str(int(leverage)), mgnMode=mgn_mode,
            )
            results.append(ok is not None)
        return all(results)

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        inst_id = self._ex_symbol(symbol)
        sz_contracts = self._coin_qty_to_contracts(inst_id, float(quantity))
        if int(sz_contracts) <= 0:
            self.logger.error(
                f"OKX open_position: contracts size <= 0 (qty={quantity}, "
                f"ctVal={self._ct_val(inst_id)})",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        params = {
            "instId": inst_id,
            "tdMode": self._td_mode(),
            "side": self._okx_side(direction),
            "ordType": "market",
            "sz": sz_contracts,
            "posSide": self._pos_side(direction, position_mode),
            "clOrdId": make_client_id("open"),
        }

        resp = self._safe_call(self.trade.place_order, retries=0, **params)
        rows = self._extract_data(resp) if resp else []
        if not rows:
            return None
        ord_id = rows[0].get("ordId") if isinstance(rows[0], dict) else None
        return str(ord_id) if ord_id else None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        return self._place_conditional(
            symbol=symbol, direction=direction, position_mode=position_mode,
            sl_trigger_price=float(stop_loss_price),
            close_fraction=True,  # close the whole position
        )

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        inst_id = self._ex_symbol(symbol)
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            sz_contracts = self._coin_qty_to_contracts(inst_id, float(tp["quantity"]))
            if int(sz_contracts) <= 0:
                continue
            self._place_conditional(
                symbol=symbol, direction=direction, position_mode=position_mode,
                tp_trigger_price=float(tp["price"]),
                sz_contracts=sz_contracts,
                reduce_only=True,
            )
            self.logger.info(
                f"OKX TP @ {tp['price']} ({tp['quantity']}, {sz_contracts}c) placed for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:
        position_mode = self.get_position_mode()
        if position_mode is None:
            return None

        new_id = self._place_conditional(
            symbol=symbol, direction=direction, position_mode=position_mode,
            sl_trigger_price=float(price), close_fraction=True,
        )
        if new_id is None:
            self.logger.error(
                f"OKX failed to place new SL @ {price}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None


        self._cancel_conditional_orders(
            symbol=symbol, direction=direction, position_mode=position_mode,
            kind="sl", keep_algo_id=new_id,
        )
        return new_id

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        inst_id = self._ex_symbol(symbol)
        sz_contracts = self._coin_qty_to_contracts(inst_id, float(quantity))
        if int(sz_contracts) <= 0:
            return None

        params = {
            "instId": inst_id,
            "tdMode": self._td_mode(),
            "side": self._close_side(direction),
            "ordType": "market",
            "sz": sz_contracts,
            "posSide": self._pos_side(direction, position_mode),
            "clOrdId": make_client_id("close"),
        }

        if position_mode == "ONE_WAY":
            params["reduceOnly"] = "true"

        resp = self._safe_call(self.trade.place_order, retries=2, **params)
        rows = self._extract_data(resp) if resp else []
        if not rows:
            return None
        ord_id = rows[0].get("ordId") if isinstance(rows[0], dict) else None
        return str(ord_id) if ord_id else None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        self._cancel_conditional_orders(
            symbol=symbol, direction=direction, position_mode=position_mode,
            kind="all",
        )

    def list_protective_orders(self) -> Optional[List[ProtectiveOrder]]:
        rows: List[Dict[str, Any]] = []
        after = ""
        for _ in range(MAX_LIST_PAGES):
            resp = self._safe_call(
                self.trade.order_algos_list, retries=0,
                ordType="conditional", instType=self.INST_TYPE,
                after=after, limit=str(self._ALGO_PAGE_SIZE),
            )
            if resp is None:
                return None
            page = self._extract_data(resp)
            rows += page
            if len(page) < self._ALGO_PAGE_SIZE:
                break
            after = str(page[-1].get("algoId", ""))
        else:
            return None
        orders = (
            self.protective_order(
                r.get("algoId"), r.get("algoClOrdId"), r.get("instId"), r.get("side"),
            )
            for r in rows
        )
        return [o for o in orders if o]

    def list_open_positions(self) -> Optional[Set[Tuple[str, Direction]]]:
        resp = self._safe_call(
            self.account.get_positions, retries=0, instType=self.INST_TYPE,
        )
        if resp is None:
            return None
        positions = (
            (r.get("instId"), self.position_direction(r.get("posSide"), r.get("pos")))
            for r in self._extract_data(resp)
        )
        return {p for p in positions if p[1]}

    def cancel_protective_order(self, order: ProtectiveOrder) -> bool:
        return self._safe_call(
            self.trade.cancel_algo_order, retries=2,
            params=[{"algoId": order.order_id, "instId": order.symbol}],
        ) is not None



    def _place_conditional(
        self,
        symbol: str,
        direction: str,
        position_mode: PositionMode,
        *,
        sl_trigger_price: Optional[float] = None,
        tp_trigger_price: Optional[float] = None,
        sz_contracts: Optional[str] = None,
        close_fraction: bool = False,
        reduce_only: bool = False,
    ) -> Optional[str]:
        inst_id = self._ex_symbol(symbol)
        params: Dict[str, Any] = {
            "instId": inst_id,
            "tdMode": self._td_mode(),
            "side": self._close_side(direction),
            "ordType": "conditional",
            "posSide": self._pos_side(direction, position_mode),
            "algoClOrdId": make_client_id("sl" if sl_trigger_price else "tp"),
        }
        if sl_trigger_price is not None:
            params["slTriggerPx"] = str(sl_trigger_price)
            params["slOrdPx"] = "-1"  # market on trigger
            params["slTriggerPxType"] = "mark"
        if tp_trigger_price is not None:
            params["tpTriggerPx"] = str(tp_trigger_price)
            params["tpOrdPx"] = "-1"
            params["tpTriggerPxType"] = "mark"

        if close_fraction:
            params["closeFraction"] = "1"
        elif sz_contracts is not None:
            params["sz"] = sz_contracts
        else:
            self.logger.error(
                "OKX conditional: either close_fraction or sz_contracts required",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        if reduce_only and position_mode == "ONE_WAY":
            params["reduceOnly"] = "true"

        resp = self._safe_call(self.trade.place_algo_order, retries=2, **params)
        rows = self._extract_data(resp) if resp else []
        if not rows:
            return None
        algo_id = rows[0].get("algoId") if isinstance(rows[0], dict) else None
        return str(algo_id) if algo_id else None

    def _cancel_conditional_orders(
        self,
        symbol: str,
        direction: str,
        position_mode: PositionMode,
        kind: Literal["sl", "tp", "all"] = "all",
        keep_algo_id: Optional[str] = None,
    ) -> None:
        inst_id = self._ex_symbol(symbol)
        target_pos_side = self._pos_side(direction, position_mode)
        target_side = self._close_side(direction)


        resp = self._safe_call(
            self.trade.order_algos_list,
            ordType="conditional", instType=self.INST_TYPE, instId=inst_id,
        )
        rows = self._extract_data(resp) if resp else []

        to_cancel: List[Dict[str, str]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("instId", "")) != inst_id:
                continue
            if str(r.get("posSide", "")).lower() != target_pos_side:
                continue
            if str(r.get("side", "")).lower() != target_side:
                continue

            has_sl = bool(r.get("slTriggerPx") and str(r.get("slTriggerPx")) != "")
            has_tp = bool(r.get("tpTriggerPx") and str(r.get("tpTriggerPx")) != "")

            if kind == "sl" and not has_sl:
                continue
            if kind == "tp" and not has_tp:
                continue

            algo_id = r.get("algoId")
            if not algo_id:
                continue
            if keep_algo_id is not None and str(algo_id) == str(keep_algo_id):
                continue
            to_cancel.append({"algoId": str(algo_id), "instId": inst_id})


        for batch_start in range(0, len(to_cancel), 20):
            batch = to_cancel[batch_start: batch_start + 20]
            self._safe_call(
                self.trade.cancel_algo_order, retries=2, params=batch,
            )



    @staticmethod
    def _extract_data(resp: Any) -> List[Dict[str, Any]]:
        if isinstance(resp, dict):
            d = resp.get("data") or []
            return d if isinstance(d, list) else []
        return []


    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[str]]:
        fn_name = getattr(fn, "__name__", repr(fn))
        symbol = params.get("instId") or params.get("symbol")
        last_code: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
                if isinstance(resp, dict):
                    code = str(resp.get("code", ""))
                    msg = str(resp.get("msg", ""))
                    if code == "0":
                        rows = self._extract_data(resp)
                        if rows and isinstance(rows[0], dict):
                            s_code = str(rows[0].get("sCode", "0"))
                            s_msg = str(rows[0].get("sMsg", ""))
                            if s_code not in ("0", ""):
                                last_code = s_code
                                kind = _classify(s_code, s_msg)
                                if kind == "benign":
                                    self.logger.info(
                                        f"OKX benign in {fn_name}: [{s_code}] {s_msg}",
                                        extra={"symbol": symbol,
                                               "broker": self.BROKER_NAME},
                                    )
                                    return None, s_code
                                self.logger.error(
                                    f"OKX API error in {fn_name}: [{s_code}] {s_msg}",
                                    extra={"params": params, "kind": kind,
                                           "attempt": attempt + 1,
                                           "symbol": symbol,
                                           "broker": self.BROKER_NAME},
                                )
                                if kind == "non_retryable":
                                    return None, s_code
                            else:
                                return resp, None
                        else:
                            return resp, None
                    else:
                        last_code = code
                        kind = _classify(code, msg)
                        if kind == "benign":
                            self.logger.info(
                                f"OKX benign in {fn_name}: [{code}] {msg}",
                                extra={"symbol": symbol,
                                       "broker": self.BROKER_NAME},
                            )
                            return None, code
                        self.logger.error(
                            f"OKX API error in {fn_name}: [{code}] {msg}",
                            extra={"params": params, "kind": kind,
                                   "attempt": attempt + 1,
                                   "symbol": symbol,
                                   "broker": self.BROKER_NAME},
                        )
                        if kind == "non_retryable":
                            return None, code
                else:
                    return resp, None
            except Exception as e:
                last_code = None
                self.logger.error(
                    f"OKX transport error in {fn_name}: {e}",
                    extra={"symbol": symbol, "attempt": attempt + 1,
                           "broker": self.BROKER_NAME},
                    exc_info=True,
                )
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 5.0))
                continue
            return None, last_code
        return None, last_code