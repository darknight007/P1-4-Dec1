# core/pricing.py

import os
from typing import Optional
from threading import Lock
from core.infrastructure import infra

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# Cache for pricing data (loaded once per Lambda execution)
_PRICING_CACHE = {}
_CACHE_LOADED = False
_CACHE_LOCK = Lock()  # Thread safety for concurrent requests

def _load_pricing_from_kb():
    """Load all pricing data from ScroogePricingKB into memory cache."""
    global _PRICING_CACHE, _CACHE_LOADED
    
    # Double-check locking pattern for thread safety
    if _CACHE_LOADED:
        return _PRICING_CACHE
    
    with _CACHE_LOCK:
        # Check again inside lock
        if _CACHE_LOADED:
            return _PRICING_CACHE
        
        try:
            pricing_table = infra.get_table('ScroogePricingKB')
            
            response = pricing_table.scan()
            items = response.get('Items', [])
            
            for item in items:
                service_metric = item.get('service_metric', '').lower()
                _PRICING_CACHE[service_metric] = {
                    'price_per_unit': float(item.get('price_per_unit', 0.0)),
                    'category': item.get('category', 'other'),
                    'unit_description': item.get('unit_description', ''),
                    'provider': item.get('provider', 'Unknown'),
                    'confidence': item.get('confidence', 'low')
                }
            
            _CACHE_LOADED = True
            print(f"✅ Loaded {len(_PRICING_CACHE)} pricing entries from KB")
            return _PRICING_CACHE
            
        except Exception as e:
            print(f"⚠️ Failed to load pricing from KB: {e}")
            print(f"⚠️ Falling back to hardcoded pricing")
            _CACHE_LOADED = True  # Don't retry on subsequent calls
            _PRICING_CACHE = _get_fallback_pricing()
            return _PRICING_CACHE

def _get_fallback_pricing():
    """
    Hardcoded fallback if KB is unavailable.
    All prices are per single unit.
    """
    return {
        "tokens": {
            'price_per_unit': 0.000002,  # Per token (was 0.002 per 1K)
            'category': 'llm',
            'unit_description': 'per token'
        },
        "gb-month": {
            'price_per_unit': 0.05,  # Per GB-month
            'category': 'storage',
            'unit_description': 'per GB-month'
        },
        "invocations": {
            'price_per_unit': 0.0000002,  # Per invocation
            'category': 'compute',
            'unit_description': 'per invocation'
        },
        "hours": {
            'price_per_unit': 0.05,  # Per hour
            'category': 'compute',
            'unit_description': 'per hour'
        }
    }

def fuzzy_match_metric(metric: str) -> Optional[dict]:
    """
    Public API for fuzzy matching pricing entries.
    Used by reporter and other modules.
    Attempts to find a matching pricing entry using loose matching.
    
    Examples:
    - "openai-tokens" → exact match
    - "gpt-4 tokens" → matches "gpt-4-tokens"
    - "tokens" → matches generic "tokens"
    """
    pricing_cache = _load_pricing_from_kb()
    
    # Normalize input
    normalized = metric.lower().replace(" ", "-").replace("_", "-")
    
    # 1. Exact match
    if normalized in pricing_cache:
        return pricing_cache[normalized]
    
    # 2. Check if any key contains the metric (e.g., "gpt-4" in "gpt-4-tokens")
    for key, data in pricing_cache.items():
        if normalized in key:
            return data
    
    # 3. Check if metric contains any key (e.g., "openai" matches "openai-tokens")
    for key, data in pricing_cache.items():
        if key in normalized:
            return data
    
    # 4. Fallback to generic category
    generic_keys = ['tokens', 'gb-month', 'invocations', 'hours']
    for generic in generic_keys:
        if generic in normalized and generic in pricing_cache:
            return pricing_cache[generic]
    
    return None

def get_standard_price(category: str, metric: str) -> float:
    """
    Returns price per unit for a given metric.
    First checks KB, then falls back to hardcoded defaults.
    """
    result = fuzzy_match_metric(metric)
    
    if result:
        return result['price_per_unit']
    
    # Ultimate fallback
    print(f"⚠️ No pricing found for: {category}/{metric}")
    return 0.0

def check_if_price_exists(metric: str) -> bool:
    """Helper for the AI to know if it needs to ask the user for a price."""
    result = fuzzy_match_metric(metric)
    return result is not None and result['price_per_unit'] > 0.0

def get_price_details(metric: str) -> Optional[dict]:
    """Returns full pricing details including provider, confidence, etc."""
    return fuzzy_match_metric(metric)

def calculate_line_item_cost(item: dict) -> float:
    """
    Calculates Monthly Cost using KB pricing.
    SIMPLIFIED: All prices are now per single unit, so just multiply.
    """
    volume = item.get("estimated_volume", 0)
    if volume == 0:
        return 0.0

    # 1. User-provided rate (highest priority)
    if item.get("user_rate", 0) > 0:
        return volume * item["user_rate"]

    # 2. KB pricing
    metric = item.get("metric", "units")
    name = item.get("name", "").lower()
    
    # Try to find price by name (e.g., "OpenAI GPT-4" → "gpt-4-tokens")
    result = fuzzy_match_metric(f"{name}-{metric}")
    
    if not result:
        # Try metric alone
        result = fuzzy_match_metric(metric)
    
    if result:
        # SIMPLIFIED: Just multiply volume by price_per_unit
        # No more division by 1000 since all prices are per single unit
        return volume * result['price_per_unit']
    
    # 3. Zero if unknown
    print(f"⚠️ Cannot calculate cost for {name} ({metric}) - no pricing data")
    return 0.0

# Lazy-loaded backward compatibility
_PRICING_DB = None

def get_pricing_db():
    """Lazy-load pricing database for backward compatibility."""
    global _PRICING_DB
    if _PRICING_DB is None:
        _PRICING_DB = _load_pricing_from_kb()
    return _PRICING_DB
