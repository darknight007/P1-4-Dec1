"""
Parser Registry and Exports

Central registry for all configuration parsers.
Provides easy access to all parsers and utility functions.

Usage:
    from core.parsers import get_all_parsers, parse_file
    
    # Get all parsers
    parsers = get_all_parsers()
    
    # Parse a single file (auto-selects parser)
    result = parse_file('/path/to/Dockerfile')

Author: Scrooge Scanner Team
"""

from typing import List, Optional, Dict, Any
import logging

# Import base classes
from core.parsers.base_parser import (
    BaseParser,
    ParsedConfig,
    ParserRegistry
)

# Import all concrete parsers
from core.parsers.dockerfile_parser import DockerfileParser
from core.parsers.serverless_parser import ServerlessParser
from core.parsers.docker_compose_parser import DockerComposeParser
from core.parsers.terraform_parser import TerraformParser
from core.parsers.requirements_parser import RequirementsParser
from core.parsers.package_json_parser import PackageJsonParser

logger = logging.getLogger(__name__)


# Global parser registry instance
_global_registry: Optional[ParserRegistry] = None


def get_registry() -> ParserRegistry:
    """
    Get or create the global parser registry.
    
    Returns:
        ParserRegistry instance with all parsers registered
    """
    global _global_registry
    
    if _global_registry is None:
        _global_registry = ParserRegistry()
        
        # Register all parsers
        _global_registry.register(DockerfileParser())
        _global_registry.register(ServerlessParser())
        _global_registry.register(DockerComposeParser())
        _global_registry.register(TerraformParser())
        _global_registry.register(RequirementsParser())
        _global_registry.register(PackageJsonParser())
        
        logger.debug("Initialized global parser registry with 6 parsers")
    
    return _global_registry


def get_all_parsers(verbose: bool = False) -> List[BaseParser]:
    """
    Get instances of all available parsers.
    
    Args:
        verbose: Enable verbose logging for parsers
        
    Returns:
        List of parser instances
    """
    return [
        DockerfileParser(verbose=verbose),
        ServerlessParser(verbose=verbose),
        DockerComposeParser(verbose=verbose),
        TerraformParser(verbose=verbose),
        RequirementsParser(verbose=verbose),
        PackageJsonParser(verbose=verbose),
    ]


def parse_file(
    file_path: str,
    verbose: bool = False
) -> Optional[ParsedConfig]:
    """
    Parse a file using the appropriate parser.
    
    Automatically selects the correct parser based on file characteristics.
    
    Args:
        file_path: Path to file to parse
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object if parsing succeeded, None otherwise
    """
    registry = get_registry()
    return registry.parse_file(file_path)


def parse_directory(
    dir_path: str,
    verbose: bool = False
) -> List[ParsedConfig]:
    """
    Parse all parseable files in a directory recursively.
    
    Args:
        dir_path: Path to directory to scan
        verbose: Enable verbose logging
        
    Returns:
        List of ParsedConfig objects for successfully parsed files
    """
    registry = get_registry()
    return registry.parse_directory(dir_path)


def get_parser_for_file(file_path: str) -> Optional[BaseParser]:
    """
    Get the appropriate parser for a file without parsing it.
    
    Useful for checking if a file can be parsed.
    
    Args:
        file_path: Path to file
        
    Returns:
        Parser instance if file can be parsed, None otherwise
    """
    parsers = get_all_parsers()
    
    for parser in parsers:
        if parser.can_parse(file_path):
            return parser
    
    return None


def get_supported_file_types() -> Dict[str, str]:
    """
    Get a mapping of supported file types to parser names.
    
    Returns:
        Dictionary mapping file patterns to parser names
    """
    return {
        'Dockerfile': 'DockerfileParser',
        'serverless.yml': 'ServerlessParser',
        'docker-compose.yml': 'DockerComposeParser',
        '*.tf': 'TerraformParser',
        'requirements.txt': 'RequirementsParser',
        'package.json': 'PackageJsonParser',
    }


# Export all public APIs
__all__ = [
    # Base classes
    'BaseParser',
    'ParsedConfig',
    'ParserRegistry',
    
    # Concrete parsers
    'DockerfileParser',
    'ServerlessParser',
    'DockerComposeParser',
    'TerraformParser',
    'RequirementsParser',
    'PackageJsonParser',
    
    # Utility functions
    'get_registry',
    'get_all_parsers',
    'parse_file',
    'parse_directory',
    'get_parser_for_file',
    'get_supported_file_types',
]


# Version info
__version__ = '1.0.0'


# Module-level logging configuration
def configure_logging(level: int = logging.INFO):
    """
    Configure logging for the parsers module.
    
    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO)
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Set level for all parser loggers
    for parser_name in [
        'core.parsers.dockerfile_parser',
        'core.parsers.serverless_parser',
        'core.parsers.docker_compose_parser',
        'core.parsers.terraform_parser',
        'core.parsers.requirements_parser',
        'core.parsers.package_json_parser',
    ]:
        logging.getLogger(parser_name).setLevel(level)
