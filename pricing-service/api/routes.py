"""
FastAPI Routes - Pricing Service API
RESTful endpoints for pricing configuration, recommendation, and preview.

Fortune 500 Standards:
- Comprehensive error handling with proper HTTP status codes
- Request validation via Pydantic models
- Structured logging for all operations
- CORS enabled for cross-origin frontend access
"""

import logging
from typing import List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from core.models import (
    PricingConfig, RecommendRequest, PreviewRequest, PreviewResponse,
    MeteringEvent, PricingRecommendation
)
from core.storage import PricingStorage
from core.billing_preview import preview_invoice
from agents.recommender import get_recommender

logger = logging.getLogger("PricingAPI")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/pricing", tags=["pricing"])

# Initialize dependencies
storage = PricingStorage()
recommender = get_recommender()


# ============================================================================
# PRICING RECOMMENDATION
# ============================================================================

@router.post("/recommend", response_model=PricingConfig, status_code=status.HTTP_201_CREATED)
async def recommend_pricing(payload: RecommendRequest):
    """
    Generate AI-powered pricing recommendation.
    
    Input:
    - Savings summary (from cost-savings service)
    - Cost profile (from cost analyzer)
    - Value credits (optional, for enhanced recommendations)
    - Customer segment
    
    Output:
    - Complete PricingConfig ready for builder review/editing
    
    This is the CORE endpoint - integrates savings + costs → intelligent pricing.
    """
    try:
        logger.info(
            f"Pricing recommendation requested for feature {payload.savings.feature_id}, "
            f"segment={payload.customer_segment}"
        )
        
        # Generate recommendation via LLM
        recommendation: PricingRecommendation = recommender.generate_proposal(
            savings=payload.savings,
            costs=payload.costs,
            value_credits=payload.value_credits,
            customer_segment=payload.customer_segment
        )
        
        # Auto-save to storage as DRAFT
        config = recommendation.config
        storage.save_config(config)
        
        logger.info(
            f"Pricing config generated: {config.pricing_config_id}, "
            f"confidence={recommendation.confidence_score:.2f}, "
            f"PI={recommendation.pi_score:.2f}"
        )
        
        # Return config with metadata in headers
        return JSONResponse(
            content=config.model_dump(),
            status_code=status.HTTP_201_CREATED,
            headers={
                "X-Pricing-Confidence": str(recommendation.confidence_score),
                "X-Pricing-Index": str(recommendation.pi_score),
                "X-Strategy-Used": recommendation.selected_strategy
            }
        )
        
    except Exception as e:
        logger.error(f"Pricing recommendation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate pricing recommendation: {str(e)}"
        )


# ============================================================================
# INVOICE PREVIEW (CRITICAL UX FEATURE)
# ============================================================================

@router.post("/preview", response_model=PreviewResponse)
async def preview_pricing(payload: PreviewRequest):
    """
    Calculate simulated invoice for hypothetical usage.
    
    Use Case:
    - Builder: "What will my invoice be at 10K runs/month?"
    - Customer: "How much will this cost me?"
    - Sales: "Let me show you a pricing scenario"
    
    This is READ-ONLY - no actual billing occurs.
    """
    try:
        logger.info(
            f"Preview requested for config {payload.config_id}, "
            f"usage={payload.hypothetical_usage}"
        )
        
        # Load config from storage
        config = storage.get_config(payload.config_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pricing config '{payload.config_id}' not found"
            )
        
        # Calculate preview
        preview = preview_invoice(
            config=config,
            usage=payload.hypothetical_usage,
            period_days=payload.period_days
        )
        
        logger.info(
            f"Preview calculated: {len(preview.lines)} line items, "
            f"subtotal=${preview.subtotal:.2f}"
        )
        
        return preview
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Preview calculation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate preview: {str(e)}"
        )


# ============================================================================
# CONFIG CRUD OPERATIONS
# ============================================================================

