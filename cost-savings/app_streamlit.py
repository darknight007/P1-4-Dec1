import streamlit as st
import json
import requests
import pandas as pd
import uuid
from typing import List, Dict, Any

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Cost Savings Consultant", page_icon="💰", layout="wide")
API_URL = "http://localhost:8000"
PRICING_API_URL = "http://localhost:8001"

if "report_context" not in st.session_state:
    st.session_state.report_context = {}
if "feature_map" not in st.session_state:
    st.session_state.feature_map = {} # {driver_id: feature_id}
if "calc_schema" not in st.session_state:
    st.session_state.calc_schema = {}
if "active_params" not in st.session_state:
    st.session_state.active_params = [] # List of param IDs to show
if "custom_params" not in st.session_state:
    st.session_state.custom_params = [] # List of {name, ai_val, human_val}
if "roi_results" not in st.session_state:
    st.session_state.roi_results = None  # Store calculation for pricing
if "roi_feature_id" not in st.session_state:
    st.session_state.roi_feature_id = None

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def load_context(json_text):
    try:
        data = json.loads(json_text)
        st.session_state.report_context = data
        
        # Build initial Feature Map (Driver -> Feature)
        f_map = {}
        # 1. Default to "Unassigned"
        for cat in ["llm_calls", "infrastructure", "integrations", "data_components"]:
            for item in data.get(cat, []):
                f_map[item["id"]] = "Unassigned"
        
        # 2. Override with existing mappings
        if "features" in data:
            for feat in data["features"]:
                for driver_id in feat.get("cost_driver_ids", []):
                    f_map[driver_id] = feat["id"]
        
        st.session_state.feature_map = f_map
        st.success("✅ Project Context Loaded!")
    except json.JSONDecodeError:
        st.error("❌ Invalid JSON format.")
    except Exception as e:
        st.error(f"❌ Error loading context: {e}")

def get_feature_options():
    """Returns list of (name, id) tuples for dropdowns."""
    ctx = st.session_state.report_context
    opts = [("Unassigned", "Unassigned")]
    if "features" in ctx:
        for f in ctx["features"]:
            opts.append((f"{f['name']} ({f['id']})", f["id"]))
    return opts

def fetch_schema(feature_id):
    """Fetches smart parameters from backend."""
    if not feature_id or feature_id == "Unassigned": return
    
    try:
        payload = {
            "context": st.session_state.report_context,
            "target_feature_id": feature_id
        }
        resp = requests.post(f"{API_URL}/savings/discovery/schema", json=payload)
        resp.raise_for_status()
        schema = resp.json()
        
        st.session_state.calc_schema = schema
        # Initialize active params with recommended ones
        st.session_state.active_params = schema.get("recommended_parameters", [])
    except Exception as e:
        st.error(f"❌ Discovery Failed: {e}")

def generate_pricing_proposal(roi_data, feature_id):
    """Calls the Pricing Service to get a recommendation."""
    try:
        # 1. Construct SavingsSummary
        savings_payload = {
            "feature_id": feature_id,
            "benefit_units": {"units_processed": 1000}, # Normalized
            "human_hours_saved": roi_data['hours_saved'],
            "estimated_monthly_savings_usd": roi_data['savings'],
            "quality_factor": roi_data['quality_factor']
        }
        
        # 2. Construct CostProfile
        costs_payload = {
            "feature_id": feature_id,
            "costs": {"raw": roi_data['ai_total']},
            "total_est_cost_per_run": roi_data['ai_total'] / 1000.0 if roi_data['ai_total'] > 0 else 0.0
        }
        
        # 3. Call API
        resp = requests.post(
            f"{PRICING_API_URL}/pricing/recommend", 
            json={
                "savings": savings_payload,
                "costs": costs_payload,
                "customer_segment": "smb" # Default
            }
        )
        resp.raise_for_status()
        return resp.json()
        
    except Exception as e:
        st.error(f"Pricing Service Error: {e}")
        return None

