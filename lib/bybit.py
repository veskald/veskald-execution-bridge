import time
from typing import Any, Dict, List, Optional, Set, Tuple

from pybit.exceptions import InvalidRequestError
from pybit.unified_trading import HTTP

from config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET
from lib.base_trader import (
    MAX_LIST_PAGES, BaseTrader, Direction, PositionMode, ProtectiveOrder,
    make_client_id,
)
from lib.symbols import to_exchange_symbol


_BENIGN = {
    34036,
    110043,
    34040,
    110025,
    10001,
}

_NON_RETRYABLE = {
    10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010,
    10018, 10019, 10024, 10027, 10028,
    100028,
    110001, 110003, 110004, 110005, 110006, 110007, 110008, 110009, 110012,
    110013, 110014, 110015, 110017, 110018, 110019, 110020, 110021, 110022,
    110024, 110026, 110027, 110028, 110029, 110030, 110031, 110032, 110033,
    110034, 110035, 110036, 110037, 110038, 110039, 110040, 110041, 110042,
    110044, 110045, 110046, 110047, 110048, 110049,
    170131,
    170132, 170133, 170134, 170135, 170136, 170137, 170138, 170139, 170140,
    170141,
    30084,
}

_RETRYABLE = {
    10000, 10016,
    10017,
    -1, -2,
}


_TRULY_BENIGN = {34036, 110043, 110025, 30084, 34040}


def _classify(code: Optional[int]) -> str:
    if code is None:
        return "retryable"
    if code == 0:
        return "ok"
    if code in _TRULY_BENIGN:
        return "benign"
    if code in _NON_RETRYABLE:
        return "non_retryable"
    if code in _RETRYABLE:
        return "retryable"
    return "unknown"


