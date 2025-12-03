"""
Node.js Package.json Parser

Extracts dependency information from package.json files:
- Runtime dependencies (affect production costs)
- Development dependencies (typically don't affect production)
- Scripts (may indicate deployment/build processes)
- AI/ML libraries (OpenAI SDK, LangChain.js, etc.)
- Cloud SDKs (AWS SDK, Google Cloud, Azure)

Supports:
- Standard package.json format
- Monorepo/workspace configurations
- Private registry configurations

Author: Scrooge Scanner Team
"""

import json
from typing import Optional, Dict, List, Set
from pathlib import Path
from core.parsers.base_parser import BaseParser, ParsedConfig
from schemas.parsed_configs import PackageJsonConfig
import logging

logger = logging.getLogger(__name__)


class PackageJsonParser(BaseParser):
    """
    Parser for Node.js package.json files.
    
    Identifies cost-relevant libraries and deployment configurations.
    """
    
    # AI/ML libraries for Node.js
    AI_KEYWORDS = {
        'openai', '@anthropic-ai', 'langchain', '@langchain',
        'cohere-ai', 'replicate', '@pinecone-database',
        'chromadb', 'weaviate-ts-client', 'qdrant-js',
        '@google-ai', 'google-generative-ai', '@mistralai',
        '@huggingface', 'transformers', 'brain.js', 'synaptic',
        '@tensorflow/tfjs', 'natural', 'compromise', 'wink-nlp'
    }
    
    # Cloud SDKs
    CLOUD_KEYWORDS = {
        'aws-sdk', '@aws-sdk', 'aws-cdk', 'aws-amplify',
        '@google-cloud', 'google-cloud', 'firebase', 'firebase-admin',
        '@azure', 'azure-storage', 'azure-functions-core-tools',
        '@digitalocean', 'do-wrapper', 'cloudflare',
        '@vercel', 'vercel', 'netlify', 'railway'
    }
    
    # Database libraries
    DATABASE_KEYWORDS = {
        'mongodb', 'mongoose', 'pg', 'postgres', 'mysql', 'mysql2',
        'redis', 'ioredis', 'elasticsearch', '@elastic',
        'neo4j-driver', 'cassandra-driver', 'dynamodb',
        'prisma', '@prisma/client', 'typeorm', 'sequelize',
        'knex', 'bookshelf'
    }
    
    # Web frameworks and API libraries
    WEB_KEYWORDS = {
        'express', 'fastify', 'koa', '@nestjs', 'next',
        'nuxt', 'svelte', 'vue', 'react', 'angular',
        'axios', 'node-fetch', 'got', 'superagent', 'request',
        '@hapi/hapi', 'restify', 'polka', 'micro'
    }
    
    def __init__(self, verbose: bool = False):
        super().__init__(verbose)
        self.logger = logging.getLogger(f"{__name__}.PackageJsonParser")
    
    def can_parse(self, file_path: str) -> bool:
        """Check if file is a package.json."""
        return Path(file_path).name == 'package.json'
    
    def parse(self, file_path: str) -> Optional[ParsedConfig]:
        """
        Parse package.json and extract dependency information.
        
        Args:
            file_path: Path to package.json
            
        Returns:
            ParsedConfig with PackageJsonConfig in raw_data
        """
        content = self._read_file_safely(file_path)
        if content is None:
            return None
        
        try:
            data = json.loads(content)
            
            if not isinstance(data, dict):
                self.logger.warning(f"{file_path} does not contain valid JSON object")
                return None
            
            # Build PackageJsonConfig
            config = PackageJsonConfig(
                file_path=file_path,
                name=data.get('name', ''),
                version=data.get('version', '0.0.0'),
                dependencies=data.get('dependencies', {}),
                dev_dependencies=data.get('devDependencies', {}),
                scripts=data.get('scripts', {})
            )
            
            # Calculate confidence
            confidence = self._calculate_confidence(config, data)
            
            return ParsedConfig(
                file_path=file_path,
                parser_type="package-json",
                confidence=confidence,
                raw_data=config.dict()
            )
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing error in {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to parse package.json {file_path}: {e}")
            return None
    
    def _calculate_confidence(self, config: PackageJsonConfig, raw_data: Dict) -> str:
        """
        Calculate parsing confidence.
        
        High confidence if:
        - Has many dependencies
        - Found cost-relevant libraries (AI, cloud)
        - Has build/deploy scripts
        
        Medium confidence if:
        - Has some dependencies
        - Mix of standard and cost-relevant libraries
        
        Low confidence if:
        - Few dependencies
        - Only standard libraries
        """
        score = 0
        
        # Award points for number of dependencies
        total_deps = len(config.dependencies) + len(config.dev_dependencies)
        if total_deps > 30:
            score += 3
        elif total_deps > 15:
            score += 2
        elif total_deps > 5:
            score += 1
        
        # Award points for cost-relevant libraries
        if config.ai_libraries:
            score += 3
        
        # Check for cloud SDKs
        all_deps = set(config.dependencies.keys()) | set(config.dev_dependencies.keys())
        cloud_count = sum(
            1 for dep in all_deps
            if any(kw in dep.lower() for kw in self.CLOUD_KEYWORDS)
        )
        if cloud_count > 0:
            score += 2
        
        # Check for database libraries
        db_count = sum(
            1 for dep in all_deps
            if any(kw in dep.lower() for kw in self.DATABASE_KEYWORDS)
        )
        if db_count > 0:
            score += 1
        
        # Check for web frameworks
        web_count = sum(
            1 for dep in all_deps
            if any(kw in dep.lower() for kw in self.WEB_KEYWORDS)
        )
        if web_count > 0:
            score += 1
        
        # Award points for deployment-related scripts
        scripts = config.scripts
        deploy_scripts = [
            'build', 'deploy', 'start', 'prod', 'production', 'serve'
        ]
        if any(script in scripts for script in deploy_scripts):
            score += 1
        
        # Check for monorepo/workspace (indicates complex setup)
        if 'workspaces' in raw_data:
            score += 1
        
        if score >= 8:
            return "high"
        elif score >= 4:
            return "medium"
        else:
            return "low"


# Convenience function for standalone usage
def parse_package_json(file_path: str, verbose: bool = False) -> Optional[ParsedConfig]:
    """
    Convenience function to parse package.json.
    
    Args:
        file_path: Path to package.json
        verbose: Enable verbose logging
        
    Returns:
        ParsedConfig object or None
    """
    parser = PackageJsonParser(verbose=verbose)
    return parser.safe_parse(file_path)
