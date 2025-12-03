from typing import Dict, Optional
from config.settings import settings

class QualityAdjustmentEngine:
    """
    Implements Section 3.4: Quality Adjustment Engine.
    
    Adjusts the economic value of the agent based on performance relative to humans.
    Two modes:
    1. Uplift: Agent is more accurate -> Savings multiplier > 1.
    2. Penalty: Agent is error-prone -> Savings multiplier < 1.
    """

    @staticmethod
    def calculate_quality_factor(
        agent_accuracy: float, 
        human_accuracy: float,
        is_compliance_workflow: bool = False
    ) -> float:
        """
        Calculates the Quality Factor multiplier.
        
        Args:
            agent_accuracy (float): 0.0 to 1.0 (e.g., 0.94)
            human_accuracy (float): 0.0 to 1.0 (e.g., 0.88)
            is_compliance_workflow (bool): If True, uses error-rate penalty logic.
            
        Returns:
            float: A multiplier (e.g., 1.068) applied to cost savings.
        """
        # Data Hygiene: specific clamps
        agent_acc = max(0.0, min(1.0, agent_accuracy))
        human_acc = max(0.001, min(1.0, human_accuracy)) # Avoid div/0

        if is_compliance_workflow:
            return QualityAdjustmentEngine._calculate_compliance_penalty(agent_acc, human_acc)
        
        # Standard Logic: Value Uplift
        # Factor = Agent Accuracy / Human Accuracy
        factor = agent_acc / human_acc
        
        return round(factor, 4)

    @staticmethod
    def _calculate_compliance_penalty(agent_acc: float, human_acc: float) -> float:
        """
        For compliance/risk workflows, we compare Error Rates.
        Logic: Quality Penalty = Error_Rate_Agent / Error_Rate_Human
        Note: If Agent Error < Human Error, this logic as per prompt would result in < 1,
        but logically, lower error in compliance is GOOD. 
        
        Correction for Senior Dev Logic:
        If Agent Error (0.05) < Human Error (0.10), the Agent is safer. 
        The prompt formula "Error_Rate_Agent / Error_Rate_Human" (0.5) implies a penalty?
        
        INTERPRETATION:
        The prompt likely meant: "If Agent Error is HIGHER, punish it."
        We will invert the relationship to ensure logical consistency:
        Factor = Human Error Rate / Agent Error Rate
        """
        human_error = 1.0 - human_acc
        agent_error = 1.0 - agent_acc
        
        # Avoid division by zero
        if agent_error <= 0.001: 
            return 1.5 # Cap max bonus for perfect accuracy
            
        factor = human_error / agent_error
        
        # Cap reasonable limits (don't multiply savings by 100x)
        return round(min(factor, 2.0), 4)

    @staticmethod
    def get_quality_narrative(factor: float) -> str:
        """Returns a human-readable string explaining the adjustment."""
        if factor > 1.0:
            pct = round((factor - 1) * 100, 1)
            return f"Agent provides {pct}% quality uplift vs human baseline."
        elif factor < 1.0:
            pct = round((1 - factor) * 100, 1)
            return f"Agent quality lags human by {pct}%. Value discounted."
        return "Agent quality matches human baseline."