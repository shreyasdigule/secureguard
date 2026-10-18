# SecureGuard     Person 3 Completion Report

## 1. Role
Person 3 is responsible for the physical and process safety validation of the SecureGuard system. This encompasses the Digital Twin, Safety Envelope, Anomaly Detection (Residual Engine), Risk Scoring, State Machine transitions, and generating Explainable AI (XAI) outputs.

## 2. Objective
The objective was to upgrade the initial rudimentary motor model into a robust, conveyor-specific Digital Twin. The system must evaluate authorized commands against safety limits, predict expected conveyor behavior, detect physical anomalies by comparing observed data against predictions, calculate a comprehensive risk score, and lock down the subsystem if necessary.

## 3. Implemented Components

| Component | File | Purpose | Status |
| :--- | :--- | :--- | :--- |
| **Configuration** | `config.py` | Centralizes safety limits, weights, and risk thresholds. | Complete |
| **Digital Twin** | `digital_twin.py` | Predicts expected behavior based on commands. | Complete |
| **Safety Envelope** | `digital_twin.py` | Validates commands against physical limits *before* execution. | Complete |
| **Residual Engine** | `residual_engine.py` | Computes anomaly errors and risk scores, and generates XAI. | Complete |
| **State Machine** | `state_machine.py` | Maps risk to authorization state (NORMAL -> QUARANTINED). | Complete |
| **Pipeline** | `pipeline.py` | Orchestrates Auth -> Twin -> Safety -> Residual -> State. | Complete |
| **API Server** | `main.py` | Fast API backend for integration with the dashboard and mock data. | Complete |
| **Logging** | `evidence_log.py` | Appends forensic audit trails. | Complete |
| **Automated Tests** | `test_pipeline.py` | Validates all scenarios with isolated databases. | Complete |
| **Demonstration** | `demo.py` | Interactive script proving all core scenarios. | Complete |

## 4. Five Monitored Parameters
The system now exclusively focuses on these 5 parameters for the conveyor model:
1. **Conveyor belt state:** Categorical state (`RUNNING` or `STOPPED`).
2. **Motor speed:** Float representing RPM.
3. **Motor current:** Float representing Amperage.
4. **Temperature:** Float representing Celsius.
5. **Box rate:** Float representing items processed per minute.

## 5. System Flow
```text
[User Command]
      |
      v
[Person 2: Authorization] --(Fails)--> REJECTED
      |
      v
[Person 3: Digital Twin Prediction]
      |
      v
[Person 3: Safety Envelope] --(Unsafe Limits)--> REJECTED
      |
      v
[Mocked Observation Data]
      |
      v
[Person 3: Anomaly / Residual Engine]
      |
      v
[Person 3: Risk Scoring (0-100)]
      |
      v
[Person 3: State Machine (NORMAL..QUARANTINED)]
      |
      v
[Person 3: XAI Generation]
      |
      v
[Person 4: Dashboard / Logging]
```

## 6. Digital Twin
The `ConveyorDigitalTwin` predicts the expected trajectory based purely on the commanded speed.
Currently, the formulas are **simplified development assumptions** and must be updated later:
* **Current:** `2.0 + (0.002 * to_speed_rpm)`
* **Temperature:** `35.0 + (to_speed_rpm / 100.0)`
* **Box Rate:** `20.0 * (to_speed_rpm / 500.0)`
* **Conveyor State:** `STOPPED` if RPM is 0, else `RUNNING`.

## 7. Safety Envelope
The `SafetyEnvelope` validates the command immediately after the Digital Twin prediction. It checks:
* Target RPM <= `max_safe_rpm`
* Predicted Current <= `max_safe_current_amps`
* Predicted Temperature <= `max_safe_temperature_c`
* Predicted Box Rate <= `max_safe_box_rate_per_min`
* Ensures no negative values or `NaN`/`Infinity`.
If any limit is breached, the command is immediately rejected with a `safety_violations` reason, avoiding physical execution entirely.

## 8. Anomaly Detection
The `ResidualEngine` compares observed data against the prediction.
* **Normalized Error:** For numerical values, it calculates `abs(observed - predicted) / max(predicted, 1.0)`.
* **Parameter Weights:** Configurable in `config.py` (e.g., current=0.30, temp=0.25, speed=0.25, box_rate=0.20).
* **Conveyor-State Mismatch:** A categorical mismatch (e.g., expected `RUNNING`, observed `STOPPED`) adds a massive flat 0.5 penalty to the residual.
* **Residual:** The sum of all weighted errors, capped at `1.0`.

