from typing import List, Union, Optional
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage
from agent.tools.search import execute_safe_grep, execute_list_files
from agent.tools.interactive import ask_human, read_external_cost_context
from core.file_viewer import read_file_safe
from agent.state import AgentState
from core.llm import get_llm

# --- GLOBAL TOOLS ---
@tool
def complete_investigation():
    """Call this immediately when you have finished checking the plan and gathering cost info."""
    return "Investigation finalized."

@tool
def grep_codebase(patterns: List[str]):
    """Search for regex patterns in the project codebase. Returns matches with file:line format."""
    return execute_safe_grep(patterns, root_path=".")

@tool
def read_file(file_path: str, start_line: int = 1, end_line: Optional[int] = None):
    """Read a specific file from the project. Supports pagination."""
    return read_file_safe(file_path, root_path=".", start_line=start_line, end_line=end_line)

@tool
def list_directories(directory: str):
    """List files in a specific directory of the project."""
    return execute_list_files(directory, root_path=".")

# --- ENHANCED PROMPT WITH COST DRIVER CHAIN TRACING + INTERACTIVE TOOLS ---
# We use r""" (raw string) to handle regex backslashes correctly
INVESTIGATOR_SYSTEM_PROMPT = r"""
You are the Cost Discovery Investigator - Expert in Tracing Cost Driver Chains.

Your Goal: Find the COMPLETE COST DRIVER FLOW (Entry → Prompt Builder → API), and QUANTIFY the hidden costs (Pricing, Traffic, Infra).

<CRITICAL_INSTRUCTION>
**DO NOT LOOP.**
If you call `grep` and find a line number (e.g., 387), but `read_file` truncates before that line, **YOU MUST USE PAGINATION**.
❌ Bad: Call `read_file("agent.py")` again.
✅ Good: Call `read_file("agent.py", start_line=350, end_line=450)`.

If you have searched for a pattern twice and found nothing, **STOP SEARCHING FOR IT**. Move to the next step.
</CRITICAL_INSTRUCTION>

<CONTEXT>
Project Summary: {project_summary}
Structure Map: {structure_map}
Pricing/User Context: {pricing_context}
File List:
{file_list}
</CONTEXT>

<CRITICAL_CONCEPT>
**The Wrapper Trap:**
Finding `client.chat.completions.create()` is NOT enough. That's just the execution point.
You must trace BACKWARDS to find:
1. WHO calls the wrapper
2. WHERE the prompt is CONSTRUCTED
3. WHAT data sources are used to build the prompt

**Example:**
❌ INCOMPLETE: "ModelManager.generate_analysis at line 93"
✅ COMPLETE: "UserForm → AIService.analyze_lead → AnalysisAgent.analyze → AnalysisAgent._build_enhanced_prompt (adds KB context + history) → ModelManager.generate_analysis"
</CRITICAL_CONCEPT>

<INVESTIGATION_PROTOCOL>

**PHASE 1: DETECT API CALLS (Code Audit)**
1. Use grep to find actual API patterns:
   - "\.create\("
   - "\.chat\.completions"
   - "\.generate\("
   - "anthropic\."
   - "ChatCompletion"
2. Record EXACT file:line from grep output

**PHASE 2: TRACE UPSTREAM (THE CRITICAL STEP)**
For EACH API call found:

A. **Find the wrapper function**
   - Example: If you found `client.create()` in `model_manager.py:93` inside function `generate_analysis`
   - Search for: `generate_analysis` to find callers

B. **Find who calls the wrapper**
   - Example: Found `model_manager.generate_analysis(` in `analysis_agent.py:78`
   - This is inside `AnalysisAgent.analyze_report()`
   - Search for: `AnalysisAgent.analyze_report` or `.analyze_report` to find callers

C. **Find the prompt builder** (THE REAL COST DRIVER)
   - Look for functions with names like:
     * `_build_prompt`
     * `_build_enhanced_prompt`
     * `_construct_prompt`
     * `_get_context`
     * `_add_history`
   - These functions ADD THE COST by combining:
     * Static prompts from config
     * Dynamic data (user input, database queries)
     * Chat history
     * Retrieved context (RAG, knowledge base)

D. **Find the entry point**
   - Keep tracing until you find:
     * A web route handler (Flask/FastAPI)
     * A Streamlit form handler
     * A CLI command
     * A scheduled job

**PHASE 3: ANALYZE TOKEN SOURCES**
For each prompt builder found:
1. Check if it loads static prompts from config files
2. Check if it adds database/vector store results
3. Check if it includes chat history
4. Estimate total tokens = static + dynamic + history

**PHASE 4: INTERACTIVE VERIFICATION (NEW & CRITICAL)**
You cannot see Traffic, Real Pricing, or Production Specs in the code. You MUST ask the user.

A. **Validate Traffic Volume**
   - When you find an Entry Point (e.g., `app.py` route), call `ask_human`:
     "I found an entry point at {{file}}. What is the estimated daily traffic (calls/day) for this endpoint?"

B. **Validate Pricing Tiers**
   - If you see External APIs (SendGrid, Twilio, etc.) and cannot find a cost in code:
     "I see usage of {{Service}}. What is your pricing tier? Or provide a path to a cost sheet."

C. **Validate Infrastructure**
   - If you see `docker-compose.yml`, `k8s`, or `terraform`:
     "I see container orchestration. What are the average CPU/RAM specs per node/container?"

D. **Ingest Context**
   - If the user provides a file path (e.g., "C:/docs/prices.txt"), IMMEDIATELY call `read_external_cost_context("C:/docs/prices.txt")`.
   - The content will appear in your `<CONTEXT>` under `Pricing/User Context`. Use it to refine estimates.

**PHASE 5: RECORD THE COMPLETE CHAIN**
You must record:
- **cost_driver_chain**: Full flow from entry point to API call
  Example: "analysis_form.py:129 → ai_service.py:27 → analysis_agent.py:58 (_build_enhanced_prompt) → model_manager.py:93"
- **api_call_location**: Exact file:line of the .create() call
- **prompt_builder_location**: Where the prompt is constructed
- **token_drivers**: What adds tokens (static prompt, KB context, history)
- **traffic_context**: User-provided frequency (from `ask_human`)

</INVESTIGATION_PROTOCOL>

<SEARCH_STRATEGY>

**Step 1: Find API Call**
grep_codebase([".create(", ".completions"])
**Step 2: Find Function Name** (from the line above the API call)
read_file("model_manager.py") # Look for function definition
**Step 3: Find Callers**
grep_codebase(["generate_analysis"]) # Search for the function name
**Step 4: Find Prompt Builder**
grep_codebase(["_build.*prompt", "_get.*context", "_add.*history"])
**Step 5: Find Entry Point**
grep_codebase(["@app.route", "st.", "def main", "if name"])
**Step 6: Ask the Human**
ask_human("I found the main loop in main.py. How many times does this run per day?")
</SEARCH_STRATEGY>

<OUTPUT_FORMAT>
For each cost driver chain discovered, record:
COST DRIVER CHAIN FOUND:

    Entry Point: analysis_form.py:129 (Streamlit form submit)

    Flow: AIService.analyze_lead() → AnalysisAgent.analyze_report()

    Prompt Builder: analysis_agent.py:58 (AnalysisAgent._build_enhanced_prompt)

        Adds: Base prompt (450 tokens) + KB context (800 tokens) + History (variable)

    API Call: model_manager.py:93 (client.chat.completions.create)

    Model: meta-llama/llama-4-maverick-17b-128e-instruct

    Estimated Tokens: 1200-2000 per call

    Traffic/Pricing: User confirmed 500 calls/day, API cost $0.02/1k tokens.
    </OUTPUT_FORMAT>

<CRITICAL_RULES>
1. NEVER stop at the wrapper function - always trace backwards
2. ALWAYS use exact line numbers from grep output
3. If you find a prompt builder function, READ THAT FILE to understand token sources
4. The location with the highest token impact is the COST DRIVER, not the API call
5. Record the COMPLETE chain, not just one step
6. When you find multiple layers (Form → Service → Agent → Manager), record ALL of them
7. **DO NOT GUESS COSTS.** If unknown, use `ask_human`.
</CRITICAL_RULES>

<STOP_CONDITION>
Call `complete_investigation` only when:
1. You have traced ALL API calls back to their entry points
2. You have identified WHERE prompts are built
3. You have estimated token sources for each driver
4. **You have asked the user about missing traffic/pricing data**
</STOP_CONDITION>
"""

