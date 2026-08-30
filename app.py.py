import subprocess
import sys

# --- DYNAMIC DEPENDENCY INSTALLER BYPASS ---
# This forces Streamlit Cloud to download openpyxl even if requirement.txt.txt is misread
try:
    import openpyxl
    from openpyxl import Workbook
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl
    from openpyxl import Workbook

import streamlit as st
import pandas as pd
import io

# --- PAGE CONFIGURATION & THEME ---
st.set_page_config(page_title="Bajet Sunuwai AI Portal", layout="wide", page_icon="🇳🇵")

# --- INITIALIZE MOCK FREE DATABASE (In-Memory Session State) ---
if 'budget_pool' not in st.session_state:
    st.session_state.budget_pool = 50000000  # Total 5 Crore NPR available
if 'complaints' not in st.session_state:
    st.session_state.complaints = [
        {"ID": "CMP-001", "Ward": "Ward 3", "Sector": "Water", "Language": "Maithili", "Text": "कल गढबढ अछि, पानि नै आबैए।", "Priority": "🔴 High", "Status": "Recurring (Escalated)"},
        {"ID": "CMP-002", "Ward": "Ward 1", "Sector": "Roads", "Language": "Nepali", "Text": "पिच बाटो खनेर अलकत्रा हालेकै छैन, धुलो उड्यो।", "Priority": "🔴 High", "Status": "Budget-Linked"},
        {"ID": "CMP-003", "Ward": "Ward 4", "Sector": "Irrigation", "Language": "Nepali", "Text": "सिचाई कुलो थुनियो, धान बाली सुक्न लाग्यो।", "Priority": "🟡 Medium", "Status": "Filed"},
        {"ID": "CMP-004", "Ward": "Ward 3", "Sector": "Water", "Language": "Maithili", "Text": "इनार सुखि गेल छै, पीने वाला पानी नै छै।", "Priority": "🔴 High", "Status": "Recurring (Escalated)"},
    ]
if 'allocations' not in st.session_state:
    st.session_state.allocations = [
        {"Project Name": "Ward 1 Primary Road Pitch Repair", "Ward": "Ward 1", "Sector": "Roads", "AI Allocated (NPR)": 15000000, "Justification": "Matches High-Urgency Road Complaint Cluster"},
        {"Project Name": "Ward 3 Deep Tube-well Installation", "Ward": "Ward 3", "Sector": "Water", "AI Allocated (NPR)": 8000000, "Justification": "Fixes 2 Recurring Water Crisis Complaints"},
        {"Project Name": "Administrative Oversight & Salaries", "Ward": "All", "Sector": "Admin", "AI Allocated (NPR)": 12000000, "Justification": "Fixed Statutory Budget Overhead"}
    ]

# --- APP HEADER ---
st.title("🇳🇵 Bajet Sunuwai (बजेट सुनुवाई)")
st.caption("Agentic AI Financial Allocation & Civic Accountability Framework for Nepal's Local Governments")

# --- LIVE STATS BAR ---
total_allocated = sum(item["AI Allocated (NPR)"] for item in st.session_state.allocations)
remaining_budget = st.session_state.budget_pool - total_allocated

col1, col2, col3 = st.columns(3)
col1.metric("Total Budget Pool", f"NPR {st.session_state.budget_pool:,.2f}")
col2.metric("Allocated Budget", f"NPR {total_allocated:,.2f}", delta=f"{total_allocated/st.session_state.budget_pool*100:.1f}% Use")
col3.metric("Remaining Contingency", f"NPR {remaining_budget:,.2f}", delta_color="inverse" if remaining_budget < 0 else "normal")

# --- SYSTEM TABS ---
tab1, tab2, tab3 = st.tabs(["📊 Citizen Complaint & Escalation Box", "🛠️ Engineer Dashboard & Excel Loop", "🚨 Hello Sarkar Escalations"])

# TAB 1: CITIZEN INPUT LAYER
with tab1:
    st.header("📥 Ingested Local Grievances (Google Forms & Ward Boxes)")
    st.write("Our Translation and Sentiment Agents automatically cluster multilingual text submissions into urgency metrics.")
    
    df_complaints = pd.DataFrame(st.session_state.complaints)
    st.dataframe(df_complaints, use_container_width=True)
    
    st.markdown("---")
    st.subheader("Simulate a Live Citizen Entry via Google Forms")
    with st.form("citizen_form"):
        c_ward = st.selectbox("Select Ward", ["Ward 1", "Ward 2", "Ward 3", "Ward 4", "Ward 5"])
        c_sector = st.selectbox("Sector", ["Roads", "Water", "Irrigation", "Health", "Education"])
        c_lang = st.selectbox("Language", ["Nepali", "Maithili", "Bhojpuri", "English"])
        c_text = st.text_area("Your Grievance (Natural Text Input)")
        
        submitted = st.form_submit_button("Submit to Bajet Sunuwai System")
        
        if submitted and c_text:
            new_id = f"CMP-00{len(st.session_state.complaints) + 1}"
            st.session_state.complaints.append({
                "ID": new_id, "Ward": c_ward, "Sector": c_sector, "Language": c_lang, "Text": c_text, "Priority": "🔴 High", "Status": "Filed"
            })
            st.success(f"🤖 AI Ingestion Agent successfully parsed grievance as High Priority. Logged as {new_id}!")
            st.rerun()

# TAB 2: EXCEL INTERFACE LOOP
with tab2:
    st.header("🏗️ Engineer Allocations & Bidirectional Excel Interface")
    st.info("The Planning Engineer can inspect the AI-suggested budget, edit it manually via Microsoft Excel offline, and re-upload it.")
    
    df_alloc = pd.DataFrame(st.session_state.allocations)
    st.dataframe(df_alloc, use_container_width=True)
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_alloc.to_excel(writer, index=False, sheet_name="AI_Budget_Allocation_Draft")
    buffer.seek(0)
    
    st.download_button(
        label="📥 Download Budget Draft to Excel (.xlsx)",
        data=buffer,
        file_name="bajet_sunuwai_draft.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    
    st.markdown("---")
    st.subheader("🔄 Re-upload Revised Spreadsheet (Human-In-The-Loop Override)")
    uploaded_file = st.file_uploader("Choose the modified Excel file to instantly recalculate citizen notification matrices:", type=["xlsx"])
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_excel(uploaded_file, engine='openpyxl')
            st.session_state.allocations = uploaded_df.to_dict(orient="records")
            st.success("✅ Financial allocations synchronized with Engineer's adjustments! Citizen SMS pipelines triggered.")
            st.rerun()
        except Exception as e:
            st.error(f"Error parsing file: {e}")

# TAB 3: ACCOUNTABILITY MATRIX
with tab3:
    st.header("🚨 Hello Sarkar Automatic Audit & Escalation Engine")
    st.write("When a grievance is labeled 'Resolved' by field operators but citizens report identical issues again, the system escalates past local municipal backlogs.")
    
    recurring = [c for c in st.session_state.complaints if c["Status"] == "Recurring (Escalated)"]
    if recurring:
        for item in recurring:
            with st.expander(f"⚠️ {item['ID']} — {item['Ward']} ({item['Sector']})"):
                st.write(f"**Citizen Issue Statement:** {item['Text']}")
                st.write(f"**Language Tracked:** {item['Language']}")
                st.error("🚨 **System Status:** Escalated to Hello Sarkar Central Dashboard due to repeated local funding bypasses.")
    else:
        st.success("All localized recurring threats have successfully matched open budgeting blocks.")