def calculate_advanced_roi(feature_id, user_inputs, custom_params, custom_formula=None):
    """
    Performs ROI calculation with Custom Parameters, Formula Transparency, and User-Defined Logic.
    """
    ctx = st.session_state.report_context
    
    # 1. Baseline AI Cost
    ai_cost_monthly = 0.0
    f_map = st.session_state.feature_map
    linked_drivers = [did for did, fid in f_map.items() if fid == feature_id]
    
    driver_breakdown = []
    for cat in ["llm_calls", "infrastructure", "integrations", "data_components"]:
        for item in ctx.get(cat, []):
            if item["id"] in linked_drivers:
                c = item.get("monthly_cost", 0.0)
                ai_cost_monthly += c
                driver_breakdown.append(f"{item.get('name', item.get('model'))}: ${c:.4f}")

    # 2. Core Inputs
    hourly_rate = user_inputs.get("human_hourly_rate", 0.0)
    throughput = user_inputs.get("human_throughput", 1.0) # units/hr
    agent_acc = user_inputs.get("agent_accuracy", 0.99)
    human_acc = user_inputs.get("human_accuracy", 0.95)
    
    quality_factor = agent_acc / human_acc if human_acc > 0 else 1.0

    # 3. Time Savings Calculation (Per 1000 Units)
    units_batch = 1000
    human_hours_per_1k = units_batch / throughput if throughput > 0 else 0
    ai_hours_per_1k = 0.0 # Assume negligible
    
    hours_saved = human_hours_per_1k - ai_hours_per_1k

    # 4. Custom Params Summation
    custom_human_cost = sum(cp['human_val'] for cp in custom_params)
    custom_ai_cost = sum(cp['ai_val'] for cp in custom_params)

    # 5. Base Variables for Formula
    human_cost = (human_hours_per_1k * hourly_rate) + custom_human_cost
    ai_cost = ai_cost_monthly + custom_ai_cost # Assuming monthly cost ~= 1k units cost for this view
    
    # 6. Execute Custom Formula (Safe Eval)
    default_formula = "(human_cost * quality_factor) - ai_cost"
    formula_to_use = custom_formula if custom_formula else default_formula
    
    safe_locals = {
        "human_cost": human_cost,
        "ai_cost": ai_cost,
        "quality_factor": quality_factor,
        "hours_saved": hours_saved,
        "custom_human": custom_human_cost,
        "custom_ai": custom_ai_cost,
        "hourly_rate": hourly_rate,
        "throughput": throughput
    }
    
    try:
        savings = eval(formula_to_use, {"__builtins__": {}}, safe_locals)
    except Exception as e:
        savings = 0.0
        st.error(f"Formula Error: {e}")

    result = {
        "ai_total": ai_cost,
        "human_total": human_cost,
        "quality_factor": quality_factor,
        "hours_saved": hours_saved,
        "savings": savings,
        "driver_details": driver_breakdown
    }
    
    # Save state for Tab 3
    st.session_state.roi_results = result
    st.session_state.roi_feature_id = feature_id
    
    return result

# -----------------------------------------------------------------------------
# UI Pages
# -----------------------------------------------------------------------------

st.title("🤖 Cost Savings Consultant")

tab1, tab2, tab3 = st.tabs(["1. 🗺️ Feature Mapper", "2. 🧮 Custom ROI Calculator", "3. 🏷️ Pricing Designer"])

