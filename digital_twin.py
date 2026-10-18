"""
digital_twin.py — Conveyor Digital Twin & Safety Envelope
"""

import math
from dataclasses import dataclass
from config import config

@dataclass
class Trajectory:
    conveyor_state: str  # "STOPPED" or "RUNNING"
    motor_speed_rpm: float
    motor_current_amps: float
    temperature_c: float
    box_rate_per_min: float

class SafetyEnvelope:
    """
    "Should this commanded operating point be allowed?"
    Validates physical limits BEFORE execution.
    """
    def validate(self, target_rpm: float, predicted: Trajectory, torque_limit: float = 100.0, direction: str = "FWD") -> tuple[bool, str]:
        if target_rpm < 0:
            return False, "Target motor speed cannot be negative."
        if predicted.motor_current_amps < 0:
            return False, "Predicted current cannot be negative."
        if predicted.temperature_c < 0:
            return False, "Predicted temperature cannot be negative."
        if predicted.box_rate_per_min < 0:
            return False, "Predicted box rate cannot be negative."
            
        if target_rpm > config.max_safe_rpm:
            return False, f"Target motor speed ({target_rpm} RPM) exceeds the configured safety limit ({config.max_safe_rpm} RPM)."
        if predicted.motor_current_amps > config.max_safe_current_amps:
            return False, f"Predicted current ({predicted.motor_current_amps} A) exceeds safety limit ({config.max_safe_current_amps} A)."
        if predicted.temperature_c > config.max_safe_temperature_c:
            return False, f"Predicted temperature ({predicted.temperature_c} C) exceeds safety limit ({config.max_safe_temperature_c} C)."
        if predicted.box_rate_per_min > config.max_safe_box_rate_per_min:
            return False, f"Predicted box rate ({predicted.box_rate_per_min}) exceeds safety limit ({config.max_safe_box_rate_per_min})."
            
        if math.isnan(target_rpm) or math.isinf(target_rpm):
            return False, "Invalid target motor speed (NaN or Inf)."
        
        # Torque limit validation
        if torque_limit > 150.0:
            return False, f"Torque limit ({torque_limit}%) exceeds maximum allowed (150%)."
        if torque_limit < 10.0:
            return False, f"Torque limit ({torque_limit}%) below minimum allowed (10%)."
        
        # Direction validation
        if direction not in ("FWD", "REV"):
            return False, f"Invalid direction '{direction}'. Must be FWD or REV."
        
        return True, "Safe"

class ConveyorDigitalTwin:
    """
    Predicts expected conveyor behavior given a command.
    """
    def predict(
        self,
        from_speed_rpm: float,
        to_speed_rpm: float,
        accel_rate: float = 100.0,
        decel_rate: float = 150.0,
        torque_limit: float = 100.0,
        direction: str = "FWD",
        ctrl_mode: str = "VELOCITY",
    ) -> Trajectory:
        # DEVELOPMENT PLACEHOLDERS: Simple deterministic equations for the prototype.
        # These are NOT validated machine physics and must be replaced when hardware arrives.
        
        # Apply control mode effects
        if ctrl_mode == "TORQUE":
            # Torque control mode - current scales with torque limit
            base_current = 2.0 + (0.002 * to_speed_rpm)
            predicted_current = base_current * (torque_limit / 100.0)
        elif ctrl_mode == "POSITION":
            # Position control - higher current for positioning accuracy
            base_current = 2.0 + (0.002 * to_speed_rpm)
            predicted_current = base_current * 1.2
        else:
            # VELOCITY mode (default)
            predicted_current = 0.0 if to_speed_rpm == 0 else 2.0 + (0.002 * to_speed_rpm)
        
        # Apply torque limit
        predicted_current = min(predicted_current, 10.0 * (torque_limit / 100.0))
        
        # Apply direction
        effective_speed = to_speed_rpm if direction == "FWD" else -to_speed_rpm
        
        # Apply acceleration/deceleration effects on current
        if accel_rate < 50:
            predicted_current *= 1.1  # Slow accel = higher sustained current
        if decel_rate < 50:
            predicted_current *= 1.05  # Slow decel = regenerative current
        
        # Temperature prediction - affected by current and speed
        predicted_temp = config.normal_temperature_c + (abs(effective_speed) / 100.0) + (predicted_current * 0.5)
        
        # Box rate prediction - affected by speed and direction
        predicted_box_rate = 0.0 if effective_speed == 0 else config.normal_box_rate_per_min * (abs(effective_speed) / 500.0)
        
        conveyor_state = "STOPPED" if effective_speed == 0 else "RUNNING"
        
        return Trajectory(
            conveyor_state=conveyor_state,
            motor_speed_rpm=float(effective_speed),
            motor_current_amps=round(predicted_current, 2),
            temperature_c=round(predicted_temp, 1),
            box_rate_per_min=round(predicted_box_rate, 1)
        )
