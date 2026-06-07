import os
import sys
import types
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


config_stub = types.ModuleType("config")
for k, v in {
    "HUB_URL": "", "MACHINE_TOKEN": "tok",
    "BINANCE_API_KEY": "x", "BINANCE_API_SECRET": "x",
    "BYBIT_API_KEY": "x", "BYBIT_API_SECRET": "x", "BYBIT_TESTNET": False,
    "KRAKEN_API_KEY": "x", "KRAKEN_API_SECRET": "x", "KRAKEN_SANDBOX": False,
    "OKX_API_KEY": "x", "OKX_API_SECRET": "x", "OKX_API_PASSPHRASE": "x",
    "OKX_DEMO": False, "OKX_DEFAULT_ISOLATED": False,
    "COINBASE_API_KEY": "x", "COINBASE_API_SECRET": "x",
    "COINBASE_INTX_PORTFOLIO_UUID": "",
    "UNIQUE_ID": "uid", "ENV_UNIQUE_ID": "", "LOCAL_UNIQUE_ID": "uid",
}.items():
    setattr(config_stub, k, v)

def _has_creds_stub(broker: str) -> bool:
    override = getattr(config_stub, "HAS_CREDS_OVERRIDE", None)
    if override is not None:
        return override.get(broker.lower(), True)
    return True

config_stub.has_credentials = _has_creds_stub
sys.modules["config"] = config_stub

# Binance SDK
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


for mod in list(sys.modules):
    if mod.startswith("lib"):
        del sys.modules[mod]

from lib.symbols import to_exchange_symbol, from_exchange_symbol
from lib.base_trader import BaseTrader, make_client_id
from lib.trader_factory import build_trader, _normalize_broker, SUPPORTED_BROKERS

results: List[Tuple[str, bool, str]] = []
def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))



check("symbols binance: BTCUSDT", to_exchange_symbol("BTCUSDT", "binance") == "BTCUSDT")
check("symbols bybit: BTCUSDT", to_exchange_symbol("BTCUSDT", "bybit") == "BTCUSDT")
check("symbols kraken: BTCUSDT → PF_XBTUSD", to_exchange_symbol("BTCUSDT", "kraken") == "PF_XBTUSD")
check("symbols kraken: ETHUSDT → PF_ETHUSD", to_exchange_symbol("ETHUSDT", "kraken") == "PF_ETHUSD")
check("symbols kraken: SOLUSDT → PF_SOLUSD", to_exchange_symbol("SOLUSDT", "kraken") == "PF_SOLUSD")

check("symbols okx: BTCUSDT → BTC-USDT-SWAP",
      to_exchange_symbol("BTCUSDT", "okx") == "BTC-USDT-SWAP")
check("symbols okx: ETHUSDT → ETH-USDT-SWAP",
      to_exchange_symbol("ETHUSDT", "okx") == "ETH-USDT-SWAP")
check("symbols okx: BTCUSDC → BTC-USDC-SWAP",
      to_exchange_symbol("BTCUSDC", "okx") == "BTC-USDC-SWAP")

check("symbols coinbase: BTCUSDT → BTC-PERP-INTX",
      to_exchange_symbol("BTCUSDT", "coinbase") == "BTC-PERP-INTX")
check("symbols coinbase: ETHUSDT → ETH-PERP-INTX",
      to_exchange_symbol("ETHUSDT", "coinbase") == "ETH-PERP-INTX")
check("symbols coinbase: SOLUSDT → SOL-PERP-INTX",
      to_exchange_symbol("SOLUSDT", "coinbase") == "SOL-PERP-INTX")
check("symbols coinbase: lower input ok",
      to_exchange_symbol("btcusdt", "coinbase") == "BTC-PERP-INTX")

# Reverse
check("symbols okx back: BTC-USDT-SWAP → BTCUSDT",
      from_exchange_symbol("BTC-USDT-SWAP", "okx") == "BTCUSDT")
check("symbols coinbase back: BTC-PERP-INTX → BTCUSDT",
      from_exchange_symbol("BTC-PERP-INTX", "coinbase") == "BTCUSDT")
check("symbols kraken back: PF_XBTUSD → BTCUSDT",
      from_exchange_symbol("PF_XBTUSD", "kraken") == "BTCUSDT")

# Errors
try:
    to_exchange_symbol("BTC", "okx")
    check("symbols okx invalid raises", False)
except ValueError:
    check("symbols okx invalid raises", True)

