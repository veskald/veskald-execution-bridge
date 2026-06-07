# Building Veskald Execution Bridge locally

How to produce the desktop binaries (Linux AppImage, macOS `.app`,
Windows `.exe`) from this repository. **PyInstaller does not
cross-compile** — each platform's artifact must be built on a host of
that platform (or via the GitLab CI pipeline).

For server / Docker deployments use the existing `Dockerfile` instead —
this document is only about the desktop builds.

---

## 1. Linux → AppImage

Tested on Ubuntu 22.04 / 24.04. Should work on any glibc ≥ 2.35 distro.

### One-time setup

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip \
                    libxcb-cursor0 libxkbcommon-x11-0 libdbus-1-3 \
                    libfuse2 \
                    librsvg2-bin               # for icon rendering (optional)
```

`libfuse2` is required by AppImage runtime; `libxcb-cursor0` by Qt 6.5+.

### Build

```bash
installer/build-local.sh                    # auto-detects version via git
installer/build-local.sh v1.2.3             # pin version explicitly
```

Output: `dist/Veskald-Execution-Bridge-<version>-x86_64.AppImage` (+ `.sha256`).

### Run

```bash
chmod +x dist/Veskald-Execution-Bridge-*.AppImage
./dist/Veskald-Execution-Bridge-*.AppImage
```

Double-clicking from a file manager works the same — no terminal opens.

---

## 2. macOS → `.app` bundle

Tested on macOS 13+ on Apple Silicon and Intel.

### One-time setup

**For arch-native builds** (arm64 *or* x86_64, matching the host):

```bash
brew install python@3.11               # or use the python.org installer
brew install librsvg                   # icon SVG → PNG conversion (optional)
```

**For `universal2` builds** (one `.app` for both arm64 and x86_64): the
host `python3` MUST be a universal2 build. Brew/pyenv give you a single
arch; install Python directly from
[python.org](https://www.python.org/downloads/macos/) (pick
`python-3.11.x-macos11.pkg`). Confirm with:

```bash
file "$(which python3)"
# expect: Mach-O universal binary with 2 architectures: [x86_64:...] [arm64:...]
```

### Build

```bash
installer/build-local.sh                  # native arch (arm64 or x86_64)
installer/build-local.sh --universal      # one .app for both arches
installer/build-local.sh --arch arm64     # force a specific arch
```

Outputs:

| Flag | File |
|---|---|
| (none) | `dist/Veskald-Execution-Bridge-<v>-macos-arm64.tar.gz` (or `-x86_64.tar.gz`) |
| `--universal` | `dist/Veskald-Execution-Bridge-<v>-macos-universal2.tar.gz` |
| `--arch arm64` | `dist/Veskald-Execution-Bridge-<v>-macos-arm64.tar.gz` |
| `--arch x86_64` | `dist/Veskald-Execution-Bridge-<v>-macos-x86_64.tar.gz` |

The tarball contains `Veskald Execution Bridge.app` — drag it into
`/Applications`. The bundle is **ad-hoc codesigned** (no Apple Developer
account needed) which lets Gatekeeper launch it after one of:

```bash
# Either: strip the quarantine flag after extracting
xattr -dr com.apple.quarantine "/Applications/Veskald Execution Bridge.app"

