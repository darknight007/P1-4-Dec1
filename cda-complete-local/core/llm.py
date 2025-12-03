import os
from langchain_google_genai import ChatGoogleGenerativeAI

def get_llm(temperature: float = 0):
    """
    Returns the configured LLM instance based on .env settings.
    """
    # Default to 1.5-flash if env var is missing, otherwise use the one in .env
    model_name = os.getenv("LLM_MODEL", "gemini-2.0-flash-lite")
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        print("❌ [LLM] GOOGLE_API_KEY is missing!")
        raise ValueError("GOOGLE_API_KEY not found in environment variables. Please check your .env file.")

    masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "****"
    print(f"🔌 [LLM] Connecting to {model_name} with key {masked_key}")

    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        api_key=api_key,
        request_timeout=60  # Add timeout to prevent infinite hanging
    )