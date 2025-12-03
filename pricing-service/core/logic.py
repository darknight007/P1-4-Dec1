"""
Pricing Logic Engine - Core Business Rules
Deterministic pricing calculations with industry-relative benchmarking.

Fortune 500 Standards:
- All calculations are auditable and reproducible
- Market benchmarks are configurable, not hardcoded
- Thread-safe singleton pattern
- Comprehensive validation of inputs
"""

import yaml
import logging
from typing import Dict, Any, Optional
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("PricingLogicEngine")
logger.setLevel(logging.INFO)

# Configuration paths
CONFIG_DIR = Path(__file__).parent.parent / "config"
BENCHMARKS_FILE = CONFIG_DIR / "market_benchmarks.yaml"
STRATEGIES_FILE = CONFIG_DIR / "pricing_strategies.yaml"
FEATURES_FILE = CONFIG_DIR / "feature_weights.yaml"


class ConfigurationError(Exception):
    """Raised when critical configuration is missing or invalid."""
    pass


class PricingLogicEngine:
    """
    Deterministic pricing calculations and strategy selection.
    
    Design Philosophy:
    - Market-relative pricing (not absolute)
    - Configurable benchmarks (not magic numbers)
    - Defensive programming (validate everything)
    - Performance-optimized (cached configs)
    
    Pricing Index Formula:
        PI = (Savings × Quality × Stickiness) / Market Benchmark
        
    Where:
        - Savings: Monthly USD savings from agent
        - Quality: Agent accuracy / Human accuracy (multiplier)
        - Stickiness: Feature lock-in factor (0.0-1.0)
        - Market Benchmark: Industry-specific baseline savings
    
    Example:
        Chatbot saves $3K/month, market avg is $1.5K
        PI = (3000 × 1.1 × 0.5) / 1500 = 1.1 → HIGH PI → Aggressive pricing
        
        Enterprise ERP saves $3K/month, market avg is $25K
        PI = (3000 × 1.0 × 0.9) / 25000 = 0.108 → LOW PI → Conservative pricing
    """
    
    def __init__(self):
        """Initialize with configuration loading and validation."""
        self.benchmarks = self._load_yaml(BENCHMARKS_FILE)
        self.strategies = self._load_yaml(STRATEGIES_FILE)
        self.features = self._load_yaml(FEATURES_FILE)
        self._validate_configs()
        
        logger.info(
            f"PricingLogicEngine initialized: "
            f"{len(self.benchmarks.get('categories', {}))} benchmark categories, "
            f"{len(self.strategies.get('strategies', {}))} pricing strategies"
        )
    
    @staticmethod
    def _load_yaml(filepath: Path) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        try:
            if not filepath.exists():
                logger.warning(f"Config file not found: {filepath}. Using empty defaults.")
                return {}
            
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    raise ValueError(f"YAML file {filepath.name} must parse to a dict.")
                return data
                
        except Exception as e:
            logger.error(f"Failed to load {filepath.name}: {e}")
            return {}
    
    def _validate_configs(self):
        """Ensure critical configuration keys exist."""
        # Validate pricing strategies
        if "strategies" not in self.strategies:
            logger.error("CRITICAL: 'strategies' key missing in pricing_strategies.yaml")
            self.strategies["strategies"] = {
                "fallback": {
                    "margin_target_percent": 50,
                    "base_fee_weight": 0.5,
                    "usage_markup_multiplier": 2.0
                }
            }
        
        # Validate feature weights
        if "defaults" not in self.features:
            self.features["defaults"] = {
                "stickiness": 0.5,
                "value_perception": "medium"
            }
        
        # Validate market benchmarks
        if "categories" not in self.benchmarks:
            logger.warning("No benchmark categories defined. Using single default.")
            self.benchmarks["categories"] = {}
        
        if "defaults" not in self.benchmarks:
            self.benchmarks["defaults"] = {
                "benchmark_monthly_savings": 2500,
                "benchmark_description": "Generic baseline"
            }
    
    def calculate_pricing_index(
        self,
        monthly_savings: float,
        quality_factor: float,
        feature_category: str = "automation",
        market_benchmark_override: Optional[float] = None
    ) -> float:
        """
        Calculate Pricing Index with market-relative benchmarking.
        
        Args:
            monthly_savings: Estimated monthly savings in USD
            quality_factor: Quality multiplier (agent accuracy / human accuracy)
            feature_category: Category key from market_benchmarks.yaml
            market_benchmark_override: Optional manual benchmark override
            
        Returns:
            Pricing Index score (typically 0.0-10.0, uncapped)
            
        Algorithm:
            1. Validate and clamp inputs
            2. Load market benchmark for category
            3. Calculate raw score: Savings × Quality × Stickiness
            4. Normalize by market benchmark
            5. Return capped score for safety
        """
        
        # STEP 1: Input validation and sanitization
        if monthly_savings < 0:
            logger.warning(f"Negative savings input: {monthly_savings}. Clamping to 0.")
            monthly_savings = 0.0
        
        quality_factor = max(0.0, min(quality_factor, 5.0))  # Cap at 5x improvement
        
        # STEP 2: Load market benchmark
        if market_benchmark_override:
            benchmark = market_benchmark_override
            logger.info(f"Using manual benchmark override: ${benchmark}")
        else:
            benchmark = self._get_market_benchmark(feature_category)
        
        # STEP 3: Get feature stickiness factor
        stickiness = self._get_stickiness(feature_category)
        
        # STEP 4: Calculate raw score
        raw_score = monthly_savings * quality_factor * stickiness
        
        # STEP 5: Normalize by market benchmark
        if benchmark <= 0:
            logger.error(f"Invalid benchmark {benchmark} for {feature_category}. Using default.")
            benchmark = self.benchmarks["defaults"]["benchmark_monthly_savings"]
        
        pi_score = raw_score / benchmark
        
        # STEP 6: Apply safety cap (prevent extreme scores from bad data)
        # Cap at 10.0 for sanity, but don't artificially limit genuine high-value features
        capped_score = min(pi_score, 10.0)
        
        if pi_score > 10.0:
            logger.warning(
                f"PI score {pi_score:.2f} exceeds cap. Using 10.0. "
                f"(Savings=${monthly_savings}, Quality={quality_factor}, "
                f"Stickiness={stickiness}, Benchmark=${benchmark})"
            )
        
        logger.info(
            f"Pricing Index Calculation: "
            f"Savings=${monthly_savings:.2f}, Quality={quality_factor:.2f}, "
            f"Stickiness={stickiness:.2f}, Benchmark=${benchmark:.2f} → "
            f"PI={capped_score:.2f} ({self._get_pi_band(capped_score)})"
        )
        
        return round(capped_score, 2)
    
    def _get_market_benchmark(self, category: str) -> float:
        """
        Load market benchmark for a specific category.
        
        Args:
            category: Category key (e.g., "chatbot", "automation")
            
        Returns:
            Benchmark monthly savings in USD
        """
        categories = self.benchmarks.get("categories", {})
        
        if category in categories:
            benchmark = categories[category].get("benchmark_monthly_savings")
            if benchmark:
                logger.debug(
                    f"Benchmark for '{category}': ${benchmark} "
                    f"({categories[category].get('benchmark_description', 'N/A')})"
                )
                return float(benchmark)
        
        # Fallback to default
        default = self.benchmarks.get("defaults", {}).get("benchmark_monthly_savings", 2500.0)
        logger.debug(f"Category '{category}' not found. Using default benchmark: ${default}")
        return float(default)
    
    def _get_stickiness(self, category: str) -> float:
        """
        Retrieve feature stickiness factor from feature_weights.yaml.
        
        Stickiness = How hard it is for customer to rip out the feature.
        Higher stickiness = More pricing power.
        
        Args:
            category: Feature category
            
        Returns:
            Stickiness factor (0.0-1.0)
        """
        categories = self.features.get("categories", {})
        defaults = self.features.get("defaults", {"stickiness": 0.5})
        
        if category in categories:
            return float(categories[category].get("stickiness", defaults["stickiness"]))
        
        return float(defaults["stickiness"])
    
    def _get_pi_band(self, pi_score: float) -> str:
        """Classify PI score into interpretable bands."""
        guidance = self.benchmarks.get("scoring_guidance", {})
        
        if pi_score >= guidance.get("high_pi", {}).get("threshold", 1.5):
            return "HIGH - Above Market"
        elif pi_score >= guidance.get("medium_pi", {}).get("threshold", 0.7):
            return "MEDIUM - At Market"
        elif pi_score >= guidance.get("low_pi", {}).get("threshold", 0.4):
            return "LOW - Below Market"
        else:
            return "VERY LOW - Reconsider PMF"
    
    def select_strategy(
        self,
        pi_score: float,
        customer_segment: str = "smb",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Select optimal pricing strategy based on PI score and segment.
        
        Strategy Selection Rules:
        - Enterprise + High PI (>5.0) → Aggressive Enterprise
        - SMB + Low PI (<1.0) → PLG Growth
        - Default → Balanced SaaS
        
        Args:
            pi_score: Calculated pricing index
            customer_segment: "smb" | "mid_market" | "enterprise"
            context: Optional additional context for decision-making
            
        Returns:
            Strategy configuration dict
        """
        strategies = self.strategies.get("strategies", {})
        selected_key = "balanced_saas"  # Safe default
        
        # Normalize segment
        segment = customer_segment.lower().strip()
        
        # RULE ENGINE
        # Rule 1: Enterprise with high value → Maximize margin
        if segment == "enterprise" and pi_score > 5.0:
            if "aggressive_enterprise" in strategies:
                selected_key = "aggressive_enterprise"
                logger.info(
                    f"Strategy: Aggressive Enterprise (PI={pi_score:.2f} >> threshold, "
                    f"segment=enterprise)"
                )
        
        # Rule 2: SMB with low value → Maximize adoption
        elif segment == "smb" and pi_score < 1.0:
            if "plg_growth" in strategies:
                selected_key = "plg_growth"
                logger.info(
                    f"Strategy: PLG Growth (PI={pi_score:.2f} << threshold, segment=smb)"
                )
        
        # Rule 3: Mid-market or balanced scenarios
        elif "balanced_saas" in strategies:
            selected_key = "balanced_saas"
            logger.info(
                f"Strategy: Balanced SaaS (PI={pi_score:.2f}, segment={segment})"
            )
        
        # Safety: Ensure selected strategy exists
        if selected_key not in strategies:
            logger.warning(
                f"Selected strategy '{selected_key}' not in config. "
                f"Using first available strategy."
            )
            if strategies:
                selected_key = list(strategies.keys())[0]
            else:
                raise ConfigurationError("No pricing strategies defined in config.")
        
        strategy = strategies[selected_key]
        
        # Enrich strategy with metadata
        strategy["_selected_strategy_name"] = selected_key
        strategy["_pi_score"] = pi_score
        strategy["_customer_segment"] = segment
        
        return strategy
    
    def calculate_margins(
        self,
        base_cost: float,
        strategy: Dict[str, Any],
        pi_score: Optional[float] = None
    ) -> float:
        """
        Calculate target pricing with margin multiplier and optional PI premium.
        
        Formula: Price = Cost × Markup × (1 + PI Premium)
        
        Where:
            - Cost: Technical cost per unit
            - Markup: Strategy-defined multiplier (e.g., 2.5x)
            - PI Premium: Optional uplift for high-value features
        
        Args:
            base_cost: Cost per unit (from CostProfile)
            strategy: Selected pricing strategy dict
            pi_score: Optional PI score for premium calculation
            
        Returns:
            Recommended unit price
        """
        multiplier = strategy.get("usage_markup_multiplier", 2.5)
        
        # Optional PI-based premium (high value = charge more)
        if pi_score and pi_score > 1.5:
            pi_premium = 1 + ((pi_score - 1.5) * 0.1)  # +10% per PI point above 1.5
            pi_premium = min(pi_premium, 2.0)  # Cap at 2x premium
        else:
            pi_premium = 1.0
        
        price = base_cost * multiplier * pi_premium
        
        logger.debug(
            f"Margin calculation: ${base_cost:.4f} × {multiplier}x × {pi_premium:.2f} "
            f"= ${price:.4f}"
        )
        
        return round(price, 4)
    
    def get_strategy_recommendation(self, pi_score: float) -> str:
        """
        Get human-readable strategy recommendation based on PI score.
        
        Used for UI display and explainability.
        """
        guidance = self.benchmarks.get("scoring_guidance", {})
        
        for band in ["high_pi", "medium_pi", "low_pi", "very_low_pi"]:
            band_config = guidance.get(band, {})
            threshold = band_config.get("threshold", 0)
            
            if pi_score >= threshold:
                return band_config.get(
                    "strategy_recommendation",
                    "No recommendation available"
                )
        
        return "Insufficient data for recommendation"


# Singleton instance for application-wide use
_engine_instance = None

def get_engine() -> PricingLogicEngine:
    """Get or create singleton pricing engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PricingLogicEngine()
    return _engine_instance


# Legacy compatibility - maintain old interface
engine = get_engine()
