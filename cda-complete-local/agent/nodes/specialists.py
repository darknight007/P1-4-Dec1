# agent/nodes/specialists.py

import uuid
import re
import json
from typing import List, Union
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, BaseMessage, HumanMessage
from pydantic import ValidationError
from agent.state import AgentState
from core.llm import get_llm
from agent.tools.specialist_tools import SPECIALIST_TOOLS
from agent.schemas.action_schema import AgentAction

# --- PROMPTS ---

ARCHITECT_PROMPT = """
You are the **Infrastructure Architect**. Phase 1 of 3.
**GOAL:** Identify the Compute, Storage, and CI/CD assets.

<CONTEXT>
{structure_map}
</CONTEXT>

<LEDGER_CONTEXT>
{ledger_dump}
</LEDGER_CONTEXT>

<INSTRUCTIONS>
1. **DETECT:** Frameworks (CDK, Serverless, Docker).
2. **SEARCH:** `grep_codebase` for "docker", "s3", "dynamodb", "lambda", "ec2".
3. **PRICE CHECKS:** Use `check_price_knowledge` for verified assets.
4. **DECIDE:** Output a Structured Action.

<EXAMPLE_OUTPUT>
{{
  "thought": "I see a Dockerfile mentioned in the structure. I need to search for Docker-related orchestration like docker-compose, ECS, or Kubernetes to understand the deployment setup.",
  "action_type": "call_tool",
  "tool_name": "grep_codebase",
  "tool_args": {{
    "patterns": ["docker-compose", "ECS", "Kubernetes", "kubectl"]
  }}
}}
</EXAMPLE_OUTPUT>

<CRITICAL_RULES>
- For grep_codebase you MUST ALWAYS set tool_args.patterns to a non-empty list like ["docker", "s3"].
- DO NOT invent new tools. Only use: grep_codebase, read_file, check_price_knowledge, complete_phase.
- If you cannot find what you're looking for after 2-3 searches, call complete_phase with your findings.
</CRITICAL_RULES>
</INSTRUCTIONS>
"""

INTELLIGENCE_PROMPT = """
You are the **AI Intelligence Officer**. Phase 2 of 3.
**GOAL:** Trace Cost Driver Chains (LLMs, Data).

<PREVIOUS_FINDINGS>
{last_summary}
</PREVIOUS_FINDINGS>

<LEDGER_CONTEXT>
{ledger_dump}
</LEDGER_CONTEXT>

<INSTRUCTIONS>
1. **FIND API CALLS:** `grep_codebase` for "ChatOpenAI", "bedrock", "anthropic".
2. **TRACE:** Find Prompt Builders.
3. **DECIDE:** Output a Structured Action.

<EXAMPLE_OUTPUT>
{{
  "thought": "I need to find LLM API calls. I'll search for common LLM client patterns.",
  "action_type": "call_tool",
  "tool_name": "grep_codebase",
  "tool_args": {{
    "patterns": ["ChatOpenAI", "bedrock", "anthropic", "openai.chat"]
  }}
}}
</EXAMPLE_OUTPUT>

<CRITICAL_RULES>
- For grep_codebase you MUST ALWAYS provide tool_args.patterns as a list: ["keyword1", "keyword2"].
- Use read_file to examine specific files after grep finds them.
</CRITICAL_RULES>
</INSTRUCTIONS>
"""

INTEGRATOR_PROMPT = """
You are the **Systems Integrator**. Phase 3 of 3.
**GOAL:** Find SaaS & Human-in-the-Loop.

<PREVIOUS_FINDINGS>
{last_summary}
</PREVIOUS_FINDINGS>

<LEDGER_CONTEXT>
{ledger_dump}
</LEDGER_CONTEXT>

<INSTRUCTIONS>
1. **SCAN:** requirements.txt for SaaS (Stripe, Twilio).
2. **CHECK:** Human processes ('approval', 'review').
3. **DECIDE:** Output a Structured Action.

<EXAMPLE_OUTPUT>
{{
  "thought": "I need to search for SaaS integrations like payment processors and communication services.",
  "action_type": "call_tool",
  "tool_name": "grep_codebase",
  "tool_args": {{
    "patterns": ["stripe", "twilio", "sendgrid", "mailgun"]
  }}
}}
</EXAMPLE_OUTPUT>

<CRITICAL_RULES>
- For grep_codebase you MUST ALWAYS provide tool_args.patterns as a list.
- When done, use finish_phase with a clear summary.
</CRITICAL_RULES>
</INSTRUCTIONS>
"""

