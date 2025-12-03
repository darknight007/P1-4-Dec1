from dotenv import load_dotenv
load_dotenv()
"""
AI-Powered Pricing Recommendation Agent
Uses LLM to generate intelligent pricing configurations with deterministic guardrails.

- LLM is advisor, not decision-maker (guardrails enforce constraints)
- All recommendations are auditable with reasoning
- Deterministic fallback for LLM failures
- Performance-optimized (streaming disabled, structured output)
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from core.models import (
    PricingConfig, PricingModel, PricingComponent,
    SavingsSummary, CostProfile, ValueCredit, PricingRecommendation
)
from core.logic import get_engine

logger = logging.getLogger("PricingRecommender")
logger.setLevel(logging.INFO)


# ============================================================================
# SYSTEM PROMPT - Chief Pricing Officer Persona
# ============================================================================

RECOMMENDER_SYSTEM_PROMPT = """You are the **Chief Pricing Officer** for an AI agent marketplace.

Your mission: Design pricing that maximizes revenue while remaining competitive and fair.

## INPUT CONTEXT YOU WILL RECEIVE

1. **Savings Value**: Monthly dollar savings the agent delivers
2. **Quality Factor**: Agent accuracy vs human accuracy (multiplier)
3. **Pricing Index (PI)**: Market-relative score (0-10 scale)
   - PI > 1.5 = Above market → Aggressive pricing justified
   - PI 0.7-1.5 = At market → Standard pricing
   - PI < 0.7 = Below market → Conservative/freemium pricing
4. **Selected Strategy**: Pre-calculated strategy with margin targets
5. **Cost Structure**: Technical costs (LLM, compute, APIs)
6. **Value Credits**: Dimensions of value (throughput, accuracy, coverage)
7. **Customer Segment**: SMB, mid-market, or enterprise

## VALUE CREDIT INTERPRETATION RULES

**Throughput Credits (High Volume)**:
- Indicates many units processed per period
- **Recommendation**: USAGE-based pricing (per workflow run, per API call)
- Justification: Customer pays for what they consume, scales naturally

**Accuracy Credits (High Quality)**:
- Indicates agent output quality is measurable and high
- **Recommendation**: OUTCOME-based pricing (pay per qualified lead, per successful prediction)
- Justification: Customer pays for results, aligns incentives

**Coverage Credits (Multiple Outputs)**:
- Indicates agent provides diverse functionality
- **Recommendation**: HYBRID model (base + usage) or TIERED (feature bundles)
- Justification: Different customers value different capabilities

**Multiple High Credits**:
- Indicates premium product
- **Recommendation**: HYBRID with higher base fee + usage + optional outcome component

**Low/Missing Credits**:
- Indicates unclear value proposition
- **Recommendation**: Simple SUBSCRIPTION or PLG-friendly pricing

## PRICING MODEL SELECTION LOGIC

**Use USAGE_ONLY when**:
- High throughput credit + clear per-unit metric
- Low/unpredictable usage patterns
- SMB segment with budget sensitivity

**Use OUTCOME_ONLY when**:
- High accuracy credit + measurable outcome
- Customer is risk-averse (wants performance guarantee)
- High PI score (premium positioning)

**Use HYBRID (Base + Usage) when**:
- Medium/high PI score
- Predictable baseline usage + variable peaks
- Want to ensure minimum revenue commitment

**Use SUBSCRIPTION when**:
- Enterprise segment with seat-based model
- Value is in access, not volume
- Low/moderate PI score

**Use FREEMIUM when**:
- PI < 0.5 (need market adoption first)
- PLG strategy
- Network effects or viral potential

## COMPONENT CALCULATION FORMULAS

**Base Fee Calculation**:
Base Fee = (Monthly Savings × Strategy.base_fee_weight × 0.08) 
Constraints: Min $5, Max $999, Round to nearest $1

**Usage Price Calculation**:
Usage Price = (Cost Per Run × Strategy.usage_markup_multiplier × PI_Premium)
Where PI_Premium = 1 + max(0, (PI - 1.5) × 0.1)
Constraints: Min $0.001, Round to 4 decimals

