"""
pipeline.py — Full command-processing loop
"""

import numpy as np
from dataclasses import dataclass

from multi_dimensional_risk import MultiDimensionalRiskEngine, MultiDimensionalRisk, RiskDimension
from state_machine import StateStore, AuthState
from keycloak_auth import AuthContext, dual_control_required
from dual_control_store import check_dual_control
from hardware_telemetry import get_global_telemetry, TelemetryReading
from physics_digital_twin import PhysicsBasedDigitalTwin as ConveyorDigitalTwin, Trajectory, ConveyorSpecification, Prediction
from digital_twin import SafetyEnvelope
from causal_xai import CausalXAIEngine, CausalExplanation
from timeout_utils import with_pipeline_timeout, operation_timeout, TimeoutError
from config import app_config


def _to_native(val):
    """Convert numpy types to Python native types."""
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, (np.integer, np.int8, np.int16, np.int32, np.int64,
                        np.uint8, np.uint16, np.uint32, np.uint64)):
        return int(val)
    if isinstance(val, (np.floating, np.float16, np.float32, np.float64)):
        return float(val)
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, dict):
        return {k: _to_native(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_native(v) for v in val]
    return val


@dataclass
class CommandResult:
    accepted: bool
    reason: str
    previous_state: AuthState | None = None
    predicted: Trajectory | None = None
    observed: Trajectory | None = None
    risk: MultiDimensionalRisk | None = None
    new_state: AuthState | None = None
    explanation: str | None = None
    safety_violations: list[str] | None = None
    telemetry_source: str | None = None
    telemetry_quality: str | None = None
    telemetry_sequence: int | None = None


class SecureGuardPipeline:
    def __init__(self, telemetry_interface=None, conveyor_spec=None, application_type="manufacturing_assembly", operating_phase="steady_state", material_type="generic", environment="indoor"):
        spec = conveyor_spec or ConveyorSpecification()
        self.twin = ConveyorDigitalTwin(spec)
        self.safety_envelope = SafetyEnvelope()
        self.risk_engine = MultiDimensionalRiskEngine(
            application=application_type,
            operating_phase=operating_phase,
            material_type=material_type,
            environment=environment
        )
        self.state_store = StateStore()
        self._telemetry = telemetry_interface

    def _get_telemetry(self):
        """Get telemetry interface (injected or global)."""
        if self._telemetry is not None:
            return self._telemetry
        from hardware_telemetry import get_global_telemetry
        return get_global_telemetry()

    def _auth_gate(self, requirement: str, auth: AuthContext, subsystem_id: str = None, action_description: str = None) -> tuple[bool, str]:
        if requirement == "standard_rbac":
            if "operator" in auth.roles or "supervisor" in auth.roles or "engineer" in auth.roles:
                return True, f"RBAC role satisfied ({auth.username})"
            return False, "BLOCKED: token lacks an operational role"
        if requirement == "step_up_mfa_plus_fresh_prediction":
            if auth.mfa_verified and auth.mfa_fresh():
                return True, "step-up MFA claim satisfied (fresh)"
            return False, "BLOCKED: requires fresh step-up MFA (subsystem is DEGRADED)"
        if requirement == "step_up_mfa_plus_supervisor_approval_plus_fresh_prediction":
            if auth.mfa_verified and auth.mfa_fresh() and auth.supervisor_approved:
                if dual_control_required():
                    # Check dual-control from store
                    if subsystem_id and action_description:
                        if not check_dual_control(subsystem_id, auth.username, action_description):
                            return False, "BLOCKED: dual-control supervisor approval required (subsystem is RESTRICTED)"
                    elif not auth.dual_control_satisfied():
                        return False, "BLOCKED: dual-control supervisor approval required (subsystem is RESTRICTED)"
                return True, "step-up MFA + supervisor role + dual-control satisfied"
            return False, "BLOCKED: requires fresh step-up MFA + supervisor approval + dual-control (subsystem is RESTRICTED)"
        if requirement == "all_actuator_commands_blocked_diagnostics_only":
            return False, "BLOCKED: subsystem is QUARANTINED — actuator commands not permitted"
        return False, f"BLOCKED: unknown requirement '{requirement}'"

    def process_command(
        self,
        subsystem_id: str,
        from_speed_rpm: float,
        to_speed_rpm: float,
        cmd_type: str = "SET_SPEED",
        accel_rate: float = 100.0,
        decel_rate: float = 150.0,
        torque_limit: float = 100.0,
        direction: str = "FWD",
        ctrl_mode: str = "VELOCITY",
        auth: AuthContext | None = None,
    ) -> CommandResult:
        if auth is None:
            return CommandResult(accepted=False, reason="BLOCKED: authenticated Keycloak context required")
        subsystem = self.state_store.get(subsystem_id)
        pre_transition_state = subsystem.state
        requirement = subsystem.required_auth()

        # 1. Authorization Gate
        action_desc = f"{cmd_type} = {int(to_speed_rpm)} RPM (accel={accel_rate}, decel={decel_rate}, torque={torque_limit}%, dir={direction}, mode={ctrl_mode})"
        allowed, gate_reason = self._auth_gate(requirement, auth, subsystem_id, action_desc)
        if not allowed:
            return CommandResult(accepted=False, reason=gate_reason, previous_state=pre_transition_state)

        # 2. Digital Twin Prediction (with timeout)
        command = {
            "from_speed_rpm": from_speed_rpm,
            "to_speed_rpm": to_speed_rpm,
            "cmd_type": cmd_type,
            "accel_rate": accel_rate,
            "decel_rate": decel_rate,
            "torque_limit": torque_limit,
            "direction": direction,
            "ctrl_mode": ctrl_mode,
            "load_factor": 1.0
        }
        
        # Use timeout for digital twin prediction
        with operation_timeout("digital_twin_prediction", app_config.timeouts.get_pipeline_timeout()):
            predicted = self.twin.predict(
                command=command,
                current_state={"motor_speed_rpm": from_speed_rpm},
                environment={},
                dt=1.0
            )

        # 3. Safety Envelope Check
        is_safe, safety_reason = self.safety_envelope.validate(to_speed_rpm, predicted.trajectory, torque_limit, direction)
        if not is_safe:
            return CommandResult(
                accepted=_to_native(False),
                reason=f"SAFETY VIOLATION: {safety_reason}",
                previous_state=pre_transition_state,
                predicted=_to_native(predicted.trajectory) if predicted else None,
                safety_violations=[safety_reason]
            )

        # 4. Observation — HARDWARE TELEMETRY ONLY (P0 security fix)
        # Client-provided overrides are NEVER accepted.
        # Telemetry is pulled strictly from the hardware layer.
        telemetry_interface = self._get_telemetry()
        
        # Set the commanded state for simulation (so telemetry matches prediction in test mode)
        if hasattr(telemetry_interface, 'set_commanded_state'):
            telemetry_interface.set_commanded_state(
                subsystem_id, predicted.trajectory,
                cmd_type=cmd_type,
                accel_rate=accel_rate,
                decel_rate=decel_rate,
                torque_limit=torque_limit,
                direction=direction,
                ctrl_mode=ctrl_mode,
            )
        
        # Verify telemetry source is healthy
        if not telemetry_interface.health_check(subsystem_id):
            return CommandResult(
                accepted=_to_native(False),
                reason=f"TELEMETRY ERROR: Hardware telemetry source unhealthy for {subsystem_id}",
                previous_state=pre_transition_state,
                predicted=_to_native(predicted.trajectory) if predicted else None,
                safety_violations=["Telemetry source unhealthy"]
            )
        
        # Read telemetry from hardware layer ONLY (with timeout)
        with operation_timeout("telemetry_read", app_config.timeouts.get_telemetry_timeout()):
            telemetry_reading: TelemetryReading = telemetry_interface.read_telemetry(subsystem_id)
        observed = telemetry_reading.trajectory

        # 5. Multi-Dimensional Risk Assessment
        context = {
            "belt_age_hours": getattr(subsystem, 'belt_age_hours', 0.0),
            "splice_count": getattr(subsystem, 'splice_count', 0),
            "last_inspection_hours": getattr(subsystem, 'last_inspection_hours', 0.0),
            "has_vibration_sensor": True,
            "has_temperature_sensor": True,
        }
        
        # 5. Multi-Dimensional Risk Assessment (with timeout)
        with operation_timeout("risk_assessment", app_config.timeouts.get_pipeline_timeout()):
            risk = self.risk_engine.assess(
                prediction=predicted,
                observation=observed,
                context=context,
                safety_violations=[] if is_safe else [safety_reason]
            )
        
        # 6. State Machine transition (with timeout)
        with operation_timeout("state_machine_transition", app_config.timeouts.get_pipeline_timeout()):
            new_state = subsystem.transition(risk.overall_risk_score)
        
        # Build explanation from risk dimensions
        explanation_parts = []
        for dim, score in risk.dimensions.items():
            if score.risk_score >= 25:
                explanation_parts.append(f"{dim.value}: {score.risk_score:.1f} ({score.risk_level}) - {'; '.join(score.evidence) if score.evidence else 'no specific evidence'}")
        
        explanation = "; ".join(explanation_parts) if explanation_parts else "All risk dimensions within acceptable limits"
        
        return CommandResult(
            accepted=_to_native(True),
            reason=explanation,
            previous_state=pre_transition_state,
            predicted=_to_native(predicted.trajectory) if predicted else None,
            observed=_to_native(observed) if observed else None,
            risk=_to_native(risk) if risk else None,
            new_state=new_state,
            explanation=explanation,
            safety_violations=[],
            telemetry_source=telemetry_reading.source,
            telemetry_quality=telemetry_reading.quality,
            telemetry_sequence=telemetry_reading.sequence_id,
        )

# End of SecureGuardPipeline class