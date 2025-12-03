import os
import re
from typing import List, Union, Any, Dict
from langchain_core.tools import tool
from core.ignore_handler import IgnoreHandler
from core.file_viewer import detect_binary_file # NEW IMPORT for binary check

# --- GLOBAL BROKER STATE ---
# This is injected by main.py at startup
BROKER = None

def set_broker(broker_instance):
    """Called by main.py to inject the TaskBroker."""
    global BROKER
    BROKER = broker_instance

# --- CORE LOGIC FUNCTIONS ---

def execute_list_files(directory: str, root_path: str) -> str:
    """
    Lists files in a directory to understand structure.
    """
    abs_root = os.path.abspath(root_path)
    target_dir = os.path.abspath(os.path.join(abs_root, directory))

    # Security Check: Ensure target_dir is within project root
    if not target_dir.startswith(abs_root):
        return "Error: Access denied (outside project root)."

    if not os.path.exists(target_dir):
        return f"Error: Directory {directory} does not exist."

    ignore_handler = IgnoreHandler(abs_root)
    items = []

    try:
        for item in os.listdir(target_dir):
            full_path = os.path.join(target_dir, item)
            # Use the aggressive ignore handler
            if not ignore_handler.is_ignored(full_path):
                if os.path.isdir(full_path):
                    items.append(f"{item}/")
                else:
                    items.append(item)
        return f"Contents of {directory}:\n" + "\n".join(sorted(items))
    except Exception as e:
        return f"Error listing directory: {e}"

def execute_safe_grep(
    patterns: Union[List[str], str],
    root_path: str,
    verbose: bool = False
) -> Dict[str, Any]: 
    """
    Searches the codebase for regex patterns, respecting ignore rules and skipping binary files.
    Returns a structured Dict used by TaskBroker.
    """
    # Ensure patterns is a list
    if isinstance(patterns, str):
        patterns = [patterns]

    abs_root = os.path.abspath(root_path)
    ignore_handler = IgnoreHandler(abs_root)

    results = [] # List of {pattern, matches, error}

    # 1. Compile Regex
    valid_patterns = []
    for p in patterns:
        try:
            if len(p.strip()) > 0:
                valid_patterns.append({
                    "raw": p,
                    "compiled": re.compile(p, re.IGNORECASE)
                })
        except re.error as e:
             results.append({"pattern": p, "matches": [], "error": str(e)})

    if not valid_patterns:
         return {"results": results, "error": "No valid patterns", "files_scanned": 0}

    # 2. Scan Files
    files_scanned = 0
    matches_by_pattern = {vp["raw"]: [] for vp in valid_patterns}

    # Pass ignore_handler to os.walk or filter dirs in place
    for root, dirs, files in os.walk(abs_root, topdown=True):
        # Filter directories in-place for os.walk to skip them
        dirs[:] = [d for d in dirs if not ignore_handler.is_ignored(os.path.join(root, d))]

        for file in files:
            full_path = os.path.join(root, file)
            # Skip ignored files
            if ignore_handler.is_ignored(full_path):
                continue
            
            # Skip binary files
            if detect_binary_file(full_path):
                continue

            files_scanned += 1
            rel_path = os.path.relpath(full_path, abs_root)

            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    for line_idx, line in enumerate(f):
                        for vp in valid_patterns:
                            if vp["compiled"].search(line):
                                clean_line = line.strip()[:150]
                                matches_by_pattern[vp["raw"]].append({
                                    "file": rel_path,
                                    "lineno": line_idx + 1,
                                    "snippet": clean_line
                                })
            except Exception: # Catch any other reading errors (e.g., permission)
                continue

    # 3. Format Results
    for vp in valid_patterns:
        results.append({
            "pattern": vp["raw"],
            "matches": matches_by_pattern[vp["raw"]],
            "error": None
        })

    return {"results": results, "files_scanned": files_scanned}

# --- TOOL WRAPPERS ---

@tool
def list_files_tool(directory: str, root_path: str) -> str:
    """Tool wrapper for listing files."""
    return execute_list_files(directory, root_path)

@tool
def safe_grep_tool(patterns: Union[List[str], str], root_path: str) -> str:
    """Tool wrapper for grepping codebase (returns string for LLM)."""
    data = execute_safe_grep(patterns, root_path)
    
    output = []
    if "error" in data and data["error"]:
        return f"Error: {data['error']}"

    for r in data.get("results", []):
        if r.get("error"):
            output.append(f"Error searching pattern '{r.get('pattern')}': {r['error']}")
            continue
        for m in r.get("matches", []):
            output.append(f"{m['file']}:{m['lineno']}: {m['snippet']}")
            
    return "\n".join(output[:100]) if output else "No matches found."