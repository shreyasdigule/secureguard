"""
physics_digital_twin.py — Physics-Based Digital Twin for Conveyor Systems
Implements DIN 22101 / ISO 5048 belt mechanics, thermal modeling, wear/fatigue.
Replaces linear heuristics with physics-based predictions.
"""

from dataclasses import dataclass
import numpy as np
from digital_twin import Trajectory
from config import config


@dataclass
class ConveyorSpecification:
    """Complete conveyor specification for physics-based modeling."""
    # Geometry
    length: float = 100.0              # m
    lift_height: float = 10.0          # m
    belt_width: float = 1.0            # m
    belt_speed_nominal: float = 2.0    # m/s
    
    # Belt properties
    belt_type: str = "fabric"          # "steel_cord", "fabric", "pipe"
    belt_modulus: float = 500.0        # N/mm² (dynamic modulus)
    belt_density: float = 1200.0       # kg/m³
    belt_thickness: float = 15.0       # mm
    belt_mass_per_m: float = 25.0      # kg/m
    
    # Mechanical
    drive_pulley_dia: float = 0.8      # m
    tail_pulley_dia: float = 0.8       # m
    drive_pulley_lagging: str = "rubber"
    friction_coeff: float = 0.35       # belt/pulley friction
    
    # Idlers
    idler_spacing: float = 1.2         # m
    idler_roll_dia: float = 150.0      # mm
    idler_pitch: int = 3               # 3-roll, 5-roll
    
    # Drive - 7.5kW motor (matches ~15A at 400V)
    motor_power: float = 7.5           # kW
    motor_rated_speed: float = 1500.0  # RPM
    gearbox_ratio: float = 20.0
    gearbox_efficiency: float = 0.97
    
    # Environment
    ambient_temp: float = 25.0         # °C
    altitude: float = 100.0            # m
    
    # Material
    material_density: float = 1.6      # t/m³
    material_surcharge_angle: float = 20.0  # degrees
    material_friction_angle: float = 35.0   # degrees
    
    # Safety limits (from config)
    max_safe_rpm: float = 1000.0
    max_safe_current_amps: float = 10.0
    max_safe_temperature_c: float = 80.0
    max_safe_box_rate_per_min: float = 60.0


class BeltMechanicsModel:
    """
    DIN 22101 / ISO 5048 compliant belt mechanics.
    Computes tension profile, power, slip, wave propagation.
    """
    
    def __init__(self, spec: ConveyorSpecification):
        self.spec = spec
        self._precompute_constants()
    
    def _precompute_constants(self):
        s = self.spec
        self.belt_area = s.belt_width * s.belt_thickness / 1e6  # m²
        self.m_belt = s.belt_mass_per_m
        self.m_material = self._material_mass_per_m()
        self.m_total = self.m_belt + self.m_material
        self.r_drive = s.drive_pulley_dia / 2
        self.mu_drive = self._friction_coefficient(s.drive_pulley_lagging)
        self.mu_idler = 0.02
        self.wave_speed = np.sqrt(s.belt_modulus * 1e6 / s.belt_density)
    
    def _material_mass_per_m(self) -> float:
        s = self.spec
        A = (s.belt_width / 1000)**2 * np.tan(np.radians(s.material_surcharge_angle)) / 4
        return A * s.material_density * 1000
    
    def _friction_coefficient(self, lagging: str) -> float:
        return {"rubber": 0.35, "ceramic": 0.45, "bare": 0.25}.get(lagging, 0.30)
    
    def steady_state_tension(self, speed_mps: float, load_factor: float = 1.0) -> dict:
        """DIN 22101 steady-state tension calculation."""
        s = self.spec
        m = self.m_total * load_factor
        
        C = 0.030
        f = 0.022
        L = s.length
        H = s.lift_height
        g = 9.81
        
        F_H = C * m * g * L * np.cos(np.arcsin(H/L)) if L > 0 else 0
        F_S = f * m * g * L
        F_L = m * g * H
        
        F_total = F_H + F_S + F_L
        
        T1 = F_total / (1 - np.exp(-self.mu_drive * np.pi))
        T2 = T1 - F_total
        
        return {
            "T1_drive": T1,
            "T2_tail": T2,
            "T_max": T1,
            "T_min": T2,
            "F_total": F_total,
            "slip_risk": T1 / (T1 - T2) > 1.0 / (1 - np.exp(-self.mu_drive * np.pi))
        }
    
    def dynamic_tension_wave(self, speed_change: float, dt: float) -> np.ndarray:
        """Solve 1D wave equation for tension propagation."""
        c = self.wave_speed
        L = self.spec.length
        nx = 100
        x = np.linspace(0, L, nx)
        dx = L / (nx - 1)
        
        T = np.ones(nx) * self.steady_state_tension(1.0)["T1_drive"]
        
        for _ in range(int(dt / (dx/c))):
            T_new = T.copy()
            for i in range(1, nx-1):
                T_new[i] = T[i] + (c**2 * dt**2 / dx**2) * (T[i+1] - 2*T[i] + T[i-1])
            T = T_new
        
        return T
    
    def slip_probability(self, tension: float, speed: float, torque: float) -> float:
        T1 = tension
        T2 = tension - torque / self.r_drive
        slip_ratio = T2 / T1
        critical_ratio = np.exp(-self.mu_drive * np.pi)
        margin = slip_ratio / critical_ratio
        if margin >= 1.0:
            return 0.0
        return 1.0 - margin


