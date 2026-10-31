import time
from typing import Any, Dict, List, Optional, Set, Tuple

from kraken.futures import Market, Trade, User

from config import KRAKEN_API_KEY, KRAKEN_API_SECRET, KRAKEN_SANDBOX
from lib.base_trader import (
    BaseTrader, Direction, PositionMode, ProtectiveOrder, make_client_id,
)
from lib.symbols import to_exchange_symbol


_BENIGN_TEXTS = (
    "leverage not modified",
    "no need to change",
    "already set",
)
_NON_RETRYABLE_TEXTS = (
    "insufficient",
    "invalid",
    "minimum",
    "maximum",
    "not allowed",
    "rejected",
    "would trigger immediately",
    "tick size",
    "lot size",
    "marketSuspended",
    "noOrdersForReduce",
    "wouldNotReducePosition",
)
_RETRYABLE_TEXTS = (
    "timeout",
    "service unavailable",
    "rate limit",
    "too many requests",
    "internal server error",
    "nonceDuplicate",
)


def _classify(text: str) -> str:
    t = text.lower()
    if not t:
        return "ok"
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


class VeskaldKraken(BaseTrader):
    BROKER_NAME = "kraken"

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.trade = Trade(
            key=KRAKEN_API_KEY, secret=KRAKEN_API_SECRET, sandbox=KRAKEN_SANDBOX,
        )
        self.user = User(
            key=KRAKEN_API_KEY, secret=KRAKEN_API_SECRET, sandbox=KRAKEN_SANDBOX,
        )

        self.market = Market(
            key=KRAKEN_API_KEY, secret=KRAKEN_API_SECRET, sandbox=KRAKEN_SANDBOX,
        )


    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "kraken")

    @staticmethod
    def _kraken_side(direction: str) -> str:

        return "buy" if direction.upper() == "LONG" else "sell"

    @staticmethod
    def _close_side(direction: str) -> str:
        return "sell" if direction.upper() == "LONG" else "buy"



    def get_position_mode(self) -> Optional[PositionMode]:

        if self._position_mode_cache is None:
            self._position_mode_cache = "ONE_WAY"
        return self._position_mode_cache

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        positions = self._get_open_positions()
        if positions is None:
            return False
        ex_sym = self._ex_symbol(symbol).lower()  # Kraken returns lowercase symbols
        for p in positions:
            if str(p.get("symbol", "")).lower() != ex_sym:
                continue
            size = float(p.get("size", 0) or 0)
            if size <= 0:
                continue
            side = str(p.get("side", "")).lower()
            if direction.upper() == "LONG" and side == "long":
                return True
            if direction.upper() == "SHORT" and side == "short":
                return True
        return False

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        positions = self._get_open_positions() or []
        ex_sym = self._ex_symbol(symbol).lower()
        amt = 0.0
        be = 0.0
        for p in positions:
            if str(p.get("symbol", "")).lower() != ex_sym:
                continue
            side = str(p.get("side", "")).lower()
            size = float(p.get("size", 0) or 0)
            if size <= 0:
                continue
            if direction.upper() == "LONG" and side != "long":
                continue
            if direction.upper() == "SHORT" and side != "short":
                continue
            amt = size

            be = float(
                p.get("avgEntryPrice")
                or p.get("price")
                or p.get("entryPrice")
                or 0
            )
            break
        return amt, "BOTH", self._close_side(direction), be

    _MARGIN_WARNING_LOGGED: bool = False

    def set_isolated_margin(self, symbol: str) -> bool:

        if not VeskaldKraken._MARGIN_WARNING_LOGGED:
            self.logger.warning(
                "Kraken margin mode (cross/isolated) is account-level. "
                "Configure it once in Kraken UI: Trade → Settings → Margin Mode. "
                "API cannot toggle it.",
                extra={"broker": self.BROKER_NAME, "symbol": symbol},
            )
            VeskaldKraken._MARGIN_WARNING_LOGGED = True
        return True

    def set_leverage(self, symbol: str, leverage: int) -> bool:

        ok = self._safe_call(
            self.market.set_leverage_preference,
            symbol=self._ex_symbol(symbol),
            maxLeverage=int(leverage),
        )
        return ok is not None

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        params = {
            "orderType": "mkt",
            "symbol": self._ex_symbol(symbol),
            "side": self._kraken_side(direction),
            "size": float(quantity),
            "cliOrdId": make_client_id("open"),
        }

        result = self._safe_call(self.trade.create_order, retries=0, **params)
        if result is None:
            return None
        order_id = self._extract_order_id(result)
        return str(order_id) if order_id else None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        return self._place_stop(
            symbol=symbol, trigger_price=float(stop_loss_price),
            direction=direction,
        )

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        close_side = self._close_side(direction)
        ex_sym = self._ex_symbol(symbol)
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            params = {
                "orderType": "take_profit",
                "symbol": ex_sym,
                "side": close_side,
                "size": tp["quantity"],
                "stopPrice": tp["price"],
                "triggerSignal": "mark",
                "reduceOnly": True,
                "cliOrdId": make_client_id("tp"),
            }
            self._safe_call(self.trade.create_order, retries=2, **params)
            self.logger.info(
                f"TP @ {tp['price']} ({tp['quantity']}) placed for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:

        new_id = self._place_stop(
            symbol=symbol, trigger_price=float(price), direction=direction,
        )
        if new_id is None:
            self.logger.error(
                f"Failed to place new SL @ {price} — keeping old SL",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        self._cancel_stop_orders(
            symbol=symbol, side_to_cancel=self._close_side(direction),
            keep_order_id=new_id,
        )
        return new_id

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        params = {
            "orderType": "mkt",
            "symbol": self._ex_symbol(symbol),
            "side": self._close_side(direction),
            "size": float(quantity),
            "reduceOnly": True,
            "cliOrdId": make_client_id("close"),
        }
        result = self._safe_call(self.trade.create_order, retries=2, **params)
        if result is None:
            return None
        oid = self._extract_order_id(result)
        return str(oid) if oid else None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        close_side = self._close_side(direction)
        self._cancel_stop_orders(symbol=symbol, side_to_cancel=close_side)

    def list_protective_orders(self) -> Optional[List[ProtectiveOrder]]:
        resp = self._safe_call(self.user.get_open_orders, retries=0)
        if resp is None:
            return None
        orders = (
            self.protective_order(
                o.get("order_id"), o.get("cliOrdId"), o.get("symbol"), o.get("side"),
            )
            for o in resp.get("openOrders") or []
        )
        return [o for o in orders if o]

    def list_open_positions(self) -> Optional[Set[Tuple[str, Direction]]]:
        resp = self._safe_call(self.user.get_open_positions, retries=0)
        if resp is None:
            return None
        positions = (
            (p.get("symbol"), self.position_direction(p.get("side"), p.get("size")))
            for p in resp.get("openPositions") or []
        )
        return {p for p in positions if p[1]}

    def cancel_protective_order(self, order: ProtectiveOrder) -> bool:
        return self._safe_call(
            self.trade.cancel_order, retries=2, order_id=order.order_id,
        ) is not None



    def _place_stop(
        self, symbol: str, trigger_price: float, direction: str
    ) -> Optional[str]:
        params = {
            "orderType": "stp",
            "symbol": self._ex_symbol(symbol),
            "side": self._close_side(direction),

            "size": self._current_position_size(symbol, direction),
            "stopPrice": float(trigger_price),
            "triggerSignal": "mark",
            "reduceOnly": True,
            "cliOrdId": make_client_id("sl"),
        }
        if params["size"] <= 0:
            self.logger.warning(
                "_place_stop skipped — no current position size",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        result = self._safe_call(self.trade.create_order, retries=2, **params)
        if result is None:
            return None
        return str(self._extract_order_id(result) or "")

    def _current_position_size(self, symbol: str, direction: str) -> float:
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        return amt

    def _get_open_positions(self) -> Optional[List[Dict[str, Any]]]:
        resp = self._safe_call(self.user.get_open_positions)
        if resp is None:
            return None
        if isinstance(resp, dict):
            return resp.get("openPositions") or []
        return []

    def _cancel_stop_orders(
        self, symbol: str, side_to_cancel: str,
        keep_order_id: Optional[str] = None,
    ) -> None:
        resp = self._safe_call(self.user.get_open_orders)
        if resp is None or not isinstance(resp, dict):
            return
        ex_sym = self._ex_symbol(symbol).lower()
        for o in resp.get("openOrders", []) or []:
            if str(o.get("symbol", "")).lower() != ex_sym:
                continue
            if str(o.get("side", "")).lower() != side_to_cancel.lower():
                continue
            order_type = str(o.get("orderType", "")).lower()
            if order_type not in ("stp", "stop", "stop_market", "stop_loss"):
                continue
            order_id = o.get("order_id") or o.get("orderId")
            if not order_id:
                continue
            if keep_order_id and str(order_id) == str(keep_order_id):
                continue
            self._safe_call(
                self.trade.cancel_order, retries=2, order_id=str(order_id),
            )

    @staticmethod
    def _extract_order_id(resp: Any) -> Optional[str]:
        if not isinstance(resp, dict):
            return None

        ss = resp.get("sendStatus")
        if isinstance(ss, dict):
            oid = ss.get("order_id") or ss.get("orderId")
            if oid:
                return str(oid)
        oid = resp.get("order_id") or resp.get("orderId")
        return str(oid) if oid else None



    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[str]]:
        fn_name = getattr(fn, "__name__", repr(fn))
        symbol = params.get("symbol")
        last_text: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)

                if isinstance(resp, dict):
                    if resp.get("result") == "success":
                        return resp, None

                    ss = resp.get("sendStatus") or {}
                    if isinstance(ss, dict):
                        status = str(ss.get("status", "")).lower()
                        if status in ("placed", "partiallyfilled", "fullyexecuted",
                                       "untouched", "edited"):
                            return resp, None
                        if status:
                            last_text = status
                    err = resp.get("error") or resp.get("errors") or last_text
                    text = err if isinstance(err, str) else str(err)
                    last_text = text
                    kind = _classify(text)
                    if kind == "ok":
                        return resp, None
                    if kind == "benign":
                        self.logger.info(
                            f"Kraken benign in {fn_name}: {text}",
                            extra={"symbol": symbol, "broker": self.BROKER_NAME},
                        )
                        return None, text
                    self.logger.error(
                        f"Kraken API error in {fn_name}: {text}",
                        extra={"params": params, "kind": kind,
                               "attempt": attempt + 1,
                               "symbol": symbol, "broker": self.BROKER_NAME},
                    )
                    if kind == "non_retryable":
                        return None, text
                else:
                    return resp, None
            except Exception as e:
                last_text = str(e)
                self.logger.error(
                    f"Kraken transport error in {fn_name}: {e}",
                    extra={"symbol": symbol, "attempt": attempt + 1,
                           "broker": self.BROKER_NAME},
                    exc_info=True,
                )
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 5.0))
                continue
            return None, last_text
        return None, last_text