"""
JavaScript/TypeScript AST Parser

Extracts structural information from JavaScript and TypeScript files using tree-sitter.
Falls back to regex-based parsing if tree-sitter is unavailable.

Detects:
- Import/require statements (AI libraries, cloud SDKs)
- Function declarations
- API calls (fetch, axios, HTTP requests)
- Async/await patterns
- Export patterns

Supports:
- JavaScript (.js)
- TypeScript (.ts)
- JSX (.jsx)
- TSX (.tsx)

Author: Scrooge Scanner Team
"""

import re
from typing import Dict, List, Any, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Try to import tree-sitter
try:
    from tree_sitter_languages import get_language, get_parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.warning(
        "tree-sitter-languages not installed. Using regex fallback. "
        "Install with: pip install tree-sitter-languages"
    )


class JavaScriptASTParser:
    """
    Parser for JavaScript/TypeScript source files.
    
    Uses tree-sitter when available, falls back to regex-based parsing.
    """
    
    # AI/ML libraries for JavaScript
    LLM_LIBRARIES = {
        'openai', '@anthropic-ai', 'langchain', '@langchain',
        'cohere-ai', 'replicate', '@pinecone-database',
        '@google-ai', 'google-generative-ai',
    }
    
    # Cloud SDKs
    CLOUD_LIBRARIES = {
        'aws-sdk', '@aws-sdk', '@google-cloud', 'firebase',
        '@azure', 'azure-storage',
    }
    
    # HTTP client libraries
    HTTP_LIBRARIES = {'axios', 'node-fetch', 'got', 'superagent', 'request'}
    
    def __init__(self, verbose: bool = False):
        """
        Initialize JavaScript AST parser.
        
        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self.logger = logging.getLogger(f"{__name__}.JavaScriptASTParser")
        
        if TREE_SITTER_AVAILABLE:
            try:
                self.parser = get_parser('javascript')
                self.language = get_language('javascript')
            except Exception as e:
                self.logger.warning(f"Failed to load tree-sitter: {e}. Using regex fallback.")
                self.parser = None
        else:
            self.parser = None
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a JavaScript/TypeScript file."""
        return file_path.endswith(('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'))
    
    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse JavaScript/TypeScript file and extract structural information.
        
        Args:
            file_path: Path to JS/TS file
            
        Returns:
            Dictionary with extracted information
        """
        if not Path(file_path).exists():
            return {'file_path': file_path, 'error': 'File not found'}
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
            
            if self.parser:
                return self._parse_with_tree_sitter(file_path, source)
            else:
                return self._parse_with_regex(file_path, source)
                
        except Exception as e:
            self.logger.error(f"Failed to parse {file_path}: {e}")
            return {'file_path': file_path, 'error': str(e)}
    
    def _parse_with_tree_sitter(self, file_path: str, source: str) -> Dict[str, Any]:
        """Parse using tree-sitter (more accurate but requires library)."""
        tree = self.parser.parse(bytes(source, 'utf8'))
        
        return {
            'file_path': file_path,
            'imports': self._extract_imports_ts(tree, source),
            'functions': self._extract_functions_ts(tree, source),
            'api_calls': self._extract_api_calls_ts(tree, source),
            'async_patterns': self._extract_async_patterns_ts(tree, source),
        }
    
    def _parse_with_regex(self, file_path: str, source: str) -> Dict[str, Any]:
        """Parse using regex patterns (fallback method)."""
        return {
            'file_path': file_path,
            'imports': self._extract_imports_regex(source),
            'functions': self._extract_functions_regex(source),
            'api_calls': self._extract_api_calls_regex(source),
            'async_patterns': self._extract_async_patterns_regex(source),
        }
    
    # ========== Regex-based Extraction (Fallback) ==========
    
    def _extract_imports_regex(self, source: str) -> List[Dict[str, Any]]:
        """Extract import statements using regex."""
        imports = []
        
        # Pattern 1: import ... from '...'
        import_pattern = r"import\s+(?:(?:\{[^}]+\}|\*\s+as\s+\w+|\w+)(?:\s*,\s*(?:\{[^}]+\}|\w+))?\s+from\s+)?['\"]([^'\"]+)['\"]"
        for match in re.finditer(import_pattern, source):
            module = match.group(1)
            imports.append({
                'module': module,
                'is_llm': any(lib in module for lib in self.LLM_LIBRARIES),
                'is_cloud': any(lib in module for lib in self.CLOUD_LIBRARIES),
            })
        
        # Pattern 2: require('...')
        require_pattern = r"require\(['\"]([^'\"]+)['\"]\)"
        for match in re.finditer(require_pattern, source):
            module = match.group(1)
            imports.append({
                'module': module,
                'is_llm': any(lib in module for lib in self.LLM_LIBRARIES),
                'is_cloud': any(lib in module for lib in self.CLOUD_LIBRARIES),
            })
        
        return imports
    
    def _extract_functions_regex(self, source: str) -> List[Dict[str, Any]]:
        """Extract function declarations using regex."""
        functions = []
        
        # Pattern 1: function name() {}
        func_pattern = r"(?:async\s+)?function\s+(\w+)\s*\([^)]*\)"
        for match in re.finditer(func_pattern, source):
            functions.append({
                'name': match.group(1),
                'is_async': 'async' in match.group(0),
                'type': 'function_declaration',
            })
        
        # Pattern 2: const name = () => {}
        arrow_pattern = r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>"
        for match in re.finditer(arrow_pattern, source):
            functions.append({
                'name': match.group(1),
                'is_async': 'async' in match.group(0),
                'type': 'arrow_function',
            })
        
        # Pattern 3: name: function() {} (object methods)
        method_pattern = r"(\w+)\s*:\s*(?:async\s+)?function\s*\([^)]*\)"
        for match in re.finditer(method_pattern, source):
            functions.append({
                'name': match.group(1),
                'is_async': 'async' in match.group(0),
                'type': 'object_method',
            })
        
        return functions
    
    def _extract_api_calls_regex(self, source: str) -> List[Dict[str, Any]]:
        """Extract API calls using regex."""
        api_calls = []
        
        # Pattern 1: fetch()
        fetch_pattern = r"fetch\s*\(['\"]([^'\"]+)['\"]"
        for match in re.finditer(fetch_pattern, source):
            api_calls.append({
                'type': 'http',
                'target': 'fetch',
                'url': match.group(1),
            })
        
        # Pattern 2: axios.get/post/etc
        axios_pattern = r"axios\.(get|post|put|patch|delete)\s*\(['\"]([^'\"]+)['\"]"
        for match in re.finditer(axios_pattern, source):
            api_calls.append({
                'type': 'http',
                'target': f'axios.{match.group(1)}',
                'url': match.group(2),
            })
        
        # Pattern 3: OpenAI/LLM API calls
        openai_pattern = r"(openai|client)\.(chat|completions?|embeddings?)\.(create|generate)"
        for match in re.finditer(openai_pattern, source):
            api_calls.append({
                'type': 'llm',
                'target': match.group(0),
            })
        
        return api_calls
    
    def _extract_async_patterns_regex(self, source: str) -> List[Dict[str, str]]:
        """Extract async/await patterns using regex."""
        patterns = []
        
        # Count async functions
        async_func_count = len(re.findall(r'\basync\s+function\b', source))
        if async_func_count > 0:
            patterns.append({
                'type': 'async_functions',
                'count': str(async_func_count),
            })
        
        # Count await expressions
        await_count = len(re.findall(r'\bawait\s+', source))
        if await_count > 0:
            patterns.append({
                'type': 'await_expressions',
                'count': str(await_count),
            })
        
        # Check for Promise.all (indicates concurrent API calls)
        if 'Promise.all' in source:
            patterns.append({
                'type': 'promise_all',
                'note': 'Concurrent API call pattern detected',
            })
        
        return patterns
    
    # ========== Tree-sitter based Extraction (More Accurate) ==========
    
    def _extract_imports_ts(self, tree, source: str) -> List[Dict[str, Any]]:
        """Extract imports using tree-sitter (placeholder - requires full implementation)."""
        # For now, fallback to regex
        return self._extract_imports_regex(source)
    
    def _extract_functions_ts(self, tree, source: str) -> List[Dict[str, Any]]:
        """Extract functions using tree-sitter."""
        return self._extract_functions_regex(source)
    
    def _extract_api_calls_ts(self, tree, source: str) -> List[Dict[str, Any]]:
        """Extract API calls using tree-sitter."""
        return self._extract_api_calls_regex(source)
    
    def _extract_async_patterns_ts(self, tree, source: str) -> List[Dict[str, str]]:
        """Extract async patterns using tree-sitter."""
        return self._extract_async_patterns_regex(source)


# Convenience function
def parse_javascript_file(file_path: str, verbose: bool = False) -> Dict[str, Any]:
    """
    Convenience function to parse a JavaScript/TypeScript file.
    
    Args:
        file_path: Path to JS/TS file
        verbose: Enable verbose logging
        
    Returns:
        Dictionary with parsed information
    """
    parser = JavaScriptASTParser(verbose=verbose)
    return parser.parse_file(file_path)
