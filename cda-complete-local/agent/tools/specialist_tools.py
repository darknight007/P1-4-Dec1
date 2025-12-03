# agent/tools/specialist_tools.py

import os
from langchain_core.tools import tool
from typing import Optional

# Check environment
IS_LOCAL = os.environ.get("SCROOGE_ENV") == "LOCAL"

@tool
def grep_codebase(patterns: list[str]) -> str:
    """
    Search the codebase for specific patterns.
    Use this to find imports, API calls, config files, or infrastructure definitions.
    
    Args:
        patterns: List of strings to search for (e.g., ['openai', 'stripe', 'docker'])
    
    Returns:
        String with matched file paths and line numbers
    
    Examples:
        grep_codebase(['openai', 'langchain'])
        grep_codebase(['Dockerfile', 'docker-compose'])
    """
    return f"Tool execution happens in graph - this is a schema placeholder"

@tool
def read_file(file_path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
    """
    Read contents of a specific file, optionally within a line range.
    
    Args:
        file_path: Relative path to the file
        start_line: Starting line number (default: 1)
        end_line: Ending line number (default: read to EOF)
    
    Returns:
        File contents as string
    
    Examples:
        read_file('requirements.txt')
        read_file('src/main.py', 10, 50)
    """
    return f"Tool execution happens in graph - this is a schema placeholder"

# --- ASK HUMAN IMPLEMENTATION ---
if IS_LOCAL:
    # In Local Mode, we need to raise an exception to pause the runner loop
    # Define exception here to avoid circular imports
    class HumanInputNeeded(Exception):
        def __init__(self, question: str):
            self.question = question
            super().__init__(f"Human input required: {question}")

    @tool
    def ask_human(question: str) -> str:
        """
        Pause execution and ask the human operator a question.
        Use this when you need pricing information, volume estimates, or clarification.
        
        Args:
            question: Clear, specific question for the human
        
        Returns:
            Human's answer as string
        """
        # This Exception MUST be caught by local_runner.py
        # Note: local_runner.py must import this exception class or catch the name
        raise HumanInputNeeded(question)
else:
    @tool
    def ask_human(question: str) -> str:
        """
        Pause execution and ask the human operator a question.
        Use this when you need pricing information, volume estimates, or clarification.
        
        Args:
            question: Clear, specific question for the human
        
        Returns:
            Human's answer as string
        """
        return f"Tool execution happens in graph - this is a schema placeholder"

@tool
def check_price_knowledge(metric: str) -> str:
    """
    Check if we have pricing data for a specific metric in our knowledge base.
    
    Args:
        metric: The metric to check (e.g., 'tokens', 'gb-month', 'invocations')
    
    Returns:
        String indicating if price is known or unknown
    
    Examples:
        check_price_knowledge('tokens')
        check_price_knowledge('stripe-transactions')
    """
    from core.pricing import check_if_price_exists
    
    exists = check_if_price_exists(metric)
    
    if exists:
        return f"✅ Price KNOWN. You only need to ask the user for Volume."
    else:
        return f"❌ Price UNKNOWN. You must ask the user for BOTH Volume AND Rate."

@tool
def calculate_cost(
    volume: float,
    metric: str,
    service_name: str = ""
) -> dict:
    """
    Calculate monthly cost for a given volume and metric using our pricing knowledge base.
    This tool handles all unit conversions and pricing lookups automatically.
    
    Args:
        volume: The monthly volume (e.g., 50000 for tokens, 100 for GB-month)
        metric: Unit type (e.g., "tokens", "gb-month", "invocations", "hours")
        service_name: Optional service name for specific pricing (e.g., "gpt-4", "s3")
    
    Returns:
        Dictionary with:
        - monthly_cost: Calculated cost in USD
        - volume: Input volume
        - metric: Input metric
        - price_per_unit: Unit price used
        - unit_description: Description of pricing unit
        - provider: Service provider
        - breakdown: Human-readable calculation
        - error: Error message if calculation failed
        - needs_user_input: True if pricing not found
    
    Examples:
        calculate_cost(50000, "tokens", "gpt-4")
        # Returns: {"monthly_cost": 1.50, "breakdown": "50000 tokens × $0.00003/token = $1.50"}
        
        calculate_cost(100, "gb-month", "s3")
        # Returns: {"monthly_cost": 2.30, "breakdown": "100 gb-month × $0.023/gb-month = $2.30"}
        
        calculate_cost(1000000, "invocations", "lambda")
        # Returns: {"monthly_cost": 0.20, "breakdown": "1000000 invocations × $0.0000002/invocation = $0.20"}
    """
    from core.pricing import fuzzy_match_metric
    
    try:
        # Validate inputs
        if volume < 0:
            return {
                "error": "Volume cannot be negative",
                "monthly_cost": 0.0,
                "needs_user_input": False
            }
        
        # Find pricing
        search_key = f"{service_name}-{metric}" if service_name else metric
        result = fuzzy_match_metric(search_key)
        
        if not result:
            return {
                "error": f"No pricing found for {search_key}",
                "monthly_cost": 0.0,
                "needs_user_input": True,
                "suggestion": f"Ask user: 'What is your rate for {metric}?'"
            }
        
        price_per_unit = result['price_per_unit']
        unit_desc = result.get('unit_description', 'per unit')
        provider = result.get('provider', 'Unknown')
        
        # Simple multiplication - all prices are now per single unit
        monthly_cost = volume * price_per_unit
        
        return {
            "monthly_cost": round(monthly_cost, 4),
            "volume": volume,
            "metric": metric,
            "price_per_unit": price_per_unit,
            "unit_description": unit_desc,
            "provider": provider,
            "breakdown": f"{volume:,.0f} {metric} × ${price_per_unit}/{unit_desc.replace('per ', '')} = ${monthly_cost:.2f}",
            "needs_user_input": False
        }
    
    except Exception as e:
        return {
            "error": f"Calculation failed: {str(e)}",
            "monthly_cost": 0.0,
            "needs_user_input": False
        }

@tool
def complete_validation() -> str:
    """
    Signal that validation is complete and the report can be generated.
    Call this after you have collected all necessary volume and pricing information.
    
    Returns:
        Confirmation message
    """
    return "✅ Validation complete. Proceeding to report generation."

# Export all tools
SPECIALIST_TOOLS = [
    grep_codebase,
    read_file,
    ask_human,
    check_price_knowledge,
    calculate_cost,  # ← NEW TOOL ADDED
    complete_validation
]