# cost-savings/services/interactive_service.py

from typing import Dict, Any, List
from models.context_models import ImportedLLMCall

class InteractiveSavingsCalculator:
    """
    The Math Engine for the Interactive Mode.
    Calculates ROI based on EXPLICIT user parameters (e.g., "Human Rate is $50/hr").
    """

    def compute(self, payload: Any) -> Dict[str, Any]:
        """
        Main calculation logic.
        Payload is 'InteractiveCalculationRequest' (feature_name, selected_parameters, ai_cost).
        """
        params = payload.selected_parameters
        ai_monthly_cost = payload.ai_estimated_cost
        
        # 1. Extract Core Metrics (with safe defaults)
        hourly_rate = params.get("human_hourly_rate", 30.0)
        throughput = params.get("human_throughput", 10.0) # units/hr
        accuracy = params.get("human_accuracy", 0.95)
        
        # 2. Determine Volume Context
        # Since the UI sends the AI Cost (Monthly), we try to reverse-engineer volume 
        # or assume a standard "1 FTE equivalent" workload if volume is unknown.
        # For this calculation, we calculate the "Break-Even Point" and "Per-Unit Savings".
        
        # Human Cost Per Unit = (Hourly Rate / Throughput)
        if throughput > 0:
            human_cost_per_unit = hourly_rate / throughput
        else:
            human_cost_per_unit = 0.0

        # 3. Calculate "Human Equivalent Monthly Cost"
        # We estimate how much it would cost a human to do what the AI does for 'ai_monthly_cost'.
        # We assume the AI cost represents the full workload. 
        # Logic: If AI cost is $50 (approx 2M tokens), that's ~2000 units.
        # This is hard to guess without 'volume', so we provide 'Per 1k Units' analysis.
        
        units_batch = 1000.0
        human_cost_batch = human_cost_per_unit * units_batch
        
        # 4. Velocity / Latency Impact
        human_sla = params.get("human_sla", 24.0) # hours
        ai_sla = 0.01 # hours (near instant)
        velocity_mult = human_sla / ai_sla if ai_sla > 0 else 1.0

        # 5. Generate Narrative
        savings_per_unit = human_cost_per_unit # Assuming AI unit cost is negligible compared to human
        
        narrative = (
            f"Replacing this feature saves **${human_cost_per_unit:.2f} per unit** in human labor. "
            f"At a benchmark of {throughput} units/hr, the agent performs work equivalent to "
            f"**${hourly_rate:.2f}/hr** while operating {velocity_mult:,.0f}x faster."
        )

        return {
            "feature_name": payload.feature_name,
            "financials": {
                "human_cost_per_unit": round(human_cost_per_unit, 4),
                "human_cost_per_1k_units": round(human_cost_batch, 2),
                "implied_hourly_value": hourly_rate,
                "velocity_multiplier": round(velocity_mult, 1)
            },
            "parameters_used": params,
            "strategic_analysis": narrative
        }