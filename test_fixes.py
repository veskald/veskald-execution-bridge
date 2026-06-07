import os
import sys
import types
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# stubs
config_stub = types.ModuleType("config")
for k, v in {
    "HUB_URL": "", "MACHINE_TOKEN": "tok",
    "BINANCE_API_KEY": "x", "BINANCE_API_SECRET": "x",
    "BYBIT_API_KEY": "x", "BYBIT_API_SECRET": "x", "BYBIT_TESTNET": False,
    "KRAKEN_API_KEY": "x", "KRAKEN_API_SECRET": "x", "KRAKEN_SANDBOX": False,
    "UNIQUE_ID": "uid", "ENV_UNIQUE_ID": "", "LOCAL_UNIQUE_ID": "uid",
}.items():
    setattr(config_stub, k, v)
sys.modules["config"] = config_stub

bc_conf = types.ModuleType("binance_common.configuration")
bc_conf.ConfigurationRestAPI = lambda **kw: MagicMock()
bc_const = types.ModuleType("binance_common.constants")
bc_const.DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL = ""
bc_pkg = types.ModuleType("binance_common"); bc_pkg.configuration = bc_conf; bc_pkg.constants = bc_const
sdk_pkg = types.ModuleType("binance_sdk_derivatives_trading_usds_futures"); sdk_pkg.__path__ = []
sdk_sub = types.ModuleType("binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures")
class _FakeBinance:
    def __init__(self, *a, **kw): self.rest_api = MagicMock()
sdk_sub.DerivativesTradingUsdsFutures = _FakeBinance
sys.modules["binance_common"] = bc_pkg
sys.modules["binance_common.configuration"] = bc_conf
sys.modules["binance_common.constants"] = bc_const
sys.modules["binance_sdk_derivatives_trading_usds_futures"] = sdk_pkg
sys.modules["binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures"] = sdk_sub

# Чистим кеш модулей
for mod in list(sys.modules):
    if mod.startswith("lib"):
        del sys.modules[mod]

from lib.binance import VeskaldBinance, _classify

results: List[Tuple[str, bool, str]] = []
def check(name, cond, detail=""):
    results.append((name, cond, detail))


ge_text = "An open stop or take profit order with GTE and closePosition in the direction is existing."
check("classify GTE+closePosition by text → non_retryable",
      _classify(None, ge_text) == "non_retryable")

check("classify timeout by text → retryable",
      _classify(None, "Connection timeout occurred") == "retryable")

check("classify margin insufficient by text → non_retryable",
      _classify(None, "Margin is insufficient.") == "non_retryable")

check("classify reduceOnly rejected by text → non_retryable",
      _classify(None, "ReduceOnly Order is rejected.") == "non_retryable")

# Если есть код — он приоритетнее текста
check("classify code wins over text (-4046 → benign)",
      _classify(-4046, ge_text) == "benign")

check("classify -4061 still non_retryable",
      _classify(-4061, "") == "non_retryable")

check("classify None code, empty text → retryable (network)",
      _classify(None, "") == "retryable")

check("classify None code, unrecognized text → unknown (safer not to retry)",
      _classify(None, "some weird stuff") == "unknown")


def _algo_row(algo_id, side, position_side, order_type="STOP_MARKET",
              stop_price=100.0, close_position=True):
    r = MagicMock()
    r.algo_id = algo_id
    r.side = side
    r.position_side = position_side
    r.order_type = order_type
    r.stop_price = stop_price
    r.close_position = close_position
    return r


trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"

call_log: List[Tuple[str, dict]] = []

def make_safe_call(behaviors):

    def _safe(fn, retries=3, **params):
        name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", str(fn))
        for key, behavior in behaviors.items():
            if key in name:
                result = behavior(params)
                call_log.append((key, params))
                return result
        call_log.append((name, params))
        return None
    return _safe

def make_safe_call_meta(behaviors):
    def _safe(fn, retries=3, **params):
        name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", str(fn))
        for key, behavior in behaviors.items():
            if key in name:
                result = behavior(params)
                call_log.append((key, params))
                return (result, None) if result is not None else (None, -2011)
        call_log.append((name, params))
        return None, None
    return _safe


def setup_client(trader):
    trader.client.rest_api.current_all_algo_open_orders = MagicMock()
    trader.client.rest_api.current_all_algo_open_orders._mock_name = "current_all_algo_open_orders"
    trader.client.rest_api.cancel_algo_order = MagicMock()
    trader.client.rest_api.cancel_algo_order._mock_name = "cancel_algo_order"
    trader.client.rest_api.new_algo_order = MagicMock()
    trader.client.rest_api.new_algo_order._mock_name = "new_algo_order"
    trader.client.rest_api.position_information_v3 = MagicMock()
    trader.client.rest_api.position_information_v3._mock_name = "position_information_v3"
    trader.client.rest_api.new_order = MagicMock()
    trader.client.rest_api.new_order._mock_name = "new_order"


setup_client(trader)
call_log.clear()
old_row = _algo_row(algo_id=111, side="SELL", position_side="BOTH",
                    stop_price=90.0)
