import ast
import os
from typing import List

def get_file_skeleton(file_path: str) -> str:
    """
    Parses a Python file and returns a simplified 'Skeleton' string
    showing Imports, Classes, Functions, and Global Assignments.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        
        tree = ast.parse(source)
        lines = []

        for node in ast.iter_child_nodes(tree):
            # 1. Capture Imports
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
                lines.append(f"IMPORT: {', '.join(names)}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module if node.module else "."
                names = [n.name for n in node.names]
                lines.append(f"FROM {module} IMPORT {', '.join(names)}")

            # 2. Capture Classes & their methods
            elif isinstance(node, ast.ClassDef):
                bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                base_str = f"({', '.join(bases)})" if bases else ""
                lines.append(f"CLASS {node.name}{base_str}:")
                
                # Inspect Class Body for methods
                for subitem in node.body:
                    if isinstance(subitem, ast.FunctionDef):
                        args = [a.arg for a in subitem.args.args]
                        if 'self' in args: args.remove('self')
                        lines.append(f"  METHOD {subitem.name}({', '.join(args)})")
            
            # 3. Capture Global Functions
            elif isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                lines.append(f"FUNCTION {node.name}({', '.join(args)})")

            # 4. Capture Global Assignments (Good for finding CONSTANTS or CONFIG)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # Only capture if value is simple (number, string, boolean)
                        if isinstance(node.value, (ast.Constant, ast.Str, ast.Num)):
                            lines.append(f"VAR {target.id} = ...")

    except SyntaxError:
        return "  [Syntax Error parsing file]"
    except Exception as e:
        return f"  [Error parsing file: {str(e)}]"

    return "\n".join(lines)

def generate_project_structure(repo_path: str, priority_files: List[str]) -> str:
    """
    Generates a combined skeleton for all relevant Python files in the priority list
    or root directory.
    """
    output = ["=== PROJECT STRUCTURE MAP ==="]
    
    # If priority files exist, process them first
    processed_files = set()
    
    for rel_path in priority_files:
        if rel_path.endswith(".py"):
            full_path = os.path.join(repo_path, rel_path)
            if os.path.exists(full_path):
                output.append(f"\nFILE: {rel_path}")
                output.append(get_file_skeleton(full_path))
                processed_files.add(rel_path)

    # Also scan top-level python files if not already processed
    # to ensure we capture entry points like main.py
    try:
        for f in os.listdir(repo_path):
            if f.endswith(".py") and f not in processed_files:
                output.append(f"\nFILE: {f}")
                output.append(get_file_skeleton(os.path.join(repo_path, f)))
    except OSError:
        pass

    return "\n".join(output)