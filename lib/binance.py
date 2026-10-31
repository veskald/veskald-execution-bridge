import re
import time
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
)

from config import BINANCE_API_KEY, BINANCE_API_SECRET
from lib.base_trader import (
    BaseTrader, Direction, PositionMode, ProtectiveOrder, make_client_id,
)
from lib.symbols import to_exchange_symbol


_BENIGN = {
    -4046,
    -4059,
}
_NON_RETRYABLE = {
    -1100, -1101, -1102, -1104, -1106, -1111, -1115, -1116, -1117, -1120,
    -1121, -1125, -1127, -1128, -1130,
    -2010, -2011, -2013, -2014, -2015, -2018, -2019, -2020, -2021, -2022,
    -2023, -2024, -2025, -2026, -2027, -2028,
    -4003, -4004, -4005, -4006, -4007, -4008, -4009, -4010, -4011, -4012,
    -4013, -4014, -4015, -4016, -4017, -4018, -4019, -4020, -4021, -4022,
    -4023, -4024, -4025, -4026, -4027, -4028, -4029, -4030,
    -4061, -4062, -4063, -4064, -4065, -4066, -4067, -4068, -4069,
    -4120, -4131, -4164,
}
_RETRYABLE = {-1000, -1001, -1003, -1006, -1007, -1008, -1021, -1099}

# Known Binance error texts that must not be retried (the exchange often
# returns them WITHOUT a numeric code inside the SDK exception wrapper).
_NON_RETRYABLE_TEXTS = (
    "open stop or take profit order with gte and closeposition",  # duplicate protective order
    "order would immediately trigger",
    "reduceonly order is rejected",
    "reduceonly order failed",
    "margin is insufficient",
    "balance is insufficient",
    "order's notional must be no smaller than",
    "tick size",
    "lot size",
    "precision is over the maximum",
    "leverage reduction is not supported",
    "no need to modify",
    "exceed maximum modify order limit",
    "order does not exist",
    "unknown order sent",
)

_RETRYABLE_TEXTS = (
    "timeout",
    "service unavailable",
    "internal error",
    "too many requests",
    "timestamp for this request",
)


def _classify(code: Optional[int], text: str = "") -> str:
    if code is not None:
        if code in _BENIGN:
            return "benign"
        if code in _NON_RETRYABLE:
            return "non_retryable"
        if code in _RETRYABLE:
            return "retryable"
    t = (text or "").lower()
    if t:
        for s in _NON_RETRYABLE_TEXTS:
            if s in t:
                return "non_retryable"
        for s in _RETRYABLE_TEXTS:
            if s in t:
                return "retryable"
    if code is None and not t:
        return "retryable"
    return "unknown"