**Outcome Price Calculation**:
Outcome Price = (Monthly Savings / Expected Outcomes Per Month) × Strategy.margin_target × 0.01
Constraints: Min $1, Round to 2 decimals

## OUTPUT REQUIREMENTS

Return ONLY a valid JSON object matching this schema. Do not include markdown code blocks or explanations.

{
  "pricing_config_id": "pc_<product_id>_v1",
  "product_id": "<from input>",
  "name": "Descriptive Plan Name",
  "desc": "Brief explanation of value proposition",
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
          "billing_interval": "monthly",
          "desc": "Monthly platform access"
        },
        {
          "component_id": "usage",
          "component_type": "USAGE",
          "unit_price": 0.10,
          "usage_dimension": "workflow_run",
          "desc": "Per workflow execution"
        }
      ],
      "margin_multiplier": 1.0,
      "credit_factor": 1.0
    }
  ],
  "wallet_enabled": false,
  "status": "draft"
}

## CRITICAL CONSTRAINTS

1. **Margin Safety**: Ensure gross margin > 40% (price / cost ratio > 1.67x)
2. **Pricing Psychology**: 
   - Base fees end in 9 or 5 (e.g., $29, $49, $99)
   - Usage prices use clean decimals (e.g., $0.10, not $0.0873)
3. **Competitiveness**: Check PI score - don't price above market unless PI > 1.5
4. **Value Alignment**: Pricing should reflect value credits (high throughput → usage-based)

IMPORTANT: Return ONLY the JSON config. Do not include markdown code blocks, explanations, or any non-JSON text.
"""


# ============================================================================
# Pricing Recommender Agent
# ============================================================================

class PricingRecommender:
    """
    AI-powered pricing recommendation engine with deterministic guardrails.
    
    Architecture:
    1. Prepare context (PI, strategy, value credits)
    2. Invoke LLM with structured prompt
    3. Validate output against constraints
    4. Apply deterministic corrections if needed
    5. Return PricingConfig with reasoning
    """
    
    def __init__(self, model_name: str = "gemini-2.0-flash-exp"):
        """
        Initialize recommender with LLM client.
        
        Args:
            model_name: Gemini model to use (flash for speed, pro for quality)
        """
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.3,
            max_output_tokens=2048
        )
        self.engine = get_engine()
        logger.info(f"PricingRecommender initialized with model: {model_name}")
    
    def generate_proposal(
        self,
        savings: SavingsSummary,
        costs: CostProfile,
        value_credits: list[ValueCredit] = None,
        customer_segment: str = "smb"
    ) -> PricingRecommendation:
        """
        Generate AI-powered pricing recommendation with guardrails.
        
        Args:
            savings: ROI calculation results
            costs: Technical cost breakdown
            value_credits: Optional value dimensions for enhanced recommendations
            customer_segment: Target customer type
            
        Returns:
            PricingRecommendation with config, reasoning, and metadata
            
        Raises:
            Exception: If both LLM and fallback fail (rare)
        """
        
        # STEP 1: Calculate Pricing Index
        pi_score = self.engine.calculate_pricing_index(
            monthly_savings=savings.estimated_monthly_savings_usd,
            quality_factor=savings.quality_factor,
            feature_category="automation"
        )
        
        # STEP 2: Select pricing strategy
        strategy = self.engine.select_strategy(
            pi_score=pi_score,
            customer_segment=customer_segment
        )
        strategy_name = strategy.get("_selected_strategy_name", "unknown")
        
        logger.info(
            f"Generating pricing proposal: PI={pi_score:.2f}, "
            f"Strategy={strategy_name}, Segment={customer_segment}"
        )
        
        # STEP 3: Attempt LLM generation
        try:
            config = self._invoke_llm(
                savings, costs, value_credits, pi_score, strategy, customer_segment
            )
            confidence = 0.85
            reasoning = self._extract_reasoning(config, pi_score, strategy_name)
            
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}. Using deterministic fallback.")
            config = self._fallback_proposal(savings, costs, pi_score, strategy, customer_segment)
            confidence = 0.60
            reasoning = (
                f"Generated via deterministic fallback due to LLM failure. "
                f"Strategy: {strategy_name}, PI: {pi_score:.2f}. "
                f"Pricing uses conservative margin multipliers."
            )
        
        # STEP 4: Apply guardrails
        config = self._apply_guardrails(config, costs, strategy)
        
        # STEP 5: Return wrapped recommendation
        return PricingRecommendation(
            config=config,
            confidence_score=confidence,
            reasoning=reasoning,
            pi_score=pi_score,
            selected_strategy=strategy_name
        )
    
    def _invoke_llm(
        self,
        savings: SavingsSummary,
        costs: CostProfile,
        value_credits: Optional[list[ValueCredit]],
        pi_score: float,
        strategy: Dict[str, Any],
        customer_segment: str
    ) -> PricingConfig:
        """Invoke LLM with structured prompt."""
        
        # Build value credits context
        credits_context = "No value credits provided."
        if value_credits:
            credits_list = []
            for credit in value_credits:
                credits_list.append(
                    f"- {credit.credit_type.upper()}: {credit.raw_value} "
                    f"({credit.context_tag})"
                )
            credits_context = "\n".join(credits_list)
        
        # Construct prompt
        strategy_name = strategy.get("_selected_strategy_name", "unknown")
        prompt = f"""{RECOMMENDER_SYSTEM_PROMPT}

