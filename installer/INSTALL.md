# Veskald Execution Bridge — installation guide

Double-click and run. No Python install, no terminal, no setup script.

## Download

| Platform | Format | File |
|---|---|---|
| **Windows x86_64** | zip | `Veskald-Execution-Bridge-<version>-windows-x86_64.zip` |
| **macOS Apple Silicon** | tar.gz (.app inside) | `Veskald-Execution-Bridge-<version>-macos-arm64.tar.gz` |
| **macOS Intel** | tar.gz (.app inside) | `Veskald-Execution-Bridge-<version>-macos-x86_64.tar.gz` |
| **Linux x86_64** | AppImage | `Veskald-Execution-Bridge-<version>-x86_64.AppImage` |

SHA-256 checksums (`.sha256`) are published next to each artifact.

## Install & run

### Windows

1. Right-click the `.zip` → **Extract All...**.
2. Double-click `veskald-execution-bridge.exe`.
3. First launch shows a SmartScreen warning — click **More info → Run anyway**.

### macOS

1. Double-click the `.tar.gz` to extract.
2. Drag `Veskald Execution Bridge.app` into your **Applications** folder.
3. Double-click it. If Gatekeeper refuses to launch it the first time:

   ```bash
   xattr -dr com.apple.quarantine "/Applications/Veskald Execution Bridge.app"
   ```

   Then double-click again. (Alternatively: right-click the `.app` → **Open** → confirm once.)

### Linux

1. Make the AppImage executable:

   ```bash
   chmod +x Veskald-Execution-Bridge-*.AppImage
   ```

2. Double-click it from your file manager — it launches like Telegram, no install needed.

   First-time AppImage on a system? Install `libfuse2` if your distro is missing it:
   `sudo apt install libfuse2` (Ubuntu/Debian), or `sudo dnf install fuse-libs` (Fedora).

## First-run setup

On the very first launch the app opens a **Settings** dialog automatically:

- **Veskald tab** — Hub URL (default is correct) and **Machine token** (copy from
  your veskald.com dashboard, required).
- **Per-exchange tabs** — paste API key + secret + any extra fields (passphrase
  for OKX and KuCoin, INTX portfolio UUID for Coinbase, account address and
  API wallet private key for Hyperliquid). Leave a tab blank to
  skip that exchange.

Click **Save**. The app immediately starts connecting, runs health checks on
every configured exchange, and the live log fills with output.

Re-open Settings anytime via the **Settings** button in the top bar.

## What you'll see

- Big status text (Idle / Connecting / Live / Stopped / Error) in the top-left
  with a colored dot.
- Machine-token badge next to it.
- **Exchanges** table — per-exchange connection status (Connected / Not
  configured / Failed) with the reason in the detail column.
- **Activity** — color-coded live log tail.
- Bottom status bar — config file path on the left, UTC clock on the right.

## Keyboard shortcuts

- `Ctrl+,` — open Settings
- `Ctrl+R` — restart the app (applies config changes)
- `Ctrl+L` — clear the log view
- `Ctrl+Enter` — toggle Start / Stop
- `Esc` (from message dialogs) — dismiss

## Where things live

- **`.env`** — credentials, written by the Settings dialog (mode `0600` on
  Unix). Lives next to the executable on Windows/Linux; inside
  `~/Library/Application Support/...` is *not* used — everything stays with
  the binary.
- **`logs/veskald_bridge.log`** — rolling log, also next to the executable.
- **`.unique_id`** — auto-generated machine ID.

Override the log destination with `VESKALD_LOGS_DIR=/path/to/dir`.

## Troubleshooting

- **All exchanges show "Failed"** — wrong API key permissions or IP allowlist
  on the exchange dashboard doesn't match this machine. Re-check on the
  exchange side.
- **"Connecting…" forever** — wrong machine token, or no internet. Open
  Settings, re-paste the token, restart with `Ctrl+R`.
- **Windows SmartScreen blocks the binary** — the binary is not yet
  code-signed; click "More info" → "Run anyway".
- **macOS: "developer cannot be verified"** — run
  `xattr -dr com.apple.quarantine "/Applications/Veskald Execution Bridge.app"`.
- **Linux AppImage refuses to run** — usually `libfuse2` missing. Install it
  (`sudo apt install libfuse2`), or run with the extract-and-run flag:
  `./Veskald-Execution-Bridge-*.AppImage --appimage-extract-and-run`.
