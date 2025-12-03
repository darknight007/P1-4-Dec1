from typing import List, Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# 1. Input Schemas (Coming from Upstream Value Credit Engine)
# -----------------------------------------------------------------------------

class CreditType(str, Enum):
    """Enumeration of all supported Value Credit types."""
    ACCURACY = "Accuracy Credit"
    THROUGHPUT = "Throughput Credit"
    COVERAGE = "Coverage Credit"
    DEPTH = "Depth Credit"
    RISK_REDUCTION = "Risk Reduction Credit"
    PERSONALIZATION = "Personalization Credit"
    ENGAGEMENT = "Engagement Credit"
    OPERATIONAL_COST = "Operational Cost Savings Credit"
    KNOWLEDGE_DISCOVERY = "Knowledge Discovery Credit"

class ValueCredit(BaseModel):
    """Represents a raw value credit detected in the code analysis phase."""
    credit_type: CreditType
    feature_id: str
    feature_name: str
    raw_value: float = Field(..., description="The quantitative value extracted from code analysis (Count, Time, or %)")
    context_tag: str = Field(..., description="The context: 'files', 'leads', 'api_calls', etc.")

# -----------------------------------------------------------------------------
# 2. Human Benchmark Schemas (The Knowledge Base)
# -----------------------------------------------------------------------------

class HumanRole(BaseModel):
    """
    Represents the human profile being replaced or augmented.
    Includes Cost, Throughput, Accuracy, and SLA (Velocity) metrics.
    """
    role_name: str = Field(..., description="E.g., SDR, Analyst, Content Writer")
    
    # Cost Structure
    hourly_rate_usd: float = Field(..., gt=0, description="Fully loaded hourly cost in USD")
    annual_salary_usd: Optional[float] = Field(None, description="Optional annual salary for reference")
    
    # Productivity (Volume)
    throughput_per_hour: float = Field(..., gt=0, description="How many units a human processes per hour")
    unit_of_measure: str = Field(..., description="The unit for throughput: 'leads', 'files', 'reports'")
    
    # Velocity (Speed/SLA) - Critical for "Time-to-Delivery" metrics
    avg_turnaround_time_hours: float = Field(
        ..., 
        gt=0, 
        description="Avg time to complete one batch/task end-to-end (including wait time)."
    )
    
    # Quality & Accuracy
    average_accuracy_rate: float = Field(..., ge=0.0, le=1.0, description="Human accuracy (0.0 to 1.0)")
    error_tolerance_rate: float = Field(0.05, ge=0.0, le=1.0, description="Acceptable error rate")

    class Config:
        json_schema_extra = {
            "example": {
                "role_name": "SDR",
                "hourly_rate_usd": 35.0,
                "throughput_per_hour": 20.0,
                "unit_of_measure": "leads",
                "avg_turnaround_time_hours": 24.0, 
                "average_accuracy_rate": 0.88
            }
        }

# -----------------------------------------------------------------------------
# 3. Calculation & Logic Schemas (Internal Processing)
# -----------------------------------------------------------------------------

class BenefitUnitResult(BaseModel):
    """Output of the ValueCredit -> BenefitUnit Translator"""
    feature_id: str
    benefit_units: Dict[str, float] = Field(..., description="Key is unit name, Value is count.")

class FeatureSavingsReport(BaseModel):
    """
    Detailed savings calculation for a single feature.
    Includes Traceability, Financials, and Diagnostics.
    """
    feature_id: str
    feature_name: str
    
    # Benefit Traceability
    benefits: Dict[str, float]
    
    # Human Baseline Used
    human_role_used: str
    human_rate_per_hour: float
    human_throughput_per_hour: float
    
    # Calculated Metrics
    hours_saved: float
    quality_factor: float = Field(..., description="Multiplier based on Agent vs Human accuracy")
    
    # Velocity Metric
    velocity_multiplier: float = Field(..., description="How much faster is the agent? (e.g. 10x)")
    
    dollar_savings: float
    humans_replaced_equivalent: float
    
    # Micro-Narrative
    impact_narrative: str = Field(..., description="Generated sentence explaining the specific value.")

# -----------------------------------------------------------------------------
# 4. Final Output Schemas (Reporting)
# -----------------------------------------------------------------------------

class SavingsSummary(BaseModel):
    """
    The Master JSON output fed into the Pricing Engine.
    """
    feature_level_savings: List[FeatureSavingsReport]
    
    # Aggregated Financials
    total_monthly_savings_usd: float
    total_annual_savings_usd: float
    
    # Strategic Metrics
    pricing_power_score: float = Field(..., ge=0.0, le=1.0, description="0 to 1 score indicating pricing strength")
    recommended_pricing_dimensions: List[str]
    
    # Text Analysis
    strategic_analysis: str = Field(..., description="Generated paragraph explaining the business value.")

# -----------------------------------------------------------------------------
# 5. Interaction Schemas (For the Data Collection Agent)
# -----------------------------------------------------------------------------

class BenchmarkRequest(BaseModel):
    """Used when the agent needs to ask the user for missing data."""
    missing_role: str
    missing_fields: List[str]
    context_message: str