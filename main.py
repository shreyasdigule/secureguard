"""
main.py — SecureGuard FastAPI application
"""

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import time

from digital_twin import Trajectory
from pipeline import SecureGuardPipeline
from evidence_log import (
    classify_decision,
    log_evidence,
    log_auth_rejection,
    read_all_evidence,
)
from keycloak_auth import AuthContext, validate_access_token, dual_control_required, _compute_device_fingerprint
from verify_log import verify_chain
from dual_control_store import (
    get_approval,
    set_approval,
    check_dual_control as store_check_dual_control,
    clear_approval,
    get_approval_status,
    clear_all as clear_all_approvals,
)

app = FastAPI(title="SecureGuard", version="0.4.0")
pipeline = SecureGuardPipeline()
bearer_scheme = HTTPBearer(auto_error=False)


def current_auth(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    request: Request = None,
) -> AuthContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No authentication token provided. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    auth = validate_access_token(credentials.credentials, request)
    
    # Enforce token freshness (continuous re-auth)
    if not auth.token_fresh():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token too old — re-authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return auth


# ---------------------------------------------------------------------------
# Phase 1.2 — Forensic Blackout Fix: Audit middleware
# Captures every request that fails authentication or validation BEFORE
# pipeline.process_command() is called, ensuring zero forensic blackouts.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def forensic_audit_middleware(request: Request, call_next):
    """
    Intercepts 401/403 responses and appends a REJECTED_AUTH record to the
    forensic ledger so auth failures are never invisible.
    Only applies to /command POST requests (actuator commands).
    """
    response = await call_next(request)

    if request.method == "POST" and request.url.path == "/command":
        if response.status_code in (401, 403):
            # Read body for subsystem_id if available (best-effort)
            subsystem = "unknown"
            command = "BLOCKED_AT_GATEWAY"
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk
                import json as _json
                body = _json.loads(body_bytes.decode("utf-8"))
                detail = body.get("detail", "Auth rejected")
                # Re-stream body so FastAPI can send it
                from fastapi.responses import Response
                response = Response(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            except Exception:
                detail = "Auth rejected"
            log_auth_rejection(
                subsystem=subsystem,
                command=command,
                reason=detail,
                user="unauthenticated",
                device_fingerprint=_compute_device_fingerprint(request),
            )

    return response


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------
# P0 Security Fix: ObservedOverride REMOVED.
# Clients must NOT supply sensor telemetry — it is pulled exclusively
# from the hardware layer (digital-twin simulation or real hardware)
# to prevent attackers from forging zero-residual observations.

class CommandRequest(BaseModel):
    subsystem_id: str
    from_speed_rpm: float
    to_speed_rpm: float
    # observed field REMOVED — P0 telemetry-ingestion security fix


class CommandResponse(BaseModel):
    accepted: bool
    reason: str
    predicted: Optional[dict] = None
    observed: Optional[dict] = None
    residual: Optional[float] = None
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    new_state: Optional[str] = None
    explanation: Optional[str] = None
    safety_violations: Optional[List[str]] = None
    telemetry_source: Optional[str] = None
    telemetry_quality: Optional[str] = None
    telemetry_sequence: Optional[int] = None


class SubsystemStateResponse(BaseModel):
    subsystem_id: str
    state: str
    required_auth: str
    consecutive_low_risk: int


class DualControlApprovalRequest(BaseModel):
    """Request for second supervisor to approve a restricted action."""
    target_username: str
    action_description: str
    subsystem_id: str


class DualControlApprovalResponse(BaseModel):
    approved: bool
    reason: str
    approved_by: str
    approved_at: str


class SessionInfoResponse(BaseModel):
    username: str
    roles: List[str]
    device_fingerprint: str
    token_jti: Optional[str]
    token_issued_at: Optional[int]
    token_age_seconds: Optional[float]
    mfa_verified: bool
    mfa_fresh: bool
    mfa_challenge_ts: Optional[int]
    supervisor_approved: bool
    dual_control_satisfied: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "SecureGuard is running", "version": "0.4.0"}


