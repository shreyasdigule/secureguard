# SecureGuard Governance Model     Decision Log

This document records every significant technical decision made during development,
including the rationale for library choices and the reasoning behind accepted tradeoffs.
It is intended to be the single source of truth for why the system is built the way
it is, so future maintainers do not re-litigate settled questions.

---

## 1. Qt Binding: PySide6 (authoritative), PyQt6 excluded

### Decision
PySide6 is the sole supported Qt binding. `PYQTGRAPH_QT_LIB=PySide6` is pinned in
`main_qt.py`, `dashboard_qt.py`, and `Dockerfile.dashboard`. PyQt5 and PyQt6 are
explicitly excluded from the PyInstaller spec (`SecureGuard.spec:79`).

### Rationale
PySide6 is the official Qt for Python binding, maintained by The Qt Company, with
clear licensing (LGPL/GPL/commercial) and no CLA requirements. PyQt6 was present on
the development machine as an unrelated dependency; without the pin, pyqtgraph would
scan `sys.modules`, detect PyQt6 first, and silently rebind every `QFont`/`QColor`/
`QPen` crossing the Qt/pyqtgraph boundary. That caused hard crashes in the chart
tabs that were intermittent and environment-dependent.

### Tradeoff
Locking to one binding removes flexibility if a future dependency requires PyQt6.
The cost of dual-binding support (two code paths, two sets of import hooks, twice
the test surface) was judged not worth it for an internal governance console.

---

## 2. GUI Framework: PySide6 + pyqtgraph + PyOpenGL

### Decision
- **PySide6** for widgets, layout, and the main window.
- **pyqtgraph** for trend charts and the 3D OpenGL view (`pyqtgraph.opengl`).
- **PyOpenGL** as the OpenGL backend for the 3D conveyor visualization.

### Rationale
PySide6 provides the full Qt widget set needed for an industrial HMI (tables, tabs,
dials, progress bars, tree views). pyqtgraph is purpose-built for scientific/real-time
plotting with numpy integration, far lighter than embedding matplotlib. PyOpenGL is
required by `pyqtgraph.opengl` for the `QOpenGLWidget`-based 3D conveyor belt.

### Tradeoff
pyqtgraph's theming API drifts between releases (config option names change), so
`apply_plot_theme()` in `industrial_theme.py` applies options defensively with
try/except per key. This is accepted fragility in exchange for not maintaining a
custom charting stack.

---

## 3. Packaging: PyInstaller one-file console executable

### Decision
The application is packaged with PyInstaller using `SecureGuard.spec`, producing
`dist/SecureGuard.exe` (~73 MB) as a console application (`console=True`).

### Rationale
A single `.exe` simplifies deployment to plant-floor operator stations. No Python
installation is required on the target machine. A console (not windowed) build was
chosen so stdout/stderr remain visible for diagnostics during headless runs.

### Tradeoff
PyInstaller bundles the entire Python interpreter and all dependencies, producing a
large executable. Startup involves extracting to a `_MEIxxxx` temp directory, which
adds a few seconds to first launch. This is accepted because the dashboard runs
continuously once started and is not launched repeatedly.

---

## 4. Authentication Model: Keycloak JWT + hermetic test tokens

### Decision
Production validates real Keycloak RS256 access tokens against the realm JWKS
endpoint (`keycloak_auth.py`). In test mode (`SECUREGUARD_TEST_MODE=1`), test tokens
are minted with a committed RSA 2048 test key pair (`tests/fixtures/test_keys.py`)
using the `TEST_KID = "secureguard-test-key"` key identifier.

### Rationale
Keycloak is an industry-standard OIDC provider with RBAC, MFA, device fingerprinting,
and token revocation support. The test-key path allows fully offline, hermetic
testing without a running Keycloak server     essential for CI and air-gapped
development.

### Tradeoff
Test tokens use a hardcoded private key committed to the repository. This is
explicitly labeled "NEVER use in production" and is gated behind
`SECUREGUARD_TEST_MODE=1`. In production mode, `keycloak_client.create_test_token()`
raises `RuntimeError`, and `validate_access_token()` rejects `TEST_KID` tokens with
401.

---

## 5. Startup Flow: Modal profile-selection gate before dashboard

### Decision
Authentication happens in a modal `StartupProfileDialog` (`startup_profile.py`) that
must be accepted before `SecureGuardDashboard` is constructed. The dialog has four
tabs: Quick Profile (test mode only), Manual Token, MFA Token, and Token JTI. Auto-auth
only occurs when `SECUREGUARD_AUTO_AUTH=1` is explicitly set (headless CI).

