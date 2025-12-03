# cost-savings/services/parameter_discovery.py

import re
import json
import os
from typing import List, Set, Dict, Any
from pathlib import Path

from models.context_models import (
    CostReportContext, 
    CostParameter, 
    FeatureConfigSchema,
    ImportedLLMCall, 
    ImportedCostItem, 
    Feature 
)
from services.llm_client import LLMClient

# Path to the Persistent Knowledge Base
KB_FILE = Path("data/parameter_knowledge.json")

class ParameterDiscoveryEngine:
    """
    The Brain that decides which Human Benchmarks are relevant.
    Hybrid Architecture: 
    1. Database (Global Defaults + Regex Rules)
    2. Real AI Inference (LLM Client)
    3. Self-Learning (Saves successful params)
    """

    def __init__(self):
        self.llm_client = LLMClient()
        self._ensure_kb_exists()
        self.knowledge_base = self._load_kb()

    def _ensure_kb_exists(self):
        """Creates the JSON DB if missing, seeded with sensible defaults."""
        if not KB_FILE.exists():
            KB_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Seed with defaults
            defaults = {
                "global": [
                    {"id": "human_hourly_rate", "label": "Human Hourly Cost", "data_type": "currency", "unit": "$", "default_value": 30.0, "reasoning": "Global Baseline"},
                    {"id": "human_throughput", "label": "Human Throughput", "data_type": "number", "unit": "units/hr", "default_value": 10.0, "reasoning": "Global Baseline"}
                ],
                "regex_rules": {
                    "quality": {"pattern": "(quality|review|check|audit)", "params": [
                        {"id": "human_accuracy", "label": "Human Accuracy", "data_type": "percent", "unit": "%", "default_value": 95.0, "reasoning": "Manual Error Rate"}
                    ]},
                    "latency": {"pattern": "(real-?time|fast|sla|chat|instant)", "params": [
                        {"id": "human_sla", "label": "Human SLA (Turnaround)", "data_type": "number", "unit": "hrs", "default_value": 24.0, "reasoning": "Queue Wait Time"}
                    ]}
                },
                "learned_patterns": {} # New section for self-learning
            }
            with open(KB_FILE, "w") as f:
                json.dump(defaults, f, indent=2)

    def _load_kb(self) -> Dict:
        try:
            with open(KB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {"global": [], "regex_rules": {}, "learned_patterns": {}}

    def _save_kb(self):
        """Persists the updated knowledge base."""
        try:
            with open(KB_FILE, "w") as f:
                json.dump(self.knowledge_base, f, indent=2)
        except Exception as e:
            print(f"Failed to save KB: {e}")

    def learn_new_parameters(self, feature_name: str, used_parameters: Dict[str, Any]):
        """
        The Learning Loop.
        Called when a user successfully calculates ROI using specific parameters.
        We associate these parameters with keywords in the feature name for future suggestions.
        """
        learned = self.knowledge_base.get("learned_patterns", {})
        
        # Simple keyword extraction (unigrams)
        # e.g. "Medical Record Analysis" -> "medical", "record", "analysis"
        keywords = feature_name.lower().split()
        
        updated = False
        # Get IDs of global params so we don't 'learn' what we already know globally
        global_ids = [p["id"] for p in self.knowledge_base.get("global", [])]
        
        for kw in keywords:
            if len(kw) < 4: continue # Skip small words
            
            if kw not in learned:
                learned[kw] = []
            
            for param_id in used_parameters.keys():
                if param_id not in global_ids:
                    # It's a specific param. Record the association.
                    if param_id not in learned[kw]:
                        learned[kw].append(param_id)
                        updated = True
                        print(f"🧠 LEARNING: Associated '{param_id}' with keyword '{kw}'")

        if updated:
            self.knowledge_base["learned_patterns"] = learned
            self._save_kb()

    def generate_schema(self, context: CostReportContext, target_feature_id: str) -> FeatureConfigSchema:
        """
        Constructs the configuration schema for a specific feature, using its ID and linked cost drivers.
        """
        parameters: List[CostParameter] = []
        seen_ids: Set[str] = set()

        # 1. Retrieve the target Feature from the context
        target_feature = next((f for f in context.features if f.id == target_feature_id), None)
        if not target_feature:
            raise ValueError(f"Feature with ID '{target_feature_id}' not found in CostReportContext.")

        # 2. Build a rich contextual search string for parameter discovery
        driver_details = []
        
        # Combine all cost items into a single lookup
        # Note: We iterate specifically to ensure we get the Pydantic objects
        all_cost_items = {}
        for item in context.llm_calls:
            all_cost_items[item.id] = item
        for item in context.infrastructure:
            all_cost_items[item.id] = item
        for item in context.integrations:
            all_cost_items[item.id] = item
        for item in context.data_components:
            all_cost_items[item.id] = item

        for driver_id in target_feature.cost_driver_ids:
            driver = all_cost_items.get(driver_id)
            if driver:
                # Robustly handle different Pydantic models
                if isinstance(driver, ImportedLLMCall):
                    # LLMCall has: model, entry_point, api_call_location
                    # Does NOT have: category, metric (well, implicit)
                    detail = f"LLM Model: {driver.model} via {driver.entry_point}"
                    driver_details.append(detail)
                elif isinstance(driver, ImportedCostItem):
                    # CostItem has: category, name, location, metric
                    detail = f"{driver.category.upper()}: {driver.name} ({driver.metric})"
                    driver_details.append(detail)
                else:
                    # Fallback for unknown types
                    driver_details.append(f"Driver ID: {driver_id}")
        
        project_summary = context.get_project_summary()
        
        # This will be used for both regex rules and LLM inference
        rich_search_text = (
            f"Feature: {target_feature.name}. "
            f"Description: {target_feature.description}. "
            f"Powered by: {'; '.join(driver_details)}. "
            f"Project Overview: {project_summary}"
        ).lower()

        # 3. GLOBAL DEFAULTS (From DB)
        for p in self.knowledge_base.get("global", []):
            self._add_param_from_dict(parameters, seen_ids, p, "db_global")

        # 4. CONTEXT ENRICHMENT (Region/Currency Logic) - now using rich_search_text
        self._enrich_defaults_from_context(parameters, rich_search_text)

        # 5. REGEX TRIGGERS (From DB) - now using rich_search_text
        regex_rules = self.knowledge_base.get("regex_rules", {})
        
        for group, rule in regex_rules.items():
            pattern = rule.get("pattern", "")
            if re.search(pattern, rich_search_text, re.IGNORECASE):
                for p in rule.get("params", []):
                    self._add_param_from_dict(parameters, seen_ids, p, "db_regex")
        
        # 6. LEARNED PATTERNS (The "Recall" Step)
        learned_patterns = self.knowledge_base.get("learned_patterns", {})
        for kw in rich_search_text.split():
            if kw in learned_patterns:
                # Add logic to retrieve and add these learned params. For now, it's a hint.
                pass 

        # 7. LLM INFERENCE (Real AI) - now using rich_search_text
        existing_ids = list(seen_ids)
        llm_suggestions = self.llm_client.suggest_human_benchmarks(
            feature_name=target_feature.name,
            feature_description=target_feature.description, # NEW: Pass description
            feature_drivers=driver_details,                 # NEW: Pass drivers
            project_context=project_summary,
            existing_params=existing_ids
        )

        for item in llm_suggestions:
            try:
                p_obj = CostParameter(
                    id=item.get("id"),
                    label=item.get("label"),
                    data_type=item.get("data_type", "number"),
                    unit=item.get("unit", ""),
                    default_value=item.get("default_value", 0.0),
                    source="llm_inference",
                    reasoning=item.get("reasoning", "AI Suggestion")
                )
                if p_obj.id not in seen_ids:
                    parameters.append(p_obj)
                    seen_ids.add(p_obj.id)
            except Exception as e:
                print(f"Skipping invalid LLM suggestion: {e}")

        # 8. BUILD RECOMMENDATIONS
        recommended = ["human_hourly_rate", "human_throughput"]
        for p in parameters:
            if p.source != "db_global" and len(recommended) < 5: # Limit default recommendations
                if p.id not in recommended: # Avoid duplicates
                    recommended.append(p.id)
        
        return FeatureConfigSchema(
            feature_id=target_feature.id, # Use actual feature ID
            feature_name=target_feature.name,
            available_parameters=parameters,
            recommended_parameters=recommended
        )

    def _add_param_from_dict(self, target, seen, p_dict, source):
        """Helper to safely instantiate CostParameter from dict and handle validation errors."""
        if p_dict["id"] not in seen:
            d = p_dict.copy()
            d["source"] = source
            try:
                obj = CostParameter(**d)
                target.append(obj)
                seen.add(obj.id)
            except Exception as e:
                # Useful logging for debugging DB issues
                print(f"⚠️ Validation Error for param '{p_dict.get('id')}': {e}")

    def _enrich_defaults_from_context(self, parameters: List[CostParameter], text: str):
        """Adjusts currency/rates based on region keywords."""
        is_us = bool(re.search(r"(?i)\b(us|usa|united states|dollar)\b", text))
        is_eu = bool(re.search(r"(?i)\b(eu|europe|euro|germany)\b", text))
        
        for p in parameters:
            if p.data_type == "currency":
                if is_us:
                    p.unit = "$"
                    if p.id == "human_hourly_rate" and p.default_value < 35:
                        p.default_value = 45.0
                elif is_eu:
                    p.unit = "€"
                    if p.id == "human_hourly_rate" and p.default_value < 30:
                        p.default_value = 40.0