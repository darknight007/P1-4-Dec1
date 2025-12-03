"""
Token Analyzer Module

Provides accurate token counting for LLM cost estimation using tiktoken.
Analyzes prompt files, code comments, and configuration to estimate
actual token usage rather than relying on LLM guesses.

Features:
- Multi-model token counting (GPT-4, GPT-3.5, Claude, etc.)
- Prompt file detection and analysis
- Placeholder/variable expansion estimation
- Batch analysis for entire repositories

Supports:
- OpenAI models (via tiktoken)
- Anthropic models (via estimated encoding)
- Generic fallback encoding

Author: Scrooge Scanner Team
"""

import os
import re
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# Try to import tiktoken, but make it optional
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning(
        "tiktoken not installed. Token counting will use estimates. "
        "Install with: pip install tiktoken"
    )


@dataclass
class PromptAnalysis:
    """
    Analysis result for a single prompt file.
    
    Attributes:
        file_path: Path to the analyzed file
        base_tokens: Token count for static content
        placeholders: List of detected placeholder/variable names
        estimated_expansion_factor: Multiplier for dynamic content
        estimated_total_tokens: base_tokens * expansion_factor
        model: Model used for token counting
        encoding_name: Tiktoken encoding used
        error: Error message if analysis failed
    """
    file_path: str
    base_tokens: int = 0
    placeholders: List[str] = field(default_factory=list)
    estimated_expansion_factor: float = 1.0
    estimated_total_tokens: int = 0
    model: str = "gpt-4"
    encoding_name: str = "cl100k_base"
    error: Optional[str] = None
    
    def __post_init__(self):
        """Calculate estimated total tokens if not provided."""
        if self.estimated_total_tokens == 0 and self.base_tokens > 0:
            self.estimated_total_tokens = int(
                self.base_tokens * self.estimated_expansion_factor
            )


