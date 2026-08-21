import base64
import hashlib
import hmac
import json
import sys
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from config import (
    KUCOIN_API_KEY,
    KUCOIN_API_PASSPHRASE,
    KUCOIN_API_SECRET,
)
from lib.base_trader import (
    BaseTrader, Direction, PositionMode, make_client_id,
)
from lib.symbols import to_exchange_symbol

# KuCoin broker (partner) tag and key. Normally they arrive with the signal;
# hardcoded fallbacks below. KuCoin issues separate tags per market — this
# adapter is Futures-only, so the Futures tag is the fallback. The key signs
# KC-API-PARTNER-SIGN — without it KuCoin does not attribute the tag.
DEFAULT_BROKER_TAG = ""
DEFAULT_BROKER_KEY = ""

_BROKER_TAG_KEYS = ("broker_tag", "brokertag", "brokerTag")
_BROKER_KEY_KEYS = ("broker_key", "brokerkey", "brokerKey")


def _from_signal(data: Dict[str, Any], keys: Tuple[str, ...], default: str) -> str:
    for key in keys:
        value = (data or {}).get(key)
        if value:
            return str(value).strip()
    return default


def resolve_broker_tag(data: Dict[str, Any]) -> str:
    return _from_signal(data, _BROKER_TAG_KEYS, DEFAULT_BROKER_TAG)


def resolve_broker_key(data: Dict[str, Any]) -> str:
    return _from_signal(data, _BROKER_KEY_KEYS, DEFAULT_BROKER_KEY)


_BENIGN_TEXTS = (
    "not modified",
    "no need to change",
    "no change",
    "already exist",
)
_NON_RETRYABLE_TEXTS = (
    "insufficient",
    "invalid",
    "minimum",
    "maximum",
    "exceed",
    "not exist",
    "parameter",
    "rejected",
    "not allowed",
    "forbidden",
    "risk limit",
    "size below",
    "lot size",
    "tick size",
    "unavailable",
)
_RETRYABLE_TEXTS = (
    "timeout",
    "too many requests",
    "system busy",
    "server error",
    "service unavailable",
    "try again",
    "network",
)
_RETRYABLE_CODES = {"429000", "500000"}


def _classify(code: Optional[str], text: str = "") -> str:
    if code == "200000":
        return "ok"
    if code in _RETRYABLE_CODES:
        return "retryable"
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
    return "unknown"


