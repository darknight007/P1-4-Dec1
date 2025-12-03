"""
Serverless Framework Parser

Extracts cost-relevant configuration from serverless.yml files:
- Function memory allocations (primary Lambda cost driver)
- Timeout settings (affects max cost per invocation)
- Event triggers (helps estimate invocation volume)
- VPC configuration (affects cold start time and cost)
- Layer usage (affects package size)

Supports:
- Serverless Framework v2 and v3
- AWS, GCP, Azure providers
- Variable interpolation detection

Author: Scrooge Scanner Team
"""

import yaml
from typing import Optional, Dict, List, Any
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import (
    ServerlessConfig, 
    ServerlessFunction,
    CloudProvider
)
import logging
import re

logger = logging.getLogger(__name__)


class ServerlessParser(BaseParser):
    """
    Parser for serverless.yml configuration files.
    
    Extracts function-level cost parameters and provider settings.
    """
    
    # Default values per provider
    PROVIDER_DEFAULTS = {
        'aws': {
            'runtime': 'nodejs18.x',
            'memory': 1024,
            'timeout': 6,
            'region': 'us-east-1'
        },
        'gcp': {
            'runtime': 'nodejs18',
            'memory': 256,
            'timeout': 60,
            'region': 'us-central1'
        },
        'azure': {
            'runtime': 'node18',
            'memory': 128,
            'timeout': 5,
            'region': 'westus'
        }
    }
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.ServerlessParser")
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a serverless configuration."""
        file_name = Path(file_path).name.lower()
        return file_name in ['serverless.yml', 'serverless.yaml']
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse serverless.yml and extract function configurations.
        
        Args:
            file_path: Path to serverless.yml
            
        Returns:
            ParsedConfig with ServerlessConfig in raw_data
        """
        content = self._read_file_safely(file_path)
        if content is None:
            return None
        
        try:
            # Parse YAML
            data = yaml.safe_load(content)
            
            if not isinstance(data, dict):
                self.logger.warning(f"{file_path} does not contain valid YAML dict")
                return None
            
            # Extract provider configuration
            provider_config = data.get('provider', {})
            if isinstance(provider_config, str):
                provider_config = {'name': provider_config}
            
            provider_name = provider_config.get('name', 'aws').lower()
            
            # Map to CloudProvider enum
            provider_enum = self._map_provider(provider_name)
            
            # Get provider defaults
            defaults = self.PROVIDER_DEFAULTS.get(provider_name, self.PROVIDER_DEFAULTS['aws'])
            
            # Build ServerlessConfig
            config = ServerlessConfig(
                file_path=file_path,
                service_name=data.get('service', 'unknown'),
                provider=provider_enum,
                region=provider_config.get('region', defaults['region']),
                runtime=provider_config.get('runtime', defaults['runtime']),
                plugins=data.get('plugins', []),
                custom=data.get('custom', {})
            )
            
            # Parse functions
            functions_data = data.get('functions', {})
            if isinstance(functions_data, dict):
                for func_name, func_config in functions_data.items():
                    func = self._parse_function(
                        func_name, 
                        func_config, 
                        provider_config,
                        defaults
                    )
                    if func:
                        config.functions.append(func)
            
            # Calculate confidence
            confidence = self._calculate_confidence(config, data)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="serverless",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except yaml.YAMLError as e:
            self.logger.error(f"YAML parsing error in {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to parse serverless config {file_path}: {e}")
            return None
    
    def _map_provider(self, provider_name: str) -> CloudProvider:
        """Map provider string to CloudProvider enum."""
        provider_map = {
            'aws': CloudProvider.AWS,
            'amazon': CloudProvider.AWS,
            'gcp': CloudProvider.GCP,
            'google': CloudProvider.GCP,
            'azure': CloudProvider.AZURE,
            'microsoft': CloudProvider.AZURE
        }
        return provider_map.get(provider_name.lower(), CloudProvider.UNKNOWN)
    
    def _parse_function(
        self,
        func_name: str,
        func_config: Any,
        provider_config: Dict,
        defaults: Dict
    ) -> Optional[ServerlessFunction]:
        """
        Parse individual function configuration.
        
        Args:
            func_name: Function name
            func_config: Function configuration dict
            provider_config: Provider-level configuration
            defaults: Default values for this provider
            
        Returns:
            ServerlessFunction object or None
        """
        # Handle shorthand syntax (function: handler)
        if isinstance(func_config, str):
            func_config = {'handler': func_config}
        
        if not isinstance(func_config, dict):
            self.logger.warning(f"Invalid function config for {func_name}")
            return None
        
        try:
            # Extract memory with fallback chain
            memory = (
                func_config.get('memorySize') or
                func_config.get('memory') or
                provider_config.get('memorySize') or
                provider_config.get('memory') or
                defaults['memory']
            )
            
            # Extract timeout with fallback chain
            timeout = (
                func_config.get('timeout') or
                provider_config.get('timeout') or
                defaults['timeout']
            )
            
            # Extract runtime with fallback chain
            runtime = (
                func_config.get('runtime') or
                provider_config.get('runtime') or
                defaults['runtime']
            )
            
            # Parse events
            events = self._parse_events(func_config.get('events', []))
            
            # Parse environment variables
            env_vars = {}
            func_env = func_config.get('environment', {})
            provider_env = provider_config.get('environment', {})
            
            if isinstance(provider_env, dict):
                env_vars.update(provider_env)
            if isinstance(func_env, dict):
                env_vars.update(func_env)
            
            # Convert variable references to strings
            env_vars = {k: str(v) for k, v in env_vars.items()}
            
            return ServerlessFunction(
                name=func_name,
                runtime=str(runtime),
                memory_mb=int(memory),
                timeout_seconds=int(timeout),
                handler=func_config.get('handler', ''),
                events=events,
                environment=env_vars,
                layers=func_config.get('layers', []),
                vpc=func_config.get('vpc')
            )
            
        except (ValueError, TypeError) as e:
            self.logger.warning(f"Error parsing function {func_name}: {e}")
            return None
    
    def _parse_events(self, events_data: Any) -> List[Dict[str, Any]]:
        """
        Parse event triggers.
        
        Events can be:
        - List of dicts: [{http: {method: get, path: /users}}]
        - List of strings: ['http']
        """
        if not isinstance(events_data, list):
            return []
        
        parsed_events = []
        
        for event in events_data:
            if isinstance(event, dict):
                parsed_events.append(event)
            elif isinstance(event, str):
                parsed_events.append({event: {}})
        
        return parsed_events
    
    def _calculate_confidence(self, config: ServerlessConfig, raw_data: Dict) -> str:
        """
        Calculate parsing confidence.
        
        High confidence if:
        - Has functions with explicit memory/timeout
        - Has event triggers defined
        - No variable interpolation in critical fields
        
        Medium confidence if:
        - Has functions with defaults
        - Some variable interpolation
        
        Low confidence if:
        - Minimal configuration
        - Heavy variable interpolation
        """
        score = 0
        
        # Award points for function quality
        if config.functions:
            score += 3
            
            for func in config.functions:
                # Check for explicit configuration (not defaults)
                if func.memory_mb != 1024:  # AWS default
                    score += 1
                if func.events:
                    score += 1
                if func.vpc:
                    score += 1
        
        # Penalize for variable interpolation in critical fields
        yaml_str = str(raw_data)
        variable_count = yaml_str.count('${')
        if variable_count > 10:
            score -= 2
        elif variable_count > 5:
            score -= 1
        
        if score >= 7:
            return "high"
        elif score >= 3:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_serverless(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse serverless.yml.
    
    Args:
        file_path: Path to serverless.yml
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = ServerlessParser(verbose=verbose)
    return parser.safe_parse(file_path)
