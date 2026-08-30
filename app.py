import streamlit as st
import pandas as pd
import io
import os
import sys

# --- FOOLPROOF INLINE EXCEL INSTALLER ---
# Ensures the .xlsx generation runs perfectly on Streamlit Cloud without setup crashes
try:
    import openpyxl
    from openpyxl import Workbook
except ImportError:
    os.system(f"{sys.executable} -m pip install openpyxl")
    try:
        import openpyxl
    except Exception:
        pass

# --- PAGE CONFIGURATION & THEME STYLING ---
st.set_page_config(
    page_title="Bajet Sunuwai — Digital Local Governance Platform", 
    layout="wide", 
    page_icon="🇳🇵"
)

# Custom Clean CSS Styling for Hackathon Aesthetics
st.markdown("""
    <style>
    .main-title { font-size: 2.4rem; font-weight: 800; color: #1E3A8A; margin-bottom: 0.2rem; }
    .subtitle { font-size: 1.1rem; color: #4B5563; margin-bottom: 1.5rem; }
    .section-header { font-size: 1.5rem; font-weight: 700; color: #0F172A; margin-top: 1rem; margin-bottom: 0.8rem; border-left: 5px solid #2563EB; padding-left: 10px; }
    .card { background-color: #F8FAFC; padding: 20px; border-radius: 10px; border: 1px solid #E2E8F0; margin-bottom: 15px; }
    .badge-high { background-color: #FEE2E2; color: #991B1B; padding: 4px 8px; border-radius: 5px; font-weight: bold; font-size: 0.8rem; }
    .badge-status { background-color: #DBEAFE; color: #1E40AF; padding: 4px 8px; border-radius: 5px; font-weight: bold; font-size: 0.8rem; }
    </style>
""", unsafe_with_html=True)

# --- INITIALIZE SECURE STATE DATABASE ---
if 'central_grant' not in st.session_state:
    st.session_state.central_grant = 25000000.0
if 'provincial_grant' not in st.session_state:
    st.session_state.provincial_grant = 15000000.0
if 'internal_revenue' not in st.session_state:
    st.session_state.internal_revenue = 10000000.0
if 'ai_focus_prompt' not in st.session_state:
    st.session_state.ai_focus_prompt = "Prioritize agricultural structural setups, climate resilience for monsoon flooding patterns typical of Madhesh geographic terrains, and secondary road corridor network connections."

if 'complaints' not in st.session_state:
    st.session_state.complaints = [
        {"ID": "CMP-101", "Ward": "Ward 3", "Sector": "Water & Sanitation", "Language": "Maithili", "Text": "कल गढबढ अछि, पानि नै आबैए। स्वच्छ पीबयबला पानि के समस्या भेल अछि।", "Priority": "🔴 High Priority", "Status": "Pending Review", "Official Response": "", "Budget Linked": "No", "Days Unresolved": 8},
        {"ID": "CMP-102", "Ward": "Ward 1", "Sector": "Road Infrastructure", "Language": "Nepali", "Text": "पिच बाटो खनेर अलकत्रा हालेकै छैन, जताततै धुलो उडेर बुढाबुढी र बच्चाहरु बिरामी परे।", "Priority": "🔴 High Priority", "Status": "Pending Review", "Official Response": "", "Budget Linked": "No", "Days Unresolved": 9},
        {"ID": "CMP-103", "Ward": "Ward 4", "Sector": "Agriculture & Irrigation", "Language": "Nepali", "Text": "मनसुनको बाढीले सिचाई कुलो बगायो, धान बाली सुक्न लाग्यो। पुनर्निर्माण छिटो गरियोस्।", "Priority": "🔴 High Priority", "Status": "Pending Review", "Official Response": "", "Budget Linked": "No", "Days Unresolved": 2}
    ]

if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = [
        {"Source": "Local Tole Bikas Samiti", "Type": "Dhyanakarshan Letter", "Details": "Demanding NPR 5,00,000 for local public park preservation and perimeter wire fence construction."},
        {"Source": "Joint Political Committee", "Type": "Memorandum", "Details": "Urging allocation for blacktopping the primary connecting market corridor in Ward 1."}
    ]

if 'allocations' not in st.session_state:
    st.session_state.allocations = []
if 'budget_published' not in st.session_state:
    st.session_state.budget_published = False

# --- BRANDING LAYER ---
st.markdown('<div class="main-title">🇳🇵 Bajet Sunuwai (बजेट सुनुवाई)</div>', unsafe_with_html=True)
st.markdown('<div class="subtitle">An Agentic AI Civic Accountability Framework Connecting Local Public Feedback Closures directly to Municipal Capital Allocations.</div>', unsafe_with_html=True)

# --- SYSTEM EXPERIENCE SEGREGATION (Clean User Tabs) ---
app_view = st.sidebar.radio("🌐 Select Portal View", ["👤 Public Citizen Portal", "🏢 Municipal Admin Operations Room"])