### Rationale
The previous design had profile switching inside the dashboard, which meant the
console could render unauthenticated or with a stale identity. Moving auth to a
pre-dashboard gate guarantees every command that reaches the pipeline carries a
validated `AuthContext`. Quick Profile buttons give operators one-click login in
test mode without forcing auto-login (auto-login is opt-in via env var).

### Tradeoff
The extra dialog adds one click to every launch in test mode. This is accepted as
the correct security posture: identity is established before any UI surface exists.

---

## 6. UI Design: Flat industrial HMI, no gradients, sharp corners, monospace numerics

### Decision
`industrial_theme.py` enforces an austere design contract: flat solid fills only,
sharp 90-degree corners (zero border-radius), crisp 1px borders, no shadows, no
gradients, and monospaced fonts for all measured values. Amber is the primary action
colour; signal green/amber/red are reserved for state only.

### Rationale
Industrial HMI practice dictates that chrome must recede behind process data. Rounded
corners, gradients, drop shadows, and pastel colours are consumer-software idioms
that reduce legibility under harsh plant-floor lighting and increase the risk of
an operator misreading a state. Monospaced digits prevent column jitter when values
change width, which otherwise reads as data instability even when the signal is
steady.

### Tradeoff
The aesthetic is deliberately utilitarian and will not win design awards. Custom
widget styling requires more QSS than a default Qt look. This is accepted because
the console is safety-critical tooling, not a consumer product.

---

## 7. Persistence: SQLite + JSONL evidence ledger with Ed25519 signing

### Decision
- `secureguard.db`     SQLite for pipeline state, dual-control store, thresholds.
- `evidence_log.jsonl`     append-only JSONL forensic ledger, each record signed with
  an Ed25519 key (`crypto_audit.py`), chain-hashed (`verify_log.py`).
- `risk_thresholds.json`     operator-editable risk thresholds persisted per data dir.

### Rationale
SQLite is serverless, zero-config, and ACID     appropriate for a single-operator
console with no DBA. The JSONL ledger provides tamper evidence: each record references
the previous record's hash, and Ed25519 signatures make post-hoc modification
cryptographically detectable. Thresholds in JSON are human-editable for tuning
without code changes.

### Tradeoff
SQLite has no built-in replication or multi-writer concurrency. The docker-compose
deployment warning (`docker-compose.yml:146-153`) documents that two containers
sharing `/data` can fork the evidence chain or lock the database. This is accepted
because the intended deployment is one dashboard instance per data directory.

---

## 8. Backend Architecture: SecureGuardPipeline with digital twin + risk engine

### Decision
`SecureGuardPipeline` (`pipeline.py`) is the central command processor. Each command
passes through: (1) auth gate, (2) digital-twin prediction, (3) safety-envelope
check, (4) hardware telemetry read (client overrides never accepted), (5)
multi-dimensional risk assessment, (6) state-machine transition. Each stage has a
configurable timeout via `timeout_utils.py`.

### Rationale
Command processing must be deterministic and auditable. The digital twin predicts
the physical outcome before any actuator command is accepted. The safety envelope
rejects physically dangerous setpoints. Hardware telemetry is the sole source of
ground truth     client-provided speed/temperature/current values are never trusted.
Risk assessment is multi-dimensional (speed, current, temperature, box rate) so a
single-sensor fault cannot mask a real hazard.

### Tradeoff
Every command incurs the latency of twin prediction + risk assessment + telemetry
read. Timeouts are generous (default 900s for pipeline commands) to avoid rejecting
valid commands on loaded hosts. This is accepted because an incorrect acceptance is
far worse than a delayed rejection in a governance system.

---

## 9. Containerization: Docker + docker-compose, two services

### Decision
`Dockerfile.api` builds the FastAPI service; `Dockerfile.dashboard` builds the
PySide6 console headless under Xvfb with `QT_QPA_PLATFORM=offscreen` and
`QT_QPA_FONTDIR` pointing at DejaVu fonts. Both run as unprivileged uid 10001.
They share a `secureguard-data` volume for evidence, SQLite, and the audit key.

### Rationale
The API and dashboard are independently deployable. The dashboard is headless by
design: it renders evidence and writes the ledger, but there is no VNC or display
export. Xvfb provides the X display required by `QOpenGLWidget` (3D view), while
the offscreen platform plugin keeps Qt off the window system. The font directory is
load-bearing     without it, `QFontDatabase.families()` returns 0 families and all
text metrics are degenerate.

### Tradeoff
Running PySide6 headless under Xvfb is more complex than a pure-FastAPI deployment.
The dashboard container has no network surface, so it can only be observed via logs.
This is accepted because the dashboard is an operator console, not a service.

---

## 10. Test Strategy: Isolated temp data dir, 103 tests, design-system compliance guard