class ThermalModel:
    """Physics-based thermal model for conveyor components."""
    
    def __init__(self, spec: ConveyorSpecification):
        self.spec = spec
        self._thermal_network = self._build_thermal_network()
    
    def _build_thermal_network(self) -> dict:
        return {
            "motor": {"R_th": 0.5, "C_th": 5000, "P_loss": 0.0},
            "drive_bearing": {"R_th": 2.0, "C_th": 500, "P_loss": 0.0},
            "idler_bearing": {"R_th": 5.0, "C_th": 200, "P_loss": 0.0},
            "belt": {"R_th": 10.0, "C_th": 2000, "P_loss": 0.0},
            "ambient": {"T": self.spec.ambient_temp, "R_th": 0.0}
        }
    
    def update_power_losses(self, state: dict):
        I = state.get("motor_current", 0)
        R_motor = 0.5
        self._thermal_network["motor"]["P_loss"] = I**2 * R_motor
        
        speed = abs(state.get("motor_speed_rpm", 0))
        load = state.get("torque", 0)
        self._thermal_network["drive_bearing"]["P_loss"] = 0.001 * speed * load
        
        n_idlers = int(self.spec.length / self.spec.idler_spacing)
        self._thermal_network["idler_bearing"]["P_loss"] = n_idlers * 0.0005 * abs(state.get("motor_speed_rpm", 0))
        
        belt_speed = abs(state.get("motor_speed_rpm", 0)) * np.pi * self.spec.drive_pulley_dia / 60
        tension = state.get("tension", 10000)
        self._thermal_network["belt"]["P_loss"] = 0.01 * belt_speed * tension / 10000
    
    def step(self, dt: float) -> dict:
        temps = {}
        for node, props in self._thermal_network.items():
            if node == "ambient":
                temps[node] = props["T"]
                continue
            Q_out = (temps.get(node, self.spec.ambient_temp) - self.spec.ambient_temp) / props["R_th"]
            dT = (props["P_loss"] - Q_out) / props["C_th"] * dt
            temps[node] = temps.get(node, self.spec.ambient_temp) + dT
        return temps


