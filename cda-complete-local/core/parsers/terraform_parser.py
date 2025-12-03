"""
Terraform Parser

Extracts infrastructure-as-code definitions from Terraform (.tf) files:
- Resource declarations (aws_lambda_function, aws_s3_bucket, etc.)
- Resource attributes (memory, timeout, instance_type, etc.)
- Provider configuration
- Variable definitions

Supports:
- HCL (HashiCorp Configuration Language) syntax
- Basic resource block extraction
- Attribute parsing

Limitations:
- Does not fully evaluate HCL expressions
- Does not resolve variable interpolations
- Best-effort parsing of complex nested blocks

Author: Scrooge Scanner Team
"""

import re
from typing import Optional, Dict, List, Any, Tuple
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import TerraformConfig, TerraformResource
import logging

logger = logging.getLogger(__name__)


class TerraformParser(BaseParser):
    """
    Parser for Terraform .tf configuration files.
    
    Uses regex-based parsing for resource extraction.
    Note: Full HCL parsing would require a proper HCL parser library.
    """
    
    # Common cloud resource types and their cost relevance
    COMPUTE_RESOURCES = [
        'aws_lambda_function', 'aws_ecs_task_definition', 'aws_ecs_service',
        'aws_instance', 'aws_autoscaling_group', 'aws_eks_cluster',
        'google_cloudfunctions_function', 'google_compute_instance',
        'azurerm_function_app', 'azurerm_virtual_machine'
    ]
    
    STORAGE_RESOURCES = [
        'aws_s3_bucket', 'aws_dynamodb_table', 'aws_rds_instance',
        'aws_ebs_volume', 'aws_efs_file_system',
        'google_storage_bucket', 'google_sql_database_instance',
        'azurerm_storage_account', 'azurerm_sql_database'
    ]
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.TerraformParser")
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a Terraform configuration."""
        return file_path.endswith('.tf')
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse Terraform file and extract resource definitions.
        
        Args:
            file_path: Path to .tf file
            
        Returns:
            ParsedConfig with TerraformConfig in raw_data
        """
        content = self._read_file_safely(file_path)
        if content is None:
            return None
        
        try:
            # Remove comments
            content = self._remove_comments(content)
            
            # Extract provider
            provider = self._extract_provider(content)
            
            # Build TerraformConfig
            config = TerraformConfig(
                file_path=file_path,
                provider=provider
            )
            
            # Extract resources
            resources = self._extract_resources(content)
            config.resources.extend(resources)
            
            # Extract variables
            config.variables = self._extract_variables(content)
            
            # Extract outputs
            config.outputs = self._extract_outputs(content)
            
            # Calculate confidence
            confidence = self._calculate_confidence(config, content)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="terraform",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except Exception as e:
            self.logger.error(f"Failed to parse Terraform file {file_path}: {e}")
            return None
    
    def _remove_comments(self, content: str) -> str:
        """
        Remove comments from HCL content.
        
        Handles:
        - Line comments: # and //
        - Block comments: /* ... */
        """
        # Remove block comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Remove line comments
        lines = []
        for line in content.split('\n'):
            # Remove # comments
            line = re.sub(r'#.*$', '', line)
            # Remove // comments
            line = re.sub(r'//.*$', '', line)
            lines.append(line)
        
        return '\n'.join(lines)
    
    def _extract_provider(self, content: str) -> str:
        """
        Extract provider configuration.
        
        Matches: provider "aws" { ... }
        """
        pattern = r'provider\s+"([^"]+)"'
        match = re.search(pattern, content)
        
        if match:
            return match.group(1)
        
        # Fallback: infer from resource types
        if 'aws_' in content:
            return 'aws'
        elif 'google_' in content:
            return 'gcp'
        elif 'azurerm_' in content:
            return 'azure'
        
        return 'unknown'
    
    def _extract_resources(self, content: str) -> List[TerraformResource]:
        """
        Extract resource blocks.
        
        Matches: resource "type" "name" { ... }
        """
        resources = []
        
        # Pattern for resource blocks
        # Captures: resource "aws_lambda_function" "my_function" { ... }
        pattern = r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}'
        
        matches = re.finditer(pattern, content, re.DOTALL)
        
        for match in matches:
            resource_type = match.group(1)
            resource_name = match.group(2)
            attributes_block = match.group(3)
            
            # Parse attributes from the block
            attributes = self._parse_attributes(attributes_block)
            
            resources.append(TerraformResource(
                type=resource_type,
                name=resource_name,
                attributes=attributes
            ))
        
        return resources
    
    def _parse_attributes(self, block: str) -> Dict[str, Any]:
        """
        Parse attribute assignments from a resource block.
        
        Handles:
        - Simple assignments: key = "value"
        - Numeric assignments: key = 123
        - Boolean assignments: key = true
        - List assignments: key = ["a", "b"]
        - Nested blocks (simplified extraction)
        """
        attributes = {}
        
        # Pattern for simple key = value pairs
        # Matches: memory_size = 512
        simple_pattern = r'(\w+)\s*=\s*([^=\n]+?)(?=\n|$)'
        
        for match in re.finditer(simple_pattern, block):
            key = match.group(1).strip()
            value_str = match.group(2).strip()
            
            # Skip if this looks like it's inside a nested block
            if '{' in value_str or '}' in value_str:
                continue
            
            # Parse the value
            value = self._parse_value(value_str)
            attributes[key] = value
        
        return attributes
    
    def _parse_value(self, value_str: str) -> Any:
        """
        Parse a value string into appropriate Python type.
        
        Handles:
        - Strings: "hello" -> "hello"
        - Numbers: 123 -> 123
        - Booleans: true -> True
        - Lists: ["a", "b"] -> ["a", "b"]
        """
        value_str = value_str.strip()
        
        # Remove trailing comma if present
        if value_str.endswith(','):
            value_str = value_str[:-1].strip()
        
        # Boolean
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False
        
        # Quoted string
        if value_str.startswith('"') and value_str.endswith('"'):
            return value_str[1:-1]
        
        # Number
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # List (simplified)
        if value_str.startswith('[') and value_str.endswith(']'):
            # Extract quoted strings from list
            items = re.findall(r'"([^"]+)"', value_str)
            return items if items else value_str
        
        # Variable reference or expression - keep as string
        return value_str
    
    def _extract_variables(self, content: str) -> Dict[str, Any]:
        """
        Extract variable definitions.
        
        Matches: variable "name" { ... }
        """
        variables = {}
        
        pattern = r'variable\s+"([^"]+)"\s*\{([^}]*)\}'
        
        matches = re.finditer(pattern, content, re.DOTALL)
        
        for match in matches:
            var_name = match.group(1)
            var_block = match.group(2)
            
            # Extract default value if present
            default_match = re.search(r'default\s*=\s*([^\n]+)', var_block)
            if default_match:
                default_value = self._parse_value(default_match.group(1))
                variables[var_name] = default_value
            else:
                variables[var_name] = None
        
        return variables
    
    def _extract_outputs(self, content: str) -> Dict[str, Any]:
        """
        Extract output definitions.
        
        Matches: output "name" { value = ... }
        """
        outputs = {}
        
        pattern = r'output\s+"([^"]+)"\s*\{([^}]*)\}'
        
        matches = re.finditer(pattern, content, re.DOTALL)
        
        for match in matches:
            output_name = match.group(1)
            output_block = match.group(2)
            
            # Extract value if present
            value_match = re.search(r'value\s*=\s*([^\n]+)', output_block)
            if value_match:
                value = self._parse_value(value_match.group(1))
                outputs[output_name] = value
            else:
                outputs[output_name] = None
        
        return outputs
    
    def _calculate_confidence(self, config: TerraformConfig, content: str) -> str:
        """
        Calculate parsing confidence.
        
        High confidence if:
        - Multiple resources with clear attributes
        - Recognized resource types
        - Minimal complex expressions
        
        Medium confidence if:
        - Has resources but many variable references
        - Mix of simple and complex resources
        
        Low confidence if:
        - Minimal resources extracted
        - Heavy use of variables and expressions
        """
        score = 0
        
        # Award points for successfully parsed resources
        if config.resources:
            score += 3
            
            # Check for cost-relevant resources
            for resource in config.resources:
                if resource.type in self.COMPUTE_RESOURCES:
                    score += 2
                elif resource.type in self.STORAGE_RESOURCES:
                    score += 1
                
                # Award points for extracted attributes
                if len(resource.attributes) > 3:
                    score += 1
        
        # Award points for variables and outputs (indicates structured config)
        if config.variables:
            score += 1
        if config.outputs:
            score += 1
        
        # Penalize for heavy variable interpolation
        var_ref_count = content.count('var.')
        if var_ref_count > 20:
            score -= 2
        elif var_ref_count > 10:
            score -= 1
        
        # Penalize for complex expressions
        expression_count = content.count('${'
        ) + content.count('for_each') + content.count('count =')
        if expression_count > 15:
            score -= 2
        elif expression_count > 8:
            score -= 1
        
        if score >= 8:
            return "high"
        elif score >= 4:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_terraform(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse Terraform file.
    
    Args:
        file_path: Path to .tf file
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = TerraformParser(verbose=verbose)
    return parser.safe_parse(file_path)