def _fmt_price(price: float) -> str:
    # str() renders small prices in scientific notation — KuCoin rejects it.
    s = format(Decimal(str(price)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


class _KucoinFuturesClient:
    """Thin REST client for api-futures.kucoin.com with v2 signing and
    the KC-API-PARTNER(-SIGN) partner headers."""

    BASE_URL = "https://api-futures.kucoin.com"

    def __init__(
        self,
        key: str,
        secret: str,
        passphrase: str,
        broker_tag: str = "",
        broker_key: str = "",
    ):
        self.key = key or ""
        self.secret = (secret or "").encode()
        self.passphrase = passphrase or ""
        self.broker_tag = broker_tag or ""
        self.broker_key = (broker_key or "").encode()
        self.session = requests.Session()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, body=body)

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("DELETE", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        endpoint = f"{path}?{urlencode(params)}" if params else path
        payload = json.dumps(body) if body is not None else ""
        headers = self._headers(method, endpoint, payload)
        # TEMPORARY: raw header dump for broker-integration debugging,
        # remove once verified.
        resp = self.session.request(
            method,
            self.BASE_URL + endpoint,
            data=payload if body is not None else None,
            headers=headers,
            timeout=30,
        )
        try:
            return resp.json()
        except ValueError:
            return {"code": str(resp.status_code), "msg": resp.text[:200]}

    def _headers(self, method: str, endpoint: str, payload: str) -> Dict[str, str]:
        ts = str(int(time.time() * 1000))
        sign = base64.b64encode(
            hmac.new(
                self.secret, (ts + method + endpoint + payload).encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        passphrase = base64.b64encode(
            hmac.new(self.secret, self.passphrase.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "KC-API-KEY": self.key,
            "KC-API-SIGN": sign,
            "KC-API-TIMESTAMP": ts,
            "KC-API-PASSPHRASE": passphrase,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json",
        }
        # KuCoin only accepts the tag when paired with a broker-key signature.
        # The broker name KuCoin issued to us equals the tag.
        if self.broker_tag and self.broker_key:
            partner_sign = base64.b64encode(
                hmac.new(
                    self.broker_key, (ts + self.broker_tag + self.key).encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            headers["KC-API-PARTNER"] = self.broker_tag
            headers["KC-API-PARTNER-SIGN"] = partner_sign
            headers["KC-API-PARTNER-VERIFY"] = "true"
            headers["KC-BROKER-NAME"] = self.broker_tag
        return headers


class VeskaldKucoin(BaseTrader):
    BROKER_NAME = "kucoin"

    _PARTNER_WARNING_LOGGED: bool = False

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        self.broker_tag = resolve_broker_tag(self.action_data)
        self.broker_key = resolve_broker_key(self.action_data)
        tag_src = "signal" if any(
            self.action_data.get(k) for k in _BROKER_TAG_KEYS) else "default"
        key_src = "signal" if any(
            self.action_data.get(k) for k in _BROKER_KEY_KEYS) else "default"
        # Plain print on purpose: the logging pipeline masks secrets, and this
        # debug line must show the real values. Console/docker logs only;
        # stdout is None in the windowed desktop build.
        if not self.broker_key and not VeskaldKucoin._PARTNER_WARNING_LOGGED:
            self.logger.warning(
                "KuCoin broker key missing — orders go out without the "
                "partner headers.",
                extra={"broker": self.BROKER_NAME},
            )
            VeskaldKucoin._PARTNER_WARNING_LOGGED = True
        self._client = _KucoinFuturesClient(
            KUCOIN_API_KEY,
            KUCOIN_API_SECRET,
            KUCOIN_API_PASSPHRASE,
            broker_tag=self.broker_tag,
            broker_key=self.broker_key,
        )
        self._multiplier_cache: Dict[str, float] = {}
        self._leverage: Dict[str, int] = {}

    @staticmethod
    def _ex_symbol(symbol: str) -> str:
        return to_exchange_symbol(symbol, "kucoin")

    @staticmethod
    def _kucoin_side(direction: str) -> str:
        return "buy" if direction.upper() == "LONG" else "sell"

    @staticmethod
    def _close_side(direction: str) -> str:
        return "sell" if direction.upper() == "LONG" else "buy"

    @staticmethod
    def _sl_stop(direction: str) -> str:
        # A LONG stop-loss triggers on falling price.
        return "down" if direction.upper() == "LONG" else "up"

    @staticmethod
    def _tp_stop(direction: str) -> str:
        return "up" if direction.upper() == "LONG" else "down"

    def _multiplier(self, symbol_ex: str) -> float:
        if symbol_ex in self._multiplier_cache:
            return self._multiplier_cache[symbol_ex]
        resp = self._safe_call(
            self._client.get, path=f"/api/v1/contracts/{symbol_ex}",
        )
        data = self._data(resp)
        try:
            mult = float(data.get("multiplier", 1) or 1)
        except (TypeError, ValueError):
            mult = 1.0
        if mult <= 0:
            mult = 1.0
        self._multiplier_cache[symbol_ex] = mult
        return mult

    def _coin_qty_to_contracts(self, symbol_ex: str, coin_qty: float) -> int:
        mult = self._multiplier(symbol_ex)
        contracts = Decimal(str(coin_qty)) / Decimal(str(mult))
        # KuCoin expects a whole number of contracts; round down.
        return max(int(contracts), 0)

    def _contracts_to_coin_qty(self, symbol_ex: str, contracts: float) -> float:
        mult = self._multiplier(symbol_ex)
        return float(Decimal(str(contracts)) * Decimal(str(mult)))

    def get_position_mode(self) -> Optional[PositionMode]:
        if self._position_mode_cache is not None:
            return self._position_mode_cache
        resp = self._safe_call(
            self._client.get, path="/api/v2/position/getPositionMode",
        )
        if resp is None:
            return None
        mode = str(self._data(resp).get("positionMode", 0))
        self._position_mode_cache = "HEDGE" if mode == "1" else "ONE_WAY"
        return self._position_mode_cache

    def set_position_mode(self, mode: PositionMode) -> bool:
        ok, err = self._safe_call_with_meta(
            self._client.post, retries=1,
            path="/api/v2/position/switchPositionMode",
            body={"positionMode": "1" if mode == "HEDGE" else "0"},
        )
        if ok is not None or (err and "not modified" in err.lower()):
            self._position_mode_cache = None
            return True
        return False

    def _get_position_row(
        self, symbol_ex: str, direction: str
    ) -> Optional[Dict[str, Any]]:
        """Position row for the direction: {} when flat, None on API failure.

        Uses the list endpoint — in hedge mode a symbol can have two rows
        (positionSide LONG and SHORT) and the single-position endpoint
        cannot disambiguate them.
        """
        resp = self._safe_call(self._client.get, path="/api/v1/positions")
        if resp is None:
            return None
        hedge = self.get_position_mode() == "HEDGE"
        want = direction.upper()
        for row in self._data_list(resp):
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol", "")) != symbol_ex:
                continue
            qty = float(row.get("currentQty", 0) or 0)
            if qty == 0:
                continue
            if hedge:
                if str(row.get("positionSide", "")).upper() == want:
                    return row
            elif (want == "LONG") == (qty > 0):
                return row
        return {}

    def has_open_position(self, symbol: str, direction: str) -> bool:
        if direction is None:
            raise ValueError("direction is required")
        return bool(self._get_position_row(self._ex_symbol(symbol), direction))

    def get_position_size_and_sides(
        self, symbol: str, direction: str
    ) -> Tuple[float, str, str, float]:
        ex_sym = self._ex_symbol(symbol)
        row = self._get_position_row(ex_sym, direction) or {}
        amt_contracts = abs(float(row.get("currentQty", 0) or 0))
        be = float(row.get("avgEntryPrice", 0) or 0)
        amt_coins = self._contracts_to_coin_qty(ex_sym, amt_contracts)
        pos_side = (
            direction.upper()
            if self.get_position_mode() == "HEDGE" else "BOTH"
        )
        return amt_coins, pos_side, self._close_side(direction), be

    _MARGIN_WARNING_LOGGED: bool = False

    def set_isolated_margin(self, symbol: str) -> bool:
        ok = self._safe_call(
            self._client.post, retries=1,
            path="/api/v2/position/changeMarginMode",
            body={"symbol": self._ex_symbol(symbol), "marginMode": "ISOLATED"},
        )
        if ok is None and not VeskaldKucoin._MARGIN_WARNING_LOGGED:
            self.logger.warning(
                "Could not switch KuCoin margin mode to ISOLATED — "
                "check it in the KuCoin UI.",
                extra={"broker": self.BROKER_NAME, "symbol": symbol},
            )
            VeskaldKucoin._MARGIN_WARNING_LOGGED = True
        return True

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        # KuCoin applies leverage per order (isolated); there is no
        # separate API call for it.
        self._leverage[self._ex_symbol(symbol)] = int(leverage)
        return True

    def open_position(
        self, symbol: str, position_mode: PositionMode,
        quantity: float, direction: str,
    ) -> Optional[str]:
        ex_sym = self._ex_symbol(symbol)
        size = self._coin_qty_to_contracts(ex_sym, float(quantity))
        if size <= 0:
            self.logger.error(
                f"KuCoin open_position: contracts size <= 0 (qty={quantity}, "
                f"multiplier={self._multiplier(ex_sym)})",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None

        params = {
            "clientOid": make_client_id("open"),
            "side": self._kucoin_side(direction),
            "symbol": ex_sym,
            "type": "market",
            "size": size,
            "leverage": self._leverage.get(ex_sym, 1),
            "marginMode": "ISOLATED",
        }
        if position_mode == "HEDGE":
            params["positionSide"] = direction.upper()
        resp = self._safe_call(
            self._client.post, retries=0, path="/api/v1/orders", body=params,
        )
        order_id = self._data(resp).get("orderId") if resp else None
        return str(order_id) if order_id else None

    def set_stop_loss_price(
        self, symbol: str, stop_loss_price: float,
        direction: Direction, position_mode: PositionMode,
    ) -> Optional[str]:
        return self._place_stop(
            symbol=symbol, trigger_price=float(stop_loss_price),
            direction=direction, position_mode=position_mode,
        )

    def place_take_profits(
        self, symbol: str, take_profits: List[Dict[str, Any]],
        direction: str, position_mode: PositionMode,
        full_position_quantity: float,
    ) -> None:
        ex_sym = self._ex_symbol(symbol)
        for tp in self.clamp_take_profits(take_profits, full_position_quantity):
            size = self._coin_qty_to_contracts(ex_sym, float(tp["quantity"]))
            if size <= 0:
                continue
            params = {
                "clientOid": make_client_id("tp"),
                "side": self._close_side(direction),
                "symbol": ex_sym,
                "type": "market",
                "stop": self._tp_stop(direction),
                "stopPrice": _fmt_price(tp["price"]),
                "stopPriceType": "MP",
                "size": size,
                "reduceOnly": True,
            }
            if position_mode == "HEDGE":
                params["positionSide"] = direction.upper()
            self._safe_call(
                self._client.post, retries=2, path="/api/v1/orders", body=params,
            )
            self.logger.info(
                f"KuCoin TP @ {tp['price']} ({tp['quantity']}, {size}c) "
                f"placed for {symbol}",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )

    def move_trailing_stop(
        self, symbol: str, direction: str, price: float
    ) -> Optional[str]:
        position_mode = self.get_position_mode()
        if position_mode is None:
            return None
        new_id = self._place_stop(
            symbol=symbol, trigger_price=float(price), direction=direction,
            position_mode=position_mode,
        )
        if new_id is None:
            self.logger.error(
                f"KuCoin failed to place new SL @ {price} — keeping old SL",
                extra={"symbol": symbol, "broker": self.BROKER_NAME},
            )
            return None
        self._cancel_stop_orders(
            symbol=symbol, direction=direction, keep_order_id=new_id,
        )
        return new_id

    def market_close(
        self, symbol: str, direction: str, quantity: float,
        position_mode: PositionMode,
    ) -> Optional[str]:
        ex_sym = self._ex_symbol(symbol)
        size = self._coin_qty_to_contracts(ex_sym, float(quantity))
        if size <= 0:
            return None
        params = {
            "clientOid": make_client_id("close"),
            "side": self._close_side(direction),
            "symbol": ex_sym,
            "type": "market",
            "size": size,
            "reduceOnly": True,
        }
        if position_mode == "HEDGE":
            params["positionSide"] = direction.upper()
        resp = self._safe_call(
            self._client.post, retries=2, path="/api/v1/orders", body=params,
        )
        order_id = self._data(resp).get("orderId") if resp else None
        return str(order_id) if order_id else None

    def cleanup_protective_orders(
        self, symbol: str, direction: str, position_mode: PositionMode
    ) -> None:
        if position_mode == "HEDGE":
            # Deleting all stops for the symbol would also kill the opposite
            # position's protection — cancel only this side's orders.
            self._cancel_stop_orders(
                symbol=symbol, direction=direction, include_tp=True,
            )
            return
        self._safe_call(
            self._client.delete, retries=2, path="/api/v1/stopOrders",
            params={"symbol": self._ex_symbol(symbol)},
        )

    def _place_stop(
        self, symbol: str, trigger_price: float, direction: str,
        position_mode: PositionMode,
    ) -> Optional[str]:
        # closeOrder=True closes whatever remains of the position on trigger.
        params = {
            "clientOid": make_client_id("sl"),
            "side": self._close_side(direction),
            "symbol": self._ex_symbol(symbol),
            "type": "market",
            "stop": self._sl_stop(direction),
            "stopPrice": _fmt_price(trigger_price),
            "stopPriceType": "MP",
            "closeOrder": True,
        }
        if position_mode == "HEDGE":
            params["positionSide"] = direction.upper()
        resp = self._safe_call(
            self._client.post, retries=2, path="/api/v1/orders", body=params,
        )
        order_id = self._data(resp).get("orderId") if resp else None
        return str(order_id) if order_id else None

    def _cancel_stop_orders(
        self, symbol: str, direction: str,
        keep_order_id: Optional[str] = None,
        include_tp: bool = False,
    ) -> None:
        ex_sym = self._ex_symbol(symbol)
        resp = self._safe_call(
            self._client.get, path="/api/v1/stopOrders",
            params={"symbol": ex_sym, "pageSize": 50},
        )
        items = self._data(resp).get("items") or [] if resp else []
        close_side = self._close_side(direction)
        # This position's protective orders share its close side; the stop
        # trigger direction separates its SL from its TP.
        wanted_stops = {self._sl_stop(direction)}
        if include_tp:
            wanted_stops.add(self._tp_stop(direction))
        for o in items:
            if not isinstance(o, dict):
                continue
            if str(o.get("symbol", "")) != ex_sym:
                continue
            if str(o.get("side", "")).lower() != close_side:
                continue
            if str(o.get("stop", "")).lower() not in wanted_stops:
                continue
            order_id = o.get("id")
            if not order_id:
                continue
            if keep_order_id and str(order_id) == str(keep_order_id):
                continue
            self._safe_call(
                self._client.delete, retries=2, path=f"/api/v1/orders/{order_id}",
            )

    @staticmethod
    def _data(resp: Any) -> Dict[str, Any]:
        if isinstance(resp, dict):
            d = resp.get("data")
            if isinstance(d, dict):
                return d
        return {}

    @staticmethod
    def _data_list(resp: Any) -> List[Dict[str, Any]]:
        if isinstance(resp, dict):
            d = resp.get("data")
            if isinstance(d, list):
                return d
        return []

    def _safe_call(self, fn, retries: int = 3, **params) -> Any:
        ok, _ = self._safe_call_with_meta(fn, retries=retries, **params)
        return ok

    def _safe_call_with_meta(
        self, fn, retries: int = 3, **params
    ) -> Tuple[Any, Optional[str]]:
        path = params.get("path") or getattr(fn, "__name__", repr(fn))
        last_text: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                resp = fn(**params)
                if isinstance(resp, dict):
                    code = str(resp.get("code", ""))
                    if code == "200000":
                        return resp, None
                    msg = str(resp.get("msg", ""))
                    last_text = msg or code
                    kind = _classify(code, msg)
                    if kind == "benign":
                        self.logger.info(
                            f"KuCoin benign in {path}: [{code}] {msg}",
                            extra={"broker": self.BROKER_NAME},
                        )
                        return None, last_text
                    self.logger.error(
                        f"KuCoin API error in {path}: [{code}] {msg}",
                        extra={"params": params, "kind": kind,
                               "attempt": attempt + 1,
                               "broker": self.BROKER_NAME},
                    )
                    if kind == "non_retryable":
                        return None, last_text
                else:
                    return resp, None
            except Exception as e:
                last_text = str(e)
                self.logger.error(
                    f"KuCoin transport error in {path}: {e}",
                    extra={"attempt": attempt + 1, "broker": self.BROKER_NAME},
                    exc_info=True,
                )
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 5.0))
                continue
            return None, last_text
        return None, last_text
