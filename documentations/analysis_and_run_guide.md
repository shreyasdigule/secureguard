# SecureGuard Governance Model (SGGM) - Session Analysis & Run Guide
**Date:** 2026-09-18  
**Commit:** `fedc72f`  
**Branch:** `main` (pushed to origin)

---

## Executive Summary

Closed critical authentication loopholes in the SecureGuard industrial control system. The original implementation trusted JWT claims as ground truth     stolen tokens = full persona takeover. Implemented defense-in-depth authentication with **fresh MFA enforcement**, **dual-control supervisor approval**, **session binding**, **token freshness**, and **enhanced audit logging**.

All 25 tests pass. Changes deployed to `main` branch.

---

## Detailed Technical Changes

### 1. Authentication Core (`keycloak_auth.py`)

**New `AuthContext` fields:**
```python
@dataclass(frozen=True)
class AuthContext:
    subject: str
    username: str
    roles: frozenset[str]
    mfa_verified: bool
    mfa_challenge_ts: Optional[int] = None      # NEW: from JWT claim
    device_fingerprint: str = "unknown"          # NEW: SHA256 of headers
    token_jti: Optional[str] = None              # NEW: JWT ID for replay detection
    token_issued_at: Optional[int] = None        # NEW: for token age enforcement
    second_supervisor_approved: bool = False     # NEW: dual-control flag
```

**New methods:**
- `mfa_fresh(max_age=300s)` - rejects stale MFA challenges
- `token_fresh(max_age=900s)` - enforces token rotation
- `dual_control_satisfied()` - checks dual-control store

**Config via env vars:**
```bash
SECUREGUARD_MFA_FRESHNESS=300      # MFA validity window (seconds)
SECUREGUARD_TOKEN_MAX_AGE=900      # Max token age before re-auth (seconds)
SECUREGUARD_DUAL_CONTROL=1         # Enable dual-supervisor approval
```

### 2. Test Token Generation (`keycloak_client.py`)

Test tokens now include `mfa_challenge_ts` claim when `mfa_verified=True`:
```python
if mfa_verified:
    claims["mfa_challenge_ts"] = now
```

### 3. Authorization Gates (`pipeline.py`)

**Updated `_auth_gate()` requirements:**

| Subsystem State | Required Auth | Implementation |
|----------------|---------------|----------------|
| `NORMAL` | `standard_rbac` | operator/engineer/supervisor |
| `DEGRADED` | `fresh step-up MFA` | `auth.mfa_verified and auth.mfa_fresh()` |
| `RESTRICTED` | `fresh MFA + supervisor + dual-control` | `auth.mfa_verified and auth.mfa_fresh() and auth.supervisor_approved and check_dual_control()` |
| `QUARANTINED` | `blocked` | Nobody |

**Dual-control check uses shared store:**
```python
if dual_control_required():
    if not check_dual_control(subsystem_id, auth.username, action_description):
        return False, "BLOCKED: dual-control supervisor approval required"
```

### 4. API Endpoints (`main.py`)

**New endpoints:**
- `GET /session/info` - Returns full auth context for anomaly detection UI
- `POST /auth/dual-control/approve` - First/second supervisor approval
- `GET /auth/dual-control/status` - Check approval status
- `DELETE /auth/dual-control/clear` - Clear approval after action

**Token freshness enforcement in `current_auth()`:**
```python
if not auth.token_fresh():
    raise HTTPException(401, "Token too old     re-authentication required")
```

### 5. Shared Dual-Control Store (`dual_control_store.py` - NEW)

```python
# Single instance shared across main.py (API) and pipeline.py (auth gate)
_dual_control_approvals: dict[str, dict] = {}

def check_dual_control(subsystem_id, target_username, action_description) -> bool:
    key = f"{subsystem_id}:{target_username}:{action_description}"
    approval = _dual_control_approvals.get(key)
    return approval is not None and approval.get("second_approver") is not None
```

### 6. Enhanced Audit Logging (`evidence_log.py`)

**EvidenceRecord now includes:**
```python
device_fingerprint: str      # SHA256 of client headers
token_jti: Optional[str]     # JWT ID for replay detection
dual_control_satisfied: bool # Dual-control status at decision time
```

### 7. Dashboard Integration (`dashboard_app.py`)

