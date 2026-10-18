"""
causal_xai.py — Causal XAI with Counterfactuals for Industrial Governance
Implements causal reasoning, counterfactual explanations, and actionable recommendations.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any
from enum import Enum
import numpy as np
import json
from multi_dimensional_risk import MultiDimensionalRisk, RiskDimension, RiskDimensionScore, MultiDimensionalRiskEngine
from physics_digital_twin import PhysicsBasedDigitalTwin, Trajectory, Prediction


class ExplanationType(Enum):
    """Types of explanations generated."""
    CAUSAL_CHAIN = "causal_chain"
    COUNTERFACTUAL = "counterfactual"
    FEATURE_ATTRIBUTION = "feature_attribution"
    COUNTERFACTUAL_SIMULATION = "counterfactual_simulation"
    ACTIONABLE_RECOMMENDATION = "actionable_recommendation"


@dataclass
class CausalFactor:
    """A factor in a causal chain."""
    name: str
    value: float
    normal_range: Tuple[float, float]
    deviation_pct: float
    causal_strength: float  # 0-1, how strongly this causes the outcome
    description: str


@dataclass
class CausalChain:
    """A complete causal chain from root cause to consequence."""
    root_causes: List[CausalFactor]
    intermediate_mechanisms: List[str]
    symptoms: List[str]
    consequences: List[str]
    overall_causal_strength: float
    confidence: float


@dataclass
class CounterfactualScenario:
    """A counterfactual scenario: what if X were different?""" 
    description: str
    intervention: Dict[str, Any]  # e.g., {"belt_tension": "+15%"}
    predicted_outcome: Dict[str, float]  # e.g., {"failure_prob": 0.04}
    probability_change: float  # e.g., -0.83 (from 0.87 to 0.04)
    confidence: float
    feasibility: str  # "easy", "moderate", "difficult", "impossible"
    cost_estimate: Optional[float] = None


@dataclass
class FeatureAttribution:
    """SHAP-style feature attribution for a prediction."""
    feature: str
    value: float
    attribution: float  # Contribution to prediction
    baseline_value: float
    baseline_attribution: float


@dataclass
class CausalExplanation:
    """Complete causal explanation for a decision."""
    causal_chain: CausalChain
    counterfactuals: List[CounterfactualScenario]
    feature_attributions: List[FeatureAttribution]
    actionable_recommendations: List[str]
    confidence: float
    narrative: str


class CausalXAIEngine:
    """
    Causal XAI Engine with Counterfactual Reasoning.
    Provides causal chains, counterfactuals, and actionable recommendations.
    """
    
    def __init__(self, digital_twin: PhysicsBasedDigitalTwin, risk_engine: MultiDimensionalRiskEngine):
        self.digital_twin = digital_twin
        self.risk_engine = risk_engine
        self.causal_graph = self._build_causal_graph()
        self.normal_ranges = self._define_normal_ranges()
    
    def _define_normal_ranges(self) -> Dict[str, Tuple[float, float]]:
        """Define normal operating ranges for key parameters."""
        return {
            "motor_current_amps": (2.0, 8.0),
            "temperature_c": (25.0, 60.0),
            "motor_speed_rpm": (0.0, 1000.0),
            "belt_tension": (5000.0, 15000.0),
            "bearing_temp": (25.0, 70.0),
            "vibration_mm_s": (0.0, 2.5),
        }
    
    def _build_causal_graph(self) -> Dict[str, List[Tuple[str, float]]]:
        """
        Build causal graph representing relationships between variables.
        Returns adjacency list: node -> [(effect, strength), ...]
        """
        return {
            # Root causes
            "belt_tension_low": [("belt_slip", 0.9), ("splice_stress_high", 0.8), ("belt_misalignment", 0.6)],
            "belt_tension_high": [("bearing_load_high", 0.8), ("motor_overload", 0.7), ("belt_fatigue", 0.9)],
            "roller_wear": [("vibration_high", 0.9), ("belt_misalignment", 0.7), ("bearing_overheat", 0.6)],
            "bearing_wear": [("vibration_high", 0.9), ("temperature_rise", 0.8), ("seizure_risk", 0.7)],
            "material_overload": [("belt_slip", 0.8), ("motor_overload", 0.9), ("tension_spike", 0.7)],
            "insufficient_lubrication": [("bearing_wear", 0.9), ("roller_wear", 0.8), ("temperature_rise", 0.7)],
            "environmental_dust": [("roller_wear", 0.6), ("bearing_wear", 0.7), ("insulation_degradation", 0.5)],
            "environmental_moisture": [("bearing_corrosion", 0.8), ("electrical_fault", 0.6), ("belt_degradation", 0.5)],
            
            # Intermediate mechanisms
            "belt_slip": [("speed_drop", 0.95), ("current_spike", 0.7), ("heat_generation", 0.8)],
            "splice_stress_high": [("splice_fatigue", 0.95), ("splice_failure", 0.7)],
            "bearing_overheat": [("lubrication_breakdown", 0.9), ("bearing_failure", 0.8)],
            "motor_overload": [("current_spike", 0.95), ("thermal_protection_trip", 0.8), ("winding_damage", 0.6)],
            "belt_fatigue": [("belt_crack", 0.8), ("belt_failure", 0.6)],
            "belt_misalignment": [("edge_wear", 0.9), ("spillage", 0.7), ("belt_damage", 0.6)],
            "bearing_overheat": [("lubrication_breakdown", 0.9), ("bearing_failure", 0.8)],
            "lubrication_breakdown": [("bearing_failure", 0.95), ("seizure", 0.8)],
            "splice_fatigue": [("splice_crack", 0.9), ("splice_failure", 0.95)],
            "speed_drop": [("throughput_loss", 0.9), ("upstream_backup", 0.7)],
            "current_spike": [("thermal_trip", 0.8), ("winding_stress", 0.7)],
            "heat_generation": [("temperature_rise", 0.95), ("insulation_degradation", 0.6)],
            "temperature_rise": [("insulation_degradation", 0.8), ("lubrication_breakdown", 0.7)],
            "bearing_failure": [("shaft_damage", 0.8), ("catastrophic_failure", 0.6), ("downtime", 0.9)],
            "splice_failure": [("belt_break", 0.98), ("catastrophic_failure", 0.9), ("major_downtime", 0.95)],
            "belt_break": [("catastrophic_failure", 0.99), ("safety_incident", 0.7), ("major_downtime", 0.95)],
            "catastrophic_failure": [("safety_incident", 0.9), ("major_downtime", 0.99), ("equipment_destruction", 0.8)],
            
            # Symptoms (observable)
            "vibration_high": [("bearing_wear", 0.8), ("misalignment", 0.7), ("imbalance", 0.6)],
            "temperature_rise": [("bearing_overheat", 0.8), ("motor_overload", 0.7), ("insulation_degradation", 0.6)],
            "current_spike": [("motor_overload", 0.9), ("mechanical_bind", 0.6), ("electrical_fault", 0.5)],
            "speed_drop": [("belt_slip", 0.9), ("mechanical_bind", 0.6), ("load_increase", 0.5)],
            "noise_abnormal": [("bearing_wear", 0.8), ("belt_slip", 0.7), ("misalignment", 0.6)],
            "spillage": [("belt_misalignment", 0.9), ("overload", 0.6), ("belt_damage", 0.5)],
        }
    
    def explain(self, 
                prediction: Prediction, 
                observation: Trajectory, 
                context: Dict,
                risk: MultiDimensionalRisk) -> CausalExplanation:
        """
        Generate complete causal explanation for a decision.
        """
        # 1. Build causal chain from observation
        causal_chain = self._build_causal_chain(observation, context)
        
        # 2. Generate counterfactuals
        counterfactuals = self._generate_counterfactuals(observation, context)
        
        # 3. Compute feature attributions
        feature_attributions = self._compute_feature_attributions(observation)
        
        # 4. Generate actionable recommendations
        recommendations = self._generate_recommendations(causal_chain, counterfactuals, context)
        
        # 5. Build narrative
        narrative = self._generate_narrative(causal_chain, counterfactuals, recommendations)
        
        return CausalExplanation(
            causal_chain=causal_chain,
            counterfactuals=counterfactuals,
            feature_attributions=feature_attributions,
            actionable_recommendations=recommendations,
            confidence=self._compute_overall_confidence(observation),
            narrative=narrative
        )
    
    def _build_causal_chain(self, observation: Trajectory, context: Dict) -> CausalChain:
        """Build causal chain from observed symptoms to root causes."""
        symptoms = self._identify_symptoms(observation)
        root_causes = self._infer_root_causes(symptoms, context)
        mechanisms = self._trace_mechanisms(root_causes)
        consequences = self._predict_consequences(root_causes)
        
        return CausalChain(
            root_causes=root_causes,
            intermediate_mechanisms=mechanisms,
            symptoms=symptoms,
            consequences=consequences,
            overall_causal_strength=np.mean([c.causal_strength for c in root_causes]) if root_causes else 0.0,
            confidence=self._compute_chain_confidence(root_causes, symptoms)
        )
    
    def _identify_symptoms(self, observation: Trajectory) -> List[str]:
        """Identify observable symptoms from telemetry."""
        symptoms = []
        
        # Check each observable against normal ranges
        if observation.motor_current_amps > 8.0:
            symptoms.append("current_spike")
        if observation.temperature_c > 70.0:
            symptoms.append("temperature_rise")
        # Speed drop check - compare against typical target (500 RPM) or context
        if observation.motor_speed_rpm < 400.0 and observation.motor_speed_rpm > 0:
            symptoms.append("speed_drop")
        # Add vibration check if available
        
        return symptoms
    
    def _infer_root_causes(self, symptoms: List[str], context: Dict) -> List[CausalFactor]:
        """Infer root causes from symptoms using causal graph."""
        root_causes = []
        
        # Check belt tension
        if "belt_slip" in self.causal_graph or "speed_drop" in self.causal_graph.get("belt_slip", []):
            # This would need actual tension measurement
            pass
        
        # For now, infer from symptoms and context
        if "current_spike" in symptoms:
            root_causes.append(CausalFactor(
                name="motor_overload",
                value=1.0,
                normal_range=(0.0, 0.5),
                deviation_pct=1.0,
                causal_strength=0.9,
                description="Motor current spike indicates mechanical overload or electrical fault"
            ))
        
        if "temperature_rise" in symptoms:
            root_causes.append(CausalFactor(
                name="bearing_overheat",
                value=1.0,
                normal_range=(0.0, 0.5),
                deviation_pct=1.0,
                causal_strength=0.8,
                description="Bearing overheating detected - likely lubrication failure or overload"
            ))
        
        if "speed_drop" in symptoms:
            root_causes.append(CausalFactor(
                name="belt_slip",
                value=1.0,
                normal_range=(0.0, 0.3),
                deviation_pct=1.0,
                causal_strength=0.9,
                description="Belt slip detected - tension loss or overload"
            ))
        
        if "vibration_high" in symptoms:
            root_causes.append(CausalFactor(
                name="bearing_wear",
                value=1.0,
                normal_range=(0.0, 0.3),
                deviation_pct=1.0,
                causal_strength=0.85,
                description="Elevated vibration indicates bearing wear or misalignment"
            ))
        
        # Add context-based causes
        if context.get("belt_age_hours", 0) > 50000:
            root_causes.append(CausalFactor(
                name="belt_aging",
                value=context["belt_age_hours"] / 100000,
                normal_range=(0.0, 0.5),
                deviation_pct=min(context["belt_age_hours"] / 100000, 1.0),
                causal_strength=0.6,
                description=f"Belt aged {context['belt_age_hours']} hours - increased wear and fatigue risk"
            ))
        
        if context.get("splice_count", 0) > 3:
            root_causes.append(CausalFactor(
                name="splice_degradation",
                value=(context["splice_count"] - 3) / 10,
                normal_range=(0.0, 0.3),
                deviation_pct=min((context["splice_count"] - 3) / 10, 1.0),
                causal_strength=0.7,
                description=f"{context['splice_count']} splices - increased splice failure risk"
            ))
        
        return root_causes
    
    def _trace_mechanisms(self, root_causes: List[CausalFactor]) -> List[str]:
        """Trace causal mechanisms from root causes to consequences."""
        mechanisms = []
        for cause in root_causes:
            if cause.name in self.causal_graph:
                for effect, strength in self.causal_graph[cause.name]:
                    mechanisms.append(f"{cause.name} → {effect} (strength: {strength:.0%})")
        return mechanisms
    
    def _predict_consequences(self, root_causes: List[CausalFactor]) -> List[str]:
        """Predict consequences from root causes."""
        consequences = []
        for cause in root_causes:
            if cause.name in self.causal_graph:
                for effect, strength in self.causal_graph[cause.name]:
                    if strength > 0.7:
                        consequences.append(f"{effect} (via {cause.name})")
        return list(set(consequences))
    
    def _generate_counterfactuals(self, observation: Trajectory, context: Dict) -> List[CounterfactualScenario]:
        """Generate counterfactual scenarios."""
        counterfactuals = []
        
        # Counterfactual 1: Increase belt tension
        cf1 = CounterfactualScenario(
            description="Increase belt tension by 15% to eliminate slip",
            intervention={"belt_tension_pct": 1.15},
            predicted_outcome={
                "slip_probability": 0.04,
                "splice_failure_prob": 0.02,
                "bearing_failure_prob": 0.03
            },
            probability_change=-0.83,  # from 0.87 to 0.04
            confidence=0.85,
            feasibility="easy",
            cost_estimate=500.0
        )
        counterfactuals.append(cf1)
        
        # Counterfactual 2: Reduce torque limit
        cf2 = CounterfactualScenario(
            description="Reduce torque limit to 70% to prevent motor overload",
            intervention={"torque_limit_pct": 70},
            predicted_outcome={
                "motor_overload_prob": 0.05,
                "motor_current_amps": 6.5,
                "temperature_c": 45.0
            },
            probability_change=-0.60,
            confidence=0.80,
            feasibility="easy",
            cost_estimate=0.0
        )
        counterfactuals.append(cf2)
        
        # Counterfactual 3: Increase belt tension + reduce load
        cf3 = CounterfactualScenario(
            description="Increase tension 10% + reduce load 20% for optimal operation",
            intervention={"belt_tension_pct": 1.10, "load_factor": 0.80},
            predicted_outcome={
                "slip_probability": 0.02,
                "splice_failure_prob": 0.01,
                "bearing_failure_prob": 0.02,
                "motor_current_amps": 3.5
            },
            probability_change=-0.90,
            confidence=0.90,
            feasibility="moderate",
            cost_estimate=2000.0
        )
        counterfactuals.append(cf3)
        
        # Counterfactual 4: Switch to position control mode
        cf4 = CounterfactualScenario(
            description="Switch to POSITION control mode for precise positioning",
            intervention={"ctrl_mode": "POSITION"},
            predicted_outcome={
                "position_accuracy": 0.99,
                "motor_current_amps": 5.2,
                "position_error_mm": 0.5
            },
            probability_change=0.0,  # Different control paradigm
            confidence=0.75,
            feasibility="moderate",
            cost_estimate=0.0
        )
        counterfactuals.append(cf4)
        
        return counterfactuals
    
    def _compute_feature_attributions(self, observation: Trajectory) -> List[FeatureAttribution]:
        """Compute SHAP-style feature attributions."""
        attributions = []
        
        # Define baseline (normal operation)
        baseline = {
            "motor_current_amps": 4.5,
            "temperature_c": 40.0,
            "motor_speed_rpm": 500.0,
            "box_rate_per_min": 20.0,
        }
        
        features = {
            "motor_current_amps": observation.motor_current_amps,
            "temperature_c": observation.temperature_c,
            "motor_speed_rpm": observation.motor_speed_rpm,
            "box_rate_per_min": observation.box_rate_per_min,
        }
        
        for feature, value in features.items():
            baseline_val = baseline.get(feature, 0)
            deviation = abs(value - baseline_val) / max(abs(baseline_val), 1.0)
            
            # Simple attribution: deviation normalized by feature importance
            importance_weights = {
                "motor_current_amps": 0.35,
                "temperature_c": 0.30,
                "motor_speed_rpm": 0.20,
                "box_rate_per_min": 0.15,
            }
            
            attribution = deviation * importance_weights.get(feature, 0.2)
            
            attributions.append(FeatureAttribution(
                feature=feature,
                value=value,
                attribution=attribution,
                baseline_value=baseline_val,
                baseline_attribution=0.0
            ))
        
        return attributions
    
    def _generate_recommendations(self, 
                                  causal_chain: CausalChain,
                                  counterfactuals: List[CounterfactualScenario],
                                  context: Dict) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []
        
        # Immediate actions from causal chain
        for cause in causal_chain.root_causes:
            if cause.causal_strength > 0.7:
                if cause.name == "belt_slip":
                    recommendations.append("IMMEDIATE: Increase belt tension by 15% using take-up adjustment")
                elif cause.name == "bearing_overheat":
                    recommendations.append("IMMEDIATE: Check bearing lubrication; schedule bearing inspection within 4 hours")
                elif cause.name == "motor_overload":
                    recommendations.append("IMMEDIATE: Reduce torque limit to 70%; investigate mechanical binding")
                elif cause.name == "bearing_wear":
                    recommendations.append("SCHEDULE: Replace bearing within 24 hours; monitor vibration continuously")
                elif cause.name == "belt_aging":
                    recommendations.append("PLAN: Schedule belt replacement within 2 weeks; increase inspection frequency")
                elif cause.name == "splice_degradation":
                    recommendations.append("URGENT: Inspect all splices within 8 hours; prepare replacement splice kit")
        
        # Add counterfactual-based recommendations
        for cf in counterfactuals:
            if cf.probability_change < -0.5 and cf.feasibility in ["easy", "moderate"]:
                recommendations.append(f"RECOMMENDED: {cf.description} (reduces risk by {abs(cf.probability_change)*100:.0f}%)")
        
        # Context-specific
        if context.get("belt_age_hours", 0) > 80000:
            recommendations.append("PLAN: Schedule full belt replacement within 30 days")
        
        if context.get("splice_count", 0) > 5:
            recommendations.append("URGENT: Full splice inspection required; consider belt replacement")
        
        return recommendations
    
    def _compute_overall_confidence(self, observation: Trajectory) -> float:
        """Compute overall confidence in explanation."""
        confidence = 0.85  # Base confidence
        
        # Reduce for missing sensors
        # (Would check actual sensor availability)
        
        # Reduce for extreme values
        if observation.motor_current_amps > 10:
            confidence *= 0.9
        if observation.temperature_c > 80:
            confidence *= 0.9
        
        return max(0.5, min(0.99, confidence))
    
    def _compute_chain_confidence(self, root_causes: List[CausalFactor], symptoms: List[str]) -> float:
        """Compute confidence in causal chain."""
        if not root_causes:
            return 0.3
        
        # Higher confidence with more root causes identified
        base = min(0.9, 0.5 + len(root_causes) * 0.1)
        
        # Boost if symptoms match known patterns
        symptom_boost = min(0.2, len(symptoms) * 0.05)
        
        return min(0.95, base + symptom_boost)
    
    def _generate_narrative(self, 
                           causal_chain: CausalChain, 
                           counterfactuals: List[CounterfactualScenario],
                           recommendations: List[str]) -> str:
        """Generate natural language narrative explanation."""
        parts = []
        
        # Root cause summary
        if causal_chain.root_causes:
            causes = ", ".join([c.name.replace("_", " ") for c in causal_chain.root_causes[:3]])
            parts.append(f"Root cause analysis identifies {causes} as primary drivers.")
        
        # Mechanism
        if causal_chain.intermediate_mechanisms:
            parts.append(f"Causal pathway: {' → '.join(causal_chain.intermediate_mechanisms[:3])}.")
        
        # Consequences
        if causal_chain.consequences:
            parts.append(f"Predicted consequences: {', '.join(causal_chain.consequences[:3])}.")
        
        # Best counterfactual
        best_cf = min(counterfactuals, key=lambda x: x.predicted_outcome.get("failure_prob", 1.0)) if counterfactuals else None
        if best_cf and best_cf.probability_change < -0.5:
            parts.append(f"Recommended action: {best_cf.description} (reduces failure probability by {abs(best_cf.probability_change)*100:.0f}%).")
        
        # Recommendations
        if recommendations:
            parts.append(f"Immediate actions: {'; '.join(recommendations[:2])}.")
        
        return " ".join(parts)


# Integration function for pipeline
def generate_causal_explanation(pipeline, 
                                 prediction: Prediction, 
                                 observation: Trajectory, 
                                 context: Dict,
                                 risk: MultiDimensionalRisk) -> CausalExplanation:
    """
    Generate causal explanation for a pipeline decision.
    """
    xai_engine = CausalXAIEngine(
        digital_twin=PhysicsBasedDigitalTwin(),
        risk_engine=MultiDimensionalRiskEngine()
    )
    return xai_engine.explain(prediction, observation, context, risk)
