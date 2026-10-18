# SecureGuard Governance Model (SGGM)     Person 4 Advancement Roadmap
**Lead:** Person 4     Dashboard, Secure Logging & System Integration Lead  
**Objective:** Transition the system from prototype to an advanced, publication-ready cyber-physical governance platform.  
**Version:** 1.0  
**Date:** 2026-09-17  

---

## ­ƒº¡ Executive Overview
As Person 4, you own the **Operator Interface (HMI)**, the **Forensic Evidence & Database Layer**, and the **System Integration** binding Person 1 (Hardware), Person 2 (Keycloak Auth), and Person 3 (Digital Twin & Safety).

This roadmap outlines a 5-phase engineering progression from the current prototype to an advanced, publication-ready release.

```
+-------------+     +-------------+     +-------------+     +-------------+     +-------------+
|   PHASE 1   | --  ║ |   PHASE 2   | --  ║ |   PHASE 3   | --  ║ |   PHASE 4   | --  ║ |   PHASE 5   |
|Stabilization|     |Cryptographic|     |Advanced HMI |     |Attack/Def   |     |Paper Data & |
| & CI Tests  |     |   Logging   |     |  Dashboard  |     |  Testbed    |     |Visuals (P2) |
\---------------+     \---------------+     \---------------+     \---------------+     \---------------+
```

---

## ­ƒô  Phase 1: Immediate Stabilization & Integration Bug Fixes
**Target Duration:** Day 1  
**Goal:** Eliminate all blocking errors, restore automated CI/CD test pass rate to 100%, and eliminate forensic blackouts.

- [ ] **1.1 Fix Automated Test Suite (`test_pipeline.py`)**
  - **Issue:** All 7 tests currently fail with `KeyError: 'accepted'` because Person 2 added JWT enforcement to `main.py` without updating test harnesses.
  - **Action:** 
    - Create a test fixture providing mock `AuthContext` objects (`operator_auth`, `supervisor_auth`).
    - Use FastAPI's `app.dependency_overrides[current_auth]` to inject verified test contexts.
    - Add explicit test assertions verifying HTTP status codes and response schemas.
    - Add negative security tests verifying that requests lacking tokens receive `401 Unauthorized` / `403 Forbidden`.

- [ ] **1.2 Fix the "Forensic Blackout" on Auth & Gateway Rejections (`main.py`)**
  - **Issue:** Currently, `log_evidence()` is only called *after* `pipeline.process_command()`. If a request is rejected by Keycloak auth (invalid/missing token) or malformed payload, **no forensic log is created**.
  - **Action:**
    - Introduce an audit logging interceptor/middleware in `main.py`.
    - Ensure every rejection (Auth failure, Safety limit breach, Invalid input) is logged with `decision="BLOCKED_BY_GATEWAY"` or `decision="REJECTED_AUTH"`.

- [ ] **1.3 Update the Conveyor Demo Script (`demo.py`)**
  - **Action:** Add token generation/mocking so the demo runs seamlessly end-to-end without authorization errors.

---

## ­ƒ   Phase 2: Context-Rich Forensic Evidence & Cryptographic Tamper-Evidence
**Target Duration:** Days 2  ô3  
**Goal:** Upgrade the logging layer from simple JSONL into an immutable, mathematically verifiable forensic ledger.

- [ ] **2.1 Context-Rich Forensic Schema Upgrade (`evidence_log.py`)**
  - **Action:** Expand `EvidenceRecord` to capture the complete causal chain mandated by your role:
    ```python
    @dataclass
    class EvidenceRecord:
        event_id: str
        timestamp: str
        user: str                      # Username from JWT (e.g., "operator01")
        roles: list[str]               # Active roles (e.g., ["operator"])
        command: str                   # e.g., "SET_SPEED = 500 RPM"
        subsystem: str                 # e.g., "Conveyor_Motor_01"
        previous_state: str            # NORMAL, DEGRADED, RESTRICTED, QUARANTINED
        approval_info: dict            # {"mfa_verified": bool, "supervisor_approved": bool}
        predicted_trajectory: dict     # Speed, current, temp, box rate, belt state
        observed_trajectory: dict      # Actual sensor readings
        residual: float                # Normalized error (0.0 - 1.0)
        risk_score: float              # 0 - 100
        risk_level: str                # LOW, MEDIUM, HIGH, CRITICAL
        final_decision: str            # "ACCEPTED" | "REJECTED_SAFETY" | "REJECTED_AUTH" | "BLOCKED_QUARANTINE"
        rejection_reason: str          # Descriptive reason or safety violation
        new_state: str                 # Post-transition state
        xai_explanation: str           # Causal attribution text
        previous_record_hash: str      # Hash of the preceding record (chaining)
        signature: str                 # HMAC-SHA256 or ECDSA signature
    ```

