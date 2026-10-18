# SecureGuard Governance Model - Code Execution Flow

This document maps the complete execution flow of the SecureGuard operator console:
the entry point, the sequence of initialization, the relationships between files
and functions, and the function call graph. It covers both the normal startup path
and the runtime timer network.

---

## 1. Entry Point

### `main_qt.py:main()` - PySide6 launcher

This is the process entry point (`python main_qt.py` or `dist/SecureGuard.exe`).

```
main_qt.main()
  +--- Sets env vars (before QApplication):
  |     QT_ENABLE_HIGHDPI_SCALING=1
  |     QT_AUTO_SCREEN_SCALE_FACTOR=1
  |     SECUREGUARD_TEST_MODE=1
  |     PYQTGRAPH_QT_LIB=PySide6            <-- binds pyqtgraph to PySide6
  |
  +--- Creates QApplication with High DPI attributes:
  |     AA_EnableHighDpiScaling
  |     AA_UseHighDpiPixmaps
  |     PassThrough scale factor rounding
  |
  +--- run_startup_profile_gate(app)              <-- startup_profile.py
  |     \--- Returns (auth, token) or (None, None) if cancelled
  |
  +--- If auth is None -> sys.exit(0)
  |
  \--- dashboard_qt.main(argv, auth=auth, token=token)       <-- dashboard_qt.py
        \--- Returns (app, window); sys.exit(app.exec())
```

**Key design point:** All bootstrap logic (theme, fonts, DPI policy, dashboard construction, teardown wiring) lives in `dashboard_qt.main()`, so the packaged entry point (`main_qt.py`) and a direct `python dashboard_qt.py` run cannot drift apart.

---

## 2. Startup Profile Gate (Authentication Before Dashboard)

### `startup_profile.py:run_startup_profile_gate(app)` -> `StartupProfileDialog.exec()`

The startup dialog is a modal `QDialog` that must be accepted before `SecureGuardDashboard` is constructed. It has four tabs:

| Tab | Purpose | Available in production? |
|-----|---------|--------------------------|
| Quick Profile | One-click login as operator01 / supervisor01 / engineer01 / auditor01 | Test mode only |
| Manual Token | Paste a JWT token manually | Yes |
| MFA Token | MFA configuration info + quick MFA profiles | Test mode only |
| Token JTI | Displays the `jti` (JWT ID) of the authenticated token | Yes |

**Call graph:**

```
run_startup_profile_gate(app)                              [startup_profile.py:351]
  \--- StartupProfileDialog.__init__(parent, on_authenticated)
       +--- _build_ui()                                        [line 58]
       |     +--- Builds 4-tab QTabWidget (Quick Profile / Manual Token / MFA Token / JTI)
       |     +--- Quick Profile: creates QPushButton per profile
       |     |     \--- clicked -> _login_test_profile(username, roles, mfa)
       |     +--- Manual Token: QTextEdit + "LOGIN WITH TOKEN" button
       |     |     \--- clicked -> _login_manual_token()
       |     \--- JTI tab: QLabel for JTI display
       |
       +--- If SECUREGUARD_AUTO_AUTH=1 -> QTimer.singleShot(0, _auto_authenticate_test)
       |     \--- create_test_token("supervisor01", [...], mfa_verified=True)
       |     \--- validate_access_token(token)
       |     \--- self.accept()
       |
       \--- dialog.exec()                       <-- blocks until accepted or cancelled
             +--- _login_test_profile(username, roles, mfa)
             |     +--- create_test_token(username, roles, mfa_verified=mfa)
             |     |     \--- [tests/fixtures/test_keys.py] create_test_token()
             |     |           \--- jwt.encode(claims, TEST_PRIVATE_KEY, RS256, kid=TEST_KID)
             |     +--- validate_access_token(token)           [keycloak_auth.py:134]
             |     |     +--- jwt.get_unverified_header(token) -> kid
             |     |     +--- kid == TEST_KID -> use TEST_PUBLIC_KEY
             |     |     \--- jwt.decode(token, key, RS256, audience, issuer)
             |     |           \--- Returns AuthContext(subject, username, roles, mfa_verified, token_jti, ...)
             |     +--- self._update_jti_display(auth)
             |     +--- on_authenticated(auth, token)  (callback to main_qt.main)
             |     \--- self.accept()
             |
             +--- _login_manual_token()
             |     +--- validate_access_token(token_text)
             |     +--- self._update_jti_display(auth)
             |     +--- on_authenticated(auth, token)
             |     \--- self.accept()
             |
             \--- _auto_authenticate_test()  (headless CI only)
                   +--- create_test_token("supervisor01", ["operator","supervisor"], mfa_verified=True)
                   \--- validate_access_token(token)
```

