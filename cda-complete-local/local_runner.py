import os
import sys
import json
import time
import uuid
import shutil
import subprocess
import re
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load env BEFORE anything else
load_dotenv()

# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# FORCE LOCAL MODE
os.environ["SCROOGE_ENV"] = "LOCAL"

from core.infrastructure import infra
from schemas.analysis_models import InvestigationLedger
from agent.tools.specialist_tools import HumanInputNeeded

# --- Configuration ---
# We rely on infrastructure.py to set up the DB and paths
DATA_DIR = os.path.join(os.path.dirname(current_dir), "data")
SCANS_DIR = os.path.join(DATA_DIR, "scans")
os.makedirs(SCANS_DIR, exist_ok=True)

# Set Environment Variables for Child Processes/Modules
os.environ["AWS_REGION"] = "local"
os.environ["UPLOAD_BUCKET"] = "local-bucket"
os.environ["TABLE_SCAN_STATE"] = "ScroogeScanState"
os.environ["TABLE_TARGETS"] = "ScroogeTargets"
os.environ["TABLE_KNOWLEDGE_BASE"] = "ScroogeKnowledgeBase"

class LocalRunner:
    def __init__(self):
        self.scan_table = infra.get_table("ScroogeScanState")
        self.targets_table = infra.get_table("ScroogeTargets")
        print("🚀 Scrooge Local Runner initialized.")

    def update_scan_status(self, scan_id: str, status: str, message: str = "", current_question: str = "", repo_name: str = "", repo_url: str = ""):
        print(f"[{status}] {scan_id[:8]}...: {message}")
        
        update_expr = "SET #status = :status, last_updated = :ts, message = :msg"
        vals = {
            ":status": status,
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":msg": message
        }
        
        if current_question:
            update_expr += ", current_question = :q"
            vals[":q"] = current_question
        if repo_name:
            update_expr += ", repo_name = :rn"
            vals[":rn"] = repo_name
        if repo_url:
            update_expr += ", repo_url = :ru"
            vals[":ru"] = repo_url
            
        self.scan_table.update_item(
            Key={"scan_id": scan_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=vals
        )

    def clone_repo(self, repo_url: str, target_dir: str) -> bool:
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir)
        
        try:
            print(f"⬇️ Cloning {repo_url}...")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, target_dir],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                return True
            print(f"❌ Git clone failed: {result.stderr}")
        except Exception as e:
            print(f"❌ Git failed: {e}")
        return False

    def run_scan(self, scan_id: str, repo_url: str, is_resume: bool = False, resume_answer: str = None):
        scan_dir = os.path.join(SCANS_DIR, scan_id)
        repo_dir = os.path.join(scan_dir, "repo")
        checkpoint_db = os.path.join(scan_dir, "checkpoints.sqlite")
        
        os.makedirs(scan_dir, exist_ok=True)
        
        # Prepare Repo Name
        repo_name_match = re.search(r'/([^/]+?)(\.git)?$', repo_url)
        repo_name = repo_name_match.group(1) if repo_name_match else "unknown_repo"
        repo_name = re.sub(r'[^a-zA-Z0-9\-_]', '', repo_name)

        if not is_resume:
            self.update_scan_status(scan_id, "RUNNING", "Cloning repository...", repo_name=repo_name, repo_url=repo_url)
            if not self.clone_repo(repo_url, repo_dir):
                self.update_scan_status(scan_id, "FAILED", "Clone failed")
                return
        else:
             self.update_scan_status(scan_id, "RUNNING", "Resuming...", repo_name=repo_name)

        # Setup Env
        os.environ["REPO_PATH"] = repo_dir
        
        # Initialize LangGraph with persistent SQLite
        conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
        
        try:
            # Save CWD
            old_cwd = os.getcwd()
            os.chdir(repo_dir)
            
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver
                from core.ingestion import run_ingestion
                from core.task_broker import TaskBroker
                from agent.tools.search import set_broker
                from agent.graph import build_graph
                from langchain_core.messages import ToolMessage, HumanMessage
                
                memory = SqliteSaver(conn)
                app = build_graph(checkpointer=memory)
                config = {"configurable": {"thread_id": scan_id}, "recursion_limit": 200}
                
                initial_state = None
                
                if not is_resume:
                    # Fresh Start
                    broker = TaskBroker(max_workers=1, repo_root=".")
                    set_broker(broker)
                    
                    ingest_data = run_ingestion(".")
                    
                    initial_state = {
                        "repo_path": ".",
                        "manifest": ingest_data["manifest"],
                        "priority_files": ingest_data["priority_files"],
                        "structure_map": ingest_data["structure_map"],
                        "pricing_context": "",
                        "active_specialist": "architect",
                        "messages": [],
                        "ledger": InvestigationLedger(),
                        "verbose": True,
                        "project_summary": "",
                        "regex_findings": "",
                        "search_plan": [],
                        "final_report": {},
                        "fuzzy_parse_count": 0
                    }
                else:
                    # Resume Logic
                    snapshot = app.get_state(config)
                    if not snapshot.values:
                        print("❌ No snapshot found for resume.")
                        return

                    last_message = snapshot.values.get("messages", [])[-1]
                    
                    # Inject Answer
                    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                         # Try to find the tool call ID
                         tool_call_id = last_message.tool_calls[0]['id']
                         answer_msg = ToolMessage(content=f"User Answer: {resume_answer}", tool_call_id=tool_call_id)
                         app.update_state(config, {"messages": [answer_msg]}, as_node="tools")
                    else:
                         app.update_state(config, {"messages": [HumanMessage(content=f"Answer: {resume_answer}")]})
                    
                    initial_state = None # Continue from state

                # Execution Loop
                iterator = app.stream(initial_state, config=config, stream_mode="values")
                
                for step in iterator:
                    messages = step.get("messages", [])
                    if messages:
                        last = messages[-1]
                        content = getattr(last, 'content', '')
                        self.update_scan_status(scan_id, "RUNNING", str(content)[:60], repo_name=repo_name)
                
                # Completion
                self.finalize_report(repo_dir, scan_id, repo_name)
                self.update_scan_status(scan_id, "COMPLETED", "Analysis Complete", repo_name=repo_name)
                
                # Update Target Status
                self.targets_table.update_item(
                    Key={"repo_url": repo_url},
                    UpdateExpression="SET #status = :s",
                    ExpressionAttributeValues={":s": "COMPLETED"}
                )
                
            except HumanInputNeeded as e:
                self.update_scan_status(scan_id, "PAUSED", "Waiting for input", current_question=e.question, repo_name=repo_name)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.update_scan_status(scan_id, "FAILED", str(e))
            finally:
                os.chdir(old_cwd)
                
        finally:
            conn.close()

    def finalize_report(self, repo_dir, scan_id, repo_name):
        src = os.path.join(repo_dir, "cost_analysis", "cost_elements.json")
        if os.path.exists(src):
            dest = os.path.join(DATA_DIR, "results", repo_name, scan_id, "report.json")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(src, dest)
            print(f"📄 Report saved to {dest}")

    def poll(self):
        """Main Loop."""
        print(f"👀 Polling for jobs... (DB: {os.path.join(DATA_DIR, 'scrooge.db')})")
        while True:
            try:
                # 1. Check for Resume Actions
                scans = self.scan_table.scan(
                    FilterExpression="#status = :s",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":s": "RESUME_QUEUED"}
                )["Items"]
                
                if scans:
                    scan = scans[0]
                    print(f"🔄 Resuming scan {scan['scan_id']}")
                    answer = scan.get("pending_answer", "")
                    self.run_scan(scan['scan_id'], scan['repo_url'], is_resume=True, resume_answer=answer)
                    continue
                
                # 2. Check for Queued Targets (High Priority)
                targets = self.targets_table.scan(
                    FilterExpression="#status = :s",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":s": "QUEUED"}
                )["Items"]
                
                if targets:
                    target = targets[0]
                    print(f"🎯 Found target: {target['repo_url']}")
                    scan_id = str(uuid.uuid4())
                    
                    # Mark RUNNING
                    self.targets_table.update_item(
                        Key={"repo_url": target['repo_url']},
                        UpdateExpression="SET #status = :s, current_scan_id = :id",
                        ExpressionAttributeValues={":s": "RUNNING", ":id": scan_id}
                    )
                    
                    self.run_scan(scan_id, target['repo_url'])
                    continue
                
                # 3. Check for NEW Targets (Optional Auto-run)
                # Uncomment if you want auto-runner behavior
                # targets_new = self.targets_table.scan(
                #     FilterExpression="#status = :s",
                #     ExpressionAttributeNames={"#status": "status"},
                #     ExpressionAttributeValues={":s": "NEW"}
                # )["Items"]
                # if targets_new: ...
                
                time.sleep(2)
                
            except KeyboardInterrupt:
                print("\n🛑 Stopping runner...")
                break
            except Exception as e:
                print(f"\n⚠️ Poll Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    runner = LocalRunner()
    runner.poll()