# Or: right-click → Open → "Open anyway" (one time)
```

### Limitations without a paid Apple Developer account

- No notarization → Gatekeeper warns on first launch (workaround above)
- No App Store / TestFlight distribution
- No `Hardened Runtime` entitlements

For paid distribution add `codesign_identity=...` and `entitlements_file=...`
to the `EXE(...)` block in `installer/veskald-execution-bridge.spec`, plus an
`xcrun notarytool` step.

---

## 3. Windows → `.exe` in a zip

Tested on Windows 10 / 11 x86_64.

### One-time setup

1. Install **Python 3.11** from
   [python.org](https://www.python.org/downloads/windows/) — be sure to
   tick **"Add Python to PATH"** in the installer.
2. Install **Git for Windows** (optional, only for `git describe`-derived
   versions).
3. (Optional) Install **ImageMagick** for icon rendering, otherwise the
   build still works with a placeholder icon.
4. Allow PowerShell to run local scripts once:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

### Build

From the project root in PowerShell:

```powershell
.\installer\build-local.ps1                   # auto version
.\installer\build-local.ps1 -Version v1.2.3   # pin version
```

Output: `dist\Veskald-Execution-Bridge-<version>-windows-x86_64.zip` (+ `.sha256`).

### Run

Extract the zip, double-click `veskald-execution-bridge.exe`. The first launch
shows a **SmartScreen** warning (the binary is not yet code-signed):
click **More info → Run anyway**.

### Code signing (optional)

To suppress SmartScreen permanently you need an EV (Extended Validation)
code-signing certificate (~$300/year). Once you have a `.pfx`, sign the
`.exe` after build:

```powershell
& "$env:ProgramFiles(x86)\Windows Kits\10\bin\10.0.*\x64\signtool.exe" `
  sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f your.pfx /p "yourpass" `
  dist\veskald-execution-bridge.exe
```

---

## 4. Docker image (server / headless)

The same `Dockerfile` powers both local Docker development and the
multi-arch image published to GitLab Container Registry by CI.

### Build locally (single arch, fast)

```bash
docker build -t execution-bridge:dev .
docker run --rm \
  -e HUB_URL=https://stream.veskald.com \
  -e MACHINE=<your-token> \
  execution-bridge:dev
```

Or with the existing `docker-compose.yml` for a full local stack:

```bash
cp .env.example .env && nano .env
docker compose up --build -d
docker compose logs -f
```

### Build multi-arch (matches what CI ships)

CI builds `linux/amd64,linux/arm64` and pushes to
`registry.gitlab.com/veskald/veskald-execution-bridge`. To reproduce locally you need
**buildx** and **QEMU**:

```bash
docker run --privileged --rm tonistiigi/binfmt --install all   # one-time
docker buildx create --use --name veskald-builder                # one-time
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag execution-bridge:multiarch-test \
  --load .              # --load only works for the current host arch
```

`--load` will only materialise the arch matching your machine; the other
manifest stays in the buildx cache. Use `--push` instead to push both to a
registry.

### Use the CI-published image

After a release, the image is at:

```
registry.gitlab.com/veskald/veskald-execution-bridge:<version>   # versioned, immutable
registry.gitlab.com/veskald/veskald-execution-bridge:latest      # always newest stable
```

End users don't run `docker pull` themselves — `installer/server-install.sh`
handles that. See README → "Server (Docker) — one command".

---

## 5. Release flow (GitLab CI)

The desktop apps are **built locally** by the maintainer (one OS per build host),
while the multi-arch Docker image is built by CI on tag push.

### Desktop apps → S3 (local + `--deploy`)

On each desktop host (Linux, macOS, Windows) run the local builder with the
`--deploy` flag. The script builds the binary and uploads the archives directly
to S3, versioned + rolling `/latest/`.

```bash
# Linux
S3_BUCKET=downloads.veskald.com installer/build-local.sh --deploy v1.2.3

# macOS (Apple Silicon native, or --universal for both arches)
S3_BUCKET=downloads.veskald.com installer/build-local.sh --universal --deploy v1.2.3
```

```powershell
# Windows
$env:S3_BUCKET = "downloads.veskald.com"
.\installer\build-local.ps1 -Deploy -Version v1.2.3
```

S3 layout after deploy:

```
s3://<bucket>/execution-bridge/releases/
├── v1.2.3/
│   ├── Veskald-Execution-Bridge-v1.2.3-windows-x86_64.zip
│   ├── Veskald-Execution-Bridge-v1.2.3-macos-arm64.tar.gz
│   ├── Veskald-Execution-Bridge-v1.2.3-linux-x86_64.tar.gz
│   ├── Veskald-Execution-Bridge-v1.2.3-x86_64.AppImage
│   ├── Veskald-Execution-Bridge-v1.2.3-linux-x86_64-installer.tar.gz
│   └── *.sha256
└── latest/                ← rolling mirror with version stripped from filenames
    ├── Veskald-Execution-Bridge-windows-x86_64.zip
    ├── Veskald-Execution-Bridge-macos-arm64.tar.gz
    └── ...
