# agent/nodes/recon.py
import os
import re
from langchain_core.messages import HumanMessage
from agent.state import AgentState
from agent.tools.search import execute_safe_grep
from core.seed_knowledge import DEFAULT_PATTERNS  # Fallback
from core.infrastructure import infra

TABLE_NAME = os.environ.get("TABLE_KNOWLEDGE_BASE", "ScroogeKnowledgeBase")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

def validate_regex(pattern: str) -> bool:
    """Test if regex pattern is valid."""
    try:
        re.compile(pattern)
        return True
    except re.error as e:
        print(f"⚠️ Invalid regex pattern: {pattern[:50]}... Error: {e}")
        return False

def fetch_patterns():
    """
    Fetches regex patterns from DynamoDB ScroogeKnowledgeBase with pagination.
    Falls back to local DEFAULT_PATTERNS ONLY if DynamoDB fails.
    """
    try:
        table = infra.get_table(TABLE_NAME)
        
        print(f"🔍 [Recon] Fetching patterns from DynamoDB: {TABLE_NAME}")
        
        items = []
        response = table.scan()
        items.extend(response.get('Items', []))
        
        # Handle pagination (critical for large knowledge bases)
        while 'LastEvaluatedKey' in response:
            print(f"   📄 Fetching next page of patterns...")
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            items.extend(response.get('Items', []))
        
        if not items:
            print(f"⚠️ [Recon] DynamoDB table '{TABLE_NAME}' is empty. Using {len(DEFAULT_PATTERNS)} fallback patterns.")
            return DEFAULT_PATTERNS
        
        print(f"✅ [Recon] Loaded {len(items)} patterns from DynamoDB")
        return items
        
    except Exception as e:
        print(f"❌ [Recon] DynamoDB fetch failed: {e}")
        print(f"   Falling back to {len(DEFAULT_PATTERNS)} local patterns")
        return DEFAULT_PATTERNS

def run_pattern_sweep(repo_path: str, patterns: list) -> str:
    """Runs a fast grep for all knowledge base patterns with validation."""
    if not patterns:
        return "No patterns available for sweep."
    
    # Extract and validate regex strings
    regex_list = []
    invalid_patterns = []
    
    for p in patterns:
        if 'regex' in p:
            regex = p['regex']
            if validate_regex(regex):
                regex_list.append(regex)
            else:
                keyword = p.get('keyword', 'unknown')
                invalid_patterns.append(keyword)
    
    if invalid_patterns:
        print(f"⚠️ [Recon] Skipped {len(invalid_patterns)} invalid regexes: {invalid_patterns[:5]}")
    
    if not regex_list:
        return "No valid regexes found in patterns."
    
    print(f"   🔎 Running Sweep with {len(regex_list)} validated patterns...")
    
    # Execute Bulk Grep
    try:
        result = execute_safe_grep(regex_list, repo_path)
    except Exception as e:
        print(f"❌ [Recon] Grep execution failed: {e}")
        return f"Pattern sweep failed: {str(e)[:100]}"
    
    # Map back to categories
    summary_map = {}  # category -> list of findings
    total_matches = 0
    
    for res in result.get("results", []):
        matches = res.get("matches", [])
        if matches:
            total_matches += len(matches)
            
            # Find which pattern this belongs to
            original_ptrn = next(
                (p for p in patterns if p.get('regex') == res['pattern']), 
                None
            )
            if original_ptrn:
                cat = original_ptrn.get('category', 'unknown')
                desc = original_ptrn.get('description', 'Pattern')
                confidence = original_ptrn.get('confidence', 'unknown')
                keyword = original_ptrn.get('keyword', 'N/A')
                
                if cat not in summary_map:
                    summary_map[cat] = []
                
                summary_map[cat].append({
                    'description': desc,
                    'keyword': keyword,
                    'match_count': len(matches),
                    'confidence': confidence
                })
    
    if not summary_map:
        return "✅ Sweep completed. No high-confidence patterns found."
    
    # Format Output with better structure
    output = [f"**🔍 RECON SWEEP FINDINGS:** ({total_matches} total matches across {len(summary_map)} categories)"]
    output.append("")
    
    # Sort categories by priority (ai, cloud, storage, etc.)
    category_priority = {
        'ai': 1, 'ai_framework': 2, 'ai_storage': 3,
        'cloud': 4, 'storage': 5, 'saas': 6,
        'infra': 7, 'ci_cd': 8, 'unknown': 99
    }
    
    sorted_categories = sorted(
        summary_map.items(),
        key=lambda x: category_priority.get(x[0], 50)
    )
    
    for cat, findings in sorted_categories:
        output.append(f"**{cat.upper().replace('_', ' ')}:**")
        
        # Sort findings by confidence (high > medium > low)
        confidence_order = {'high': 1, 'medium': 2, 'low': 3}
        sorted_findings = sorted(
            findings,
            key=lambda x: (confidence_order.get(x['confidence'], 4), -x['match_count'])
        )
        
        for finding in sorted_findings[:5]:  # Limit to top 5 per category
            output.append(
                f"  • {finding['description']} "
                f"({finding['match_count']} hits, {finding['confidence']} confidence)"
            )
        
        if len(findings) > 5:
            output.append(f"  • ... and {len(findings) - 5} more patterns")
        output.append("")
    
    return "\n".join(output)

