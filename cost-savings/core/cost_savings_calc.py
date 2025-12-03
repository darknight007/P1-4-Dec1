from typing import List, Dict
from config.settings import settings

class CostSavingsCalculator:
    """
    Implements Section 3.3 (Financials) & Velocity Math.
    Acts as the 'Physics Engine' for Time and Money.
    """

    @staticmethod
    def calculate_dollar_savings(
        hours_saved: float,
        hourly_rate: float,
        quality_factor: float
    ) -> float:
        """
        Formula: Savings = Human_Hours_Saved * Human_Hourly_Rate * Quality_Factor
        """
        if hours_saved < 0 or hourly_rate < 0:
            return 0.0
            
        raw_savings = hours_saved * hourly_rate
        adjusted_savings = raw_savings * quality_factor
        return round(adjusted_savings, 2)

    @staticmethod
    def calculate_velocity_multiplier(
        human_turnaround_hours: float,
        agent_processing_seconds_per_unit: float = 2.0 
    ) -> float:
        """
        Calculates how many times faster the agent is compared to the human SLA.
        
        Args:
            human_turnaround_hours: The SLA (e.g., 24 hours to return a file).
            agent_processing_seconds_per_unit: Est. time for AI to process (default 2s).
            
        Returns:
            float: Multiplier (e.g., 43200.0x faster).
        """
        # Safety check for bad inputs
        if human_turnaround_hours <= 0:
            return 1.0 # No speedup if human is instant (impossible)
            
        # Convert human hours to seconds for apples-to-apples comparison
        human_seconds = human_turnaround_hours * 3600
        
        # Ensure we don't divide by zero if agent time is 0
        agent_seconds = max(0.1, agent_processing_seconds_per_unit)
        
        multiplier = human_seconds / agent_seconds
        
        # Cap the multiplier at a reasonable number for reporting (e.g., 10,000x)
        # to avoid scientific notation in JSON
        return round(min(multiplier, 10000.0), 1)

    @staticmethod
    def generate_pricing_dimensions(benefit_units: Dict[str, float]) -> List[str]:
        """
        Implements Section 6.1: Pricing Dimensions Inference.
        Looks at what work was done (units) and suggests how to charge for it.
        """
        dimensions = []
        
        # Map specific units to pricing language
        for unit_name, count in benefit_units.items():
            if count > 0:
                # e.g. "leads_enriched" -> "Per leads enriched"
                clean_name = unit_name.replace("_", " ")
                dimensions.append(f"Per {clean_name} ($/unit)")
        
        # Add generic dimensions that always apply
        dimensions.append("Flat Platform Fee (Tiered)")
        dimensions.append("ROI-based Success Fee (% of savings)")
        
        return list(set(dimensions)) # Remove duplicates