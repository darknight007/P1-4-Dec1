import os
from langchain_core.tools import tool

@tool
def ask_human(question: str, context: str = ""):
    """
    Asks the human user a specific question to clarify costs, traffic, or infrastructure.
    Use this when you cannot find specific values in the code (e.g., "What is the API pricing tier?", "How many users per day?").
    The process will PAUSE until the user answers.
    """
    # This function body is a placeholder.
    # The logic is intercepted in main.py by the runtime.
    return "Waiting for user input..."

@tool
def read_external_cost_context(file_path: str):
    """
    Reads an EXTERNAL file (outside the repo) provided by the user containing cost sheets, pricing data, or specs.
    Supports .txt, .md, .csv, .json.
    """
    # We allow absolute paths here because the user explicitly provided them.
    clean_path = file_path.strip().strip('"').strip("'")
    
    if not os.path.exists(clean_path):
        return f"❌ Error: The file at '{clean_path}' does not exist. Please ask the user for the correct path."

    try:
        # Simple text reading. We rely on the LLM to parse CSV/JSON structure from the raw text.
        with open(clean_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Truncate if massive to prevent context window explosion
        if len(content) > 30000:
            return f"--- FILE: {os.path.basename(clean_path)} (Truncated) ---\n{content[:30000]}\n... [Truncated]"
        
        return f"--- FILE: {os.path.basename(clean_path)} ---\n{content}"
    except Exception as e:
        return f"❌ Error reading file: {str(e)}"