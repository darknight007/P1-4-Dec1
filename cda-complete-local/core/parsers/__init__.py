# core/parsers/__init__.py
from typing import List
from .dockerfile_parser import DockerfileParser
from .docker_compose_parser import DockerComposeParser
from .requirements_parser import RequirementsParser
from .package_json_parser import PackageJsonParser
from .serverless_parser import ServerlessParser
from .terraform_parser import TerraformParser

__all__ = [
    'DockerfileParser', 'DockerComposeParser', 'RequirementsParser',
    'PackageJsonParser', 'ServerlessParser', 'TerraformParser'
]

def get_all_parsers() -> List:
    """
    Returns all available parsers for auto-discovery.
    """
    return [
        DockerfileParser,
        DockerComposeParser,
        RequirementsParser,
        PackageJsonParser,
        ServerlessParser,
        TerraformParser,
    ]