- [ ] **2.2 Implement Cryptographic Hash Chaining (Blockchain-like Tamper Evidence)**
  - **Action:**
    - Implement forward-secure hash chaining:
      $$\mathcal{H}_n = \text{HMAC-SHA256}(\text{CanonicalRecord}_n \mathbin{\Vert} \mathcal{H}_{n-1}, K_{\text{audit}})$$
    - Store the genesis hash $\mathcal{H}_0$ in a secure configuration.
    - Each record seals the entire history of past events.

- [ ] **2.3 Build the Forensic Verification Tool (`verify_log.py`)**
  - **Action:**
    - Create a standalone CLI and API endpoint (`GET /evidence/verify`):
      - Scans `evidence_log.jsonl` from line 0 to $N$.
      - Recomputes the hash chain.
      - If an attacker modifies even a single timestamp, sensor reading, or deletes an entry, the verification fails and outputs the exact line number of tampering.

- [ ] **2.4 Relational Storage Mirroring (`persistence.py`)**
  - **Action:**
    - Add an `evidence_records` table to SQLite (`secureguard.db`).
    - Store indexed columns (`timestamp`, `subsystem_id`, `user`, `risk_score`, `final_decision`) allowing instant querying and dashboard filtering.

---

## ­ƒ Ñ´©Å Phase 3: Advanced Operator HMI Dashboard Upgrades
**Target Duration:** Days 4  ô5  
**Goal:** Deliver a high-performance, ISA-101 compliant operator dashboard featuring full situational awareness, identity context, and live monitoring.

- [ ] **3.1 Add the "User Identity & Security Context Card" (`dashboard_app.py`)**
  - **Action:**
    - Add a dedicated top-panel card displaying:
      * **Active Operator:** `operator01` (or current authenticated subject)
      * **Assigned Roles:** `[operator]` / `[supervisor, engineer]`
      * **MFA Status:** `    OTP Verified` (Green LED) vs `    Standard Auth` (Yellow)
      * **Supervisor Privilege:** `    Authorized` vs `    Standard Operator`
      * **Session Token Expiry:** Live countdown timer.

- [ ] **3.2 Interactive Profile Switcher / Direct Grant Login Dialog**
  - **Action:**
    - Replace the cumbersome "paste raw JWT token" text box with:
      * A one-click **"Switch Profile"** modal: Select `operator01` (standard) or `supervisor01` (MFA + supervisor role).
      * Integrated token fetcher that authenticates directly against Keycloak (`192.168.137.96:8080/realms/secureguard`).
      * Manual token paste tab as a developer fallback.

- [ ] **3.3 Live Telemetry Streamer & Playback Mode**
  - **Action:**
    - Add a **"Stream Mode"** toggle on the HMI:
      * **Manual Mode:** Form entry for custom experimental testing.
      * **Live Mock Streamer:** A background worker generating realistic physical telemetry with random gaussian sensor noise, updating the mimic diagram and trend charts in real time (1 Hz).
      * **Hardware Streamer Hook:** Prepared socket to consume real ESP32-S3 telemetry from Person 1.

- [ ] **3.4 Forensic Drill-down Inspector (Evidence Log Tab)**
  - **Action:**
    - Allow operators to double-click any row in the **Evidence Log Treeview**.
    - Opens a modal showing the full causal chain: predicted vs observed radar chart, XAI explanation, cryptographic hash status, and approval audit trail.

---

##  Ü ´©Å Phase 4: Full Attack & Defense Demonstration Testbed
**Target Duration:** Days 6  ô7  
**Goal:** Build an automated, repeatable validation suite proving the cyber-physical governance capabilities for the paper.

- [ ] **4.1 Build the Automated Attack/Defense Testbed (`run_attack_defense_demo.py`)**
  - **Action:** Implement an interactive and scripted test harness running all 6 critical scenarios:

