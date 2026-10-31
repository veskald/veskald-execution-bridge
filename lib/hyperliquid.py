import time
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Set, Tuple

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL
from hyperliquid.utils.error import ClientError
from hyperliquid.utils.signing import Cloid

from config import (
    HYPERLIQUID_ACCOUNT_ADDRESS,
    HYPERLIQUID_PRIVATE_KEY,
    HYPERLIQUID_TESTNET,
)
from lib.base_trader import (
    BaseTrader, Direction, PositionMode, ProtectiveOrder, make_client_id,
)
from lib.symbols import to_exchange_symbol

# A cloid is 16 bytes of hex: a one-byte tag for the client id prefix, the
# client id's 16 hex chars and a zero tail that marks it as the bridge's own.
_CLOID_TAGS = {"open": "01", "sl": "02", "tp": "03", "close": "04"}
_CLOID_PREFIXES = {tag: prefix for prefix, tag in _CLOID_TAGS.items()}
_CLOID_PAD = "0" * 14

_SIDES = {"A": "SELL", "B": "BUY"}

# A trigger order's orderType is "<kind> Market" or "<kind> Limit".
_TRIGGER_KINDS = {"Stop": "sl", "Take Profit": "tp"}

# Worst fill a triggered SL/TP accepts, as a fraction of its trigger price.
_SLIPPAGE = 0.05


def to_cloid(client_id: str) -> Cloid:
    prefix, _, hex16 = client_id.partition("-")
    return Cloid(f"0x{_CLOID_TAGS[prefix]}{hex16}{_CLOID_PAD}")


def from_cloid(raw: Any) -> Optional[str]:
    """The bridge client id a cloid encodes, None for any other cloid."""
    raw = str(raw or "")
    if len(raw) != 34 or not raw.endswith(_CLOID_PAD):
        return None
    prefix = _CLOID_PREFIXES.get(raw[2:4])
    return f"{prefix}-{raw[4:20]}" if prefix else None


def _build_exchange() -> Exchange:
    wallet = Account.from_key(HYPERLIQUID_PRIVATE_KEY)
    url = TESTNET_API_URL if HYPERLIQUID_TESTNET else MAINNET_API_URL
    return Exchange(
        wallet, url, account_address=HYPERLIQUID_ACCOUNT_ADDRESS, timeout=30)