# --- TAB 1: MAPPER ---
with tab1:
    col_up, col_down = st.columns([1, 2])
    with col_up:
        st.markdown("### 1. Load Context")
        json_val = st.text_area("Paste cost_elements.json", height=100, help="Output from Analyzer")
        if st.button("Load JSON"):
            load_context(json_val)

    if st.session_state.report_context:
        st.divider()
        
        # --- Create Custom Feature ---
        with st.expander("✨ Create Custom Feature", expanded=False):
            c_f1, c_f2 = st.columns([2, 1])
            with c_f1:
                new_feat_name = st.text_input("Feature Name", placeholder="e.g. Legacy Migration")
                new_feat_desc = st.text_input("Description", placeholder="Manual migration of DB...")
            with c_f2:
                st.write(" ") # Spacing
                st.write(" ") 
                if st.button("Create Feature"):
                    if new_feat_name:
                        new_id = f"F_CUSTOM_{uuid.uuid4().hex[:4].upper()}"
                        new_feat = {
                            "id": new_id,
                            "name": new_feat_name,
                            "description": new_feat_desc,
                            "cost_driver_ids": []
                        }
                        st.session_state.report_context["features"].append(new_feat)
                        st.success(f"Created {new_feat_name} ({new_id})")
                        st.rerun()

        st.markdown("### 2. Map Drivers to Features")
        
        ctx = st.session_state.report_context
        
        # --- Feature Reference ---
        with st.expander("📘 Feature Reference Guide"):
            if "features" in ctx:
                ref_data = [{"ID": f["id"], "Name": f["name"], "Description": f["description"]} for f in ctx["features"]]
                st.dataframe(pd.DataFrame(ref_data), hide_index=True, use_container_width=True)

        # --- Editor ---
        id_to_label = {"Unassigned": "Unassigned"}
        label_to_id = {"Unassigned": "Unassigned"}
        if "features" in ctx:
            for f in ctx["features"]:
                label = f"{f['id']}: {f['name']}"
                id_to_label[f["id"]] = label
                label_to_id[label] = f["id"]
        
        feature_options = list(label_to_id.keys())

        rows = []
        for cat in ["llm_calls", "infrastructure", "integrations", "data_components"]:
            for item in ctx.get(cat, []):
                current_fid = st.session_state.feature_map.get(item["id"], "Unassigned")
                current_label = id_to_label.get(current_fid, "Unassigned")
                rows.append({
                    "Driver ID": item["id"],
                    "Category": cat.upper(),
                    "Name": item.get("name", item.get('model', 'Unknown')),
                    "Assigned Feature": current_label 
                })
        
        df = pd.DataFrame(rows)
        edited_df = st.data_editor(
            df,
            column_config={
                "Assigned Feature": st.column_config.SelectboxColumn(
                    "Assigned Feature",
                    options=feature_options,
                    required=True,
                    width="large"
                )
            },
            disabled=["Driver ID", "Category", "Name"],
            hide_index=True,
            use_container_width=True
        )
        
        if st.button("💾 Update Mapping"):
            new_map = {}
            for index, row in edited_df.iterrows():
                selected_label = row["Assigned Feature"]
                real_id = label_to_id.get(selected_label, "Unassigned")
                new_map[row["Driver ID"]] = real_id
            st.session_state.feature_map = new_map
            st.toast("Mapping updated!", icon="✅")

