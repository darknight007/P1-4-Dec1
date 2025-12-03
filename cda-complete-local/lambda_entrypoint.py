# lambda_entrypoint.py
import os
import sys
import json
import sqlite3
import shutil
import uuid
import zipfile
import io
import time
from datetime import datetime, timezone
from typing import Dict, Any
import subprocess
import re
import urllib.request
from botocore.exceptions import ClientError
from core.infrastructure import infra

# Environment Variables
MOUNT_PATH = os.environ.get("MOUNT_PATH", "/tmp")
UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "scrooge-cost-reports")
TABLE_SCAN_STATE = os.environ.get("TABLE_SCAN_STATE", "ScroogeScanState")
TABLE_TARGETS = os.environ.get("TABLE_TARGETS", "ScroogeTargets")
TABLE_KNOWLEDGE_BASE = os.environ.get("TABLE_KNOWLEDGE_BASE", "ScroogeKnowledgeBase")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# AWS Clients via Infra
dynamodb = None # Lazy loaded via infra if needed directly, but we prefer infra.get_table
s3_client = infra.get_s3_client()
scan_state_table = infra.get_table(TABLE_SCAN_STATE)
targets_table = infra.get_table(TABLE_TARGETS)

# Custom Exception for Human Input
class HumanInputNeeded(Exception):
    def __init__(self, question: str):
        self.question = question
        super().__init__(f"Human input required: {question}")

# --- DynamoDB State Management ---
def update_scan_status(
    scan_id: str,
    status: str,
    message: str = "",
    current_question: str = "",
    repo_name: str = "",
    repo_url: str = ""
):
    """Updates scan status in DynamoDB."""
    try:
        update_expr_parts = ["#status = :status", "last_updated = :ts", "message = :msg"]
        expr_attr_names = {"#status": "status"}
        expr_attr_values = {
            ":status": status,
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":msg": message
        }
        if current_question:
            update_expr_parts.append("current_question = :q")
            expr_attr_values[":q"] = current_question
        if repo_name:
            update_expr_parts.append("repo_name = :rn")
            expr_attr_values[":rn"] = repo_name
        if repo_url:
            update_expr_parts.append("repo_url = :ru")
            expr_attr_values[":ru"] = repo_url
        
        scan_state_table.update_item(
            Key={"scan_id": scan_id},
            UpdateExpression=f"SET {', '.join(update_expr_parts)}",
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values
        )
    except Exception as e:
        print(f"⚠️ Failed to update scan state: {e}")

def mark_target_complete(repo_url: str):
    """Marks target as completed in targets table."""
    try:
        targets_table.update_item(
            Key={"repo_url": repo_url},
            UpdateExpression="SET #status = :completed, last_queued = :ts",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":completed": "COMPLETED",
                ":ts": datetime.now(timezone.utc).isoformat()
            }
        )
    except Exception as e:
        print(f"⚠️ Failed to mark target complete: {e}")

# --- Git & S3 Brain Management ---
def clone_repo(repo_url: str, target_dir: str) -> bool:
    """Clones repo or downloads ZIP if git unavailable."""
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, target_dir],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            return True
    except Exception as e:
        print(f"⚠️ Git binary not found or failed. Attempting Zip Download fallback...")
    
    # Fallback: Download ZIP
    try:
        if "github.com" in repo_url:
            zip_url = repo_url.rstrip('/') + "/archive/refs/heads/main.zip"
            print(f"⬇️ Downloading Zip: {zip_url}")
            
            response = urllib.request.urlopen(zip_url, timeout=60)
            zip_data = response.read()
            
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                z.extractall(target_dir)
            
            # Github zips create a root folder like 'repo-main', move contents up
            extracted_folders = [f for f in os.listdir(target_dir) if os.path.isdir(os.path.join(target_dir, f))]
            if len(extracted_folders) == 1:
                extracted_path = os.path.join(target_dir, extracted_folders[0])  
                for item in os.listdir(extracted_path):
                    shutil.move(os.path.join(extracted_path, item), target_dir)
                os.rmdir(extracted_path)
            
            return True
    except Exception as e:
        print(f"❌ ZIP download failed: {e}")
        return False

