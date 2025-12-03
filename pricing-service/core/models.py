"""
Pydantic Data Models - Type-Safe Schema Definitions
Defines all data structures used across pricing-service.

Fortune 500 Standards:
- Strict type validation at boundaries
- Comprehensive field documentation
- JSON schema generation for API contracts
- Backward-compatible changes only
"""

from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum


# ============================================================================
# VALUE CREDITS (New - for LLM context enrichment)
# ============================================================================

class CreditType(str, Enum):
    """Enumeration of value credit types that influence pricing recommendations."""
    ACCURACY = "accuracy"
    THROUGHPUT = "throughput"
    COVERAGE = "coverage"
    DEPTH = "depth"
    RISK_REDUCTION = "risk_reduction"
    PERSONALIZATION = "personalization"
    ENGAGEMENT = "engagement"
    OPERATIONAL_COST = "operational_cost"
    KNOWLEDGE_DISCOVERY = "knowledge_discovery"


class ValueCredit(BaseModel):
    """
    Represents a dimension of value created by the agent.
    Used to enrich LLM context for intelligent pricing recommendations.
    
    Example:
        High throughput credit → Recommend USAGE-based pricing
        High accuracy credit → Recommend OUTCOME-based pricing
    """
    credit_type: CreditType
    feature_id: str
    feature_name: str
    raw_value: float = Field(
        ...,
        description="Quantitative value (count, percentage, multiplier)"
    )
    context_tag: str = Field(
        ...,
        description="Context for value (e.g., 'leads_enriched', 'quality_multiplier')"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "credit_type": "throughput",
                "feature_id": "F1",
                "feature_name": "Lead Enrichment",
                "raw_value": 120.0,
                "context_tag": "leads_enriched"
            }
        }


# ============================================================================
# INPUT MODELS (From upstream services)
# ============================================================================

class CostProfile(BaseModel):
    """
    Technical cost breakdown from cost analyzer.
    Matches billing spec schema.
    
    This is the authoritative cost structure used by pricing recommender.
    """
    feature_id: str
    costs: Dict[str, Any] = Field(
        description="Structured cost breakdown by category (llm, compute, api_calls, storage)"
    )
    total_est_cost_per_run: float = Field(
        ge=0.0,
        description="Total estimated cost per workflow run"
    )
    last_updated: Optional[str] = Field(
        default=None,
        description="ISO8601 timestamp of cost calculation"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "feature_id": "F1",
                "costs": {
                    "llm": {
                        "model": "gpt-4o-mini",
                        "est_input_tokens": 45000000,
                        "est_output_tokens": 15000000,
                        "unit_cost_per_1k_tokens": 0.002
                    },
                    "compute": {
                        "cpu_seconds": 5400000,
                        "unit_cost_per_cpu_second": 0.0001
                    }
                },
                "total_est_cost_per_run": 0.66
            }
        }


class SavingsSummary(BaseModel):
    """
    Value payload from ROI calculation (cost-savings service).
    Required input for pricing recommendation.
    """
    feature_id: str
    benefit_units: Dict[str, float] = Field(
        description="Countable outputs (e.g., {'leads_enriched': 120})"
    )
    human_hours_saved: float = Field(
        ge=0.0,
        description="Time savings per period"
    )
    estimated_monthly_savings_usd: float = Field(
        ge=0.0,
        description="Dollar value of savings"
    )
    quality_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=5.0,
        description="Quality multiplier (agent accuracy / human accuracy)"
    )
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    
    class Config:
        json_schema_extra = {
            "example": {
                "feature_id": "F1",
                "benefit_units": {"leads_enriched": 120},
                "human_hours_saved": 60.0,
                "estimated_monthly_savings_usd": 4200.0,
                "quality_factor": 1.08
            }
        }


# ============================================================================
# PRICING CONFIG MODELS (The core artifacts)
# ============================================================================

class PricingComponent(BaseModel):
    """
    Atomic pricing element (base fee, usage charge, outcome fee, etc.).
    Building block for pricing models.
    """
    component_id: str
    component_type: Literal[
        "BASE_FEE",
        "USAGE",
        "OUTCOME",
        "SEAT",
        "BLOCK_PREPAY",
        "SHARED_SAVINGS",
        "MILESTONE",
        "DISCOUNT_RULE"
    ]
    
    # Price amounts (mutually exclusive based on type)
    amount: Optional[float] = Field(None, ge=0.0, description="Flat fee amount")
    unit_price: Optional[float] = Field(None, ge=0.0, description="Per-unit price")
    percentage: Optional[float] = Field(None, ge=0.0, le=1.0, description="For shared savings")
    
    # Billing dimensions
    billing_interval: Optional[Literal["monthly", "annual", "one_time"]] = None
    usage_dimension: Optional[str] = Field(None, description="e.g., 'workflow_run', 'tokens'")
    outcome_dimension: Optional[str] = Field(None, description="e.g., 'qualified_meeting'")
    
    # Tier pricing (optional advanced feature)
    tiers: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Volume-based pricing tiers"
    )
    
    # Metadata
    desc: Optional[str] = Field(None, description="Human-readable description")
    
    @field_validator('component_type')
    @classmethod
    def validate_component_type(cls, v):
        """Ensure component type is recognized."""
        valid_types = [
            "BASE_FEE", "USAGE", "OUTCOME", "SEAT",
            "BLOCK_PREPAY", "SHARED_SAVINGS", "MILESTONE", "DISCOUNT_RULE"
        ]
        if v not in valid_types:
            raise ValueError(f"Invalid component_type. Must be one of: {valid_types}")
        return v


