import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # AWS Configuration
    AWS_REGION: str = "ap-south-1"  # Default to your region
    UPLOAD_BUCKET: str              # Must be set in ECS Task Definition
    SCANNER_LAMBDA_NAME: str        # Must be set in ECS Task Definition
    
    # Security
    # In prod, this would be a DB lookup. For now, a master token is fine.
    SCROOGE_MASTER_TOKEN: str = "secret-demo-token"
    
    # App Config
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

# Global singleton
settings = Settings()