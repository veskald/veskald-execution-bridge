import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from coinbase.rest import RESTClient

from config import (
    COINBASE_API_KEY,
    COINBASE_API_SECRET,
    COINBASE_INTX_PORTFOLIO_UUID,
)
from lib.base_trader import (
    BaseTrader, Direction, PositionMode, make_client_id,
)
from lib.symbols import to_exchange_symbol


_BENIGN_TEXTS = (
    "no change",
    "already set",
    "leverage not modified",
)
_NON_RETRYABLE_TEXTS = (
    "insufficient",
    "invalid",
    "not allowed",
    "not exist",
    "minimum",
    "maximum",
    "rejected",
    "would trigger",
    "permission denied",
    "unauthorized",
    "preview_invalid_order",
    "preview_insufficient_fund",
    "permission_denied",
    "unsupported_order_configuration",
    "invalid_request",
)
_RETRYABLE_TEXTS = (
    "timeout",
    "service unavailable",
    "internal server error",
    "rate limit",
    "too many requests",
    "system busy",
)


def _classify(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return "retryable"
    for s in _BENIGN_TEXTS:
        if s in t:
            return "benign"
    for s in _NON_RETRYABLE_TEXTS:
        if s in t:
            return "non_retryable"
    for s in _RETRYABLE_TEXTS:
        if s in t:
            return "retryable"
    return "unknown"


def _to_dict(obj: Any) -> Dict[str, Any]:

    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


class VeskaldCoinbase(BaseTrader):
    BROKER_NAME = "coinbase"

    _MARGIN_WARNING_LOGGED: bool = False

    _portfolio_uuid_cache: Optional[str] = None

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)

        self.client = RESTClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            timeout=10,
        )

    # ---------- helpers ----------

    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "coinbase")

    @staticmethod
    def _coinbase_side(direction: str) -> str:
        return "BUY" if direction.upper() == "LONG" else "SELL"

    @staticmethod
    def _close_side(direction: str) -> str:
        return "SELL" if direction.upper() == "LONG" else "BUY"

    @staticmethod
    def _stop_direction(direction: str) -> str:
        return ""

    def _portfolio_uuid(self) -> Optional[str]:

        if VeskaldCoinbase._portfolio_uuid_cache is not None:
            return VeskaldCoinbase._portfolio_uuid_cache
        if COINBASE_INTX_PORTFOLIO_UUID:
            VeskaldCoinbase._portfolio_uuid_cache = COINBASE_INTX_PORTFOLIO_UUID
            return VeskaldCoinbase._portfolio_uuid_cache

        resp = self._safe_call(self.client.get_portfolios)
        d = _to_dict(resp)
        portfolios = d.get("portfolios") or []
        for p in portfolios:
            pd = _to_dict(p)
            ptype = str(pd.get("type", "")).upper()
            if ptype == "INTX":
                uuid_ = pd.get("uuid") or pd.get("portfolio_uuid")
                if uuid_:
                    VeskaldCoinbase._portfolio_uuid_cache = str(uuid_)
                    return VeskaldCoinbase._portfolio_uuid_cache

        self.logger.error(
            "Coinbase: no INTX portfolio found — perpetuals trading impossible",
            extra={"broker": self.BROKER_NAME},
        )
        return None

    # ---------- core API ----------

    def get_position_mode(self) -> Optional[PositionMode]:

        if self._position_mode_cache is None:
            self._position_mode_cache = "ONE_WAY"
        return self._position_mode_cache

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        portfolio_uuid = self._portfolio_uuid()
        if not portfolio_uuid:
            return False
        product_id = self._ex_symbol(symbol)

        resp = self._safe_call(
            self.client.list_perps_positions, portfolio_uuid=portfolio_uuid,
        )
        d = _to_dict(resp)
        positions = d.get("positions") or []
        for p in positions:
            pd = _to_dict(p)
            if str(pd.get("product_id", "")) != product_id:
                continue
            net_size = pd.get("net_size") or pd.get("size") or "0"
            try:
                size = float(str(net_size))
            except (TypeError, ValueError):
                size = 0.0
            if size == 0.0:
                continue

            side = str(pd.get("side", "")).upper()
            if direction.upper() == "LONG" and ("LONG" in side or size > 0):
                return True
            if direction.upper() == "SHORT" and ("SHORT" in side or size < 0):
                return True
        return False

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        portfolio_uuid = self._portfolio_uuid()
        if not portfolio_uuid:
            return 0.0, "BOTH", self._close_side(direction), 0.0

        product_id = self._ex_symbol(symbol)
        resp = self._safe_call(
            self.client.list_perps_positions, portfolio_uuid=portfolio_uuid,
        )
        d = _to_dict(resp)
        positions = d.get("positions") or []
        amt = 0.0
        be = 0.0
        for p in positions:
            pd = _to_dict(p)
            if str(pd.get("product_id", "")) != product_id:
                continue
            try:
                size = float(str(pd.get("net_size", pd.get("size", "0"))))
            except (TypeError, ValueError):
                size = 0.0
            side = str(pd.get("side", "")).upper()

            is_long = "LONG" in side or size > 0
            is_short = "SHORT" in side or size < 0
            if direction.upper() == "LONG" and not is_long:
                continue
            if direction.upper() == "SHORT" and not is_short:
                continue
            amt = abs(size)

            be_str = (
                pd.get("entry_vwap")
                or pd.get("vwap")
                or pd.get("avg_entry_price")
                or "0"
            )
            try:
                be = float(str(be_str))
            except (TypeError, ValueError):
                be = 0.0
            break

        return amt, "BOTH", self._close_side(direction), be

    def set_isolated_margin(self, symbol: str) -> bool:
        if not VeskaldCoinbase._MARGIN_WARNING_LOGGED:
            self.logger.warning(
                "Coinbase margin mode is account-level. Configure in UI: "
                "Coinbase Advanced → Settings → Perpetuals.",
                extra={"broker": self.BROKER_NAME, "symbol": symbol},
            )
            VeskaldCoinbase._MARGIN_WARNING_LOGGED = True
        return True

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        return True

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        product_id = self._ex_symbol(symbol)
        side = self._coinbase_side(direction)
        params = {
            "client_order_id": make_client_id("open"),
            "product_id": product_id,
            "side": side,
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": str(quantity),
                }
            },
        }
        # retries=0 — idempotency via client_order_id
        resp = self._safe_call(self.client.create_order, retries=0, **params)
        d = _to_dict(resp)
        if not d.get("success"):
            return None
        success = _to_dict(d.get("success_response"))
        order_id = success.get("order_id")
        return str(order_id) if order_id else None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        if amt <= 0:
            self.logger.warning(
                "Coinbase set_stop_loss_price: no position size, skipping",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        return self._place_stop_market(
            symbol=symbol, direction=direction, base_size=amt,
            stop_trigger_price=float(stop_loss_price),
            is_take_profit=False,
        )

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            oid = self._place_stop_market(
                symbol=symbol, direction=direction,
                base_size=tp["quantity"],
                stop_trigger_price=tp["price"],
                is_take_profit=True,
            )
            self.logger.info(
                f"Coinbase TP @ {tp['price']} ({tp['quantity']}) placed for {symbol} (id={oid})",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:

        position_mode = "ONE_WAY"
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        if amt <= 0:
            self.logger.warning(
                "Coinbase move_trailing_stop: no position size",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        new_id = self._place_stop_market(
            symbol=symbol, direction=direction, base_size=amt,
            stop_trigger_price=float(price), is_take_profit=False,
        )
        if new_id is None:
            self.logger.error(
                f"Coinbase failed to place new SL @ {price}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        self._cancel_stop_orders(
            symbol=symbol, direction=direction,
            kind="sl", keep_order_id=new_id,
        )
        return new_id

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        product_id = self._ex_symbol(symbol)
        params = {
            "client_order_id": make_client_id("close"),
            "product_id": product_id,
            "side": self._close_side(direction),
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": str(quantity),
                }
            },
        }
        resp = self._safe_call(self.client.create_order, retries=2, **params)
        d = _to_dict(resp)
        if not d.get("success"):
            return None
        success = _to_dict(d.get("success_response"))
        order_id = success.get("order_id")
        return str(order_id) if order_id else None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        self._cancel_stop_orders(symbol=symbol, direction=direction, kind="all")

    def _place_stop_market(
        self,
        symbol: str,
        direction: str,
        base_size: float,
        stop_trigger_price: float,
        is_take_profit: bool,
    ) -> Optional[str]:

        product_id = self._ex_symbol(symbol)
        is_long = direction.upper() == "LONG"

        if is_take_profit:
            stop_direction = "STOP_DIRECTION_STOP_UP" if is_long else "STOP_DIRECTION_STOP_DOWN"
        else:
            stop_direction = "STOP_DIRECTION_STOP_DOWN" if is_long else "STOP_DIRECTION_STOP_UP"


        slippage = 0.01
        if is_long:
            limit_price = stop_trigger_price * (1 - slippage)
        else:
            limit_price = stop_trigger_price * (1 + slippage)

        params = {
            "client_order_id": make_client_id("tp" if is_take_profit else "sl"),
            "product_id": product_id,
            "side": self._close_side(direction),
            "order_configuration": {
                "stop_limit_stop_limit_gtc": {
                    "base_size": str(base_size),
                    "limit_price": f"{limit_price:.10f}".rstrip("0").rstrip("."),
                    "stop_price": str(stop_trigger_price),
                    "stop_direction": stop_direction,
                }
            },
        }
        resp = self._safe_call(self.client.create_order, retries=2, **params)
        d = _to_dict(resp)
        if not d.get("success"):
            return None
        success = _to_dict(d.get("success_response"))
        order_id = success.get("order_id")
        return str(order_id) if order_id else None

    def _cancel_stop_orders(
        self,
        symbol: str,
        direction: str,
        kind: str = "all",  # "sl" | "tp" | "all"
        keep_order_id: Optional[str] = None,
    ) -> None:
        product_id = self._ex_symbol(symbol)
        close_side = self._close_side(direction)

        resp = self._safe_call(
            self.client.list_orders,
            product_id=product_id,
            order_status=["OPEN"],
        )
        d = _to_dict(resp)
        orders = d.get("orders") or []

        is_long = direction.upper() == "LONG"
        # SL: STOP_DOWN for LONG, STOP_UP for SHORT
        sl_dir = "STOP_DIRECTION_STOP_DOWN" if is_long else "STOP_DIRECTION_STOP_UP"
        tp_dir = "STOP_DIRECTION_STOP_UP" if is_long else "STOP_DIRECTION_STOP_DOWN"

        to_cancel: List[str] = []
        for o in orders:
            od = _to_dict(o)
            if str(od.get("side", "")).upper() != close_side.upper():
                continue
            if str(od.get("product_id", "")) != product_id:
                continue
            order_id = od.get("order_id")
            if not order_id:
                continue
            if keep_order_id is not None and str(order_id) == str(keep_order_id):
                continue

            cfg = _to_dict(od.get("order_configuration"))
            stop_cfg = _to_dict(cfg.get("stop_limit_stop_limit_gtc")
                                or cfg.get("stop_limit_stop_limit_gtd"))
            if not stop_cfg:
                continue
            stop_dir = str(stop_cfg.get("stop_direction", ""))
            if kind == "sl" and stop_dir != sl_dir:
                continue
            if kind == "tp" and stop_dir != tp_dir:
                continue
            to_cancel.append(str(order_id))


        for batch_start in range(0, len(to_cancel), 100):
            batch = to_cancel[batch_start: batch_start + 100]
            self._safe_call(
                self.client.cancel_orders, retries=2, order_ids=batch,
            )



    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[str]]:
        fn_name = getattr(fn, "__name__", repr(fn))
        symbol = params.get("product_id") or params.get("symbol")
        last_text: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
                d = _to_dict(resp)
                # create_order response: {"success": bool, "error_response": {...}}
                if "success" in d and not d.get("success"):
                    err = _to_dict(d.get("error_response"))
                    text = (
                        str(err.get("error", ""))
                        or str(err.get("message", ""))
                        or str(err.get("preview_failure_reason", ""))
                    )
                    last_text = text
                    kind = _classify(text)
                    if kind == "benign":
                        self.logger.info(
                            f"Coinbase benign in {fn_name}: {text}",
                            extra={"symbol": symbol,
                                   "broker": self.BROKER_NAME},
                        )
                        return None, text
                    self.logger.error(
                        f"Coinbase API error in {fn_name}: {text}",
                        extra={"params": params, "kind": kind,
                               "attempt": attempt + 1,
                               "symbol": symbol,
                               "broker": self.BROKER_NAME},
                    )
                    if kind == "non_retryable":
                        return None, text
                    # retryable / unknown — keep retrying
                else:
                    return resp, None
            except Exception as e:
                last_text = str(e)
                kind = _classify(last_text)
                self.logger.error(
                    f"Coinbase transport error in {fn_name}: {e}",
                    extra={"symbol": symbol, "attempt": attempt + 1,
                           "kind": kind,
                           "broker": self.BROKER_NAME},
                    exc_info=True,
                )
                if kind == "non_retryable":
                    return None, last_text
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 5.0))
                continue
            return None, last_text
        return None, last_text