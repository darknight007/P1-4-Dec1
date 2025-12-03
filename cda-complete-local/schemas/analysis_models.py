# schemas/analysis_models.py

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class InvestigationLedger(BaseModel):
    """
    The 'Snowball' Context passed sequentially between specialists.
    Each specialist reads from previous findings and adds their own.

    This replaces the chat history as the primary source of truth for
    cross-agent collaboration.
    """
    # --- PHASE 1: ARCHITECT (Infra & Ops) ---
    primary_code_dir: str = Field(".", description="Detected root of source code (e.g., src/ or app/)")
    
    # NEW: Helps identifying the tech stack early to prevent wrong searches
    project_framework: str = Field("Unknown", description="Detected Framework: AWS CDK, Django, Flask, Next.js, etc.")
    key_config_files: List[str] = Field(default_factory=list, description="Critical configs found: cdk.json, serverless.yml")

    compute_assets: List[str] = Field(
        default_factory=list,
        description="Found compute definitions: Dockerfiles, K8s manifests, Lambda functions, EC2 configs"
    )

    storage_assets: List[str] = Field(
        default_factory=list,
        description="Found storage definitions: S3 buckets, RDS instances, DynamoDB tables, PVCs"
    )

    ci_cd_pipelines: List[str] = Field(
        default_factory=list,
        description="Found automation: GitHub Actions, CircleCI, Jenkins, scheduled cron jobs"
    )

    # --- PHASE 2: INTELLIGENCE (AI & Data) ---
    llm_chains: List[str] = Field(
        default_factory=list,
        description="Confirmed LLM call chains (Entry -> Wrapper -> Prompt -> API)"
    )

    vector_dbs: List[str] = Field(
        default_factory=list,
        description="Found Vector DB usages: Pinecone, Chroma, Qdrant, Milvus"
    )

    third_party_compute: List[str] = Field(
        default_factory=list,
        description="Found heavy client-side compute: Scrapers (Selenium/Playwright), Data Pipelines"
    )

    # --- PHASE 3: INTEGRATOR (SaaS & Humans) ---
    saas_services: List[str] = Field(
        default_factory=list,
        description="Found external paid APIs: Stripe, Twilio, SendGrid, Auth0"
    )

    hitl_patterns: List[str] = Field(
        default_factory=list,
        description="Found Human-in-the-Loop patterns: Approval steps, manual triggers, review queues"
    )

    # --- SHARED STATE & OPTIMIZATION ---
    searched_paths: List[str] = Field(
        default_factory=list,
        description="List of directories or files already deeply audited to avoid redundant searching"
    )

    notes: List[str] = Field(
        default_factory=list,
        description="High-level notes, warnings, or hypothesis passed between agents"
    )