| # | Scenario Name | Attack Description | SecureGuard Defense Mechanism | Expected Result |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Physical Limit Breach** | Authorized operator commands 1500 RPM (>1000 limit) | **SafetyEnvelope** intercepts before actuator execution | **REJECTED_SAFETY** (Motor never actuated) |
| **2** | **Sensor Spoofing / Belt Jam** | Attacker issues 500 RPM; current spikes to 8.7A | **Digital Twin & Residual Engine** detect 190% anomaly | **QUARANTINED** (Risk Score = 82.3) |
| **3** | **Unprivileged Actuation** | Standard operator issues command while system is DEGRADED | **Keycloak Gate** checks AMR claim; blocks without OTP | **BLOCKED_AUTH** (Step-Up MFA Required) |
| **4** | **Quarantine Lock Bypass** | Supervisor with MFA tries to actuate in QUARANTINED state | **Fail-Safe Gate** blocks all actuator commands in Quarantine | **BLOCKED_QUARANTINE** (Actuation forbidden) |
| **5** | **Controlled Recovery Path** | Supervisor issues 3 consecutive healthy low-risk commands | **StateStore Streak Counter** requires 3 clean cycles | **RESTRICTED --  ║ DEGRADED --  ║ NORMAL** |
| **6** | **Audit Log Tampering Attack** | Rogue operator alters `evidence_log.jsonl` to cover tracks | **Hash Chain Validator** detects mismatched digest | **TAMPER DETECTED** (Pinpoints line & record) |

- [ ] **4.2 Comprehensive Latency & Performance Benchmark**
  - **Action:** Benchmark end-to-end processing times across 1,000 cycles:
    * Keycloak JWT decode & verification: $\approx 0.35\text{ ms}$
    * Digital Twin trajectory prediction: $\approx 0.05\text{ ms}$
    * Safety envelope validation: $\approx 0.02\text{ ms}$
    * Residual calculation & XAI generation: $\approx 0.08\text{ ms}$
    * Cryptographic log append & hash chaining: $\approx 0.45\text{ ms}$
    * **Total Pipeline Overhead:** $< 1.2\text{ ms}$ (Proves industrial real-time feasibility).

---

## ­ƒôä Phase 5: Research Paper Deliverables (For Person 2)
**Target Duration:** Days 8  ô9  
**Goal:** Supply Person 2 with all required figures, tables, experimental data, and architecture write-ups for the academic paper.

- [ ] **5.1 Publication-Grade Figure Generation (`generate_paper_figures.py`)**
  - **Action:** Write an automated script generating high-resolution (300 DPI) vector figures (`.pdf`, `.png`):
    * **Figure 1 (Anomaly Detection & Residual Spike):** Multi-axis timeline showing Speed, Current, Temp, and the instantaneous Residual spike under a belt jam attack.
    * **Figure 2 (State Machine Escalation & Recovery):** Phase plot showing state transitions ($S_n \rightarrow S_{n+1}$) under attack escalation and the 3-interaction recovery streak.
    * **Figure 3 (System Architecture & Pipeline Flow):** Architectural block diagram connecting Keycloak $\rightarrow$ Gateway $\rightarrow$ Twin $\rightarrow$ Residual $\rightarrow$ Forensic Ledger $\rightarrow$ HMI.
    * **Figure 4 (Cryptographic Tamper-Evidence):** Diagram showing the forward hash chain and verification failure when a record is manipulated.
    * **Figure 5 (Latency Breakdown):** Stacked bar chart showing sub-millisecond execution times for each pipeline stage.

- [ ] **5.2 Export Structured Experimental Datasets**
  - **Action:** Export clean CSV and JSON datasets containing raw attack/defense trajectories, residuals, and state histories for inclusion in the paper's evaluation section.

- [ ] **5.3 Deliver Written Paper Sections for Person 2**
  - **Action:** Prepare ready-to-paste LaTeX / Markdown drafts for:
    1. **Dashboard & HMI Architecture:** Situational awareness, ISA-101 design rationale, and operator feedback loops.
    2. **Forensic Logging Architecture:** Mathematical formulation of the causal chain and forward-secure hash chaining.
    3. **Experimental Setup:** Hardware/software specs (Raspberry Pi 5, ESP32-S3, Python FastAPI, Keycloak).
    4. **Evaluation & Results:** Detailed narrative interpreting the figures and tables.
    5. **Discussion, Limitations & Future Scope:** Realities of OT security ("Authorized $\neq$ Safe"), hardware secure elements (ATECC108A), and scaling to distributed SCADA networks.

---

## ­ƒôè Summary of Deliverables & Timeline

| Phase | Milestone Name | Key Output Files | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Stabilization & CI Pass | `test_pipeline.py`, `main.py`, `demo.py` |  Å| Ready to Start |
| **Phase 2** | Cryptographic Logging | `evidence_log.py`, `verify_log.py`, `persistence.py` |  Å| Scheduled |
| **Phase 3** | Advanced Dashboard HMI | `dashboard_app.py` |  Å| Scheduled |
| **Phase 4** | Attack/Defense Testbed | `run_attack_defense_demo.py`, `benchmark.py` |  Å| Scheduled |
| **Phase 5** | Research Paper Materials | `generate_paper_figures.py`, `PAPER_SECTIONS_PERSON_4.md` |  Å| Scheduled |

---
*Roadmap created for Person 4     SecureGuard Governance Model (SGGM)*