check("normalize 'okx'", _normalize_broker("okx") == "okx")
check("normalize 'OKX'", _normalize_broker("OKX") == "okx")
check("normalize 'okex' alias", _normalize_broker("okex") == "okx")
check("normalize 'okx-v5' alias", _normalize_broker("okx-v5") == "okx")
check("normalize 'coinbase'", _normalize_broker("coinbase") == "coinbase")
check("normalize 'cb-advanced'", _normalize_broker("cb-advanced") == "coinbase")
check("normalize 'coinbase-advanced'", _normalize_broker("coinbase-advanced") == "coinbase")

check("SUPPORTED_BROKERS includes all 5",
      set(SUPPORTED_BROKERS) == {"binance", "bybit", "kraken", "okx", "coinbase"})

# Factory builds all 5
for b in SUPPORTED_BROKERS:
    t = build_trader({"broker": b})
    expected = {"binance": "VeskaldBinance", "bybit": "VeskaldBybit",
                "kraken": "VeskaldKraken", "okx": "VeskaldOkx",
                "coinbase": "VeskaldCoinbase"}[b]
    check(f"factory builds {expected}", t.__class__.__name__ == expected)



from lib.okx import VeskaldOkx, _classify as _okx_classify

check("OKX side LONG → buy", VeskaldOkx._okx_side("LONG") == "buy")
check("OKX side SHORT → sell", VeskaldOkx._okx_side("SHORT") == "sell")
check("OKX close LONG → sell", VeskaldOkx._close_side("LONG") == "sell")
check("OKX pos_side ONE_WAY → net",
      VeskaldOkx._pos_side("LONG", "ONE_WAY") == "net")
check("OKX pos_side HEDGE LONG → long",
      VeskaldOkx._pos_side("LONG", "HEDGE") == "long")
check("OKX pos_side HEDGE SHORT → short",
      VeskaldOkx._pos_side("SHORT", "HEDGE") == "short")
check("OKX symbol BTCUSDT → BTC-USDT-SWAP",
      VeskaldOkx._ex_symbol("BTCUSDT") == "BTC-USDT-SWAP")

# Classify: code "0" = ok
check("OKX classify code='0' ok", _okx_classify("0", "") == "ok")
check("OKX classify benign 'leverage not modified'",
      _okx_classify("51016", "Leverage not modified") == "benign")
check("OKX classify non_retryable 'insufficient'",
      _okx_classify("51008", "Order placement failed: insufficient balance") == "non_retryable")
check("OKX classify retryable 'rate limit'",
      _okx_classify("50011", "Rate limit reached") == "retryable")


trader_okx = build_trader({"broker": "okx"})
trader_okx._ct_val_cache["BTC-USDT-SWAP"] = 0.01  # 1 контракт = 0.01 BTC
check("OKX 1 BTC → 100 contracts",
      trader_okx._coin_qty_to_contracts("BTC-USDT-SWAP", 1.0) == "100")
check("OKX 0.05 BTC → 5 contracts",
      trader_okx._coin_qty_to_contracts("BTC-USDT-SWAP", 0.05) == "5")
check("OKX 0.005 BTC → 0 contracts (rounds down)",
      trader_okx._coin_qty_to_contracts("BTC-USDT-SWAP", 0.005) == "0")
check("OKX contracts 100 → 1.0 BTC",
      abs(trader_okx._contracts_to_coin_qty("BTC-USDT-SWAP", 100) - 1.0) < 1e-9)
check("OKX contracts 5 → 0.05 BTC",
      abs(trader_okx._contracts_to_coin_qty("BTC-USDT-SWAP", 5) - 0.05) < 1e-9)



from lib.coinbase import VeskaldCoinbase, _classify as _cb_classify

check("Coinbase side LONG → BUY", VeskaldCoinbase._coinbase_side("LONG") == "BUY")
check("Coinbase side SHORT → SELL", VeskaldCoinbase._coinbase_side("SHORT") == "SELL")
check("Coinbase close LONG → SELL", VeskaldCoinbase._close_side("LONG") == "SELL")
check("Coinbase always ONE_WAY", build_trader({"broker": "coinbase"}).get_position_mode() == "ONE_WAY")
check("Coinbase symbol BTCUSDT → BTC-PERP-INTX",
      VeskaldCoinbase._ex_symbol("BTCUSDT") == "BTC-PERP-INTX")

check("Coinbase classify benign 'no change'",
      _cb_classify("Setting has no change") == "benign")
check("Coinbase classify non_retryable 'insufficient'",
      _cb_classify("Insufficient funds for order") == "non_retryable")
check("Coinbase classify retryable 'timeout'",
      _cb_classify("Request timeout") == "retryable")



