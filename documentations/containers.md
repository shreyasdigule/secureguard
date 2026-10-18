# SecureGuard containers

Two images, one compose file, one shared data volume.

| Service | Image | Entrypoint | Listens on | Purpose |
|---|---|---|---|---|
| `api` | `Dockerfile.api` | `uvicorn main:app --host 0.0.0.0 --port 8000` | `8000` inside, `127.0.0.1:8000` on the host | FastAPI service (`main.py`) |
| `dashboard` | `Dockerfile.dashboard` | `xvfb-run -a   ª python main_qt.py` | nothing | PySide6 operator console, headless |

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/      # {"status":"SecureGuard is running","version":"0.4.0"}
docker compose ps               # both services should reach "healthy"
docker compose logs -f dashboard
```

---

## 1. API service

**Framework / entry point.** FastAPI. The application object is a module-level
global, `app = FastAPI(title="SecureGuard", version="0.4.0")` at `main.py:32`,
and `main.py` has **no** `if __name__ == "__main__"` block, so there is no
in-repo server bootstrap. The invocation the project documents is
`python -m uvicorn main:app --host 0.0.0.0 --port 8000`
(`docs/ANALYSIS_AND_RUN_GUIDE_2026-09-18.md:194`); the compose file and
`Dockerfile.api` use exactly that.

**Port 8000, bound to `0.0.0.0` inside the container.** Because the binding is a
uvicorn CLI flag, no source change is needed. Host-side publishing is
`127.0.0.1:8000:8000`     `/` and `/docs` are unauthenticated, so publishing on
every host interface would hand the OpenAPI schema to the LAN. Change the
mapping to `"8000:8000"` if you need remote access, and put TLS in front.

**Health mechanism     there is no `/health` endpoint.** The complete route table
is `/`, `/command`, `/state/{subsystem_id}`, `/evidence`, `/evidence/verify`,
`/session/info`, `/auth/dual-control/{approve,status,clear,cleanup}`, plus
FastAPI's automatic `/docs`, `/redoc` and `/openapi.json`. Every application
route except `/` depends on `current_auth` (`main.py:37-57`), so `/` is the only
unauthenticated liveness signal the service actually publishes. The container
healthcheck reads it and asserts the status banner rather than accepting any
200:

```python
urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)  # -> {"status": "SecureGuard is running",   ª}
```

`docker compose up` gates the dashboard on this check
(`depends_on: api: condition: service_healthy`).

**Dependencies.** `requirements.txt` also declares PySide6, pyqtgraph and
PyOpenGL, but nothing reachable from `main.py` imports Qt     the chain
`main -> pipeline -> {causal_xai, multi_dimensional_risk, physics_digital_twin,
hardware_telemetry, state_machine, dual_control_store, evidence_log,
verify_log, crypto_audit, persistence}` needs only numpy, FastAPI/Pydantic,
PyJWT and cryptography. The API image installs only those, and a build-time
`RUN python -c "import main;   ª"` fails the build if that closure ever stops
being true, so the trim cannot silently rot.

---

## 2. Dashboard container (headless Qt)

```dockerfile
ENV QT_QPA_PLATFORM=offscreen
ENV QT_QPA_FONTDIR=/usr/share/fonts/truetype/dejavu
ENV LIBGL_ALWAYS_SOFTWARE=1
CMD ["sh","-c","exec xvfb-run -a --server-args=\"-screen 0 ${SG_XVFB_SCREEN} -nolisten tcp\" python main_qt.py"]
```

Both environment settings are mandatory, and the second one is not obvious:

* `QT_QPA_PLATFORM=offscreen`     headless rendering.
* `QT_QPA_FONTDIR`     without a real font directory the Qt font database is
  **empty**. Measured on this repo with a `QFontDatabase.families()` probe:

  | Environment | Families loaded |
  |---|---|
  | `QT_QPA_PLATFORM=offscreen`, no `QT_QPA_FONTDIR` | **0** |
  | `QT_QPA_PLATFORM=offscreen` + `QT_QPA_FONTDIR` at a real font dir | **175** |

  With zero families every `QFontMetrics` value is degenerate: layout collapses
  and any assertion about text is meaningless. The project already documents
  this in `test_ui_compliance.py:599-603`, and `industrial_theme.resolve_mono_family()`
  (`industrial_theme.py:136-166`) degrades to the generic `monospace` family    
  a correct fallback, but not backed by real metrics.

  Fonts come from the distro package `fonts-dejavu-core` (never copied from the
  host). Debian bookworm ships that package to
  `/usr/share/fonts/truetype/dejavu/` with `DejaVuSans.ttf`,
  `DejaVuSansMono.ttf`, `DejaVuSerif.ttf` and their bold variants, so the
  in-container monospace family resolves to a real fixed-pitch face
  (`DejaVu Sans Mono`) instead of the generic fallback. The Dockerfile asserts
  the directory exists and contains `.ttf` files, so a future base-image change
  fails the build instead of shipping a silently empty font database.

Xvfb is required *even though* the platform plugin is `offscreen`: the 3D view
(`qt_view3d.py` -> `pyqtgraph.opengl` -> `QOpenGLWidget`) still needs a real GL
context, and that context is created through GLX/EGL against a display server.
Mesa's software rasteriser supplies the implementation
(`libgl1-mesa-dri`, `libglx-mesa0`, `libegl-mesa0`, `libglu1-mesa`);
`LIBGL_ALWAYS_SOFTWARE=1` keeps it on llvmpipe because a container has no GPU.
`xauth` is installed as well: Debian's `xvfb-run` is a shell script that shells
out to `xauth`, and aborts without it.

**Healthcheck.** The container exposes no network service, so liveness is
checked the only two honest ways available: `pgrep` for the console process,
and a Qt font-database probe that fails if the family list is empty. The second
half matters     a container can report healthy while every string renders with
degenerate metrics.

**There is no VNC/X11 export.** The console renders, records evidence and keeps
its timers running; nothing is visible from the host. Watch it with
`docker compose logs -f dashboard`.

### Test mode is OFF

`SECUREGUARD_TEST_MODE` is pinned to `"0"` in both images and in
`docker-compose.yml`, and is **never** `"1"`:

* API: only the exact string `"1"` enables hermetic test tokens
  (`keycloak_auth.py:42-44`), and with it enabled the API accepts tokens signed
  by the in-repo test key (`keycloak_auth.py:147-153`) instead of validating
  real Keycloak RS256 tokens against the realm JWKS.
* Console: with test mode off, `_bootstrap_auth()` does not mint a session
  (`dashboard_qt.py:1490-1494`) and the Quick Profile buttons are replaced by
  an explanatory label (`dashboard_qt.py:711-719`). An operator pastes a real
  token on the Manual Token tab, or the app calls Keycloak directly.

To point the deployment at a real realm, supply placeholders through the
environment (no secrets are committed):

```bash
export KEYCLOAK_BASE_URL=https://keycloak.example.com
export KEYCLOAK_ISSUER=$KEYCLOAK_BASE_URL/realms/secureguard
export KEYCLOAK_JWKS_URL=$KEYCLOAK_BASE_URL/realms/secureguard/protocol/openid-connect/certs
export KEYCLOAK_AUDIENCE=secureguard-api
export KEYCLOAK_CLIENT_ID=secureguard-api
export KEYCLOAK_CLIENT_SECRET=            # confidential client, if any
```

`KEYCLOAK_JWKS_URL` must not be set to an empty string: `os.getenv` returns `""`
rather than the composed default, and the API would then try to fetch JWKS from
an empty URL (`keycloak_auth.py:31-33`). The compose file supplies a placeholder
default for that reason.

---

## 3. Persistent storage

The data directory is resolved by `app_paths.data_dir()`
(`app_paths.py:34-70`), in this order:

1. `SECUREGUARD_DATA_DIR` if set     **the only thing the containers set**, to
   `/data`;
2. the executable's directory when frozen;
3. the module's directory.

Both images set `SECUREGUARD_DATA_DIR=/data`, and compose mounts the named
volume `secureguard-data` there. Files that land in it:

| File | Created by |
|---|---|
| `evidence_log.jsonl` | `evidence_log.py:38` (`LOG_PATH = data_file(...)`) |
| `secureguard.db` | `persistence.py:22`; schema via `persistence.init_db()`, called from `state_machine.py:88` |
| `dual_control.db` (+ `-wal`, `-shm`) | `dual_control_store.py:19`; WAL mode at `dual_control_store.py:35` |
| `risk_thresholds.json` | `dashboard_qt.py:1801-1802` |
| `.secureguard/audit_key.pem` | `crypto_audit.py:309-321`     see below |

**The signing key needs `HOME=/data`, and this is not optional.**
`crypto_audit.get_audit_signer()` generates the Ed25519 ledger-signing key at
`Path.home() / ".secureguard" / "audit_key.pem"` (`crypto_audit.py:309-321`)    
a path that `app_paths.data_dir()` does **not** cover. Left alone in a container
it would be written to the container's writable layer and regenerated on every
redeploy, and `verify_log.verify_chain()` verifies signatures against the
*current* signer's public key (`verify_log.py:173-179`), so every previously
signed record would then be reported as tampered. Both images therefore set
`HOME=/data`, which makes the code's own default path resolve inside the volume.

`AUDIT_KEY_PATH=/data/.secureguard/audit_key.pem` is set to the same file, but
note it is only read when the file **already exists**
(`crypto_audit.py:301-307`); otherwise `crypto_audit` falls back to the
`Path.home()` default. That is exactly why `HOME` has to agree with it rather
than replace it.

**Bind-mount alternative** (commented in `docker-compose.yml`, uncomment for
either or both services):

```yaml
    volumes:
      - secureguard-data:/data
      - ./docker-data:/data
