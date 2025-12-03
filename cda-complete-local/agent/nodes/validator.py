# agent/nodes/validator.py

from langchain_core.messages import SystemMessage
from agent.state import AgentState
from core.llm import get_llm
from agent.tools.specialist_tools import SPECIALIST_TOOLS

VALIDATOR_PROMPT = """
You are the **Cost Validator**. 
Your job is to review findings and **INTERVIEW THE USER** to fill in missing data.

**CRITICAL RULE:** 
You are **MUTED**. The user cannot see your "thought" text.
To talk to the user, you **MUST** call the tool `ask_human(question="...")`.
If you generate text without calling `ask_human`, the user will see NOTHING and the process will fail.

**GOAL:** Ensure every found cost driver has a Volume AND a Price.
**INPUT:** The Ledger of findings from previous agents.

<LEDGER_CONTEXT>
{ledger_dump}
</LEDGER_CONTEXT>

<PRICING_CONTEXT>
{pricing_context}
</PRICING_CONTEXT>

<INSTRUCTIONS>
1. **Distinguish Capability vs Activity:**
   - Ignore services found only in `.md`/`.txt` unless confirmed in code/config.

2. **Check Price Availability:**
   - Call `check_price_knowledge(metric="...")` for items.
   - If "Price UNKNOWN", add a question for the user: "What is your rate?"

3. **Execute the Interview:**
   - Compile your questions into a single list.
   - **CALL `ask_human`** with that list. 
   - Do NOT just "think" the questions.

4. **Review User Answers:**
   - If you've already asked the user and they responded, review the PRICING_CONTEXT above.
   - The user's answers contain volume and rate information.
   - Proceed to `complete_validation` once you have sufficient information.

5. **Finalize:**
   - Once you have the volumes/rates from the user, call `complete_validation`.
</INSTRUCTIONS>
"""

def validator_node(state: AgentState):
    """
    Validator that asks user for missing volumes/prices.
    The REPORTER will extract the actual values from pricing_context.
    """
    llm = get_llm(temperature=0).bind_tools(SPECIALIST_TOOLS)

    ledger_dump = state.ledger.model_dump_json(indent=2)
    pricing_context = state.pricing_context if state.pricing_context else "No user input yet."
    
    formatted_prompt = VALIDATOR_PROMPT.format(
        ledger_dump=ledger_dump,
        pricing_context=pricing_context
    )
    
    messages = [SystemMessage(content=formatted_prompt)] + state.messages

    response = llm.invoke(messages)

    if state.verbose:
        print(f"\n👮 \033[1m[VALIDATOR] Reasoning:\033[0m")
        content_to_print = ""
        if isinstance(response.content, list):
            for block in response.content:
                if isinstance(block, dict) and "text" in block:
                    content_to_print += block["text"]
        elif isinstance(response.content, str):
            content_to_print = response.content
            
        if content_to_print:
             print(f"   \"{content_to_print[:200]}...\"")

        if response.tool_calls:
            tools = [t['name'] for t in response.tool_calls]
            print(f"🛠️  \033[1m[VALIDATOR] Calling Tools:\033[0m {tools}")

    return {
        "messages": [response], 
        "active_specialist": "validator"
    }
