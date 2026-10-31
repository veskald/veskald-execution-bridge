from typing import Literal

Broker = Literal["binance", "bybit", "kraken", "okx", "coinbase", "kucoin", "hyperliquid"]

_KRAKEN_BASE_RENAME = {"BTC": "XBT"}
_KUCOIN_BASE_RENAME = {"BTC": "XBT"}


def _split_binance_symbol(symbol: str) -> tuple[str, str]:
    s = symbol.upper().strip()
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote):
            base = s[: -len(quote)]
            if base:
                return base, quote
    raise ValueError(f"Cannot parse symbol: {symbol!r}")


def to_exchange_symbol(symbol: str, broker: Broker) -> str:
    if broker not in ("binance", "bybit", "kraken", "okx", "coinbase", "kucoin", "hyperliquid"):
        raise ValueError(f"Unknown broker: {broker}")

    s = symbol.upper().strip()
    if broker in ("binance", "bybit"):
        return s

    base, quote = _split_binance_symbol(s)

    if broker == "kraken":
        base_kr = _KRAKEN_BASE_RENAME.get(base, base)
        quote_kr = "USD" if quote in ("USDT", "USDC", "BUSD") else quote
        return f"PF_{base_kr}{quote_kr}"

    if broker == "okx":
        return f"{base}-{quote}-SWAP"

    if broker == "coinbase":
        return f"{base}-PERP-INTX"

    if broker == "hyperliquid":
        return "k" + base[4:] if base.startswith("1000") else base

    if broker == "kucoin":
        base_kc = _KUCOIN_BASE_RENAME.get(base, base)
        return f"{base_kc}{quote}M"

    raise ValueError(f"Unhandled broker: {broker}")


def from_exchange_symbol(symbol: str, broker: Broker) -> str:
    if broker in ("binance", "bybit"):
        return symbol.upper().strip()

    if broker == "hyperliquid":
        coin = symbol.strip()
        return ("1000" + coin[1:] if coin.startswith("k") else coin.upper()) + "USDT"

    s = symbol.upper().strip()

    if broker == "okx":
        if s.endswith("-SWAP"):
            s = s[:-5]
        parts = s.split("-")
        if len(parts) == 2:
            return parts[0] + parts[1]
        return s.replace("-", "")

    if broker == "coinbase":
        if s.endswith("-PERP-INTX"):
            base = s[: -len("-PERP-INTX")]
            return base + "USDT"
        return s.replace("-", "")

    if broker == "kucoin":
        if s.endswith("M"):
            s = s[:-1]
        inv = {v: k for k, v in _KUCOIN_BASE_RENAME.items()}
        for src, dst in inv.items():
            if s.startswith(src):
                return dst + s[len(src):]
        return s

    if broker == "kraken":
        if s.startswith("PF_") or s.startswith("PI_"):
            s = s[3:]
        inv = {v: k for k, v in _KRAKEN_BASE_RENAME.items()}
        for src, dst in inv.items():
            if s.startswith(src):
                rest = s[len(src):]
                if rest.endswith("USD"):
                    return dst + rest + "T"
                return dst + rest
        if s.endswith("USD"):
            return s + "T"
        return s

    return s