behaviors_a = {
    "current_all_algo_open_orders": lambda p: [old_row],
    "cancel_algo_order": lambda p: {"ok": True},
    "new_algo_order": lambda p: MagicMock(algo_id=999),
}
trader._safe_call = make_safe_call(behaviors_a)
trader._safe_call_with_meta = make_safe_call_meta(behaviors_a)

result = trader.move_trailing_stop("BTCUSDT", "LONG", 95.0)
check("Binance move_trailing happy: returns new id", result == 999, f"got {result}")


order = [c[0] for c in call_log]
list_idx = order.index("current_all_algo_open_orders")
cancel_idx = order.index("cancel_algo_order")
new_idx = order.index("new_algo_order")
check("Binance happy: list before cancel", list_idx < cancel_idx)
check("Binance happy: cancel before new", cancel_idx < new_idx)


new_count = sum(1 for c in order if c == "new_algo_order")
check("Binance happy: single new_algo_order", new_count == 1, f"got {new_count}")

cancel_calls = [c for c in call_log if c[0] == "cancel_algo_order"]
check("Binance happy: cancelled algoid=111",
      cancel_calls[0][1].get("algoid") == 111,
      f"got {cancel_calls[0][1]}")



trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"
setup_client(trader)
call_log.clear()

new_calls_count = {"n": 0}
def _new_algo_behavior(p):
    new_calls_count["n"] += 1
    if new_calls_count["n"] == 1:
        return None
    return MagicMock(algo_id=222)

behaviors_b = {
    "current_all_algo_open_orders": lambda p: [_algo_row(algo_id=111, side="SELL",
                                                          position_side="BOTH",
                                                          stop_price=90.0)],
    "cancel_algo_order": lambda p: {"ok": True},
    "new_algo_order": _new_algo_behavior,
}
trader._safe_call = make_safe_call(behaviors_b)
trader._safe_call_with_meta = make_safe_call_meta(behaviors_b)

result = trader.move_trailing_stop("BTCUSDT", "LONG", 95.0)
check("Binance move_trailing fail-then-restore: returns None", result is None)
new_calls = [c for c in call_log if c[0] == "new_algo_order"]
check("Binance fail-then-restore: 2 new_algo_order calls (new + restore)",
      len(new_calls) == 2, f"got {len(new_calls)}")

check("Binance restore: first new with new price 95.0",
      new_calls[0][1].get("trigger_price") == 95.0,
      f"got {new_calls[0][1].get('trigger_price')}")

check("Binance restore: second new with old price 90.0",
      new_calls[1][1].get("trigger_price") == 90.0,
      f"got {new_calls[1][1].get('trigger_price')}")



trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"
setup_client(trader)
call_log.clear()


def _all_fail(p):
    return None


new_order_calls = []
def _new_order_capture(p):
    new_order_calls.append(p)
    return MagicMock(order_id=42)

behaviors_c = {
    "current_all_algo_open_orders": lambda p: [_algo_row(algo_id=111, side="SELL",
                                                          position_side="BOTH",
                                                          stop_price=90.0)],
    "cancel_algo_order": lambda p: {"ok": True},
    "new_algo_order": _all_fail,
    "position_information_v3": lambda p: [
        type("R", (), {"position_side": "BOTH", "position_amt": "1.5",
                       "break_even_price": "100"})()
    ],
    "new_order": _new_order_capture,
}
trader._safe_call = make_safe_call(behaviors_c)
trader._safe_call_with_meta = make_safe_call_meta(behaviors_c)

result = trader.move_trailing_stop("BTCUSDT", "LONG", 95.0)
check("Binance both-fail: returns None", result is None)
check("Binance both-fail: emergency market_close called",
      len(new_order_calls) == 1, f"calls={len(new_order_calls)}")
if new_order_calls:
    p = new_order_calls[0]
    check("Binance both-fail: market_close side=SELL (closing LONG)",
          p["side"] == "SELL", f"got {p.get('side')}")
    check("Binance both-fail: market_close type=MARKET",
          p["type"] == "MARKET")
    check("Binance both-fail: close qty matches position size",
          p["quantity"] == 1.5)


trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"
setup_client(trader)
call_log.clear()

behaviors_d = {
    "current_all_algo_open_orders": lambda p: [_algo_row(algo_id=111, side="SELL",
                                                          position_side="BOTH",
                                                          stop_price=90.0)],
    "cancel_algo_order": lambda p: None,
    "new_algo_order": lambda p: MagicMock(algo_id=999),
}

def safe_meta_d(fn, retries=3, **params):
    name = getattr(fn, "_mock_name", None) or getattr(fn, "__name__", str(fn))
    if "cancel_algo_order" in name:
        call_log.append((name, params))
        return (None, -2011)
    if "current_all_algo_open_orders" in name:
        call_log.append((name, params))
        return ([_algo_row(111, "SELL", "BOTH", stop_price=90.0)], None)
    if "new_algo_order" in name:
        call_log.append((name, params))
        return (MagicMock(algo_id=999), None)
    return None, None

trader._safe_call = make_safe_call(behaviors_d)
trader._safe_call_with_meta = safe_meta_d

