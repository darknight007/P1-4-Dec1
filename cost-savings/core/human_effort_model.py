from typing import Dict, Any
from models.schemas import BenefitUnitResult, HumanRole

class HumanEffortModel:
    """
    Implements Section 3.2: Human Effort Replacement Model.
    Calculates time saved based on human throughput benchmarks.
    
    Formula: Human Hours Saved = Benefit Unit Count / Human Output Rate per hour
    """

    @staticmethod
    def calculate_hours_saved(
        benefit_data: BenefitUnitResult, 
        human_benchmark: HumanRole
    ) -> Dict[str, Any]:
        """
        Computes the hours saved for a specific feature against a specific human role.
        Includes 'Smart Matching' to handle vocabulary mismatches.
        """
        
        units = benefit_data.benefit_units
        benchmark_unit = human_benchmark.unit_of_measure.lower()
        
        # 1. Identify the relevant unit to calculate against
        target_volume = 0.0
        matched_key = None

        # Strategy A: Exact Match
        if benchmark_unit in units:
            target_volume = units[benchmark_unit]
            matched_key = benchmark_unit
            
        # Strategy B: Substring/Fuzzy Match (e.g. 'files' matches 'files_analyzed')
        if matched_key is None:
            for key, value in units.items():
                if benchmark_unit in key or key in benchmark_unit:
                    target_volume = value
                    matched_key = key
                    break
        
        # Strategy C: Single Unit Fallback (The "Assume Intent" Fix)
        # If the feature produced exactly ONE type of work, and we have benchmarks,
        # assume they are related even if the names don't match (e.g. "invoices" vs "docs").
        if matched_key is None:
            valid_keys = [k for k in units.keys() if units[k] > 0]
            if len(valid_keys) == 1:
                matched_key = valid_keys[0]
                target_volume = units[matched_key]
        
        # If still no match or 0 volume, we cannot calculate savings
        if matched_key is None or target_volume == 0:
            return {
                "hours_saved": 0.0,
                "note": f"Could not match benchmark '{benchmark_unit}' to benefits {list(units.keys())}"
            }

        # 2. Apply Formula: Hours = Volume / Throughput
        if human_benchmark.throughput_per_hour <= 0:
            # Avoid DivisionByZero
            return {
                "hours_saved": 0.0,
                "note": "Human throughput is zero or invalid."
            }

        hours_saved = target_volume / human_benchmark.throughput_per_hour

        return {
            "hours_saved": round(hours_saved, 2),
            "matched_unit": matched_key,
            "unit_volume": target_volume,
            "human_throughput": human_benchmark.throughput_per_hour,
            "role_used": human_benchmark.role_name
        }

    @staticmethod
    def calculate_fte_equivalent(hours_saved_monthly: float) -> float:
        """
        Helper to convert monthly hours saved into Full-Time Employee (FTE) equivalents.
        Assumes ~168 hours per work month (21 days * 8 hours).
        """
        standard_work_month_hours = 168.0 
        return round(hours_saved_monthly / standard_work_month_hours, 2)