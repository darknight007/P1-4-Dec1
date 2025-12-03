# cost-savings/api/routes.py

from fastapi import APIRouter, HTTPException, status, BackgroundTasks
from typing import Dict, Any, List
from pydantic import BaseModel

# Models
from models.context_models import (
    CostReportContext, 
    FeatureConfigSchema, 
    CostParameter
)
# Services
from services.parameter_discovery import ParameterDiscoveryEngine
from services.interactive_service import InteractiveSavingsCalculator

router = APIRouter(prefix="/savings", tags=["Savings Agent"])
discovery_engine = ParameterDiscoveryEngine()
interactive_calc = InteractiveSavingsCalculator()

# -----------------------------------------------------------------------------
# Request Models
# -----------------------------------------------------------------------------

class DiscoveryRequest(BaseModel):
    """
    Payload sent when User selects a feature in the UI.
    Contains the full context (Report) + the specific feature ID.
    """
    context: CostReportContext
    target_feature_id: str # Changed from target_feature_name

class InteractiveCalculationRequest(BaseModel):
    """
    Payload sent when User clicks 'Calculate'.
    Contains the values for the parameters the User agreed upon.
    """
    feature_name: str
    selected_parameters: Dict[str, float]  # e.g. {"human_hourly_rate": 50.0}
    ai_estimated_cost: float = 0.0         # From System A

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/discovery/schema",
    response_model=FeatureConfigSchema,
    status_code=status.HTTP_200_OK
)
async def discover_parameters(payload: DiscoveryRequest):
    """
    The Brain Endpoint.
    Generates a Dynamic Schema of Human Benchmarks using Hybrid Logic (DB + LLM).
    """
    try:
        schema = discovery_engine.generate_schema(
            context=payload.context,
            target_feature_id=payload.target_feature_id # Changed from target_feature_name
        )
        return schema
    except Exception as e:
        print(f"Discovery Error: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Discovery Engine Failed: {str(e)}"
        )

@router.post(
    "/calculate_interactive",
    status_code=status.HTTP_200_OK
)
async def calculate_interactive(
    payload: InteractiveCalculationRequest,
    background_tasks: BackgroundTasks
):
    """
    The Math Endpoint + Learning Trigger.
    1. Computes Savings/ROI.
    2. Triggers a Background Task to 'Learn' these parameters for future suggestions.
    """
    try:
        # 1. Perform Calculation
        result = interactive_calc.compute(payload)
        
        # 2. Trigger Learning (Fire and Forget)
        # We use BackgroundTasks so we don't slow down the UI response
        background_tasks.add_task(
            discovery_engine.learn_new_parameters,
            feature_name=payload.feature_name,
            used_parameters=payload.selected_parameters
        )
        
        return result
    except Exception as e:
        print(f"Calculation Error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Calculation Failed: {str(e)}"
        )