---

## YOUR TASK

Generate a pricing configuration for this agent:

**Savings Summary:**
- Monthly Savings: ${savings.estimated_monthly_savings_usd:,.2f}
- Human Hours Saved: {savings.human_hours_saved:.1f} hours
- Quality Factor: {savings.quality_factor:.2f}x
- Benefit Units: {json.dumps(savings.benefit_units)}

**Cost Profile:**
- Cost Per Run: ${costs.total_est_cost_per_run:.6f}
- Cost Breakdown: {json.dumps(costs.costs, indent=2)}

**Value Credits:**
{credits_context}

**Pricing Context:**
- Pricing Index (PI): {pi_score:.2f}
- Selected Strategy: {strategy_name}
- Strategy Margin Target: {strategy.get('margin_target_percent', 50)}%
- Strategy Base Fee Weight: {strategy.get('base_fee_weight', 0.5)}
- Strategy Usage Markup: {strategy.get('usage_markup_multiplier', 2.5)}x
- Customer Segment: {customer_segment}

**Feature ID:** {savings.feature_id}
**Product ID:** {costs.feature_id}_product

---

Generate the PricingConfig JSON now:
"""
        
        # Invoke LLM
        response = self.llm.invoke([HumanMessage(content=prompt)])
        raw_output = response.content.strip()
        
        # Clean output
        clean_json = raw_output
        if 'json' in raw_output and raw_output.count('`') >= 6:
            parts = raw_output.split('`'*3)
            if len(parts) >= 3:
                clean_json = parts[1].replace('json', '').strip()
        elif raw_output.count('`') >= 6:
            parts = raw_output.split('`'*3)
            if len(parts) >= 3:
                clean_json = parts[1].strip()
        
        # Parse and validate
        data = json.loads(clean_json)
        config = PricingConfig(**data)
        
        logger.info(f"LLM successfully generated pricing config: {config.pricing_config_id}")
        return config
    
    def _fallback_proposal(
        self,
        savings: SavingsSummary,
        costs: CostProfile,
        pi_score: float,
        strategy: Dict[str, Any],
        customer_segment: str
    ) -> PricingConfig:
        """Deterministic fallback when LLM fails."""
        
        # Calculate base fee
        base_fee_weight = strategy.get("base_fee_weight", 0.5)
        base_fee = savings.estimated_monthly_savings_usd * base_fee_weight * 0.08
        base_fee = max(5.0, min(base_fee, 999.0))
        base_fee = round(base_fee / 10) * 10 - 1
        
        # Calculate usage price
        markup = strategy.get("usage_markup_multiplier", 2.5)
        pi_premium = 1.0 + max(0, (pi_score - 1.5) * 0.1)
        usage_price = costs.total_est_cost_per_run * markup * pi_premium
        usage_price = max(0.001, round(usage_price, 4))
        
        # Build HYBRID model
        components = [
            PricingComponent(
                component_id="base",
                component_type="BASE_FEE",
                amount=base_fee,
                billing_interval="monthly",
                desc="Monthly platform access"
            ),
            PricingComponent(
                component_id="usage",
                component_type="USAGE",
                unit_price=usage_price,
                usage_dimension="workflow_run",
                desc="Per workflow execution"
            )
        ]
        
        config = PricingConfig(
            pricing_config_id=f"pc_{costs.feature_id}_fallback",
            product_id=f"{costs.feature_id}_product",
            name=f"{savings.feature_id} - Standard Plan (Auto-Generated)",
            desc="Fallback pricing generated by deterministic rules",
            currency="USD",
            models=[
                PricingModel(
                    model_id="m1",
                    type="HYBRID",
                    components=components,
                    margin_multiplier=1.0,
                    credit_factor=1.0
                )
            ],
            status="draft"
        )
        
        logger.info(f"Fallback config generated: Base=${base_fee}, Usage=${usage_price}")
        return config
    
    def _apply_guardrails(
        self,
        config: PricingConfig,
        costs: CostProfile,
        strategy: Dict[str, Any]
    ) -> PricingConfig:
        """Validate and correct pricing config against business constraints."""
        
        target_margin = strategy.get("margin_target_percent", 50) / 100
        min_margin = 0.40
        
        for model in config.models:
            for component in model.components:
                
                # Margin validation for USAGE
                if component.component_type == "USAGE" and component.unit_price:
                    implied_margin = (
                        (component.unit_price - costs.total_est_cost_per_run) 
                        / component.unit_price
                    )
                    
                    if implied_margin < min_margin:
                        min_price = costs.total_est_cost_per_run / (1 - min_margin)
                        old_price = component.unit_price
                        component.unit_price = round(min_price, 4)
                        
                        logger.warning(
                            f"Margin guardrail triggered: Adjusted usage price "
                            f"${old_price} → ${component.unit_price}"
                        )
                
                # Pricing psychology for base fees
                if component.component_type == "BASE_FEE" and component.amount:
                    amount = component.amount
                    last_digit = int(amount) % 10
                    
                    if last_digit not in [5, 9]:
                        if last_digit < 5:
                            adjusted = (int(amount) // 10) * 10 + 5
                        else:
                            adjusted = (int(amount) // 10) * 10 + 9
                        
                        if adjusted != amount:
                            logger.info(f"Pricing psychology: ${amount} → ${adjusted}")
                            component.amount = float(adjusted)
        
        return config
    
    def _extract_reasoning(
        self,
        config: PricingConfig,
        pi_score: float,
        strategy_name: str
    ) -> str:
        """Generate reasoning explanation for the pricing decision."""
        model_type = config.models[0].type if config.models else "UNKNOWN"
        base_component = next(
            (c for c in config.models[0].components if c.component_type == "BASE_FEE"),
            None
        )
        usage_component = next(
            (c for c in config.models[0].components if c.component_type == "USAGE"),
            None
        )
        
        reasoning_parts = []
        
        reasoning_parts.append(
            f"Selected {model_type} pricing model based on {strategy_name} strategy "
            f"(PI score: {pi_score:.2f})."
        )
        
        if base_component and usage_component:
            reasoning_parts.append(
                f"Base fee of ${base_component.amount:.0f}/month ensures minimum revenue commitment, "
                f"while ${usage_component.unit_price:.4f} per workflow run scales with customer usage."
            )
        elif usage_component:
            reasoning_parts.append(
                f"Usage-only pricing at ${usage_component.unit_price:.4f} per run "
                f"provides low barrier to entry and aligns costs with value delivered."
            )
        
        if pi_score > 1.5:
            reasoning_parts.append(
                "Pricing is positioned above market average due to superior value delivery."
            )
        elif pi_score < 0.7:
            reasoning_parts.append(
                "Conservative pricing recommended to drive adoption in competitive market."
            )
        else:
            reasoning_parts.append(
                "Pricing is competitive with market standards."
            )
        
        return " ".join(reasoning_parts)


# Singleton instance
_recommender_instance = None

def get_recommender() -> PricingRecommender:
    """Get or create singleton recommender instance."""
    global _recommender_instance
    if _recommender_instance is None:
        _recommender_instance = PricingRecommender()
    return _recommender_instance