class WearFatigueModel:
    """Physics-based wear and fatigue accumulation."""
    
    def __init__(self, spec: ConveyorSpecification):
        self.spec = spec
        self.cumulative_damage = {
            "belt_wear": 0.0,
            "splice_fatigue": 0.0,
            "bearing_life_used": 0.0,
            "splice_aging": 0.0
        }
    
    def update(self, dt: float, state: dict, command: dict):
        speed = abs(state.get("motor_speed_rpm", 0))
        load = abs(state.get("load_factor", 1.0))
        temp = state.get("temperature_c", 25)
        tension = state.get("tension", 10000)
        
        # 1. Belt wear (Archard's law)
        k_wear = 1e-6 * (1 + 0.01 * (state.get("temperature_c", 25) - 25))
        normal_force = state.get("tension", 10000) / 1000
        sliding_distance = abs(state.get("motor_speed_rpm", 0)) * np.pi * 0.5 / 60
        wear_rate = 1e-8 * normal_force * sliding_distance
        self.cumulative_damage["belt_wear"] += wear_rate * dt
        
        # 2. Splice fatigue (Palmgren-Miner)
        stress_range = abs(state.get("tension", 10000) - 10000) / 1000
        if stress_range > 10:
            A = 1e12
            b = 3.0
            cycles_to_failure = A * stress_range ** -b
            cycles_per_sec = abs(state.get("motor_speed_rpm", 0)) / 60
            damage_rate = cycles_per_sec / cycles_to_failure
            self.cumulative_damage["splice_fatigue"] += damage_rate * dt
        
        # 3. Bearing life (L10)
        C = 100000
        P = abs(state.get("load_factor", 1.0)) * 5000
        if P > 0:
            L10_revs = (100000 / P) ** 3 * 1e6
            revs_per_sec = abs(state.get("motor_speed_rpm", 0)) / 60
            bearing_life_rate = revs_per_sec / L10_revs
            self.cumulative_damage["bearing_life_used"] += bearing_life_rate * dt
        
        # 4. Splice aging (Arrhenius)
        Ea = 80000
        R = 8.314
        T_kelvin = state.get("temperature_c", 25) + 273.15
        aging_rate = 1e10 * np.exp(-Ea / (R * T_kelvin))
        self.cumulative_damage["splice_aging"] += aging_rate * dt
    
    def failure_probabilities(self) -> dict:
        d = self.cumulative_damage
        return {
            "belt_wear": min(1.0, d["belt_wear"] / 5.0),
            "splice_failure": min(1.0, d["splice_fatigue"]),
            "bearing_failure": min(1.0, d["bearing_life_used"]),
            "splice_aging": min(1.0, d["splice_aging"] / 1.0),
            "overall": max(
                min(1.0, d["belt_wear"] / 5.0),
                min(1.0, d["splice_fatigue"]),
                min(1.0, d["bearing_life_used"]),
                min(1.0, d["splice_aging"] / 1.0)
            )
        }
    
    def remaining_useful_life(self) -> dict:
        d = self.cumulative_damage
        return {
            "belt_wear_hours": max(0, (5.0 - d["belt_wear"]) / 1e-6) / 3600,
            "splice_fatigue_hours": (1.0 - d["splice_fatigue"]) / 1e-6 / 3600 if d["splice_fatigue"] < 1 else 0,
            "bearing_life_hours": (1.0 - d["bearing_life_used"]) / 1e-6 / 3600 if d["bearing_life_used"] < 1 else 0,
            "splice_aging_hours": (1.0 - d["splice_aging"]) / 1e-6 / 3600 if d["splice_aging"] < 1 else 0
        }


