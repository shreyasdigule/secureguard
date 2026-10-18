"""
residual_engine.py — Anomaly Detection and Risk Scoring
Compares predicted vs observed.
"""

from dataclasses import dataclass
from digital_twin import Trajectory
from config import config

@dataclass
class ResidualBreakdown:
    residual: float
    risk_score: float
    risk_level: str
    explanation: str

class ResidualEngine:
    def compute(self, predicted: Trajectory, observed: Trajectory, safety_violations: list[str] = None) -> ResidualBreakdown:
        if safety_violations is None:
            safety_violations = []

        # Numerical errors (normalized)
        speed_error = abs(observed.motor_speed_rpm - predicted.motor_speed_rpm) / (predicted.motor_speed_rpm if predicted.motor_speed_rpm > 0 else 1.0)
        current_error = abs(observed.motor_current_amps - predicted.motor_current_amps) / (predicted.motor_current_amps if predicted.motor_current_amps > 0 else 1.0)
        temp_error = abs(observed.temperature_c - predicted.temperature_c) / (predicted.temperature_c if predicted.temperature_c > 0 else 1.0)
        box_rate_error = abs(observed.box_rate_per_min - predicted.box_rate_per_min) / (predicted.box_rate_per_min if predicted.box_rate_per_min > 0 else 1.0)

        # Conveyor state mismatch (adds to residual)
        state_mismatch_penalty = 1.0 if observed.conveyor_state != predicted.conveyor_state else 0.0

        # Weighted residual
        residual = (
            config.weight_speed * min(speed_error, 1.0) +
            config.weight_current * min(current_error, 1.0) +
            config.weight_temperature * min(temp_error, 1.0) +
            config.weight_box_rate * min(box_rate_error, 1.0) +
            0.5 * state_mismatch_penalty # state mismatch is a major anomaly
        )
        
        # Cap residual for risk mapping
        residual = min(residual, 1.0)

        risk_score = residual * 100.0
        
        # If there are safety violations, max out the risk score
        if safety_violations:
            risk_score = 100.0

        if risk_score >= config.risk_threshold_quarantined:
            risk_level = "CRITICAL"
        elif risk_score >= config.risk_threshold_restricted:
            risk_level = "HIGH"
        elif risk_score >= config.risk_threshold_degraded:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
            
        explanation = self._explain(predicted, observed, speed_error, current_error, temp_error, box_rate_error, safety_violations)
        
        return ResidualBreakdown(
            residual=round(residual, 3),
            risk_score=round(risk_score, 1),
            risk_level=risk_level,
            explanation=explanation
        )

    def _explain(self, predicted: Trajectory, observed: Trajectory, speed_error: float, current_error: float, temp_error: float, box_rate_error: float, safety_violations: list[str]) -> str:
        parts = []
        
        if safety_violations:
            parts.extend(safety_violations)
            
        if observed.conveyor_state != predicted.conveyor_state:
            parts.append(f"Observed conveyor state differs from predicted state")
            
        if speed_error > 0.1:
            if observed.motor_speed_rpm > predicted.motor_speed_rpm:
                parts.append(f"Motor speed is {speed_error*100:.0f}% above expected target")
            else:
                parts.append(f"Motor speed is {speed_error*100:.0f}% below expected target")
                
        if current_error > 0.15:
            if observed.motor_current_amps > predicted.motor_current_amps:
                parts.append(f"Motor current is significantly higher ({current_error*100:.0f}%) than the Digital Twin prediction")
            else:
                parts.append(f"Motor current is significantly lower ({current_error*100:.0f}%) than expected")
                
        if temp_error > 0.15:
            if observed.temperature_c > predicted.temperature_c:
                diff = observed.temperature_c - predicted.temperature_c
                parts.append(f"Temperature is {diff:.1f}C above the expected operating value")
                
        if box_rate_error > 0.2:
            parts.append(f"Box rate deviates by {box_rate_error*100:.0f}% from expected rate for commanded speed")
            
        if not parts:
            return "Behavior consistent with prediction"
            
        return "; ".join(parts)
