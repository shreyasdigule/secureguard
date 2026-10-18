# SecureGuard Dashboard Restoration Plan

## Objective
Complete the PySide6 dashboard by implementing all missing components and adding dynamic timeout handling for slow computations to prevent upstream timeout errors.

---

## Current State
- **Framework**: PySide6 (migrated from PyQt6 across 9 files)
- **Core Logic**: All functional (22/22 tests passing)     pipeline, physics twin, risk engine, XAI, Keycloak auth, dual-control store
- **GUI**: Partial `dashboard_qt.py` with widget definitions but missing `SecureGuardDashboard` main window class
- **Tabs**: `ChartsTab`, `StreamTab`, `EvidenceDetailDialog`, `View3DTab`, `Conveyor3DView` exist but not integrated

---

## Missing Components to Implement

### 1. Dynamic Timeout / Retry Infrastructure (P0     prevents upstream timeouts)

| File | Change |
|------|--------|
| `timeout_utils.py` (new) | `DynamicTimeout` class with exponential backoff, configurable base/max timeout, jitter |
| `pipeline.py` | Wrap `process_command()` and physics twin calls with dynamic timeout |
| `multi_dimensional_risk.py` | Add timeout to risk computation loops |
| `causal_xai.py` | Add timeout to counterfactual generation |
| `evidence_tab.py` | Increase `TelemetryStreamer` tick interval from 1s to configurable (default **5s**) |
| `charts_tab.py` | Make chart refresh timer configurable (default **30s**) |
| `qt_view3d.py` | Make animation frame interval configurable (default **33ms = 30 FPS**) |

**Timeout Configuration**:
```python
# Base timeout for fast ops: 60s (was 5s)     increased to avoid upstream idle timeout
# Slow computation timeout: 300s / 5min (was 30s)     pipeline, risk, XAI physics computations
# Max retry timeout: 600s / 10min (was 120s)     total budget with retries
# Backoff: exponential (2x) + jitter (+▒10%)
# Telemetry streamer tick interval: 5s (was 1s/2s)     reduce polling frequency
# Chart refresh timer: 30s (was 5s)     reduce UI refresh rate
# 3D animation frame: 33ms / 30 FPS (was 16ms/60 FPS)     reduce GPU load
```

**Environment Variable Overrides** (for deployment tuning):
```python
SECUREGUARD_BASE_TIMEOUT=60
SECUREGUARD_SLOW_TIMEOUT=300
SECUREGUARD_MAX_TIMEOUT=600
SECUREGUARD_TELEMETRY_INTERVAL=5
SECUREGUARD_CHART_REFRESH=30
SECUREGUARD_3D_FPS=30
```

### 2. Main Dashboard Window (`dashboard_qt.py`)

**Add `SecureGuardDashboard(QMainWindow)` class with**:
- `_init_ui()`     central widget, tab widget, toolbars, status bar
- `_build_overview_tab()`     3+--ù `SubsystemTile`, `RiskGauge`, command form (`QComboBox` subsystem, `QDoubleSpinBox` speed, `QPushButton` submit)
- `_build_charts_tab()`     instantiate `ChartsTab()`
- `_build_evidence_tab()`     `QTableWidget` + double-click -> `EvidenceDetailDialog`
- `_build_stream_tab()`     instantiate `StreamTab()`
- `_build_3d_view_tab()`     instantiate `View3DTab()`
- `_setup_timers()`     clock (1s), heartbeat (1s), chart refresh (**30s**), stream UI (**5s**)
- `refresh_subsystems()`     query pipeline state, update tiles
- `refresh_charts()`     delegate to `ChartsTab.refresh_charts()`
- `_on_command_submit()`     call pipeline with dynamic timeout, update UI on result

### 3. Auth Widgets (`auth_widgets.py`     new file)

| Widget | Purpose |
|--------|---------|
| `AuthLoginWidget` | Username/password + MFA field, "Login" button, connects to `keycloak_client.create_test_token()` in test mode |
| `TokenInputDialog` | `QDialog` with `QTextEdit` for manual JWT paste, validates via `validate_access_token()` |
| `ProfileCard` | Compact user display (avatar, roles, MFA status)     reuse `IdentityCard` logic |

