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
installer/build-local.sh --deploy           # build + upload to S3 (see §5)
installer/build-local.sh v1.2.3 --deploy    # both at once
```

Outputs in `dist/`:

| File | Notes |
|---|---|
| `Veskald-Execution-Bridge-<v>-x86_64.AppImage` | raw AppImage — user must `chmod +x` after download |
| `Veskald-Execution-Bridge-<v>-linux-x86_64.tar.gz` | wraps the AppImage **preserving `+x`** — no chmod after `tar xf` |
| `Veskald-Execution-Bridge-<v>-linux-x86_64-installer.tar.gz` | bundle with `install.sh` for desktop-menu integration |
| `*.sha256` for each archive | |

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
installer/build-local.sh --deploy         # also upload to S3 (see §5)
installer/build-local.sh v1.2.3 --universal --deploy   # pin version + universal + deploy
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
.\installer\build-local.ps1                          # auto version
.\installer\build-local.ps1 -Version v1.2.3          # pin version
.\installer\build-local.ps1 -Deploy                  # also upload to S3 (see §5)
.\installer\build-local.ps1 -Version v1.2.3 -Deploy  # both
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

**First run is interactive — no manual setup needed.** When you pass `--deploy`
the first time, the script will:

1. Install the AWS CLI v2 if it's missing (uses the official Amazon installer —
   `apt` is not required, works on Ubuntu 24.04+).
2. Detect that AWS / S3 env vars are missing and prompt you for them, one at a
   time (secret is read silently).
3. Persist them to your shell rc file (`~/.zshrc` or `~/.bashrc`) inside a
   marked block, with `chmod 600`. On Windows it stores them as **User**
   environment variables (visible in System Properties → Environment Variables).
4. Continue with the upload.

On subsequent runs, the env vars are already there, the script reuses them
silently and uploads immediately.

```bash
# Linux — first time:  asks 5 questions, then builds + uploads
installer/build-local.sh --deploy v1.2.3

# macOS — same UX
installer/build-local.sh --universal --deploy v1.2.3
```

```powershell
# Windows — same UX (uses winget / choco / direct MSI to install awscli)
.\installer\build-local.ps1 -Deploy -Version v1.2.3
```

To **re-prompt** for credentials (e.g. rotate keys), delete the marked block
from `~/.zshrc` / `~/.bashrc` (look for `# >>> veskald-deploy-env >>>`), or on
Windows clear the corresponding User env vars, then re-run with `--deploy`.

**Env vars** read by the deploy step (auto-collected on first run):

| Variable                  | Default                                    | Purpose                                    |
| ---                       | ---                                        | ---                                        |
| `AWS_ACCESS_KEY_ID`       | (prompt)                                   | AWS credentials                            |
| `AWS_SECRET_ACCESS_KEY`   | (prompt, silent)                           | AWS credentials                            |
| `AWS_DEFAULT_REGION`      | `us-east-1`                                | Region (also used as `S3_REGION` fallback) |
| `S3_BUCKET`               | (prompt, default `veskald`)                | Destination bucket                         |
| `AWS_DOWNLOADS_BASE_URL`  | `https://<bucket>.s3.<region>.amazonaws.com` | Public URL printed at the end + used by GitLab Release |
| `S3_PREFIX`               | `execution-bridge/releases`                | Key prefix (not prompted, override via env if needed) |
| `S3_REGION`               | falls back to `AWS_DEFAULT_REGION`         | Per-build override                         |
| `AWS_PROFILE`             | —                                          | Use a non-default `~/.aws/credentials` profile instead of inline keys |

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

#### One-time S3 setup (do this before the first `--deploy`)

1. Create the bucket in AWS Console — General purpose, region of your choice
   (script defaults to `us-east-1`). Use a name without dots for HTTPS to
   work out of the box (e.g. `veskald`, not `downloads.veskald.com`).
2. **Disable "Block all public access"** on the bucket.
3. Attach a bucket policy that allows public reads of the releases prefix:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "PublicReadReleases",
       "Effect": "Allow",
       "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": "arn:aws:s3:::<bucket-name>/execution-bridge/releases/*"
     }]
   }
   ```

4. Get an Access Key ID + Secret Access Key (IAM user or root access keys —
   personal preference; IAM user is safer). Keep them ready for the first
   `--deploy` run.

### Docker image + GitLab Release (CI on tag push)

The pipeline in `.gitlab-ci.yml` does two things on every `v*` tag:

1. **`docker:build-push`** — multi-arch `linux/amd64,linux/arm64` build &
   push to `registry.gitlab.com/veskald/veskald-execution-bridge:<tag>`
   (+ `:latest` for non-prerelease tags).
2. **`release:create`** — creates a GitLab Release at **Deploy → Releases**
   with the tag as name and asset links pointing at the desktop binaries
   already uploaded to S3.

So the **full release flow** is:

```bash
# 1. Build + push desktop binaries to S3 from each platform host:
installer/build-local.sh --deploy v1.2.3                    # on Linux
installer/build-local.sh --universal --deploy v1.2.3        # on macOS
.\installer\build-local.ps1 -Deploy -Version v1.2.3         # on Windows

# 2. Tag + push — CI builds the Docker image and creates the GitLab Release
git tag v1.2.3 && git push origin v1.2.3
```

**Important:** the S3 uploads must happen **before** `git push --tags`,
otherwise the asset links on the Release page will 404 until you upload.

**One-time CI setup** — in GitLab → **Settings → CI/CD → Variables** add:

| Key                       | Value                                             |
| ---                       | ---                                               |
| `AWS_DOWNLOADS_BASE_URL`  | e.g. `https://veskald.s3.us-east-1.amazonaws.com` |
| `MACOS_ARCH_TAG` (opt)    | `universal2` (default), `arm64`, or `x86_64`      |
| `S3_PREFIX` (opt)         | `execution-bridge/releases` (default)             |

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
# ── Linux ─────────────────────────────────────────────────────────────
installer/build-local.sh                          # build only, auto version
installer/build-local.sh v1.2.3                   # build only, pinned version
installer/build-local.sh --deploy                 # build + upload to S3
installer/build-local.sh v1.2.3 --deploy          # all of the above

# ── macOS ─────────────────────────────────────────────────────────────
installer/build-local.sh                          # native arch (arm64 or x86_64)
installer/build-local.sh --universal              # one .app for both arches
installer/build-local.sh --arch arm64             # force arch
installer/build-local.sh v1.2.3 --universal --deploy  # full release flow

# ── Windows (PowerShell) ──────────────────────────────────────────────
.\installer\build-local.ps1                       # build only
.\installer\build-local.ps1 -Version v1.2.3       # pinned version
.\installer\build-local.ps1 -Deploy               # build + upload to S3
.\installer\build-local.ps1 -Version v1.2.3 -Deploy

# ── CI release (tag-driven) ───────────────────────────────────────────
# After all 3 desktop builds are uploaded to S3:
git tag v1.2.3 && git push origin v1.2.3          # → CI builds Docker + creates GitLab Release
```

### All flags at a glance

| Flag (Linux/macOS) | PowerShell equivalent | Effect |
|---|---|---|
| `<version>` (positional, e.g. `v1.2.3`) | `-Version v1.2.3` | Pin version explicitly. Default: from `git describe --tags --always`. |
| `--deploy` | `-Deploy` | After build, upload archives to S3. Prompts for AWS keys on first run and persists them. |
| `--universal` | n/a (macOS only) | macOS: produce a single `.app` for arm64 + x86_64 (needs universal2 Python). |
| `--arch arm64` / `--arch x86_64` / `--arch universal2` | n/a (macOS only) | macOS: force target arch. |