**Auth validation - `keycloak_auth.py:validate_access_token()`:**

```
validate_access_token(token, request=None)
  +--- jwt.get_unverified_header(token) -> header
  +--- key_id = header["kid"]
  |
  +--- If key_id == TEST_KID ("secureguard-test-key"):
  |     +--- Requires SECUREGUARD_TEST_MODE=1, else 401
  |     \--- verification_key = TEST_PUBLIC_KEY (hardcoded RSA 2048 PEM)
  |
  +--- Else (production Keycloak):
  |     +--- _load_jwks() -> fetch JWKS from KEYCLOAK_JWKS_URL (cached 300s)
  |     +--- Find key with matching kid in JWKS keys[]
  |     \--- verification_key = RSAAlgorithm.from_jwk(key_data)
  |
  +--- jwt.decode(token, verification_key, algorithms=["RS256"],
  |           audience=AUDIENCE, issuer=ISSUER,
  |           options={"require": ["exp","iat","iss","sub"]})
  |
  +--- Extract claims:
  |     roles       = realm_access.roles
  |     amr         = authentication methods (otp/totp/mfa)
  |     mfa_verified = ("otp"|"totp"|"mfa" in amr) or otp_verified==True
  |     mfa_challenge_ts = custom claim
  |     token_jti   = claims["jti"]
  |     token_issued_at = claims["iat"]
  |     token_expires_at = claims["exp"]
  |
  \--- Return AuthContext(subject, username, roles, mfa_verified, ...)
```

---

## 3. Dashboard Construction

### `dashboard_qt.py:main(argv, auth, token)` -> `SecureGuardDashboard`

```
dashboard_qt.main(argv, auth, token)                           [line 2823]
  +--- QApplication with High DPI attributes
  +--- apply_theme(app)                                          [industrial_theme.py:687]
  |     +--- app.setStyle("Fusion")
  |     +--- Resolve monospace font family (JetBrains Mono > SF Mono > Consolas)
  |     +--- Re-point INDUSTRIAL_QSS monospace rules at resolved family
  |     +--- app.setStyleSheet(INDUSTRIAL_QSS)                       ~680-line QSS
  |     +--- app.setPalette(palette)  (Window, Text, Button, Highlight, ...)
  |     +--- app.setFont(QFont(FONT_UI, 10))                         single 10pt UI size
  |     \--- Set per-class monospace font for QTableView/QTableWidget/QHeaderView
  |
  +--- apply_plot_theme(pg)                                      [industrial_theme.py:762]
  |     +--- pyqtgraph.setConfigOption("background", BG_INSET)
  |     +--- pyqtgraph.setConfigOption("foreground", TEXT_DIM)
  |     +--- pyqtgraph.setConfigOption("antialias", False)           no trace smoothing
  |     \--- ... (defensive per-key, tolerates API drift)
  |
  +--- window = SecureGuardDashboard(auth=auth, token=token)     [line 1767]
  |     +--- __init__():
  |     |     +--- Responsive window sizing from screen geometry
  |     |     +--- self.pipeline = SecureGuardPipeline()          [pipeline.py:55]
  |     |     |         +--- ConveyorDigitalTwin(spec)
  |     |     |         +--- SafetyEnvelope()
  |     |     |         +--- MultiDimensionalRiskEngine(...)
  |     |     |         +--- StateStore()
  |     |     |         \--- telemetry_interface (None -> global)
  |     |     +--- self._load_thresholds()                            risk_thresholds.json
  |     |     +--- self._init_ui()                                [line 1829]
  |     |     |         +--- IdentityCard()                       (auth context strip)
  |     |     |         +--- QTabWidget with 7 tabs:
  |     |     |         |     +--- _build_overview_tab()          [line 1892]
  |     |     |         |     |     +--- QScrollArea > page widget
  |     |     |         |     |     +--- SystemStatePanel()
  |     |     |         |     |     +--- SubsystemTile[] (4 conveyors in HBox)
  |     |     |         |     |     +--- RiskGauge + CommandForm row
  |     |     |         |     |     +--- RiskThresholds + SafetyEnvelopePanel
  |     |     |         |     |     \--- EvidenceLogTab
  |     |     |         |     +--- _build_charts_tab()            (ChartsTab)
  |     |     |         |     +--- _build_evidence_tab()          (EvidenceLogTab)
  |     |     |         |     +--- _build_stream_tab()            (StreamTab)
  |     |     |         |     +--- _build_view3d_tab()            (View3DTab / Conveyor3DView)
  |     |     |         |     \--- _build_push_commands_tab()     (PushCommandsTab)
  |     |     |         +--- Toolbar: Refresh, Verify Chain
  |     |     |         \--- StatusBar: telemetry_label, heartbeat_label, clock_label
  |     |     +--- self._setup_timers()                           [line 2287]
  |     |     |         +--- clock_timer (1s) -> _tick_clock()
  |     |     |         +--- heartbeat_timer (1s) -> _tick_heartbeat()
  |     |     |         \--- subsystem_timer (5s) -> refresh_subsystems()
  |     |     +--- If auth provided: identity_card.update_auth(auth)
  |     |     +--- refresh_subsystems()
  |     |     \--- evidence_tab.reload()
  |     |
  \--- window.show()
     +--- app.aboutToQuit.connect(window._tear_down)
     \--- return (app, window)
```

