<div align="center">

<h1>Veskald Execution Bridge</h1>

<p><strong>Non-custodial signal execution client for Veskald.</strong> Your exchange API keys never leave your own server.</p>

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-supported-blue.svg" alt="Docker"></a>
  <a href="#supported-exchanges"><img src="https://img.shields.io/badge/exchanges-5-blue.svg" alt="Exchanges"></a>
</p>

<p>
  <a href="https://veskald.com">Website</a> ·
  <a href="https://app.veskald.com">App</a> ·
  <a href="https://gitlab.com/veskald/veskald-execution-bridge/issues">Report an issue</a>
</p>

</div>

---

## About the project

Veskald Execution Bridge is the open-source execution client for users of [veskald.com](https://veskald.com). It runs on a server you control and acts as the bridge between your strategies on veskald.com and the official APIs of supported cryptocurrency exchanges.

- **Project type:** open-source software (AGPL-3.0), self-hosted by each user on their own infrastructure.
- **What this client does:** receives signed signals from a user's own Veskald account over an authenticated WebSocket, and relays them to that user's chosen exchange using API keys the user provides locally. It does not contain strategy logic, signal generation, or any decision-making — those are user-side operations performed inside the user's own Veskald account.
- **What this client does not do:** it does not run on any GitLab-provided infrastructure. GitLab CI is used in this repository only at release time, to build and publish Docker images and desktop installers. No signal routing or order placement happens on GitLab runners — see [Continuous integration disclosure](#continuous-integration-disclosure).
- **Operator:** currently operated as a sole proprietorship (*jednoosobowa działalność gospodarcza*) registered in Poland. We plan to incorporate as a Polish limited liability company (*sp. z o.o.*) as the project grows.
- **Security contact:** security@veskald.com

## Why a separate execution client

The Veskald platform is intentionally split into two halves:

1. **Strategy layer** — strategy builder, backtesting, optimisation and signal generation — runs on `veskald.com` under your account.
2. **Execution layer** (this repository) — the part that holds your exchange API keys and places orders on your behalf — runs on a server you control.

The two halves communicate over a single authenticated WebSocket. Veskald sends signals (e.g. *open long BTCUSDT, 0.1 contracts, market, stop at 67500*) and this client relays them to your exchange using keys Veskald never sees.

This separation is non-custodial by design. The strategy logic stays with us so you do not have to maintain it. The exchange API keys stay with you, so we cannot lose them, leak them, or be compelled to use them.

> If you prefer to receive signals as Telegram or email notifications and place orders manually, you do not need this repository — enable the corresponding notification channels in the Veskald app instead.

## How signal flow works

- Signals are **signed** and **bound to your server's IP**. A leaked or copied token cannot be replayed from another machine.
- Exchange API keys **never leave your machine** — they live only in the `.env` file on your server.
- For the journal and execution log, you set up **separate read-only keys** in the Veskald app. Read-only keys cannot place orders or withdraw funds. They let Veskald compare what the strategy expected against what actually filled.
- Execution results flow back to Veskald over the same WebSocket so the journal stays accurate — no key material ever travels.

## Supported exchanges

| Exchange | Status | Market type | Test mode available |
| --- | --- | --- | --- |
| Binance  | Stable          | USD-M Futures      | —             |
| Bybit    | Stable          | USDT Perpetual     | Testnet       |
| Kraken   | Stable          | Futures            | Sandbox       |
| OKX      | In development  | Swap (Perpetual)   | Demo trading  |
| Coinbase | In development  | INTX Perpetuals    | —             |

Need another exchange (Bitget, BingX, Hyperliquid, dYdX, …)? Open an issue — new adapters typically ship within 1–3 weeks.

## Install

Three paths, pick the one that fits how you operate.

### Server — one-line install (recommended)

On a fresh Linux server (Ubuntu / Debian / Fedora / RHEL / CentOS):

```bash
bash <(curl -fsSL https://gitlab.com/veskald/veskald-execution-bridge/-/raw/main/installer/server-install.sh)
```

The installer:

- Detects your distribution and installs Docker if missing (via the official `get.docker.com` script).
- Prompts for your MACHINE token and the API keys for whichever exchanges you want to enable (skip the rest).
- Writes `.env` (mode `0600`) and a `docker-compose.yml` to `/opt/veskald-execution-bridge/` (or `$HOME/veskald-execution-bridge/` for non-root users).
- Pulls the multi-architecture image `registry.gitlab.com/veskald/veskald-execution-bridge:latest` from GitLab Container Registry (`amd64` + `arm64`).
- Starts the container with `restart: unless-stopped`.

After installation, manage the client via subcommands of the same script — see [Updating and operations](#updating-and-operations).

### Desktop app

A double-clickable GUI for Windows, macOS and Linux. No Python install required. Use this if you run the client on the same machine you operate from.

| Platform              | Format         | File                                                              |
| ---                   | ---            | ---                                                               |
| Windows x86_64        | zip            | `Veskald-Execution-Bridge-<version>-windows-x86_64.zip`           |
| macOS Apple Silicon   | tar.gz (.app)  | `Veskald-Execution-Bridge-<version>-macos-arm64.tar.gz`           |
| macOS Intel           | tar.gz (.app)  | `Veskald-Execution-Bridge-<version>-macos-x86_64.tar.gz`          |
| Linux x86_64          | AppImage       | `Veskald-Execution-Bridge-<version>-x86_64.AppImage`              |

Latest builds and SHA-256 checksums live on the [Releases page](https://gitlab.com/veskald/veskald-execution-bridge/-/releases). The first launch opens a Settings dialog for the MACHINE token and exchange keys; values are saved to a `.env` next to the executable.

Platform-specific notes (Windows SmartScreen prompts, macOS quarantine, glibc requirements) ship as `INSTALL.md` inside each archive.

### Manual server setup

If you want to inspect every command or customise the Docker image, follow the step-by-step setup below. This path uses `git clone` + `rebuild_latest.sh` and is also the path our contributors use.

<details>
<summary><strong>Detailed server setup</strong></summary>

Use this if you want full control or are debugging an install.

#### Requirements

- A Linux server — DigitalOcean at $4–6/month is enough, but any VPS works (Hetzner, Vultr, Linode, your own hardware).
- Ubuntu 22.04 LTS recommended.
- 2 GB RAM minimum, 4 GB recommended.
- A Veskald account at [app.veskald.com](https://app.veskald.com).
- API keys with futures permission on at least one supported exchange. **Disable withdrawal permission on the key.**

#### 1. Create a server

Using DigitalOcean as the example because it is cheap:

1. Sign up at [digitalocean.com](https://digitalocean.com).
2. Create → Droplets.
3. Settings:
   - **Region:** pick the one geographically closest to your chosen exchange's matching engine — typically Frankfurt or Amsterdam for European users, Singapore for Asian pairs.
   - **Image:** Ubuntu 22.04 LTS.
   - **Size:** 2 GB RAM minimum.
   - **Authentication:** SSH key (strongly preferred) or password.
4. After creation, note the droplet's public IP — you will need it.

#### 2. Generate your connection token

The token is bound to your specific server IP, so it is useless on its own.

1. Open `app.veskald.com/notifications`.
2. Find the **Socket** channel and enable it.
3. Enter your server's IP address.
4. Save — the app shows a MACHINE token. Copy it.

#### 3. Install Docker on the server

SSH in:

```bash
ssh root@YOUR_SERVER_IP
```

Install dependencies:

```bash
apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin git nano
```

#### 4. Clone and configure

```bash
git clone https://gitlab.com/veskald/veskald-execution-bridge.git
cd veskald-execution-bridge
chmod +x rebuild_latest.sh
cp .env.example .env
nano .env
```

Fill in the variables you need. You only need keys for the exchanges you will actually use — leave the rest empty.

See the [configuration reference](#configuration-reference) for every variable.

#### 5. Run

```bash
./rebuild_latest.sh
```

This builds the Docker image and starts the container in the background.

#### 6. Enable auto-restart on reboot

```bash
docker update --restart unless-stopped $(docker ps -q)
```

The client will now come back automatically if the server reboots.

</details>

## Configuration reference

All variables go in your `.env` file.

### Connection (required)

| Variable    | Required | Description                                                                 |
| ---         | ---      | ---                                                                         |
| `HUB_URL`   | yes      | WebSocket URL. Default `https://stream.veskald.com` is correct.             |
| `MACHINE`   | yes      | Token from `app.veskald.com/notifications`. Bound to your server IP.        |
| `UNIQUE_ID` | optional | Override the auto-generated machine ID. Most users don't need this.         |

### Binance (USD-M Futures)

| Variable              | Description                                  |
| ---                   | ---                                          |
| `BINANCE_API_KEY`     | API key with futures permission enabled.     |
| `BINANCE_API_SECRET`  | API secret.                                  |

### Bybit (USDT Perpetual)

| Variable           | Description                                          |
| ---                | ---                                                  |
| `BYBIT_API_KEY`    | API key.                                             |
| `BYBIT_API_SECRET` | API secret.                                          |
| `BYBIT_TESTNET`    | `true` for testnet, `false` for live (default).      |

### Kraken Futures

| Variable             | Description                                          |
| ---                  | ---                                                  |
| `KRAKEN_API_KEY`     | API key.                                             |
| `KRAKEN_API_SECRET`  | API secret.                                          |
| `KRAKEN_SANDBOX`     | `true` for sandbox, `false` for live (default).      |

### OKX Swap

| Variable                | Description                                                  |
| ---                     | ---                                                          |
| `OKX_API_KEY`           | API key.                                                     |
| `OKX_API_SECRET`        | API secret.                                                  |
| `OKX_API_PASSPHRASE`    | API passphrase (required by OKX).                            |
| `OKX_DEMO`              | `true` for demo, `false` for live.                           |
| `OKX_DEFAULT_ISOLATED`  | `true` for isolated margin by default, `false` for cross.    |

### Coinbase INTX

| Variable                         | Description                |
| ---                              | ---                        |
| `COINBASE_API_KEY`               | API key.                   |
| `COINBASE_API_SECRET`            | API secret.                |
| `COINBASE_INTX_PORTFOLIO_UUID`   | INTX portfolio UUID.       |

## Verifying it works

Check the container is running:

```bash
docker ps
```

You should see one container in the `Up` state.

Follow the logs:

```bash
docker compose logs -f
```

You are looking for a successful WebSocket handshake and a `connected` message. If you have an active strategy in your Veskald account with full-auto enabled and a signal fires, the log will show the order being placed.

## Updating and operations

How you keep the client up-to-date depends on the install path you picked.

### Server one-liner (`server-install.sh`)

```bash
bash server-install.sh update         # pull the latest image, restart container
bash server-install.sh status         # docker compose ps
bash server-install.sh logs           # tail -f the container logs
bash server-install.sh restart
bash server-install.sh stop
bash server-install.sh reconfigure    # rerun the wizard, overwrite .env
bash server-install.sh uninstall      # remove container + image + dir
```

Pin a specific image version: edit the generated `docker-compose.yml` and replace `:latest` with e.g. `:v1.2.3`, then `bash server-install.sh restart`.

### Manual setup (`rebuild_latest.sh`)

```bash
./rebuild_latest.sh                  # git pull + rebuild image + restart
docker compose stop                  # full stop
docker compose logs -f               # follow logs
docker compose logs --tail=100       # last 100 lines
```

### Desktop app

Re-download the latest archive from the [Releases page](https://gitlab.com/veskald/veskald-execution-bridge/releases) and replace the binary. Your `.env` and logs are kept outside the bundle (in the OS user config directory) and survive upgrades.

## Security

This client handles your exchange API keys. Treat it accordingly.

- **Never commit `.env`.** It is already in `.gitignore` — keep it that way.
- **Use API keys with futures permission only.** Disable withdrawal at the exchange. Most exchanges (Binance, OKX, Bybit) also let you whitelist the client's server IP — do that.
- **The MACHINE token is bound to your IP**, but treat it as a secret anyway.
- **Audit the code.** That is the point of open source. `lib/` is roughly 1,500 lines of readable Python. Read it.
- **Use SSH keys, not passwords.** Disable root SSH login once you have created a non-root sudo user.
- **Keep the server patched** — `apt update && apt upgrade -y` weekly is a healthy habit.
- The Docker image and desktop binaries never contain your `.env`. It stays on your host or in the OS user config directory.

Found a security issue? Please email **security@veskald.com** rather than opening a public issue.

## Troubleshooting

**Container won't start.** Check `docker compose logs`. Almost always an empty or malformed value in `.env` — verify no trailing spaces and no quotes around values.

**WebSocket disconnects immediately.** The server's public IP must match what you entered at `app.veskald.com/notifications`. If you moved servers, regenerate the token.

**Order rejected by exchange.** Usually one of: (1) the API key is missing futures permission, (2) the exchange has IP whitelisting on and your server IP is not whitelisted, (3) margin mode mismatch (isolated vs cross). The exchange's rejection reason is logged verbatim — read it.

**Client connects but no orders are placed.** Confirm the strategy in your Veskald account has full-auto mode enabled (the checkbox on the strategy edit screen). Without it, you get notifications but the client waits for your manual confirmation.

**`docker compose` not found after the one-liner.** The `get.docker.com` script normally installs the Compose v2 plugin. If Docker was pre-installed without it (e.g. `apt install docker.io` or via Snap), install the plugin and re-run the installer:

```bash
sudo apt-get install -y docker-compose-plugin       # Debian / Ubuntu
sudo dnf install -y docker-compose-plugin           # Fedora / RHEL / CentOS
```

Snap-installed Docker is not supported — `sudo snap remove docker` and let the installer set up the official package.

**An exchange API changed and something broke.** Exchanges occasionally ship breaking API changes. Run your update command (`server-install.sh update` or `./rebuild_latest.sh`). If the fix is not out yet, open an issue — patches usually land within a day.

Anything else: open an issue, or contact support from inside the Veskald app.

## Project structure

```
veskald-execution-bridge/
├── .env.example                       # environment template
├── Dockerfile                         # production image (also pushed to registry.gitlab.com)
├── docker-compose.yml                 # dev / local compose
├── rebuild_latest.sh                  # manual git-clone deploy
├── run.py                             # headless entry point
├── config.py                          # config loader
├── BUILD.md                           # how to build desktop apps locally
├── installer/
│   ├── server-install.sh              # ← server one-liner installer
│   ├── build-local.sh / build-local.ps1   # desktop builds (Linux/macOS, Windows)
│   ├── veskald-execution-bridge.spec  # PyInstaller spec
│   ├── launcher.py + ui/              # PySide6 desktop app
│   ├── INSTALL.md                     # ships inside each desktop archive
│   └── assets/                        # icon, .desktop, linux-install.sh
├── lib/                               # exchange adapters + shared logic
│   ├── base_trader.py                 # shared adapter interface
│   ├── trader_factory.py              # picks the right adapter based on the signal
│   ├── symbols.py                     # symbol mapping between Veskald and exchanges
│   ├── userdir.py                     # OS-specific config / log dirs
│   ├── logger.py
│   ├── binance.py / bybit.py / coinbase.py / kraken.py / okx.py
├── .gitlab-ci.yml                     # CI: Docker multi-arch build & push to GitLab Container Registry
└── .gitlab/merge_request_templates/Default.md   # MR template + format reminder
```

Adding a new exchange adapter is a single file in `lib/` implementing the `BaseTrader` interface.

## Continuous integration disclosure

This repository uses GitLab CI only at release time. The `.gitlab-ci.yml` pipeline runs when a release tag is pushed and is responsible for:

- Building the multi-architecture Docker image (`linux/amd64` and `linux/arm64`) and publishing it to GitLab Container Registry.
- Building desktop installers for Windows, macOS (Apple Silicon and Intel) and Linux, and uploading them as artifacts on the GitLab Release.
- Refreshing the public mirror used for desktop installer downloads.

The client itself does not run on GitLab-hosted runners. Signal routing, order placement and any other runtime behaviour happens exclusively on a user's own server or workstation, never on GitLab infrastructure. All workflow jobs declare explicit `timeout-minutes` values to prevent runaway runs, and multi-architecture builds are split into per-architecture jobs so that a stuck build cannot consume runner time beyond its configured bound.

## Roadmap

- Additional exchange adapters (Bitget, BingX, Hyperliquid) — by request.
- Multi-account routing (run several strategies against several accounts from one client).
- Optional Telegram mirror — the client posts a copy of every action it takes to a Telegram channel of your choice.

[Vote for what's next →](https://veskald.com/roadmap)

## Contributing

Bug reports and pull requests are welcome.

- Open an issue first for non-trivial changes.
- Keep exchange-specific code in `lib/<exchange>.py`. No exchange logic in `run.py`.
- Run `python test.py` before submitting.
- See `BUILD.md` for building the desktop apps and Docker image locally.

### PR titles — Conventional Commits

PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) — the title becomes a line in the auto-generated "What's Changed" section of the next release.

```
type: Subject in imperative mood, capitalized
```

Allowed types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `revert`.

Examples:

- `feat: Add Bybit testnet toggle in settings dialog`
- `fix: Reconnect socket after MACHINE token rotation`
- `chore: Bump pybit to 5.16.0`

The PR title workflow blocks merges that do not conform and posts a comment explaining what is wrong. See `.gitlab/merge_request_templates/Default.md`.

## License

[AGPL-3.0](LICENSE). Use it freely, modify it, run it for your own purposes. If you build a hosted service on top of it, the AGPL requires you to publish your changes — that is the trade.

## About the operator

Veskald is currently operated as a sole proprietorship (*jednoosobowa działalność gospodarcza*) registered in Poland. As the project scales, we plan to incorporate as a Polish limited liability company (*sp. z o.o.*).

- 🌐 [veskald.com](https://veskald.com)
- 📱 [app.veskald.com](https://app.veskald.com)
- 💬 In-app support
- 🔒 security@veskald.com
- 🐛 [GitLab issues](https://gitlab.com/veskald/veskald-execution-bridge/issues)
