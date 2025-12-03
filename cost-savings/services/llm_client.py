# cost-savings/services/llm_client.py

import os
from typing import List, Optional
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# Load environment variables (Assumes .env is in the root or shared)
load_dotenv()

class LLMParameterSuggestion(BaseModel):
    """Schema for the LLM's JSON output."""
    id: str = Field(..., description="snake_case_id")
    label: str = Field(..., description="Human Readable Label")
    data_type: str = Field(..., description="'currency', 'percent', 'number'")
    unit: str = Field(..., description="$, %, hrs, etc.")
    default_value: float = Field(..., description="Estimated benchmark value")
    reasoning: str = Field(..., description="Why is this relevant to this specific feature?")

class LLMClient:
    """
    Centralized Wrapper for the AI Intelligence.
    Uses Google Gemini Flash (fast/cheap) for real-time UI responsiveness.
    """
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("⚠️ WARNING: GOOGLE_API_KEY not found. LLM features will fail.")
            self.llm = None
        else:
            # Using 1.5 Flash for speed (critical for UI dropdown population)
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash-exp",
                temperature=0.0,
                api_key=api_key
            )
            
        self.parser = JsonOutputParser(pydantic_object=LLMParameterSuggestion)

    def suggest_human_benchmarks(
        self, 
        feature_name: str, 
        feature_description: str, 
        feature_drivers: List[str], 
        project_context: str,
        existing_params: List[str]
    ) -> List[dict]:
        """
        Asks the LLM to invent missing human benchmark parameters, with richer feature context.
        """
        if not self.llm:
            return []

        prompt = f"""
        You are an expert IT & Business Process Cost Estimator.
        
        TARGET FEATURE: "{feature_name}"
        DESCRIPTION: "{feature_description}"
        TECHNICAL DRIVERS: {'; '.join(feature_drivers)}
        FULL PROJECT CONTEXT: "{project_context}"
        
        ALREADY IDENTIFIED PARAMETERS: {', '.join(existing_params)}
        
        TASK:
        Generate a list of 3-5 *specific* HUMAN BENCHMARK parameters required to calculate the ROI of replacing this human work with AI.
        
        CRITICAL RULES:
        1. **Analysis/Diagnosis:** If the feature involves "Analysis", "Diagnosis", "Review", or "Decision Making", you **MUST** suggest:
           - `human_accuracy` (Percent, default ~90-95% depending on stakes) OR `error_rate`.
           - `error_cost` (Currency, cost to fix a mistake).
        2. **Extraction/Entry:** If the feature involves "Extraction", "Data Entry", or "Parsing", you **MUST** suggest:
           - `manual_processing_time` (Hours/Mins per unit).
           - `rework_rate` (Percent of items needing correction).
        3. **High Stakes:** Look at the PROJECT CONTEXT. If it mentions "Medical", "Financial", or "Legal", set defaults that reflect HIGH RISK (e.g., higher accuracy needs, higher error costs).
        
        OUTPUT FORMAT:
        Return a JSON list of objects matching the schema: {{id, label, data_type, unit, default_value, reasoning}}.
        """

        try:
            messages = [
                SystemMessage(content="You generate strict JSON responses for cost estimation."),
                HumanMessage(content=prompt)
            ]
            
            # Chain the LLM with the JSON parser
            chain = self.llm | self.parser
            result = chain.invoke(messages)
            
            # Handle single dict vs list return
            if isinstance(result, dict):
                return [result]
            return result
            
        except Exception as e:
            print(f"❌ LLM Inference Failed: {e}")
            return []