def recon_node(state: AgentState):
    """
    Initializes the pipeline, runs Pattern Sweep from DynamoDB, and hands off to Architect.
    """
    file_count = len(state.manifest)
    
    if state.verbose:
        print(f"\n🧠 [Recon] Initializing Sequential Pipeline...")
        print(f"   Files Detected: {file_count}")
    
    # 1. Fetch patterns (DynamoDB primary, local fallback)
    patterns = fetch_patterns()
    
    # 2. Run Regex Sweep with validation
    regex_report = run_pattern_sweep(state.repo_path, patterns)
    
    if state.verbose:
        print(f"   📝 Sweep Report Preview:")
        print(f"   {regex_report[:200]}...")
    
    # 3. Construct Initial Prompt with structured context
    files_context = "\n".join(state.priority_files[:25])  # Increased from 20 to 25
    
    # Create concise structure summary
    structure_summary = state.structure_map[:1000] if state.structure_map else "No structure map available"
    
    msg = HumanMessage(content=f"""
INITIATING COST DISCOVERY PROTOCOL.

**Repository Context:**
- Path: {state.repo_path}
- Total Files: {file_count}
- Structure Overview:
{structure_summary}

**High-Priority Files for Investigation:**
{files_context}

**Pattern Sweep Results:**
{regex_report}

---

**MISSION BRIEFING:**
Execute the 3-Phase Sequential Discovery Protocol to identify ALL 8 Cost Drivers:

**Phase 1: ARCHITECT** (Infrastructure & Compute)
- Cloud services (AWS Lambda, EC2, Azure Functions, GCP)
- Databases (DynamoDB, PostgreSQL, MongoDB)
- Storage (S3, Blob Storage, GCS)
- CI/CD pipelines (GitHub Actions, CircleCI, Jenkins)

**Phase 2: INTELLIGENCE** (AI/ML Systems)
- LLM API usage (OpenAI, Anthropic, Cohere, Google)
- AI frameworks (LangChain, LlamaIndex, Haystack)
- Vector databases (Pinecone, Weaviate, ChromaDB)
- Model hosting (HuggingFace, Replicate, Together AI)

**Phase 3: INTEGRATOR** (SaaS & Human Labor)
- Third-party SaaS APIs (Stripe, Twilio, SendGrid)
- Data providers (Snowflake, Databricks, Fivetran)
- Human-in-the-loop processes (Mechanical Turk, Scale AI, manual reviews)

---

**🎯 PHASE 1 START: ARCHITECT**

Your task: Map the infrastructure layer and identify compute/storage costs.

**Instructions:**
1. Use the Pattern Sweep findings as initial leads
2. Verify each finding by inspecting actual files (don't trust regex blindly)
3. Use `read_file` to examine config files and code
4. Use `search_files` to find additional references
5. Document findings in the Investigation Ledger
6. When infrastructure mapping is complete, call `complete_phase()`

Begin investigation now.
"""
    )
    
    return {
        "messages": [msg], 
        "active_specialist": "architect",
        "regex_findings": regex_report
    }