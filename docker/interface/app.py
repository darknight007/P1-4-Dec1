# app.py

import streamlit as st
import json
import os
import sys
import pandas as pd
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

# FORCE LOCAL MODE for Interface
os.environ["SCROOGE_ENV"] = "LOCAL"

# --- Path Setup for Local Mode ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", "cda-complete-local"))
if project_root not in sys.path:
    sys.path.append(project_root)

try:
    from core.infrastructure import infra
    from core.interface_adapter import invoke_backend
    print(f"✅ [Interface] Using Infrastructure Mode: {infra.mode}")
    if infra.mode == "LOCAL":
         # Log DB path from internal manager if possible, or reconstruct it
         db_path = os.path.join(os.path.dirname(project_root), "data", "scrooge.db")
         print(f"✅ [Interface] DB Path: {db_path}")
except ImportError as e:
    st.error(f"Failed to import core modules. Check paths: {e}")
    st.stop()

# --- Configuration ---
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
SCROOGE_MASTER_TOKEN = os.environ.get("SCROOGE_MASTER_TOKEN", "your_secret_token")
FETCHER_LAMBDA_NAME = os.environ.get("FETCHER_LAMBDA_NAME", "scrooge-stack-FetcherFunction")
SCANNER_LAMBDA_NAME = os.environ.get("SCANNER_LAMBDA_NAME", "scrooge-stack-ScroogeScannerFunction")
TABLE_SCAN_STATE = os.environ.get("TABLE_SCAN_STATE", "ScroogeScanState")
TABLE_TARGETS = os.environ.get("TABLE_TARGETS", "ScroogeTargets")
UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "scrooge-cost-reports")

# --- Infrastructure Clients ---
# Works for both AWS and LOCAL depending on SCROOGE_ENV
scan_state_table = infra.get_table(TABLE_SCAN_STATE)
targets_table = infra.get_table(TABLE_TARGETS)
s3_client = infra.get_s3_client()