class VeskaldHyperliquid(BaseTrader):
    BROKER_NAME = "hyperliquid"

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.exchange = _build_exchange()
        self.info = self.exchange.info
        self.address = self.exchange.account_address

    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "hyperliquid")

    def _sz_decimals(self, coin: str) -> Optional[int]:
        try:
            asset = self.info.name_to_asset(coin)
        except KeyError:
            self.logger.error(
                f"Hyperliquid does not list {coin}",
                extra={"symbol": coin, "broker": self.BROKER_NAME},
            )
            return None
        return self.info.asset_to_sz_decimals[asset]

    def _sz(self, coin: str, qty: float) -> Optional[float]:
        decimals = self._sz_decimals(coin)
        if decimals is None:
            return None
        step = Decimal(1).scaleb(-decimals)
        return float(Decimal(str(qty)).quantize(step, rounding=ROUND_FLOOR))

    def _px(self, coin: str, price: float) -> Optional[float]:
        decimals = self._sz_decimals(coin)
        if decimals is None:
            return None
        # Hyperliquid tick rule: integer prices are always valid; otherwise
        # 5 significant figures, at most 6 - szDecimals decimals.
        if price >= 1e5:
            return float(round(price))
        return round(float(f"{price:.5g}"), 6 - decimals)

    def _position(self, coin: str) -> Optional[Dict[str, Any]]:
        """The coin's open position: {} when flat, None on API failure."""
        state = self._safe_call(self.info.user_state, address=self.address)
        if state is None:
            return None
        for entry in state["assetPositions"]:
            row = entry["position"]
            if row["coin"] == coin and float(row["szi"]) != 0:
                return row
        return {}

    def get_position_mode(self) -> Optional[PositionMode]:
        # Hyperliquid is one-way only; the request checks that the account is reachable.
        if self._position_mode_cache is None:
            if self._safe_call(self.info.user_state, address=self.address) is not None:
                self._position_mode_cache = "ONE_WAY"
        return self._position_mode_cache

    def _position_for(self, symbol: str, direction: str) -> Optional[Dict[str, Any]]:
        """The symbol's position if it runs in direction; {} otherwise, None on API failure."""
        row = self._position(self._ex_symbol(symbol))
        if row is None:
            return None
        same_side = self.position_direction(None, row.get("szi")) == direction.upper()
        return row if same_side else {}

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        return bool(self._position_for(symbol, direction))

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        row = self._position_for(symbol, direction) or {}
        size = abs(float(row.get("szi") or 0))
        entry_px = float(row.get("entryPx") or 0)
        return size, "BOTH", self.opposite_side(direction), entry_px

    def set_isolated_margin(self, symbol: str) -> bool:
        # set_leverage switches the coin to isolated margin in the same action.
        return True

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        return self._safe_call(
            self.exchange.update_leverage, retries=1,
            leverage=int(leverage), name=self._ex_symbol(symbol), is_cross=False,
        ) is not None

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        coin = self._ex_symbol(symbol)
        sz = self._sz(coin, quantity)
        if not sz:
            self.logger.error(
                f"Hyperliquid open_position: no tradable size for qty={quantity}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        return self._order_oid(self._safe_call(
            self.exchange.market_open, retries=0,
            name=coin, is_buy=direction.upper() == "LONG", sz=sz,
            cloid=to_cloid(make_client_id("open")),
        ))

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        return self._place_stop(symbol, stop_loss_price, direction)

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        coin = self._ex_symbol(symbol)
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            sz = self._sz(coin, tp["quantity"])
            if not sz:
                self.logger.warning(
                    f"Hyperliquid TP @ {tp['price']} skipped: no tradable size "
                    f"for qty={tp['quantity']}",
                    extra={"symbol": symbol, "broker": self.BROKER_NAME},
                )
                continue
            oid = self._place_trigger(coin, "tp", sz, tp["price"], direction)
            if oid is None:
                self.logger.error(
                    f"Hyperliquid TP @ {tp['price']} ({sz}) failed for {symbol}",
                    extra={"symbol": symbol, "broker": self.BROKER_NAME},
                )
            else:
                self.logger.info(
                    f"Hyperliquid TP @ {tp['price']} ({sz}) placed for {symbol} (id={oid})",
                    extra={"symbol": symbol, "broker": self.BROKER_NAME},
                )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:
        new_id = self._place_stop(symbol, price, direction)
        if new_id is None:
            self.logger.error(
                f"Hyperliquid failed to place new SL @ {price} — keeping old SL",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        self._cancel_protective(symbol, direction, {"sl"}, keep_order_id=new_id)
        return new_id

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        # The SDK takes the close side from the live position's sign, not from direction.
        row = self._position_for(symbol, direction)
        if not row:
            reason = "position state unreadable" if row is None else f"no {direction} position"
            self.logger.error(
                f"Hyperliquid market_close not sent: {reason}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        coin = self._ex_symbol(symbol)
        sz = self._sz(coin, quantity)
        # The SDK closes the whole position when sz is 0 or None.
        if not sz:
            self.logger.error(
                f"Hyperliquid market_close: no tradable size for qty={quantity}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        # A resent partial close whose first answer was lost closes a second chunk.
        retries = 0 if sz < abs(float(row["szi"])) else 2
        return self._order_oid(self._safe_call(
            self.exchange.market_close, retries=retries,
            coin=coin, sz=sz, cloid=to_cloid(make_client_id("close")),
        ))

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        self._cancel_protective(symbol, direction, {"sl", "tp"})

    def list_protective_orders(self) -> Optional[List[ProtectiveOrder]]:
        rows = self._safe_call(
            self.info.frontend_open_orders, retries=0, address=self.address)
        if rows is None:
            return None
        orders = (
            self.protective_order(
                r.get("oid"), from_cloid(r.get("cloid")), r.get("coin"),
                _SIDES.get(r.get("side")),
            )
            for r in rows
        )
        return [o for o in orders if o]

    def list_open_positions(self) -> Optional[Set[Tuple[str, Direction]]]:
        state = self._safe_call(self.info.user_state, address=self.address)
        if state is None:
            return None
        positions = (
            (p["position"]["coin"], self.position_direction(None, p["position"]["szi"]))
            for p in state["assetPositions"]
        )
        return {p for p in positions if p[1]}

    def cancel_protective_order(self, order: ProtectiveOrder) -> bool:
        return self._first_status(self._safe_call(
            self.exchange.cancel, retries=2, name=order.symbol, oid=int(order.order_id),
        )) == "success"

    def _place_stop(
        self, symbol: str, trigger_price: float, direction: str
    ) -> Optional[str]:
        row = self._position_for(symbol, direction)
        if not row:
            reason = "position state unreadable" if row is None else f"no {direction} position"
            self.logger.error(
                f"Hyperliquid SL @ {trigger_price} not placed: {reason}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        return self._place_trigger(
            self._ex_symbol(symbol), "sl", abs(float(row["szi"])), trigger_price, direction)

    def _place_trigger(
        self, coin: str, kind: str, sz: float, trigger_price: float, direction: str
    ) -> Optional[str]:
        """A reduce-only market SL or TP (kind) on the close side of direction."""
        px = self._px(coin, float(trigger_price))
        if px is None:
            return None
        is_buy = direction.upper() != "LONG"
        return self._order_oid(self._safe_call(
            self.exchange.order, retries=2,
            name=coin, is_buy=is_buy, sz=sz, limit_px=self._slip_px(coin, px, is_buy),
            order_type={"trigger": {"triggerPx": px, "isMarket": True, "tpsl": kind}},
            reduce_only=True, cloid=to_cloid(make_client_id(kind)),
        ))

    def _slip_px(self, coin: str, trigger: float, is_buy: bool) -> Optional[float]:
        return self._px(coin, trigger * (1 + _SLIPPAGE if is_buy else 1 - _SLIPPAGE))

    def _cancel_protective(
        self, symbol: str, direction: str, kinds: Set[str],
        keep_order_id: Optional[str] = None,
    ) -> None:
        """Cancels this side's trigger orders of kinds ("sl", "tp"), whoever placed them."""
        coin = self._ex_symbol(symbol)
        close_side = "A" if direction.upper() == "LONG" else "B"
        rows = self._safe_call(
            self.info.frontend_open_orders, retries=0, address=self.address) or []
        for row in rows:
            kind = _TRIGGER_KINDS.get(str(row.get("orderType") or "").rpartition(" ")[0])
            if (row.get("coin") == coin and row.get("side") == close_side
                    and kind in kinds and str(row.get("oid")) != keep_order_id):
                self._first_status(self._safe_call(
                    self.exchange.cancel, retries=2, name=coin, oid=int(row["oid"])))

    def _safe_call(self, fn, retries: int = 3, **params) -> Optional[Any]:
        name = getattr(fn, "__name__", repr(fn))
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
            except ClientError as e:
                self.logger.error(
                    f"Hyperliquid rejected {name}: [{e.status_code}] {e.error_message}",
                    extra={"params": params, "broker": self.BROKER_NAME},
                )
                return None
            except Exception as e:
                self.logger.error(
                    f"Hyperliquid {name} failed: {e!r}",
                    extra={"attempt": attempt + 1, "broker": self.BROKER_NAME},
                    exc_info=True,
                )
                if attempt < retries:
                    time.sleep(min(0.5 * 2 ** attempt, 5.0))
                continue
            # Info answers have no status; the SDK answers a non-JSON body with "error".
            if isinstance(resp, dict) and (
                    resp.get("status", "ok") != "ok" or "error" in resp):
                reason = resp.get("response") or resp.get("error") or resp
                self.logger.error(
                    f"Hyperliquid error in {name}: {reason}",
                    extra={"params": params, "broker": self.BROKER_NAME},
                )
                return None
            return resp
        return None

    def _first_status(self, resp: Any) -> Optional[Any]:
        if resp is None:
            return None
        try:
            status = resp["response"]["data"]["statuses"][0]
        except (KeyError, IndexError, TypeError):
            self.logger.error(
                f"Hyperliquid unexpected answer: {resp}",
                extra={"response": resp, "broker": self.BROKER_NAME},
            )
            return None
        if isinstance(status, dict) and "error" in status:
            self.logger.error(
                f"Hyperliquid order rejected: {status['error']}",
                extra={"broker": self.BROKER_NAME},
            )
            return None
        return status

    def _order_oid(self, resp: Any) -> Optional[str]:
        status = self._first_status(resp)
        if not isinstance(status, dict):
            return None
        placed = status.get("resting") or status.get("filled")
        return str(placed["oid"]) if placed else None
