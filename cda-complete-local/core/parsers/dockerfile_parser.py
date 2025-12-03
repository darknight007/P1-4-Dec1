"""
Dockerfile Parser

Extracts cost-relevant infrastructure signals from Dockerfiles:
- Base image selection (affects memory/CPU requirements)
- Exposed ports (indicates service type)
- Environment variables (may contain API keys, service configs)
- Multi-stage builds (affects final image size)
- Resource hints from base images

Author: Scrooge Scanner Team
"""

import re
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import DockerConfig
import logging

logger = logging.getLogger(__name__)


class DockerfileParser(BaseParser):
    """
    Parser for Dockerfile format.
    
    Handles:
    - Standard Dockerfile syntax
    - Multi-stage builds
    - ARG and ENV variable extraction
    - Base image memory estimation
    """
    
    # Base image to memory mapping (conservative estimates in MB)
    BASE_IMAGE_MEMORY_MAP = {
        'alpine': 64,
        'scratch': 32,
        'distroless': 64,
        'slim': 128,
        'python': 256,
        'node': 256,
        'openjdk': 512,
        'java': 512,
        'golang': 128,
        'rust': 128,
        'ruby': 256,
        'php': 256,
        'nginx': 128,
        'postgres': 512,
        'mysql': 512,
        'redis': 128,
        'mongo': 512,
    }
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.DockerfileParser")
    
    def can_parse(self, file_path: str) -> bool:
        """
        Check if file is a Dockerfile.
        
        Handles common naming patterns:
        - Dockerfile
        - Dockerfile.prod
        - Dockerfile.dev
        - prod.Dockerfile
        - etc.
        """
        path_lower = file_path.lower()
        return (
            path_lower.endswith('dockerfile') or
            'dockerfile' in Path(file_path).name.lower()
        )
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse Dockerfile and extract structured configuration.
        
        Args:
            file_path: Path to Dockerfile
            
        Returns:
            ParsedConfig with DockerConfig in raw_data, or None if parsing fails
        """
        content = self._read_file_safely(file_path)
        if content is None:
            return None
        
        try:
            config = DockerConfig(file_path=file_path)
            
            # Extract all components
            config.base_images = self._extract_base_images(content)
            config.exposed_ports = self._extract_exposed_ports(content)
            config.env_vars = self._extract_env_vars(content)
            config.volumes = self._extract_volumes(content)
            config.commands = self._extract_run_commands(content)
            config.workdir = self._extract_workdir(content)
            
            # Determine if multi-stage build
            config.multi_stage = len(config.base_images) > 1
            
            # Estimate memory requirements
            config.estimated_memory_mb = self._estimate_memory(config.base_images)
            
            # Determine confidence level
            confidence = self._calculate_confidence(config)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="dockerfile",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except Exception as e:
            self.logger.error(f"Failed to parse Dockerfile {file_path}: {e}")
            return None
    
    def _extract_base_images(self, content: str) -> List[str]:
        """
        Extract all FROM statements.
        
        Handles:
        - Simple FROM image:tag
        - FROM image:tag AS stage_name
        - FROM --platform=linux/amd64 image:tag
        """
        images = []
        
        # Pattern matches: FROM [--platform=...] image[:tag] [AS stage]
        pattern = r'^\s*FROM\s+(?:--platform=[^\s]+\s+)?([^\s]+)(?:\s+[Aa][Ss]\s+[^\s]+)?'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                image = match.group(1).strip()
                # Skip build stage references (they start with stage names)
                if not image.isupper() and image not in images:
                    images.append(image)
        
        return images
    
    def _extract_exposed_ports(self, content: str) -> List[int]:
        """
        Extract EXPOSE directives.
        
        Handles:
        - EXPOSE 80
        - EXPOSE 8080/tcp
        - EXPOSE 80 443
        """
        ports = []
        
        pattern = r'^\s*EXPOSE\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                port_spec = match.group(1).strip()
                # Split multiple ports on same line
                for port_str in port_spec.split():
                    # Remove /tcp or /udp suffix
                    port_str = port_str.split('/')[0]
                    try:
                        port = int(port_str)
                        if 1 <= port <= 65535 and port not in ports:
                            ports.append(port)
                    except ValueError:
                        continue
        
        return sorted(ports)
    
    def _extract_env_vars(self, content: str) -> Dict[str, str]:
        """
        Extract ENV directives.
        
        Handles:
        - ENV KEY=value
        - ENV KEY value
        - ENV KEY1=value1 KEY2=value2
        """
        env_vars = {}
        
        # Pattern for ENV KEY=value or ENV KEY value
        pattern = r'^\s*ENV\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                env_spec = match.group(1).strip()
                
                # Handle space-separated format: ENV KEY value
                if '=' not in env_spec:
                    parts = env_spec.split(None, 1)
                    if len(parts) == 2:
                        key, value = parts
                        env_vars[key] = value.strip('"\'')
                else:
                    # Handle KEY=value format (can have multiple on one line)
                    for pair in re.findall(r'([A-Z_][A-Z0-9_]*)=([^\s]+)', env_spec):
                        key, value = pair
                        env_vars[key] = value.strip('"\'')
        
        return env_vars
    
    def _extract_volumes(self, content: str) -> List[str]:
        """
        Extract VOLUME directives.
        
        Handles:
        - VOLUME /data
        - VOLUME ["/data", "/logs"]
        """
        volumes = []
        
        pattern = r'^\s*VOLUME\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                volume_spec = match.group(1).strip()
                
                # Handle JSON array format
                if volume_spec.startswith('['):
                    # Extract paths from JSON array
                    paths = re.findall(r'["\']([^"\']+)["\']', volume_spec)
                    volumes.extend(paths)
                else:
                    # Handle simple path
                    volumes.append(volume_spec.strip('"\''))
        
        return volumes
    
    def _extract_run_commands(self, content: str) -> List[str]:
        """
        Extract RUN commands (useful for dependency detection).
        
        Only extracts first 100 chars of each command to avoid bloat.
        """
        commands = []
        
        pattern = r'^\s*RUN\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                cmd = match.group(1).strip()
                # Truncate long commands
                if len(cmd) > 100:
                    cmd = cmd[:97] + '...'
                commands.append(cmd)
        
        return commands
    
    def _extract_workdir(self, content: str) -> Optional[str]:
        """Extract WORKDIR directive (last one wins)."""
        workdir = None
        
        pattern = r'^\s*WORKDIR\s+(.+)$'
        
        for line in content.split('\n'):
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                workdir = match.group(1).strip()
        
        return workdir
    
    def _estimate_memory(self, base_images: List[str]) -> Optional[int]:
        """
        Estimate memory requirements based on base image.
        
        Uses the final base image in multi-stage builds.
        Returns conservative estimate in MB.
        """
        if not base_images:
            return None
        
        # Use last base image (final stage in multi-stage builds)
        final_image = base_images[-1].lower()
        
        # Check against known base images
        for key, memory_mb in self.BASE_IMAGE_MEMORY_MAP.items():
            if key in final_image:
                return memory_mb
        
        # Default conservative estimate for unknown images
        return 256
    
    def _calculate_confidence(self, config: DockerConfig) -> str:
        """
        Calculate parsing confidence based on extracted data quality.
        
        Returns:
            "high" if we extracted substantial information
            "medium" if we extracted some information
            "low" if we extracted minimal information
        """
        score = 0
        
        # Award points for successfully extracted data
        if config.base_images:
            score += 3
        if config.exposed_ports:
            score += 2
        if config.env_vars:
            score += 2
        if config.volumes:
            score += 1
        if config.estimated_memory_mb:
            score += 2
        
        if score >= 7:
            return "high"
        elif score >= 4:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_dockerfile(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse a Dockerfile.
    
    Args:
        file_path: Path to Dockerfile
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = DockerfileParser(verbose=verbose)
    return parser.safe_parse(file_path)
