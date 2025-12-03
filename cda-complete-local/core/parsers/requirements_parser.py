"""
Python Requirements Parser

Extracts dependency information from requirements.txt and similar files:
- Package names and version constraints
- AI/ML libraries (OpenAI, LangChain, Transformers, etc.)
- Cloud SDKs (boto3, google-cloud, azure)
- Database drivers
- Web frameworks

Supports:
- requirements.txt
- requirements-dev.txt, requirements-prod.txt variants
- Pip's extended syntax (extras, VCS URLs, editable installs)

Author: Scrooge Scanner Team
"""

import re
from typing import Optional, List, Set
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import RequirementsConfig, PythonPackage
import logging

logger = logging.getLogger(__name__)


class RequirementsParser(BaseParser):
    """
    Parser for Python requirements files.
    
    Identifies cost-relevant libraries and frameworks.
    """
    
    # AI/ML libraries that indicate LLM/AI costs
    AI_KEYWORDS = {
        'openai', 'anthropic', 'langchain', 'llamaindex', 'llama-index',
        'transformers', 'torch', 'tensorflow', 'keras', 'huggingface',
        'sentence-transformers', 'faiss', 'chromadb', 'pinecone',
        'weaviate', 'qdrant', 'milvus', 'cohere', 'replicate',
        'stability-sdk', 'elevenlabs', 'together', 'anyscale',
        'modal', 'runpod', 'banana-dev'
    }
    
    # Cloud SDKs that indicate infrastructure costs
    CLOUD_KEYWORDS = {
        'boto3', 'botocore', 'google-cloud', 'azure', 'aws',
        'gcloud', 'azureml', 'sagemaker', 'google-api-python-client',
        'digitalocean', 'linode', 'vultr', 'cloudflare'
    }
    
    # Database libraries
    DATABASE_KEYWORDS = {
        'psycopg2', 'pymongo', 'redis', 'sqlalchemy', 'django',
        'mysqlclient', 'pymysql', 'cassandra', 'elasticsearch',
        'opensearch', 'neo4j', 'influxdb', 'timescaledb'
    }
    
    # Web frameworks and API libraries
    WEB_KEYWORDS = {
        'fastapi', 'flask', 'django', 'starlette', 'aiohttp',
        'tornado', 'sanic', 'bottle', 'pyramid', 'requests',
        'httpx', 'urllib3'
    }
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.RequirementsParser")
    
    def can_parse(self, file_path: str) -> bool:
        """
        Check if file is a requirements file.
        
        Matches:
        - requirements.txt
        - requirements-dev.txt
        - requirements-prod.txt
        - requirements/*.txt
        """
        file_name = Path(file_path).name.lower()
        parent_dir = Path(file_path).parent.name.lower()
        
        return (
            file_name.startswith('requirements') and file_name.endswith('.txt') or
            parent_dir == 'requirements' and file_name.endswith('.txt')
        )
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse requirements file and extract package information.
        
        Args:
            file_path: Path to requirements file
            
        Returns:
            ParsedConfig with RequirementsConfig in raw_data
        """
        content = self._read_file_safely(file_path)
        if content is None:
            return None
        
        try:
            packages = []
            
            for line in content.split('\n'):
                package = self._parse_line(line)
                if package:
                    packages.append(package)
            
            # Build RequirementsConfig
            config = RequirementsConfig(
                file_path=file_path,
                packages=packages
            )
            
            # Calculate confidence
            confidence = self._calculate_confidence(config)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="requirements",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except Exception as e:
            self.logger.error(f"Failed to parse requirements file {file_path}: {e}")
            return None
    
    def _parse_line(self, line: str) -> Optional[PythonPackage]:
        """
        Parse a single requirements line.
        
        Handles:
        - Simple: package==1.0.0
        - Flexible: package>=1.0.0,<2.0.0
        - Extras: package[extra1,extra2]==1.0.0
        - VCS: git+https://github.com/user/repo.git@branch#egg=package
        - Editable: -e ./local/path
        - URLs: https://example.com/package.whl
        - Options: --index-url, -r, -c
        """
        line = line.strip()
        
        # Skip empty lines
        if not line:
            return None
        
        # Skip comments
        if line.startswith('#'):
            return None
        
        # Skip pip options
        if line.startswith('-'):
            # Handle -r requirements-base.txt, -e ./local, etc.
            if line.startswith('-r') or line.startswith('--requirement'):
                # Could recursively parse referenced file, but skip for now
                return None
            if line.startswith('-e') or line.startswith('--editable'):
                # Extract package name from editable install
                editable_path = line.split(None, 1)[1] if ' ' in line else ''
                # Try to extract package name from path
                pkg_name = Path(editable_path).name or 'editable-package'
                return PythonPackage(name=pkg_name, version='editable')
            # Skip other options (-i, --index-url, etc.)
            return None
        
        # Handle VCS URLs
        if any(line.startswith(vcs) for vcs in ['git+', 'hg+', 'svn+', 'bzr+']):
            # Extract package name from #egg=package
            egg_match = re.search(r'#egg=([a-zA-Z0-9_-]+)', line)
            if egg_match:
                pkg_name = egg_match.group(1)
                return PythonPackage(name=pkg_name, version='vcs')
            return None
        
        # Handle direct URLs
        if line.startswith('http://') or line.startswith('https://'):
            # Try to extract package name from URL
            url_match = re.search(r'/([a-zA-Z0-9_-]+)-[\d.]+', line)
            if url_match:
                pkg_name = url_match.group(1)
                return PythonPackage(name=pkg_name, version='url')
            return None
        
        # Standard format: package[extras]==version or package==version
        # Pattern: package_name[extras]operator(s)version
        pattern = r'^([a-zA-Z0-9_-]+)(?:\[([^\]]+)\])?(.*?)$'
        match = re.match(pattern, line)
        
        if not match:
            return None
        
        pkg_name = match.group(1).strip()
        extras_str = match.group(2)
        version_spec = match.group(3).strip()
        
        # Parse extras
        extras = []
        if extras_str:
            extras = [e.strip() for e in extras_str.split(',')]
        
        # Extract version
        version = None
        if version_spec:
            # Remove operators and get version number
            version = re.sub(r'^[<>=!~]+', '', version_spec).split(',')[0].strip()
        
        return PythonPackage(
            name=pkg_name,
            version=version,
            extras=extras
        )
    
    def _calculate_confidence(self, config: RequirementsConfig) -> str:
        """
        Calculate parsing confidence.
        
        High confidence if:
        - Successfully parsed many packages
        - Found cost-relevant libraries (AI, cloud)
        
        Medium confidence if:
        - Parsed some packages
        - Mix of standard and cost-relevant libraries
        
        Low confidence if:
        - Few packages parsed
        - Only standard libraries
        """
        score = 0
        
        # Award points for number of packages
        num_packages = len(config.packages)
        if num_packages > 20:
            score += 3
        elif num_packages > 10:
            score += 2
        elif num_packages > 5:
            score += 1
        
        # Award points for cost-relevant libraries
        if config.ai_libraries:
            score += 3
        if config.cloud_libraries:
            score += 2
        
        # Check for database libraries
        db_count = sum(
            1 for pkg in config.packages
            if any(kw in pkg.name.lower() for kw in self.DATABASE_KEYWORDS)
        )
        if db_count > 0:
            score += 1
        
        # Check for web frameworks
        web_count = sum(
            1 for pkg in config.packages
            if any(kw in pkg.name.lower() for kw in self.WEB_KEYWORDS)
        )
        if web_count > 0:
            score += 1
        
        if score >= 7:
            return "high"
        elif score >= 3:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_requirements(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse requirements.txt.
    
    Args:
        file_path: Path to requirements file
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = RequirementsParser(verbose=verbose)
    return parser.safe_parse(file_path)
