import sqlite3
import json
import os
import time
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from threading import Lock

# --- Configuration ---
# We use absolute paths to ensure all components (runner, interface) hit the same DB.
# Base is D:\analyzer-to-saving-complete\LOCAL\cda-complete-local\core\..\.. => D:\analyzer-to-saving-complete\LOCAL
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "scrooge.db")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
ZIPS_DIR = os.path.join(DATA_DIR, "zips")

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(ZIPS_DIR, exist_ok=True)

logger = logging.getLogger("LocalAdapter")

class LocalDataManager:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LocalDataManager, cls).__new__(cls)
                cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        """Initialize SQLite database with tables mimicking DynamoDB."""
        # Autocommit mode (isolation_level=None) to ensure immediate visibility
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        
        # Removed WAL mode to avoid visibility issues across processes
        # self.conn.execute("PRAGMA journal_mode=WAL;")
        
        cursor = self.conn.cursor()
        
        # Table: ScroogeTargets
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ScroogeTargets (
                repo_url TEXT PRIMARY KEY,
                status TEXT,
                added_at TEXT,
                last_queued TEXT,
                repo_name TEXT,
                current_scan_id TEXT,
                meta_json TEXT
            )
        """)

        # Table: ScroogeScanState
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ScroogeScanState (
                scan_id TEXT PRIMARY KEY,
                repo_name TEXT,
                repo_url TEXT,
                status TEXT,
                current_question TEXT,
                pending_answer TEXT, 
                thread_id TEXT,
                last_updated TEXT,
                message TEXT,
                state_json TEXT
            )
        """)

        # Table: ScroogeKnowledgeBase
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ScroogeKnowledgeBase (
                id TEXT PRIMARY KEY,
                category TEXT,
                regex TEXT,
                description TEXT,
                keyword TEXT,
                confidence TEXT,
                meta_json TEXT
            )
        """)

        # Table: ScroogePricingKB
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ScroogePricingKB (
                service_metric TEXT PRIMARY KEY,
                price_per_unit REAL,
                category TEXT,
                unit_description TEXT,
                provider TEXT,
                confidence TEXT,
                meta_json TEXT
            )
        """)
        
        self.conn.commit()

    def get_table(self, table_name: str):
        return MockTable(self.conn, table_name)

