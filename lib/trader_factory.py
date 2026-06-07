"""
Фабрика трейдеров. Команда из сокета содержит поле "broker":
  "binance" | "bybit" | "kraken" | "okx" | "coinbase"

SDK конкретных бирж импортируются ленниво: если ключи/SDK одной биржи
отсутствуют, остальные продолжают работать.
"""
from typing import Any, Dict

from .base_trader import BaseTrader
from .logger import get_logger

_logger = get_logger("TraderFactory")

_BROKERS = ("binance", "bybit", "kraken", "okx", "coinbase")
SUPPORTED_BROKERS = _BROKERS


def _normalize_broker(value: Any) -> str:
    if value is None:
        return "binance"
    s = str(value).strip().lower()
    aliases = {
        "binance-futures": "binance",
        "binance_futures": "binance",
        "bybit-v5": "bybit",
        "kraken-futures": "kraken",
        "krakenfutures": "kraken",
        "okx-v5": "okx",
        "okex": "okx",
        "coinbase-advanced": "coinbase",
        "coinbase_advanced": "coinbase",
        "cb-advanced": "coinbase",
        "cbadvanced": "coinbase",
    }
    return aliases.get(s, s)


def build_trader(data: Dict[str, Any]) -> BaseTrader:
    broker = _normalize_broker(data.get("broker"))
    if broker == "binance":
        from lib.binance import VeskaldBinance
        return VeskaldBinance(data)
    if broker == "bybit":
        from lib.bybit import VeskaldBybit
        return VeskaldBybit(data)
    if broker == "kraken":
        from lib.kraken import VeskaldKraken
        return VeskaldKraken(data)
    if broker == "okx":
        from lib.okx import VeskaldOkx
        return VeskaldOkx(data)
    if broker == "coinbase":
        from lib.coinbase import VeskaldCoinbase
        return VeskaldCoinbase(data)
    raise ValueError(
        f"Unknown broker: {broker!r}. Expected one of: {_BROKERS}"
    )