class _FakeOkxTrader(VeskaldOkx):
    def __init__(self, data):
        super().__init__(data)
        self._calls = []
        self._mode = "ONE_WAY"
        self._has_position = False
        self._position_size = 0.0
        # Подложим cache контракта чтобы не звать public API
        self._ct_val_cache["BTC-USDT-SWAP"] = 0.01

    def get_position_mode(self): return self._mode
    def has_open_position(self, sym, dir): return self._has_position
    def get_position_size_and_sides(self, sym, dir):
        return (self._position_size, self._pos_side(dir, self._mode),
                self._close_side(dir), 100.0)
    def set_isolated_margin(self, sym):
        self._calls.append(("set_isolated_margin", sym)); return True
    def set_leverage(self, sym, lev):
        self._calls.append(("set_leverage", sym, lev)); return True
    def open_position(self, sym, mode, qty, dir):
        self._calls.append(("open_position", sym, mode, qty, dir)); return "okx-001"
    def set_stop_loss_price(self, sym, sl, dir, mode):
        self._calls.append(("set_sl", sym, sl)); return f"sl-{sym}"
    def place_take_profits(self, sym, tps, dir, mode, qty):
        self._calls.append(("place_tp", sym, len(tps)))
    def move_trailing_stop(self, sym, dir, price):
        self._calls.append(("move_sl", sym, dir, price)); return f"sl-{price}"
    def market_close(self, sym, dir, qty, mode):
        self._calls.append(("close", sym, dir, qty)); return "close-okx"
    def cleanup_protective_orders(self, sym, dir, mode):
        self._calls.append(("cleanup", sym, dir))


data_open = {
    "broker": "okx", "action": "OPEN_POSITION", "symbol": "BTCUSDT",
    "direction": "LONG",
    "position": {"position": 0.05, "leverage": 10, "sl": 95000.0, "take_profits": []},
    "strategy": 1,
}
t = _FakeOkxTrader(data_open)
result = t.execute_action()
check("OKX OPEN returns order id", result == "okx-001")
called = [c[0] for c in t._calls]
check("OKX OPEN: open_position called", "open_position" in called)
check("OKX OPEN: set_sl called", "set_sl" in called)

t = _FakeOkxTrader(data_open)
t._has_position = True
result = t.execute_action()
check("OKX OPEN skipped if exists", result is None)


class _OkxFailSl(_FakeOkxTrader):
    def set_stop_loss_price(self, sym, sl, dir, mode):
        return None  # FAIL
t = _OkxFailSl(data_open)
t._position_size = 0.05
t.execute_action()
check("OKX emergency close on SL fail",
      any(c[0] == "close" for c in t._calls))


t = _FakeOkxTrader({"broker": "okx", "action": "DO_TAKE_PROFIT",
                     "symbol": "BTCUSDT", "direction": "LONG",
                     "quantity": 0.025})
t._position_size = 0.05
t.execute_action()
check("OKX DO_TAKE_PROFIT: market_close called",
      any(c[0] == "close" for c in t._calls))


t = _FakeOkxTrader({"broker": "okx", "action": "DO_TAKE_PROFIT",
                     "symbol": "BTCUSDT", "direction": "LONG",
                     "quantity": 0.025})
t._position_size = 0.0
t.execute_action()
check("OKX DO_TP no position: no close",
      not any(c[0] == "close" for c in t._calls))


t = _FakeOkxTrader({"broker": "okx", "action": "FIRE_EARLY_EXIT",
                     "symbol": "BTCUSDT", "direction": "LONG"})
t._position_size = 0.05
t.execute_action()
check("OKX FIRE_EARLY_EXIT: market_close called",
      any(c[0] == "close" for c in t._calls))
check("OKX FIRE_EARLY_EXIT: cleanup called",
      any(c[0] == "cleanup" for c in t._calls))


t = _FakeOkxTrader({"broker": "okx", "action": "SET_BREAK_EVEN",
                     "symbol": "BTCUSDT", "direction": "LONG",
                     "precision": 0.1})
t._position_size = 0.05
t.execute_action()
check("OKX SET_BREAK_EVEN: move_sl called",
      any(c[0] == "move_sl" for c in t._calls))


t = _FakeOkxTrader({"broker": "okx", "action": "OPEN_POSITION",
                     "symbol": "BTCUSDT"})  # нет direction
result = t.execute_action()
check("OKX malformed payload: no crash", result is None)