class MockTable:
    def __init__(self, conn, table_name):
        self.conn = conn
        self.table_name = table_name

    def put_item(self, Item: Dict[str, Any], ConditionExpression: str = None, **kwargs):
        """Mimics DynamoDB put_item."""
        # Define valid columns for each table
        schema_map = {
            "ScroogeTargets": ["repo_url", "status", "added_at", "last_queued", "repo_name", "current_scan_id"],
            "ScroogeScanState": ["scan_id", "repo_name", "repo_url", "status", "current_question", "pending_answer", "thread_id", "last_updated", "message"],
            "ScroogeKnowledgeBase": ["id", "category", "regex", "description", "keyword", "confidence"],
            "ScroogePricingKB": ["service_metric", "price_per_unit", "category", "unit_description", "provider", "confidence"]
        }
        
        valid_cols = schema_map.get(self.table_name, [])
        
        # 1. Handle ConditionExpression (Basic Simulation)
        if ConditionExpression:
            # Only supporting 'attribute_not_exists(pk)' which is the most common use case here
            # We check if PK exists
            pk_name = schema_map.get(self.table_name, ["id"])[0] # Assume first col is PK
            pk_val = Item.get(pk_name)
            
            if "attribute_not_exists" in ConditionExpression and pk_val:
                cursor = self.conn.cursor()
                cursor.execute(f"SELECT 1 FROM {self.table_name} WHERE {pk_name} = ?", (pk_val,))
                if cursor.fetchone():
                    # Simulate ConditionalCheckFailedException
                    # We raise a specific ValueError that our adapter can catch/users can expect?
                    # Or just silently fail/return if strict boto3 exception isn't required by caller logic 
                    # (but caller usually expects exception)
                    raise Exception("ConditionalCheckFailedException")

        row_data = {}
        extra_data = {}
        
        for k, v in Item.items():
            if k in valid_cols:
                row_data[k] = v
            else:
                extra_data[k] = v
        
        # Serialize extra data into meta_json
        row_data["meta_json"] = json.dumps(extra_data)
            
        # Use INSERT OR REPLACE
        final_cols = list(row_data.keys())
        final_vals = list(row_data.values())
        final_placeholders = ",".join(["?"] * len(final_cols))
        
        query = f"INSERT OR REPLACE INTO {self.table_name} ({','.join(final_cols)}) VALUES ({final_placeholders})"
        
        with self.conn:
            self.conn.execute(query, final_vals)

    def get_item(self, Key: Dict[str, Any]):
        """Mimics DynamoDB get_item."""
        # Key is usually {'pk_name': 'value'}
        key_col = list(Key.keys())[0]
        key_val = list(Key.values())[0]
        
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT * FROM {self.table_name} WHERE {key_col} = ?", (key_val,))
        row = cursor.fetchone()
        
        if row:
            return {"Item": self._row_to_dict(row)}
        return {}

    def scan(self, FilterExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None, Limit=None, ExclusiveStartKey=None, Select=None, ProjectionExpression=None):
        """Mimics basic DynamoDB scan. Ignores complex filters for now."""
        cursor = self.conn.cursor()
        
        query = f"SELECT * FROM {self.table_name}"
        
        # Very basic filtering support for specific common patterns
        # This is NOT a full DynamoDB expression parser
        
        if Limit:
            query += f" LIMIT {Limit}"
            
        cursor.execute(query)
        rows = cursor.fetchall()
        
        items = [self._row_to_dict(row) for row in rows]
        
        # Python-side filtering to simulate DynamoDB FilterExpression
        if FilterExpression:
            # Handle simple "#status = :s" type filters
            if "#status = :s" in str(FilterExpression) and ExpressionAttributeValues:
                target_status = ExpressionAttributeValues.get(":s")
                if target_status:
                     items = [i for i in items if i.get("status") == target_status]
            # Add more simulated filters here if needed
        
        return {"Items": items}
    
    def update_item(self, Key: Dict[str, Any], UpdateExpression: str, ExpressionAttributeNames: Dict[str, Any] = None, ExpressionAttributeValues: Dict[str, Any] = None):
        """
        Mimics DynamoDB update_item. 
        Simplified: Expects "SET #k = :v, #k2 = :v2" style.
        """
        key_col = list(Key.keys())[0]
        key_val = list(Key.values())[0]
        
        # 1. UPSERT Check: Ensure row exists
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT 1 FROM {self.table_name} WHERE {key_col} = ?", (key_val,))
        if not cursor.fetchone():
            # Row missing, insert it with just the PK
            try:
                with self.conn:
                    self.conn.execute(f"INSERT INTO {self.table_name} ({key_col}) VALUES (?)", (key_val,))
            except Exception as e:
                logger.error(f"Upsert Insert failed: {e}")

        updates = []
        params = []
        
        if "SET" in UpdateExpression:
            clean_expr = UpdateExpression.replace("SET", "").strip()
            parts = clean_expr.split(",")
            
            for part in parts:
                # format: " #status = :status "
                if "=" not in part: continue
                
                col_part, val_part = part.split("=")
                col_name = col_part.strip()
                val_placeholder = val_part.strip()
                
                # Resolve #name
                if col_name.startswith("#") and ExpressionAttributeNames:
                    col_name = ExpressionAttributeNames.get(col_name, col_name)
                elif col_name.startswith("#") and not ExpressionAttributeNames:
                     # Clean up # if no mapping provided (simpler usage)
                     col_name = col_name.replace("#", "")
                
                # Resolve :value
                val = None
                if ExpressionAttributeValues and val_placeholder in ExpressionAttributeValues:
                    val = ExpressionAttributeValues[val_placeholder]
                else:
                    # Direct value? Rare in boto3, but possible fallback
                    val = val_placeholder
                    
                updates.append(f"{col_name} = ?")
                params.append(val)
        
        if not updates:
            return

        query = f"UPDATE {self.table_name} SET {', '.join(updates)} WHERE {key_col} = ?"
        params.append(key_val)
        
        try:
            with self.conn:
                self.conn.execute(query, params)
        except Exception as e:
            logger.error(f"Update failed: {e} | Query: {query} | Params: {params}")

    def _row_to_dict(self, row):
        d = dict(row)
        # Unpack meta_json if exists
        if "meta_json" in d and d["meta_json"]:
            try:
                meta = json.loads(d["meta_json"])
                # Merge meta keys into d, ensuring we don't overwrite primary schema keys
                for k, v in meta.items():
                    if k not in d:
                        d[k] = v
                del d["meta_json"]
            except:
                pass
        return d

# --- S3 Abstraction ---
class MockS3:
    def upload_file(self, Filename, Bucket, Key):
        """Copy file to local data dir."""
        dest_path = os.path.join(DATA_DIR, Key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        with open(Filename, 'rb') as f_src:
            content = f_src.read()
        
        with open(dest_path, 'wb') as f_dst:
            f_dst.write(content)
            
        logger.info(f"📂 [MockS3] Uploaded {Filename} -> {dest_path}")

    def put_object(self, Body, Bucket, Key):
        dest_path = os.path.join(DATA_DIR, Key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        mode = 'wb' if isinstance(Body, bytes) else 'w'
        with open(dest_path, mode) as f:
            f.write(Body)
            
    def download_file(self, Bucket, Key, Filename):
        src_path = os.path.join(DATA_DIR, Key)
        if not os.path.exists(src_path):
            # Simulate 404
            raise Exception(f"An error occurred (404) when calling the HeadObject operation: Key '{Key}' does not exist")
            
        with open(src_path, 'rb') as f_src:
            content = f_src.read()
            
        with open(Filename, 'wb') as f_dst:
            f_dst.write(content)

    def head_object(self, Bucket, Key):
        src_path = os.path.join(DATA_DIR, Key)
        if not os.path.exists(src_path):
             raise Exception("404 Not Found")
        return {"ContentLength": os.path.getsize(src_path)}

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn=3600):
        # Return absolute file path for local usage
        key = Params.get('Key')
        return os.path.join(DATA_DIR, key)

class MockSQS:
    def send_message(self, QueueUrl, MessageBody):
        # In local mode, we typically write to DB or call function directly.
        # If we strictly need queue behavior, we'd use a list/table.
        # For now, log it.
        logger.info(f"📧 [MockSQS] Sent message: {MessageBody}")
        return {"MessageId": str(uuid.uuid4())}