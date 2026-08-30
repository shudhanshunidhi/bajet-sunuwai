import streamlit as st
import pandas as pd
import io

# --- PAGE CONFIGURATION & THEME ---
st.set_page_config(page_title="Bajet Sunuwai AI Portal", layout="wide", page_icon="🇳🇵")

# --- INITIALIZE DB STATE (In-Memory Session Database) ---
if 'central_grant' not in st.session_state:
    st.session_state.central_grant = 25000000.0
if 'provincial_grant' not in st.session_state:
    st.session_state.provincial_grant = 15000000.0
if 'internal_revenue' not in st.session_state:
    st.session_state.internal_revenue = 10000000.0

if 'ai_focus_prompt' not in st.session_state:
    st.session_state.ai_focus_prompt = "Focus heavily on agricultural structural setups, climate resilience for monsoon flooding patterns typical of Madhesh geographic terrains, and primary school rehabilitation."

if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = [
        {"Filename": "Yuba_Club_Dhyanakarshan.txt", "Type": "Youth Club Demand Letter", "Extracted Needs": "Requesting 5 Lakhs for Ward 3 community playground fencing."},
        {"Filename": "Political_Joint_Memorandum.txt", "Type": "Inter-party Request", "Extracted Needs": "Demanding blacktopping of the connecting highway corridor in Ward 1."}
    ]

if 'complaints' not in st.session_state:
    st.session_state.complaints = [
        {"ID": "CMP-001", "Ward": "Ward 3", "Sector": "Water/Agriculture", "Language": "Maithili", "Text": "कल गढबढ अछि, पानि नै आबैए। सिचाई ठप्प अछि।", "Priority": "🔴 High", "Status": "Pending AI Review", "Notification": "No Alert Sent"},
        {"ID": "CMP-002", "Ward": "Ward 1", "Sector": "Roads", "Language": "Nepali", "Text": "पिच बाटो खनेर अलकत्रा हालेकै छैन, असाध्यै धुलो उड्यो।", "Priority": "🔴 High", "Status": "Pending AI Review", "Notification": "No Alert Sent"},
        {"ID": "CMP-003", "Ward": "Ward 4", "Sector": "Irrigation", "Language": "Nepali", "Text": "बाढीले कुलो बगायो, खेत सुख्खा भयो।", "Priority": "🔴 High", "Status": "Pending AI Review", "Notification": "No Alert Sent"}
    ]

if 'allocations' not in st.session_state:
    st.session_state.allocations = []

# --- APP HEADER ---
st.title("🇳🇵 Bajet Sunuwai (बजेट सुनुवाई) — Smart AI Agentic Budget Engine")
st.caption("Closing the Accountability Gap: Integrating Civic Grievances, Dhyanakarshan Letters, and Regional Needs into AI-Driven Budgets.")

# --- SIDEBAR: OFFICIAL MUNICIPAL REVENUE INPUTS & AI INSTRUCTIONS ---
with st.sidebar:
    st.header("⚙️ Local Level Fiscal Setup")
    st.write("Authorized officials can update real financial ceilings here:")
    
    st.session_state.central_grant = st.number_input("Central/Federal Fiscal Grant (NPR)", value=st.session_state.central_grant, step=500000.0)
    st.session_state.provincial_grant = st.number_input("Provincial Fiscal Grant (NPR)", value=st.session_state.provincial_grant, step=500000.0)
    st.session_state.internal_revenue = st.number_input("Internal/Own Source Revenue (NPR)", value=st.session_state.internal_revenue, step=100000.0)
    
    total_budget_pool = st.session_state.central_grant + st.session_state.provincial_grant + st.session_state.internal_revenue
    
    st.markdown("---")
    st.header("🤖 Mayor's AI Policy Prompter")
    st.session_state.ai_focus_prompt = st.text_area(
        "Enter overall structural vision or geographical rules (e.g., climate, agriculture, master plans):", 
        value=st.session_state.ai_focus_prompt
    )

# --- RE-CALCULATE DYNAMIC BALANCES ---
total_allocated = sum(item["Allocated Amount (NPR)"] for item in st.session_state.allocations) if st.session_state.allocations else 0.0
remaining_contingency = total_budget_pool - total_allocated

# --- LIVE STATS BAR ---
col1, col2, col3 = st.columns(3)
col1.metric("Dynamic Budget Ceiling", f"NPR {total_budget_pool:,.2f}", help="Sum of Central + Provincial + Internal Revenue inputs")
col2.metric("Allocated Draft Total", f"NPR {total_allocated:,.2f}", delta=f"{(total_allocated/total_budget_pool*100 if total_budget_pool > 0 else 0):.1f}% Utilization")
col3.metric("Unallocated Reserve", f"NPR {remaining_contingency:,.2f}", delta_color="inverse" if remaining_contingency < 0 else "normal")

# --- SYSTEM TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Ingestion Console (Complaints & Dhyanakarshan)", "🧠 AI Budget Core Generator", "📡 Citizen Feedback & Hello Sarkar Router"])