result = trader.move_trailing_stop("BTCUSDT", "LONG", 95.0)
check("Binance cancel-fail: returns None", result is None)
new_count = sum(1 for c in call_log if c[0] == "new_algo_order")
check("Binance cancel-fail: NO new_algo_order placed (would conflict)",
      new_count == 0, f"got {new_count}")


trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"
setup_client(trader)
call_log.clear()

behaviors_e = {
    "current_all_algo_open_orders": lambda p: [],  # ничего
    "new_algo_order": lambda p: MagicMock(algo_id=555),
}
trader._safe_call = make_safe_call(behaviors_e)
trader._safe_call_with_meta = make_safe_call_meta(behaviors_e)

result = trader.move_trailing_stop("BTCUSDT", "LONG", 95.0)
check("Binance no-old-SL: returns new id", result == 555, f"got {result}")
cancel_count = sum(1 for c in call_log if c[0] == "cancel_algo_order")
check("Binance no-old-SL: no cancel calls", cancel_count == 0)



trader = VeskaldBinance({})
trader._position_mode_cache = "ONE_WAY"
setup_client(trader)

mixed = [
    _algo_row(algo_id=1, side="SELL", position_side="BOTH",
              order_type="STOP_MARKET", stop_price=90.0, close_position=True),
    _algo_row(algo_id=2, side="SELL", position_side="BOTH",
              order_type="STOP_MARKET", stop_price=85.0, close_position=False),
    _algo_row(algo_id=3, side="SELL", position_side="BOTH",
              order_type="TAKE_PROFIT_MARKET", stop_price=120.0,
              close_position=True),
    _algo_row(algo_id=4, side="BUY", position_side="BOTH",  # обратная сторона
              order_type="STOP_MARKET", stop_price=110.0, close_position=True),
]
trader._safe_call = lambda fn, retries=3, **kw: mixed
snapshot = trader._snapshot_stop_orders("BTCUSDT", "SELL", "BOTH")
check("Snapshot returns 1 entry (STOP_MARKET + cp=true + same side/pos)",
      len(snapshot) == 1, f"got {len(snapshot)}: {snapshot}")
check("Snapshot has correct algo_id",
      snapshot[0]["algo_id"] == 1)
check("Snapshot has correct trigger_price",
      snapshot[0]["trigger_price"] == 90.0)



for mod in list(sys.modules):
    if mod.startswith("lib"):
        del sys.modules[mod]


import kraken.futures as kf
_real_market = kf.Market

class _SpyMarket:
    last_call = None
    def __init__(self, *a, **kw): pass
    def set_leverage_preference(self, **kw):
        _SpyMarket.last_call = kw
        return {"result": "success"}

kf.Market = _SpyMarket

class _StubTrade:
    def __init__(self, *a, **kw): pass

class _StubUser:
    def __init__(self, *a, **kw): pass

_real_trade = kf.Trade
_real_user = kf.User
kf.Trade = _StubTrade
kf.User = _StubUser

from lib.kraken import VeskaldKraken
kr = VeskaldKraken({})
kr._safe_call = lambda fn, retries=3, **kw: fn(**kw)
ok = kr.set_leverage("BTCUSDT", 10)
check("Kraken set_leverage returns True", ok is True)
check("Kraken set_leverage hits Market.set_leverage_preference",
      _SpyMarket.last_call is not None,
      f"last_call={_SpyMarket.last_call}")
check("Kraken set_leverage symbol PF_XBTUSD",
      _SpyMarket.last_call.get("symbol") == "PF_XBTUSD")
check("Kraken set_leverage maxLeverage=10",
      _SpyMarket.last_call.get("maxLeverage") == 10)

# Откат
kf.Market = _real_market
kf.Trade = _real_trade
kf.User = _real_user



VeskaldKraken._MARGIN_WARNING_LOGGED = False
import logging


warn_records = []
class _Capture(logging.Handler):
    def emit(self, record):
        if record.levelno == logging.WARNING:
            warn_records.append(record.getMessage())

cap = _Capture()
logging.getLogger("veskald_bridge").addHandler(cap)
try:
    kr2 = VeskaldKraken({})
    ok1 = kr2.set_isolated_margin("BTCUSDT")
    ok2 = kr2.set_isolated_margin("ETHUSDT")
    ok3 = kr2.set_isolated_margin("SOLUSDT")
    check("Kraken set_isolated_margin always True", ok1 and ok2 and ok3)
    margin_warns = [w for w in warn_records if "margin mode" in w.lower()]
    check("Kraken margin warn logged exactly once across 3 calls",
          len(margin_warns) == 1, f"got {len(margin_warns)}: {margin_warns}")
finally:
    logging.getLogger("veskald_bridge").removeHandler(cap)



total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{'='*70}")
print(f"Tests: {passed}/{total} passed")
print(f"{'='*70}\n")
for name, ok, detail in results:
    status = "✓" if ok else "✗"
    line = f"  {status} {name}"
    if not ok and detail:
        line += f"  [{detail}]"
    print(line)

sys.exit(0 if passed == total else 1)