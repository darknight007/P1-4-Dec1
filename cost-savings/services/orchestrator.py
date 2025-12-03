from typing import List, Union, Dict
from models.schemas import (
    ValueCredit, 
    SavingsSummary, 
    BenchmarkRequest, 
    FeatureSavingsReport
)
# Core Logic Imports
from core.benefit_units_translator import BenefitUnitsTranslator
from core.human_effort_model import HumanEffortModel
from core.quality_adjustment import QualityAdjustmentEngine
from core.cost_savings_calc import CostSavingsCalculator
from core.role_inference import RoleInferenceEngine
from core.diagnostics import DiagnosticsEngine

# Agent Imports
from agents.collector_bot import BenchmarkCollectorBot
from config.settings import settings

class SavingsOrchestrator:
    """
    Implements Section 7C: Savings Orchestrator.
    Coordinator that pulls strings between:
    - Code Analysis (Value Credits)
    - Knowledge Base (Collector Bot)
    - Math Engines (Cost, Quality, Velocity)
    - Strategy Engines (Diagnostics)
    """

    def __init__(self):
        self.collector = BenchmarkCollectorBot()

    def process_savings_calculation(
        self, 
        feature_id: str, 
        feature_name: str, 
        credits: List[ValueCredit]
    ) -> Union[FeatureSavingsReport, BenchmarkRequest]:
        """
        Main Pipeline for a SINGLE feature.
        Returns either the Report (Success) or a Request for Data (Pause).
        """
        
        # -----------------------------------------------------------
        # Step 1: Translate Credits to Benefit Units
        # -----------------------------------------------------------
        # e.g., "Throughput Credit (200)" -> {"leads_enriched": 200}
        benefit_result = BenefitUnitsTranslator.translate(feature_id, credits)
        
        # -----------------------------------------------------------
        # Step 2: Determine Target Human Role (Smart Inference)
        # -----------------------------------------------------------
        # We extract all tags to give the inference engine the full context
        all_context_tags = [c.context_tag for c in credits]
        
        # Uses weighted keywords to guess "SDR" from "leads", "outreach", etc.
        target_role_name = RoleInferenceEngine.infer_role(all_context_tags)
            
        # -----------------------------------------------------------
        # Step 3: Check Data Availability (The "Stop & Ask" Phase)
        # -----------------------------------------------------------
        human_benchmark, gap_request = self.collector.analyze_gap(target_role_name)
        
        if gap_request:
            return gap_request  # HALT: Return question to user
            
        # -----------------------------------------------------------
        # Step 4: Run The Physics (Math Engines)
        # -----------------------------------------------------------
        
        # 4a. Time Savings (Volume / Throughput)
        effort_data = HumanEffortModel.calculate_hours_saved(benefit_result, human_benchmark)
        hours_saved = effort_data.get("hours_saved", 0.0)
        
        # 4b. Quality Adjustment
        agent_accuracy = self._extract_accuracy_from_credits(credits)
        quality_factor = QualityAdjustmentEngine.calculate_quality_factor(
            agent_accuracy=agent_accuracy,
            human_accuracy=human_benchmark.average_accuracy_rate
        )
        
        # 4c. Velocity Calculation (Speed / SLA) -- NEW
        velocity_mult = CostSavingsCalculator.calculate_velocity_multiplier(
            human_turnaround_hours=human_benchmark.avg_turnaround_time_hours
        )
        
        # 4d. Financials
        dollar_savings = CostSavingsCalculator.calculate_dollar_savings(
            hours_saved=hours_saved,
            hourly_rate=human_benchmark.hourly_rate_usd,
            quality_factor=quality_factor
        )
        
        # 4e. Micro-Diagnostic (Generate Narrative for this feature) -- NEW
        narrative = DiagnosticsEngine.generate_feature_narrative(
            hours=hours_saved,
            velocity=velocity_mult,
            role=human_benchmark.role_name
        )
        
        # -----------------------------------------------------------
        # Step 5: Construct Report
        # -----------------------------------------------------------
        return FeatureSavingsReport(
            feature_id=feature_id,
            feature_name=feature_name,
            benefits=benefit_result.benefit_units,
            human_role_used=human_benchmark.role_name,
            human_rate_per_hour=human_benchmark.hourly_rate_usd,
            human_throughput_per_hour=human_benchmark.throughput_per_hour,
            hours_saved=hours_saved,
            quality_factor=quality_factor,
            velocity_multiplier=velocity_mult, # Included in output
            dollar_savings=dollar_savings,
            humans_replaced_equivalent=HumanEffortModel.calculate_fte_equivalent(hours_saved),
            impact_narrative=narrative # Included in output
        )

    def generate_summary(self, reports: List[FeatureSavingsReport]) -> SavingsSummary:
        """
        Aggregates multiple feature reports into the Master JSON (Section 4).
        """
        total_monthly = sum(r.dollar_savings for r in reports)
        total_annual = total_monthly * settings.WORK_MONTHS_PER_YEAR
        
        # Collect all unique benefit keys for pricing dimensions
        all_benefits = {}
        avg_velocity = 0.0
        
        if reports:
            # Average the velocity across features to get a suite-level speed metric
            avg_velocity = sum(r.velocity_multiplier for r in reports) / len(reports)
            
            for r in reports:
                all_benefits.update(r.benefits)
            
        # Calculate Strategic Metrics via Diagnostics Engine
        pricing_score = DiagnosticsEngine.calculate_pricing_power(
            total_annual_savings=total_annual,
            feature_count=len(reports),
            avg_velocity_mult=avg_velocity
        )
        
        # Generate the High-Level Sales Pitch
        strategy_text = DiagnosticsEngine.generate_strategic_analysis(
            total_annual=total_annual,
            reports=reports
        )
        
        dims = CostSavingsCalculator.generate_pricing_dimensions(all_benefits)
        
        return SavingsSummary(
            feature_level_savings=reports,
            total_monthly_savings_usd=round(total_monthly, 2),
            total_annual_savings_usd=round(total_annual, 2),
            pricing_power_score=pricing_score,
            recommended_pricing_dimensions=dims,
            strategic_analysis=strategy_text
        )

    def _extract_accuracy_from_credits(self, credits: List[ValueCredit]) -> float:
        """Looks for 'Accuracy Credit' in the input list."""
        for c in credits:
            if "Accuracy" in c.credit_type.value:
                val = c.raw_value
                # Value credits often store 95% as 95.0 or 0.95. We normalize to 0.0-1.0
                return val / 100.0 if val > 1.0 else val
        return 0.95 # Default assumption if no accuracy credit found