class VeskaldBybit(BaseTrader):
    BROKER_NAME = "bybit"
    CATEGORY = "linear"

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.client = HTTP(
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
            testnet=BYBIT_TESTNET,
        )


    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "bybit")

    @staticmethod
    def _bybit_side(direction: str) -> str:
        return "Buy" if direction.upper() == "LONG" else "Sell"

    @staticmethod
    def _close_side(direction: str) -> str:
        return "Sell" if direction.upper() == "LONG" else "Buy"

    @staticmethod
    def _position_idx(direction: str, position_mode: PositionMode) -> int:
        """0 for one-way; 1 for Buy hedge; 2 for Sell hedge."""
        if position_mode == "ONE_WAY":
            return 0
        return 1 if direction.upper() == "LONG" else 2


    def set_position_mode(self, mode: PositionMode) -> bool:
        # Bybit switches per settle coin; the bridge trades USDT perps only.
        try:
            self.client.switch_position_mode(
                category=self.CATEGORY,
                coin="USDT",
                mode=3 if mode == "HEDGE" else 0,
            )
        except InvalidRequestError as e:
            if "not modified" in str(e).lower():
                self._position_mode_cache = None
                return True
            self.logger.error(
                f"Bybit switch_position_mode rejected: {e}",
                extra={"broker": self.BROKER_NAME},
            )
            return False
        except Exception as e:
            self.logger.error(
                f"Bybit switch_position_mode failed: {e}",
                extra={"broker": self.BROKER_NAME},
            )
            return False
        self._position_mode_cache = None
        return True

    def get_position_mode(self) -> Optional[PositionMode]:
        if self._position_mode_cache is not None:
            return self._position_mode_cache
        symbol = self.action_data.get("symbol") or "BTCUSDT"
        ex_sym = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.client.get_positions,
            category=self.CATEGORY,
            symbol=ex_sym,
        )
        if resp is None:
            return None
        rows = self._extract_list(resp)
        is_hedge = any(int(r.get("positionIdx", 0)) in (1, 2) for r in rows)
        if not is_hedge and len(rows) >= 2:
            idx_set = {int(r.get("positionIdx", 0)) for r in rows}
            is_hedge = (1 in idx_set or 2 in idx_set)
        self._position_mode_cache = "HEDGE" if is_hedge else "ONE_WAY"
        return self._position_mode_cache

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        ex_sym = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.client.get_positions,
            category=self.CATEGORY,
            symbol=ex_sym,
        )
        if resp is None:
            return False
        rows = self._extract_list(resp)
        if not rows:
            return False
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.warning(
                "Cannot resolve position mode — assume EXISTS",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return True
        target_idx = self._position_idx(direction, position_mode)
        for r in rows:
            if int(r.get("positionIdx", 0)) != target_idx:
                continue
            size = float(r.get("size", "0") or "0")
            if size == 0.0:
                continue
            if position_mode == "HEDGE":
                return True  # idx already identifies the side
            # ONE_WAY: row side = position direction
            row_side = str(r.get("side", "")).upper()
            if direction.upper() == "LONG" and row_side == "BUY":
                return True
            if direction.upper() == "SHORT" and row_side == "SELL":
                return True
        return False

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        ex_sym = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.client.get_positions,
            category=self.CATEGORY,
            symbol=ex_sym,
        )
        rows = self._extract_list(resp) if resp else []
        position_mode = self.get_position_mode()
        if position_mode is None:
            return 0.0, "0", self._close_side(direction), 0.0

        target_idx = self._position_idx(direction, position_mode)
        amt = 0.0
        be = 0.0
        for r in rows:
            if int(r.get("positionIdx", 0)) != target_idx:
                continue
            size = float(r.get("size", "0") or "0")
            if size <= 0:
                continue
            row_side = str(r.get("side", "")).upper()
            # ONE_WAY: single row with idx=0 — direction comes from side
            if position_mode == "ONE_WAY":
                if direction.upper() == "LONG" and row_side != "BUY":
                    continue
                if direction.upper() == "SHORT" and row_side != "SELL":
                    continue
            amt = size
            be = float(r.get("breakEvenPrice", "0") or "0")
            break

        position_side = str(target_idx)
        return amt, position_side, self._close_side(direction), be

    def set_isolated_margin(self, symbol: str) -> bool:
        leverage = int(self.action_data.get("position", {}).get("leverage", 1))
        ok, code = self._safe_call_with_meta(
            self.client.switch_margin_mode,
            category=self.CATEGORY,
            symbol=self._ex_symbol(symbol),
            tradeMode=1,  # 0 cross, 1 isolated
            buyLeverage=str(leverage),
            sellLeverage=str(leverage),
        )
        if ok:
            return True
        # UTA: per-symbol margin mode change is forbidden — handled at account level.
        if code == 100028:
            return True
        return code in _TRULY_BENIGN

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        ok, code = self._safe_call_with_meta(
            self.client.set_leverage,
            category=self.CATEGORY,
            symbol=self._ex_symbol(symbol),
            buyLeverage=str(int(leverage)),
            sellLeverage=str(int(leverage)),
        )
        if ok:
            return True

        return code in _TRULY_BENIGN

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        params = {
            "category": self.CATEGORY,
            "symbol": self._ex_symbol(symbol),
            "side": self._bybit_side(direction),
            "orderType": "Market",
            "qty": str(quantity),
            "positionIdx": self._position_idx(direction, position_mode),
            "orderLinkId": make_client_id("open"),
        }

        result = self._safe_call(self.client.place_order, retries=0, **params)
        if result is None:
            return None
        oid = self._extract_field(result, "orderId")
        return str(oid) if oid else None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        ok = self._safe_call(
            self.client.set_trading_stop,
            category=self.CATEGORY,
            symbol=self._ex_symbol(symbol),
            stopLoss=str(stop_loss_price),
            slTriggerBy="MarkPrice",
            tpslMode="Full",
            positionIdx=self._position_idx(direction, position_mode),
        )
        if ok is None:
            return None

        return f"sl:{symbol}:{direction}:{stop_loss_price}"

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        close_side = self._close_side(direction)
        pos_idx = self._position_idx(direction, position_mode)
        trigger_dir = 1 if direction.upper() == "LONG" else 2
        ex_sym = self._ex_symbol(symbol)

        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            params: Dict[str, Any] = {
                "category": self.CATEGORY,
                "symbol": ex_sym,
                "side": close_side,
                "orderType": "Market",
                "qty": str(tp["quantity"]),
                "triggerPrice": str(tp["price"]),
                "triggerDirection": trigger_dir,
                "triggerBy": "MarkPrice",
                "reduceOnly": True,
                "closeOnTrigger": True,
                "positionIdx": pos_idx,
                "orderLinkId": make_client_id("tp"),
            }
            self._safe_call(self.client.place_order, retries=2, **params)
            self.logger.info(
                f"TP @ {tp['price']} ({tp['quantity']}) placed for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:

        position_mode = self.get_position_mode()
        if position_mode is None:
            return None
        result = self._safe_call(
            self.client.set_trading_stop,
            category=self.CATEGORY,
            symbol=self._ex_symbol(symbol),
            stopLoss=str(price),
            slTriggerBy="MarkPrice",
            tpslMode="Full",
            positionIdx=self._position_idx(direction, position_mode),
        )
        if result is None:
            self.logger.error(
                f"Failed to update SL @ {price} for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        return f"sl:{symbol}:{direction}:{price}"

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        params = {
            "category": self.CATEGORY,
            "symbol": self._ex_symbol(symbol),
            "side": self._close_side(direction),
            "orderType": "Market",
            "qty": str(quantity),
            "reduceOnly": True,
            "positionIdx": self._position_idx(direction, position_mode),
            "orderLinkId": make_client_id("close"),
        }
        result = self._safe_call(self.client.place_order, retries=2, **params)
        if result is None:
            return None
        oid = self._extract_field(result, "orderId")
        return str(oid) if oid else None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:

        ex_sym = self._ex_symbol(symbol)
        pos_idx = self._position_idx(direction, position_mode)


        self._safe_call(
            self.client.cancel_all_orders,
            category=self.CATEGORY,
            symbol=ex_sym,
            orderFilter="StopOrder",
        )


        self._safe_call(
            self.client.set_trading_stop,
            category=self.CATEGORY,
            symbol=ex_sym,
            stopLoss="0",
            takeProfit="0",
            tpslMode="Full",
            positionIdx=pos_idx,
        )

    def list_protective_orders(self) -> Optional[List[ProtectiveOrder]]:
        rows = self._list_all(
            self.client.get_open_orders, limit=50, orderFilter="StopOrder",
        )
        if rows is None:
            return None
        orders = (
            self.protective_order(
                r.get("orderId"), r.get("orderLinkId"), r.get("symbol"), r.get("side"),
            )
            for r in rows
        )
        return [o for o in orders if o]

    def list_open_positions(self) -> Optional[Set[Tuple[str, Direction]]]:
        rows = self._list_all(self.client.get_positions, limit=200)
        if rows is None:
            return None
        positions = (
            (r.get("symbol"), self.position_direction(r.get("side"), r.get("size")))
            for r in rows
        )
        return {p for p in positions if p[1]}

    def cancel_protective_order(self, order: ProtectiveOrder) -> bool:
        return self._safe_call(
            self.client.cancel_order,
            retries=2,
            category=self.CATEGORY,
            symbol=order.symbol,
            orderId=order.order_id,
        ) is not None

    def _list_all(self, fn, **params) -> Optional[List[Dict[str, Any]]]:
        """Every page of a USDT-settled list; None if any page fails."""
        rows: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(MAX_LIST_PAGES):
            resp = self._safe_call(
                fn, retries=0, category=self.CATEGORY, settleCoin="USDT",
                cursor=cursor, **params,
            )
            if resp is None:
                return None
            rows += self._extract_list(resp)
            cursor = (resp.get("result") or {}).get("nextPageCursor")
            if not cursor:
                return rows
        return None

    @staticmethod
    def _extract_list(resp: Any) -> List[Dict[str, Any]]:
        if isinstance(resp, dict):
            result = resp.get("result") or {}
            lst = result.get("list") or []
            return lst if isinstance(lst, list) else []
        return []

    @staticmethod
    def _extract_field(resp: Any, name: str) -> Optional[Any]:
        if isinstance(resp, dict):
            r = resp.get("result") or {}
            return r.get(name)
        return None

    # ---------- safe_call ----------

    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[int]]:
        fn_name = getattr(fn, "__name__", repr(fn))
        symbol = params.get("symbol")
        last_code: Optional[int] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
                # pybit returns a dict with retCode
                if isinstance(resp, dict):
                    code = resp.get("retCode")
                    if code == 0:
                        return resp, 0
                    last_code = code
                    text = str(resp.get("retMsg", ""))
                    kind = _classify(code)
                    if kind == "benign":
                        self.logger.info(
                            f"Bybit benign in {fn_name}: [{code}] {text}",
                            extra={"symbol": symbol, "broker": self.BROKER_NAME},
                        )
                        return None, code
                    self.logger.error(
                        f"Bybit API error in {fn_name}",
                        extra={"params": params, "code": code, "text": text,
                               "kind": kind, "attempt": attempt + 1,
                               "symbol": symbol, "broker": self.BROKER_NAME},
                    )
                    if kind == "non_retryable":
                        return None, code
                else:
                    return resp, None
            except InvalidRequestError as e:
                code = e.status_code
                last_code = code
                kind = _classify(code)
                if kind == "benign":
                    self.logger.info(
                        f"Bybit benign in {fn_name}: [{code}] {e.message}",
                        extra={"symbol": symbol, "broker": self.BROKER_NAME},
                    )
                    return None, code
                self.logger.error(
                    f"Bybit API error in {fn_name}: [{code}] {e.message}",
                    extra={"params": params, "code": code, "kind": kind,
                           "attempt": attempt + 1, "symbol": symbol,
                           "broker": self.BROKER_NAME},
                )
                if kind == "non_retryable":
                    return None, code
            except Exception as e:
                last_code = None
                self.logger.error(
                    f"Bybit transport error in {fn_name}: {e}",
                    extra={"symbol": symbol, "attempt": attempt + 1,
                           "broker": self.BROKER_NAME},
                    exc_info=True,
                )
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 5.0))
                continue
            return None, last_code
        return None, last_code