@app.post("/command", response_model=CommandResponse)
def submit_command(req: CommandRequest, auth: AuthContext = Depends(current_auth)):
    # P0 fix: observation comes strictly from the hardware layer.
    # No client-provided observed_override is passed.
    result = pipeline.process_command(
        subsystem_id=req.subsystem_id,
        from_speed_rpm=req.from_speed_rpm,
        to_speed_rpm=req.to_speed_rpm,
        auth=auth,
    )

    pred_dict = result.predicted.__dict__ if result.predicted else {}
    obs_dict = result.observed.__dict__ if result.observed else {}

    # Determine final decision label for the forensic record
    final_decision = classify_decision(result)

    log_evidence(
        subsystem=req.subsystem_id,
        command=f"SET_SPEED = {req.to_speed_rpm} RPM",
        previous_state=result.previous_state.value if result.previous_state else "unknown",
        predicted_trajectory=pred_dict,
        observed_trajectory=obs_dict,
        residual=result.risk.overall_risk_score if result.risk else -1.0,
        risk_score=result.risk.overall_risk_score if result.risk else 0.0,
        risk_level=result.risk.overall_risk_level if result.risk else "UNKNOWN",
        new_state=result.new_state.value if result.new_state else "blocked",
        authorization_path=result.reason,
        xai_explanation=result.explanation or "",
        # Phase 2 identity context
        user=auth.username,
        roles=list(auth.roles),
        mfa_verified=auth.mfa_verified,
        supervisor_approved=auth.supervisor_approved,
        device_fingerprint=auth.device_fingerprint,
        token_jti=auth.token_jti,
        dual_control_satisfied=auth.dual_control_satisfied(),
        final_decision=final_decision,
        rejection_reason="" if result.accepted else result.reason,
    )

    return CommandResponse(
        accepted=result.accepted,
        reason=result.reason,
        predicted=pred_dict if pred_dict else None,
        observed=obs_dict if obs_dict else None,
        residual=result.risk.overall_risk_score if result.risk else -1.0,
        risk_score=result.risk.overall_risk_score if result.risk else 0.0,
        risk_level=result.risk.overall_risk_level if result.risk else "UNKNOWN",
        new_state=result.new_state.value if result.new_state else None,
        explanation=result.explanation,
        safety_violations=result.safety_violations,
        telemetry_source=result.telemetry_source,
        telemetry_quality=result.telemetry_quality,
        telemetry_sequence=result.telemetry_sequence,
    )


@app.get("/state/{subsystem_id}", response_model=SubsystemStateResponse)
def get_state(subsystem_id: str, auth: AuthContext = Depends(current_auth)):
    subsystem = pipeline.state_store.get(subsystem_id)
    return SubsystemStateResponse(
        subsystem_id=subsystem_id,
        state=subsystem.state.value,
        required_auth=subsystem.required_auth(),
        consecutive_low_risk=subsystem.consecutive_low_risk,
    )


@app.get("/evidence")
def get_evidence_log(auth: AuthContext = Depends(current_auth)):
    """Returns all forensic evidence records from the JSONL ledger."""
    return read_all_evidence()


@app.get("/evidence/verify")
def verify_evidence_log(auth: AuthContext = Depends(current_auth)):
    """
    Phase 2.3 — Cryptographic tamper-evidence verification endpoint.
    Walks the entire evidence_log.jsonl, recomputes the hash chain,
    and verifies Ed25519 signatures.
    """
    result = verify_chain(verbose=False)
    http_status = 200 if not result.tampered else 409  # 409 Conflict = integrity violation

    return JSONResponse(
        status_code=http_status,
        content={
            "log_path": result.log_path,
            "total_records": result.total_records,
            "verified_ok": result.verified_ok,
            "tampered": result.tampered,
            "first_tampered_index": result.first_tampered_index,
            "first_tampered_event_id": result.first_tampered_event_id,
            "message": result.message,
        },
    )