### Decision
`conftest.py` sets `SECUREGUARD_DATA_DIR` to a per-session temp directory and resets
cached module globals before any test module imports `evidence_log`/`persistence`/
`dual_control_store`/`verify_log`. `test_ui_compliance.py` is a static + behavioral
guard enforcing the industrial HMI design contract (sharp corners, 1px borders, no
gradients, monospace numerics, step-line charts).

### Rationale
Tests must never write to the production ledger (`evidence_log.jsonl`, `secureguard.db`,
etc.) in the repo root. The top-level conftest code runs at import time, before any
module caches a repo-root path, guaranteeing isolation. The compliance guard prevents
design drift     any future "modernisation" that adds rounded corners or pastel colours
will fail the test suite.

### Tradeoff
The compliance guard is implementation-coupled to the theme tokens. If the theme
contract changes intentionally, the tests must be updated in the same PR. This is
accepted because the design contract is itself a deliberate, documented decision.

---

## 11. Token Claims: JTI added for audit traceability

### Decision
Test tokens include a `jti` (JWT ID) claim (`tests/fixtures/test_keys.py:104`), and
`AuthContext.token_jti` exposes it (`keycloak_auth.py:74`). The Startup Profile
dialog's JTI tab displays it after authentication.

### Rationale
JTI provides a unique token identifier for audit traceability and replay detection.
Without JTI, two tokens with identical claims are indistinguishable in the evidence
ledger, making it impossible to correlate a command to a specific token issuance.

### Tradeoff
Adding JTI increases token size negligibly and requires the test-key fixture to
generate UUIDs. No production downside; real Keycloak also issues JTI by default.

---

## 12. MFA Model: OTP/TOTP via AMR claim + `mfa_verified` flag

### Decision
MFA is detected via the JWT `amr` claim (values `otp`/`totp`/`mfa`) or a custom
`otp_verified=true` claim. In test mode, MFA is simulated by the `mfa_verified`
flag on test profiles. MFA freshness is time-windowed (default 300s).

### Rationale
Keycloak issues AMR claims during authentication; reading them avoids a separate
MFA verification round-trip. The time window prevents a stale MFA from satisfying
step-up gates indefinitely.

### Tradeoff
Test-mode MFA is simulated, not real. A test operator with `mfa_verified=true` bypasses
actual OTP entry. This is explicitly limited to `SECUREGUARD_TEST_MODE=1`.

---

## 13. High DPI Scaling: AA_EnableHighDpiScaling + AA_UseHighDpiPixmaps + PassThrough

### Decision
High DPI attributes are set before `QApplication` creation in both `main_qt.py` and
`dashboard_qt.py`, with `PassThrough` rounding policy. `QT_ENABLE_HIGHDPI_SCALING=1`
and `QT_AUTO_SCREEN_SCALE_FACTOR=1` are set as environment defaults.

### Rationale
Operator stations range from 1080p to 4K monitors. Qt's high-DPI scaling ensures the
HMI remains readable at 125%, 150%, and 200% scaling. Setting the attributes before
`QApplication` construction is required     Qt reads them once at startup.

### Tradeoff
`PassThrough` rounding can produce fractional pixel sizes on some displays. This is
accepted as the least-bad option; the alternative (rounding) can make widgets
disproportionately large on high-density screens.

---

## 14. Data Directory Resolution: SECUREGUARD_DATA_DIR > frozen exe dir > module dir

### Decision
`app_paths.py` resolves persistent data locations in this order: `SECUREGUARD_DATA_DIR`
env var, then the frozen executable's directory (PyInstaller), then the module's
directory. All SQLite, JSONL, and threshold files route through `data_file()`.

### Rationale
In a frozen build, the executable directory may be read-only (e.g., `C:\Program Files`).
The env var gives operators control over where evidence and databases live. Tests
override it with a temp dir via `conftest.py` to avoid contaminating production files.

### Tradeoff
Multiple resolution paths add indirection. A misconfigured `SECUREGUARD_DATA_DIR`
can split data across locations. This is accepted because the env-var-first pattern
is standard for portable desktop applications.

---

## 15. Teardown: Explicit Qt-safe resource release on close

### Decision
`SecureGuardDashboard._tear_down()` stops all timers, terminates the telemetry
streamer thread, shuts down dashboard sync, detaches and `deleteLater()`s all tabs
(including the OpenGL 3D view), and flushes deferred delete events before the
QApplication exits. `aboutToQuit` is wired to the same handler.

### Rationale
`QOpenGLWidget` destruction must happen while the QApplication is alive; otherwise
the GL context is finalized against a dead Qt object tree, causing
`STATUS_STACK_BUFFER_OVERRUN (0xC0000409)`. Live `QThread`s at interpreter exit
abort the process with the same error.

