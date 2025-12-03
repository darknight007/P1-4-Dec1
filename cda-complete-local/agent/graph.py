# agent/graph.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from agent.state import AgentState

# Import Nodes
from agent.nodes.recon import recon_node
from agent.nodes.specialists import architect_node, intelligence_node, integrator_node
from agent.nodes.validator import validator_node 
from agent.nodes.reporter import reporter_node

# Import Tool Set
from agent.tools.specialist_tools import SPECIALIST_TOOLS

def route_specialist(state: AgentState):
    """
    Router Logic with infinite loop protection and better edge case handling.
    """
    messages = state.messages
    
    if not messages:
        print("⚠️ [Router] No messages in state - defaulting to recon")
        return "recon"
        
    last_msg = messages[-1]
    
    # Infinite Loop Protection: Check for consecutive non-tool messages
    non_tool_count = 0
    for msg in reversed(messages[-10:]):  # Check last 10 messages
        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
            non_tool_count += 1
        else:
            break
    
    if non_tool_count >= 5:
        print(f"⚠️ [Router] Potential infinite loop detected in {state.active_specialist}")
        print(f"   Last {non_tool_count} messages had no tool calls - forcing phase transition")
        
        # Force phase completion to break the loop
        if state.active_specialist == "architect":
            print("   🔄 Force transitioning: architect → intelligence")
            return "intelligence"
        elif state.active_specialist == "intelligence":
            print("   🔄 Force transitioning: intelligence → integrator")
            return "integrator"
        elif state.active_specialist == "integrator":
            print("   🔄 Force transitioning: integrator → validator")
            return "validator"
        elif state.active_specialist == "validator":
            print("   🔄 Force transitioning: validator → reporter")
            return "reporter"
        else:
            print(f"   ⚠️ Unknown specialist: {state.active_specialist}, ending")
            return "reporter"
    
    # Normal routing: Check if any tool was called
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        # No tool called - stay in current specialist
        return state.active_specialist
    
    # Check tool calls for phase completion signals
    for tc in last_msg.tool_calls:
        tool_name = tc.get("name", "")
        
        # Standard Phase Completion Signal
        if tool_name == "complete_phase":
            # Phase Transitions
            if state.active_specialist == "architect":
                print("✅ [Router] Architect complete → Intelligence")
                return "intelligence"
            elif state.active_specialist == "intelligence":
                print("✅ [Router] Intelligence complete → Integrator")
                return "integrator"
            elif state.active_specialist == "integrator":
                print("✅ [Router] Integrator complete → Validator")
                return "validator"
            elif state.active_specialist == "validator":
                print("✅ [Router] Validator complete → Reporter")
                return "reporter"
            else:
                print(f"⚠️ [Router] Unknown specialist '{state.active_specialist}' called complete_phase")
                return "reporter"
        
        # Specific Validator Completion (Fallback if validator uses a custom tool)
        elif tool_name == "complete_validation":
            print("✅ [Router] Validation complete → Reporter")
            return "reporter"
        
        # Emergency Exit Signal (if specialists need to abort)
        elif tool_name == "emergency_exit":
            print("🚨 [Router] Emergency exit triggered → Reporter")
            return "reporter"
    
    # Default: Tools were called, route to tool node for execution
    return "tools"

def route_tools(state: AgentState):
    """
    Routes back from tools to the active specialist.
    Includes safety check to prevent routing to invalid specialist.
    """
    valid_specialists = ["architect", "intelligence", "integrator", "validator"]
    
    if state.active_specialist not in valid_specialists:
        print(f"⚠️ [Router] Invalid specialist '{state.active_specialist}', defaulting to architect")
        return "architect"
    
    return state.active_specialist

def build_graph(checkpointer=None):
    """
    Builds the LangGraph workflow with improved error handling and routing.
    """
    workflow = StateGraph(AgentState)
    
    # 1. Add Nodes
    workflow.add_node("recon", recon_node)
    workflow.add_node("architect", architect_node)
    workflow.add_node("intelligence", intelligence_node)
    workflow.add_node("integrator", integrator_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("reporter", reporter_node)
    workflow.add_node("tools", ToolNode(SPECIALIST_TOOLS))
    
    # 2. Define Edges
    
    # Entry Point
    workflow.set_entry_point("recon")
    workflow.add_edge("recon", "architect")
    
    # Architect Phase Loop
    workflow.add_conditional_edges(
        "architect",
        route_specialist,
        {
            "architect": "architect",      # Loop back for more investigation
            "tools": "tools",               # Execute tools
            "intelligence": "intelligence"  # Phase complete, advance
        }
    )
    
    # Intelligence Phase Loop
    workflow.add_conditional_edges(
        "intelligence",
        route_specialist,
        {
            "intelligence": "intelligence",  # Loop back for more investigation
            "tools": "tools",                 # Execute tools
            "integrator": "integrator"        # Phase complete, advance
        }
    )
    
    # Integrator Phase Loop
    workflow.add_conditional_edges(
        "integrator",
        route_specialist,
        {
            "integrator": "integrator",  # Loop back for more investigation
            "tools": "tools",             # Execute tools
            "validator": "validator"      # Phase complete, advance
        }
    )
    
    # Validator Phase Loop
    workflow.add_conditional_edges(
        "validator",
        route_specialist,
        {
            "validator": "validator",  # Loop back for more validation
            "tools": "tools",           # Execute tools
            "reporter": "reporter"      # Validation complete, generate report
        }
    )
    
    # Tools Return Logic (with validation)
    workflow.add_conditional_edges("tools", route_tools)
    
    # End: Reporter is final node
    workflow.add_edge("reporter", END)
    
    # Compile with checkpointer
    saver = checkpointer if checkpointer else MemorySaver()
    
    try:
        compiled_graph = workflow.compile(
            checkpointer=saver,
            interrupt_before=[],  # Can add nodes to pause before execution
            interrupt_after=[]    # Can add nodes to pause after execution
        )
        
        print("✅ [Graph] Workflow compiled successfully")
        return compiled_graph
        
    except Exception as e:
        print(f"❌ [Graph] Failed to compile workflow: {e}")
        raise

def get_graph_visualization():
    """
    Returns a visual representation of the graph flow (for debugging).
    """
    return """
    Graph Flow:
    
    recon
      ↓
    architect ⇄ tools
      ↓
    intelligence ⇄ tools
      ↓
    integrator ⇄ tools
      ↓
    validator ⇄ tools
      ↓
    reporter
      ↓
    END
    
    Loop Protection: Auto-advance after 5 consecutive non-tool messages
    """