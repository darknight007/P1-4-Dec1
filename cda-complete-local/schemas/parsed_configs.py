"""
Parsed Configuration Data Models

Pydantic models representing structured data extracted from
configuration files (Dockerfile, serverless.yml, etc.)

These models serve as the contract between parsers and downstream
cost calculation logic.

Author: Scrooge Scanner Team
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from enum import Enum


class CloudProvider(str, Enum):
    """Supported cloud providers"""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    UNKNOWN = "unknown"


class RuntimeEnvironment(str, Enum):
    """Supported runtime environments"""
    PYTHON = "python"
    NODE = "nodejs"
    JAVA = "java"
    GO = "go"
    DOTNET = "dotnet"
    RUBY = "ruby"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


# ==================== Docker Configurations ====================

class DockerConfig(BaseModel):
    """
    Structured representation of Dockerfile analysis.
    
    Extracts cost-relevant information:
    - Base image (affects cold start time)
    - Memory hints (from base image type)
    - Environment variables (may contain service configs)
    - Multi-stage builds (affects final image size)
    """
    file_path: str = Field(..., description="Path to Dockerfile")
    
    base_images: List[str] = Field(
        default_factory=list,
        description="List of FROM statements"
    )
    
    exposed_ports: List[int] = Field(
        default_factory=list,
        description="Ports exposed via EXPOSE directive"
    )
    
    env_vars: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables set via ENV"
    )
    
    volumes: List[str] = Field(
        default_factory=list,
        description="Volume mount points"
    )
    
    commands: List[str] = Field(
        default_factory=list,
        description="RUN commands (can indicate dependencies)"
    )
    
    estimated_memory_mb: Optional[int] = Field(
        default=None,
        description="Estimated memory requirement based on base image",
        ge=64,  # Minimum 64MB
        le=30720  # Maximum 30GB
    )
    
    multi_stage: bool = Field(
        default=False,
        description="Whether this is a multi-stage build"
    )
    
    workdir: Optional[str] = Field(
        default=None,
        description="Working directory set via WORKDIR"
    )
    
    @validator('exposed_ports')
    def validate_ports(cls, v):
        """Ensure all port numbers are valid"""
        for port in v:
            if not (1 <= port <= 65535):
                raise ValueError(f"Invalid port number: {port}")
        return v


class DockerComposeService(BaseModel):
    """Single service definition from docker-compose.yml"""
    name: str = Field(..., description="Service name")
    image: Optional[str] = Field(default=None, description="Docker image")
    build: Optional[str] = Field(default=None, description="Build context path")
    ports: List[str] = Field(default_factory=list, description="Port mappings")
    environment: Dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    volumes: List[str] = Field(default_factory=list, description="Volume mounts")
    depends_on: List[str] = Field(default_factory=list, description="Service dependencies")
    deploy: Optional[Dict[str, Any]] = Field(default=None, description="Deployment config")


class DockerComposeConfig(BaseModel):
    """Complete docker-compose.yml representation"""
    file_path: str = Field(..., description="Path to docker-compose.yml")
    version: str = Field(default="3", description="Compose file version")
    services: List[DockerComposeService] = Field(
        default_factory=list,
        description="Service definitions"
    )
    networks: Dict[str, Any] = Field(default_factory=dict, description="Network configs")
    volumes: Dict[str, Any] = Field(default_factory=dict, description="Volume configs")


# ==================== Serverless Configurations ====================

class ServerlessFunction(BaseModel):
    """
    Individual function definition from serverless.yml.
    
    Contains all cost-relevant parameters:
    - Memory allocation (primary cost driver)
    - Timeout (affects cost per invocation)
    - Event triggers (helps estimate invocation volume)
    """
    name: str = Field(..., description="Function name")
    
    runtime: str = Field(
        default="nodejs18.x",
        description="Function runtime environment"
    )
    
    memory_mb: int = Field(
        default=128,
        description="Memory allocation in MB",
        ge=128,
        le=10240
    )
    
    timeout_seconds: int = Field(
        default=3,
        description="Execution timeout in seconds",
        ge=1,
        le=900  # AWS Lambda max timeout
    )
    
    handler: str = Field(
        default="",
        description="Function handler path"
    )
    
    events: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Event triggers (http, s3, dynamodb, etc.)"
    )
    
    environment: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables"
    )
    
    layers: List[str] = Field(
        default_factory=list,
        description="Lambda layers (can affect package size)"
    )
    
    vpc: Optional[Dict[str, Any]] = Field(
        default=None,
        description="VPC configuration (adds cold start time)"
    )
    
    @property
    def has_vpc(self) -> bool:
        """Check if function is VPC-attached (affects costs)"""
        return self.vpc is not None
    
    @property
    def trigger_types(self) -> List[str]:
        """Extract trigger types from events"""
        return [list(event.keys())[0] for event in self.events if event]


class ServerlessConfig(BaseModel):
    """Complete serverless.yml representation"""
    file_path: str = Field(..., description="Path to serverless.yml")
    
    service_name: str = Field(
        default="unknown",
        description="Service name"
    )
    
    provider: CloudProvider = Field(
        default=CloudProvider.AWS,
        description="Cloud provider"
    )
    
    region: str = Field(
        default="us-east-1",
        description="Deployment region"
    )
    
    runtime: str = Field(
        default="nodejs18.x",
        description="Default runtime for all functions"
    )
    
    functions: List[ServerlessFunction] = Field(
        default_factory=list,
        description="Function definitions"
    )
    
    plugins: List[str] = Field(
        default_factory=list,
        description="Serverless framework plugins"
    )
    
    custom: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom configuration sections"
    )
    
    @property
    def total_functions(self) -> int:
        """Total number of functions defined"""
        return len(self.functions)
    
    @property
    def total_memory_mb(self) -> int:
        """Sum of memory across all functions"""
        return sum(f.memory_mb for f in self.functions)
    
    @property
    def avg_memory_mb(self) -> float:
        """Average memory allocation per function"""
        if not self.functions:
            return 0
        return self.total_memory_mb / len(self.functions)


# ==================== Terraform Configurations ====================

class TerraformResource(BaseModel):
    """Individual Terraform resource block"""
    type: str = Field(..., description="Resource type (e.g., aws_lambda_function)")
    name: str = Field(..., description="Resource name")
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resource attributes"
    )
    
    @property
    def is_compute(self) -> bool:
        """Check if this is a compute resource"""
        compute_types = ['lambda', 'ec2', 'ecs', 'eks', 'fargate', 'function']
        return any(ct in self.type.lower() for ct in compute_types)
    
    @property
    def is_storage(self) -> bool:
        """Check if this is a storage resource"""
        storage_types = ['s3', 'ebs', 'efs', 'dynamodb', 'rds', 'storage']
        return any(st in self.type.lower() for st in storage_types)


class TerraformConfig(BaseModel):
    """Complete Terraform file representation"""
    file_path: str = Field(..., description="Path to .tf file")
    
    provider: str = Field(
        default="unknown",
        description="Cloud provider"
    )
    
    resources: List[TerraformResource] = Field(
        default_factory=list,
        description="Resource definitions"
    )
    
    variables: Dict[str, Any] = Field(
        default_factory=dict,
        description="Variable definitions"
    )
    
    outputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Output definitions"
    )
    
    @property
    def compute_resources(self) -> List[TerraformResource]:
        """Filter to compute-only resources"""
        return [r for r in self.resources if r.is_compute]
    
    @property
    def storage_resources(self) -> List[TerraformResource]:
        """Filter to storage-only resources"""
        return [r for r in self.resources if r.is_storage]


# ==================== Package/Dependency Configurations ====================

class PythonPackage(BaseModel):
    """Python package from requirements.txt"""
    name: str = Field(..., description="Package name")
    version: Optional[str] = Field(default=None, description="Version specifier")
    extras: List[str] = Field(default_factory=list, description="Extra dependencies")


class RequirementsConfig(BaseModel):
    """Parsed requirements.txt"""
    file_path: str = Field(..., description="Path to requirements.txt")
    packages: List[PythonPackage] = Field(default_factory=list, description="All packages")
    
    @property
    def ai_libraries(self) -> List[str]:
        """Extract AI/ML library names"""
        ai_keywords = ['openai', 'anthropic', 'langchain', 'transformers', 
                       'tensorflow', 'torch', 'sklearn', 'huggingface']
        return [p.name for p in self.packages 
                if any(kw in p.name.lower() for kw in ai_keywords)]
    
    @property
    def cloud_libraries(self) -> List[str]:
        """Extract cloud SDK names"""
        cloud_keywords = ['boto3', 'google-cloud', 'azure', 'aws', 'gcp']
        return [p.name for p in self.packages 
                if any(kw in p.name.lower() for kw in cloud_keywords)]


class PackageJsonDependency(BaseModel):
    """Node.js package from package.json"""
    name: str
    version: str


class PackageJsonConfig(BaseModel):
    """Parsed package.json"""
    file_path: str = Field(..., description="Path to package.json")
    name: str = Field(default="", description="Package name")
    version: str = Field(default="0.0.0", description="Package version")
    dependencies: Dict[str, str] = Field(default_factory=dict)
    dev_dependencies: Dict[str, str] = Field(default_factory=dict)
    scripts: Dict[str, str] = Field(default_factory=dict)
    
    @property
    def ai_libraries(self) -> List[str]:
        """Extract AI library names"""
        ai_keywords = ['openai', 'anthropic', '@langchain', 'tensorflow', 'brain']
        all_deps = {**self.dependencies, **self.dev_dependencies}
        return [name for name in all_deps.keys() 
                if any(kw in name.lower() for kw in ai_keywords)]