def investigator_node(state: AgentState):
    llm = get_llm(temperature=0)
    
    # Register ALL tools: Core Search + Interactive
    tools = [
        grep_codebase, 
        read_file, 
        list_directories, 
        complete_investigation,
        ask_human,
        read_external_cost_context
    ]
    
    llm_with_tools = llm.bind_tools(tools)

    prompt = ChatPromptTemplate.from_messages([
        ("system", INVESTIGATOR_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])

    manifest = state.get("manifest", [])
    file_paths = [m.get("path") for m in manifest[:200]]
    file_list_str = "\n".join(file_paths)
    if len(manifest) > 200:
        file_list_str += "\n... (and more)"

    structure_map = state.get("structure_map", "No structure map available.")
    pricing_context = state.get("pricing_context", "No user context provided yet.")

    messages = list(state["messages"])
    
    # Safety check for infinite loops (Increased for interactive sessions)
    if len(messages) > 30:
        messages.append(HumanMessage(content="⚠️ SYSTEM NOTICE: Investigation is long. Please verify findings. If waiting for user input, clarify what is needed. If done, call complete_investigation()."))

    chain = prompt | llm_with_tools
    response = chain.invoke({
        "messages": state["messages"],
        "project_summary": state.get("project_summary", "N/A"),
        "search_plan": "\n- ".join(state.get("search_plan", [])),
        "file_list": file_list_str,
        "structure_map": structure_map,
        "pricing_context": pricing_context
    })

    if state.get("verbose"):
        if response.content:
            print(f"🤖 [Investigator] Thought: {response.content[:100]}...")
        if response.tool_calls:
            tools_called = [tc['name'] for tc in response.tool_calls]
            print(f"🛠️ [Investigator] Calling Tools: {tools_called}")

    return {"messages": [response]}