# --- Helper Functions ---
def invoke_lambda(function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invokes Backend (Lambda or Local) and returns parsed response."""
    try:
        response = invoke_backend(function_name, payload)
        
        # AWS Lambda returns nested payload structure, Local returns direct dict
        # invoke_backend already normalizes this mostly, but let's be safe
        
        if 'body' in response and isinstance(response['body'], str):
             # Some returns have double-encoded body
             try:
                 response['body'] = json.loads(response['body'])
             except:
                 pass
                 
        return response
    except Exception as e:
        st.error(f"❌ Failed to invoke backend {function_name}: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

@st.cache_data(ttl=30, show_spinner="Fetching stats...")
def get_target_stats() -> Dict[str, int]:
    """Gets count of targets by status."""
    try:
        response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "get_stats"})
        if response and response.get("statusCode") == 200:
            body = response.get('body', '{}')
            if isinstance(body, str):
                return json.loads(body)
            return body
        return {}
    except Exception as e:
        st.error(f"Could not fetch target stats: {e}")
        return {}

@st.cache_data(ttl=60, show_spinner="Loading repositories...")
def get_all_targets() -> List[Dict[str, Any]]:
    """Gets all targets from DynamoDB with direct access (faster than Lambda)."""
    try:
        # Direct DynamoDB access - much faster than Lambda invoke
        response = targets_table.scan(Limit=200)
        items = response.get('Items', [])
        
        # Add index numbers
        for i, item in enumerate(items, 1):
            item['index'] = i
        
        # Sort by added_at
        items.sort(key=lambda x: x.get('added_at', ''), reverse=True)
        return items
    except Exception as e:
        st.error(f"Error fetching targets: {e}")
        return []

@st.cache_data(ttl=10, show_spinner="Loading scans...")
def get_scans_by_status(status: str = None) -> List[Dict[str, Any]]:
    """Gets scans from DynamoDB, optionally filtered by status."""
    try:
        print(f"🔍 [Interface] Fetching scans with status={status}...")
        if status:
            response = scan_state_table.scan(
                FilterExpression="#status = :s",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":s": status},
                Limit=100
            )
        else:
            response = scan_state_table.scan(Limit=100)
        
        items = response.get('Items', [])
        print(f"   ✅ Found {len(items)} items.")
        if items:
            print(f"   Example item status: {items[0].get('status')}")
            
        items.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        return items
    except Exception as e:
        st.error(f"Error fetching scans: {e}")
        print(f"❌ Error fetching scans: {e}")
        return []

def format_timestamp(iso_string: str) -> str:
    """Converts ISO timestamp to relative time."""
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        now = datetime.now(dt.tzinfo)
        diff = now - dt
        
        if diff < timedelta(minutes=1):
            return "Just now"
        elif diff < timedelta(hours=1):
            mins = int(diff.total_seconds() / 60)
            return f"{mins} min{'s' if mins > 1 else ''} ago"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            days = diff.days
            return f"{days} day{'s' if days > 1 else ''} ago"
    except:
        return iso_string[:19] if len(iso_string) > 19 else iso_string

def status_badge(status: str) -> str:
    """Returns emoji + status string."""
    badges = {
        "PAUSED": "🔴 PAUSED",
        "RUNNING": "🟡 RUNNING",
        "COMPLETED": "🟢 COMPLETED",
        "FAILED": "⚫ FAILED",
        "QUEUED": "🔵 QUEUED",
        "NEW": "⚪ NEW"
    }
    return badges.get(status, f"❓ {status}")

def submit_answer(scan_id: str, answer: str, repo_name: str, repo_url: str) -> bool:
    """Submits answer to resume scan. Returns True if successful."""
    if not answer.strip():
        st.warning("Please provide an answer before submitting.")
        return False
    
    with st.spinner("Sending answer to agent..."):
        payload = {
            "action": "resume",
            "scan_id": scan_id,
            "answer": answer,
            "repo_name": repo_name,
            "repo_url": repo_url
        }
        
        response = invoke_lambda(SCANNER_LAMBDA_NAME, payload)
        
        if not response:
            st.error("❌ No response from Lambda")
            return False
        
        status_code = response.get('statusCode', 500)
        body = response.get('body', '{}')
        
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except:
                body = {"error": "Invalid response"}
        
        if status_code == 200:
            if body.get('status') == 'resumed':
                st.toast("✅ Scan resumed successfully!", icon="✅")
                return True
            else:
                st.toast(f"⚠️ Resume issue: {body.get('error', 'Unknown')}", icon="⚠️")
                return False
        elif status_code == 202:
            st.toast("⏸️ Agent paused again with new question", icon="⏸️")
            return True
        else:
            st.error(f"❌ Resume failed: {body.get('error', 'Unknown error')}")
            return False

def parse_range_string(range_str: str) -> List[int]:
    """Parses a string like '1-5, 8, 10' into a list of integers."""
    indices = set()
    parts = range_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                indices.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            try:
                indices.add(int(part))
            except ValueError:
                continue
    return sorted(list(indices))

def load_default_repos() -> List[str]:
    """Returns list of sample repos."""
    return [
        "https://github.com/Significant-Gravitas/AutoGPT",
        "https://github.com/reworkd/AgentGPT",
        "https://github.com/yoheinakajima/babyagi",
        "https://github.com/Torantulino/Auto-GPT",
        "https://github.com/hwchase17/langchain",
        "https://github.com/openai/openai-python",
        "https://github.com/streamlit/streamlit",
        "https://github.com/gradio-app/gradio",
        "https://github.com/tiangolo/fastapi",
        "https://github.com/psf/requests"
    ]

def get_report_url(scan_id: str, repo_name: str) -> str:
    """Generates presigned URL for cost report."""
    try:
        s3_key = f"results/{repo_name}/{scan_id}/report.json"
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': UPLOAD_BUCKET, 'Key': s3_key},
            ExpiresIn=3600
        )
        return url
    except:
        return None

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="Scrooge Control Plane", page_icon="🦆")

st.markdown("""
    # 🦆 Scrooge Cost Scanner - Mission Control
    Manage your code scanning operations and human-in-the-loop interactions.
""")

# Initialize session state
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()

# --- Tab Navigation ---
tab_mission, tab_repo_browser, tab_repo_manager, tab_settings = st.tabs([
    "🧠 Mission Control", 
    "🗂️ Repo Browser", 
    "⚙️ Repo Manager", 
    "⚙️ Settings"
])

# ==================== MISSION CONTROL TAB ====================
with tab_mission:
    st.header("🧠 Human-in-the-Loop & Live Scans")
    
    # Top bar: Manual refresh
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.caption(f"Last updated: {st.session_state.last_refresh.strftime('%H:%M:%S')}")
    
    with col2:
        if st.button("🔄 Refresh Now", use_container_width=True):
            # Clear caches
            get_scans_by_status.clear()
            st.session_state.last_refresh = datetime.now()
            st.rerun()
    
    st.divider()
    
    # ===== SECTION 1: Active Questions (PAUSED) =====
    st.subheader("🔴 Active Questions")
    
    paused_scans = get_scans_by_status("PAUSED")
    
    if paused_scans:
        for scan in paused_scans:
            scan_id = scan.get('scan_id', 'unknown')
            repo_name = scan.get('repo_name', 'Unknown Repo')
            repo_url = scan.get('repo_url', '')
            question = scan.get('current_question', 'No question provided')
            last_updated = scan.get('last_updated', '')
            
            with st.container(border=True):
                col_info, col_time = st.columns([3, 1])
                
                with col_info:
                    st.markdown(f"**📋 {repo_name}**")
                    st.caption(f"Scan ID: `{scan_id[:16]}...`")
                
                with col_time:
                    st.caption(f"⏰ {format_timestamp(last_updated)}")
                
                st.info(f"**Question:** {question}")
                
                # Answer input
                answer_key = f"answer_{scan_id}"
                answer = st.text_input(
                    "Your answer:",
                    key=answer_key,
                    placeholder="Type your answer here..."
                )
                
                col_btn, col_space = st.columns([1, 3])
                with col_btn:
                    if st.button("Submit Answer", key=f"submit_{scan_id}", type="primary", use_container_width=True):
                        if submit_answer(scan_id, answer, repo_name, repo_url):
                            # Clear cache and refresh
                            get_scans_by_status.clear()
                            time.sleep(2)
                            st.rerun()
    else:
        st.success("✅ No paused scans - all agents are running smoothly!")
    
    st.divider()
    
    # ===== SECTION 2: Running Scans =====
    with st.expander("🟡 Running Scans", expanded=True):
        running_scans = get_scans_by_status("RUNNING")
        
        if running_scans:
            running_data = []
            for scan in running_scans:
                running_data.append({
                    "Project": scan.get('repo_name', 'Unknown'),
                    "Status": status_badge("RUNNING"),
                    "Message": scan.get('message', '')[:80],
                    "Updated": format_timestamp(scan.get('last_updated', '')),
                    "Scan ID": scan.get('scan_id', '')[:12]
                })
            
            df_running = pd.DataFrame(running_data)
            st.dataframe(df_running, use_container_width=True, hide_index=True)
        else:
            st.info("No scans currently running.")
    
    # ===== SECTION 3: Recent Activity =====
    with st.expander("📊 Recent Activity (All Scans)", expanded=False):
        all_scans = get_scans_by_status()
        
        if all_scans:
            activity_data = []
            for scan in all_scans[:50]:  # Limit to 50 most recent
                scan_id = scan.get('scan_id', 'unknown')
                repo_name = scan.get('repo_name', 'Unknown')
                status = scan.get('status', 'UNKNOWN')
                
                activity_data.append({
                    "Time": format_timestamp(scan.get('last_updated', '')),
                    "Project": repo_name,
                    "Status": status_badge(status),
                    "Message": scan.get('message', '')[:60],
                    "Scan ID": scan_id[:12],
                    "Report": "📄" if status == "COMPLETED" else ""
                })
            
            df_activity = pd.DataFrame(activity_data)
            
            # Add clickable report links for completed scans
            st.dataframe(df_activity, use_container_width=True, hide_index=True)
            
            # Download reports section
            completed = [s for s in all_scans if s.get('status') == 'COMPLETED']
            if completed:
                st.markdown("**📥 Download Reports:**")
                for scan in completed[:10]:
                    scan_id = scan.get('scan_id')
                    repo_name = scan.get('repo_name')
                    url = get_report_url(scan_id, repo_name)
                    if url:
                        st.markdown(f"- [{repo_name}]({url})")
        else:
            st.info("No scan activity yet.")

# ==================== REPO BROWSER TAB ====================
with tab_repo_browser:
    st.header("🗂️ Repository Browser")
    st.info("View all loaded repositories and selectively queue them for scanning.")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption("📊 Data cached for 60 seconds")
    with col2:
        if st.button("🔄 Force Refresh", use_container_width=True):
            # Clear cache
            get_all_targets.clear()
            st.rerun()
    
    all_targets = get_all_targets()
    
    if all_targets:
        df_targets = pd.DataFrame(all_targets)
        
        if 'index' in df_targets.columns:
            cols = ['index', 'repo_url', 'status', 'added_at', 'last_queued']
            cols = [c for c in cols if c in df_targets.columns]
            st.dataframe(df_targets[cols], use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_targets, use_container_width=True)
            
        st.subheader("Queue Specific Repositories")
        col1, col2 = st.columns([3, 1])
        
        with col1:
            range_input = st.text_input("Enter Index Range (e.g., 1-5, 8, 10):")
        
        with col2:
            force_requeue = st.checkbox("Force Re-queue?")
            
        if st.button("🚀 Queue Selected Repos"):
            if range_input:
                selected_indices = parse_range_string(range_input)
                
                selected_urls = []
                for idx in selected_indices:
                    match = next((item for item in all_targets if item.get('index') == idx), None)
                    if match:
                        selected_urls.append(match['repo_url'])
                
                if selected_urls:
                    with st.spinner(f"Queueing {len(selected_urls)} repositories..."):
                        payload = {
                            "action": "queue_specific_targets", 
                            "target_urls": selected_urls,
                            "force": force_requeue
                        }
                        response = invoke_lambda(FETCHER_LAMBDA_NAME, payload)
                        
                        if response and response.get('statusCode') == 200:
                            body = response.get('body', '{}')
                            if isinstance(body, str):
                                body = json.loads(body)
                            st.success(f"✅ {body.get('message')}")
                            st.info(f"Queued: {body.get('queued')} | Skipped: {body.get('skipped')}")
                            # Clear cache and refresh
                            get_all_targets.clear()
                            time.sleep(1)
                            st.rerun()
                else:
                    st.warning("No valid repositories found for the entered indices.")
            else:
                st.warning("Please enter an index range.")
    else:
        st.warning("No repositories found in database. Go to 'Repo Manager' to load some.")

# ==================== REPO MANAGER TAB ====================
with tab_repo_manager:
    st.header("⚙️ Bulk Operations")

    st.subheader("Load Repositories")
    repo_input_type = st.radio("Choose input method:", ("Default List", "Manual Input"), horizontal=True)

    if repo_input_type == "Default List":
        if st.button("Load Default Sample Repos"):
            repos_to_add = load_default_repos()
            response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "load_targets", "targets": repos_to_add})
            if response and response.get('statusCode') == 200:
                body = response.get('body', '{}')
                if isinstance(body, str):
                    body = json.loads(body)
                st.success(f"✅ Loaded {body.get('added', 0)} new repos into the system.")
                # Clear caches
                get_all_targets.clear()
                get_target_stats.clear()
            st.rerun()
    else:
        manual_repos_str = st.text_area("Enter GitHub Repo URLs (one per line):", height=150)
        if st.button("Add Manual Repos"):
            repos_to_add = [url.strip() for url in manual_repos_str.split('\n') if url.strip()]
            if repos_to_add:
                response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "load_targets", "targets": repos_to_add})
                if response and response.get('statusCode') == 200:
                    body = response.get('body', '{}')
                    if isinstance(body, str):
                        body = json.loads(body)
                    st.success(f"✅ Loaded {body.get('added', 0)} new repos into the system.")
                    # Clear caches
                    get_all_targets.clear()
                    get_target_stats.clear()
                st.rerun()

    st.divider() 
    
    st.subheader("Repository Status Overview")
    stats = get_target_stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("New Repos", stats.get("NEW", 0))
    col2.metric("Queued", stats.get("QUEUED", 0))
    col3.metric("Running", stats.get("RUNNING", 0))
    col4.metric("Completed", stats.get("COMPLETED", 0))

    st.subheader("Queue Batch (Auto-Select New)")
    num_repos_to_queue = st.number_input("Number of NEW repos to queue:", min_value=1, value=5, step=1)
    if st.button("Queue Batch"):
        response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "queue_batch", "limit": num_repos_to_queue})
        if response and response.get('statusCode') == 200:
            body = response.get('body', '{}')
            if isinstance(body, str):
                body = json.loads(body)
            st.success(f"✅ Queued {body.get('queued', 0)} repos for scanning.")
            # Clear caches
            get_all_targets.clear()
            get_target_stats.clear()
        st.rerun()
        
    st.subheader("Reset Repository Status")
    reset_repo_url = st.text_input("Enter Repo URL to reset its status to 'NEW':")
    if st.button("Reset Repo"):
        if reset_repo_url:
            response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "reset_target", "repo_url": reset_repo_url})
            if response and response.get('statusCode') == 200:
                st.success(f"✅ Repository {reset_repo_url} reset to NEW.")
                # Clear caches
                get_all_targets.clear()
                get_target_stats.clear()
            st.rerun()
        else:
            st.warning("Please enter a repository URL to reset.")

# ==================== SETTINGS TAB ====================
with tab_settings:
    st.header("⚙️ System Configuration")
    
    st.json({
        "AWS_REGION": AWS_REGION,
        "FETCHER_LAMBDA_NAME": FETCHER_LAMBDA_NAME,
        "SCANNER_LAMBDA_NAME": SCANNER_LAMBDA_NAME,
        "UPLOAD_BUCKET": UPLOAD_BUCKET,
        "TABLE_SCAN_STATE": TABLE_SCAN_STATE,
        "TABLE_TARGETS": TABLE_TARGETS
    })
    
    st.divider()
    
    st.subheader("🔧 Diagnostics")
    
    if st.button("Test Lambda Connection"):
        with st.spinner("Testing..."):
            response = invoke_lambda(FETCHER_LAMBDA_NAME, {"action": "get_stats"})
            if response and response.get('statusCode') == 200:
                st.success("✅ Lambda connection successful")
            else:
                st.error(f"❌ Lambda connection failed: {response}")
    
    if st.button("Test DynamoDB Connection"):
        with st.spinner("Testing..."):
            try:
                scan_state_table.scan(Limit=1)
                st.success("✅ DynamoDB ScanState connection successful")
                
                targets_table.scan(Limit=1)
                st.success("✅ DynamoDB Targets connection successful")
            except Exception as e:
                st.error(f"❌ DynamoDB connection failed: {e}")
    
    if st.button("Clear All Caches"):
        get_all_targets.clear()
        get_target_stats.clear()
        get_scans_by_status.clear()
        st.success("✅ All caches cleared!")
        st.rerun()