class VeskaldBinance(BaseTrader):
    BROKER_NAME = "binance"

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        configuration = ConfigurationRestAPI(
            api_key=BINANCE_API_KEY,
            api_secret=BINANCE_API_SECRET,
            base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
        )
        self.client = DerivativesTradingUsdsFutures(config_rest_api=configuration)


    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "binance")

    @staticmethod
    def _resolve_position_side(direction: str, position_mode: PositionMode) -> str:
        return direction.upper() if position_mode == "HEDGE" else "BOTH"


    def set_position_mode(self, mode: PositionMode) -> bool:
        try:
            self.client.rest_api.change_position_mode(
                dual_side_position="true" if mode == "HEDGE" else "false",
            )
        except Exception as e:
            if "no need to change" in str(e).lower():
                self._position_mode_cache = None
                return True
            self.logger.error(
                f"Binance change_position_mode failed: {e}",
                extra={"broker": self.BROKER_NAME},
            )
            return False
        self._position_mode_cache = None
        return True

    def get_position_mode(self) -> Optional[PositionMode]:
        if self._position_mode_cache is not None:
            return self._position_mode_cache
        data = self._safe_call(self.client.rest_api.get_current_position_mode)
        if not data:
            return None
        val = getattr(data, "dual_side_position", None)
        if val is None and isinstance(data, dict):
            val = data.get("dualSidePosition")
        is_hedge = bool(val) if isinstance(val, bool) else str(val).lower() == "true"
        self._position_mode_cache = "HEDGE" if is_hedge else "ONE_WAY"
        return self._position_mode_cache

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        rows = self._safe_call(
            self.client.rest_api.position_information_v3,
            symbol=self._ex_symbol(symbol),
        ) or []
        if not rows:
            return False
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.warning(
                "Cannot resolve position mode — assume EXISTS",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return True
        direction = direction.upper()
        if position_mode == "HEDGE":
            for r in rows:
                if (str(getattr(r, "position_side", "")).upper() == direction
                        and float(getattr(r, "position_amt", 0.0)) != 0.0):
                    return True
            return False
        pos_amt = float(getattr(rows[0], "position_amt", 0.0))
        return (pos_amt > 0) if direction == "LONG" else (pos_amt < 0)

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        direction = direction.upper()
        rows = self._safe_call(
            self.client.rest_api.position_information_v3,
            symbol=self._ex_symbol(symbol),
        ) or []
        position_mode = self.get_position_mode()
        if position_mode is None:
            return 0.0, "BOTH", self.opposite_side(direction), 0.0

        if position_mode == "HEDGE":
            row = next(
                (r for r in rows
                 if str(getattr(r, "position_side", "")).upper() == direction),
                None,
            )
            amt = abs(float(getattr(row, "position_amt", 0.0))) if row else 0.0
            be = float(getattr(row, "break_even_price", 0.0)) if row else 0.0
            position_side = direction
        else:
            row = rows[0] if rows else None
            signed = float(getattr(row, "position_amt", 0.0)) if row else 0.0
            be = float(getattr(row, "break_even_price", 0.0)) if row else 0.0
            if (direction == "LONG" and signed > 0) or (direction == "SHORT" and signed < 0):
                amt = abs(signed)
            else:
                amt = 0.0
            position_side = "BOTH"
        return amt, position_side, self.opposite_side(direction), be

    def set_isolated_margin(self, symbol: str) -> bool:
        ok, code = self._safe_call_with_meta(
            self.client.rest_api.change_margin_type,
            symbol=self._ex_symbol(symbol),
            margin_type="ISOLATED",
        )
        if ok:
            return True
        return code == -4046

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        return bool(self._safe_call(
            self.client.rest_api.change_initial_leverage,
            symbol=self._ex_symbol(symbol),
            leverage=int(leverage),
        ))

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[int]:
        binance_side = "BUY" if direction.upper() == "LONG" else "SELL"
        position_side = self._resolve_position_side(direction, position_mode)
        params: Dict[str, Any] = {
            "symbol": self._ex_symbol(symbol),
            "side": binance_side,
            "type": "MARKET",
            "quantity": float(quantity),
            "position_side": position_side,
            "new_order_resp_type": "RESULT",
            "new_client_order_id": make_client_id("open"),
        }

        mkt = self._safe_call(self.client.rest_api.new_order, retries=0, **params)
        if mkt is None:
            return None
        order_id = getattr(mkt, "order_id", None)
        if order_id is None and isinstance(mkt, dict):
            order_id = mkt.get("orderId") or mkt.get("order_id")
        try:
            return int(order_id) if order_id is not None else None
        except (TypeError, ValueError):
            return None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[int]:
        order_side = self.opposite_side(direction)
        position_side = self._resolve_position_side(direction, position_mode)
        return self._place_stop_market_close_all(
            symbol=symbol,
            order_side=order_side,
            position_side=position_side,
            trigger_price=float(stop_loss_price),
        )

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        order_side = self.opposite_side(direction)
        position_side = self._resolve_position_side(direction, position_mode)
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            params: Dict[str, Any] = {
                "algo_type": "CONDITIONAL",
                "symbol": self._ex_symbol(symbol),
                "side": order_side,
                "type": "TAKE_PROFIT_MARKET",
                "trigger_price": tp["price"],
                "position_side": position_side,
                "working_type": "MARK_PRICE",
                "price_protect": "TRUE",
                "quantity": tp["quantity"],
                "client_algo_id": make_client_id("tp"),
            }

            if position_mode == "ONE_WAY":
                params["reduce_only"] = "true"
            self._safe_call(self.client.rest_api.new_algo_order, retries=2, **params)
            self.logger.info(
                f"TP @ {tp['price']} ({tp['quantity']}) placed for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[int]:
        direction = direction.upper()
        position_mode = self.get_position_mode()
        if position_mode is None:
            return None
        position_side = self._resolve_position_side(direction, position_mode)
        sl_side = self.opposite_side(direction)


        snapshot = self._snapshot_stop_orders(
            symbol=symbol, order_side=sl_side, position_side=position_side,
        )


        cancelled_any = self._cancel_algo_orders_by_ids(
            [s["algo_id"] for s in snapshot]
        )
        if not cancelled_any and snapshot:
            self.logger.error(
                "Failed to cancel old SL — refusing to place new (would conflict)",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        new_id = self._place_stop_market_close_all(
            symbol=symbol,
            order_side=sl_side,
            position_side=position_side,
            trigger_price=float(price),
        )
        if new_id is not None:
            return new_id


        self.logger.error(
            f"Failed to place new SL @ {price} — attempting to restore old SL(s)",
            extra={"symbol": symbol, "broker": self.BROKER_NAME,
                   "snapshot_count": len(snapshot)},
        )
        restored = False
        for s in snapshot:
            rid = self._place_stop_market_close_all(
                symbol=symbol,
                order_side=sl_side,
                position_side=position_side,
                trigger_price=float(s["trigger_price"]),
            )
            if rid is not None:
                restored = True
                self.logger.warning(
                    f"Restored old SL @ {s['trigger_price']} (id={rid})",
                    extra={"symbol": symbol, "broker": self.BROKER_NAME},
                )
                break  # one protective order is enough

        if not restored:
            # 5) Worst case — the position is naked. Close at market.
            self.logger.critical(
                "Both new SL and old-SL restore failed — emergency closing position",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            self._emergency_close(symbol, direction, position_mode)
        return None

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[int]:
        position_side = self._resolve_position_side(direction, position_mode)
        side = self.opposite_side(direction)
        params: Dict[str, Any] = {
            "symbol": self._ex_symbol(symbol),
            "side": side,
            "position_side": position_side,
            "quantity": float(quantity),
            "type": "MARKET",
            "new_client_order_id": make_client_id("close"),
        }
        if position_mode == "ONE_WAY":
            params["reduce_only"] = "true"
        result = self._safe_call(
            self.client.rest_api.new_order, retries=2, **params
        )
        order_id = getattr(result, "order_id", None) if result is not None else None
        try:
            return int(order_id) if order_id is not None else None
        except (TypeError, ValueError):
            return None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        position_side = self._resolve_position_side(direction, position_mode)
        order_side = self.opposite_side(direction)
        rows = self._safe_call(
            self.client.rest_api.current_all_algo_open_orders,
            algo_type="CONDITIONAL",
            symbol=self._ex_symbol(symbol),
        ) or []
        if not isinstance(rows, list):
            rows = [rows]
        for o in rows:
            if (str(getattr(o, "side", "")).upper() == order_side
                    and str(getattr(o, "position_side", "")).upper() == position_side):
                algo_id = getattr(o, "algo_id", None)
                if algo_id is not None:
                    self._safe_call(
                        self.client.rest_api.cancel_algo_order,
                        retries=2,
                        algo_id=int(algo_id),
                    )

    def list_protective_orders(self) -> Optional[List[ProtectiveOrder]]:
        rows = self._safe_call(
            self.client.rest_api.current_all_algo_open_orders,
            retries=0,
            algo_type="CONDITIONAL",
        )
        if rows is None:
            return None
        orders = (
            self.protective_order(o.algo_id, o.client_algo_id, o.symbol, o.side)
            for o in rows
        )
        return [o for o in orders if o]

    def list_open_positions(self) -> Optional[Set[Tuple[str, Direction]]]:
        rows = self._safe_call(
            self.client.rest_api.position_information_v3, retries=0,
        )
        if rows is None:
            return None
        positions = (
            (r.symbol, self.position_direction(r.position_side, r.position_amt))
            for r in rows
        )
        return {p for p in positions if p[1]}

    def cancel_protective_order(self, order: ProtectiveOrder) -> bool:
        return self._safe_call(
            self.client.rest_api.cancel_algo_order,
            retries=2,
            algo_id=int(order.order_id),
        ) is not None

    # ---------- internal ----------

    def _place_stop_market_close_all(
        self, symbol: str, order_side: str, position_side: str,
        trigger_price: float,
    ) -> Optional[int]:
        params = {
            "algo_type": "CONDITIONAL",
            "symbol": self._ex_symbol(symbol),
            "side": order_side,
            "type": "STOP_MARKET",
            "trigger_price": float(trigger_price),
            "close_position": "true",
            "position_side": position_side,
            "working_type": "MARK_PRICE",
            "price_protect": "TRUE",
            "client_algo_id": make_client_id("sl"),
        }
        data = self._safe_call(
            self.client.rest_api.new_algo_order, retries=2, **params
        )
        return self._extract_algo_id(data)

    def _snapshot_stop_orders(
        self, symbol: str, order_side: str, position_side: str,
    ) -> List[Dict[str, Any]]:

        rows = self._safe_call(
            self.client.rest_api.current_all_algo_open_orders,
            algo_type="CONDITIONAL",
            symbol=self._ex_symbol(symbol),
        ) or []
        if not isinstance(rows, list):
            rows = [rows]
        snapshot: List[Dict[str, Any]] = []
        for o in rows:
            if (str(getattr(o, "side", "")).upper() != order_side
                    or str(getattr(o, "position_side", "")).upper() != position_side):
                continue
            order_type = str(getattr(o, "order_type", "")).upper()
            if order_type not in ("STOP_MARKET", "STOP"):
                continue
            cp = getattr(o, "close_position", None)
            if cp in (True, "true", "TRUE", "True"):
                pass
            elif cp is None:
                pass
            else:
                continue
            algo_id = getattr(o, "algo_id", None)
            trigger = (
                getattr(o, "stop_price", None)
                or getattr(o, "trigger_price", None)
                or getattr(o, "stopPrice", None)
            )
            if algo_id is None or trigger is None:
                continue
            try:
                snapshot.append({
                    "algo_id": int(algo_id),
                    "trigger_price": float(trigger),
                })
            except (TypeError, ValueError):
                continue
        return snapshot

    def _cancel_algo_orders_by_ids(self, algo_ids: List[int]) -> bool:

        if not algo_ids:
            return True
        any_ok = False
        for algo_id in algo_ids:
            ok, _ = self._safe_call_with_meta(
                self.client.rest_api.cancel_algo_order,
                retries=2,
                algo_id=int(algo_id),
            )
            if ok is not None:
                any_ok = True
        return any_ok

    @staticmethod
    def _extract_algo_id(data: Any) -> Optional[int]:
        if data is None:
            return None
        if hasattr(data, "algo_id") and getattr(data, "algo_id") is not None:
            try:
                return int(getattr(data, "algo_id"))
            except (TypeError, ValueError):
                return None
        if isinstance(data, dict):
            for k in ("algoId", "algo_id"):
                if k in data and data[k] is not None:
                    try:
                        return int(data[k])
                    except (TypeError, ValueError):
                        return None
        return None


    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[int]]:
        fn_name = getattr(fn, "__name__", repr(fn))
        symbol = params.get("symbol")
        params.setdefault("recv_window", 20000)
        last_code: Optional[int] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
                result = resp.data() if hasattr(resp, "data") else resp
                return result, None
            except Exception as e:
                code, text = self._extract_err(e)
                last_code = code
                kind = _classify(code, text)
                if kind == "benign":
                    self.logger.info(
                        f"API benign notice in {fn_name}: [{code}] {text}",
                        extra={"symbol": symbol, "broker": self.BROKER_NAME},
                    )
                    return None, code
                self.logger.error(
                    f"Binance API error in {fn_name}",
                    extra={"params": params, "code": code, "text": text,
                           "kind": kind, "attempt": attempt + 1,
                           "symbol": symbol, "broker": self.BROKER_NAME},
                    exc_info=True,
                )
                if kind == "non_retryable":
                    return None, code
                if attempt < retries:
                    time.sleep(min(0.5 * (2 ** attempt), 5.0))
                    continue
                return None, code
        return None, last_code

    @staticmethod
    def _extract_err(e: Exception) -> Tuple[Optional[int], str]:
        s = str(e)
        m = re.search(r'"code"\s*:\s*(-?\d+)\s*,\s*"msg"\s*:\s*"([^"]+)"', s)
        if m:
            return int(m.group(1)), m.group(2)
        if "No need to change margin type" in s:
            return -4046, "No need to change margin type."
        if "Timestamp for this request is outside" in s:
            return -1021, "Timestamp outside recvWindow"
        return None, s