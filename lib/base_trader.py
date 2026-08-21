import re
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import Any, Dict, List, Literal, Optional, Tuple

from lib.logger import get_logger

PositionMode = Literal["ONE_WAY", "HEDGE"]
Direction = Literal["LONG", "SHORT"]



_CLIENT_ID_RE = re.compile(r"[^A-Za-z0-9_\-]")


def make_client_id(prefix: str) -> str:
    raw = f"{prefix}-{uuid.uuid4().hex[:16]}"
    safe = _CLIENT_ID_RE.sub("", raw)
    return safe[:36]



class CallResult:
    __slots__ = ("data", "error_code", "error_text", "kind")

    def __init__(
        self,
        data: Any = None,
        error_code: Optional[int] = None,
        error_text: str = "",
        kind: str = "ok",
    ):
        self.data = data
        self.error_code = error_code
        self.error_text = error_text
        self.kind = kind

    @property
    def ok(self) -> bool:
        return self.kind == "ok"

    @property
    def benign(self) -> bool:
        return self.kind == "benign"


class BaseTrader(ABC):
    BROKER_NAME: str = "base"

    def __init__(self, data: Dict[str, Any]):
        self.action_data = data or {}
        self.logger = get_logger(self.__class__.__name__)
        self._position_mode_cache: Optional[PositionMode] = None


    @staticmethod
    def opposite_side(direction: str) -> str:
        return "SELL" if direction.upper() == "LONG" else "BUY"

    @staticmethod
    def opposite_direction(direction: str) -> str:
        return "SHORT" if direction.upper() == "LONG" else "LONG"

    @staticmethod
    def round_to_step(value: float, step: float, direction: str) -> float:

        if step <= 0:
            return float(value)
        rounding = ROUND_CEILING if direction.upper() == "LONG" else ROUND_FLOOR
        dval = Decimal(str(value))
        dstep = Decimal(str(step))
        n = (dval / dstep).to_integral_value(rounding=rounding)
        return float((n * dstep).quantize(dstep))

    def execute_action(self) -> Optional[Any]:
        action = self.action_data.get("action")
        symbol = self.action_data.get("symbol")
        # The full payload is already logged as raw_data on receipt.
        self.logger.info(
            f"[{self.BROKER_NAME}] Received command: {action}",
            extra={"symbol": symbol, "broker": self.BROKER_NAME},
        )
        try:
            if action == "OPEN_POSITION":
                return self._handle_open_position()
            if action == "PLACE_TP":
                return self._handle_place_tp()
            if action == "DO_TAKE_PROFIT":
                self.do_take_profit(
                    self.action_data["symbol"],
                    self.action_data["quantity"],
                    self.action_data["direction"],
                )
                return None
            if action == "MOVE_TRAILING_STOP":
                self.move_trailing_stop(
                    self.action_data["symbol"],
                    self.action_data["direction"],
                    self.action_data["new_price"],
                )
                return None
            if action == "SET_BREAK_EVEN":
                self.set_break_even(
                    self.action_data["symbol"],
                    self.action_data["direction"],
                    self.action_data["precision"],
                )
                return None
            if action == "FIRE_EARLY_EXIT":
                self.fire_early_exit(
                    self.action_data["symbol"], self.action_data["direction"]
                )
                return None

            self.logger.warning(
                f"Unknown action: {action}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        except KeyError as e:
            self.logger.error(
                f"Malformed command — missing key {e}",
                extra={"action_data": self.action_data, "symbol": symbol,
                       "broker": self.BROKER_NAME},
                exc_info=True,
            )
            return None

    def _handle_open_position(self) -> Optional[Any]:
        symbol = self.action_data["symbol"]
        direction = self.action_data["direction"]
        position_data = self.action_data["position"]

        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.error(
                "Cannot resolve position mode — abort OPEN_POSITION",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        if self.has_open_position(symbol, direction):
            self.logger.info(
                f"Position {symbol} {direction} already exists, skip opening",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        # In one-way mode an opposite-direction order would reduce or flip
        # the other strategy's position instead of opening a new one.
        if position_mode == "ONE_WAY" and self.has_open_position(
                symbol, self.opposite_direction(direction)):
            self.logger.warning(
                f"Blocked {direction} open on {symbol}: the opposite position "
                "is already open and the account is in one-way mode. Running "
                "long and short strategies on one asset needs hedge mode — "
                "switch it in the desktop app Settings or on the exchange.",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        self.set_isolated_margin(symbol)
        self.set_leverage(symbol, int(position_data["leverage"]))

        opened_id = self.open_position(
            symbol, position_mode, float(position_data["position"]), direction
        )
        if opened_id is None:
            self.logger.error(
                "open_position returned None — verifying actual state",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            if not self.has_open_position(symbol, direction):
                self.logger.error(
                    "Position was NOT opened — aborting",
                    extra={"symbol": symbol, "broker": self.BROKER_NAME},
                )
                return None
            self.logger.warning(
                "Position appears opened despite missing order id",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

        # SL is critical — close the position if it cannot be placed.
        sl_id = self.set_stop_loss_price(
            symbol, float(position_data["sl"]), direction, position_mode
        )
        if sl_id is None:
            self.logger.error(
                f"Stop-loss FAILED — emergency close {symbol} {direction}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            self._emergency_close(symbol, direction, position_mode)
            return None

        self.logger.info(
            f"SL set @ {position_data['sl']} for {symbol} (id={sl_id})",
            extra={"symbol": symbol, "broker": self.BROKER_NAME},
        )
        return opened_id

    def _handle_place_tp(self) -> None:
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.error(
                "Cannot resolve position mode — abort PLACE_TP",
                extra={"symbol": self.action_data.get("symbol"),
                       "broker": self.BROKER_NAME},
            )
            return
        self.place_take_profits(
            self.action_data["symbol"],
            self.action_data["position"]["take_profits"],
            self.action_data["direction"],
            position_mode,
            float(self.action_data["position"]["quantity"]),
        )

    def set_break_even(self, symbol: str, direction: str, precision: float) -> None:
        amt, _, _, be = self.get_position_size_and_sides(symbol, direction)
        if amt <= 0 or be <= 0:
            self.logger.warning(
                f"set_break_even skipped — no position or BE=0 (amt={amt}, be={be})",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return
        new_sl = self.round_to_step(be, precision, direction)
        self.move_trailing_stop(symbol, direction, new_sl)

    def fire_early_exit(self, symbol: str, direction: str) -> None:
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.error(
                "Cannot resolve position mode — abort FIRE_EARLY_EXIT",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        if amt <= 0:
            self.logger.info(
                f"fire_early_exit: nothing to close on {symbol} {direction}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            self.cleanup_protective_orders(symbol, direction, position_mode)
            return
        self.market_close(symbol, direction, amt, position_mode)
        self.cleanup_protective_orders(symbol, direction, position_mode)

    def _emergency_close(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        if amt <= 0:
            self.logger.info(
                f"Emergency close: nothing to close on {symbol} {direction}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return
        self.market_close(symbol, direction, amt, position_mode)

    def do_take_profit(self, symbol: str, quantity: float, direction: str) -> None:
        position_mode = self.get_position_mode()
        if position_mode is None:
            self.logger.error(
                "Cannot resolve position mode — abort do_take_profit",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return
        amt, _, _, _ = self.get_position_size_and_sides(symbol, direction)
        close_qty = min(float(quantity), amt)
        if close_qty <= 0:
            self.logger.warning(
                f"do_take_profit skipped (have={amt}, want={quantity})",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return
        self.market_close(symbol, direction, close_qty, position_mode)


    def set_position_mode(self, mode: PositionMode) -> bool:
        """Switches the account's position mode. False when unsupported."""
        self.logger.warning(
            f"{self.BROKER_NAME} does not support switching position mode "
            "via API",
            extra={"broker": self.BROKER_NAME},
        )
        return False

    @abstractmethod
    def get_position_mode(self) -> Optional[PositionMode]: ...

    @abstractmethod
    def has_open_position(self, symbol: str, direction: str) -> bool: ...

    @abstractmethod
    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        ...

    @abstractmethod
    def set_isolated_margin(self, symbol: str) -> bool: ...

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool: ...

    @abstractmethod
    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[Any]: ...

    @abstractmethod
    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[Any]: ...

    @abstractmethod
    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None: ...

    @abstractmethod
    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[Any]: ...

    @abstractmethod
    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[Any]:

        ...

    @abstractmethod
    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:

        ...


    @staticmethod
    def clamp_take_profits(
        tps: List[Dict[str, Any]], full_quantity: float
    ) -> List[Dict[str, Any]]:

        remaining = abs(float(full_quantity))
        out: List[Dict[str, Any]] = []
        for tp in tps:
            if remaining <= 0:
                break
            qty = min(float(tp["quantity"]), remaining)
            if qty <= 0:
                continue
            out.append({"price": float(tp["price"]), "quantity": qty})
            remaining -= qty
        return out