---

## 4. Runtime Timer Network

The dashboard runs four timers after construction:

```
+---------------+    +-----------------+    +-------------------+    +----------------------+
|  clock_timer  |    | heartbeat_timer |    |  subsystem_timer  |    |   charts_tab chart   |
|  (1 second)   |    |   (1 second)    |    |    (5 seconds)    |    | refresh_timer (30s)  |
+-------+-------+    +--------+--------+    +---------+---------+    +----------+-----------+
        |                     |                       |                         |
        v                     v                       v                         v
  _tick_clock()        _tick_heartbeat()     refresh_subsystems()    ChartsTab.refresh_charts()
  [line 2315]          [line 2323]           [line 2337]             [charts_tab.py]
                                               |                         |
                                               +--- pipeline._get_telemetry()   Publish history
                                               +--- per subsystem:               and redraw plots
                                               |     state_store.get(sub_id)   [via _publish_chart_history]
                                               |     _read_metrics(telemetry, ...)
                                               |     thresholds.severity(metrics)
                                               |     tile.update_data(...)
                                               |     command_form.record_result(...)
                                               |     push_commands_tab.update_current_speed(...)
                                               |
                                               +--- _refresh_risk_gauge()
                                               +--- _update_telemetry_status()
                                               +--- _sample_trends()
                                               +--- _publish_chart_history()
                                               +--- system_state_panel.update_state(auth, pipeline, metrics)
                                               \--- first-paint charts if not _charts_painted
```

### `refresh_subsystems()` detailed flow [line 2337]

```
refresh_subsystems()
  +--- telemetry = pipeline._get_telemetry()           [hardware_telemetry.get_global_telemetry()]
  |
  +--- For each subsystem_id in DEFAULT_SUBSYSTEMS:
  |     +--- subsystem = pipeline.state_store.get(subsystem_id)
  |     +--- state_value = subsystem.state.value
  |     +--- metrics = _read_metrics(telemetry, subsystem_id)
  |     +--- verdict, driver = thresholds.severity(metrics)
  |     +--- display_state = verdict if (verdict in RESTRICTED/QUARANTINED and state==NORMAL) else state_value
  |     +--- tile.update_data(subsystem_id, display_state, metrics, consecutive)
  |     +--- speed = metrics["motor_speed_rpm"]
  |     |     +--- command_form.record_result(subsystem_id, speed)
  |     |     \--- push_commands_tab.update_current_speed(subsystem_id, speed)
  |     \--- alarms[subsystem_id] = {...} if QUARANTINED
  |
  +--- _refresh_risk_gauge()               aggregate risk from all subsystems
  +--- _update_telemetry_status()          status bar TEL indicator
  +--- _sample_trends()                    append one point per conveyor to trend_history
  +--- _publish_chart_history()            feed charts_tab with accumulated history
  +--- system_state_panel.update_state(auth, pipeline, metrics)
  \--- If not _charts_painted: paint charts once (avoid blank tab on first 30s)
```

---

## 5. Command Processing Flow

### Operator submits a command (SET_SPEED or Push Commands tab)

