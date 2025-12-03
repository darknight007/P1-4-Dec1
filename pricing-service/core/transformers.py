"""
Data Transformation Layer - Cost Analyzer → Pricing Service
Converts upstream cost-savings JSON format to pricing-service schema contracts.

Fortune 500 Standards:
- Fail fast with clear error messages
- Comprehensive validation at boundaries
- Zero tolerance for malformed data
- Full audit trail via logging
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.models import CostProfile, ValueCredit

logger = logging.getLogger("PricingTransformers")
logger.setLevel(logging.INFO)


class TransformationError(Exception):
    """Raised when data transformation fails validation."""
    pass


class CostAnalyzerTransformer:
    """
    Transforms cost-analyzer report_context JSON to pricing-service schemas.
    
    Design Philosophy:
    - Explicit validation at every step
    - Graceful degradation with warnings (not crashes)
    - Rich error context for debugging
    - Performance: O(n) single-pass transformation
    """
    
    @staticmethod
    def transform_to_cost_profile(
        analyzer_json: Dict[str, Any],
        feature_id: str
    ) -> CostProfile:
        """
        Convert cost-analyzer JSON to spec-compliant CostProfile.
        
        Args:
            analyzer_json: Full report_context from cost-savings service
            feature_id: Target feature ID to extract costs for
            
        Returns:
            CostProfile matching billing spec schema
            
        Raises:
            TransformationError: If feature not found or data invalid
            
        Example Input (cost-analyzer):
        {
            "features": [{"id": "F1", "cost_driver_ids": ["L1", "I1"]}],
            "llm_calls": [{"id": "L1", "model": "gpt-4o-mini", "base_tokens": 60000000}],
            "infrastructure": [{"id": "I1", "category": "compute", "monthly_cost": 2.4}]
        }
        
        Example Output (pricing-service):
        {
            "feature_id": "F1",
            "costs": {
                "llm": {"model": "gpt-4o-mini", "est_input_tokens": 45000000, ...},
                "compute": {"cpu_seconds": 5400000, ...}
            },
            "total_est_cost_per_run": 0.0218
        }
        """
        
        # STEP 1: Validate and extract feature
        feature = CostAnalyzerTransformer._extract_feature(analyzer_json, feature_id)
        driver_ids = set(feature["cost_driver_ids"])
        
        logger.info(f"Transforming feature {feature_id} with {len(driver_ids)} cost drivers")
        
        # STEP 2: Build unified driver lookup (all categories merged)
        all_drivers = CostAnalyzerTransformer._build_driver_lookup(analyzer_json)
        
        # STEP 3: Extract and categorize costs
        llm_costs = CostAnalyzerTransformer._extract_llm_costs(all_drivers, driver_ids)
        compute_costs = CostAnalyzerTransformer._extract_compute_costs(all_drivers, driver_ids)
        api_costs = CostAnalyzerTransformer._extract_api_costs(all_drivers, driver_ids)
        storage_costs = CostAnalyzerTransformer._extract_storage_costs(all_drivers, driver_ids)
        
        # STEP 4: Calculate total monthly cost
        total_monthly = CostAnalyzerTransformer._calculate_total_monthly_cost(
            all_drivers, driver_ids
        )
        
        # STEP 5: Estimate cost per run
        # Heuristic: Assume monthly cost covers ~1000 workflow runs
        # This is a simplification - real systems would use actual volume metrics
        estimated_monthly_runs = analyzer_json.get("estimates", {}).get("estimated_monthly_runs", 1000)
        cost_per_run = total_monthly / estimated_monthly_runs if estimated_monthly_runs > 0 else total_monthly
        
        logger.info(
            f"Feature {feature_id}: Total=${total_monthly:.4f}/mo, "
            f"PerRun=${cost_per_run:.6f}, Runs={estimated_monthly_runs}"
        )
        
        # STEP 6: Construct CostProfile
        return CostProfile(
            feature_id=feature_id,
            costs={
                "llm": llm_costs,
                "compute": compute_costs,
                "api_calls": api_costs,
                "storage": storage_costs
            },
            total_est_cost_per_run=round(cost_per_run, 6),
            last_updated=datetime.utcnow().isoformat()
        )
    
    @staticmethod
    def _extract_feature(analyzer_json: Dict, feature_id: str) -> Dict:
        """Extract and validate feature from JSON."""
        features = analyzer_json.get("features", [])
        feature = next((f for f in features if f["id"] == feature_id), None)
        
        if not feature:
            available = [f["id"] for f in features]
            raise TransformationError(
                f"Feature '{feature_id}' not found. Available: {available}"
            )
        
        if not feature.get("cost_driver_ids"):
            logger.warning(f"Feature {feature_id} has no cost drivers - will return zero costs")
        
        return feature
    
    @staticmethod
    def _build_driver_lookup(analyzer_json: Dict) -> Dict[str, Dict]:
        """Merge all cost items into unified lookup by ID."""
        lookup = {}
        
        for category in ["llm_calls", "infrastructure", "integrations", "data_components"]:
            for item in analyzer_json.get(category, []):
                item_id = item.get("id")
                if item_id:
                    lookup[item_id] = {**item, "_category": category}
        
        return lookup
    
    @staticmethod
    def _extract_llm_costs(all_drivers: Dict, driver_ids: set) -> Dict[str, Any]:
        """Extract LLM cost structure."""
        llm_costs = {}
        
        for driver_id in driver_ids:
            driver = all_drivers.get(driver_id)
            if driver and driver.get("_category") == "llm_calls":
                total_tokens = driver.get("base_tokens", 0)
                monthly_cost = driver.get("monthly_cost", 0)
                
                # Industry standard: 75% input tokens, 25% output tokens
                llm_costs = {
                    "model": driver.get("model", "unknown"),
                    "est_input_tokens": int(total_tokens * 0.75),
                    "est_output_tokens": int(total_tokens * 0.25),
                    "unit_cost_per_1k_tokens": (
                        monthly_cost / (total_tokens / 1000) if total_tokens > 0 else 0
                    )
                }
                break  # Use first LLM found
        
        return llm_costs
    
    @staticmethod
    def _extract_compute_costs(all_drivers: Dict, driver_ids: set) -> Dict[str, Any]:
        """Extract compute infrastructure costs."""
        compute_costs = {}
        
        for driver_id in driver_ids:
            driver = all_drivers.get(driver_id)
            if driver and driver.get("_category") == "infrastructure":
                if driver.get("category") == "compute":
                    compute_costs = {
                        "cpu_seconds": driver.get("estimated_volume", 0),
                        "gpu_seconds": 0,  # Not typically in cost-analyzer yet
                        "unit_cost_per_cpu_second": driver.get("user_rate", 0)
                    }
                    break
        
        return compute_costs
    
    @staticmethod
    def _extract_api_costs(all_drivers: Dict, driver_ids: set) -> Dict[str, Any]:
        """Extract third-party API costs."""
        api_costs = {}
        
        for driver_id in driver_ids:
            driver = all_drivers.get(driver_id)
            if driver and driver.get("_category") == "integrations":
                api_name = driver.get("name", "unknown_api").lower().replace(" ", "_")
                api_costs[api_name] = {
                    "calls_per_run": 1,  # Assume 1 call per workflow
                    "unit_cost": driver.get("monthly_cost", 0)
                }
        
        return api_costs
    
    @staticmethod
    def _extract_storage_costs(all_drivers: Dict, driver_ids: set) -> Dict[str, Any]:
        """Extract storage costs."""
        storage_costs = {}
        
        for driver_id in driver_ids:
            driver = all_drivers.get(driver_id)
            if driver and driver.get("_category") == "data_components":
                storage_costs = {
                    "mbs": driver.get("estimated_volume", 0),
                    "unit_cost_per_mb": driver.get("user_rate", 0)
                }
                break
        
        return storage_costs
    
    @staticmethod
    def _calculate_total_monthly_cost(all_drivers: Dict, driver_ids: set) -> float:
        """Sum all monthly costs for selected drivers."""
        total = 0.0
        
        for driver_id in driver_ids:
            driver = all_drivers.get(driver_id)
            if driver:
                total += driver.get("monthly_cost", 0)
        
        return total
    
    @staticmethod
    def generate_value_credits(
        benefit_units: Dict[str, float],
        quality_factor: float,
        feature_id: str
    ) -> List[ValueCredit]:
        """
        Generate ValueCredit objects from ROI calculation results.
        
        Maps benefit_units (e.g., "leads_enriched": 120) to credit types
        that influence pricing model selection.
        
        Args:
            benefit_units: Dict of unit_name → count from savings calculation
            quality_factor: Quality multiplier from ROI (agent vs human accuracy)
            feature_id: Feature identifier
            
        Returns:
            List of ValueCredit objects for pricing recommender
            
        Credit Type Logic:
        - High volume units → Throughput credit
        - Quality factor → Accuracy credit  
        - Multiple unit types → Coverage credit
        """
        credits = []
        
        # THROUGHPUT CREDIT: Based on total volume
        total_volume = sum(benefit_units.values())
        if total_volume > 0:
            # Determine primary unit (highest volume)
            primary_unit = max(benefit_units.items(), key=lambda x: x[1])
            credits.append(ValueCredit(
                credit_type="throughput",
                feature_id=feature_id,
                feature_name=feature_id,  # Will be enriched by caller
                raw_value=total_volume,
                context_tag=primary_unit[0]  # e.g., "leads_enriched"
            ))
        
        # ACCURACY CREDIT: Based on quality factor
        if quality_factor > 0:
            credits.append(ValueCredit(
                credit_type="accuracy",
                feature_id=feature_id,
                feature_name=feature_id,
                raw_value=quality_factor,
                context_tag="quality_multiplier"
            ))
        
        # COVERAGE CREDIT: Based on diversity of outputs
        unique_outputs = len(benefit_units)
        if unique_outputs > 1:
            credits.append(ValueCredit(
                credit_type="coverage",
                feature_id=feature_id,
                feature_name=feature_id,
                raw_value=float(unique_outputs),
                context_tag="output_diversity"
            ))
        
        logger.info(f"Generated {len(credits)} value credits for {feature_id}")
        return credits


# Convenience functions for common transformations
def transform_cost_profile(analyzer_json: Dict, feature_id: str) -> CostProfile:
    """Convenience wrapper for cost profile transformation."""
    return CostAnalyzerTransformer.transform_to_cost_profile(analyzer_json, feature_id)


def transform_value_credits(
    benefit_units: Dict[str, float],
    quality_factor: float,
    feature_id: str
) -> List[ValueCredit]:
    """Convenience wrapper for value credit generation."""
    return CostAnalyzerTransformer.generate_value_credits(
        benefit_units, quality_factor, feature_id
    )