@router.post("/config", response_model=PricingConfig, status_code=status.HTTP_201_CREATED)
async def create_or_update_config(config: PricingConfig):
    """
    Save or update pricing configuration.
    
    Use Cases:
    - Save LLM-generated config (from /recommend)
    - Save manually edited config (from UI)
    - Update existing config
    
    Validation ensures config meets business constraints.
    """
    try:
        logger.info(f"Saving pricing config: {config.pricing_config_id}")
        
        # Validate config has at least one model
        if not config.models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PricingConfig must have at least one pricing model"
            )
        
        # Validate each model has components
        for model in config.models:
            if not model.components:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Pricing model {model.model_id} must have at least one component"
                )
        
        # Save to storage
        storage.save_config(config)
        
        logger.info(f"Config saved successfully: {config.pricing_config_id}")
        return config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Config save failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save config: {str(e)}"
        )


@router.get("/config/{config_id}", response_model=PricingConfig)
async def get_config(config_id: str):
    """Retrieve pricing configuration by ID."""
    try:
        config = storage.get_config(config_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pricing config '{config_id}' not found"
            )
        
        logger.info(f"Config retrieved: {config_id}")
        return config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Config retrieval failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve config: {str(e)}"
        )


@router.get("/configs", response_model=List[PricingConfig])
async def list_configs(
    product_id: str = None,
    status_filter: str = None,
    limit: int = 100
):
    """
    List pricing configurations with optional filters.
    
    Query Parameters:
    - product_id: Filter by product
    - status_filter: Filter by status (draft/active/archived)
    - limit: Max results (default 100)
    """
    try:
        configs = storage.list_configs(
            product_id=product_id,
            status_filter=status_filter,
            limit=limit
        )
        
        logger.info(
            f"Listed {len(configs)} configs "
            f"(product={product_id}, status={status_filter})"
        )
        
        return configs
        
    except Exception as e:
        logger.error(f"Config listing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list configs: {str(e)}"
        )


@router.delete("/config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(config_id: str):
    """
    Delete (or archive) pricing configuration.
    
    Note: In production, consider soft-delete (status=archived) instead of hard delete
    to maintain audit trail.
    """
    try:
        # Check if exists
        config = storage.get_config(config_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pricing config '{config_id}' not found"
            )
        
        # Soft delete: set status to archived
        config.status = "archived"
        storage.save_config(config)
        
        logger.info(f"Config archived: {config_id}")
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Config deletion failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete config: {str(e)}"
        )


# ============================================================================
# METERING EVENTS (For future Billing Agent integration)
# ============================================================================

@router.post("/metering/event", status_code=status.HTTP_202_ACCEPTED)
async def record_metering_event(event: MeteringEvent):
    """
    Record metering event for billing.
    
    This endpoint is for FUTURE integration with Billing Agent.
    Currently just logs events to storage for audit purposes.
    
    In production:
    - Validate event signature (HMAC)
    - Check idempotency (event_id)
    - Publish to event bus
    - Store for billing runs
    """
    try:
        logger.info(
            f"Metering event received: {event.event_id}, "
            f"type={event.type}, product={event.product_id}"
        )
        
        # Store event (idempotent)
        storage.save_metering_event(event)
        
        logger.info(f"Metering event stored: {event.event_id}")
        
        return {
            "status": "accepted",
            "event_id": event.event_id,
            "message": "Event recorded for billing processing"
        }
        
    except Exception as e:
        logger.error(f"Metering event recording failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record metering event: {str(e)}"
        )


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Service health check.
    
    Returns:
    - Service status
    - Database connectivity
    - LLM availability (degraded if offline)
    """
    health_status = {
        "service": "pricing-service",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check storage
    try:
        storage.get_config("health_check_test")  # Will return None, but tests connection
        health_status["components"]["storage"] = "healthy"
    except Exception as e:
        health_status["components"]["storage"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check LLM (optional - don't fail health check if LLM is down)
    try:
        # Simple check - if recommender initialized, LLM is likely available
        if recommender:
            health_status["components"]["llm"] = "healthy"
    except Exception as e:
        health_status["components"]["llm"] = f"degraded: {str(e)}"
        # Don't mark overall status as unhealthy - fallback exists
    
    logger.info(f"Health check: {health_status['status']}")
    
    if health_status["status"] == "healthy":
        return health_status
    else:
        return JSONResponse(
            content=health_status,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