def sanitize_history(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Ensures history is valid for Gemini strict alternation."""
    if not messages:
        return [HumanMessage(content="Resume analysis.")]

    clean_messages = list(messages)

    while clean_messages and not isinstance(clean_messages[0], HumanMessage):
        clean_messages.pop(0)

    if not clean_messages:
        return [HumanMessage(content="Resume analysis.")]

    return clean_messages

def smart_fuzzy_parse(response_text: str, role: str) -> AgentAction:
    """
    Intelligent fuzzy parser that only activates for genuinely broken output.
    First tries JSON parsing, then falls back to heuristics.
    """
    
    if not response_text or len(response_text.strip()) < 5:
        return AgentAction(
            thought=f"Empty response from {role}",
            action_type="finish_phase",
            phase_summary=f"{role.capitalize()} completed with limited findings"
        )
    
    # TIER 1: Try parsing as valid JSON
    try:
        # Clean common LLM JSON quirks
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        data = json.loads(cleaned.strip())
        
        # If it's valid AgentAction-like JSON, reconstruct it
        if isinstance(data, dict) and "thought" in data:
            return AgentAction(
                thought=data.get("thought", "Continuing analysis")[:500],
                action_type=data.get("action_type", "finish_phase"),
                tool_name=data.get("tool_name"),
                tool_args=data.get("tool_args", {}),
                human_question=data.get("human_question"),
                phase_summary=data.get("phase_summary", f"{role} complete")
            )
    except (json.JSONDecodeError, ValueError):
        pass  # Actually malformed, continue to heuristic parsing
    
    # TIER 2: Heuristic extraction for truly broken output
    thought = response_text[:300]
    text_lower = response_text.lower()
    
    # Pattern 1: Grep detection (but smarter - avoid false positives)
    if ("grep" in text_lower or "search for" in text_lower) and "pattern" in text_lower:
        # Extract only infrastructure keywords, not JSON keys
        infrastructure_keywords = [
            "docker", "kubernetes", "lambda", "ec2", "s3", "dynamodb", 
            "openai", "anthropic", "bedrock", "stripe", "twilio", "sendgrid"
        ]
        
        found_patterns = [kw for kw in infrastructure_keywords if kw in text_lower]
        
        if found_patterns:
            # Clean tool name immediately
            tool_name = "grep_codebase"  # Don't trust extracted name

            return AgentAction(
                thought=thought,
                action_type="call_tool",
                tool_name="grep_codebase",
                tool_args={"patterns": found_patterns[:5]}
            )
    
    # Pattern 2: Read file detection
    if "read" in text_lower and (".py" in response_text or ".txt" in response_text or ".yml" in response_text):
        file_match = re.search(r'([a-zA-Z0-9_/\-\.]+\.(?:py|js|ts|yml|yaml|json|txt))', response_text)
        if file_match:
            return AgentAction(
                thought=thought,
                action_type="call_tool",
                tool_name="read_file",  # Hardcode clean name
                tool_args={"file_path": file_match.group(1)}
            )
    
    # Pattern 3: Finish phase detection
    if any(kw in text_lower for kw in ["complete", "finish", "done", "phase 1", "phase 2", "phase 3"]):
        summary = response_text[:500] if len(response_text) > 100 else f"{role.capitalize()} analysis complete"
        return AgentAction(
            thought=thought,
            action_type="finish_phase",
            phase_summary=summary
        )
    
    # Default: Force finish to prevent loops
    return AgentAction(
        thought=f"Unable to parse {role} output clearly",
        action_type="finish_phase",
        phase_summary=f"{role.capitalize()} completed. Output: {response_text[:200]}"
    )

def try_constrained_decoding(llm_model_name: str, messages: List[BaseMessage]) -> AgentAction:
    """Attempt constrained decoding via outlines (optional)."""
    try:
        from outlines import models, generate
        
        model = models.text_generation(llm_model_name)
        generator = generate.json(model, AgentAction)
        
        prompt_text = "\n\n".join([
            f"{'System' if isinstance(m, SystemMessage) else 'Human' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
            for m in messages
        ])
        
        action = generator(prompt_text)
        return action
        
    except ImportError:
        raise ImportError("outlines library not available")
    except Exception as e:
        raise Exception(f"Constrained decoding failed: {e}")

def run_specialist(state: AgentState, prompt_template: str, role: str):
    """
    Production specialist with smart fallbacks and recursion guard.
    """
    
    # RECURSION GUARD: Stop after 3 fuzzy parse attempts
    fuzzy_count = state.fuzzy_parse_count
    if fuzzy_count >= 3:
        if state.verbose:
            print(f"\n   🚨 [{role.upper()}] Fuzzy parse budget exhausted. Forcing finish.")
        
        return {
            "messages": [AIMessage(
                content=f"{role} exhausted retry budget",
                tool_calls=[{
                    "name": "complete_phase",
                    "args": {"summary": f"{role.capitalize()} completed with partial findings due to parsing errors."},
                    "id": str(uuid.uuid4())
                }]
            )],
            "active_specialist": role,
            "fuzzy_parse_count": 0  # Reset for next specialist
        }
    
    # Prepare context
    ledger_dump = state.ledger.model_dump_json(indent=2)
    structure_map = state.structure_map if state.structure_map else "No structure map available."
    tree_context = structure_map[:20000]

    messages_list = state.messages if state.messages else []
    last_msg = messages_list[-1] if messages_list else None
    last_summary = last_msg.content if last_msg and "PHASE_COMPLETE" in str(last_msg.content) else "No previous summary."

    formatted_system = prompt_template.format(
        ledger_dump=ledger_dump,
        last_summary=last_summary,
        structure_map=tree_context
    )

    clean_history = sanitize_history(messages_list)
    messages = [SystemMessage(content=formatted_system)] + clean_history

    verbose = state.verbose
    if verbose:
        # --- FIX: Closed the print statement string below ---
        print(f"\n🤖 \033[1m[{role.upper()}] Thinking...\033[0m")

    # TIER 1: Constrained decoding
    try:
        llm_instance = get_llm(temperature=0)
        model_name = llm_instance.model_name if hasattr(llm_instance, 'model_name') else "gemini-2.5-flash-lite"
        
        action = try_constrained_decoding(model_name, messages)
        if verbose:
            print(f"\n   ✨ Constrained decoding success")
        return _convert_action_to_message(action, role, state)
    except ValueError as ve:
        # Critical config error (e.g. API key), re-raise immediately
        raise ve
    except (ImportError, Exception):
        pass

    # TIER 2: Structured output with retry
    # llm_instance is already retrieved above or we failed fast
    llm_with_schema = llm_instance.with_structured_output(AgentAction)
    
    for attempt in range(3):
        try:
            if verbose and attempt > 0:
                print(f"\n   🔄 Retry {attempt + 1}/3...")
            
            action = llm_with_schema.invoke(messages)
            
            if action is None:
                if verbose:
                    print(f"\n   ❌ LLM returned None")
                messages.append(HumanMessage(content="Your response was empty. Output valid AgentAction JSON."))
                continue
            
            if verbose:
                print(f"\n   ✅ Valid on attempt {attempt + 1}")
            
            return _convert_action_to_message(action, role, state)
            
        except ValueError as ve:
             raise ve
        except ValidationError as e:
            error_msg = str(e).split('\n')[0]
            if 'default_api:' in error_msg:
                error_msg = error_msg.replace('default_api:', '')
            
            if verbose:
                print(f"\n   ❌ Validation error: {error_msg[:80]}")
            
            messages.append(HumanMessage(content=f"VALIDATION ERROR: {error_msg}\nFix and output valid JSON."))
            
        except Exception as e:
            if verbose:
                print(f"\n   ⚠️ Error: {str(e)[:80]}")
            continue

    # TIER 3: Smart fuzzy parsing
    if verbose:
        print(f"\n   🔧 Attempting smart fuzzy parse...")
    
    try:
        raw_llm = get_llm(temperature=0)
        raw_response = raw_llm.invoke(messages)
        
        response_text = ""
        if hasattr(raw_response, 'content'):
            if isinstance(raw_response.content, str):
                response_text = raw_response.content
            elif isinstance(raw_response.content, list):
                response_text = " ".join([b.get("text", "") for b in raw_response.content if isinstance(b, dict)])
        
        if response_text:
            action = smart_fuzzy_parse(response_text, role)
            
            if verbose:
                print(f"\n   ✅ Fuzzy: {action.action_type} -> {action.tool_name or 'finish'}")
            
            # Increment fuzzy counter
            new_state = _convert_action_to_message(action, role, state)
            new_state["fuzzy_parse_count"] = fuzzy_count + 1
            
            if verbose:
                print(f"\n   📊 [MONITORING] Fuzzy parse {fuzzy_count + 1}/3 for {role}")
            
            return new_state
    except Exception as e:
        if verbose:
            print(f"\n   ⚠️ Fuzzy failed: {str(e)[:80]}")

    # TIER 4: Force finish
    if verbose:
        print(f"\n   🚨 All tiers failed. Forcing finish.")
    
    fallback_action = AgentAction(
        thought=f"Technical difficulties in {role}",
        action_type="finish_phase",
        phase_summary=f"{role.capitalize()} completed with partial findings."
    )
    
    result = _convert_action_to_message(fallback_action, role, state)
    result["fuzzy_parse_count"] = 0  # Reset
    return result

def _convert_action_to_message(action: AgentAction, role: str, state: AgentState) -> dict:
    """Convert AgentAction to AIMessage with tool_calls."""
    tool_calls = []

    if action.action_type == "call_tool":
        if action.tool_name:
            clean_tool_name = action.tool_name.split(":")[-1] if ":" in action.tool_name else action.tool_name
            
            tool_calls.append({
                "name": clean_tool_name,
                "args": action.tool_args or {},
                "id": str(uuid.uuid4())
            })

    elif action.action_type == "ask_human":
        tool_calls.append({
            "name": "ask_human",
            "args": {"question": action.human_question or "Confirm finding?"},
            "id": str(uuid.uuid4())
        })

    elif action.action_type == "finish_phase":
        tool_calls.append({
            "name": "complete_phase",
            "args": {"summary": action.phase_summary or "Phase Complete."},
            "id": str(uuid.uuid4())
        })

    ai_message = AIMessage(content=action.thought, tool_calls=tool_calls)

    return {"messages": [ai_message], "active_specialist": role}

# --- EXPORTED NODES ---

def architect_node(state: AgentState):
    return run_specialist(state, ARCHITECT_PROMPT, "architect")

def intelligence_node(state: AgentState):
    return run_specialist(state, INTELLIGENCE_PROMPT, "intelligence")

def integrator_node(state: AgentState):
    return run_specialist(state, INTEGRATOR_PROMPT, "integrator")