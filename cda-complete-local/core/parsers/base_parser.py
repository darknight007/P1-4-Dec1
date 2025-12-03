"""
Base Parser Module

Provides abstract base class and interfaces for all configuration file parsers.
Follows Google's Python Style Guide and includes comprehensive error handling.

Author: Scrooge Scanner Team
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pathlib import Path
import logging

# Configure module logger
logger = logging.getLogger(__name__)


class ParsedConfig(BaseModel):
    """
    Structured representation of a parsed configuration file.
    
    This model serves as the output contract for all parsers,
    ensuring consistent data structure across different config types.
    
    Attributes:
        file_path: Absolute or relative path to the parsed file
        parser_type: Identifier for the parser that processed this file
        confidence: Confidence level of parsing accuracy (high|medium|low)
        raw_data: Parsed configuration data as nested dictionary
        error_message: Optional error description if parsing was partial
    """
    file_path: str = Field(..., description="Path to the parsed file")
    parser_type: str = Field(..., description="Type of parser used")
    confidence: str = Field(
        default="low",
        pattern=r"^(high|medium|low|unknown)$"
    )
    raw_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured configuration data"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if parsing failed or was partial"
    )
    
    class Config:
        """Pydantic model configuration"""
        extra = "forbid"  # Reject unknown fields
        validate_assignment = True  # Validate on field assignment


class BaseParser(ABC):
    """
    Abstract base class for all configuration file parsers.
    
    Implements the Template Method pattern, providing a standard
    parsing workflow with hooks for parser-specific logic.
    
    Usage:
        class MyParser(BaseParser):
            def can_parse(self, file_path: str) -> bool:
                return file_path.endswith('.myconfig')
            
            def parse(self, file_path: str) -> Optional[ParsedConfig]:
                # Implementation
                pass
    """
    
    def __init__(self, verbose: bool = False):
        """
        Initialize parser.
        
        Args:
            verbose: Enable verbose logging for debugging
        """
        self.verbose = verbose
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    def can_parse(self, file_path: str) -> bool:
        """
        Determine if this parser can handle the given file.
        
        This method should be fast and lightweight, as it's called
        for every file in the repository during scanning.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if this parser can handle the file, False otherwise
        """
        pass
    
    @abstractmethod
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse the configuration file and extract structured data.
        
        Implementations should:
        1. Validate file exists and is readable
        2. Parse content according to format specification
        3. Extract relevant cost-related information
        4. Return None if parsing fails completely
        
        Args:
            file_path: Path to the file to parse
            
        Returns:
            ParsedConfig object if successful, None if parsing failed
        """
        pass
    
    def safe_parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Wrapper around parse() with comprehensive error handling.
        
        This method provides:
        - File existence validation
        - Exception catching and logging
        - Graceful degradation
        - Performance timing (when verbose)
        
        Args:
            file_path: Path to the file to parse
            
        Returns:
            ParsedConfig object if successful, None if parsing failed
        """
        import time
        
        # Validate file path
        path_obj = Path(file_path)
        if not path_obj.exists():
            if self.verbose:
                self.logger.warning(f"File does not exist: {file_path}")
            return None
        
        if not path_obj.is_file():
            if self.verbose:
                self.logger.warning(f"Path is not a file: {file_path}")
            return None
        
        # Check if this parser can handle the file
        if not self.can_parse(file_path):
            return None
        
        # Attempt parsing with timing
        start_time = time.time() if self.verbose else 0
        
        try:
            result = self.parse(file_path)
            
            if self.verbose:
                elapsed = time.time() - start_time
                self.logger.info(
                    f"Parsed {file_path} with {self.__class__.__name__} "
                    f"in {elapsed:.3f}s"
                )
            
            return result
            
        except PermissionError as e:
            self.logger.error(f"Permission denied reading {file_path}: {e}")
            return None
            
        except UnicodeDecodeError as e:
            self.logger.warning(
                f"Encoding error in {file_path}: {e}. "
                f"File may be binary or use non-UTF-8 encoding."
            )
            return None
            
        except Exception as e:
            self.logger.error(
                f"Parser {self.__class__.__name__} failed on {file_path}: "
                f"{type(e).__name__}: {e}",
                exc_info=self.verbose
            )
            return None
    
    def _read_file_safely(self, file_path: str) -> Optional[str]:
        """
        Read file content with fallback encoding strategies.
        
        Args:
            file_path: Path to the file to read
            
        Returns:
            File content as string, or None if reading failed
        """
        encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                self.logger.error(f"Error reading {file_path}: {e}")
                return None
        
        self.logger.error(f"Could not decode {file_path} with any known encoding")
        return None


class ParserRegistry:
    """
    Registry for managing multiple parsers.
    
    Provides centralized parser discovery and execution
    with automatic fallback and priority handling.
    """
    
    def __init__(self):
        self.parsers: list[BaseParser] = []
        self.logger = logging.getLogger(f"{__name__}.ParserRegistry")
    
    def register(self, parser: BaseParser) -> None:
        """Register a parser instance."""
        self.parsers.append(parser)
        self.logger.debug(f"Registered parser: {parser.__class__.__name__}")
    
    def parse_file(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Attempt to parse file with all registered parsers.
        
        Returns result from first parser that succeeds.
        
        Args:
            file_path: Path to file to parse
            
        Returns:
            ParsedConfig from first successful parser, or None
        """
        for parser in self.parsers:
            result = parser.safe_parse(file_path)
            if result:
                return result
        return None
    
    def parse_directory(self, dir_path: str) -> list[ParsedConfig]:
        """
        Recursively parse all parseable files in directory.
        
        Args:
            dir_path: Path to directory to scan
            
        Returns:
            List of successfully parsed configurations
        """
        results = []
        dir_obj = Path(dir_path)
        
        for file_path in dir_obj.rglob('*'):
            if file_path.is_file():
                result = self.parse_file(str(file_path))
                if result:
                    results.append(result)
        
        return results
