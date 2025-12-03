"""
Python AST Parser

Extracts structural information from Python source files using the built-in AST module:
- Import statements (detect AI/cloud libraries)
- Function/class definitions
- API calls and network requests
- Decorator usage
- Async/await patterns

This is an improved version extracted from structure_parser.py with better
API call detection and cost-relevant pattern recognition.

Author: Scrooge Scanner Team
"""

import ast
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
import re
import logging

logger = logging.getLogger(__name__)


class PythonASTParser:
    """
    Parser for Python source files using AST.
    
    Focuses on cost-relevant patterns:
    - LLM API calls (OpenAI, Anthropic, etc.)
    - Cloud SDK usage (boto3, google-cloud)
    - HTTP requests
    - Async operations
    """
    
    # API call patterns to detect
    LLM_API_PATTERNS = {
        'openai': ['ChatCompletion', 'Completion', 'Embedding', 'create'],
        'anthropic': ['messages', 'completions', 'Message', 'Claude'],
        'langchain': ['LLMChain', 'ChatOpenAI', 'OpenAI', 'Anthropic'],
        'cohere': ['generate', 'embed', 'classify'],
    }
    
    CLOUD_API_PATTERNS = {
        'boto3': ['client', 'resource', 'invoke', 'put_object', 'get_object'],
        'google.cloud': ['storage', 'pubsub', 'functions', 'run'],
        'azure': ['BlobServiceClient', 'QueueClient', 'ServiceBusClient'],
    }
    
    HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'request'}
    
    def __init__(self, verbose: bool = False):
        """
        Initialize Python AST parser.
        
        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self.logger = logging.getLogger(f"{__name__}.PythonASTParser")
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a Python source file."""
        return file_path.endswith('.py')
    
    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse Python file and extract structural information.
        
        Args:
            file_path: Path to Python file
            
        Returns:
            Dictionary with extracted information:
            - file_path: Original file path
            - imports: List of import statements
            - functions: List of function definitions
            - classes: List of class definitions
            - api_calls: List of detected API calls
            - async_patterns: List of async/await usage
            - decorators: List of decorator usage
            - error: Error message if parsing failed
        """
        if not Path(file_path).exists():
            return {'file_path': file_path, 'error': 'File not found'}
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=file_path)
            
            result = {
                'file_path': file_path,
                'imports': self._extract_imports(tree),
                'functions': self._extract_functions(tree),
                'classes': self._extract_classes(tree),
                'api_calls': self._extract_api_calls(tree, source),
                'async_patterns': self._extract_async_patterns(tree),
                'decorators': self._extract_decorators(tree),
            }
            
            return result
            
        except SyntaxError as e:
            self.logger.warning(f"Syntax error in {file_path}: {e}")
            return {'file_path': file_path, 'error': f'Syntax error: {e}'}
        except Exception as e:
            self.logger.error(f"Failed to parse {file_path}: {e}")
            return {'file_path': file_path, 'error': str(e)}
    
    def _extract_imports(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """
        Extract import statements.
        
        Returns list of dicts with:
        - module: Module name
        - names: Imported names
        - is_llm: Whether this is an LLM library
        - is_cloud: Whether this is a cloud SDK
        """
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        'module': alias.name,
                        'alias': alias.asname,
                        'is_llm': self._is_llm_import(alias.name),
                        'is_cloud': self._is_cloud_import(alias.name),
                    })
            
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    imports.append({
                        'module': module,
                        'name': alias.name,
                        'alias': alias.asname,
                        'is_llm': self._is_llm_import(module),
                        'is_cloud': self._is_cloud_import(module),
                    })
        
        return imports
    
    def _extract_functions(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """
        Extract function definitions.
        
        Returns list of dicts with:
        - name: Function name
        - args: List of argument names
        - is_async: Whether function is async
        - decorators: List of decorator names
        - lineno: Line number
        """
        functions = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                functions.append({
                    'name': node.name,
                    'args': [arg.arg for arg in node.args.args],
                    'is_async': isinstance(node, ast.AsyncFunctionDef),
                    'decorators': [self._get_decorator_name(d) for d in node.decorator_list],
                    'lineno': node.lineno,
                })
        
        return functions
    
    def _extract_classes(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """
        Extract class definitions.
        
        Returns list of dicts with:
        - name: Class name
        - bases: Base class names
        - methods: Number of methods
        - lineno: Line number
        """
        classes = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Count methods
                method_count = sum(
                    1 for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                
                classes.append({
                    'name': node.name,
                    'bases': [self._get_name(base) for base in node.bases],
                    'methods': method_count,
                    'lineno': node.lineno,
                })
        
        return classes
    
    def _extract_api_calls(self, tree: ast.AST, source: str) -> List[Dict[str, Any]]:
        """
        Extract API calls and network requests.
        
        Detects:
        - LLM API calls (openai.ChatCompletion.create())
        - Cloud SDK calls (boto3.client('s3'))
        - HTTP requests (requests.get(), httpx.post())
        """
        api_calls = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_info = self._analyze_call(node, source)
                if call_info:
                    api_calls.append(call_info)
        
        return api_calls
    
    def _analyze_call(self, node: ast.Call, source: str) -> Optional[Dict[str, Any]]:
        """
        Analyze a function call to determine if it's an API call.
        
        Returns dict with:
        - type: 'llm', 'cloud', 'http', 'other'
        - target: Function/method being called
        - lineno: Line number
        """
        target = self._get_call_target(node)
        
        if not target:
            return None
        
        call_type = 'other'
        
        # Check for LLM API calls
        for lib, patterns in self.LLM_API_PATTERNS.items():
            if lib in target.lower():
                for pattern in patterns:
                    if pattern.lower() in target.lower():
                        call_type = 'llm'
                        break
        
        # Check for cloud API calls
        if call_type == 'other':
            for lib, patterns in self.CLOUD_API_PATTERNS.items():
                if lib.replace('.', '') in target.replace('.', '').lower():
                    for pattern in patterns:
                        if pattern.lower() in target.lower():
                            call_type = 'cloud'
                            break
        
        # Check for HTTP calls
        if call_type == 'other':
            for method in self.HTTP_METHODS:
                if target.lower().endswith(f'.{method}') or target.lower() == method:
                    call_type = 'http'
                    break
        
        # Only return if it's a cost-relevant call
        if call_type != 'other':
            return {
                'type': call_type,
                'target': target,
                'lineno': node.lineno,
            }
        
        return None
    
    def _get_call_target(self, node: ast.Call) -> Optional[str]:
        """Get the full name of the function being called."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return '.'.join(reversed(parts))
        return None
    
    def _extract_async_patterns(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """
        Extract async/await patterns.
        
        Async patterns can indicate concurrent API calls which affect cost scaling.
        """
        async_patterns = []
        
        for node in ast.walk(tree):
            # Async function definitions
            if isinstance(node, ast.AsyncFunctionDef):
                async_patterns.append({
                    'type': 'async_function',
                    'name': node.name,
                    'lineno': node.lineno,
                })
            
            # Await expressions
            elif isinstance(node, ast.Await):
                async_patterns.append({
                    'type': 'await',
                    'lineno': node.lineno,
                })
            
            # Async with statements
            elif isinstance(node, ast.AsyncWith):
                async_patterns.append({
                    'type': 'async_with',
                    'lineno': node.lineno,
                })
            
            # Async for loops
            elif isinstance(node, ast.AsyncFor):
                async_patterns.append({
                    'type': 'async_for',
                    'lineno': node.lineno,
                })
        
        return async_patterns
    
    def _extract_decorators(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """
        Extract decorator usage.
        
        Decorators like @app.route, @celery.task indicate API endpoints or background jobs.
        """
        decorators = []
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    decorator_name = self._get_decorator_name(decorator)
                    if decorator_name:
                        decorators.append({
                            'decorator': decorator_name,
                            'function': node.name,
                            'lineno': node.lineno,
                        })
        
        return decorators
    
    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name from AST node."""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return self._get_name(decorator)
        elif isinstance(decorator, ast.Call):
            return self._get_name(decorator.func)
        return ''
    
    def _get_name(self, node: ast.expr) -> str:
        """Get full name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        return ''
    
    def _is_llm_import(self, module: str) -> bool:
        """Check if module is an LLM library."""
        llm_keywords = ['openai', 'anthropic', 'langchain', 'cohere', 'transformers']
        return any(kw in module.lower() for kw in llm_keywords)
    
    def _is_cloud_import(self, module: str) -> bool:
        """Check if module is a cloud SDK."""
        cloud_keywords = ['boto3', 'google.cloud', 'azure', 'aws']
        return any(kw in module.lower() for kw in cloud_keywords)


# Convenience function
def parse_python_file(file_path: str, verbose: bool = False) -> Dict[str, Any]:
    """
    Convenience function to parse a Python file.
    
    Args:
        file_path: Path to Python file
        verbose: Enable verbose logging
        
    Returns:
        Dictionary with parsed information
    """
    parser = PythonASTParser(verbose=verbose)
    return parser.parse_file(file_path)