```
Dashboard command submission
  |
  +--- _on_command_submitted(subsystem_id, from_rpm, to_rpm)          [line 2533]
  |   OR  _on_push_command_submitted(subsystem_id, command_dict)   [line 2585]
  |
  +--- If self._auth is None:
  |     +--- log_auth_rejection(subsystem, command, reason)           [evidence_log.py]
  |     +--- evidence_tab.reload()
  |     \--- statusBar: "Command rejected locally: not authenticated"
  |     \--- return
  |
  +--- pipeline.process_command(
  |        subsystem_id=subsystem_id,
  |        from_speed_rpm=from_rpm,
  |        to_speed_rpm=to_rpm,
  |        cmd_type=cmd_type,
  |        accel_rate=accel_rate,
  |        decel_rate=decel_rate,
  |        torque_limit=torque_limit,
  |        direction=direction,
  |        ctrl_mode=ctrl_mode,
  |        auth=self._auth
  |     )                                                              [pipeline.py:99]
  |     |
  |     +--- if auth is None -> return rejected
  |     +--- subsystem = state_store.get(subsystem_id)
  |     +--- requirement = subsystem.required_auth()
  |     |
  |     +--- _auth_gate(requirement, auth, subsystem_id, action_desc)  [pipeline.py:75]
  |     |     +--- standard_rbac          -> operator/supervisor/engineer role check
  |     |     +--- step_up_mfa_plus_fresh_prediction                   -> mfa_verified && mfa_fresh()
  |     |     +--- step_up_mfa_plus_supervisor_approval_plus_fresh_prediction
  |     |     |         -> mfa_verified && mfa_fresh() && supervisor_approved
  |     |     |         +--- dual_control_required() -> check_dual_control(subsystem, username, action)
  |     |     |     \--- dual_control_store.check_dual_control(...)
  |     |     \--- all_actuator_commands_blocked_diagnostics_only     -> QUARANTINED, reject
  |     |
  |     +--- If not allowed -> return CommandResult(accepted=False, reason=gate_reason)
  |     |
  |     +--- Digital twin prediction (with timeout)                     [physics_digital_twin.py]
  |     |     +--- twin.predict(command, current_state, environment, dt=1.0)
  |     |     \--- predicted.trajectory
  |     |
  |     +--- Safety envelope check                                       [digital_twin.py:SafetyEnvelope]
  |     |     +--- validate(to_speed_rpm, trajectory, torque_limit, direction)
  |     |     \--- If not safe -> return rejected with safety_violations
  |     |
  |     +--- Hardware telemetry read (with timeout)                      [hardware_telemetry.py]
  |     |     +--- telemetry_interface = _get_telemetry()
  |     |     +--- set_commanded_state(subsystem_id, predicted.trajectory, ...)
  |     |     +--- health_check(subsystem_id)
  |     |     \--- read_telemetry(subsystem_id) -> TelemetryReading
  |     |           \--- observed = telemetry_reading.trajectory
  |     |     \--- source = telemetry_reading.source, quality, sequence_id
  |     |
  |     +--- Multi-dimensional risk assessment (with timeout)            [multi_dimensional_risk.py]
  |     |     +--- risk_engine.assess(prediction, observation, context, safety_violations)
  |     |     \--- risk = MultiDimensionalRisk(overall_score, overall_level, dimensions)
  |     |
  |     +--- State machine transition (with timeout)                     [state_machine.py]
  |     |     +--- subsystem.transition(risk.overall_risk_score) -> new_state
  |     |     \--- NORMAL -> DEGRADED -> RESTRICTED -> QUARANTINED
  |     |
  |     +--- Build explanation from risk dimensions
  |     |
  |     \--- Return CommandResult(accepted=True/False, reason, predicted, observed,
  |                              risk, new_state, explanation, telemetry_source, ...)
  |
  +--- If result.accepted -> statusBar "ACCEPTED - subsystem -> new_state"
  |   Else -> statusBar "REJECTED - reason"
  |
  +--- _record_command(subsystem_id, result, to_rpm)                   [line 2635]
  |     +--- Build history entry (timestamp, accepted, risk_score, risk_level, reason,
  |     |     observed/predicted metrics, ...)
  |     +--- Append to command_history[subsystem_id] (trimmed to _max_points)
  |     +--- command_form.record_result(subsystem_id, speed)
  |     +--- _write_evidence(subsystem_id, result, to_rpm)             [line 2675]
  |     |     +--- evidence_log.log_evidence(...)                      [evidence_log.py]
  |     |     |     +--- Read previous chain hash
  |     |     |     +--- Compute new chain hash
  |     |     |     +--- Ed25519 sign the record                       [crypto_audit.py]
  |     |     |     \--- Append JSONL record to evidence_log.jsonl
  |     |     \--- evidence_tab.reload()
  |     |
  |     \--- refresh_all()                                                  repaint everything
  |           +--- refresh_subsystems()
  |           \--- refresh_charts()
```

