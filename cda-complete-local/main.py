# main.py

import os
import argparse
import sys
import uuid
from dotenv import load_dotenv
from langchain_core.messages import ToolMessage

# Load env before imports
load_dotenv()

from core.ingestion import run_ingestion
from agent.graph import build_graph

# --- NEW IMPORTS FOR BROKER ---
from core.task_broker import TaskBroker
from agent.tools.search import set_broker

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Cost Discovery Agent: Sequential Specialist Pipeline."
    )
    parser.add_argument("path", type=str, help="Path to the local repository to analyze")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed logging")
    return parser.parse_args()

def get_multiline_input(prompt: str) -> str:
    """
    Captures multi-line input from the user.
    Stops when the user presses Enter on an empty line or types 'DONE'.
    """
    print(f"{prompt} (Paste your text, then press Enter on an empty line to send)")
    print("\033[1m👤 Answer:\033[0m ", end="", flush=True)
    
    lines = []
    while True:
        try:
            line = input()
            # specific check to allow finishing input
            if line.strip() == "" or line.strip().upper() == "DONE":
                if not lines: # If they just hit enter at start, keep waiting or accept empty?
                    # If empty, let's assume they want to skip or are confused, but let's break to avoid hang
                    break
                break
            lines.append(line)
        except EOFError:
            break
            
    return "\n".join(lines)

def main():
    args = parse_arguments()
    repo_path = os.path.abspath(args.path)

    if not os.path.exists(repo_path) or not os.path.isdir(repo_path):
        print(f"❌ Error: The path '{repo_path}' does not exist.")
        sys.exit(1)

    print(f"\n🚀 \033[1mStarting Cost Discovery Agent\033[0m")
    print(f"📂 Target: {repo_path}")

    original_cwd = os.getcwd()
    try:
        os.chdir(repo_path)
    except Exception as e:
        print(f"❌ Error changing directory: {e}")
        sys.exit(1)

    # 1. INITIALIZE BROKER
    print("\n🔌 Initializing Task Broker...")
    broker = TaskBroker(max_workers=4, repo_root=".")
    set_broker(broker) # Injects broker into search tools
    print("✅ Broker Ready.")

    # 2. Ingestion
    try:
        print("\n--- Phase A: Ingestion ---")
        ingest_data = run_ingestion(".")
        stats = ingest_data["stats"]
        priority_files = ingest_data["priority_files"]

        print(f"✅ Ingestion Complete ({stats['file_count']} files).")
    except Exception as e:
        print(f"❌ Critical Error during Ingestion: {e}")
        sys.exit(1)

    # 3. Initialize State
    initial_state = {
        "repo_path": ".",
        "verbose": args.verbose,
        "manifest": ingest_data["manifest"],
        "priority_files": priority_files,
        # Ensure structure_map is populated
        "structure_map": ingest_data.get("structure_map", ""),
        "pricing_context": "",
        "active_specialist": "architect",
        "messages": []
    }

    # 4. Run Graph
    print("\n--- Phase B: AI Investigation (Interactive) ---")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

    app = build_graph()
    app.update_state(config, initial_state)

    try:
        current_input = None

        while True:
            events = app.stream(current_input, config=config, stream_mode="values")

            for event in events:
                pass

            snapshot = app.get_state(config)
            if not snapshot.next:
                print("\n✅ Investigation Finished.")
                final_state = snapshot.values
                break

            # Check for Interruption (Tools)
            last_message = snapshot.values["messages"][-1]
            if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
                current_input = None
                continue

            tool_calls = last_message.tool_calls
            human_call_found = False

            # Intercept 'ask_human'
            for tool_call in tool_calls:
                if tool_call["name"] == "ask_human":
                    human_call_found = True
                    question = tool_call["args"].get("question", "Clarification needed?")
                    print(f"\n\033[93m🤔 Agent Asks:\033[0m {question}")

                    # USE NEW MULTILINE INPUT FUNCTION
                    user_answer = get_multiline_input("")

                    tool_message = ToolMessage(
                        tool_call_id=tool_call["id"],
                        content=f"User Answer: {user_answer}"
                    )

                    # Update pricing context with the answer
                    current_pricing = snapshot.values.get("pricing_context", "")
                    new_pricing = current_pricing + f"\nQ: {question}\nA: {user_answer}\n"

                    app.update_state(
                        config,
                        {
                            "messages": [tool_message],
                            "pricing_context": new_pricing
                        },
                        as_node="tools"
                    )
                    print("   ✅ Resuming...")

            if human_call_found:
                current_input = None
            else:
                pass # Let ToolNode execute other tools

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    except Exception as e:
        print(f"\n❌ Runtime Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        os.chdir(original_cwd)

    if 'final_state' in locals() and final_state.get("final_report"):
        print(f"\n🎉 Success! Report saved to cost_analysis/")
    else:
        print("\n⚠️ Done.")

if __name__ == "__main__":
    main()