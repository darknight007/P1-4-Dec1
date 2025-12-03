# schemas/output_models.py

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

# --- GENERIC COST COMPONENT ---

class CostItem(BaseModel):
    """
    Generic representation for non-LLM cost drivers.
    Used for: Infrastructure, SaaS, CI/CD, Vector DBs, Storage, etc.
    """
    id: str = Field(..., description="Unique identifier (e.g. 'infra_1') for linking to Features")
    category: Literal[
        "compute",
        "storage",
        "saas",
        "cicd",
        "vector_db",
        "scraping",
        "human",
        "other"
    ] = Field(..., description="The broad cost category")

    name: str = Field(..., description="Name of the resource (e.g., 'AWS RDS', 'Stripe', 'GitHub Actions')")
    location: str = Field("Unknown", description="File/Line evidence where this is defined or used")
    description: str = Field("", description="Brief context about how it is used")

    # Cost Factors
    metric: str = Field("units", description="Billing metric (e.g., 'hours', 'GB-month', 'API calls', 'users')")
    
    # CRITICAL FIX: Added user_rate so the reporter can store the $0.07 extracted from chat
    user_rate: float = Field(0.0, description="Specific price per unit provided by the user (overrides standard defaults)")
    
    estimated_volume: float = Field(0.0, description="Estimated monthly volume based on code/user input")
    monthly_cost: float = Field(0.0, description="Estimated monthly cost in USD")

# --- LLM SPECIFIC COMPONENTS ---

class TokenDriver(BaseModel):
    """Component that contributes tokens to a prompt"""
    component: str = Field(..., description="Name of component (e.g., 'System Prompt', 'Chat History')")
    location: str = Field("Unknown", description="File:line where this is added")
    estimated_tokens: int = Field(0, description="Estimated token contribution")
    is_dynamic: bool = Field(False, description="Whether token count varies per request")

class LLMCall(BaseModel):
    """Detailed LLM Cost Driver"""
    id: str = Field(..., description="Unique identifier (e.g. 'llm_1') for linking to Features")
    model: str = Field("Unknown", description="The specific model used (e.g., gpt-4)")
    entry_point: str = Field("Unknown", description="Where the flow starts (e.g., route handler)")

    cost_driver_chain: List[str] = Field(
        default_factory=list,
        description="Step-by-step flow from entry to API call"
    )

    prompt_builder_location: str = Field("Unknown", description="Where the prompt is constructed")
    token_drivers: List[TokenDriver] = Field(default_factory=list, description="Breakdown of token sources")
    api_call_location: str = Field("Unknown", description="Exact file:line of API execution")

    # Usage Stats
    base_tokens: int = Field(0, description="Static + Min Dynamic tokens")
    max_tokens: int = Field(0, description="Max output tokens limit")
    estimated_calls_per_unit: int = Field(1, description="Calls made per single unit of work (request/lead)")
    notes: Optional[str] = Field(None, description="Analysis notes")

# --- FEATURE MAPPING ---

class Feature(BaseModel):
    """
    A Business Logic Unit that aggregates multiple cost drivers.
    Example: "Candidate Analysis" -> [LLM(gpt-4), DB(Vectors), Storage(S3)]
    """
    id: str = Field(..., description="Unique ID for this feature (e.g. 'feat_search')")
    name: str = Field(..., description="Business feature name (e.g., 'Smart Search', 'User Signup')")
    description: str = Field("", description="Explanation of value provided to the user")
    cost_driver_ids: List[str] = Field(default_factory=list, description="List of CostItem.id or LLMCall.id that power this feature")

# --- AGGREGATES ---

class Estimates(BaseModel):
    """Financial Summary"""
    monthly_cost_usd: float = Field(0.0, description="Total Estimated Monthly Cost")
    monthly_token_estimate: int = Field(0, description="Total Monthly LLM Tokens")

    # Category Breakdowns
    compute_cost: float = Field(0.0)
    llm_cost: float = Field(0.0)
    saas_cost: float = Field(0.0)
    storage_cost: float = Field(0.0)
    other_cost: float = Field(0.0)

class CostElements(BaseModel):
    """Root Report Object"""
    repo: str = Field("Unknown")
    timestamp: str = Field("Unknown")

    # The 8 Categories Map
    llm_calls: List[LLMCall] = Field(default_factory=list)

    # Grouping the other 7 drivers
    infrastructure: List[CostItem] = Field(default_factory=list, description="Compute, Storage, CI/CD")
    integrations: List[CostItem] = Field(default_factory=list, description="SaaS, Human-in-the-Loop")
    data_components: List[CostItem] = Field(default_factory=list, description="VectorDB, Scraping/3rd Party Compute")
    
    # Mapping
    features: List[Feature] = Field(default_factory=list, description="Mapped Business Features")

    estimates: Estimates = Field(default_factory=Estimates)