---

## 6. Key Classes and Their Responsibilities

### `SecureGuardDashboard` (dashboard_qt.py:1757)
Main window. Owns the pipeline, all 7 tabs, the timer network, and command dispatch.

### `SecureGuardPipeline` (pipeline.py:54)
Backend command processor: auth gate -> twin prediction -> safety check -> telemetry -> risk -> state transition.

### `StartupProfileDialog` (startup_profile.py:31)
Modal pre-dashboard authentication dialog with 4 tabs.

### `AuthContext` (keycloak_auth.py:67)
Frozen dataclass holding validated token identity: subject, username, roles, mfa_verified, token_jti, expiry.

### `RiskGauge` / `_CircularGaugeCanvas` (dashboard_qt.py:115 / 221)
Animated circular risk indicator with severity headline and numeric readout.

### `SubsystemTile` (dashboard_qt.py:296)
Per-conveyor status tile: asset tag, state LED, 2x2 metric grid (speed, current, temp, box rate).

### `IdentityCard` (dashboard_qt.py)
User identity strip: MFA, supervisor, dual-control, token freshness, session countdown, JTI.

### `SystemStatePanel` (dashboard_qt.py:1555)
Consolidated 2-row status banner on Overview tab: plant state, risk, alarms, governance, session.

### `PushCommandsTab` (dashboard_qt.py:1218)
14 PLC command types with dynamic parameter panel; emits `command_submitted` signal.

### `MultiDimensionalRiskEngine` (multi_dimensional_risk.py)
Assesses risk across speed, current, temperature, box rate dimensions.

### `ConveyorDigitalTwin` / `PhysicsBasedDigitalTwin` (physics_digital_twin.py)
Predicts conveyor trajectory from a command.

### `SafetyEnvelope` (digital_twin.py)
Validates that a commanded speed/torque/direction is physically safe.

### `StateStore` / `AuthState` (state_machine.py)
Holds per-subsystem state (NORMAL, DEGRADED, RESTRICTED, QUARANTINED) and transitions.

### `TelemetryStreamer` / `get_global_telemetry` (hardware_telemetry.py)
Singleton telemetry source; the only trusted source of observed values.

### `EvidenceLogTab` / `log_evidence` (evidence_tab.py / evidence_log.py)
Tamper-evident JSONL ledger with Ed25519 signatures and chain hashing.

### `ChartsTab` (charts_tab.py)
Trend charts repainted at 30s interval; displays command and telemetry history.

### `View3DTab` / `Conveyor3DView` (view3d_tab.py / qt_view3d.py)
OpenGL 3D conveyor belt visualization (QOpenGLWidget via pyqtgraph.opengl).

---

## 7. Cross-File Function Call Summary

