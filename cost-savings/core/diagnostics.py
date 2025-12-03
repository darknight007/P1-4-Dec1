from typing import List
from models.schemas import FeatureSavingsReport
from config.settings import settings

class DiagnosticsEngine:
    """
    Implements Section 7A & 6.2.
    Generates 'Strategic Analysis' and 'Pricing Power' using rule-based logic.
    """

    @staticmethod
    def calculate_pricing_power(
        total_annual_savings: float,
        feature_count: int,
        avg_velocity_mult: float,
        market_benchmark: float = 50000.0
    ) -> float:
        """
        Calculates 0-1 score based on Savings, Stickiness, and SPEED.
        """
        # 1. Savings Score (Capped at 2.0)
        savings_score = min(2.0, total_annual_savings / max(1.0, market_benchmark))
        
        # 2. Velocity Score (Speed is premium)
        # If agent is 10x faster -> Score 1.0. If 100x -> Score 1.5
        velocity_score = min(1.5, avg_velocity_mult / 10.0)
        
        # 3. Suite Depth (Stickiness)
        depth_score = min(1.5, feature_count / 5.0)
        
        # Weighted Sum
        raw_score = (
            (savings_score * 0.4) +
            (velocity_score * 0.3) +
            (depth_score * 0.3)
        )
        
        return round(min(0.99, raw_score), 2)

    @staticmethod
    def generate_strategic_analysis(
        total_annual: float, 
        reports: List[FeatureSavingsReport]
    ) -> str:
        """
        Generates the 'Sales Pitch' text without an LLM.
        """
        if not reports:
            return "No analysis available."

        # Find the 'Hero Feature' (highest savings)
        hero = max(reports, key=lambda x: x.dollar_savings)
        
        # Template selection based on Impact
        narrative = []
        narrative.append(f"This agent suite is projected to save ${total_annual:,.0f} annually.")
        
        narrative.append(
            f"The primary value driver is '{hero.feature_name}', which replaces "
            f"{hero.humans_replaced_equivalent} FTE of {hero.human_role_used} effort."
        )

        # Speed impact
        avg_speed = sum(r.velocity_multiplier for r in reports) / len(reports)
        if avg_speed > 10:
            narrative.append(
                f"Operational Velocity is increased by {avg_speed:.1f}x, "
                "unlocking real-time capabilities previously impossible for humans."
            )
        
        # Quality impact
        avg_quality = sum(r.quality_factor for r in reports) / len(reports)
        if avg_quality > 1.05:
            narrative.append(f"Quality is improved by {((avg_quality-1)*100):.1f}% over human baselines.")
        elif avg_quality < 1.0:
            narrative.append("Note: Automation error rates require human-in-the-loop review for compliance.")

        return " ".join(narrative)

    @staticmethod
    def generate_feature_narrative(hours: float, velocity: float, role: str) -> str:
        """Micro-narrative for individual features."""
        return (
            f"Saves {hours} hours/mo of {role} labor. "
            f"Processes tasks {velocity}x faster than manual workflows."
        )