@app.get("/session/info", response_model=SessionInfoResponse)
def get_session_info(auth: AuthContext = Depends(current_auth)):
    """Returns current session authentication context for anomaly detection UI."""
    token_age = None
    if auth.token_issued_at:
        token_age = time.time() - auth.token_issued_at
    return SessionInfoResponse(
        username=auth.username,
        roles=list(auth.roles),
        device_fingerprint=auth.device_fingerprint,
        token_jti=auth.token_jti,
        token_issued_at=auth.token_issued_at,
        token_age_seconds=token_age,
        mfa_verified=auth.mfa_verified,
        mfa_fresh=auth.mfa_fresh(),
        mfa_challenge_ts=auth.mfa_challenge_ts,
        supervisor_approved=auth.supervisor_approved,
        dual_control_satisfied=auth.dual_control_satisfied(),
    )


@app.post("/auth/dual-control/approve", response_model=DualControlApprovalResponse)
def approve_dual_control(
    req: DualControlApprovalRequest,
    auth: AuthContext = Depends(current_auth),
):
    """
    Second supervisor approves a restricted action.
    Requires the approver to have supervisor role and fresh MFA.
    """
    if not auth.supervisor_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only supervisors can provide dual-control approval",
        )
    if not auth.mfa_fresh():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Fresh MFA challenge required for dual-control approval",
        )
    
    approval_key = f"{req.subsystem_id}:{req.target_username}:{req.action_description}"
    
    # Check if already approved
    existing = get_approval(approval_key)
    if existing:
        if existing["first_approver"] == auth.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already approved this action",
            )
        # Second approval - dual control satisfied
        existing["second_approver"] = auth.username
        existing["second_approved_at"] = datetime.utcnow().isoformat()
        set_approval(approval_key, existing)
        
        return DualControlApprovalResponse(
            approved=True,
            reason="Dual-control satisfied — both supervisors approved",
            approved_by=auth.username,
            approved_at=datetime.utcnow().isoformat(),
        )
    
    # First approval
    set_approval(approval_key, {
        "subsystem_id": req.subsystem_id,
        "target_username": req.target_username,
        "action_description": req.action_description,
        "first_approver": auth.username,
        "first_approved_at": datetime.utcnow().isoformat(),
        "second_approver": None,
        "second_approved_at": None,
    })
    
    return DualControlApprovalResponse(
        approved=False,
        reason="First approval recorded — awaiting second supervisor",
        approved_by=auth.username,
        approved_at=datetime.utcnow().isoformat(),
    )


@app.get("/auth/dual-control/status")
def get_dual_control_status(
    subsystem_id: str,
    target_username: str,
    action_description: str,
    auth: AuthContext = Depends(current_auth),
):
    """Check dual-control approval status for an action."""
    return get_approval_status(subsystem_id, target_username, action_description)


@app.delete("/auth/dual-control/clear")
def clear_dual_control(
    subsystem_id: str,
    target_username: str,
    action_description: str,
    auth: AuthContext = Depends(current_auth),
):
    """Clear dual-control approval (for testing or after action completion)."""
    if not auth.supervisor_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only supervisors can clear dual-control approvals",
        )
    
    key = f"{subsystem_id}:{target_username}:{action_description}"
    if clear_approval(key):
        return {"cleared": True}
    return {"cleared": False, "reason": "No approval found"}


@app.post("/auth/dual-control/cleanup")
def cleanup_old_approvals(
    max_age_hours: int = 168,
    auth: AuthContext = Depends(current_auth),
):
    """Clean up old satisfied approvals (admin only)."""
    if not auth.supervisor_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only supervisors can cleanup approvals",
        )
    
    from dual_control_store import cleanup_old_approvals
    deleted = cleanup_old_approvals(max_age_hours)
    return {"deleted": deleted}