class PhysicsBasedDigitalTwin:
    """Unified physics-based digital twin replacing heuristics."""
    
    def __init__(self, spec: ConveyorSpecification = None):
        self.spec = spec or ConveyorSpecification()
        self.belt_mechanics = BeltMechanicsModel(self.spec)
        self.thermal = ThermalModel(self.spec)
        self.wear_fatigue = WearFatigueModel(self.spec)
        self._state_history = []
    
    def predict(
        self,
        command: dict,
        current_state: dict,
        environment: dict,
        dt: float = 1.0
    ) -> "Prediction":
        """Full physics-based prediction."""
        
        # 1. Belt mechanics prediction
        tension_calc = self.belt_mechanics.steady_state_tension(
            speed_mps=command.get("to_speed_rpm", 0) * np.pi * self.spec.drive_pulley_dia / 60,
            load_factor=command.get("load_factor", 1.0)
        )
        
        # 2. Motor electrical model
        # Rated torque at base speed
        rated_torque = self.spec.motor_power * 1000 / (2 * np.pi * self.spec.motor_rated_speed / 60)
        
        # Available torque based on torque limit and speed
        speed_rpm = command.get("to_speed_rpm", 0)
        if speed_rpm > 0:
            omega = 2 * np.pi * speed_rpm / 60
            # Below base speed: constant torque; above base speed: constant power
            if speed_rpm <= self.spec.motor_rated_speed:
                available_torque = rated_torque * (command.get("torque_limit", 100) / 100)
            else:
                # Above base speed: constant power region
                available_torque = min(
                    rated_torque * (command.get("torque_limit", 100) / 100),
                    self.spec.motor_power * 1000 / (2 * np.pi * speed_rpm / 60)
                )
        else:
            available_torque = 0.0
        
        torque = available_torque
        motor_current = self._motor_current_model(torque, speed_rpm)
        
        # 3. Thermal prediction
        predicted_state = {
            "motor_current": motor_current,
            "torque": torque,
            "tension": tension_calc["T1_drive"],
            "motor_speed_rpm": command.get("to_speed_rpm", 0),
            "temperature_c": 35.0,
            "load_factor": command.get("load_factor", 1.0)
        }
        
        self.thermal.update_power_losses(predicted_state)
        temps = self.thermal.step(1.0)
        
        # 5. Wear/fatigue update
        self.wear_fatigue.update(1.0, predicted_state, command)
        failure_probs = self.wear_fatigue.failure_probabilities()
        
        # 6. Safety checks
        slip_prob = self.belt_mechanics.slip_probability(
            tension_calc["T1_drive"], 
            command.get("to_speed_rpm", 0),
            command.get("torque_limit", 100)
        )
        
        predicted_trajectory = Trajectory(
            conveyor_state="RUNNING" if command.get("to_speed_rpm", 0) > 0 else "STOPPED",
            motor_speed_rpm=command.get("to_speed_rpm", 0),
            motor_current_amps=motor_current,
            temperature_c=temps.get("motor", 35.0),
            box_rate_per_min=self._predict_box_rate(command)
        )
        
        uncertainty = self._quantify_uncertainty(command, predicted_state)
        
        return Prediction(
            trajectory=predicted_trajectory,
            tension_profile=tension_calc,
            temperatures=temps,
            failure_probabilities=failure_probs,
            slip_probability=slip_prob,
            uncertainty=uncertainty,
            wear_state=self.wear_fatigue.cumulative_damage,
            remaining_life=self.wear_fatigue.remaining_useful_life()
        )
    
    def _motor_current_model(self, torque: float, speed_rpm: float) -> float:
        omega = 2 * np.pi * abs(speed_rpm) / 60
        torque_nm = torque / 100 * 150 * 1000 / (2 * np.pi * 1500 / 60)
        P_mech = torque * omega
        P_elec = P_mech / 0.9
        V = 400; pf = 0.85
        I = P_elec / (np.sqrt(3) * V * pf)
        return I
    
    def _predict_box_rate(self, command: dict) -> float:
        speed = command.get("to_speed_rpm", 0)
        return 0.0 if speed == 0 else 20.0 * abs(speed) / 500.0
    
    def _quantify_uncertainty(self, command: dict, state: dict) -> dict:
        return {
            "current_std": 0.15,
            "temp_std": 1.5,
            "speed_std": 5.0,
            "box_rate_std": 1.0
        }


@dataclass
class Prediction:
    trajectory: Trajectory
    tension_profile: dict
    temperatures: dict
    failure_probabilities: dict
    slip_probability: float
    uncertainty: dict
    wear_state: dict
    remaining_life: dict


# Backward compatibility - replace ConveyorDigitalTwin
ConveyorDigitalTwin = PhysicsBasedDigitalTwin
