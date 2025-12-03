# agent/nodes/reporter.py

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict
from langchain_core.messages import SystemMessage
from core.llm import get_llm
from schemas.output_models import CostElements
from agent.state import AgentState
from core.pricing import calculate_line_item_cost, fuzzy_match_metric

REPORTER_SYSTEM_PROMPT = """
You are the **Final Reporter**.
Analyze the investigation history and User Validation (Pricing Context).

Generate a JSON report covering ALL 8 COST CATEGORIES and perform **FEATURE MAPPING**.

<PRICING_CONTEXT>
{pricing_context}
</PRICING_CONTEXT>

<REQUIRED_JSON_STRUCTURE>
{{
  "pricing_scratchpad": [
    {{ 
      "item_name": "Groq Llama-3",
      "user_string": "$0.05 per 1M tokens",
      "calculation": "0.05 / 1000000",
      "result_rate": 0.00000005
    }}
  ],
  "llm_calls": [
    {{ 
      "id": "llm_1", 
      "model": "gpt-4", 
      "entry_point": "app.py", 
      "api_call_location": "core/llm.py:20", 
      "estimated_calls_per_unit": 1, 
      "base_tokens": 100, 
      "max_tokens": 100,
      "user_rate": 0.00000005 
    }}
  ],
  "infrastructure": [
    {{ 
      "id": "infra_1",
      "category": "compute", 
      "name": "AWS Lambda", 
      "location": "infra/stack.ts",
      "metric": "invocations", 
      "estimated_volume": 100000,
      "user_rate": 0.0000002 
    }}
  ],
  "integrations": [],
  "data_components": [],
  "features": [
    {{
       "id": "feat_1",
       "name": "Intelligent Search",
       "description": "Allows users to search docs using AI",
       "cost_driver_ids": ["llm_1", "infra_1"]
    }}
  ],
  "estimates": {{ "monthly_cost_usd": 0.0 }}
}}
</REQUIRED_JSON_STRUCTURE>

**CRITICAL RULES FOR EXTRACTION:**

1. **USE THE SCRATCHPAD (MANDATORY):**
   - Before filling any `user_rate`, you MUST add an entry to `pricing_scratchpad`.
   - Copy the exact string the user said (e.g., "$0.05 per 1M").
   - Show your math division (e.g., "0.05 / 1000000").
   - Calculate the `result_rate` (price per 1 single unit).
   - COPY that `result_rate` into the `user_rate` field of the item.

2. **READ THE PRICING_CONTEXT CAREFULLY:**
   - The user's answers contain ACTUAL volumes and rates.
   - Example: "50,000 tokens/month" means `base_tokens: 50000` in llm_calls.
   - Example: "100k invocations" means `estimated_volume: 100000` in infrastructure.

3. **HANDLE "PER MILLION" RATES:**
   - **Input:** "$0.05 per 1M tokens"
   - **Math:** 0.05 / 1,000,000 = 0.00000005
   - **Output:** `user_rate: 0.00000005`
   - IF YOU MISS THIS CONVERSION, THE COST WILL BE WRONG.

4. **SMART CATEGORIZATION:**
   - **LLM/AI costs** go in `llm_calls` (tokens, model calls).
   - **Infrastructure** is for compute/storage (Lambda, S3, EC2, Docker).
   - **Integrations** are external APIs (Stripe, Twilio, Auth providers).
   - **Data components** are databases/caches (DynamoDB, Redis, Postgres).

5. **EXTRACT NUMBERS FROM NATURAL LANGUAGE:**
   - "fifty thousand" → 50000
   - "10k" → 10000
   - "around 250" → 250

6. **USER-PROVIDED RATES OVERRIDE EVERYTHING:**
   - If the user states a rate, USE IT. Do not look up knowledge base prices.
   - Leave `user_rate` at 0 ONLY if they didn't provide one.

7. **GENERATE IDs:** 
   - Short, unique IDs for every item (e.g., "L1", "I1", "INT1").

8. **MAP FEATURES:** 
   - Group cost drivers into business features.
   - Link them using `cost_driver_ids`.

9. **MANDATORY LOCATIONS:** 
   - Fill `location`, `entry_point`, `api_call_location` from chat history.
   - Look for patterns like "Found in `src/app.py`".

10. **DO NOT CALCULATE TOTALS:** 
   - Just fill inputs (volumes, rates). The system does the math.
   - Do NOT put values in the `estimates` section - leave it empty or just include placeholder.

**REMEMBER:** Your job is to accurately capture what the user told us. Be smart about units, conversions, and categorization. When in doubt, favor the user's explicit statements over assumptions.
"""