## 9. Risk Scoring
The `risk_score` is directly derived from the residual (`residual * 100.0`), yielding a clear `0  ô100` scale.
The four risk levels are mapped via thresholds in `config.py`:
* **LOW:** Score 0  ô24.9
* **MEDIUM:** Score 25  ô49.9
* **HIGH:** Score 50  ô74.9
* **CRITICAL:** Score 75  ô100

## 10. State Machine
The `StateStore` maps the risk level directly to an authorization state:
* `LOW` risk -> **NORMAL**
* `MEDIUM` risk -> **DEGRADED**
* `HIGH` risk -> **RESTRICTED**
* `CRITICAL` risk -> **QUARANTINED**
**Recovery Logic:** The system strictly escalates to worse states immediately. To recover (e.g., from `RESTRICTED` down to `DEGRADED`), the system requires `3` consecutive interactions that result in a `LOW` risk score.

## 11. XAI
The system produces highly specific, human-readable explanations by inspecting exactly which variable caused the anomaly. 
*Example:* "Temperature is 30.0C above the expected operating value; Motor current is significantly higher (190%) than the Digital Twin prediction."

## 12. Testing Results
Tests were executed using `pytest test_pipeline.py -v`. All tests are isolated using a teardown fixture.

| Test | Result |
| :--- | :--- |
| `test_normal_operation` | PASSED |
| `test_high_current_anomaly` | PASSED |
| `test_excessive_rpm` | PASSED |
| `test_high_temperature` | PASSED |
| `test_box_rate_anomaly` | PASSED |
| `test_conveyor_state_mismatch` | PASSED |
| `test_invalid_values` | PASSED |

## 13. Demonstration Results
Executed using `demo.py`.

| Scenario | Result | Risk | State |
| :--- | :--- | :--- | :--- |
| 1     NORMAL OPERATION | ACCEPTED | LOW | NORMAL |
| 2     HIGH MOTOR CURRENT | ACCEPTED | MEDIUM | DEGRADED |
| 3     HIGH TEMPERATURE | ACCEPTED | LOW | NORMAL |
| 4     LOW BOX RATE | ACCEPTED | LOW | NORMAL |
| 5     CONVEYOR STATE MISMATCH | ACCEPTED | CRITICAL | QUARANTINED |
| 6     UNSAFE SPEED COMMAND | REJECTED | N/A | N/A |
| 7     AUTHORIZED BUT UNSAFE | REJECTED | N/A | N/A |

## 14. Complexity
* **Time Complexity:** `O(1)` per command. The pipeline runs a fixed number of deterministic arithmetic operations for prediction, a fixed number of comparisons for safety, and a fixed number of arithmetic operations for the residual. There are no loops or complex algorithms.
* **Space Complexity:**
  * *Per-command computational space:* `O(1)`. Only small dataclasses (`Trajectory`, `CommandResult`) are instantiated in memory.
  * *Persistent storage:* `O(N)` for `secureguard.db` (where N is the number of distinct subsystems) and `O(E)` for `evidence_log.jsonl` (where E is the total number of events processed).

## 15. Integration With Other Team Members
* **Person 1 (Hardware):** We currently rely on mock API observation payloads. Person 1 must eventually stream real telemetry to replace this.
* **Person 2 (Authorization):** Intact. Their `_auth_gate()` logic intercepts requests before Person 3 processing.
* **Person 3 (Safety/Twin):** Completed as documented in this report.
* **Person 4 (Dashboard/Logging):** Intact. `evidence_log.py` correctly appends the updated trajectories and risk scores.

## 16. Key Security Concept: "Authorized  ëá Safe"
**Example (Scenario 6/7):** A user might have the correct RBAC role and MFA token to request `1500 RPM` (Person 2 Authorization: PASSED). However, the physical hardware is only rated for `1000 RPM`. Person 3's Safety Envelope catches this physics violation and rejects the command (Person 3 Safety Check: FAILED) before it executes. 

## 17. Current Limitations
* Sensor data is currently simulated/supplied directly by the API caller.
* Real Raspberry Pi/ESP32 integration is pending.
* Digital Twin formulas are simplified development assumptions.
* Safety limits are development placeholders and require hardware validation.
* Real deployment should use trusted internal sensor telemetry rather than accepting sensor observations directly from an untrusted public client.

## 18. Future Integration
When Person 1 finishes the hardware, we must:
1. Update `config.py` with real physical maximums.
2. Update the equations in `ConveyorDigitalTwin.predict()` using real baseline measurements (e.g., actual idle current, exact belt ratios).
3. Connect a trusted telemetry stream so `observed_override` can be removed from the public API.

## 19. Final Status

**PERSON 3 PROTOTYPE IMPLEMENTATION: COMPLETE**

* Implementation: PASS
* Automated tests: PASS
* Demo: PASS
* Integration readiness: PENDING (Waiting on Person 1 hardware specifications)