class _FakeCbTrader(VeskaldCoinbase):
    def __init__(self, data):
        super().__init__(data)
        self._calls = []
        self._has_position = False
        self._position_size = 0.0

    def get_position_mode(self): return "ONE_WAY"
    def has_open_position(self, sym, dir): return self._has_position
    def get_position_size_and_sides(self, sym, dir):
        return (self._position_size, "BOTH", self._close_side(dir), 100.0)
    def set_isolated_margin(self, sym):
        self._calls.append(("set_isolated_margin", sym)); return True
    def set_leverage(self, sym, lev):
        self._calls.append(("set_leverage", sym, lev)); return True
    def open_position(self, sym, mode, qty, dir):
        self._calls.append(("open_position", sym, mode, qty, dir)); return "cb-001"
    def set_stop_loss_price(self, sym, sl, dir, mode):
        self._calls.append(("set_sl", sym, sl)); return f"sl-{sym}"
    def place_take_profits(self, sym, tps, dir, mode, qty):
        self._calls.append(("place_tp", sym, len(tps)))
    def move_trailing_stop(self, sym, dir, price):
        self._calls.append(("move_sl", sym, dir, price)); return f"sl-{price}"
    def market_close(self, sym, dir, qty, mode):
        self._calls.append(("close", sym, dir, qty)); return "close-cb"
    def cleanup_protective_orders(self, sym, dir, mode):
        self._calls.append(("cleanup", sym, dir))


data_open = {
    "broker": "coinbase", "action": "OPEN_POSITION", "symbol": "BTCUSDT",
    "direction": "LONG",
    "position": {"position": 0.05, "leverage": 5, "sl": 95000.0, "take_profits": []},
    "strategy": 7,
}
t = _FakeCbTrader(data_open)
result = t.execute_action()
check("Coinbase OPEN returns order id", result == "cb-001")
check("Coinbase OPEN: set_sl called",
      any(c[0] == "set_sl" for c in t._calls))


t = _FakeCbTrader(data_open); t._has_position = True
check("Coinbase OPEN skipped if exists", t.execute_action() is None)


class _CbFailSl(_FakeCbTrader):
    def set_stop_loss_price(self, *a, **k): return None
t = _CbFailSl(data_open)
t._position_size = 0.05
t.execute_action()
check("Coinbase emergency close on SL fail",
      any(c[0] == "close" for c in t._calls))


t = _FakeCbTrader({"broker": "coinbase", "action": "DO_TAKE_PROFIT",
                     "symbol": "BTCUSDT", "direction": "LONG", "quantity": 0.02})
t._position_size = 0.05
t.execute_action()
check("Coinbase DO_TP: close called",
      any(c[0] == "close" for c in t._calls))


t = _FakeCbTrader({"broker": "coinbase", "action": "FIRE_EARLY_EXIT",
                     "symbol": "BTCUSDT", "direction": "LONG"})
t._position_size = 0.05
t.execute_action()
check("Coinbase FIRE_EARLY_EXIT: close + cleanup",
      any(c[0] == "close" for c in t._calls) and
      any(c[0] == "cleanup" for c in t._calls))


t = _FakeCbTrader({"broker": "coinbase", "action": "SET_BREAK_EVEN",
                     "symbol": "BTCUSDT", "direction": "LONG",
                     "precision": 0.1})
t._position_size = 0.05
t.execute_action()
check("Coinbase BREAK_EVEN: move_sl called",
      any(c[0] == "move_sl" for c in t._calls))


t = _FakeCbTrader({"broker": "coinbase", "action": "OPEN_POSITION",
                    "symbol": "BTCUSDT"})
check("Coinbase malformed: no crash", t.execute_action() is None)


import logging
warn_records = []
class _Cap(logging.Handler):
    def emit(self, r):
        if r.levelno == logging.WARNING:
            warn_records.append(r.getMessage())
cap = _Cap()
logging.getLogger("veskald_bridge").addHandler(cap)
try:
    VeskaldCoinbase._MARGIN_WARNING_LOGGED = False
    cb1 = VeskaldCoinbase({})
    cb1.set_isolated_margin("BTCUSDT")
    cb2 = VeskaldCoinbase({})
    cb2.set_isolated_margin("ETHUSDT")
    cb3 = VeskaldCoinbase({})
    cb3.set_isolated_margin("SOLUSDT")
    margin_warns = [w for w in warn_records if "margin mode" in w.lower()]
    check("Coinbase margin warn logged exactly once",
          len(margin_warns) == 1, f"got {len(margin_warns)}")
finally:
    logging.getLogger("veskald_bridge").removeHandler(cap)


config_stub.HAS_CREDS_OVERRIDE = {
    "binance": True,
    "bybit": False,    # без credentials → skip
    "kraken": True,
    "okx": False,
    "coinbase": True,
}


