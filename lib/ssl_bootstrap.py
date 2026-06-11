"""Force stdlib `ssl`, requests, httpx and websocket-client onto certifi's
CA bundle at process start.

Why: python.org's macOS framework Python ships without a usable system trust
store. Without this, `ssl.SSLCertVerificationError: unable to get local
issuer certificate` kills every https / wss handshake until the user
double-clicks `Install Certificates.command` — which most end-users won't.
Inside a PyInstaller .app the problem is identical and there is no command
to run, so we have to wire it up ourselves.

The frozen build already bundles `certifi/cacert.pem` via the PyInstaller
spec; from source the installed `certifi` package supplies one. Either way
`certifi.where()` returns a real path we can hand to OpenSSL.

Must run BEFORE any import that triggers a TLS handshake (socketio,
requests, exchange SDKs, etc.).
"""
from __future__ import annotations

import os


def apply() -> None:
    try:
        import certifi
    except Exception:
        return

    ca = certifi.where()
    if not ca or not os.path.exists(ca):
        return

    # Don't clobber an explicit user override — if SSL_CERT_FILE is already
    # set, the user (or sysadmin) has pinned a specific bundle on purpose.
    for var in (
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "WEBSOCKET_CLIENT_CA_BUNDLE",
    ):
        os.environ.setdefault(var, ca)