```

Required env vars when using `--deploy`:

| Variable                | Default                          | Purpose                          |
| ---                     | ---                              | ---                              |
| `S3_BUCKET`             | (required)                       | Destination bucket               |
| `S3_PREFIX`             | `execution-bridge/releases`      | Key prefix                       |
| `S3_REGION`             | `us-east-1`                      | Bucket region                    |
| `AWS_PROFILE` / `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | (your usual AWS auth) | Credentials |
| `AWS_DOWNLOADS_BASE_URL`| `https://<bucket>.s3.<region>.amazonaws.com` | Printout URL only |

### Docker image → registry.gitlab.com (CI on tag push)

The only thing CI does. Pipeline in `.gitlab-ci.yml`:

```bash
git tag v1.2.3 && git push origin v1.2.3
```

Triggers `authorize` → `docker` (multi-arch `linux/amd64,linux/arm64` build &
push to `registry.gitlab.com/veskald/veskald-execution-bridge`). Tags:

- `:v1.2.3`, `:1.2.3`, `:1.2`, `:1`, `:latest` (non-prerelease)
- `:sha-<short>` (always)

Dry run without push:

```bash
gh workflow run "Build & Release" -f version=v0.0.0-dev -f push_image=false
```

---

## Troubleshooting

### `No package metadata was found for <name>`

A bundled SDK does `importlib.metadata.version(...)` at runtime, but
PyInstaller skipped its `.dist-info` directory. Add the distribution
name to the `for dist in (...)` block in
`installer/veskald-execution-bridge.spec`, then rebuild.

### `ModuleNotFoundError: No module named 'lib.foo'`

The module is lazy-imported and PyInstaller's static analyzer missed
it. Add it to `hidden_imports` in the spec.

### Linux: `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`

System Qt runtime libs missing. Install with:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libdbus-1-3
```

For Wayland desktops the AppImage usually picks the right backend, but
you can force X11 if rendering is glitchy:

```bash
QT_QPA_PLATFORM=xcb ./dist/Veskald-Execution-Bridge-*.AppImage
```

### macOS: app crashes silently when double-clicked

Open the bundle's binary directly from a terminal so you can see the
exception:

```bash
"/Applications/Veskald Execution Bridge.app/Contents/MacOS/veskald-execution-bridge"
```

### Windows: app exits immediately

PyInstaller built it as `console=False`, so any traceback goes nowhere.
Rebuild with `console=True` temporarily by editing the `EXE(...)` block
in the spec, or run with `Debug` enabled.

---

## Where config / logs live after install

| OS | Config (`.env`, `.unique_id`) | Logs |
|---|---|---|
| Linux | `~/.config/veskald-execution-bridge/` | `~/.config/veskald-execution-bridge/logs/` |
| macOS | `~/Library/Application Support/Veskald Execution Bridge/` | same dir + `logs/` |
| Windows | `%APPDATA%\Veskald Execution Bridge\` | same dir + `logs\` |

Override with `VESKALD_LOGS_DIR=/somewhere/else`.

---

## Quick reference

```bash
# Linux
installer/build-local.sh                          # AppImage

# macOS (Apple Silicon mac, universal output)
installer/build-local.sh --universal              # .app, both arches

# macOS (per-arch)
installer/build-local.sh                          # native (arm64 or x86_64)

# Windows (in PowerShell)
.\installer\build-local.ps1                       # .exe in zip

# All three via CI
gh workflow run "Build & Release" -f version=v0.0.0-dev -f publish=false
```
