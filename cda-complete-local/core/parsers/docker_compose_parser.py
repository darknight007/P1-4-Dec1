"""
Docker Compose Parser

Extracts multi-container application architecture from docker-compose.yml:
- Service definitions (each service may have cost implications)
- Resource limits (memory, CPU constraints)
- Volume mounts (storage costs)
- Network configurations
- Deployment/scaling configurations

Supports:
- Docker Compose v2 and v3 syntax
- Environment variable substitution detection
- Service dependency analysis

Author: Scrooge Scanner Team
"""

import yaml
from typing import Optional, Dict, List, Any
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import DockerComposeConfig, DockerComposeService
import logging
import re

logger = logging.getLogger(__name__)


class DockerComposeParser(BaseParser):
    """
    Parser for docker-compose.yml configuration files.
    
    Extracts service-level configurations that affect infrastructure costs.
    """
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.DockerComposeParser")
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a docker-compose configuration."""
        file_name = Path(file_path).name.lower()
        return (
            'docker-compose' in file_name and
            file_name.endswith(('.yml', '.yaml'))
        )
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse docker-compose.yml and extract service configurations.
        
        Args:
            file_path: Path to docker-compose.yml
            
        Returns:
            ParsedConfig with DockerComposeConfig in raw_data
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
            
            # Extract version
            version = str(data.get('version', '3'))
            
            # Build DockerComposeConfig
            config = DockerComposeConfig(
                file_path=file_path,
                version=version,
                networks=data.get('networks', {}),
                volumes=data.get('volumes', {})
            )
            
            # Parse services
            services_data = data.get('services', {})
            if isinstance(services_data, dict):
                for service_name, service_config in services_data.items():
                    service = self._parse_service(service_name, service_config)
                    if service:
                        config.services.append(service)
            
            # Calculate confidence
            confidence = self._calculate_confidence(config, data)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="docker-compose",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except yaml.YAMLError as e:
            self.logger.error(f"YAML parsing error in {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to parse docker-compose config {file_path}: {e}")
            return None
    
    def _parse_service(
        self,
        service_name: str,
        service_config: Any
    ) -> Optional[DockerComposeService]:
        """
        Parse individual service configuration.
        
        Args:
            service_name: Service name
            service_config: Service configuration dict
            
        Returns:
            DockerComposeService object or None
        """
        if not isinstance(service_config, dict):
            self.logger.warning(f"Invalid service config for {service_name}")
            return None
        
        try:
            # Extract image or build context
            image = service_config.get('image')
            build = service_config.get('build')
            
            # Build can be a string (path) or dict
            if isinstance(build, dict):
                build = build.get('context', str(build))
            
            # Parse ports (can be strings or integers)
            ports = self._parse_ports(service_config.get('ports', []))
            
            # Parse environment variables
            environment = self._parse_environment(service_config.get('environment', {}))
            
            # Parse volumes
            volumes = self._parse_volumes(service_config.get('volumes', []))
            
            # Parse depends_on
            depends_on = self._parse_depends_on(service_config.get('depends_on', []))
            
            # Parse deploy configuration (v3 syntax)
            deploy = service_config.get('deploy')
            
            return DockerComposeService(
                name=service_name,
                image=image,
                build=str(build) if build else None,
                ports=ports,
                environment=environment,
                volumes=volumes,
                depends_on=depends_on,
                deploy=deploy if isinstance(deploy, dict) else None
            )
            
        except Exception as e:
            self.logger.warning(f"Error parsing service {service_name}: {e}")
            return None
    
    def _parse_ports(self, ports_data: Any) -> List[str]:
        """
        Parse port mappings.
        
        Handles:
        - Short syntax: ["3000", "8080:80"]
        - Long syntax: [{target: 80, published: 8080, protocol: tcp}]
        """
        if not isinstance(ports_data, list):
            return []
        
        parsed_ports = []
        
        for port in ports_data:
            if isinstance(port, (str, int)):
                # Short syntax: "host:container" or just "port"
                parsed_ports.append(str(port))
            elif isinstance(port, dict):
                # Long syntax (v3)
                target = port.get('target', '')
                published = port.get('published', '')
                protocol = port.get('protocol', 'tcp')
                
                if published and target:
                    parsed_ports.append(f"{published}:{target}/{protocol}")
                elif target:
                    parsed_ports.append(f"{target}/{protocol}")
        
        return parsed_ports
    
    def _parse_environment(self, env_data: Any) -> Dict[str, Any]:
        """
        Parse environment variables.
        
        Handles:
        - Dict format: {KEY: value}
        - List format: ["KEY=value"]
        """
        environment = {}
        
        if isinstance(env_data, dict):
            # Direct dict format
            environment = {k: str(v) for k, v in env_data.items()}
        elif isinstance(env_data, list):
            # List format: ["KEY=value"]
            for item in env_data:
                if isinstance(item, str) and '=' in item:
                    key, value = item.split('=', 1)
                    environment[key] = value
        
        return environment
    
    def _parse_volumes(self, volumes_data: Any) -> List[str]:
        """
        Parse volume mounts.
        
        Handles:
        - Short syntax: ["./data:/data"]
        - Long syntax: [{type: bind, source: ./data, target: /data}]
        """
        if not isinstance(volumes_data, list):
            return []
        
        parsed_volumes = []
        
        for volume in volumes_data:
            if isinstance(volume, str):
                # Short syntax
                parsed_volumes.append(volume)
            elif isinstance(volume, dict):
                # Long syntax (v3)
                vol_type = volume.get('type', 'volume')
                source = volume.get('source', '')
                target = volume.get('target', '')
                
                if source and target:
                    parsed_volumes.append(f"{source}:{target} (type={vol_type})")
                elif target:
                    parsed_volumes.append(f"{target} (type={vol_type})")
        
        return parsed_volumes
    
    def _parse_depends_on(self, depends_data: Any) -> List[str]:
        """
        Parse service dependencies.
        
        Handles:
        - List format: ["db", "redis"]
        - Dict format: {db: {condition: service_healthy}}
        """
        if isinstance(depends_data, list):
            return [str(dep) for dep in depends_data]
        elif isinstance(depends_data, dict):
            return list(depends_data.keys())
        
        return []
    
    def _calculate_confidence(self, config: DockerComposeConfig, raw_data: Dict) -> str:
        """
        Calculate parsing confidence.
        
        High confidence if:
        - Has multiple services with clear configurations
        - Has deploy/resource configurations
        - Minimal variable interpolation
        
        Medium confidence if:
        - Has services with basic configs
        - Some variable interpolation
        
        Low confidence if:
        - Minimal service configuration
        - Heavy variable interpolation
        """
        score = 0
        
        # Award points for service quality
        if config.services:
            score += 3
            
            for service in config.services:
                # Check for explicit configuration
                if service.image or service.build:
                    score += 1
                if service.ports:
                    score += 1
                if service.deploy:
                    score += 2  # Deploy config is valuable for cost estimation
                if service.environment:
                    score += 1
        
        # Award points for networks and volumes (indicates complex setup)
        if config.networks:
            score += 1
        if config.volumes:
            score += 1
        
        # Penalize for variable interpolation
        yaml_str = str(raw_data)
        variable_count = yaml_str.count('${')
        if variable_count > 15:
            score -= 2
        elif variable_count > 8:
            score -= 1
        
        if score >= 10:
            return "high"
        elif score >= 5:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_docker_compose(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse docker-compose.yml.
    
    Args:
        file_path: Path to docker-compose.yml
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = DockerComposeParser(verbose=verbose)
    return parser.safe_parse(file_path)