# --- TAB 2: CALCULATOR ---
with tab2:
    if not st.session_state.report_context:
        st.warning("Please load the JSON in the Mapper tab first.")
    else:
        col_conf, col_res = st.columns([1, 1])
        
        with col_conf:
            st.subheader("1. Configuration")
            
            # Feature Selector
            feat_opts = get_feature_options()
            valid_opts = [x for x in feat_opts if x[1] != "Unassigned"]
            selected_feat_tuple = st.selectbox("Target Feature", options=valid_opts, format_func=lambda x: x[0])
            
            if selected_feat_tuple:
                selected_fid = selected_feat_tuple[1]
                
                # Fetch Params
                if st.button("🔄 Fetch AI Parameters"):
                    fetch_schema(selected_fid)
                
                # --- Dynamic Params ---
                user_inputs = {}
                if st.session_state.calc_schema:
                    available = st.session_state.calc_schema.get("available_parameters", [])
                    st.caption("Benchmark Parameters")
                    
                    for pid in st.session_state.active_params:
                        p_def = next((p for p in available if p["id"] == pid), None)
                        if p_def:
                            # Enhanced UI: Label + Unit, Help tooltip for reasoning
                            label = f"{p_def['label']} ({p_def['unit']})"
                            reasoning = p_def.get('reasoning', 'Suggested by AI')
                            
                            val = st.number_input(
                                label=label, 
                                value=float(p_def['default_value']), 
                                help=f"💡 AI Reasoning: {reasoning}",
                                key=f"in_{pid}"
                            )
                            user_inputs[pid] = val
                    
                    # Add Param
                    unused = [p for p in available if p["id"] not in st.session_state.active_params]
                    if unused:
                        new_p = st.selectbox("Add Benchmark:", options=["Select..."] + [p["label"] for p in unused])
                        if new_p != "Select...":
                            target = next(p for p in unused if p["label"] == new_p)
                            if st.button("➕"):
                                st.session_state.active_params.append(target["id"])
                                st.rerun()

                st.divider()
                
                # --- Custom Params ---
                st.markdown("#### Custom Cost Variables")
                with st.expander("Add New Variable", expanded=False):
                    cp_name = st.text_input("Name", placeholder="e.g. Server Electricity")
                    c_ai, c_hu = st.columns(2)
                    cp_ai = c_ai.number_input("Project Side Cost ($)", 0.0)
                    cp_hu = c_hu.number_input("Human Side Cost ($)", 0.0)
                    
                    if st.button("Add Variable"):
                        st.session_state.custom_params.append({"name": cp_name, "ai_val": cp_ai, "human_val": cp_hu})
                        st.rerun()
                
                if st.session_state.custom_params:
                    for i, cp in enumerate(st.session_state.custom_params):
                        st.write(f"🔹 **{cp['name']}**: AI=${cp['ai_val']} | Human=${cp['human_val']}")
                        if st.button(f"Remove {cp['name']}", key=f"del_{i}"):
                            st.session_state.custom_params.pop(i)
                            st.rerun()

        with col_res:
            st.subheader("2. Strategic ROI Analysis")
            
            if selected_feat_tuple:
                # Formula Editor
                st.markdown("#### 📐 Savings Formula")
                default_formula = "(human_cost * quality_factor) - ai_cost"
                custom_formula = st.text_area("Edit Logic (Python syntax):", value=default_formula, height=68)
                st.caption("Available: `human_cost`, `ai_cost`, `quality_factor`, `hours_saved`, `hourly_rate`")

                # Run Calc
                res = calculate_advanced_roi(selected_feat_tuple[1], user_inputs, st.session_state.custom_params, custom_formula)
                
                st.divider()
                
                # Results
                m1, m2, m3 = st.columns(3)
                m1.metric("Time Savings", f"{res['hours_saved']:.1f} hrs", help="Per 1000 units")
                m2.metric("Net Savings ($)", f"${res['savings']:,.2f}", delta_color="normal")
                m3.metric("Quality Factor", f"{res['quality_factor']:.2f}x")
                
                st.success(f"**Strategic Insight:** Saving **{res['hours_saved']:.1f} hours** creates **${res['savings']:,.2f}** in value per batch.")
                
                with st.expander("Detailed Breakdown"):
                    st.write(res['driver_details'])
                    st.write(f"**Human Total:** ${res['human_total']:.2f}")
                    st.write(f"**AI Total:** ${res['ai_total']:.2f}")