### Tradeoff
Teardown code is defensive and duplicated across `closeEvent` and `aboutToQuit`.
This is accepted because a hard crash on exit is worse than duplicated cleanup.

---

## 16. Library Exclusions: matplotlib, tkinter, PyQt5, PyQt6

### Decision
`SecureGround.spec` excludes `matplotlib`, `matplotlib.backends`, `tkinter`,
`PyQt5`, and `PyQt6` from the frozen build.

### Rationale
matplotlib and tkinter are unused (charts use pyqtgraph; GUI uses PySide6).
PyQt5/PyQt6 are excluded to prevent pyqtgraph from binding to the wrong Qt at
runtime, which was a recurring source of crashes during development.

### Tradeoff
If a future feature requires matplotlib (e.g., complex statistical plots), it would
need to be re-added and the binding pin re-verified. No such feature is planned.

---

## 17. Versioning: 1.0.0 for dashboard, 0.4.0 for container images

### Decision
`dashboard_qt.main()` sets application version `1.0.0`. Docker images are tagged
`secureguard-api:0.4.0` and `secureguard-dashboard:0.4.0`.

### Rationale
The desktop application has reached a stable 1.0 release. Container images are
versioned independently (0.4.0) because the containerization work is more recent
and still iterating.

### Tradeoff
Divergent version schemes can confuse operators. The application version is what
appears in the title bar and About dialog; image tags are internal to CI/CD.

---

## 18. Error Handling: Defensive try/except everywhere in UI, strict in auth

### Decision
UI code (`dashboard_qt.py`, `startup_profile.py`) wraps every external call in
try/except with status-bar feedback. Auth code (`keycloak_auth.py`) raises
`HTTPException` on any validation failure with no silent fallbacks.

### Rationale
The console must never crash in front of an operator     a status-bar message and a
stale screen are preferable to a disappearing window. Auth must never silently
accept an invalid token     a rejected command is the correct outcome.

### Tradeoff
Defensive UI error handling can mask real bugs during development. Tests (`test_*`)
are the backstop: if the UI silently swallows an error, the corresponding test
asserts on the expected behaviour instead.

---

## 19. Threading: QThread for telemetry, no background threads for UI updates

### Decision
`hardware_telemetry.TelemetryStreamer` runs in a `QThread` and emits signals to
the main thread. All UI updates happen on the main thread via Qt signals/slots.
`dashboard_sync.py` provides `shutdown_dashboard_sync()` for orderly thread exit.

### Rationale
Qt requires all GUI operations on the main (GUI) thread. Telemetry polling is
I/O-bound and belongs on a worker thread. Signals marshal data across the thread
boundary safely.

### Tradeoff
Signal-slot marshalling adds latency (queued connections). This is accepted    
telemetry updates at 2s intervals, far slower than the marshal cost.

---

## 20. Legacy Code: archive/ preserved but not imported

### Decision
`archive/deprecated/` contains historical versions of dashboard modules (Tkinter
era, PyQt6 migration, partial rewrites). These are tracked in git via `.gitignore`
re-include rules but are not imported by any live code.

### Rationale
Preserving legacy code provides reference for how the system evolved and allows
recovery if a migration introduced a regression. The `.gitignore` re-includes
exactly the files that were previously tracked, so nothing is silently lost.

### Tradeoff
The archive tree adds noise to the repository. It is excluded from Docker builds
and PyInstaller packages, so it carries no runtime cost.

---

## 21. Logging: Status bar + stdout, no file logging in console

### Decision
The console reports errors via `QStatusBar.showMessage()` and stdout/stderr. The
API service logs via uvicorn's default logging. No rotating file logger is
configured for the desktop application.

### Rationale
An operator console is observed interactively; a status bar message is visible
immediately. File logs on an operator station are rarely checked and can fill a
disk. The evidence ledger is the system of record for audit, not log files.

### Tradeoff
Intermittent failures that don't produce a status bar message may go unnoticed.
The test suite and evidence ledger are the mitigation.

---

## 22. Security: No hardcoded production secrets, env-driven configuration

### Decision
All credential-shaped values (Keycloak URLs, client secrets, issuer, audience) are
read from environment variables with safe defaults pointing to internal endpoints.
No production tokens or keys are committed. The only committed key is the test RSA
pair in `tests/fixtures/test_keys.py`, explicitly test-only.

### Rationale
12-factor configuration keeps secrets out of source control. The test key is
necessary for hermetic testing but is gated behind `SECUREGUARD_TEST_MODE=1`.

### Tradeoff
Operators must set environment variables correctly for production deployments. A
misconfigured `KEYCLOAK_ISSUER` causes all token validation to fail. Docker
Compose uses `${VAR:-default}` syntax to document required variables.

---

<!-- End of decisions.md -->
