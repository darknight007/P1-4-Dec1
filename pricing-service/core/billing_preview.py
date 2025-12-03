"""
Billing Preview Calculator - Invoice Simulation Engine
Calculates hypothetical invoices WITHOUT touching actual billing systems.

Fortune 500 Standards:
- Read-only operations (no DB writes, no charges)
- Accurate simulation matching billing agent logic
- Clear disclaimers (preview != actual bill)
- Performance-optimized (no external API calls)
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.models import PricingConfig, PricingComponent, PreviewRequest, PreviewResponse

logger = logging.getLogger("BillingPreview")
logger.setLevel(logging.INFO)


class PreviewCalculationError(Exception):
    """Raised when preview calculation fails validation."""
    pass


class BillingPreviewCalculator:
    """
    Simulates invoice calculations for user validation.
    
    Use Cases:
    - Builder wants to see "What will my invoice be at 10K runs/month?"
    - Customer evaluating pricing before commitment
    - Sales team demonstrating pricing scenarios
    
    NOT Used For:
    - Actual billing (that's the Billing Agent's job)
    - Metering event processing
    - Payment capture
    """
    
    @staticmethod
    def calculate_preview(
        config: PricingConfig,
        hypothetical_usage: Dict[str, float],
        period_days: int = 30
    ) -> PreviewResponse:
        """
        Calculate simulated invoice for given usage scenario.
        
        Args:
            config: Pricing configuration to simulate
            hypothetical_usage: Dict of dimension → quantity
                Example: {"workflow_run": 1000, "qualified_meeting": 10}
            period_days: Billing period length (default 30 for monthly)
            
        Returns:
            PreviewResponse with line items and totals
            
        Raises:
            PreviewCalculationError: If config or usage is invalid
        """
        
        logger.info(
            f"Calculating preview for config {config.pricing_config_id}: "
            f"{hypothetical_usage} over {period_days} days"
        )
        
        # Validate inputs
        if period_days < 1 or period_days > 365:
            raise PreviewCalculationError("period_days must be between 1 and 365")
        
        if not config.models:
            raise PreviewCalculationError("PricingConfig has no models defined")
        
        # Use first model
        model = config.models[0]
        
        # Calculate line items
        lines = []
        subtotal = 0.0
        
        for component in model.components:
            line_item = BillingPreviewCalculator._calculate_component(
                component, hypothetical_usage, period_days
            )
            
            if line_item:
                lines.append(line_item)
                subtotal += line_item["amount"]
        
        # Build response
        response = PreviewResponse(
            preview=True,
            config_id=config.pricing_config_id,
            period_days=period_days,
            lines=lines,
            subtotal=round(subtotal, 2),
            currency=config.currency,
            note=(
                "⚠️ PREVIEW ONLY - This is a simulation based on estimated usage. "
                "Actual billing will be based on real metered events and may differ. "
                "Taxes and payment processing fees not included."
            )
        )
        
        logger.info(
            f"Preview calculated: {len(lines)} line items, "
            f"subtotal ${subtotal:.2f} {config.currency}"
        )
        
        return response
    
    @staticmethod
    def _calculate_component(
        component: PricingComponent,
        usage: Dict[str, float],
        period_days: int
    ) -> Optional[Dict[str, Any]]:
        """Calculate single line item for a pricing component."""
        
        comp_type = component.component_type
        
        # BASE_FEE
        if comp_type == "BASE_FEE":
            amount = component.amount or 0.0
            
            if component.billing_interval == "monthly" and period_days != 30:
                amount = (amount / 30) * period_days
            elif component.billing_interval == "annual" and period_days != 365:
                amount = (amount / 365) * period_days
            
            return {
                "description": component.desc or f"Base Fee ({component.billing_interval})",
                "quantity": 1,
                "unit_price": amount,
                "amount": round(amount, 2),
                "component_type": comp_type
            }
        
        # USAGE
        elif comp_type == "USAGE":
            dimension = component.usage_dimension
            if not dimension:
                logger.warning(f"USAGE component {component.component_id} missing usage_dimension")
                return None
            
            quantity = usage.get(dimension, 0.0)
            unit_price = component.unit_price or 0.0
            
            if component.tiers:
                amount = BillingPreviewCalculator._calculate_tiered(quantity, component.tiers)
            else:
                amount = quantity * unit_price
            
            return {
                "description": component.desc or f"{dimension.replace('_', ' ').title()}",
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": round(amount, 2),
                "component_type": comp_type,
                "dimension": dimension
            }
        
        # OUTCOME
        elif comp_type == "OUTCOME":
            dimension = component.outcome_dimension
            if not dimension:
                logger.warning(f"OUTCOME component {component.component_id} missing outcome_dimension")
                return None
            
            quantity = usage.get(dimension, 0.0)
            unit_price = component.unit_price or 0.0
            amount = quantity * unit_price
            
            return {
                "description": component.desc or f"{dimension.replace('_', ' ').title()} (Outcome)",
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": round(amount, 2),
                "component_type": comp_type,
                "dimension": dimension
            }
        
        # SEAT
        elif comp_type == "SEAT":
            seats = usage.get("seats", 1)
            unit_price = component.unit_price or 0.0
            amount = seats * unit_price
            
            return {
                "description": component.desc or "Per Seat/User",
                "quantity": seats,
                "unit_price": unit_price,
                "amount": round(amount, 2),
                "component_type": comp_type
            }
        
        # BLOCK_PREPAY
        elif comp_type == "BLOCK_PREPAY":
            dimension = component.usage_dimension or "units"
            quantity = usage.get(dimension, 0.0)
            unit_price = component.unit_price or 0.0
            amount = quantity * unit_price
            
            return {
                "description": component.desc or f"Prepaid Block Consumption ({dimension})",
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": round(amount, 2),
                "component_type": comp_type,
                "note": "This would be deducted from your prepaid wallet balance"
            }
        
        # SHARED_SAVINGS
        elif comp_type == "SHARED_SAVINGS":
            realized_savings = usage.get("realized_savings", 0.0)
            percentage = component.percentage or 0.0
            amount = realized_savings * percentage
            
            return {
                "description": component.desc or "Shared Savings Fee",
                "quantity": realized_savings,
                "unit_price": percentage,
                "amount": round(amount, 2),
                "component_type": comp_type,
                "note": "Calculated as % of realized savings (requires approval)"
            }
        
        else:
            logger.warning(f"Unknown component type: {comp_type}")
            return None
    
    @staticmethod
    def _calculate_tiered(quantity: float, tiers: List[Dict[str, Any]]) -> float:
        """Calculate tiered pricing."""
        total = 0.0
        remaining = quantity
        previous_threshold = 0
        
        for tier in sorted(tiers, key=lambda t: t.get("upto") or float('inf')):
            tier_limit = tier.get("upto")
            tier_price = tier.get("price", 0.0)
            
            if tier_limit is None:
                total += remaining * tier_price
                break
            else:
                tier_quantity = min(remaining, tier_limit - previous_threshold)
                total += tier_quantity * tier_price
                remaining -= tier_quantity
                previous_threshold = tier_limit
                
                if remaining <= 0:
                    break
        
        return total


def preview_invoice(
    config: PricingConfig,
    usage: Dict[str, float],
    period_days: int = 30
) -> PreviewResponse:
    """Convenience wrapper for invoice preview calculation."""
    return BillingPreviewCalculator.calculate_preview(config, usage, period_days)