| Caller | File:Line | Callee | File:Line | Purpose |
|--------|-----------|--------|-----------|---------|
| `main` | main_qt.py:25 | `run_startup_profile_gate` | startup_profile.py:351 | Auth gate before dashboard |
| `main` | main_qt.py:51 | `dashboard_qt.main` | dashboard_qt.py:2823 | Construct and show dashboard |
| `StartupProfileDialog._login_test_profile` | startup_profile.py:288 | `create_test_token` | keycloak_client.py:124 | Mint test JWT |
| `create_test_token` | keycloak_client.py:124 | `create_test_token` | tests/fixtures/test_keys.py:75 | Delegated test-token generation |
| `create_test_token` | tests/fixtures/test_keys.py:75 | `jwt.encode` | PyJWT | Sign RS256 token with test key |
| `StartupProfileDialog._login_*` | startup_profile.py:291/312 | `validate_access_token` | keycloak_auth.py:134 | Validate JWT -> AuthContext |
| `validate_access_token` | keycloak_auth.py:134 | `_load_jwks` | keycloak_auth.py:110 | Fetch Keycloak JWKS (production) |
| `validate_access_token` | keycloak_auth.py:134 | `jwt.decode` | PyJWT | Verify signature and claims |
| `dashboard_qt.main` | dashboard_qt.py:2823 | `apply_theme` | industrial_theme.py:687 | Install QSS, palette, fonts |
| `dashboard_qt.main` | dashboard_qt.py:2823 | `apply_plot_theme` | industrial_theme.py:762 | Configure pyqtgraph dark theme |
| `SecureGuardDashboard.__init__` | dashboard_qt.py:1767 | `SecureGuardPipeline()` | pipeline.py:55 | Construct backend pipeline |
| `SecureGuardDashboard._init_ui` | dashboard_qt.py:1829 | `_build_overview_tab` | dashboard_qt.py:1892 | Build Overview tab |
| `SecureGuardDashboard._init_ui` | dashboard_qt.py:1829 | `_build_push_commands_tab` | dashboard_qt.py:1799 (approx) | Build Push Commands tab |
| `SecureGuardDashboard._setup_timers` | dashboard_qt.py:2287 | `QTimer.timeout -> refresh_subsystems` | dashboard_qt.py:2337 | 5s telemetry poll |
| `refresh_subsystems` | dashboard_qt.py:2337 | `pipeline._get_telemetry` | pipeline.py:68 | Get telemetry interface |
| `refresh_subsystems` | dashboard_qt.py:2337 | `tile.update_data` | dashboard_qt.py:296+ | Update per-conveyor tile |
| `_on_command_submitted` | dashboard_qt.py:2533 | `pipeline.process_command` | pipeline.py:99 | Process command through full pipeline |
| `process_command` | pipeline.py:99 | `_auth_gate` | pipeline.py:75 | Authorization check |
| `process_command` | pipeline.py:99 | `twin.predict` | physics_digital_twin.py | Digital twin prediction |
| `process_command` | pipeline.py:99 | `safety_envelope.validate` | digital_twin.py | Safety check |
| `process_command` | pipeline.py:99 | `telemetry_interface.read_telemetry` | hardware_telemetry.py | Read observed telemetry |
| `process_command` | pipeline.py:99 | `risk_engine.assess` | multi_dimensional_risk.py | Risk assessment |
| `process_command` | pipeline.py:99 | `subsystem.transition` | state_machine.py | State machine transition |
| `_write_evidence` | dashboard_qt.py:2675 | `log_evidence` | evidence_log.py | Append signed record to ledger |
| `PushCommandsTab._execute_pending_command` | dashboard_qt.py:1509 | `command_submitted.emit` | dashboard_qt.py:1227 | Signal command to dashboard |
| `IdentityCard.tick_session` | dashboard_qt.py | `_tick_clock` calls this | dashboard_qt.py:2315 | Session countdown tick |
| `SystemStatePanel.update_state` | dashboard_qt.py:1640 | Called by `refresh_subsystems` | dashboard_qt.py:2390 | Update consolidated status |

---

## 8. File Inventory

### Core application (shipped in Docker + PyInstaller)

| File | Role |
|------|------|
| `main_qt.py` | Entry point; env vars, QApplication, startup gate, dashboard launch |
| `dashboard_qt.py` | Main window, all 7 tabs, timer network, command dispatch, evidence writing |
| `startup_profile.py` | Pre-dashboard authentication dialog (4 tabs) |
| `industrial_theme.py` | Design system: colour tokens, QSS, font resolution, plot/theme styling |
| `pipeline.py` | `SecureGuardPipeline`: auth -> twin -> safety -> telemetry -> risk -> state |
| `config.py` | Timeout, conveyor, and app configuration (env-overridable) |
| `keycloak_auth.py` | JWT validation, `AuthContext`, test/production modes |
| `keycloak_client.py` | Keycloak OIDC client; delegates test tokens to fixtures |
| `state_machine.py` | `StateStore`, `AuthState`: conveyor states and transitions |
| `digital_twin.py` | `SafetyEnvelope`: physical safety validation |
| `physics_digital_twin.py` | `ConveyorDigitalTwin`: trajectory prediction |
| `multi_dimensional_risk.py` | Multi-dimensional risk engine |
| `causal_xai.py` | Causal explanations for risk decisions |
| `hardware_telemetry.py` | Singleton telemetry source (only trusted observed values) |
| `evidence_log.py` | Tamper-evident JSONL ledger with Ed25519 signing |
| `verify_log.py` | Chain verification (detects tampering) |
| `crypto_audit.py` | Ed25519 audit signing key generation and verification |
| `persistence.py` | SQLite persistence layer |
| `dual_control_store.py` | Dual-control approval store (WAL-mode SQLite) |
| `evidence_tab.py` | Evidence log tab UI |
| `charts_tab.py` | Trend charts tab |
| `view3d_tab.py` / `qt_view3d.py` | 3D conveyor visualization (OpenGL) |
| `timeout_utils.py` | Timeout context managers for pipeline stages |
| `dashboard_sync.py` | Cross-dashboard synchronization |
| `app_paths.py` | Data directory resolution (env > frozen exe > module) |
| `create_shortcut_qt.py` | Windows shortcut creator |