**Integration**: Show `AuthLoginWidget` on first launch if not `SECUREGUARD_TEST_MODE`; on success, emit `authenticated(AuthContext, token)` to main window.

### 4. Risk Configuration UI

**Add `RiskConfigWidget(QWidget)`** (in `dashboard_qt.py` or new `risk_config.py`):
- `QDoubleSpinBox` for each threshold: `OVER_TEMPERATURE_C` (85.0), `OVER_CURRENT_A` (15.0), `OVER_SPEED_RPM` (500.0), `BOX_RATE_LOW` (10.0)
- `QPushButton` "Apply" -> emits `thresholds_changed(dict)` 
- Connect to `SecureGuardPipeline.update_risk_thresholds()` (add method to pipeline)

**Visual feedback**: SubsystemTile color bar shifts from green->yellow->red as metrics approach thresholds.

### 5. Safety Envelope Visualization

**Add to OverviewTab**:
- Read-only `QGroupBox` showing current safety limits from `physics_digital_twin.py`
- Motor: 7.5 kW, max 15A, max 500 RPM (configurable)
- Temperature: 85+ C alert, 100+ C shutdown
- Color-coded labels (green/yellow/red) based on current telemetry

### 6. Export Evidence Functionality

**In `evidence_tab.py` / `dashboard_qt.py`**:
- `_export_evidence()`     `QFileDialog.getSaveFileName()`, write JSONL to CSV/JSON
- Wire to toolbar "Export Evidence" action

---

## Integration Wiring

| Signal | Source | Target |
|--------|--------|--------|
| `command_submitted(subsystem, from_rpm, to_rpm)` | OverviewTab command form | `SecureGuardDashboard._on_command_submit()` |
| `pipeline_result(result)` | Pipeline (async) | Update tiles, charts, evidence table |
| `authenticated(auth, token)` | AuthLoginWidget | `SecureGuardDashboard._on_auth_callback()` |
| `thresholds_changed(dict)` | RiskConfigWidget | `SecureGuardPipeline.update_risk_thresholds()` |
| `stream_tick(data)` | TelemetryStreamer | StreamTab charts + View3DTab animation |
| `evidence_double_clicked(record)` | Evidence table | `EvidenceDetailDialog.show()` |

---

## Validation Checklist (must pass before merge)

1. `python main_qt.py` launches without errors
2. Login works (test mode auto-advance; manual token dialog works)
3. Command form -> pipeline -> evidence log chain completes
4. Charts tab refreshes with live data (**30s timer**)
5. Live stream starts/stops at configurable rate (default **0.2 Hz / 5s interval**)
6. Evidence detail dialog opens on double-click with forensic data
7. 3D view starts/stops at **30 FPS** (configurable frame interval)
8. Risk threshold changes propagate to pipeline and tile colors
9. All 22 existing tests pass
10. `pyinstaller SecureGuard.spec` -> `dist/SecureGuard.exe` runs identically

---

## Risks

| Risk | Mitigation |
|------|------------|
| Import cycles (dashboard     pipeline     risk) | Keep `dashboard_qt.py` imports local to methods; use `TYPE_CHECKING` for type hints |
| Dynamic timeout masks real hangs | Log timeout events with stack trace; alert after 3 consecutive timeouts |
| 3D view FPS drops on integrated dashboard | Keep `Conveyor3DView` timer independent; test on target hardware |

---

## Open Questions (resolve before implementation)

1. **Timeout defaults**: Are 5s/30s/120s appropriate for the target hardware, or should they be env-configurable?
2. **Auth flow**: Should test mode bypass login entirely, or show a "Quick Profile" picker (already in `ProfileSwitcherDialog`)?
3. **Risk thresholds**: Persist to config file or only in-memory per session?

---

## Next Steps
1. Create `timeout_utils.py` with `DynamicTimeout` class
2. Update `pipeline.py`, `multi_dimensional_risk.py`, `causal_xai.py` to use dynamic timeouts
3. Complete `SecureGuardDashboard` in `dashboard_qt.py`
4. Create `auth_widgets.py`
5. Add `RiskConfigWidget` and wire to pipeline
6. Build and test executable
