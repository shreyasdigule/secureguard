"""
multi_dimensional_risk.py — Multi-Dimensional Risk Assessment Engine
Replaces single scalar residual with multi-dimensional risk vector.
Implements: Risk = Probability × Consequence across multiple dimensions.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from enum import Enum
import numpy as np
from digital_twin import Trajectory
from physics_digital_twin import Prediction
from config import config


class RiskDimension(Enum):
    """Dimensions of risk for conveyor systems."""
    SAFETY = "safety"                    # Harm to people
    ASSET = "asset"                      # Equipment damage/loss
    OPERATIONAL = "operational"          # Throughput/quality loss
    ENVIRONMENTAL = "environmental"      # Pollution, spillage, dust
    REGULATORY = "regulatory"            # Compliance, fines, license
    FINANCIAL = "financial"              # Revenue loss, repair costs


class ConveyorApplication(Enum):
    """Conveyor application types with different risk profiles."""
    MINING_OVERLAND = "mining_overland"
    MINING_UNDERGROUND = "mining_underground"
    PORT_BULK_TERMINAL = "port_bulk_terminal"
    FOOD_PROCESSING = "food_processing"
    AIRPORT_BAGGAGE = "airport_baggage"
    MANUFACTURING_ASSEMBLY = "manufacturing_assembly"
    WAREHOUSE_PARCEL = "warehouse_parcel"
    CEMENT_AGGREGATE = "cement_aggregate"
    POWER_PLANT_COAL = "power_plant_coal"
    POWER_PLANT_BIOMASS = "power_plant_biomass"


class RiskDimensionScore:
    """Score for a single risk dimension with probability and consequence."""
    
    def __init__(self, 
                 dimension: RiskDimension,
                 probability: float,      # 0-1 probability of adverse event
                 consequence: float,      # Consequence severity (0-1 normalized)
                 confidence: float,       # Confidence in assessment (0-1)
                 time_horizon_hours: float,  # Time horizon for risk
                 evidence: List[str] = None):
        self.dimension = dimension
        self.probability = np.clip(probability, 0.0, 1.0)
        self.consequence = np.clip(consequence, 0.0, 1.0)
        self.confidence = np.clip(confidence, 0.0, 1.0)
        self.time_horizon_hours = time_horizon_hours
        self.evidence = evidence or []
    
    @property
    def risk_score(self) -> float:
        """Risk = Probability × Consequence (normalized 0-100)"""
        return self.probability * self.consequence * 100.0
    
    @property
    def risk_level(self) -> str:
        score = self.risk_score
        if score >= 75: return "CRITICAL"
        elif score >= 50: return "HIGH"
        elif score >= 25: return "MEDIUM"
        else: return "LOW"


@dataclass
class MultiDimensionalRisk:
    """Complete multi-dimensional risk assessment."""
    dimensions: Dict[RiskDimension, RiskDimensionScore] = field(default_factory=dict)
    application: ConveyorApplication = ConveyorApplication.MANUFACTURING_ASSEMBLY
    operating_phase: str = "steady_state"  # startup, steady_state, shutdown, emergency, maintenance
    material_type: str = "generic"
    environment: str = "indoor"
    belt_age_hours: float = 0.0
    splice_count: int = 0
    last_inspection_hours: float = 0.0
    
    def __post_init__(self):
        # Ensure all dimensions exist
        for dim in RiskDimension:
            if dim not in self.dimensions:
                self.dimensions[dim] = RiskDimensionScore(
                    dimension=dim, probability=0.0, consequence=0.0, confidence=0.5, time_horizon_hours=24.0
                )
    
    @property
    def overall_risk_score(self) -> float:
        """Weighted overall risk score."""
        weights = {
            RiskDimension.SAFETY: 0.35,
            RiskDimension.ASSET: 0.20,
            RiskDimension.OPERATIONAL: 0.15,
            RiskDimension.ENVIRONMENTAL: 0.10,
            RiskDimension.REGULATORY: 0.10,
            RiskDimension.FINANCIAL: 0.10,
        }
        return sum(
            self.dimensions[dim].risk_score * weights.get(dim, 0.0)
            for dim in RiskDimension
        )
    
    @property
    def overall_risk_level(self) -> str:
        score = self.overall_risk_score
        if score >= 75: return "CRITICAL"
        elif score >= 50: return "HIGH"
        elif score >= 25: return "MEDIUM"
        else: return "LOW"
    
    def get_dimension(self, dim: RiskDimension) -> RiskDimensionScore:
        return self.dimensions.get(dim, RiskDimensionScore(dimension=dim, probability=0.0, consequence=0.0, confidence=0.5, time_horizon_hours=24.0))
    
    def get_critical_dimensions(self, threshold: float = 50.0) -> List[RiskDimension]:
        return [dim for dim, score in self.dimensions.items() if score.risk_score >= threshold]


class ApplicationRiskProfile:
    """Risk profile for a specific conveyor application."""
    
    # Consequence weights per application (0-1 normalized)
    CONSEQUENCE_WEIGHTS = {
        ConveyorApplication.MINING_OVERLAND: {
            RiskDimension.SAFETY: 0.30,
            RiskDimension.ASSET: 0.25,
            RiskDimension.OPERATIONAL: 0.20,
            RiskDimension.ENVIRONMENTAL: 0.15,
            RiskDimension.REGULATORY: 0.05,
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.MINING_UNDERGROUND: {
            RiskDimension.SAFETY: 0.40,  # Fire/explosion risk
            RiskDimension.ASSET: 0.20,
            RiskDimension.OPERATIONAL: 0.15,
            RiskDimension.ENVIRONMENTAL: 0.10,
            RiskDimension.REGULATORY: 0.10,
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.PORT_BULK_TERMINAL: {
            RiskDimension.SAFETY: 0.20,
            RiskDimension.ASSET: 0.25,
            RiskDimension.OPERATIONAL: 0.30,  # Ship loading deadlines
            RiskDimension.ENVIRONMENTAL: 0.15,  # Dust, spillage
            RiskDimension.REGULATORY: 0.05,
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.FOOD_PROCESSING: {
            RiskDimension.SAFETY: 0.15,
            RiskDimension.ASSET: 0.15,
            RiskDimension.OPERATIONAL: 0.20,
            RiskDimension.ENVIRONMENTAL: 0.10,
            RiskDimension.REGULATORY: 0.30,  # FDA/FSMA/HACCP
            RiskDimension.FINANCIAL: 0.15,
        },
        ConveyorApplication.AIRPORT_BAGGAGE: {
            RiskDimension.SAFETY: 0.25,
            RiskDimension.ASSET: 0.15,
            RiskDimension.OPERATIONAL: 0.35,  # Missed flights
            RiskDimension.ENVIRONMENTAL: 0.05,
            RiskDimension.REGULATORY: 0.15,  # TSA/ECAC
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.MANUFACTURING_ASSEMBLY: {
            RiskDimension.SAFETY: 0.25,
            RiskDimension.ASSET: 0.20,
            RiskDimension.OPERATIONAL: 0.30,
            RiskDimension.ENVIRONMENTAL: 0.05,
            RiskDimension.REGULATORY: 0.10,
            RiskDimension.FINANCIAL: 0.10,
        },
        ConveyorApplication.WAREHOUSE_PARCEL: {
            RiskDimension.SAFETY: 0.20,
            RiskDimension.ASSET: 0.15,
            RiskDimension.OPERATIONAL: 0.35,  # Sorting accuracy, SLA
            RiskDimension.ENVIRONMENTAL: 0.05,
            RiskDimension.REGULATORY: 0.10,
            RiskDimension.FINANCIAL: 0.15,
        },
        ConveyorApplication.CEMENT_AGGREGATE: {
            RiskDimension.SAFETY: 0.20,
            RiskDimension.ASSET: 0.30,  # Abrasive wear
            RiskDimension.OPERATIONAL: 0.20,
            RiskDimension.ENVIRONMENTAL: 0.15,  # Dust
            RiskDimension.REGULATORY: 0.10,
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.POWER_PLANT_COAL: {
            RiskDimension.SAFETY: 0.30,  # Fire, dust explosion
            RiskDimension.ASSET: 0.20,
            RiskDimension.OPERATIONAL: 0.25,
            RiskDimension.ENVIRONMENTAL: 0.15,
            RiskDimension.REGULATORY: 0.05,
            RiskDimension.FINANCIAL: 0.05,
        },
        ConveyorApplication.POWER_PLANT_BIOMASS: {
            RiskDimension.SAFETY: 0.35,  # Spontaneous combustion
            RiskDimension.ASSET: 0.20,
            RiskDimension.OPERATIONAL: 0.20,
            RiskDimension.ENVIRONMENTAL: 0.15,
            RiskDimension.REGULATORY: 0.03,
            RiskDimension.FINANCIAL: 0.02,
        },
    }
    
    # Probability multipliers per operating phase
    PHASE_PROBABILITY_MULTIPLIERS = {
        "startup": {
            RiskDimension.SAFETY: 2.0,
            RiskDimension.ASSET: 1.5,
            RiskDimension.OPERATIONAL: 1.2,
            RiskDimension.ENVIRONMENTAL: 1.0,
            RiskDimension.REGULATORY: 1.0,
            RiskDimension.FINANCIAL: 1.0,
        },
        "steady_state": {
            RiskDimension.SAFETY: 1.0,
            RiskDimension.ASSET: 1.0,
            RiskDimension.OPERATIONAL: 1.0,
            RiskDimension.ENVIRONMENTAL: 1.0,
            RiskDimension.REGULATORY: 1.0,
            RiskDimension.FINANCIAL: 1.0,
        },
        "shutdown": {
            RiskDimension.SAFETY: 1.5,
            RiskDimension.ASSET: 1.2,
            RiskDimension.OPERATIONAL: 1.0,
            RiskDimension.ENVIRONMENTAL: 1.0,
            RiskDimension.REGULATORY: 1.0,
            RiskDimension.FINANCIAL: 1.0,
        },
        "emergency": {
            RiskDimension.SAFETY: 5.0,
            RiskDimension.ASSET: 3.0,
            RiskDimension.OPERATIONAL: 2.0,
            RiskDimension.ENVIRONMENTAL: 2.0,
            RiskDimension.REGULATORY: 2.0,
            RiskDimension.FINANCIAL: 1.5,
        },
        "maintenance": {
            RiskDimension.SAFETY: 3.0,
            RiskDimension.ASSET: 2.0,
            RiskDimension.OPERATIONAL: 0.5,
            RiskDimension.ENVIRONMENTAL: 1.0,
            RiskDimension.REGULATORY: 1.5,
            RiskDimension.FINANCIAL: 1.0,
        },
    }
    
    @classmethod
    def get_weights(cls, application: ConveyorApplication) -> Dict[RiskDimension, float]:
        """Raw authored taxonomy: relative importance weights summing to 1.0."""
        return cls.CONSEQUENCE_WEIGHTS.get(application, cls.CONSEQUENCE_WEIGHTS[ConveyorApplication.MANUFACTURING_ASSEMBLY])

    @classmethod
    def get_severities(cls, application: ConveyorApplication) -> Dict[RiskDimension, float]:
        """
        Convert the taxonomy weights into absolute 0-1 consequence severities.

        ``CONSEQUENCE_WEIGHTS`` are *relative* importance weights that sum to
        1.0 across the six dimensions, so feeding them straight into
        ``risk_score = probability * consequence * 100`` suppresses every score
        and makes the 25/50/75 bands unreachable. With the raw weights, four of
        six dimensions could never exceed 20 even at certainty, and no dimension
        could ever exceed 30 — so the level was permanently "LOW".

        Dividing by the profile maximum rescales so the dominant dimension has
        severity 1.0 while the relative ordering inside the profile is
        preserved (underground mining still outweighs its financial dimension).
        """
        weights = cls.get_weights(application)
        peak = max(weights.values()) if weights else 1.0
        if peak <= 0:
            return {dim: 0.0 for dim in RiskDimension}
        return {dim: (weight / peak) for dim, weight in weights.items()}
    
    @classmethod
    def get_phase_multipliers(cls, phase: str) -> Dict[RiskDimension, float]:
        return cls.PHASE_PROBABILITY_MULTIPLIERS.get(phase, cls.PHASE_PROBABILITY_MULTIPLIERS["steady_state"])


class MultiDimensionalRiskEngine:
    """
    Multi-Dimensional Risk Assessment Engine.
    Replaces single scalar residual with multi-dimensional risk vector.
    Risk = Probability × Consequence across multiple dimensions.
    """
    
    def __init__(self, 
                 application: ConveyorApplication = ConveyorApplication.MANUFACTURING_ASSEMBLY,
                 operating_phase: str = "steady_state",
                 material_type: str = "generic",
                 environment: str = "indoor"):
        self.application = application
        self.operating_phase = operating_phase
        self.material_type = material_type
        self.environment = environment
        self.consequence_weights = ApplicationRiskProfile.get_weights(application)
        self.phase_multipliers = ApplicationRiskProfile.get_phase_multipliers(operating_phase)
    
    def assess(self, 
               prediction: Trajectory | Prediction,
               observation: Trajectory,
               context: Dict,
               safety_violations: List[str] = None) -> "MultiDimensionalRisk":
        """
        Compute multi-dimensional risk from prediction vs observation.
        
        Args:
            prediction: Digital twin prediction (Prediction or Trajectory)
            observation: Actual sensor observation (Trajectory)
            context: Context dict with subsystem_id, belt_age, splice_count, etc.
            safety_violations: List of safety violations from safety envelope
            
        Returns:
            MultiDimensionalRisk with per-dimension scores
        """
        # Extract trajectory from prediction if it's a Prediction object
        trajectory = prediction.trajectory if hasattr(prediction, 'trajectory') else prediction
        
        # 1. Compute prediction errors
        errors = self._compute_errors(trajectory, observation)
        
        # 2. Get base probabilities from errors
        base_probabilities = self._errors_to_probabilities(errors)
        
        # 3. Apply phase multipliers
        probabilities = self._apply_phase_multipliers(base_probabilities)
        
        # 4. Apply context modifiers (belt age, splice count, material, environment)
        probabilities = self._apply_context_modifiers(probabilities, context)
        
        # 5. Apply safety violations
        probabilities = self._apply_safety_violations(probabilities, safety_violations)
        
        # 6. Compute consequences per dimension
        trajectory = prediction.trajectory if hasattr(prediction, 'trajectory') else prediction
        consequences = self._compute_consequences(trajectory, observation, context)
        
        # 7. Build dimension scores
        dimensions = {}
        for dim in RiskDimension:
            prob = probabilities.get(dim, 0.0)
            consequence = consequences.get(dim, 0.0)
            confidence = self._compute_confidence(dim, errors, context)
            time_horizon = self._estimate_time_horizon(dim, context)
            evidence = self._gather_evidence(dim, errors, context)
            
            dimensions[dim] = RiskDimensionScore(
                dimension=dim,
                probability=prob,
                consequence=consequence,
                confidence=confidence,
                time_horizon_hours=time_horizon,
                evidence=evidence
            )
        
        # 8. Apply safety violations override
        if safety_violations:
            for dim in [RiskDimension.SAFETY, RiskDimension.ASSET]:
                dimensions[dim].probability = max(dimensions[dim].probability, 0.9)
                dimensions[dim].consequence = max(dimensions[dim].consequence, 0.9)
        
        return MultiDimensionalRisk(
            dimensions=dimensions,
            application=self.application,
            operating_phase=self.operating_phase,
            material_type=self.material_type,
            environment=self.environment,
            belt_age_hours=context.get("belt_age_hours", 0.0),
            splice_count=context.get("splice_count", 0),
            last_inspection_hours=context.get("last_inspection_hours", 0.0)
        )
    
    def _compute_errors(self, prediction: Trajectory, observation: Trajectory) -> Dict[str, float]:
        """Compute normalized prediction errors."""
        errors = {}
        
        # Speed error
        pred_speed = prediction.motor_speed_rpm
        obs_speed = observation.motor_speed_rpm
        errors["speed"] = abs(obs_speed - pred_speed) / (abs(pred_speed) if abs(pred_speed) > 1 else 1.0)
        
        # Current error
        pred_current = prediction.motor_current_amps
        obs_current = observation.motor_current_amps
        errors["current"] = abs(obs_current - pred_current) / (abs(pred_current) if abs(pred_current) > 0.1 else 1.0)
        
        # Temperature error
        pred_temp = prediction.temperature_c
        obs_temp = observation.temperature_c
        errors["temperature"] = abs(obs_temp - pred_temp) / (abs(pred_temp) if abs(pred_temp) > 1 else 1.0)
        
        # Box rate error
        pred_box = prediction.box_rate_per_min
        obs_box = observation.box_rate_per_min
        errors["box_rate"] = abs(obs_box - pred_box) / (abs(pred_box) if abs(pred_box) > 1 else 1.0)
        
        # State mismatch
        errors["state_mismatch"] = 1.0 if observation.conveyor_state != prediction.conveyor_state else 0.0
        
        return errors
    
    def _errors_to_probabilities(self, errors: Dict[str, float]) -> Dict[RiskDimension, float]:
        """Convert prediction errors to failure probabilities per risk dimension."""
        probs = {dim: 0.0 for dim in RiskDimension}
        
        # Speed error → Operational, Safety (overspeed)
        speed_err = errors.get("speed", 0.0)
        probs[RiskDimension.OPERATIONAL] += min(speed_err * 0.8, 1.0)
        probs[RiskDimension.SAFETY] += min(speed_err * 0.3, 1.0)  # Overspeed risk
        
        # Current error → Asset (bearing/motor), Safety (overcurrent), Operational
        current_err = errors.get("current", 0.0)
        probs[RiskDimension.ASSET] += min(current_err * 1.2, 1.0)      # Bearing/motor damage
        probs[RiskDimension.SAFETY] += min(current_err * 0.5, 1.0)     # Fire, overcurrent
        probs[RiskDimension.OPERATIONAL] += min(current_err * 0.5, 1.0)
        
        # Temperature error → Asset (insulation), Safety (fire), Environmental
        temp_err = errors.get("temperature", 0.0)
        probs[RiskDimension.ASSET] += min(temp_err * 0.8, 1.0)         # Insulation degradation
        probs[RiskDimension.SAFETY] += min(temp_err * 0.6, 1.0)        # Fire risk
        probs[RiskDimension.ENVIRONMENTAL] += min(temp_err * 0.3, 1.0)  # Heat emission
        
        # Box rate error → Operational (throughput), Financial (SLA)
        box_err = errors.get("box_rate", 0.0)
        probs[RiskDimension.OPERATIONAL] += min(box_err * 1.0, 1.0)
        probs[RiskDimension.FINANCIAL] += min(box_err * 0.5, 1.0)
        
        # State mismatch → Safety, Operational
        if errors.get("state_mismatch", 0.0) > 0.5:
            probs[RiskDimension.SAFETY] += 0.8
            probs[RiskDimension.OPERATIONAL] += 0.6
        
        return {dim: min(prob, 1.0) for dim, prob in probs.items()}
    
    def _apply_phase_multipliers(self, probabilities: Dict[RiskDimension, float]) -> Dict[RiskDimension, float]:
        multipliers = self.phase_multipliers
        return {dim: min(prob * multipliers.get(dim, 1.0), 1.0) for dim, prob in probabilities.items()}
    
    def _apply_context_modifiers(self, probabilities: Dict[RiskDimension, float], context: Dict) -> Dict[RiskDimension, float]:
        """Apply context modifiers: belt age, splice count, material, environment."""
        probs = probabilities.copy()
        
        # Belt age degradation
        belt_age = context.get("belt_age_hours", 0.0)
        if belt_age > 50000:
            age_factor = 1.0 + (belt_age - 50000) / 100000  # Increases with age
            for dim in [RiskDimension.ASSET, RiskDimension.SAFETY]:
                probabilities[dim] = min(probabilities.get(dim, 0.0) * age_factor, 1.0)
        
        # Splice count
        splice_count = context.get("splice_count", 0)
        if splice_count > 3:
            splice_factor = 1.0 + (splice_count - 3) * 0.15
            for dim in [RiskDimension.ASSET, RiskDimension.SAFETY]:
                probabilities[dim] = min(probabilities.get(dim, 0.0) * splice_factor, 1.0)
        
        # Material type modifiers
        material = self.material_type.lower()
        if material in ["coal", "biomass"]:
            probabilities[RiskDimension.SAFETY] = min(probabilities.get(RiskDimension.SAFETY, 0.0) * 1.5, 1.0)
            probabilities[RiskDimension.ENVIRONMENTAL] = min(probabilities.get(RiskDimension.ENVIRONMENTAL, 0.0) * 2.0, 1.0)
            if material == "biomass":
                probabilities[RiskDimension.SAFETY] = min(probabilities.get(RiskDimension.SAFETY, 0.0) * 1.3, 1.0)  # Spontaneous combustion
        elif material in ["food", "pharma"]:
            probabilities[RiskDimension.REGULATORY] = min(probabilities.get(RiskDimension.REGULATORY, 0.0) * 2.0, 1.0)
            probabilities[RiskDimension.ENVIRONMENTAL] = min(probabilities.get(RiskDimension.ENVIRONMENTAL, 0.0) * 0.5, 1.0)
        
        # Environment modifiers
        env = self.environment.lower()
        if env in ["underground", "confined"]:
            probabilities[RiskDimension.SAFETY] = min(probabilities.get(RiskDimension.SAFETY, 0.0) * 2.0, 1.0)
            probabilities[RiskDimension.ENVIRONMENTAL] = min(probabilities.get(RiskDimension.ENVIRONMENTAL, 0.0) * 1.5, 1.0)
        elif env in ["outdoor", "exposed"]:
            probabilities[RiskDimension.ASSET] = min(probabilities.get(RiskDimension.ASSET, 0.0) * 1.3, 1.0)
            probabilities[RiskDimension.ENVIRONMENTAL] = min(probabilities.get(RiskDimension.ENVIRONMENTAL, 0.0) * 1.5, 1.0)
        
        return probabilities
    
    def _apply_safety_violations(self, probabilities: Dict[RiskDimension, float], violations: List[str]) -> Dict[RiskDimension, float]:
        probs = probabilities.copy()
        if not violations:
            return probs
        
        for v in violations:
            v_lower = v.lower()
            if any(k in v_lower for k in ["temp", "temperature", "fire", "heat"]):
                probs[RiskDimension.SAFETY] = max(probs.get(RiskDimension.SAFETY, 0.0), 0.9)
                probs[RiskDimension.ASSET] = max(probs.get(RiskDimension.ASSET, 0.0), 0.8)
            elif any(k in v_lower for k in ["current", "overcurrent", "motor"]):
                probs[RiskDimension.ASSET] = max(probs.get(RiskDimension.ASSET, 0.0), 0.9)
                probs[RiskDimension.SAFETY] = max(probs.get(RiskDimension.SAFETY, 0.0), 0.7)
            elif any(k in v_lower for k in ["speed", "overspeed", "overshoot"]):
                probs[RiskDimension.SAFETY] = max(probs.get(RiskDimension.SAFETY, 0.0), 0.9)
                probs[RiskDimension.OPERATIONAL] = max(probs.get(RiskDimension.OPERATIONAL, 0.0), 0.8)
            elif any(k in v_lower for k in ["vibration", "bearing", "alignment"]):
                probs[RiskDimension.ASSET] = max(probs.get(RiskDimension.ASSET, 0.0), 0.9)
                probs[RiskDimension.SAFETY] = max(probs.get(RiskDimension.SAFETY, 0.0), 0.6)
            else:
                probs[RiskDimension.SAFETY] = max(probs.get(RiskDimension.SAFETY, 0.0), 0.7)
                probs[RiskDimension.ASSET] = max(probs.get(RiskDimension.ASSET, 0.0), 0.6)
        return probs
    
    def _compute_consequences(self, prediction: Trajectory, observation: Trajectory, context: Dict) -> Dict[RiskDimension, float]:
        """Compute consequence severity (0-1) per dimension."""
        consequences = {dim: 0.0 for dim in RiskDimension}
        # Severities (0-1 absolute), not the raw sum-to-1.0 weights.
        weights = ApplicationRiskProfile.get_severities(self.application)
        
        # Base consequence from application profile
        for dim, weight in weights.items():
            consequences[dim] = weight
        
        # Modify based on prediction severity
        pred_current = prediction.motor_current_amps
        pred_temp = prediction.temperature_c
        pred_speed = abs(prediction.motor_speed_rpm)
        
        # High current → higher asset/safety consequence
        if pred_current > 8.0:
            consequences[RiskDimension.ASSET] = min(consequences[RiskDimension.ASSET] * 1.5, 1.0)
            consequences[RiskDimension.SAFETY] = min(consequences[RiskDimension.SAFETY] * 1.3, 1.0)
        
        # High temperature → safety, asset, environmental
        if pred_temp > 70:
            consequences[RiskDimension.SAFETY] = min(consequences[RiskDimension.SAFETY] * 1.5, 1.0)
            consequences[RiskDimension.ASSET] = min(consequences[RiskDimension.ASSET] * 1.3, 1.0)
            consequences[RiskDimension.ENVIRONMENTAL] = min(consequences[RiskDimension.ENVIRONMENTAL] * 1.3, 1.0)
        
        # High speed → operational, safety
        if pred_speed > 800:
            consequences[RiskDimension.OPERATIONAL] = min(consequences[RiskDimension.OPERATIONAL] * 1.3, 1.0)
            consequences[RiskDimension.SAFETY] = min(consequences[RiskDimension.SAFETY] * 1.2, 1.0)
        
        # Apply application weights as base consequence
        for dim, weight in weights.items():
            consequences[dim] = max(consequences[dim], weight)
        
        return {dim: min(conseq, 1.0) for dim, conseq in consequences.items()}
    
    def _compute_confidence(self, dim: RiskDimension, errors: Dict[str, float], context: Dict) -> float:
        """Compute confidence in risk assessment (0-1)."""
        base_confidence = 0.7
        
        # Reduce confidence with sparse data
        belt_age = context.get("belt_age_hours", 0)
        if belt_age > 100000:
            base_confidence *= 0.8
        
        # Reduce confidence with sparse sensors
        if not context.get("has_vibration_sensor", True):
            base_confidence *= 0.9
        if not context.get("has_temperature_sensor", True):
            base_confidence *= 0.85
        
        # Reduce for high uncertainty dimensions
        if dim in [RiskDimension.ENVIRONMENTAL, RiskDimension.REGULATORY]:
            base_confidence *= 0.8
        
        return np.clip(base_confidence, 0.3, 0.95)
    
    def _estimate_time_horizon(self, dim: RiskDimension, context: Dict) -> float:
        """Estimate time horizon for risk manifestation (hours)."""
        horizons = {
            RiskDimension.SAFETY: 24.0,          # Immediate to hours
            RiskDimension.ASSET: 720.0,          # Days to weeks
            RiskDimension.OPERATIONAL: 24.0,     # Immediate
            RiskDimension.ENVIRONMENTAL: 168.0,  # Days to weeks
            RiskDimension.REGULATORY: 720.0,     # Weeks to months
            RiskDimension.FINANCIAL: 168.0,      # Weeks
        }
        base = horizons.get(dim, 168.0)
        
        # Adjust for operating phase
        phase = self.operating_phase
        if self.operating_phase == "startup":
            return base * 0.1
        elif self.operating_phase == "emergency":
            return base * 0.01
        return base
    
    def _gather_evidence(self, dim: RiskDimension, errors: Dict[str, float], context: Dict) -> List[str]:
        """Gather evidence strings for this risk dimension."""
        evidence = []
        
        if dim == RiskDimension.SAFETY:
            if errors.get("temperature", 0) > 0.15:
                evidence.append(f"Temperature deviation: {errors['temperature']*100:.0f}%")
            if errors.get("current", 0) > 0.2:
                evidence.append(f"Current deviation: {errors['current']*100:.0f}%")
            if errors.get("speed", 0) > 0.2:
                evidence.append(f"Speed deviation: {errors['speed']*100:.0f}%")
        elif dim == RiskDimension.ASSET:
            if errors.get("current", 0) > 0.15:
                evidence.append(f"Current deviation: {errors['current']*100:.0f}% (bearing/motor stress)")
            if errors.get("temperature", 0) > 0.1:
                evidence.append(f"Temperature deviation: {errors['temperature']*100:.0f}% (insulation stress)")
        elif dim == RiskDimension.OPERATIONAL:
            if errors.get("speed", 0) > 0.1:
                evidence.append(f"Speed deviation: {errors['speed']*100:.0f}%")
            if errors.get("box_rate", 0) > 0.2:
                evidence.append(f"Box rate deviation: {errors['box_rate']*100:.0f}%")
        elif dim == RiskDimension.ENVIRONMENTAL:
            if errors.get("temperature", 0) > 0.1:
                evidence.append(f"Temperature deviation: {errors['temperature']*100:.0f}% (heat emission)")
        elif dim == RiskDimension.FINANCIAL:
            if errors.get("box_rate", 0) > 0.15:
                evidence.append(f"Throughput deviation: {errors['box_rate']*100:.0f}% (SLA risk)")
        
        return evidence