def sync_db_from_s3(scan_id: str, repo_name: str):
    """Downloads checkpoint DB from S3 if exists."""
    local_db_path = "/tmp/checkpoints.sqlite"
    s3_key = f"scans/{repo_name}/{scan_id}/checkpoints/brain.sqlite"
    
    try:
        s3_client.download_file(UPLOAD_BUCKET, s3_key, local_db_path)
        print(f"🧠 Restored brain from S3: {s3_key}")
    except Exception as e:
        if "404" in str(e) or "NoSuchKey" in str(e) or "Not Found" in str(e):
            print(f"🧠 New brain: {scan_id}")
        else:
            print(f"⚠️ Brain restore failed: {e}")

def sync_db_to_s3(scan_id: str, repo_name: str, max_retries=3):
    """Uploads checkpoint DB to S3 with retry logic."""
    local_db_path = "/tmp/checkpoints.sqlite"
    s3_key = f"scans/{repo_name}/{scan_id}/checkpoints/brain.sqlite"
    
    if not os.path.exists(local_db_path):
        print("⚠️ No brain file to save")
        return
    
    for attempt in range(max_retries):
        try:
            s3_client.upload_file(local_db_path, UPLOAD_BUCKET, s3_key)
            print(f"💾 Saved brain: {s3_key}")
            return
        except ClientError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"⚠️ S3 upload failed (attempt {attempt+1}/{max_retries}), retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Brain save failed after {max_retries} attempts: {e}")

def finalize_report(repo_dir: str, scan_id: str, repo_name: str):
    """Uploads cost report to S3."""
    report_path = os.path.join(repo_dir, "cost_analysis", "cost_elements.json")
    
    if not os.path.exists(report_path):
        print("⚠️ No report found to upload.")
        return
    
    try:
        s3_key = f"results/{repo_name}/{scan_id}/report.json"
        s3_client.upload_file(report_path, UPLOAD_BUCKET, s3_key)
        print(f"🎉 Report Uploaded: {s3_key}")
    except Exception as e:
        print(f"❌ Report upload failed: {e}")

def replace_ask_human_tool():
    """Replaces ask_human in SPECIALIST_TOOLS with Lambda pause handler (idempotent)."""
    try:
        from agent.tools import specialist_tools
        from langchain_core.tools import tool as tool_decorator
        
        # Check if already replaced (idempotent)
        for tool in specialist_tools.SPECIALIST_TOOLS:
            if hasattr(tool, 'name') and tool.name == 'ask_human_lambda':
                print("✅ ask_human already replaced (skipping)")
                return True
        
        # Define the new tool logic
        @tool_decorator
        def ask_human_lambda(question: str, context: str = "") -> str:
            """Lambda version that raises exception to pause scan."""
            raise HumanInputNeeded(question)
        
        # Find and replace in-place
        for idx, tool in enumerate(specialist_tools.SPECIALIST_TOOLS):
            if hasattr(tool, 'name') and tool.name == 'ask_human':
                specialist_tools.SPECIALIST_TOOLS[idx] = ask_human_lambda
                print("✅ Replaced ask_human in SPECIALIST_TOOLS")
                return True
        
        # If original not found, it might have been replaced already but with different name
        print("⚠️ Original ask_human not found (might be already replaced)")
        return True
        
    except Exception as e:
        print(f"❌ Failed to replace ask_human tool: {e}")
        return False

