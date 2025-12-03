# cost-savings/models/context_models.py

from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# 1. INPUT: The "Fixed" AI Cost Data (From System A)
# -----------------------------------------------------------------------------

class ImportedCostItem(BaseModel):
    id: str = Field(..., description="Unique identifier (e.g. 'infra_1') for linking to Features")
    category: str
    name: str
    estimated_volume: float = 0.0
    metric: str = "units"
    monthly_cost: float = 0.0

class ImportedLLMCall(BaseModel):
    id: str = Field(..., description="Unique identifier (e.g. 'llm_1') for linking to Features")
    model: str
    entry_point: str
    cost_driver_chain: List[str] = Field(default_factory=list)
    # The AI Cost is already calculated in System A, so we just need context
    estimated_calls_per_unit: int = 1

class Feature(BaseModel):
    """
    A Business Logic Unit that aggregates multiple cost drivers.
    Example: "Candidate Analysis" -> [LLM(gpt-4), DB(Vectors), Storage(S3)]
    """
    id: str = Field(..., description="Unique ID for this feature (e.g. 'feat_search')")
    name: str = Field(..., description="Business feature name (e.g., 'Smart Search', 'User Signup')")
    description: str = Field("", description="Explanation of value provided to the user")
    cost_driver_ids: List[str] = Field(default_factory=list, description="List of ImportedCostItem.id or ImportedLLMCall.id that power this feature")


class CostReportContext(BaseModel):
    """
    Represents the full context ingested from the Cost Analyzer (System A).
    The Savings Agent uses this to understand the PROJECT CONTEXT, not to recalculate AI costs.
    """
    repo: str = "Unknown"
    timestamp: str = "Unknown"
    estimates: Dict[str, Any] = Field(default_factory=dict)
    
    # We use these lists to understand "What is the AI doing?" 
    # so we can infer "What human is it replacing?"
    llm_calls: List[ImportedLLMCall] = Field(default_factory=list)
    infrastructure: List[ImportedCostItem] = Field(default_factory=list)
    integrations: List[ImportedCostItem] = Field(default_factory=list)
    data_components: List[ImportedCostItem] = Field(default_factory=list)

    # New: Mapped Features
    features: List[Feature] = Field(default_factory=list, description="AI-inferred business features mapped to cost drivers")

    def get_project_summary(self) -> str:
        """
        Generates a semantic summary of the AI's capabilities.
        Used by the LLM/Regex engine to guess the Human Equivalent Role.
        """
        infra_names = [i.name for i in self.infrastructure]
        saas_names = [i.name for i in self.integrations]
        # Unique models used (e.g. "gpt-4", "claude-3")
        models = list(set([c.model for c in self.llm_calls]))
        
        return (
            f"Project Repo: {self.repo}. "
            f"Infra Stack: {', '.join(infra_names)}. "
            f"Integrations: {', '.join(saas_names)}. "
            f"AI Logic Providers: {', '.join(models)}."
        )

# -----------------------------------------------------------------------------
# 2. OUTPUT: The "Variable" Human Benchmark Data (For UI)
# -----------------------------------------------------------------------------

class CostParameter(BaseModel):
    """
    A single configurable dimension for the HUMAN BASELINE.
    Example: 'Human Hourly Rate', 'Manual Review Time', 'Error Correction Cost'.
    """
    id: str = Field(..., description="Unique key for calculation (e.g., 'human_hourly_rate')")
    label: str = Field(..., description="Display name (e.g., 'Human Hourly Cost')")
    
    # UI Rendering Hints
    data_type: Literal["currency", "percent", "number", "text"] = "number"
    unit: str = Field("", description="Suffix symbol like '$', '%', 'hrs', 'mins'")
    
    # Smart Defaults
    default_value: Any = Field(0.0, description="Pre-filled value inferred from context")
    
    # Provenance (Debugging/Explanation)
    # 'db_global' is explicitly allowed here
    source: Literal["db_global", "db_regex", "llm_inference", "report_context"] = "db_regex"
    reasoning: str = Field("", description="Why was this human parameter suggested?")

class FeatureConfigSchema(BaseModel):
    """
    The complete configuration package for a SINGLE selected feature.
    Contains the specific list of Human Parameters relevant to replacing that feature.
    """
    feature_id: str
    feature_name: str
    
    # The Dropdown List: Contains ALL possible human parameters for this context
    available_parameters: List[CostParameter] = Field(
        default_factory=list, 
        description="The full list of valid human parameters relevant to this workflow"
    )
    
    # The Initial UI State: Which parameters are visible immediately?
    recommended_parameters: List[str] = Field(
        default_factory=list,
        description="List of parameter IDs that should be visible by default (e.g. Rate, Throughput)"
    )