```

A bind mount does not inherit the image's directory ownership, so the host
directory must be writable by uid 10001 (both images run as an unprivileged
user):

```bash
mkdir -p docker-data && sudo chown -R 10001:10001 docker-data
```

Inspecting the ledger from the host while the containers run:

```bash
docker compose exec api python verify_log.py            # full chain verification
docker compose exec api ls -la /data                    # db + -wal/-shm sidecars
docker run --rm -v "$PWD/docker-data:/data" busybox tail -f /data/evidence_log.jsonl
```

---

## 4. Risks in this design

1. **Two writers on one ledger.** Both containers mount `secureguard-data` and
   both append to `evidence_log.jsonl`. `evidence_log.py` reads the previous
   chain hash at line 92 and appends at line 273 with a plain
   `open(LOG_PATH, "a")` and no inter-process lock, so two writers can record the
   same predecessor and fork the hash chain     after which `verify_chain` reports
   tampering. `secureguard.db` is opened through `persistence._connect()`
   (`persistence.py:65`) with no busy timeout, so concurrent writes can raise
   "database is locked". `dual_control.db` is WAL-mode with a 10 s busy timeout
   (`dual_control_store.py:32-38`) and tolerates this.
   *Mitigation if it matters:* give the dashboard its own volume
   (`dashboard.volumes: [secureguard-dashboard-data:/data]`) so the API is the
   single writer, and treat the console as a viewer.
2. **The dashboard does not talk to the API.** `depends_on` is start-up
   ordering only. The console builds its own in-process
   `SecureGuardPipeline` (`dashboard_qt.py:1302`) and no code anywhere reads an
   API base URL     so the two containers share a data directory without a
   request path between them. If a client is added later, it will need an API
   base-URL setting that does not exist yet.
3. **The console has no unattended-exit path.** `main_qt.py:28` blocks in
   `app.exec()` forever, which is what a container wants, but it also means the
   image cannot self-verify: there is no `--selftest` style flag that renders
   once and exits non-zero on failure. Use `docker compose exec dashboard
   python -c "  ª"` for ad-hoc checks.
4. **`xvfb-run` signal forwarding.** `xvfb-run` is a shell script; `SIGTERM`
   from `docker stop` reaches it and its cleanup trap kills Xvfb, but the Qt
   process is not guaranteed to see the signal before the grace period expires.
   `stop_grace_period: 45s` and `init: true` are set to bound this. A hard kill
   mid-write is survivable     SQLite recovers its `-wal` on next open     but it
   skips `dashboard_qt._tear_down()`, which retires worker threads.
5. **GL performance.** Everything renders through llvmpipe on the CPU. The 3D
   view is fine for a dashboard; it is not a workstation.

---

## 5. Build-context hygiene

`.dockerignore` keeps the context small and leak-free. Verified against this
repository as it stands:

* Excluded: `.git/`, `dist/` (84 MB `SecureGuard.exe`), `build/`
  (`base_library.zip`, 1.3 MB), `__pycache__/`, `*.pyc`, `.kilo/` (which
  contains a full worktree copy of the source tree), `.pytest_cache/`,
  `tests/`, `docs/`, `logs/`, `archive/`.
* **Vendored OpenGL DLLs / wheel archives: there are none.** A repo-wide scan
  for `.dll/.whl/.lib/.a/.pyd/.so/.zip/.tar/.gz` returns exactly one hit,
  `build/SecureGuard/base_library.zip`, already excluded. The `*.dll`, `*.whl`,
  `*.lib`, `*.a`, `*.pyd` patterns are a guard against them coming back, not a
  description of the current tree. Nothing the Linux runtime needs comes from
  this repository     Mesa and GLX/EGL come from apt.
* Runtime state is excluded from the image on purpose: `*.db`, `*.db-wal`,
  `*.db-shm`, `*.jsonl`, `risk_thresholds.json`, `evidence_archive/`,
  `.secureguard/`. `.gitignore` already refuses to commit the forensic ledger
  because it holds operator usernames, roles, MFA state, commands and device
  fingerprints; baking a developer's live ledger into an image would copy
  exactly that data somewhere it was never meant to go.
* Secrets are excluded too: `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`,
  `*.pfx`, `*.crt`.
* Nothing the runtime needs is excluded. Both Dockerfiles `COPY` an explicit
  file list, and a check confirmed all 26 live modules plus `requirements.txt`
  survive the ignore rules.

---

## 6. Verification status

Run on this machine:

* `docker compose config` -> **exit 0**, full normalised model rendered (both
  services, the `secureguard-data` volume, `depends_on: service_healthy`).
* Every `COPY` source in both Dockerfiles confirmed to exist in the repo and to
  be absent from `.dockerignore`; every in-image path traced to the `apt` /
  `useradd` / `RUN` / `COPY` step that creates it.
* `import main` and `import dashboard_qt` executed locally under
  `QT_QPA_PLATFORM=offscreen` with `SECUREGUARD_DATA_DIR` pointed at a scratch
  directory     both succeed, which is the same assertion the images run at build
  time.
* The 0-vs-175 font-family measurement in section 2, measured locally.
* Debian bookworm package file lists checked for `fonts-dejavu-core`
  (`/usr/share/fonts/truetype/dejavu/DejaVuSans*.ttf`) and `xvfb`
  (`/usr/bin/xvfb-run`, `/usr/bin/Xvfb`).

**Not run: `docker build`.** The Docker CLI (29.8.0) and Compose v5.5.1 are
installed, but there is no daemon and no Docker Desktop installation on this
machine, so no image was built and no container was started:

```
docker build -f Dockerfile.api .
ERROR: failed to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine;   ª The system cannot find the file specified.
```

First build on a machine with a daemon should be treated as the real test of the
apt package list and of the GL stack.
