import os
import fnmatch
from typing import List

class IgnoreHandler:
    # --- AGGRESSIVE IGNORE LISTS (Fortune 500 Robustness) ---
    DEFAULT_DIR_IGNORE = [
        '.git', 'node_modules', 'venv', '__pycache__', '.pytest_cache',
        'build', 'dist', '.aws-sam', '.serverless', '.terraform',
        'cdk.out', 'target', 'vendor', # Rust/Go/CDK build
        'tmp', 'temp', 'logs',
    ]
    
    DEFAULT_FILE_EXT_IGNORE = [
        # Archives/Installers
        '.zip', '.tar', '.gz', '.rar', '.7z', '.iso', '.dmg', '.exe', '.msi',
        # Images/Media
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.ico',
        '.mp3', '.mp4', '.avi', '.mov', '.wav',
        # Documents
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        # Databases (common temp/local)
        '.db', '.sqlite', '.sqlite3',
        # Minified/Generated JS/CSS (large, not source)
        '.min.js', '.bundle.js', '.js.map', '.css.map',
        # Binary/Compiled
        '.o', '.so', '.dll', '.bin', '.class', '.pyc',
    ]

    def __init__(self, root_path: str):
        self.root_path = os.path.abspath(root_path)
        self.ignore_patterns = self._load_ignore_patterns()

    def _load_ignore_patterns(self) -> List[str]:
        patterns = []
        
        # 1. Load System Ignores (explicit project-level ignores)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        system_ignore_path = os.path.join(base_dir, 'config', 'system.ignore')
        
        if os.path.exists(system_ignore_path):
            with open(system_ignore_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        patterns.append(line)

        # 2. Load Project .gitignore (if exists)
        gitignore_path = os.path.join(self.root_path, '.gitignore')
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        patterns.append(line)
                        
        return patterns

    def is_ignored(self, file_path: str) -> bool:
        """
        Checks if a file path or directory should be ignored based on aggressive rules
        and loaded patterns.
        """
        abs_file_path = os.path.abspath(os.path.join(self.root_path, file_path))
        rel_path = os.path.relpath(abs_file_path, self.root_path)
        
        # 1. Check Default Blacklisted Directories
        for ignore_dir in self.DEFAULT_DIR_IGNORE:
            # Check if rel_path starts with or contains the blacklisted dir
            if rel_path == ignore_dir or rel_path.startswith(ignore_dir + os.sep) or f"{os.sep}{ignore_dir}{os.sep}" in rel_path:
                return True

        # 2. Check Default Blacklisted File Extensions
        ext = os.path.splitext(rel_path)[1].lower()
        if ext in self.DEFAULT_FILE_EXT_IGNORE:
            return True

        # 3. Check loaded .gitignore / system.ignore patterns
        name = os.path.basename(file_path) # Use base name for fnmatch
        for pattern in self.ignore_patterns:
            if pattern.endswith('/'): # Directory pattern
                if os.path.isdir(abs_file_path) and (fnmatch.fnmatch(name, pattern[:-1]) or fnmatch.fnmatch(rel_path, pattern[:-1])):
                    return True
            else: # File pattern
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                    return True
                
        return False