**Identity Card now shows:**
- Device Fingerprint (truncated)
- Token JTI (truncated)
- Dual-control status: SATISFIED (green) / PENDING (yellow)
- Token freshness: FRESH (green) / STALE (yellow)
- Session expiry countdown (color-coded)

**Evidence logging includes new auth fields:**
```python
log_evidence(
    device_fingerprint=auth.device_fingerprint,
    token_jti=auth.token_jti,
    dual_control_satisfied=auth.dual_control_satisfied(),
    ...
)
```

---

## Security Loopholes Closed

| Before | After |
|--------|-------|
| Stale MFA (cached `amr` claim) | Fresh MFA challenge required (<5 min) for DEGRADED/RESTRICTED |
| Single supervisor approval | RESTRICTED actions need TWO supervisors with fresh MFA |
| Token replay/theft | Device fingerprint + JTI tracking + 15min max token age |
| No session visibility | `/session/info` exposes auth context for anomaly detection |
| Incomplete audit trail | Evidence log captures full identity context |

---

## Authorization Matrix

| Subsystem State | Required Auth | Who Can Access |
|----------------|---------------|----------------|
| NORMAL | standard_rbac | operator, engineer, supervisor |
| DEGRADED | fresh step-up MFA | Any role with fresh MFA |
| RESTRICTED | fresh MFA + supervisor + dual-control | supervisor only (2 supervisors, fresh MFA) |
| QUARANTINED | blocked | Nobody |

---

## Test Profiles

| Profile | Username | Roles | MFA |
|---------|----------|-------|-----|
| operator01 (Standard) | operator01 | ["operator"] |  Ø  |
| supervisor01 (MFA + Super) | supervisor01 | ["supervisor", "operator"] |   à |
| engineer01 (Standard) | engineer01 | ["engineer"] |  Ø  |
| auditor01 (No Op Role) | auditor01 | ["auditor"] |  Ø  |

---

## Test Results

```
25 passed, 2 warnings in 1.31s
- 12 keycloak_auth tests
- 13 pipeline tests
```

---

## Complete Run Guide

### Prerequisites

```powershell
# 1. Navigate to project
cd "C:\Users\Veer\Desktop\SecureGuard-Governance-Model-SGGM-"

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Verify dependencies
python -c "import fastapi, uvicorn, jwt, cryptography; print('OK')"
```

### Terminal 1: Start API Server

```powershell
cd "C:\Users\Veer\Desktop\SecureGuard-Governance-Model-SGGM-"
.\.venv\Scripts\Activate.ps1
$env:SECUREGUARD_TEST_MODE="1"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Terminal 2: Run Dashboard (GUI)

```powershell
cd "C:\Users\Veer\Desktop\SecureGuard-Governance-Model-SGGM-"
.\.venv\Scripts\Activate.ps1
python dashboard_app.py
```

**GUI opens with:**
- Identity Card (top) - click "Switch Profile" to login
- Overview tab - subsystem status, mimic diagram, command form
- Chart tab - trend charts
- Evidence Log tab - forensic records
- Live Stream tab - telemetry

### Terminal 2 Alternative: Manual API Testing

```powershell
cd "C:\Users\Veer\Desktop\SecureGuard-Governance-Model-SGGM-"
.\.venv\Scripts\Activate.ps1

# Generate tokens
$token_op = (python -c "import os; os.environ['SECUREGUARD_TEST_MODE']='1'; from keycloak_client import create_test_token; print(create_test_token('operator01', ['operator'], mfa_verified=False))").Trim()
$token_op_mfa = (python -c "import os; os.environ['SECUREGUARD_TEST_MODE']='1'; from keycloak_client import create_test_token; print(create_test_token('operator01', ['operator'], mfa_verified=True))").Trim()
$token_sup = (python -c "import os; os.environ['SECUREGUARD_TEST_MODE']='1'; from keycloak_client import create_test_token; print(create_test_token('supervisor01', ['supervisor','operator'], mfa_verified=True))").Trim()

# Test normal operation
$body = @{subsystem_id="conv_1"; from_speed_rpm=0; to_speed_rpm=500} | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/command" -Headers @{"Authorization"="Bearer $token_op"} -ContentType "application/json" -Body $body