with tab3:
    st.header("💰 Pricing Proposal Generation")
    
    if "report_context" not in st.session_state or st.session_state.report_context is None:
        st.warning("⚠️ Please complete Step 1 (Cost Analysis) first to generate ROI data.")
        st.stop()
    
    if "roi_results" not in st.session_state or st.session_state.roi_results is None:
        st.warning("⚠️ Please complete Step 2 (ROI Calculation) first.")
        st.stop()
    
    # Now safe to access
    roi_data = st.session_state.roi_results
    report_context = st.session_state.report_context
    
    st.subheader("📊 Current ROI Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Monthly Savings", f"${roi_data['savings']:,.0f}")
    with col2:
        st.metric("Hours Saved", f"{roi_data['hours_saved']:.0f}")
    with col3:
        st.metric("Quality Factor", f"{roi_data['quality_factor']:.2f}x")
    
    st.divider()
    
    # Feature selection
    features = report_context.get("features", [])
    if not features:
        st.error("No features found in cost analysis. Please rerun Step 1.")
    else:
        feature_options = {f["name"]: f["id"] for f in features}
        selected_feature_name = st.selectbox(
            "Select Feature to Price",
            options=list(feature_options.keys()),
            help="Choose which feature to generate pricing for"
        )
        selected_feature_id = feature_options[selected_feature_name]
        
        customer_segment = st.radio(
            "Target Customer Segment",
            options=["smb", "mid_market", "enterprise"],
            index=0,
            horizontal=True,
            help="Different segments get different pricing strategies"
        )
        
        if st.button("🚀 Generate Pricing Recommendation", type="primary", use_container_width=True):
            with st.spinner("🤖 AI is analyzing your value proposition and generating pricing..."):
                try:
                    # Import transformer
                    import sys
                    sys.path.append("../pricing-service")
                    from core.transformers import transform_cost_profile, transform_value_credits
                    
                    # STEP 1: Transform cost profile
                    costs_payload = transform_cost_profile(
                        report_context,
                        selected_feature_id
                    ).model_dump()
                    
                    # STEP 2: Build savings summary
                    savings_payload = {
                        "feature_id": selected_feature_id,
                        "benefit_units": roi_data.get('benefit_units', {}),
                        "human_hours_saved": roi_data['hours_saved'],
                        "estimated_monthly_savings_usd": roi_data['savings'],
                        "quality_factor": roi_data['quality_factor']
                    }
                    
                    # STEP 3: Generate value credits
                    credits_list = transform_value_credits(
                        benefit_units=roi_data.get('benefit_units', {}),
                        quality_factor=roi_data['quality_factor'],
                        feature_id=selected_feature_id
                    )
                    value_credits = [c.model_dump() for c in credits_list]
                    
                    # STEP 4: Call pricing API
                    pricing_request = {
                        "savings": savings_payload,
                        "costs": costs_payload,
                        "value_credits": value_credits,
                        "customer_segment": customer_segment
                    }
                    
                    response = requests.post(
                        f"{PRICING_API_URL}/pricing/recommend",
                        json=pricing_request,
                        timeout=30
                    )
                    
                    if response.status_code == 201:
                        pricing_config = response.json()
                        
                        # Extract metadata from headers
                        confidence = response.headers.get('X-Pricing-Confidence', 'N/A')
                        pi_score = response.headers.get('X-Pricing-Index', 'N/A')
                        strategy = response.headers.get('X-Strategy-Used', 'N/A')
                        
                        st.session_state.generated_pricing = pricing_config
                        st.session_state.original_pricing = pricing_config.copy()  # Save original
                        st.session_state.pricing_metadata = {
                            'confidence': confidence,
                            'pi_score': pi_score,
                            'strategy': strategy,
                            'cost_per_run': costs_payload['total_est_cost_per_run']
                        }
                        
                        st.success("✅ Pricing recommendation generated successfully!")
                        st.rerun()
                    else:
                        st.error(f"❌ Pricing generation failed: {response.status_code} - {response.text}")
                
                except Exception as e:
                    st.error(f"❌ Error generating pricing: {str(e)}")
                    st.exception(e)
    
    # Display and EDIT generated pricing
    if "generated_pricing" in st.session_state:
        st.divider()
        st.subheader("📋 Pricing Configuration Editor")
        
        p_config = st.session_state.generated_pricing
        metadata = st.session_state.get('pricing_metadata', {})
        cost_per_run = float(metadata.get('cost_per_run', 0.05))
        
        # Metadata badges
        col1, col2, col3 = st.columns(3)
        with col1:
            conf_val = metadata.get('confidence', 0)
            conf_pct = float(conf_val) * 100 if conf_val != 'N/A' else 0
            st.metric("AI Confidence", f"{conf_pct:.0f}%")
        with col2:
            st.metric("Pricing Index", metadata.get('pi_score', 'N/A'))
        with col3:
            st.metric("Strategy", metadata.get('strategy', 'N/A').replace('_', ' ').title())
        
        st.markdown(f"### {p_config['name']}")
        st.caption(p_config.get('desc', 'No description provided'))
        
        model = p_config['models'][0]
        st.markdown(f"**Model Type:** {model['type']}")
        
        st.divider()
        
        # EDITABLE FORM
        st.markdown("#### 🎛️ Adjust Pricing Components")
        st.caption("Modify the AI-generated pricing to match your strategy")
        
        with st.form("pricing_editor"):
            edited_components = []
            
            for idx, comp in enumerate(model['components']):
                comp_type = comp['component_type']
                
                st.markdown(f"**Component {idx+1}: {comp_type}**")
                
                if comp_type == "BASE_FEE":
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        new_amount = st.slider(
                            "Monthly Base Fee ($)",
                            min_value=0.0,
                            max_value=500.0,
                            value=float(comp['amount']),
                            step=5.0,
                            key=f"base_{idx}",
                            help="Minimum monthly charge. Round to $X9 or $X5 for pricing psychology."
                        )
                    with col2:
                        st.metric("Current", f"${comp['amount']:.0f}")
                    
                    # Update component
                    comp['amount'] = new_amount
                    edited_components.append(comp)
                
                elif comp_type == "USAGE":
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        dimension = comp.get('usage_dimension', 'unit')
                        
                        # Smart slider range based on cost
                        min_price = cost_per_run * 1.2  # 20% markup minimum
                        max_price = cost_per_run * 10.0  # 10x markup maximum
                        current_price = float(comp['unit_price'])
                        
                        new_price = st.slider(
                            f"Usage Price per {dimension} ($)",
                            min_value=float(min_price),
                            max_value=float(max_price),
                            value=float(current_price),
                            step=0.001,
                            format="%.4f",
                            key=f"usage_{idx}",
                            help=f"Cost per {dimension}. Min based on your technical cost (${cost_per_run:.4f})"
                        )
                    with col2:
                        st.metric("Current", f"${comp['unit_price']:.4f}")
                    
                    # Calculate implied margin
                    if cost_per_run > 0:
                        margin = (new_price - cost_per_run) / new_price
                        
                        if margin < 0.3:
                            st.error(f"⚠️ Low Margin: {margin*100:.1f}% (Target: >40%)")
                        elif margin < 0.5:
                            st.warning(f"⚠️ Moderate Margin: {margin*100:.1f}% (Target: >40%)")
                        else:
                            st.success(f"✅ Healthy Margin: {margin*100:.1f}%")
                    
                    # Update component
                    comp['unit_price'] = new_price
                    edited_components.append(comp)
                
                elif comp_type == "OUTCOME":
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        dimension = comp.get('outcome_dimension', 'outcome')
                        new_price = st.number_input(
                            f"Outcome Price per {dimension} ($)",
                            min_value=0.0,
                            value=float(comp['unit_price']),
                            step=1.0,
                            format="%.2f",
                            key=f"outcome_{idx}",
                            help=f"Price per successful {dimension}"
                        )
                    with col2:
                        st.metric("Current", f"${comp['unit_price']:.2f}")
                    
                    # Update component
                    comp['unit_price'] = new_price
                    edited_components.append(comp)
                
                st.markdown("---")
            
            # Form action buttons
            col1, col2 = st.columns(2)
            
            with col1:
                save_edited = st.form_submit_button(
                    "💾 Save Edited Configuration",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                restore_original = st.form_submit_button(
                    "🔄 Restore AI Suggestion",
                    use_container_width=True
                )
        
        # Handle form submission
        if save_edited:
            with st.spinner("Saving edited configuration..."):
                try:
                    # Update model components
                    p_config['models'][0]['components'] = edited_components
                    p_config['status'] = 'active'  # Mark as active since manually edited
                    
                    # Save to pricing service
                    save_response = requests.post(
                        f"{PRICING_API_URL}/pricing/config",
                        json=p_config,
                        timeout=10
                    )
                    
                    if save_response.status_code in [200, 201]:
                        st.session_state.generated_pricing = p_config
                        st.success("✅ Edited configuration saved successfully!")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(f"Failed to save: {save_response.status_code}")
                
                except Exception as e:
                    st.error(f"Error saving configuration: {str(e)}")
        
        if restore_original:
            if "original_pricing" in st.session_state:
                st.session_state.generated_pricing = st.session_state.original_pricing.copy()
                st.info("🔄 Restored original AI-generated pricing")
                st.rerun()
        
        st.divider()
        
        # Invoice Preview Calculator
        st.subheader("💰 Invoice Preview Calculator")
        st.caption("Estimate your monthly bill based on expected usage")
        
        with st.form("invoice_preview_form"):
            # Collect usage inputs based on components
            usage_inputs = {}
            
            for comp in model['components']:
                if comp['component_type'] == "USAGE":
                    dimension = comp.get('usage_dimension', 'workflow_run')
                    default_val = 1000 if 'run' in dimension else 100
                    usage_inputs[dimension] = st.number_input(
                        f"Expected {dimension.replace('_', ' ').title()} per Month",
                        min_value=0,
                        value=default_val,
                        step=10,
                        key=f"usage_preview_{dimension}"
                    )
                
                elif comp['component_type'] == "OUTCOME":
                    dimension = comp.get('outcome_dimension', 'outcome')
                    usage_inputs[dimension] = st.number_input(
                        f"Expected {dimension.replace('_', ' ').title()} per Month",
                        min_value=0,
                        value=10,
                        step=1,
                        key=f"outcome_preview_{dimension}"
                    )
            
            calculate_btn = st.form_submit_button("Calculate Invoice", use_container_width=True)
        
        if calculate_btn:
            with st.spinner("Calculating preview..."):
                try:
                    preview_request = {
                        "config_id": p_config['pricing_config_id'],
                        "hypothetical_usage": usage_inputs,
                        "period_days": 30
                    }
                    
                    preview_response = requests.post(
                        f"{PRICING_API_URL}/pricing/preview",
                        json=preview_request,
                        timeout=10
                    )
                    
                    if preview_response.status_code == 200:
                        preview = preview_response.json()
                        
                        # Large display of total
                        st.success(f"### 💵 Estimated Monthly Bill: ${preview['subtotal']:,.2f} {preview['currency']}")
                        
                        # Detailed breakdown
                        with st.expander("📋 Line Item Breakdown", expanded=True):
                            # Header row
                            col1, col2, col3 = st.columns([2, 1, 1])
                            with col1:
                                st.markdown("**Description**")
                            with col2:
                                st.markdown("**Quantity**")
                            with col3:
                                st.markdown("**Amount**")
                            
                            st.markdown("---")
                            
                            # Line items
                            for line in preview['lines']:
                                col1, col2, col3 = st.columns([2, 1, 1])
                                with col1:
                                    st.text(line['description'])
                                with col2:
                                    if line.get('quantity', 1) > 1:
                                        st.text(f"{line['quantity']:,.0f} × ${line['unit_price']:.4f}")
                                    else:
                                        st.text("Fixed")
                                with col3:
                                    st.text(f"${line['amount']:,.2f}")
                        
                        st.info(preview['note'])
                    else:
                        st.error(f"Preview calculation failed: {preview_response.status_code}")
                
                except Exception as e:
                    st.error(f"Error calculating preview: {str(e)}")
        
        st.divider()
        
        # Export and action buttons
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("📥 Download JSON", use_container_width=True):
                import json
                json_str = json.dumps(p_config, indent=2)
                st.download_button(
                    label="Save File",
                    data=json_str,
                    file_name=f"pricing_{p_config['pricing_config_id']}.json",
                    mime="application/json",
                    use_container_width=True
                )
        
        with col2:
            if st.button("📊 View All Configs", use_container_width=True):
                try:
                    resp = requests.get(f"{PRICING_API_URL}/pricing/configs?limit=10")
                    if resp.status_code == 200:
                        configs = resp.json()
                        st.session_state.all_configs = configs
                        st.success(f"Loaded {len(configs)} configurations")
                except Exception as e:
                    st.error(f"Failed to load configs: {str(e)}")
        
        with col3:
            if st.button("🔄 Generate New", use_container_width=True):
                # Clear session state
                if 'generated_pricing' in st.session_state:
                    del st.session_state.generated_pricing
                if 'original_pricing' in st.session_state:
                    del st.session_state.original_pricing
                if 'pricing_metadata' in st.session_state:
                    del st.session_state.pricing_metadata
                st.rerun()
        
        # Show all configs if loaded
        if "all_configs" in st.session_state:
            st.divider()
            st.subheader("📚 All Pricing Configurations")
            
            for cfg in st.session_state.all_configs:
                with st.expander(f"{cfg['name']} ({cfg['status']})"):
                    st.json(cfg)
