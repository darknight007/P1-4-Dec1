# core/interface_adapter.py
import os
import sys
import json
import importlib.util

# Ensure we can find sibling modules if running from docker/interface
current_dir = os.path.dirname(os.path.abspath(__file__))
# cda-complete-local root
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from core.infrastructure import infra

MODE = os.environ.get("SCROOGE_ENV", "AWS")

FETCHER_NAME = os.environ.get("FETCHER_LAMBDA_NAME", "scrooge-stack-FetcherFunction")
SCANNER_NAME = os.environ.get("SCANNER_LAMBDA_NAME", "scrooge-stack-ScroogeScannerFunction")

def invoke_backend(function_name: str, payload: dict) -> dict:
    """
    Universal backend invoker.
    AWS -> call lambda
    LOCAL -> call python function or write to DB
    """
    if MODE == "AWS":
        import boto3
        lambda_client = boto3.client('lambda', region_name=os.environ.get("AWS_REGION", "ap-south-1"))
        
        try:
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            return json.loads(response['Payload'].read().decode("utf-8"))
        except Exception as e:
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    else:
        # LOCAL MODE
        print(f"💻 [LocalMode] Invoking {function_name} with action={payload.get('action')}")
        
        # 1. FETCHER ACTIONS (Synchronous usually)
        if function_name == FETCHER_NAME:
            try:
                fetcher_path = os.path.join(project_root, "fetcher_entrypoint.py")
                print(f"📂 [LocalMode] Loading Fetcher from: {fetcher_path}")
                
                # Import dynamically to avoid top-level import issues
                spec = importlib.util.spec_from_file_location("fetcher", fetcher_path)
                fetcher = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(fetcher)
                
                # Execute handler directly
                return fetcher.lambda_handler(payload, None)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"statusCode": 500, "body": json.dumps({"error": f"Local execution failed: {e}"})}
        
        # 2. SCANNER ACTIONS (Async or Resume)
        elif function_name == SCANNER_NAME:
            action = payload.get("action")
            
            if action == "resume":
                # In local mode, we signal resume via the DB.
                # The local runner polls for this.
                # However, our local runner logic currently looks for RESUME_QUEUED status.
                
                scan_id = payload.get("scan_id")
                answer = payload.get("answer")
                
                if not scan_id:
                    return {"statusCode": 400, "body": json.dumps({"error": "Missing scan_id"})}
                
                try:
                    scan_table = infra.get_table("ScroogeScanState")
                    scan_table.update_item(
                        Key={"scan_id": scan_id},
                        UpdateExpression="SET #status = :s, pending_answer = :a",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={":s": "RESUME_QUEUED", ":a": answer}
                    )
                    return {"statusCode": 200, "body": json.dumps({"status": "resumed", "message": "Resume signal sent"})}
                except Exception as e:
                    return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
            
            else:
                # Direct scan invocation? Usually this is done via SQS/Fetcher.
                # If the UI calls scanner directly (rare), handle it.
                return {"statusCode": 400, "body": json.dumps({"error": "Direct scanner invocation not supported in local mode yet (use Fetcher to queue)"})}
        
        return {"statusCode": 404, "body": json.dumps({"error": f"Unknown function {function_name}"})}