class TokenAnalyzer:
    """
    Analyzer for calculating accurate token counts.
    
    Uses tiktoken for OpenAI models and provides estimates for others.
    """
    
    # Model to encoding mapping
    MODEL_ENCODINGS = {
        'gpt-4': 'cl100k_base',
        'gpt-4-32k': 'cl100k_base',
        'gpt-4-turbo': 'cl100k_base',
        'gpt-4-turbo-preview': 'cl100k_base',
        'gpt-3.5-turbo': 'cl100k_base',
        'gpt-3.5-turbo-16k': 'cl100k_base',
        'text-davinci-003': 'p50k_base',
        'text-davinci-002': 'p50k_base',
        'claude-3': 'cl100k_base',  # Estimate using GPT-4 encoding
        'claude-2': 'cl100k_base',
        'claude-instant': 'cl100k_base',
    }
    
    # Patterns that indicate prompt files
    PROMPT_FILE_PATTERNS = [
        'prompt', 'template', 'system_message', 'system_prompt',
        'instruction', 'context'
    ]
    
    # File extensions to check for prompts
    PROMPT_FILE_EXTENSIONS = ['.txt', '.md', '.prompt', '.py', '.js', '.ts']
    
    def __init__(self, verbose: bool = False):
        """
        Initialize token analyzer.
        
        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self.logger = logging.getLogger(f"{__name__}.TokenAnalyzer")
        self.encoders: Dict[str, Any] = {}
        
        if not TIKTOKEN_AVAILABLE:
            self.logger.warning(
                "Running without tiktoken. Token counts will be estimates."
            )
    
    def get_encoder(self, model: str):
        """
        Get or create tiktoken encoder for model.
        
        Args:
            model: Model name (e.g., "gpt-4", "gpt-3.5-turbo")
            
        Returns:
            Tiktoken encoder or None if tiktoken unavailable
        """
        if not TIKTOKEN_AVAILABLE:
            return None
        
        # Normalize model name (remove version suffixes)
        model_base = model.lower().split('-')[0:2]
        model_key = '-'.join(model_base)
        
        if model_key not in self.encoders:
            try:
                # Try to get encoding by model name
                self.encoders[model_key] = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to encoding name
                encoding_name = self.MODEL_ENCODINGS.get(
                    model_key,
                    'cl100k_base'  # Default to GPT-4 encoding
                )
                try:
                    self.encoders[model_key] = tiktoken.get_encoding(encoding_name)
                except Exception as e:
                    self.logger.error(f"Failed to load encoding {encoding_name}: {e}")
                    return None
        
        return self.encoders[model_key]
    
    def count_tokens(self, text: str, model: str = "gpt-4") -> int:
        """
        Count tokens in text for given model.
        
        Args:
            text: Text to count tokens for
            model: Model name for tokenization
            
        Returns:
            Token count (estimated if tiktoken unavailable)
        """
        if not text:
            return 0
        
        encoder = self.get_encoder(model)
        
        if encoder:
            try:
                return len(encoder.encode(text))
            except Exception as e:
                self.logger.warning(f"Encoding error for model {model}: {e}")
        
        # Fallback: estimate ~4 chars per token (rough approximation)
        return len(text) // 4
    
    def analyze_prompt_file(
        self,
        file_path: str,
        model: str = "gpt-4"
    ) -> PromptAnalysis:
        """
        Analyze a prompt template file.
        
        Detects placeholders and estimates expansion factor.
        
        Args:
            file_path: Path to prompt file
            model: Model to use for token counting
            
        Returns:
            PromptAnalysis object with token counts and metadata
        """
        if not os.path.exists(file_path):
            return PromptAnalysis(
                file_path=file_path,
                error="File not found"
            )
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            return PromptAnalysis(
                file_path=file_path,
                error=f"Failed to read file: {e}"
            )
        
        # Count base tokens
        base_tokens = self.count_tokens(content, model)
        
        # Detect placeholders
        placeholders = self._detect_placeholders(content)
        
        # Estimate expansion factor
        expansion_factor = self._estimate_expansion_factor(content, placeholders)
        
        # Get encoding name
        encoder = self.get_encoder(model)
        encoding_name = encoder.name if encoder else "estimated"
        
        return PromptAnalysis(
            file_path=file_path,
            base_tokens=base_tokens,
            placeholders=placeholders,
            estimated_expansion_factor=expansion_factor,
            model=model,
            encoding_name=encoding_name
        )
    
    def _detect_placeholders(self, content: str) -> List[str]:
        """
        Detect placeholder variables in prompt template.
        
        Supports multiple placeholder formats:
        - {variable}
        - {{variable}}
        - ${variable}
        - $variable
        - <variable>
        - [variable]
        
        Args:
            content: Prompt template content
            
        Returns:
            List of unique placeholder names
        """
        placeholders = set()
        
        # Pattern 1: {variable} or {{variable}}
        placeholders.update(re.findall(r'\{+([a-zA-Z_][a-zA-Z0-9_]*)\}+', content))
        
        # Pattern 2: ${variable}
        placeholders.update(re.findall(r'\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}', content))
        
        # Pattern 3: $variable (shell-style)
        placeholders.update(re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)\b', content))
        
        # Pattern 4: <variable> (XML-style)
        placeholders.update(re.findall(r'<([a-zA-Z_][a-zA-Z0-9_]*)>', content))
        
        # Pattern 5: [variable] (bracket-style)
        placeholders.update(re.findall(r'\[([a-zA-Z_][a-zA-Z0-9_]*)\]', content))
        
        return sorted(list(placeholders))
    
    def _estimate_expansion_factor(
        self,
        content: str,
        placeholders: List[str]
    ) -> float:
        """
        Estimate how much the prompt will expand with real data.
        
        Uses heuristics:
        - Few placeholders (1-3): 1.2-1.5x expansion
        - Medium placeholders (4-8): 1.5-2.0x expansion
        - Many placeholders (9+): 2.0-3.0x expansion
        - Context/document placeholders: higher expansion
        
        Args:
            content: Prompt template content
            placeholders: List of detected placeholders
            
        Returns:
            Estimated expansion factor (1.0 = no expansion)
        """
        num_placeholders = len(placeholders)
        
        if num_placeholders == 0:
            return 1.0
        
        # Base expansion factor
        if num_placeholders <= 3:
            base_factor = 1.3
        elif num_placeholders <= 8:
            base_factor = 1.7
        else:
            base_factor = 2.5
        
        # Check for high-expansion placeholder names
        high_expansion_keywords = [
            'context', 'document', 'content', 'text', 'data',
            'history', 'conversation', 'examples', 'results'
        ]
        
        for placeholder in placeholders:
            if any(kw in placeholder.lower() for kw in high_expansion_keywords):
                base_factor *= 1.3
                break  # Only apply once
        
        # Cap at 5x to avoid unrealistic estimates
        return min(base_factor, 5.0)
    
    def scan_repo_for_prompts(
        self,
        repo_path: str,
        model: str = "gpt-4"
    ) -> List[PromptAnalysis]:
        """
        Find and analyze all prompt files in repository.
        
        Args:
            repo_path: Path to repository root
            model: Model to use for token counting
            
        Returns:
            List of PromptAnalysis objects
        """
        results = []
        repo_path_obj = Path(repo_path)
        
        if not repo_path_obj.exists():
            self.logger.error(f"Repository path does not exist: {repo_path}")
            return results
        
        # Walk through repository
        for file_path in repo_path_obj.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Check if file looks like a prompt
            if self._is_prompt_file(str(file_path)):
                analysis = self.analyze_prompt_file(str(file_path), model)
                
                # Only include if successfully analyzed
                if analysis.error is None and analysis.base_tokens > 0:
                    results.append(analysis)
                    
                    if self.verbose:
                        self.logger.info(
                            f"Analyzed prompt: {file_path.name} "
                            f"({analysis.base_tokens} base tokens, "
                            f"{len(analysis.placeholders)} placeholders)"
                        )
        
        return results
    
    def _is_prompt_file(self, file_path: str) -> bool:
        """
        Check if file looks like a prompt template.
        
        Args:
            file_path: Path to file
            
        Returns:
            True if file appears to be a prompt
        """
        file_name = Path(file_path).name.lower()
        file_stem = Path(file_path).stem.lower()
        parent_dir = Path(file_path).parent.name.lower()
        
        # Check file extension
        if not any(file_name.endswith(ext) for ext in self.PROMPT_FILE_EXTENSIONS):
            return False
        
        # Check if filename or directory contains prompt keywords
        for pattern in self.PROMPT_FILE_PATTERNS:
            if pattern in file_name or pattern in file_stem or pattern in parent_dir:
                return True
        
        return False
    
    def generate_summary(self, analyses: List[PromptAnalysis]) -> Dict[str, Any]:
        """
        Generate summary statistics for multiple prompt analyses.
        
        Args:
            analyses: List of PromptAnalysis objects
            
        Returns:
            Dictionary with summary statistics
        """
        if not analyses:
            return {
                'total_files': 0,
                'total_base_tokens': 0,
                'total_estimated_tokens': 0,
                'avg_expansion_factor': 0.0,
                'files': []
            }
        
        total_base = sum(a.base_tokens for a in analyses)
        total_estimated = sum(a.estimated_total_tokens for a in analyses)
        avg_expansion = sum(a.estimated_expansion_factor for a in analyses) / len(analyses)
        
        return {
            'total_files': len(analyses),
            'total_base_tokens': total_base,
            'total_estimated_tokens': total_estimated,
            'avg_expansion_factor': round(avg_expansion, 2),
            'files': [
                {
                    'path': a.file_path,
                    'base_tokens': a.base_tokens,
                    'estimated_tokens': a.estimated_total_tokens,
                    'placeholders': len(a.placeholders)
                }
                for a in analyses
            ]
        }


# Convenience functions for standalone usage
def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Convenience function to count tokens.
    
    Args:
        text: Text to count
        model: Model name
        
    Returns:
        Token count
    """
    analyzer = TokenAnalyzer()
    return analyzer.count_tokens(text, model)


def analyze_prompt(file_path: str, model: str = "gpt-4") -> PromptAnalysis:
    """
    Convenience function to analyze a prompt file.
    
    Args:
        file_path: Path to prompt file
        model: Model name
        
    Returns:
        PromptAnalysis object
    """
    analyzer = TokenAnalyzer()
    return analyzer.analyze_prompt_file(file_path, model)
