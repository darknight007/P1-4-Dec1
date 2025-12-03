# core/seed_knowledge.py
"""
Minimal fallback patterns when DynamoDB is unavailable.
These should ONLY be used if DynamoDB fetch fails.
"""

DEFAULT_PATTERNS = [
    {
        "keyword": "PATTERN_LANGCHAIN",
        "category": "ai_framework",
        "confidence": "high",
        "regex": r"(?i)(from|import)\s+langchain",
        "description": "LangChain framework"
    },
    {
        "keyword": "PATTERN_OPENAI",
        "category": "ai",
        "confidence": "high",
        "regex": r"(?i)openai|gpt-[34]|ChatOpenAI",
        "description": "OpenAI API usage"
    },
    {
        "keyword": "PATTERN_ANTHROPIC",
        "category": "ai",
        "confidence": "high",
        "regex": r"(?i)anthropic|claude|ChatAnthropic",
        "description": "Anthropic Claude API"
    },
    {
        "keyword": "PATTERN_AWS_LAMBDA",
        "category": "cloud",
        "confidence": "high",
        "regex": r"(?i)aws_lambda|lambda_handler|@lambda_function",
        "description": "AWS Lambda"
    },
    {
        "keyword": "PATTERN_DYNAMODB",
        "category": "storage",
        "confidence": "medium",
        "regex": r"(?i)dynamodb|boto3\.resource\(['\"]dynamodb",
        "description": "DynamoDB table"
    },
    {
        "keyword": "PATTERN_S3",
        "category": "storage",
        "confidence": "medium",
        "regex": r"(?i)s3_client|boto3\.client\(['\"]s3|s3\.upload",
        "description": "S3 Storage"
    },
    {
        "keyword": "PATTERN_VECTORDB",
        "category": "ai_storage",
        "confidence": "high",
        "regex": r"(?i)pinecone|chromadb|weaviate|milvus|qdrant|vectorstore",
        "description": "Vector database"
    },
    {
        "keyword": "PATTERN_HUGGINGFACE",
        "category": "ai",
        "confidence": "medium",
        "regex": r"(?i)from transformers|huggingface_hub",
        "description": "HuggingFace models"
    }
]