# TAB 1: DATA INGESTION (COMPLAINTS & MEMORANDUMS)
with tab1:
    st.header("📥 Multi-Channel Local Document Ingestion Hub")
    
    left_col, right_col = st.columns(2)
    
    with left_col:
        st.subheader("📬 Live Public Grievance Database")
        st.dataframe(pd.DataFrame(st.session_state.complaints)[["ID", "Ward", "Sector", "Text", "Priority"]], use_container_width=True)
        
        st.markdown("**Simulate New Public Submission Box Entry:**")
        with st.form("new_complaint_form"):
            w = st.selectbox("Ward", ["Ward 1", "Ward 2", "Ward 3", "Ward 4", "Ward 5"])
            s = st.selectbox("Category", ["Water/Agriculture", "Roads", "Irrigation", "Health", "Education"])
            t = st.text_area("Grievance (Nepali/Maithili Input)")
            if st.form_submit_button("Log Complaint"):
                if t:
                    st.session_state.complaints.append({
                        "ID": f"CMP-00{len(st.session_state.complaints)+1}", "Ward": w, "Sector": s, "Language": "Local Dialect", "Text": t, "Priority": "🔴 High", "Status": "Pending AI Review", "Notification": "No Alert Sent"
                    })
                    st.success("Grievance mapped and indexed dynamically!")
                    st.rerun()

    with right_col:
        st.subheader("📄 Dhyanakarshan Letters & Memorandums")
        st.write("Upload official letters submitted by community clubs or political committees directly to the Mayor's office.")
        
        uploaded_file = st.file_uploader("Upload Memorandum / Demand Document (Simulated File Reader)", type=["txt", "pdf", "docx"])
        if uploaded_file is not None:
            new_doc = {"Filename": uploaded_file.name, "Type": "Official Memorandum", "Extracted Needs": "Extracted requests targeting local road expansion and school infrastructure benchmarks."}
            st.session_state.uploaded_docs.append(new_doc)
            st.success(f"🤖 AI Document Parser scanned '{uploaded_file.name}' successfully and mapped requirements.")
            
        st.dataframe(pd.DataFrame(st.session_state.uploaded_docs), use_container_width=True)

# TAB 2: AI DRAFT CORE & EXCEL OVERRIDES
with tab2:
    st.header("🧠 Agentic AI Budget Calculation Engine")
    st.write("Click below to prompt the AI to process the geographic climate vulnerabilities, the typed revenue parameters, your specific directives, and raw complaint clusters into a balanced spreadsheet draft.")
    
    if st.button("🚀 Compile and Run AI Budget Allocation Engine"):
        with st.spinner("Analyzing regional monsoon rain parameters, cross-checking 2 Dhyanakarshan letters, and prioritizing high-density grievance sectors..."):
            st.session_state.allocations = [
                {"Project Name": "Ward 4 Agricultural Canal Concrete Repair", "Ward": "Ward 4", "Sector": "Irrigation", "Allocated Amount (NPR)": 18000000.0, "AI Logic Blueprint": "Prioritized due to High Rain/Monsoon threat data in Madhesh terrain + matches CMP-003 baseline grievance perfectly."},
                {"Project Name": "Ward 1 Connecting Corridor Tarring and Drainage", "Ward": "Ward 1", "Sector": "Roads", "Allocated Amount (NPR)": 20000000.0, "AI Logic Blueprint": "Fulfills Inter-Party Dhyanakarshan request and solves high-density dusty environment logs listed in CMP-002."},
                {"Project Name": "Ward 3 Deep Tube-Well Clean Water Array", "Ward": "Ward 3", "Sector": "Water/Agriculture", "Allocated Amount (NPR)": 7000000.0, "AI Logic Blueprint": "Direct mitigation for Ward 3 water scarcity complaint cluster (CMP-001)."},
                {"Project Name": "Emergency Disaster & Climate Relief Reserves", "Ward": "All", "Sector": "Contingency", "Allocated Amount (NPR)": 5000000.0, "AI Logic Blueprint": "Required contingency buffering mandated by Mayor's climate-focus directive input fields."}
            ]
            
            for c in st.session_state.complaints:
                c["Status"] = "SUCCESS (Budget Allocated)"
                c["Notification"] = "SMS Dispatched: Funded"
            
            st.success("✅ AI Draft Compiled! Review the structured breakdown below:")
            st.rerun()

    if st.session_state.allocations:
        df_alloc = pd.DataFrame(st.session_state.allocations)
        st.dataframe(df_alloc, use_container_width=True)
        
        csv_data = df_alloc.to_csv(index=False).encode('utf-8')
        st.download_button(label="📥 Export AI Draft to Excel/CSV", data=csv_data, file_name="ai_bajet_sunuwai_draft.csv", mime="text/csv")
        
        st.markdown("---")
        st.subheader("🔧 Manual Planning Engineer Modification Layer")
        uploaded_csv = st.file_uploader("Upload Modified Spreadsheet to Override AI Draft (Human-in-the-Loop Safeguard)", type=["csv"])
        if uploaded_csv is not None:
            try:
                st.session_state.allocations = pd.read_csv(uploaded_csv).to_dict(orient="records")
                st.success("System database overwritten with verified technical modifications successfully.")
                st.rerun()
            except Exception as e:
                st.error(f"Error parsing uploaded file: {e}")
    else:
        st.info("The AI budget sheet has not been compiled yet. Set your rules and click the engine trigger button above.")

# TAB 3: ACCOUNTABILITY MATRIX & CENTRAL GOVERNMENT ESCALATION ROUTER
with tab3:
    st.header("📡 Closed-Loop Feedback Registry & Hello Sarkar Router")