# ==========================================
# 👤 USER VIEW 1: PUBLIC CITIZEN INTERFACE
# ==========================================
if app_view == "👤 Public Citizen Portal":
    st.markdown('<div class="section-header">📥 Public Budget Feedback & Grievance Submission Box</div>', unsafe_with_html=True)
    st.write("Wards and Municipal Offices are actively requesting policy inputs (*Bajet Niti Karyakram Sambandhi Sujhav Sankalan*). Submit your infrastructure problems or policy recommendations in natural text below.")
    
    col_entry, col_status = st.columns([1, 1.2])
    
    with col_entry:
        st.markdown('<div class="card">', unsafe_with_html=True)
        st.subheader("Submit Request / Sujhav")
        with st.form("citizen_input_form", clear_on_submit=True):
            citizen_ward = st.selectbox("Your Target Ward Location", ["Ward 1", "Ward 2", "Ward 3", "Ward 4", "Ward 5"])
            citizen_sector = st.selectbox("Infrastructure / Development Sector", ["Road Infrastructure", "Water & Sanitation", "Agriculture & Irrigation", "Health Services", "Education & Sports"])
            citizen_lang = st.selectbox("Submission Language", ["Nepali", "Maithili", "Bhojpuri", "English"])
            citizen_text = st.text_area("Write your grievance, requirement, or budget suggestion in detail:", height=120)
            
            submit_btn = st.form_submit_button("Lock Submission to Municipal Core")
            if submit_btn and citizen_text:
                new_id = f"CMP-{len(st.session_state.complaints) + 101}"
                st.session_state.complaints.append({
                    "ID": new_id, "Ward": citizen_ward, "Sector": citizen_sector, "Language": citizen_lang, "Text": citizen_text, "Priority": "🔴 High Priority", "Status": "Pending Review", "Official Response": "", "Budget Linked": "No", "Days Unresolved": 0
                })
                st.success(f"🤖 AI Ingestion Agent parsed and synchronized your submission successfully. Track ID: **{new_id}**")
        st.markdown('</div>', unsafe_with_html=True)

    with col_status:
        st.subheader("📡 Live Transparency & Tracking Matrix")
        st.write("All submitted public feedback is automatically updated below as the official budget is compiled.")
        
        for c in st.session_state.complaints:
            with st.expander(f"📋 {c['ID']} — {c['Ward']} [{c['Sector']}]"):
                st.write(f"**Your Text Entry:** {c['Text']}")
                st.write(f"**Processing Status:** `{c['Status']}`")
                
                if st.session_state.budget_published:
                    if c["Budget Linked"] == "Yes":
                        st.success(f"✅ **Budget Allocation Status:** SUCCESS. Money has been reserved for this project line. {c['Official Response']}")
                    else:
                        st.error(f"❌ **Budget Allocation Status:** REJECTED / DEFERRED. {c['Official Response']}")
                        
                        # Hello Sarkar Escalation Safeguard (Only active if unanswered for > 7 Days)
                        if c["Days Unresolved"] >= 7:
                            st.markdown(f"⚠️ *This critical problem was submitted over **{c['Days Unresolved']} days ago** without resolution or sufficient funding allocations.*")
                            if st.button(f"🚨 Escalate {c['ID']} to Hello Sarkar Portal", key=f"user_esc_{c['ID']}"):
                                st.toast(f"Pushed {c['ID']} tracking package directly to the Central Prime Minister's Dashboard via Hello Sarkar Webhook connection simulation!", icon="📡")
                else:
                    st.info("⌛ The municipal assembly is currently designing the budget draft using this feedback dataset. A notification update will deploy immediately upon final publication.")

# ==========================================
# 🏢 USER VIEW 2: MUNICIPAL OPERATIONS ROOM
# ==========================================
else:
    st.markdown('<div class="section-header">🏢 Municipal Planning Control Center</div>', unsafe_with_html=True)
    st.write("Secure internal console for the Mayor, Ward Chairs, and Technical Municipal Engineers to process funding ceilings and generate layouts.")
    
    # DYNAMIC FISCAL STATS CARD
    total_budget_pool = st.session_state.central_grant + st.session_state.provincial_grant + st.session_state.internal_revenue
    total_allocated = sum(item["Allocated Amount (NPR)"] for item in st.session_state.allocations) if st.session_state.allocations else 0.0
    remaining_reserve = total_budget_pool - total_allocated

    stat_col1, stat_col2, stat_col3 = st.columns(3)
    stat_col1.metric("Revenue Ceiling (Total Pool)", f"NPR {total_budget_pool:,.2f}", help="Central Grants + Provincial Grants + Internal Revenue inputs")
    stat_col2.metric("Allocated Project Expenditure", f"NPR {total_allocated:,.2f}", delta=f"{(total_allocated/total_budget_pool*100 if total_budget_pool > 0 else 0):.1f}% Budget Utilization")
    stat_col3.metric("Remaining Unallocated Reserve", f"NPR {remaining_reserve:,.2f}", delta_color="inverse" if remaining_reserve < 0 else "normal")

    # OPERATIONAL SETTINGS MATRIX
    with st.expander("⚙️ Step 1: Manage Financial Revenues & Policy Prompts", expanded=False):
        f_col1, f_col2, f_col3 = st.columns(3)
        st.session_state.central_grant = f_col1.number_input("Federal Equalization & Conditional Grants (NPR)", value=st.session_state.central_grant, step=100000.0)
        st.session_state.provincial_grant = f_col2.number_input("Provincial Grants (NPR)", value=st.session_state.provincial_grant, step=100000.0)