def should_restore_brain(repo_url: str, scan_id: str, repo_name: str) -> bool:
    """
    Only restore brain checkpoint if:
    1. Scan was interrupted (RUNNING/PAUSED status)
    2. Brain file actually exists in S3
    """
    try:
        response = targets_table.get_item(Key={"repo_url": repo_url})
        item = response.get('Item')
        
        if not item:
            print(f"🆕 No existing target found - starting fresh scan")
            return False
        
        status = item.get('status', 'NEW')
        
        if status in ["RUNNING", "PAUSED"]:
            # Double-check brain actually exists in S3
            s3_key = f"scans/{repo_name}/{scan_id}/checkpoints/brain.sqlite"
            try:
                s3_client.head_object(Bucket=UPLOAD_BUCKET, Key=s3_key)
                print(f"♻️ Target status: {status} + Brain exists - will restore")
                return True
            except:
                print(f"⚠️ Status is {status} but brain missing - starting fresh")
                return False
        else:
            print(f"🆕 Target status: {status} - starting fresh scan")
            return False
            
    except Exception as e:
        print(f"⚠️ Could not check target status: {e} - defaulting to fresh scan")
        return False

def delete_brain_if_exists(scan_id: str, repo_name: str):
    """Deletes brain checkpoint from S3 to force fresh scan."""
    s3_key = f"scans/{repo_name}/{scan_id}/checkpoints/brain.sqlite"
    local_db_path = "/tmp/checkpoints.sqlite"
    
    try:
        s3_client.delete_object(Bucket=UPLOAD_BUCKET, Key=s3_key)
        print(f"🗑️ Deleted old brain from S3: {s3_key}")
    except s3_client.exceptions.NoSuchKey:
        pass
    except Exception as e:
        print(f"⚠️ Could not delete S3 brain: {e}")
    
    try:
        if os.path.exists(local_db_path):
            os.remove(local_db_path)
            print(f"🗑️ Deleted local brain: {local_db_path}")
    except Exception as e:
        print(f"⚠️ Could not delete local brain: {e}")

# --- Core Scan Logic ---
def handle_scan(event_body: Dict[str, Any]) -> Dict[str, Any]:
    """Handles initial scan request."""
    start_time = time.time()
    max_runtime = 840  # 14 minutes (leave 1 min buffer for cleanup)
    
    scan_id = event_body.get("scan_id") or str(uuid.uuid4())
    repo_url = event_body.get("repo_url")
    
    if not repo_url:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing repo_url"})}
    
    # Safer regex for repo name
    repo_name_match = re.search(r'/([^/]+?)(\.git)?$', repo_url)
    repo_name = repo_name_match.group(1) if repo_name_match else "unknown_repo"
    repo_name = re.sub(r'[^a-zA-Z0-9\-_]', '', repo_name)
    
    update_scan_status(scan_id, "RUNNING", "Cloning repository...", repo_name=repo_name, repo_url=repo_url)
    
    repo_dir = os.path.join(MOUNT_PATH, "scans", scan_id)
    os.makedirs(repo_dir, exist_ok=True)
    os.environ["REPO_PATH"] = repo_dir
    
    print(f"🚀 Cloning {repo_url} to {repo_dir}...")
    
    if not clone_repo(repo_url, repo_dir):
        update_scan_status(scan_id, "FAILED", "Failed to clone repository")
        return {"statusCode": 500, "body": json.dumps({"error": "Clone failed"})}
    
    # SMART BRAIN RESTORE: Only restore if target is in-progress AND brain exists
    if should_restore_brain(repo_url, scan_id, repo_name):
        sync_db_from_s3(scan_id, repo_name)
    else:
        delete_brain_if_exists(scan_id, repo_name)
        print(f"🆕 Starting fresh scan for {repo_name}")
    
    conn = sqlite3.connect("/tmp/checkpoints.sqlite", check_same_thread=False)
    
    try:
        # CRITICAL: Replace ask_human BEFORE importing graph
        replace_ask_human_tool()
        os.chdir(repo_dir)
        
        from langgraph.checkpoint.sqlite import SqliteSaver
        from core.ingestion import run_ingestion
        from core.task_broker import TaskBroker
        from agent.tools.search import set_broker
        from agent.graph import build_graph
        from schemas.analysis_models import InvestigationLedger
        
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
        
        memory = SqliteSaver(conn)
        app = build_graph(checkpointer=memory)
        config = {"configurable": {"thread_id": scan_id}, "recursion_limit": 200}
        
        for step in app.stream(initial_state, config=config, stream_mode="values"):
            # Check timeout
            if time.time() - start_time > max_runtime:
                print("⏰ Approaching Lambda timeout - saving state and exiting")
                sync_db_to_s3(scan_id, repo_name)
                update_scan_status(
                    scan_id, 
                    "PAUSED", 
                    "Timeout - will auto-resume",
                    repo_name=repo_name,
                    repo_url=repo_url
                )
                return {
                    "statusCode": 202,
                    "body": json.dumps({
                        "status": "timeout_pause",
                        "scan_id": scan_id,
                        "message": "Scan will auto-resume"
                    })
                }
            
            messages = step.get("messages", [])
            if messages:
                last_msg = messages[-1]
                preview = str(last_msg.content)[:60] if hasattr(last_msg, 'content') else "Processing..."
                update_scan_status(scan_id, "RUNNING", preview, repo_name=repo_name)
        
        finalize_report(repo_dir, scan_id, repo_name)
        update_scan_status(scan_id, "COMPLETED", "Scan complete", repo_name=repo_name, repo_url=repo_url)
        mark_target_complete(repo_url)
        
        return {"statusCode": 200, "body": json.dumps({"status": "completed", "scan_id": scan_id})}
        
    except HumanInputNeeded as e:
        update_scan_status(
            scan_id,
            "PAUSED",
            "Waiting for user input",
            current_question=e.question,
            repo_name=repo_name,
            repo_url=repo_url
        )
        print(f"⏸️ Scan paused. Question: {e.question}")
        return {"statusCode": 202, "body": json.dumps({"status": "paused", "question": e.question, "scan_id": scan_id})}
        
    except Exception as e:
        update_scan_status(scan_id, "FAILED", f"Error: {str(e)[:200]}")
        print(f"❌ Scan failed: {e}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
        
    finally:
        os.chdir("/tmp")
        conn.close()
        sync_db_to_s3(scan_id, repo_name)
        
        # Cleanup large repos to avoid /tmp filling up
        try:
            if os.path.exists(repo_dir):
                dir_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, dirnames, filenames in os.walk(repo_dir)
                    for filename in filenames
                )
                if dir_size > 100_000_000:  # 100MB
                    shutil.rmtree(repo_dir)
                    print(f"🧹 Cleaned up large repo from /tmp ({dir_size / 1_000_000:.1f}MB)")
        except Exception as e:
            print(f"⚠️ Cleanup warning: {e}")