class PricingModel(BaseModel):
    """
    A coherent pricing strategy (e.g., 'Hybrid: Base + Usage + Outcome').
    Contains multiple components that work together.
    """
    model_id: str
    type: Literal[
        "HYBRID",
        "SUBSCRIPTION",
        "USAGE_ONLY",
        "OUTCOME_ONLY",
        "PREPAID",
        "TIERED",
        "FREEMIUM"
    ]
    components: List[PricingComponent] = Field(
        min_length=1,
        description="List of pricing components in this model"
    )
    
    # Computed factors (editable by builder)
    margin_multiplier: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="Margin adjustment factor"
    )
    credit_factor: float = Field(
        default=1.0,
        ge=0.5,
        le=5.0,
        description="Value credit premium factor"
    )
    
    # Conditions for model applicability
    conditions: Dict[str, Any] = Field(
        default_factory=dict,
        description="e.g., {'min_seats': 10, 'requires_commitment': True}"
    )


class PricingConfig(BaseModel):
    """
    Master billing contract for a product/feature.
    This is what the Billing Agent consumes.
    
    Immutability: Once published, configs should be versioned not mutated.
    """
    pricing_config_id: str
    product_id: str
    name: str
    desc: Optional[str] = None
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    
    # Pricing models (can have multiple for experimentation)
    models: List[PricingModel] = Field(
        min_length=1,
        description="List of pricing models (e.g., Standard, Premium, Enterprise)"
    )
    
    # Global settings
    wallet_enabled: bool = Field(
        default=False,
        description="Enable prepaid wallet functionality"
    )
    prepaid_blocks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Prepaid package options"
    )
    payment_terms: Dict[str, Any] = Field(
        default_factory=dict,
        description="Billing provider, auto-renew, etc."
    )
    
    # Lifecycle metadata
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    status: Literal["draft", "active", "archived"] = "draft"
    
    class Config:
        json_schema_extra = {
            "example": {
                "pricing_config_id": "pc_sales_v1",
                "product_id": "sales_agent",
                "name": "Sales Agent - Standard Plan",
                "currency": "USD",
                "models": [
                    {
                        "model_id": "m1",
                        "type": "HYBRID",
                        "components": [
                            {
                                "component_id": "base",
                                "component_type": "BASE_FEE",
                                "amount": 29.0,
                                "billing_interval": "monthly"
                            },
                            {
                                "component_id": "usage",
                                "component_type": "USAGE",
                                "unit_price": 0.10,
                                "usage_dimension": "workflow_run"
                            }
                        ]
                    }
                ]
            }
        }


# ============================================================================
# METERING MODELS (Runtime events)
# ============================================================================

class MeteringEvent(BaseModel):
    """
    Source of truth for billing.
    Emitted by agent runtime, consumed by Billing Agent.
    """
    event_id: str
    timestamp: str
    product_id: str
    feature_id: str
    type: Literal["workflow_run", "token_usage", "outcome_event", "api_call"]
    metrics: Dict[str, float] = Field(
        description="e.g., {'workflow_runs': 1, 'input_tokens': 1200}"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Customer ID, correlation ID, etc."
    )
    proof: Optional[str] = Field(
        None,
        description="Cryptographic signature or receipt"
    )


# ============================================================================
# API REQUEST/RESPONSE MODELS
# ============================================================================

class RecommendRequest(BaseModel):
    """Request payload for /pricing/recommend endpoint."""
    savings: SavingsSummary
    costs: CostProfile
    value_credits: List[ValueCredit] = Field(
        default_factory=list,
        description="Optional value credits for enhanced recommendations"
    )
    customer_segment: str = Field(
        default="smb",
        description="Customer segment: 'smb' | 'mid_market' | 'enterprise'"
    )


class PreviewRequest(BaseModel):
    """Request payload for /pricing/preview endpoint."""
    config_id: str
    hypothetical_usage: Dict[str, float] = Field(
        description="Expected usage (e.g., {'workflow_run': 1000})"
    )
    period_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Billing period length"
    )


class PreviewResponse(BaseModel):
    """Response from invoice preview calculation."""
    preview: bool = Field(default=True, description="Indicates this is a simulation")
    config_id: str
    period_days: int
    lines: List[Dict[str, Any]] = Field(description="Line items with descriptions and amounts")
    subtotal: float
    currency: str = "USD"
    note: str = Field(
        default="This is a preview. Actual billing may vary based on real usage."
    )


# ============================================================================
# INTERNAL CALCULATION MODELS
# ============================================================================

class PricingRecommendation(BaseModel):
    """
    Internal model for LLM output with metadata.
    Wraps PricingConfig with confidence and reasoning.
    """
    config: PricingConfig
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="AI confidence in recommendation (0.0-1.0)"
    )
    reasoning: str = Field(
        description="Natural language explanation of why this pricing was chosen"
    )
    pi_score: float = Field(
        description="Calculated Pricing Index that informed this recommendation"
    )
    selected_strategy: str = Field(
        description="Strategy name used (e.g., 'aggressive_enterprise')"
    )
