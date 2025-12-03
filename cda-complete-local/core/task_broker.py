# core/task_broker.py

import os
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Set

# Import the actual logic functions
from agent.tools.search import execute_safe_grep, execute_list_files

class SharedCache:
    """Simple in-memory cache."""
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value

class TaskBroker:
    """
    Centralized broker for running file operations.
    Handles caching, execution, and 'Bouncer' logic (visited paths).
    """
    def __init__(self, max_workers: int = 4, repo_root: str = "."):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.repo_root = os.path.abspath(repo_root)
        self.cache = SharedCache()
        
        # --- NEW: The Bouncer Memory ---
        # Stores normalized paths of directories we have already listed.
        self.visited_dirs: Set[str] = set()

    def is_dir_visited(self, path: str) -> bool:
        """Checks if a directory has already been scanned."""
        # Normalize: remove trailing slash, resolve . and ..
        # We use relpath to keep it simple: "lib" == "./lib"
        try:
            abs_path = os.path.abspath(os.path.join(self.repo_root, path))
            rel_path = os.path.relpath(abs_path, self.repo_root)
            return rel_path in self.visited_dirs
        except ValueError:
            return False

    def mark_dir_visited(self, path: str):
        """Marks a directory as scanned."""
        try:
            abs_path = os.path.abspath(os.path.join(self.repo_root, path))
            rel_path = os.path.relpath(abs_path, self.repo_root)
            self.visited_dirs.add(rel_path)
        except ValueError:
            pass

    def _task_key(self, task_type: str, payload: Dict[str, Any]) -> str:
        """Generates a cache key."""
        base = json.dumps({"type": task_type, "payload": payload}, sort_keys=True)
        return hashlib.md5(base.encode()).hexdigest()

    def submit(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submits a task (grep/list) and returns the result (cached if available).
        """
        key = self._task_key(task_type, payload)

        # Check Cache
        cached = self.cache.get(key)
        if cached:
            return cached

        # Execute
        if task_type == "grep":
            patterns = payload.get("patterns", [])
            # Grep is idempotent, no visited check needed
            result = execute_safe_grep(patterns, self.repo_root)

        elif task_type == "list_files":
            directory = payload.get("directory", ".")
            # Note: The "Bouncer" check happens in the tool wrapper, 
            # but we could double check here if needed.
            # For now, we just execute.
            raw_text = execute_list_files(directory, self.repo_root)
            result = {"files": raw_text.splitlines()}

        else:
            result = {"error": f"Unknown task type: {task_type}"}

        # Cache and Return
        self.cache.set(key, result)
        return result