"""
state_machine.py — Per-subsystem Authorization State Machine (PCCR core)
"""

from enum import Enum
from dataclasses import dataclass, field
import persistence
from config import config

class AuthState(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    RESTRICTED = "RESTRICTED"
    QUARANTINED = "QUARANTINED"

RECOVERY_STREAK_REQUIRED = 3

AUTH_REQUIREMENT = {
    AuthState.NORMAL: "standard_rbac",
    AuthState.DEGRADED: "step_up_mfa_plus_fresh_prediction",
    AuthState.RESTRICTED: "step_up_mfa_plus_supervisor_approval_plus_fresh_prediction",
    AuthState.QUARANTINED: "all_actuator_commands_blocked_diagnostics_only",
}

@dataclass
class SubsystemAuthState:
    subsystem_id: str
    state: AuthState = AuthState.NORMAL
    consecutive_low_risk: int = 0
    history: list = field(default_factory=list)

    def _persist(self):
        persistence.save_subsystem_state(self.subsystem_id, self.state.value, self.consecutive_low_risk)

    def _risk_score_to_state(self, risk_score: float) -> AuthState:
        if risk_score < config.risk_threshold_degraded:
            return AuthState.NORMAL
        elif risk_score < config.risk_threshold_restricted:
            return AuthState.DEGRADED
        elif risk_score < config.risk_threshold_quarantined:
            return AuthState.RESTRICTED
        else:
            return AuthState.QUARANTINED

    def transition(self, risk_score: float, is_explicit_recovery_command: bool = False) -> AuthState:
        old_state = self.state
        candidate_state = self._risk_score_to_state(risk_score)

        escalation_order = [AuthState.NORMAL, AuthState.DEGRADED, AuthState.RESTRICTED, AuthState.QUARANTINED]
        old_idx = escalation_order.index(old_state)
        candidate_idx = escalation_order.index(candidate_state)
        
        is_low_risk = risk_score < config.risk_threshold_degraded

        if candidate_idx > old_idx:
            self.state = candidate_state
            self.consecutive_low_risk = 0

        elif candidate_idx < old_idx:
            if old_state == AuthState.QUARANTINED:
                if is_explicit_recovery_command and is_low_risk:
                    self.state = AuthState.RESTRICTED
                    self.consecutive_low_risk = 0
            else:
                if is_low_risk:
                    self.consecutive_low_risk += 1
                    if self.consecutive_low_risk >= RECOVERY_STREAK_REQUIRED:
                        self.state = escalation_order[old_idx - 1]
                        self.consecutive_low_risk = 0
                else:
                    self.consecutive_low_risk = 0
        else:
            if is_low_risk:
                self.consecutive_low_risk += 1
            else:
                self.consecutive_low_risk = 0

        self.history.append((risk_score, old_state, self.state))
        self._persist()
        return self.state

    def required_auth(self) -> str:
        return AUTH_REQUIREMENT[self.state]


class StateStore:
    def __init__(self):
        persistence.init_db()
        self._subsystems: dict[str, SubsystemAuthState] = {}

    def get(self, subsystem_id: str) -> SubsystemAuthState:
        if subsystem_id not in self._subsystems:
            row = persistence.load_subsystem_state(subsystem_id)
            if row:
                state_str, consecutive = row
                self._subsystems[subsystem_id] = SubsystemAuthState(
                    subsystem_id=subsystem_id,
                    state=AuthState(state_str),
                    consecutive_low_risk=consecutive,
                )
            else:
                self._subsystems[subsystem_id] = SubsystemAuthState(subsystem_id=subsystem_id)
        return self._subsystems[subsystem_id]

    def get_all(self) -> dict[str, SubsystemAuthState]:
        """Get all subsystems, loading from persistence if needed."""
        # Ensure default subsystems exist
        default_subsystems = ["Conveyor_Motor_01", "Conveyor_Motor_02", "Conveyor_Motor_03"]
        for sub_id in default_subsystems:
            if sub_id not in self._subsystems:
                self.get(sub_id)
        return self._subsystems.copy()
