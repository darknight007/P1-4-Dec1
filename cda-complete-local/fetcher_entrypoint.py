import json
import uuid
import os
from datetime import datetime
from core.infrastructure import infra

# CONFIG
TABLE_TARGETS = os.environ.get('TABLE_TARGETS', 'ScroogeTargets')
QUEUE_URL = os.environ.get('JOB_QUEUE_URL')
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

def lambda_handler(event, context):
    print(f"📦 FULL EVENT RECEIVED: {json.dumps(event)}") # For debugging
    
    action = event.get('action', 'queue_batch') # Default to queue_batch if missing
    print(f"🦅 Fetcher Action: {action}")
    
    table = infra.get_table(TABLE_TARGETS)
    sqs = infra.get_sqs_client()
    
    if action == 'load_targets':
        return handle_load_targets(event, table)
    elif action == 'queue_batch':
        return handle_queue_batch(event, table, sqs)
    elif action == 'queue_specific_targets': # NEW ACTION
        return handle_queue_specific_targets(event, table, sqs)
    elif action == 'reset_target':
        return handle_reset_target(event, table)
    elif action == 'get_stats':
        return handle_get_stats(table)
    elif action == 'get_all_targets': # NEW ACTION
        return handle_get_all_targets(table)
    else:
        return {"statusCode": 400, "body": f"Unknown action: {action}"}

def handle_load_targets(event, table):
    """Loads a list of repos into the DB if they don't exist."""
    targets = event.get('targets', [])
    # Fallback to demo list if empty
    if not targets:
        targets = [
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
        
    added = 0
    for url in targets:
        try:
            # Conditional Put to avoid overwriting existing status
            table.put_item(
                Item={
                    'repo_url': url,
                    'status': 'NEW',
                    'added_at': datetime.utcnow().isoformat()
                },
                ConditionExpression='attribute_not_exists(repo_url)'
            )
            added += 1
        except Exception as e:
            if "ConditionalCheckFailedException" in str(e):
                pass # Already exists, ignore
            else:
                print(f"⚠️ Error adding target {url}: {e}")
            
    return {
        "statusCode": 200, 
        "body": json.dumps({"message": "Targets Loaded", "added": added, "total_provided": len(targets)})
    }

def handle_queue_batch(event, table, sqs):
    """Finds NEW targets and pushes them to SQS."""
    limit = int(event.get('limit', 5))
    print(f"🔍 Queueing batch of {limit}...")
    
    # Scan for 'NEW' items
    # Note: local_adapter scan mimics filter syntax loosely
    # We use manual filtering to be safe if adapter is limited
    resp = table.scan(Limit=limit * 10) # Scan more to filter in memory if needed
    items = resp.get('Items', [])
    
    # Manual Filter for NEW
    new_items = [i for i in items if i.get('status') == 'NEW'][:limit]
    
    print(f"🔍 Found {len(new_items)} NEW items.")
    
    queued_count = 0
    
    for item in items:
        # Only process filtered items
        if item not in new_items: continue

        repo_url = item['repo_url']
        scan_id = str(uuid.uuid4())
        
        # 1. Push to SQS
        payload = {
            "action": "scan",
            "scan_id": scan_id,
            "repo_url": repo_url
        }
        
        try:
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(payload)
            )
            
            # 2. Update DB Status
            table.update_item(
                Key={'repo_url': repo_url},
                UpdateExpression="SET #s = :s, last_queued = :t, current_scan_id = :id",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={
                    ':s': 'QUEUED', 
                    ':t': datetime.utcnow().isoformat(),
                    ':id': scan_id
                }
            )
            queued_count += 1
        except Exception as e:
            print(f"❌ Failed to queue {repo_url}: {e}")
            
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Batch Queued", "queued": queued_count})
    }

def handle_queue_specific_targets(event, table, sqs):
    """Queues specific targets by URL, with optional force re-queue."""
    target_urls = event.get('target_urls', [])
    force_requeue = event.get('force', False)
    
    if not target_urls:
        return {"statusCode": 400, "body": "No target_urls provided."}
        
    queued_count = 0
    skipped_count = 0
    
    for repo_url in target_urls:
        item = table.get_item(Key={'repo_url': repo_url}).get('Item')
        
        if not item:
            print(f"⚠️ Repo {repo_url} not found in targets table.")
            skipped_count += 1
            continue
            
        current_status = item.get('status')
        
        if current_status in ['QUEUED', 'RUNNING'] and not force_requeue:
            print(f"ℹ️ Repo {repo_url} is {current_status}, skipping. Use force=True to re-queue.")
            skipped_count += 1
            continue
        
        # If COMPLETED or FAILED, and force_requeue, reset to NEW first
        if (current_status in ['COMPLETED', 'FAILED']) and force_requeue:
            table.update_item(
                Key={'repo_url': repo_url},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':s': 'NEW'}
            )
            current_status = 'NEW' # Update current_status for queuing below

        if current_status == 'NEW' or current_status == 'FAILED' or force_requeue:
            scan_id = str(uuid.uuid4())
            payload = {
                "action": "scan",
                "scan_id": scan_id,
                "repo_url": repo_url
            }
            
            try:
                sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps(payload)
                )
                
                table.update_item(
                    Key={'repo_url': repo_url},
                    UpdateExpression="SET #s = :s, last_queued = :t, current_scan_id = :id",
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={
                        ':s': 'QUEUED', 
                        ':t': datetime.utcnow().isoformat(),
                        ':id': scan_id
                    }
                )
                queued_count += 1
                print(f"✅ Repo {repo_url} queued.")
            except Exception as e:
                print(f"❌ Failed to queue {repo_url}: {e}")
                
        else: # Should not happen with above checks, but as a fallback
            print(f"⚠️ Repo {repo_url} with status {current_status} not re-queued without force.")
            skipped_count += 1
            
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Specific targets queued", 
            "queued": queued_count, 
            "skipped": skipped_count
        })
    }

def handle_reset_target(event, table):
    """Resets a target to NEW so it can be re-run."""
    repo_url = event.get('repo_url')
    if not repo_url:
        return {"statusCode": 400, "body": "Missing repo_url"}
        
    table.update_item(
        Key={'repo_url': repo_url},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':s': 'NEW'}
    )
    
    return {"statusCode": 200, "body": json.dumps({"message": f"Reset {repo_url}"})}

def handle_get_stats(table):
    """Returns counts of NEW, QUEUED, COMPLETED, FAILED."""
    # Simple scan aggregation - for larger tables, consider GSI or batch gets
    resp = table.scan(Select='SPECIFIC_ATTRIBUTES', ProjectionExpression='#s', ExpressionAttributeNames={'#s': 'status'})
    stats = {"NEW": 0, "QUEUED": 0, "RUNNING": 0, "PAUSED": 0, "COMPLETED": 0, "FAILED": 0}
    
    for item in resp.get('Items', []):
        s = item.get('status', 'NEW')
        stats[s] = stats.get(s, 0) + 1
        
    return {"statusCode": 200, "body": json.dumps(stats)}

def handle_get_all_targets(table):
    """Returns all targets in the table, sorted by added_at."""
    response = table.scan()
    items = response.get('Items', [])
    
    # Ensure items are sortable by 'added_at'
    for item in items:
        if 'added_at' not in item:
            item['added_at'] = '1970-01-01T00:00:00.000000' # Default value for old items

    items.sort(key=lambda x: x['added_at'])
    
    # Add a sequential index for the UI
    for i, item in enumerate(items):
        item['index'] = i + 1

    return {
        "statusCode": 200,
        "body": json.dumps(items, default=str) # default=str handles datetime objects
    }