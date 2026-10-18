# SecureGuard Governance Model (SGGM) -- Comprehensive Master Documentation

> **Consolidated Specification, Architecture, Decisions, Run Guide, Security Policy, and System Roadmap**

---

## Table of Contents
1. [Executive Summary & System Overview](#1-executive-summary--system-overview)
2. [Zero-Trust Security Architecture & Policy](#2-zero-trust-security-architecture--policy)
3. [Architecture Decision Records (ADRs)](#3-architecture-decision-records-adrs)
4. [System Execution Flow & Runtime Architecture](#4-system-execution-flow--runtime-architecture)
5. [Operational Analysis & Execution Guide](#5-operational-analysis--execution-guide)
6. [Container Architecture & Deployment Guide](#6-container-architecture--deployment-guide)
7. [Physical & Process Safety Validation (Digital Twin)](#7-physical--process-safety-validation-digital-twin)
8. [Forensic Evidence & System Integration Roadmap](#8-forensic-evidence--system-integration-roadmap)
9. [Dashboard Restoration & Dynamic Timeout Infrastructure](#9-dashboard-restoration--dynamic-timeout-infrastructure)
10. [Contributing Guidelines & Development Standards](#10-contributing-guidelines--development-standards)
11. [Contributor Covenant Code of Conduct](#11-contributor-covenant-code-of-conduct)

---

## 1. Executive Summary & System Overview

**SecureGuard Governance Model (SGGM)** is a zero-trust, defense-in-depth cybersecurity governance architecture and high-precision Human-Machine Interface (HMI) console designed for mission-critical **Cyber-Physical Systems (CPS)** and **Industrial Control Systems (ICS)**.

### Core Problem Solved
Traditional Industrial Control Systems (ICS) trust incoming commands from authenticated sessions or network perimeters. In modern cyber-physical threat environments, stolen credentials, compromised tokens, or insider threats allow attackers to issue physically destructive actuator commands while spoofing sensor feedback. SecureGuard bridges this gap through a multi-tiered defense:
- Multi-factor authentication (MFA) with strict temporal freshness enforcement (< 300 seconds).
- Dual-control supervisor consensus for safety-critical subsystem states.
- Mathematical validation via a physics-informed digital twin before physical actuation.
- Cryptographically chained, tamper-evident forensic audit ledger (SHA-256 hash chains + Ed25519 digital signatures).
- High-contrast industrial HMI console built on PySide6, pyqtgraph, and PyOpenGL.

### High-Level Architecture

```text
[Operator / Engineer / Supervisor]
               |
               v
   [Keycloak OIDC / JWT Token] --(Validates: Claims, Fresh MFA, JTI, Device Fingerprint)
               |
               v
     [Authorization Gate] <---- [Dual-Control Store: 2nd Supervisor Approval]
      (State Machine: NORMAL / DEGRADED / RESTRICTED / QUARANTINED)
               |
       (Allowed Actions)
               |
               v
    [SecureGuard Pipeline]
    +--- 1. Digital Twin Prediction (Physics mass, friction, velocity)
    +--- 2. Safety Envelope Check (Hard physical speed & current limits)
    +--- 3. Hardware Telemetry Ingestion (Ground truth, client values untrusted)
    +--- 4. Multi-Dimensional Risk Engine (Thermal, mechanical, rate anomalies)
    \--- 5. Causal Explainable AI (XAI root cause diagnosis)
               |
               v
  [Cryptographic Evidence Ledger] (evidence_log.jsonl)
    \--- SHA-256 Hash Chaining + Ed25519 Signatures + Verification
               |
               v
 [Industrial HMI Console (PySide6)] & [FastAPI Daemon Backend]
```

---

## 2. Zero-Trust Security Architecture & Policy

### 2.1 Four Deterministic Operational States

| State | Authorization Requirement | Permitted Roles | Actions Allowed |
|---|---|---|---|
| **`NORMAL`** | Standard Role-Based Access Control (RBAC) | Operator, Engineer, Supervisor | Standard conveyor setpoints, routing, speed adjustments |
| **`DEGRADED`** | Step-Up MFA Challenge (< 300 seconds fresh) | Any role with fresh MFA verification | Corrective setpoints, parameter re-calibration |
| **`RESTRICTED`** | Fresh MFA + 2 Independent Supervisor Approvals | Supervisors only (Dual-Control consensus) | High-risk overrides, safety threshold alterations |
| **`QUARANTINED`** | Complete Command Lockdown | Nobody (Physical interlock required) | Actuation disabled; forensic dump and inspection only |

### 2.2 Security Mechanisms
1. **Fresh MFA Enforcement (`keycloak_auth.py`)**: Rejects stale authentication claims. High-risk operations require an MFA challenge completed within the last 300 seconds (`SECUREGUARD_MFA_FRESHNESS=300`).
2. **Device Fingerprinting**: Session binding generates a SHA-256 hash across client HTTP headers and transport origins, preventing token exfiltration and off-device replay attacks.
3. **Token Age Expiration**: Hard lifetime threshold (default: 900 seconds) forces automated token rotation (`SECUREGUARD_TOKEN_MAX_AGE=900`).
4. **Dual-Control Consensus (`dual_control_store.py`)**: Critical safety modifications cannot be authorized by a single individual; two distinct authenticated supervisors must independently sign off.
5. **Tamper-Evident Ledger Integrity (`evidence_log.py`, `verify_log.py`)**: Every log entry records timestamp, user, roles, command, state before/after, risk score, digital signature, and previous record SHA-256 hash. Any retroactive mutation breaks the mathematical chain.

### 2.3 Vulnerability Disclosure Policy
To report security vulnerabilities:
1. Do not submit public issues.
2. Submit a private advisory or encrypted email detailing reproduction steps, affected components (`pipeline.py`, `keycloak_auth.py`, `evidence_log.py`), and physical impact analysis.

---

## 3. Architecture Decision Records (ADRs)

### ADR-01: Qt Binding Pinned to PySide6 (PyQt6 Excluded)
- **Decision:** PySide6 is the sole supported Qt binding. `PYQTGRAPH_QT_LIB=PySide6` is pinned across `main_qt.py`, `dashboard_qt.py`, and `Dockerfile.dashboard`. PyQt5/PyQt6 are explicitly excluded from `SecureGuard.spec`.
- **Rationale:** PySide6 is the official Qt for Python library with LGPL/commercial licensing and no CLA requirements. PyQt6 coexistence caused silent rebinding in pyqtgraph, corrupting `QFont`/`QColor` objects crossing module boundaries and causing intermittent chart crashes.
- **Tradeoff:** Rigid lock to PySide6 prevents using PyQt6-exclusive sub-libraries.

### ADR-02: GUI Stack -- PySide6 + pyqtgraph + PyOpenGL
- **Decision:** PySide6 for widgets and HMI layout, pyqtgraph for real-time 2D trend plotting, and PyOpenGL for 3D conveyor visualization (`pyqtgraph.opengl`).
- **Rationale:** pyqtgraph provides high-cadence real-time numpy plotting with minimal CPU overhead. PyOpenGL delivers hardware/software-accelerated 3D rendering for physical twin animation.
- **Tradeoff:** pyqtgraph theming API changes between releases; options are applied defensively in `industrial_theme.py`.

### ADR-03: Packaging via PyInstaller One-File Console Binary
- **Decision:** Packaged into a standalone console executable (`dist/SecureGuard.exe`, ~73MB) via `SecureGuard.spec`.
- **Rationale:** Facilitates instant plant-floor deployment on operator terminals without local Python runtimes. Console mode preserves stdout/stderr diagnostics.
- **Tradeoff:** Extraction to temporary `_MEIxxxx` directory adds 2-3 seconds to cold starts.

### ADR-04: Keycloak Authentication + Hermetic Test Mode
- **Decision:** Production validates real RS256 JWT tokens against Keycloak JWKS endpoints. In test mode (`SECUREGUARD_TEST_MODE=1`), tokens are signed using a committed RSA-2048 test keypair (`tests/fixtures/test_keys.py`).
- **Rationale:** Enables fully air-gapped unit testing and CI without requiring live identity servers.
- **Tradeoff:** Test keys must never be deployed to production; `keycloak_client.create_test_token()` strictly raises if test mode is disabled.

### ADR-05: Modal Startup Profile Gate Pre-Dashboard
- **Decision:** Identity selection occurs in a modal dialog (`startup_profile.py`) before `SecureGuardDashboard` is initialized.
- **Rationale:** Guarantees that the HMI never renders unauthenticated or with a default identity. Commands reaching the pipeline always carry a verified `AuthContext`.
- **Tradeoff:** Adds an initial profile selection step on launch.

### ADR-06: Flat Industrial Design System Contract
- **Decision:** Austere visual standards: solid fills, 90-degree sharp corners (zero `border-radius`), 1px borders, no drop shadows, no gradients, and strict monospace typography for all telemetry and numerics (`industrial_theme.py`).
- **Rationale:** Compliance with industrial SCADA/HMI standards (ISA-101). Prevents visual distraction, ensures readability under glare, and prevents numeric column jitter.
- **Tradeoff:** Utilitarian aesthetic; custom QSS required for standard widgets.

### ADR-07: Dual Persistence Engine (SQLite + JSONL Ledger)
- **Decision:** Relational data (pipeline state, dual control, thresholds) lives in SQLite (`secureguard.db`, `dual_control.db`). Forensic audit records live in append-only JSONL (`evidence_log.jsonl`) with Ed25519 signing.
- **Rationale:** SQLite provides zero-configuration local ACID transactions. JSONL enables immutable sequential cryptographic hashing.
- **Tradeoff:** Multiple concurrent process writers can lock SQLite or fork the hash chain. Handled via single-instance architecture and WAL mode with busy timeouts.

### ADR-08: Defense-in-Depth Command Pipeline
- **Decision:** All physical commands must traverse `SecureGuardPipeline`: (1) Auth Gate, (2) Digital Twin Prediction, (3) Safety Envelope Limits, (4) Hardware Ground Truth, (5) Multi-Dimensional Risk, (6) State Machine Transition.
- **Rationale:** Eliminates reliance on client-reported telemetry. Actuator actions are rejected if physics equations predict unsafe thermal or mechanical limits.
- **Tradeoff:** Adds computation latency; mitigated by generous timeouts (900s).

### ADR-09: Containerization Strategy (Dual Containers)
- **Decision:** Separated into `api` (FastAPI daemon) and `dashboard` (headless PySide6 operator console under Xvfb) sharing `/data`.
- **Rationale:** Decouples REST integration from GUI rendering. Headless dashboard runs full state machine and records audit logs without a physical screen.
- **Tradeoff:** Containers sharing write volumes must manage lock contention.

### ADR-10: Test Isolation & Anti-Contamination Harness
- **Decision:** Test suite imports `conftest.py`, dynamically redirecting `SECUREGUARD_DATA_DIR` to isolated session temporary directories.
- **Rationale:** Prevents tests from writing synthetic records to production ledgers (`evidence_log.jsonl`) or polluting SQLite databases.
- **Tradeoff:** Requires careful handling of early module-level path caching in `app_paths.py`.

---

## 4. System Execution Flow & Runtime Architecture

### 4.1 Entry Point Flow (`main_qt.py`)
```text
main_qt.py:main()
  +---- Set environment variables (QT_ENABLE_HIGHDPI_SCALING, PYQTGRAPH_QT_LIB=PySide6)
  +---- Initialize QApplication with high-DPI scaling attributes
  +---- Execute StartupProfileDialog modal gate (startup_profile.py)
  |     +---- Quick Profile Tab (Test Mode: operator01, supervisor01, engineer01, auditor01)
  |     +---- Manual Token Tab (Paste external JWT)
  |     +---- MFA Configuration Tab
  |     \---- Token JTI Display Tab
  |     \---- Validates token -> yields AuthContext
  \---- dashboard_qt.main(argv, auth=auth, token=token)
        +---- Initialize Industrial Theme (industrial_theme.py)
        +---- Construct SecureGuardDashboard(QMainWindow)
        +---- Build Tabs: Overview, ChartsTab, EvidenceTab, StreamTab, View3DTab
        +---- Bind DashboardSync state machine
        \---- Start QTimer network (Heartbeat: 1s, Clock: 1s, Stream: 2s, Charts: 30s)
```

### 4.2 Pipeline Command Processing Sequence (`pipeline.py`)
```text
Client / Operator submits Command: {"subsystem_id": "conveyor_01", "action": "SET_SPEED", "value": 550.0}
  |
  +---- 1. _auth_gate(subsystem_id, auth, action)
  |      +---- NORMAL: Verify user role in [operator, engineer, supervisor]
  |      +---- DEGRADED: Require auth.mfa_verified AND auth.mfa_fresh(<300s)
  |      +---- RESTRICTED: Require fresh MFA + supervisor role + dual_control_satisfied()
  |      \---- QUARANTINED: Reject all commands unconditionally
  |
  +---- 2. digital_twin.predict(command)
  |      \---- Calculate predicted velocity, current, temperature from physics model
  |
  +---- 3. digital_twin.validate_safety_envelope(predicted_state)
  |      \---- Check against hard thresholds (e.g. speed <= 600 RPM, temp <= 85°C)
  |
  +---- 4. hardware_telemetry.read_actual_sensors(subsystem_id)
  |      \---- Ingest ground-truth telemetry (client values strictly disregarded)
  |
  +---- 5. multi_dimensional_risk.compute_risk(actual, predicted)
  |      \---- Calculate residual vectors across speed, thermal, load, box rate
  |
  +---- 6. state_machine.evaluate_transition(current_state, risk_score)
  |      \---- Determine new state (NORMAL, DEGRADED, RESTRICTED, QUARANTINED)
  |
  \---- 7. evidence_log.log_evidence(...)
         +---- Compute SHA-256 hash linked to previous record
         +---- Sign record with local Ed25519 private key
         \---- Append record to evidence_log.jsonl
```

---

## 5. Operational Analysis & Execution Guide

### 5.1 Environment Configuration Reference

| Variable | Default | Purpose |
|---|---|---|
| `SECUREGUARD_TEST_MODE` | `0` (Prod) | Enables hermetic mock tokens (Set `1` for offline testing) |
| `SECUREGUARD_MFA_FRESHNESS`| `300` | Max age in seconds of valid step-up MFA challenge |
| `SECUREGUARD_TOKEN_MAX_AGE`| `900` | Max token age in seconds before re-authentication |
| `SECUREGUARD_DUAL_CONTROL` | `1` | Enables 2-supervisor approval gate for elevated operations |
| `SECUREGUARD_DATA_DIR`     | *(local)* | Root path for SQLite databases and JSONL ledger |
| `KEYCLOAK_URL`             | `http://localhost:8080` | Keycloak server base address |
| `KEYCLOAK_REALM`           | `secureguard` | Target realm name |
| `SG_PIPELINE_TIMEOUT`      | `900.0` | Pipeline execution timeout budget (seconds) |
| `SG_VIEW3D_FPS`            | `30.0` | Target 3D conveyor animation frame rate |
| `SG_CHART_REFRESH_MS`      | `30000` | Visual trend redraw cadence (ms) |

### 5.2 API Daemon Route Table (`main.py`)
- `GET /`: Unauthenticated liveness probe (`{"status": "SecureGuard is running", "version": "0.4.0"}`).
- `POST /command`: Submits actuator command through the zero-trust pipeline. Requires `Bearer <JWT>`.
- `GET /state/{subsystem_id}`: Returns current state machine posture and telemetry.
- `GET /session/info`: Dumps caller `AuthContext` (username, roles, MFA freshness, device fingerprint).
- `POST /auth/dual-control/approve`: Records supervisor consensus approval for target actions.
- `GET /auth/dual-control/status`: Queries pending supervisor approvals.
- `DELETE /auth/dual-control/clear`: Consumes/clears approval upon execution.
- `GET /evidence`: Fetches cryptographically verified audit records.
- `GET /evidence/verify`: Runs real-time verification of the evidence chain.

---

## 6. Container Architecture & Deployment Guide

### 6.1 Multi-Container Topography

```text
Host Environment
  +---- Port 127.0.0.1:8000 (Loopback only) --> [Container 1: secureguard-api]
  |                                                +---- uvicorn main:app (0.0.0.0:8000)
  |                                                \---- Non-root user: 10001:10001
  |
  \---- Headless Display (Xvfb) ---------------> [Container 2: secureguard-dashboard]
                                                   +---- xvfb-run python main_qt.py
                                                   +---- Mesa Software GLX (llvmpipe)
                                                   \---- Non-root user: 10001:10001
                                                            |
  Shared Named Volume: secureguard-data --------------------+--------------------------
    +---- evidence_log.jsonl (SHA-256 chained audit ledger)
    +---- secureguard.db (Pipeline state)
    +---- dual_control.db (WAL-mode supervisor approvals)
    \---- .secureguard/audit_key.pem (Ed25519 asymmetric signing key)
```

### 6.2 Running via Docker Compose
```bash
# Build and start services in background
docker compose up -d --build

# Inspect service health status
docker compose ps

# Tail API service logs
docker compose logs -f api

# Verify API liveness
curl http://127.0.0.1:8000/

# Cryptographically audit evidence ledger inside container
docker compose exec api python verify_log.py
```

---

## 7. Physical & Process Safety Validation (Digital Twin)

### 7.1 Monitored Physical Parameters
The conveyor system tracks five core cyber-physical parameters:
1. **Belt State**: Categorical state (`RUNNING` or `STOPPED`).
2. **Motor Velocity**: Mechanical rotation speed in RPM.
3. **Motor Current**: Electrical load in Amperes.
4. **Thermal Metric**: Operating temperature in Celsius.
5. **Item Throughput**: Box processing rate (items/minute).

### 7.2 Safety Envelope Enforcement
Before dispatching a setpoint to physical motor drivers, the safety envelope verifies that predicted values remain strictly within tolerable boundaries:
- Velocity: `0 <= speed <= 600.0 RPM`
- Current: `0.0 <= current <= 15.0 A`
- Temperature: `10.0 <= temp <= 85.0 °C`
Commands violating these boundaries are halted at the safety gate with `REJECTED_SAFETY_LIMITS`.

---

## 8. Forensic Evidence & System Integration Roadmap

### 8.1 Evidence Record Schema
Every forensic entry in `evidence_log.jsonl` contains:
```json
{
  "event_id": "uuid-v4",
  "timestamp": "ISO-8601-UTC",
  "user": "operator01",
  "roles": ["operator"],
  "command": "SET_SPEED = 500 RPM",
  "device_fingerprint": "sha256-hex",
  "token_jti": "jwt-unique-id",
  "mfa_verified": true,
  "dual_control_satisfied": true,
  "state_before": "NORMAL",
  "state_after": "NORMAL",
  "risk_score": 12.4,
  "anomaly_detected": false,
  "signature": "ed25519-signature-hex",
  "prev_hash": "sha256-predecessor-hex"
}
```

### 8.2 Roadmap Phases
- **Phase 1: Stabilization & Test Isolation** (Completed: 103/103 tests passing).
- **Phase 2: Cryptographic Forensic Ledger** (Completed: Ed25519 signatures + SHA-256 hash chaining).
- **Phase 3: High-Precision Industrial HMI** (Completed: PySide6, ISA-101 design system, 3D PyOpenGL view).
- **Phase 4: Adversarial Testbed & Telemetry Injection** (Planned: automated sensor drift and spoofing simulation).
- **Phase 5: Formal Publication & Verification Benchmarks** (Planned: academic cyber-physical benchmark dataset).

---

## 9. Dashboard Restoration & Dynamic Timeout Infrastructure

### 9.1 Dynamic Timeout Infrastructure (`timeout_utils.py`)
To prevent upstream network and RPC timeouts during intensive physics or risk calculations:
- `DynamicTimeout`: Exponential backoff with configurable jitter (±10%).
- `pipeline_command_timeout`: 900.0 seconds budget.
- `telemetry_stream_timeout`: 300.0 seconds budget.
- Telemetry streamer UI tick interval calibrated to 2 seconds.
- Chart repaint timer set to 30 seconds to minimize GPU overhead.
- 3D animation cadence locked to 30 FPS (33ms).

---

## 10. Contributing Guidelines & Development Standards

### 10.1 Quickstart Development Setup
```bash
# Clone repository
git clone https://github.com/verx-09/SecureGuard-Governance-Model-SGGM-.git
cd SecureGuard-Governance-Model-SGGM-

# Setup virtual environment
python -m venv .venv
# Activate:
# Windows: .venv\Scripts\activate | Linux: source .venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Run full test suite
pytest -v
```

### 10.2 Quality Standards
- Strict PEP 8 enforcement via `ruff`.
- 100% pass requirement on `pytest` test suite.
- All tests must use `conftest.py` path isolation.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`).

---

## 11. Contributor Covenant Code of Conduct

We are committed to providing a friendly, safe, and welcoming environment for all contributors, regardless of experience level, gender identity, race, or background. Harassment, derogatory commentary, or inappropriate conduct will not be tolerated.

---
*SecureGuard Governance Model (SGGM) -- End of Consolidated Documentation*
