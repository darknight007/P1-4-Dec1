import json
import os
from typing import List

MEMORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory", "insights.json")

def init_memory():
    """Ensures the memory directory and file exist."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w") as f:
            json.dump({"insights": [], "learned_patterns": []}, f)

def get_global_insights(limit: int = 5) -> str:
    """
    Retrieves the top N most recent insights to feed into the Recon agent.
    """
    init_memory()
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            insights = data.get("insights", [])
            # Return the last 'limit' insights (most recent)
            return "\n".join([f"- {i}" for i in insights[-limit:]])
    except Exception:
        return "No previous insights available."

def save_new_insight(insight: str):
    """
    Saves a new lesson learned to the global memory.
    """
    init_memory()
    if not insight or insight == "None":
        return

    try:
        with open(MEMORY_FILE, "r+") as f:
            data = json.load(f)
            
            # Avoid duplicates
            if insight not in data["insights"]:
                data["insights"].append(insight)
                
            # Keep only last 20 insights to save tokens
            if len(data["insights"]) > 20:
                data["insights"] = data["insights"][-20:]
                
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
    except Exception as e:
        print(f"⚠️ Failed to save memory: {e}")