# Check session info
Invoke-RestMethod -Method GET -Uri "http://localhost:8000/session/info" -Headers @{"Authorization"="Bearer $token_op_mfa"}
```

### Run Tests

```powershell
cd "C:\Users\Veer\Desktop\SecureGuard-Governance-Model-SGGM-"
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pytest test_keycloak_auth.py test_pipeline.py -v
```

### Suppress Deprecation Warnings

```powershell
.\.venv\Scripts\python.exe -m pytest test_keycloak_auth.py test_pipeline.py -v -W ignore::DeprecationWarning
```

---

## Manual Verification Checklist

### 1. Normal Operation (NORMAL state)
- [ ] Operator token works
- [ ] Response: `accepted: true`, `reason: "executed (RBAC role satisfied)"`

### 2. DEGRADED State - MFA Enforcement
- [ ] Force DEGRADED with high-risk observation
- [ ] Operator WITHOUT MFA -> BLOCKED: "requires fresh step-up MFA"
- [ ] Operator WITH fresh MFA -> ACCEPTED

### 3. RESTRICTED State - Dual-Control
- [ ] Force RESTRICTED with repeated high-risk
- [ ] Supervisor WITH fresh MFA alone -> BLOCKED: "dual-control supervisor approval required"
- [ ] First supervisor approves via `/auth/dual-control/approve`
- [ ] Second supervisor approves -> status: "satisfied"
- [ ] Supervisor command -> ACCEPTED: "executed (step-up MFA + supervisor role + dual-control satisfied)"

### 4. Session Info Endpoint
- [ ] `GET /session/info` returns device_fingerprint, token_jti, dual_control_satisfied, token_fresh

### 5. Token Expiry
- [ ] Token older than 15min -> 401 "Token too old     re-authentication required"

### 6. Dashboard
- [ ] Identity card shows: username, roles, MFA status, supervisor flag, device FP, JTI, dual-control, token fresh, expiry countdown
- [ ] "Switch Profile" dialog works for all 4 profiles
- [ ] Command form submits with authenticated session
- [ ] Evidence log shows new auth fields

---

## Files Changed (19 files)

| File | Changes |
|------|---------|
| `keycloak_auth.py` | AuthContext + methods + fingerprinting |
| `keycloak_client.py` | Test tokens include mfa_challenge_ts |
| `pipeline.py` | Auth gates + dual-control check |
| `main.py` | Token freshness + dual-control endpoints |
| `evidence_log.py` | Enhanced EvidenceRecord |
| `dual_control_store.py` | NEW: shared approval store |
| `dashboard_app.py` | Identity card + evidence logging |
| `test_keycloak_auth.py` | New tests for fresh MFA, token fresh, dual-control |
| `test_pipeline.py` | Updated assertions |
| `persistence.py` | Minor |
| `demo.py` | Minor |
| `verify_log.py` | Minor |
| `SESSION_RECORD_2026-09-18.txt` | NEW: session record |
| `PERSON_4_ADVANCEMENT_ROADMAP.md` | NEW |
| `SESSION_RECORD_2026-09-14.txt` | NEW |
| `SESSION_RECORD_2026-09-15.txt` | NEW |
| `Username operator01.txt` | NEW |
| `doc_content.txt` | NEW |
| `evidence_log_legacy_pre_phase2.jsonl` | NEW |

---

## Git Status

```bash
# Main branch - all changes committed and pushed
git log --oneline -1
# fedc72f feat: close auth loopholes     fresh MFA, dual-control, session binding, token freshness

git status
# nothing to commit, working tree clean

git push status
# Already up to date with origin/main
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 8000 in use | `netstat -ano \| findstr :8000` -> `taskkill /PID <PID> /F` |
| Module not found | Activate venv: `.\.venv\Scripts\Activate.ps1` |
| Test token rejected | Ensure `$env:SECUREGUARD_TEST_MODE="1"` set before starting server |
| Dashboard won't start | Ensure server running in Terminal 1 |
| PowerShell `&&` error | Use semicolon `;` or separate lines |

---

## Next Steps (Roadmap)

1. **Enhanced 2D/3D Conveyor Mimic** - PyGame/OpenGL window for Pi deployment
2. **Kivy Migration** - If Pi deployment confirmed
3. **Hardware Integration** - ESP32-S3 telemetry streamer hook
4. **Redis-backed Dual-Control Store** - Production replacement for in-memory
5. **Web Dashboard** - React/Three.js frontend for remote access