def sanitize_categories(data: Dict[str, Any]) -> Dict[str, Any]:
    """Maps invalid LLM-generated categories to the strict schema."""
    VALID_CATS = {
        "compute", "storage", "saas", "cicd",
        "vector_db", "scraping", "human", "other"
    }

    MAPPING = {
        "database": "storage", "db": "storage", "ci_cd": "cicd",
        "deployment": "cicd", "identity": "saas", "auth": "saas",
        "security": "saas", "networking": "compute", "network": "compute",
        "serverless": "compute", "ml": "compute"
    }

    for section in ["infrastructure", "integrations", "data_components"]:
        if section in data and isinstance(data[section], list):
            for item in data[section]:
                raw_cat = item.get("category", "other").lower()
                if raw_cat in MAPPING:
                    item["category"] = MAPPING[raw_cat]
                elif raw_cat in VALID_CATS:
                    item["category"] = raw_cat
                else:
                    item["category"] = "other"
    return data

def calculate_totals_with_engine(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses core/pricing.py to calculate actual costs.
    Now simplified since all prices are per single unit.
    """
    est = data.setdefault("estimates", {})
    est.setdefault("monthly_cost_usd", 0.0)

    total_usd = 0.0

    # Reset category breakdowns
    est["compute_cost"] = 0.0
    est["storage_cost"] = 0.0
    est["saas_cost"] = 0.0
    est["other_cost"] = 0.0
    est["llm_cost"] = 0.0 

    # 1. Calculate Infra/SaaS Costs
    for section in ["infrastructure", "integrations", "data_components"]:
        if section in data and isinstance(data[section], list):
            for item in data[section]:
                # Safety fixes
                try:
                    vol = item.get("estimated_volume")
                    item["estimated_volume"] = float(vol) if vol is not None else 0.0
                    
                    rate = item.get("user_rate")
                    item["user_rate"] = float(rate) if rate is not None else 0.0
                except (ValueError, TypeError):
                    item["estimated_volume"] = 0.0
                    item["user_rate"] = 0.0

                cost = calculate_line_item_cost(item)
                item["monthly_cost"] = round(cost, 4)
                total_usd += cost

                # Add to category breakdown
                cat = item.get("category", "other")
                if cat == "compute": est["compute_cost"] += cost
                elif cat == "storage": est["storage_cost"] += cost
                elif cat == "saas": est["saas_cost"] += cost
                else: est["other_cost"] += cost

    # 2. Calculate LLM Costs (SIMPLIFIED - no more division)
    total_tokens = 0
    calculated_llm_cost = 0.0

    if "llm_calls" in data and isinstance(data["llm_calls"], list):
        for call in data["llm_calls"]:
            try:
                vol_base = int(call.get("base_tokens") or 0)
                vol_max = int(call.get("max_tokens") or 0)
            except (ValueError, TypeError):
                vol_base = 0
                vol_max = 0
            
            vol = vol_base if vol_base > 0 else vol_max
            total_tokens += vol

            model_name = call.get("model", "unknown")
            result = fuzzy_match_metric(model_name)
            if not result:
                result = fuzzy_match_metric("tokens")

            # SIMPLIFIED: All prices are now per single unit (per token, not per 1K)
            if result:
                price_per_token = result['price_per_unit']  # Already per token!
                call_cost = vol * price_per_token  # Simple multiplication
            else:
                # Fallback: $0.000002 per token (was $0.002 per 1K)
                call_cost = vol * 0.000002
            
            calculated_llm_cost += call_cost

    est["monthly_token_estimate"] = total_tokens
    est["llm_cost"] = round(calculated_llm_cost, 4)
    total_usd += calculated_llm_cost

    est["monthly_cost_usd"] = round(total_usd, 2)
    return data

def reporter_node(state: AgentState):
    if state.verbose:
        print("\n📊 [Reporter] Generating verified report...")

    llm = get_llm(temperature=0)
    
    # Inject Pricing Context
    formatted_prompt = REPORTER_SYSTEM_PROMPT.format(
        pricing_context=state.pricing_context or "No user pricing provided."
    )
    
    msgs = [SystemMessage(content=formatted_prompt)] + state.messages

    try:
        response = llm.invoke(msgs)

        content = response.content
        if isinstance(content, list):
            content = "".join([b["text"] for b in content if "text" in b])

        match = re.search(r'\{.*\}', content.strip(), re.DOTALL)
        json_str = match.group(0) if match else content
        data = json.loads(json_str)

        # --- NUCLEAR OPTION: FORCE REGEX EXTRACTION ---
        # The LLM is inconsistent at writing 'user_rate' even if it knows the math.
        # We parse the user's text directly to find the rate.
        pricing_text = state.pricing_context or ""
        
        # Pattern 1: "$0.05 per 1M" or "$0.05 / 1M" or "$0.05 per million"
        # Regex groups: 1=price, 2=quantity, 3=suffix (M/k)
        # Example: "$0.05 per 1M" -> Price=0.05, Qty=1, Suffix=M
        price_pattern = re.search(r'\$([\d\.]+)\s*(?:per|/)\s*([\d\.,]+)\s*([kKmMbB]?)(?:\s*tokens?)?', pricing_text, re.IGNORECASE)
        
        if price_pattern:
            try:
                price = float(price_pattern.group(1))
                raw_qty = price_pattern.group(2).replace(',', '')
                multiplier = 1.0
                suffix = price_pattern.group(3).upper()
                
                if suffix == 'M' or 'MILLION' in pricing_text.upper(): multiplier = 1_000_000.0
                elif suffix == 'K': multiplier = 1_000.0
                elif suffix == 'B': multiplier = 1_000_000_000.0
                elif not suffix and float(raw_qty) < 100: # Assume 1M if they say "$0.05 per 1" implies unit? No, unsafe.
                     pass

                base_qty = float(raw_qty) * multiplier
                
                if base_qty > 0:
                    calculated_rate = price / base_qty
                    print(f"💰 [Reporter] Regex Override: Found ${price} per {base_qty:,.0f} -> ${calculated_rate:.10f}/unit")
                    
                    # Apply to all LLM calls if they lack a specific user rate
                    if "llm_calls" in data and isinstance(data["llm_calls"], list):
                        for item in data["llm_calls"]:
                            current_rate = item.get("user_rate", 0.0)
                            if current_rate == 0.0:
                                item["user_rate"] = calculated_rate
                                print(f"   -> Applied to {item.get('model', 'unknown')}")
            except Exception as e:
                print(f"⚠️ Pricing Regex Failed: {e}")
        # ----------------------------------------------

        data = sanitize_categories(data)
        data = calculate_totals_with_engine(data)

        data["repo"] = os.path.basename(os.path.abspath(state.repo_path))
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

        cost_data = CostElements(**data)

    except Exception as e:
        print(f"❌ Reporter Failed: {e}")
        cost_data = CostElements(
            repo="Error", 
            timestamp=str(datetime.now()),
            estimates={"monthly_cost_usd": 0.0}
        )

    out_dir = os.path.join(state.repo_path, "cost_analysis")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "cost_elements.json"), "w", encoding="utf-8") as f:
        f.write(cost_data.model_dump_json(indent=2))

    _write_markdown(cost_data, os.path.join(out_dir, "cost_report.md"))

    if state.verbose:
        print(f"✅ Report saved to {out_dir}")

    return {"final_report": cost_data.model_dump()}

def _write_markdown(data: CostElements, path: str):
    md = f"# Cost Discovery Report\n"
    md += f"**Repo:** {data.repo} | **Generated:** {data.timestamp}\n\n"

    md += f"## 💰 Est. Monthly Cost: ${data.estimates.monthly_cost_usd:,.2f}\n"
    md += f"*(Calculated using User Volumes + Custom Rates)*\n\n"

    md += "### 🧠 1. LLM & AI Logic\n"
    if data.estimates.llm_cost > 0:
        md += f"- **Total LLM Cost**: ${data.estimates.llm_cost:,.2f} (approx {data.estimates.monthly_token_estimate:,.0f} tokens)\n"
    
    if data.llm_calls:
        for item in data.llm_calls:
            vol = item.base_tokens + item.max_tokens
            if vol == 0 and item.base_tokens > 0: vol = item.base_tokens
            
            md += f"- **{item.model}**: ~{vol:,.0f} tokens/mo. Loc: `{item.entry_point}`\n"
    else:
        md += "No LLM calls detected.\n"

    def write_section(title, items):
        res = f"\n### {title}\n"
        if items:
            for item in items:
                cost_str = f"${item.monthly_cost:,.2f}"
                rate_info = f"@ ${item.user_rate}/unit" if item.user_rate > 0 else "(Standard Rate)"
                res += f"- **{item.name}**: {item.estimated_volume:,.0f} {item.metric} {rate_info} -> **{cost_str}**\n"
                if item.description:
                    res += f"  - *Context:* {item.description}\n"
        else:
            res += "None detected.\n"
        return res

    md += write_section("🏗️ 2. Infrastructure", data.infrastructure)
    md += write_section("🔌 3. Integrations", data.integrations)
    md += write_section("💾 4. Data & Compute", data.data_components)

    # Features section
    md += "\n### 🚀 5. Business Features (Mapped)\n"
    if data.features:
        for feat in data.features:
            md += f"- **{feat.name}**: {feat.description}\n"
            md += f"  - *Linked Drivers:* `{', '.join(feat.cost_driver_ids)}`\n"
    else:
        md += "No features mapped.\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