### Tests

| File | Tests |
|------|-------|
| `test_ui_compliance.py` | Design-system compliance: sharp corners, 1px borders, no gradients, monospace numerics |
| `test_profile_switch.py` | Startup profile gate end-to-end |
| `test_pipeline.py` | Command processing, auth, risk, dual control, evidence |
| `test_keycloak_auth.py` | Token validation: valid/expired/wrong-audience/rogue-key/MFA/dual-control/freshness |
| `test_evidence_chain.py` | Chain hash integrity, Ed25519 signatures, tamper detection |
| `test_dashboard_evidence.py` | Dashboard commands reach the ledger |
| `test_compile.py` | Problematic code pattern detection |
| `tests/fixtures/test_keys.py` | Test RSA key pair, test token generation, test profiles |
| `conftest.py` | Test isolation: temp data dir, seeded ledger, DB handle cleanup |

### Build / packaging / containerization

| File | Role |
|------|------|
| `SecureGuard.spec` | PyInstaller spec: entry point `main_qt.py`, 21 data files, 18+ hidden imports |
| `requirements.txt` | PySide6, pyqtgraph, PyOpenGL, numpy, fastapi, pydantic, uvicorn, PyJWT, cryptography, pytest, httpx |
| `Dockerfile.api` | FastAPI service container (python:3.12-slim, uid 10001) |
| `Dockerfile.dashboard` | PySide6 console container under Xvfb + offscreen Qt, DejaVu fonts |
| `docker-compose.yml` | Two services (api + dashboard), shared `secureguard-data` volume |
| `.dockerignore` | Standard Docker exclusions |

### Documentation

| File | Role |
|------|------|
| `decisions.md` | This decision log (technical decisions, rationale, tradeoffs) |
| `flow.md` | This execution flow document (entry point, call graph, file inventory) |
| `containers.md` | Container deployment guide |
| `dashboard_restoration_plan.md` | Restoration plan |
| `safety_twin_report.md` | Person 3 completion report |
| `advancement_roadmap.md` | Person 4 roadmap |
| `analysis_and_run_guide.md` | Analysis and run guide |

### Generated / runtime artifacts (not committed, gitignored)

| Path | Role |
|------|------|
| `dist/SecureGuard.exe` | Packaged executable (~73 MB) |
| `build/SecureGuard/` | PyInstaller intermediate build output |
| `secureguard.db` / `dual_control.db` | SQLite databases |
| `evidence_log.jsonl` | Forensic evidence ledger |
| `risk_thresholds.json` | Operator-editable risk thresholds |
| `audit_key.pem` | Ed25519 signing key |
| `.kilo/` | **(Removed)** - Kilo agent tooling artifacts |

---

## 9. Execution Summary (End-to-End)

```
1. User runs:  python main_qt.py   (or double-clicks dist/SecureGuard.exe)
2. main_qt.main() sets env vars, creates QApplication
3. StartupProfileDialog appears - operator selects a profile (Quick Profile in test mode,
   or pastes a token on Manual Token tab)
4. create_test_token() mints a JWT -> validate_access_token() verifies it -> AuthContext
5. dashboard_qt.main() constructs QApplication, applies industrial theme + plot theme
6. SecureGuardDashboard.__init__() builds pipeline, all 7 tabs, starts timers
7. Window shows; subsystem_timer polls telemetry every 5s, updating tiles, risk gauge, charts
8. Operator submits a command -> pipeline.process_command() runs full governance pipeline
9. Result written to evidence ledger (signed JSONL), dashboard refreshed
10. On close: _tear_down() stops timers, retires OpenGL context, flushes deferred deletes
```

<!-- End of flow.md -->
