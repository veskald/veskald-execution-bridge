import os
import uuid
from dotenv import load_dotenv

from lib.userdir import app_config_dir


_APP_DIR = str(app_config_dir())
# override=True so values written by the desktop app's Settings dialog
# always trump stale shell exports (otherwise BINANCE_API_KEY from the
# user's shell would silently shadow the one they just typed in the GUI).
load_dotenv(os.path.join(_APP_DIR, ".env"), override=True)

# App
HUB_URL = os.getenv("HUB_URL")
MACHINE_TOKEN = os.getenv("MACHINE")

# Graylog (GELF UDP). Handler is only attached when GRAYLOG_HOST is set.
GRAYLOG_HOST = os.getenv("GRAYLOG_HOST")
GRAYLOG_PORT = int(os.getenv("GRAYLOG_PORT", "12201"))

# Binance USDⓈ-M
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# Bybit V5 (linear)
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

# Kraken Futures (Multi-M)
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET")
KRAKEN_SANDBOX = os.getenv("KRAKEN_SANDBOX", "false").lower() == "true"

# OKX V5 (SWAP)
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE")

OKX_DEMO = os.getenv("OKX_DEMO", "false").lower() == "true"
OKX_DEFAULT_ISOLATED = os.getenv("OKX_DEFAULT_ISOLATED", "false").lower() == "true"


COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")

COINBASE_INTX_PORTFOLIO_UUID = os.getenv("COINBASE_INTX_PORTFOLIO_UUID")

# KuCoin Futures. The broker (partner) tag and key arrive with each signal;
# lib/kucoin.py holds the hardcoded fallbacks.
KUCOIN_API_KEY = os.getenv("KUCOIN_API_KEY")
KUCOIN_API_SECRET = os.getenv("KUCOIN_API_SECRET")
KUCOIN_API_PASSPHRASE = os.getenv("KUCOIN_API_PASSPHRASE")


ID_FILE = os.path.join(_APP_DIR, ".unique_id")
ENV_UNIQUE_ID = os.getenv("UNIQUE_ID")

if os.path.exists(ID_FILE):
    with open(ID_FILE, "r") as f:
        LOCAL_UNIQUE_ID = f.read().strip()
else:
    LOCAL_UNIQUE_ID = str(uuid.uuid4())[:8]
    try:
        with open(ID_FILE, "w") as f:
            f.write(LOCAL_UNIQUE_ID)
    except OSError:
        pass

UNIQUE_ID = ENV_UNIQUE_ID or LOCAL_UNIQUE_ID


def has_credentials(broker: str) -> bool:
    b = broker.lower()
    if b == "binance":
        return bool(BINANCE_API_KEY and BINANCE_API_SECRET)
    if b == "bybit":
        return bool(BYBIT_API_KEY and BYBIT_API_SECRET)
    if b == "kraken":
        return bool(KRAKEN_API_KEY and KRAKEN_API_SECRET)
    if b == "okx":
        return bool(OKX_API_KEY and OKX_API_SECRET and OKX_API_PASSPHRASE)
    if b == "coinbase":
        return bool(COINBASE_API_KEY and COINBASE_API_SECRET)
    if b == "kucoin":
        return bool(
            KUCOIN_API_KEY and KUCOIN_API_SECRET and KUCOIN_API_PASSPHRASE
        )
    return False