for mod in list(sys.modules):
    if mod == "main" or mod.startswith("lib"):
        del sys.modules[mod]


class _FakeTraderForCheck:
    def __init__(self, broker, mode_or_exception):
        self.broker = broker
        self._x = mode_or_exception
    def get_position_mode(self):
        if isinstance(self._x, Exception):
            raise self._x
        return self._x


broker_mode_map = {
    "binance": "ONE_WAY",
    "kraken": "ONE_WAY",
    "coinbase": Exception("auth failed"),
}
def _fake_build(data):
    b = data["broker"]
    return _FakeTraderForCheck(b, broker_mode_map.get(b, None))

import run as main_mod
main_mod.build_trader = _fake_build

results_main = []
for b in SUPPORTED_BROKERS:
    r = main_mod._check_one_broker(b)
    results_main.append(r)

by_broker = {r["broker"]: r["status"] for r in results_main}
check("Main check: binance ok", by_broker["binance"] == "ok")
check("Main check: bybit skip (no creds)", by_broker["bybit"] == "skip")
check("Main check: kraken ok", by_broker["kraken"] == "ok")
check("Main check: okx skip (no creds)", by_broker["okx"] == "skip")
check("Main check: coinbase error", by_broker["coinbase"] == "error")


records = []
class _AllCap(logging.Handler):
    def emit(self, r):
        records.append(r.getMessage())

allcap = _AllCap()
logging.getLogger("veskald_bridge").addHandler(allcap)
try:
    main_mod._startup_check()
    check("Main startup_check runs without exception", True)
    has_summary = any("Brokers:" in r for r in records)
    check("Main startup_check: summary line logged", has_summary,
          f"records: {records[-5:]}")
    has_active_count = any("2 active" in r for r in records)
    check("Main startup_check: 2 active brokers reported", has_active_count,
          f"records: {records[-5:]}")
    has_skip_count = any("2 skipped" in r for r in records)
    check("Main startup_check: 2 skipped brokers reported", has_skip_count)
    has_fail_count = any("1 failing" in r for r in records)
    check("Main startup_check: 1 failing broker reported", has_fail_count)
finally:
    logging.getLogger("veskald_bridge").removeHandler(allcap)


config_stub.HAS_CREDS_OVERRIDE = {b: False for b in SUPPORTED_BROKERS}
records.clear()
logging.getLogger("veskald_bridge").addHandler(allcap)
try:
    main_mod._startup_check()
    has_zero_warning = any(
        "No brokers passed" in r or "0 active" in r for r in records
    )
    check("Main: warns when zero brokers active", has_zero_warning,
          f"records: {records[-5:]}")
finally:
    logging.getLogger("veskald_bridge").removeHandler(allcap)

# Очистим
config_stub.HAS_CREDS_OVERRIDE = None



check("BaseTrader.opposite LONG → SELL", BaseTrader.opposite_side("LONG") == "SELL")
check("BaseTrader.round_to_step LONG ceil", BaseTrader.round_to_step(100.123, 0.01, "LONG") == 100.13)
check("BaseTrader.round_to_step SHORT floor", BaseTrader.round_to_step(100.123, 0.01, "SHORT") == 100.12)
check("BaseTrader.clamp_take_profits empty", BaseTrader.clamp_take_profits([], 1.0) == [])

clamped = BaseTrader.clamp_take_profits(
    [{"price": 100, "quantity": 0.4}, {"price": 110, "quantity": 0.4},
     {"price": 120, "quantity": 0.4}], 1.0)
check("BaseTrader.clamp sums to position", abs(sum(t["quantity"] for t in clamped) - 1.0) < 1e-9)

import re
re_ok = re.compile(r"^[A-Za-z0-9_\-]{1,36}$")
for prefix in ("open", "tp", "sl", "close"):
    cid = make_client_id(prefix)
    check(f"client_id valid for {prefix}", bool(re_ok.match(cid)), f"got {cid}")



from lib.binance import VeskaldBinance
from lib.bybit import VeskaldBybit
from lib.kraken import VeskaldKraken
check("VeskaldBinance.BROKER_NAME", VeskaldBinance.BROKER_NAME == "binance")
check("VeskaldBybit.BROKER_NAME", VeskaldBybit.BROKER_NAME == "bybit")
check("VeskaldKraken.BROKER_NAME", VeskaldKraken.BROKER_NAME == "kraken")
check("VeskaldOkx.BROKER_NAME", VeskaldOkx.BROKER_NAME == "okx")
check("VeskaldCoinbase.BROKER_NAME", VeskaldCoinbase.BROKER_NAME == "coinbase")


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