def handle_resume(event_body: Dict[str, Any]) -> Dict[str, Any]:
    """Resumes paused scan with user answer."""
    scan_id = event_body.get("scan_id")
    answer = event_body.get("answer")
    repo_name = event_body.get("repo_name")
    repo_url = event_body.get("repo_url")
    
    if not all([scan_id, answer, repo_name]):
        return {"statusCode": 400, "body": json.dumps({"error": "Missing scan_id, answer, or repo_name"})}
    
    update_scan_status(scan_id, "RUNNING", f"Resuming with answer: {answer[:50]}...", repo_name=repo_name)
    
    # Ensure repo directory exists (critical for cold Lambda starts)
    repo_dir = os.path.join(MOUNT_PATH, "scans", scan_id)
    if not os.path.exists(repo_dir):
        os.makedirs(repo_dir, exist_ok=True)
        if repo_url:
            print(f"🔄 Resuming scan requires fresh repo clone...")
            if not clone_repo(repo_url, repo_dir):
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": "Failed to restore repo for resume"})
                }
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Cannot resume without repo_url"})
            }
    
    os.environ["REPO_PATH"] = repo_dir
    
    sync_db_from_s3(scan_id, repo_name)
    conn = sqlite3.connect("/tmp/checkpoints.sqlite", check_same_thread=False)
    
    try:
        # CRITICAL: Replace ask_human BEFORE importing graph
        replace_ask_human_tool()
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langchain_core.messages import ToolMessage, HumanMessage
        from agent.graph import build_graph
        
        memory = SqliteSaver(conn)
        app = build_graph(checkpointer=memory)
        config = {"configurable": {"thread_id": scan_id}, "recursion_limit": 200}
        
        snapshot = app.get_state(config)
        
        if not snapshot or not snapshot.values:
            return {"statusCode": 404, "body": json.dumps({"error": "Scan state not found"})}
        
        last_message = snapshot.values.get("messages", [])[-1]
        
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            # Fallback: inject answer as human message
            app.update_state(config, {"messages": [HumanMessage(content=f"Here is the answer to your question: {answer}")]})
        else:
            # Find ask_human tool call
            tool_call_id = None
            for tc in last_message.tool_calls:
                if tc.get("name") in ["ask_human", "ask_human_lambda"]:
                    tool_call_id = tc.get("id")
                    if not tool_call_id:
                        print(f"⚠️ Tool call missing ID: {tc}")
                        continue
                    break
            
            if tool_call_id:
                answer_message = ToolMessage(
                    content=f"User Answer: {answer}",
                    tool_call_id=tool_call_id
                )
                app.update_state(config, {"messages": [answer_message]}, as_node="tools")
            else:
                # Fallback if no specific ask_human tool call found
                app.update_state(config, {"messages": [HumanMessage(content=f"Here is the answer to your question: {answer}")]})
        
        # Update pricing context
        current_pricing = snapshot.values.get("pricing_context", "")
        updated_pricing = f"{current_pricing}\n\nUser Input: {answer}"
        app.update_state(config, {"pricing_context": updated_pricing})
        
        os.chdir(repo_dir)
        
        for step in app.stream(None, config=config, stream_mode="values"):
            messages = step.get("messages", [])
            if messages:
                preview = str(messages[-1].content)[:60] if hasattr(messages[-1], 'content') else "Processing..."
                update_scan_status(scan_id, "RUNNING", preview, repo_name=repo_name)
        
        finalize_report(repo_dir, scan_id, repo_name)
        update_scan_status(scan_id, "COMPLETED", "Scan complete after resume", repo_name=repo_name, repo_url=repo_url)
        mark_target_complete(repo_url)
        
        return {"statusCode": 200, "body": json.dumps({"status": "resumed", "scan_id": scan_id})}
        
    except HumanInputNeeded as e:
        update_scan_status(scan_id, "PAUSED", "Paused again", current_question=e.question, repo_name=repo_name, repo_url=repo_url)
        return {"statusCode": 202, "body": json.dumps({"status": "paused_again", "question": e.question})}
        
    except Exception as e:
        update_scan_status(scan_id, "FAILED", f"Resume error: {str(e)[:200]}")
        print(f"❌ Resume failed: {e}")
        import traceback
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
        
    finally:
        os.chdir("/tmp")
        conn.close()
        sync_db_to_s3(scan_id, repo_name)

# --- Lambda Handler ---
def lambda_handler(event, context):
    print(f"🚀 Scanner Invoked. Version: v2025-11-29-ALL-FIXES-APPLIED")
    
    if "Records" in event:
        print(f"📥 Processing {len(event['Records'])} SQS Messages")
        results = []
        for record in event["Records"]:
            try:
                body = json.loads(record["body"])
                
                # CRITICAL FIX: Ensure action field exists
                if "action" not in body:
                    body["action"] = "scan"  # Default for backwards compatibility
                
                result = handle_single_event(body)
                results.append(result)
            except Exception as e:
                print(f"❌ Failed to process record: {e}")
                results.append({
                    "error": str(e),
                    "record_body": record.get("body", "")[:200]
                })
        return {"statusCode": 200, "body": json.dumps({"batch_results": results})}
    
    return handle_single_event(event)

def handle_single_event(event_body: Dict[str, Any]) -> Dict[str, Any]:
    action = event_body.get("action", "scan")
    
    if action == "scan":
        return handle_scan(event_body)
    elif action == "resume":
        return handle_resume(event_body)
    else:
        return {"statusCode": 400, "body": json.dumps({"error": f"Unknown action: {action}"})}