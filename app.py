"""
Bajet Sunuwai (बजेट सुनुवाई)
================================
An Agentic AI civic-budget platform connecting citizen suggestions
(in Nepali / Maithili / Bhojpuri) directly to the municipal capital
budget allocation process.

Single-file Streamlit prototype built for a hackathon submission.
Run with:  streamlit run bajet_sunuwai_app.py
"""

import io
import random
import string
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="Bajet Sunuwai | बजेट सुनुवाई",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------
# CONSTANTS
# --------------------------------------------------------------------------
WARDS = ["Ward 1", "Ward 2", "Ward 3", "Ward 4", "Ward 5"]
SECTORS = ["Roads", "Water", "Irrigation", "Health", "Education"]
LANGUAGES = ["Nepali", "Maithili", "Bhojpuri"]

URGENCY_KEYWORDS = [
    "bhayavaha", "samasya", "khatara", "flood", "baadhi", "toot", "bigreko",
    "nasta", "urgent", "aapatkalin", "kharab", "risk", "danger", "collapsed",
    "dukh", "kasht", "problem", "damage",
]

CLIMATE_JUSTIFICATIONS = [
    "Prioritized due to high rainfall risk indices typical of Madhesh terrain",
    "Flagged under monsoon-flooding vulnerability mapping for the Tarai belt",
    "Aligned with river-embankment erosion risk common to Dhanusa wards",
    "Matches seasonal waterlogging patterns recorded in prior monsoon cycles",
    "Supports irrigation resilience against erratic Madhesh rainfall distribution",
]

# --------------------------------------------------------------------------
# CUSTOM CSS  (dusty, muted palette — no pure/bright white or saturated tones)
# --------------------------------------------------------------------------
def inject_css():
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #eae7e1;
        }
        section[data-testid="stSidebar"] {
            background-color: #dcd9d2;
            border-right: 1px solid #c7c3ba;
        }
        h1, h2, h3, h4 {
            color: #3a372f;
            font-family: 'Segoe UI', sans-serif;
        }
        .main-header {
            background: linear-gradient(90deg, #4b463c 0%, #6e6656 100%);
            padding: 28px 32px;
            border-radius: 14px;
            color: #f0ede4;
            margin-bottom: 22px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.12);
        }
        .main-header h1 {
            color: #f0ede4;
            margin: 0;
            font-size: 30px;
        }
        .main-header p {
            color: #dcd7c9;
            margin: 6px 0 0 0;
            font-size: 15px;
        }
        .metric-card {
            background-color: #f2efe8;
            border: 1px solid #cfc9ba;
            border-radius: 12px;
            padding: 18px 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        }
        .complaint-card {
            background-color: #f2efe8;
            border: 1px solid #cfc9ba;
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }
        .status-pill {
            display: inline-block;
            padding: 3px 12px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
            color: #f2efe8;
        }
        .pill-pending { background-color: #8a7f5c; }
        .pill-funded { background-color: #4f7a5a; }
        .pill-rejected { background-color: #8c4a3c; }
        .pill-high { background-color: #8c4a3c; }
        .pill-standard { background-color: #6e6656; }
        div.stButton > button[kind="primary"] {
            background-color: #8c2f22 !important;
            color: #f2efe8 !important;
            border: none !important;
            font-weight: 600;
        }
        div.stButton > button[kind="primary"]:hover {
            background-color: #6f241a !important;
        }
        .footer-note {
            color: #6e6656;
            font-size: 12px;
            margin-top: 28px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# --------------------------------------------------------------------------
def seed_complaint(cid, ward, sector, language, text, days_unresolved):
    return {
        "id": cid,
        "ward": ward,
        "sector": sector,
        "language": language,
        "text": text,
        "priority": classify_priority(text),
        "status": "Pending Review",
        "days_unresolved": days_unresolved,
        "submitted_on": (datetime.now() - timedelta(days=days_unresolved)).strftime("%Y-%m-%d"),
        "funded": None,          # None / True / False
        "ai_reason": None,
        "admin_response": "",
        "override_include": "Yes",
        "escalated": False,
    }


def classify_priority(text):
    lowered = text.lower()
    if any(word in lowered for word in URGENCY_KEYWORDS) or len(text) > 120:
        return "High Priority"
    return "Standard Priority"


def init_session_state():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True

    # --- Revenue figures (NPR) ---
    st.session_state.federal_grant = 15_000_000
    st.session_state.provincial_grant = 8_000_000
    st.session_state.internal_revenue = 4_500_000
    st.session_state.policy_directive = (
        "Prioritize monsoon flood-mitigation infrastructure and irrigation "
        "resilience across low-lying wards; support agricultural access roads."
    )

    # --- Complaint catalog (seeded demo data) ---
    st.session_state.complaints = [
        seed_complaint(
            "CMP-101", "Ward 3", "Water", "Maithili",
            "Hamar tolaa mein pani ke pipe bahut din se toot gel ba, pani "
            "nai aabait ba aur samasya bahut bhayavaha ho gel ba.",
            10,
        ),
        seed_complaint(
            "CMP-102", "Ward 1", "Roads", "Nepali",
            "Bato ekdam kharab avastha ma cha, motorcycle chalauna gaahro "
            "vayeko cha ra baccha haru school jaanay bela dherai samasya huncha.",
            3,
        ),
        seed_complaint(
            "CMP-103", "Ward 5", "Irrigation", "Bhojpuri",
            "Khet me sinchai ke naali dherai purana ba, baarish me paani "
            "jama ho jaala aur fasal barbaad ho jaala, jaldi thik karwaawa.",
            12,
        ),
    ]
    st.session_state.next_complaint_num = 104

    # --- Memos / Dhyanakarshan letters ---
    st.session_state.memos = [
        {
            "source": "Nagarain Youth Club",
            "doc_type": "Dhyanakarshan Letter",
            "demand": "Request for streetlight installation along the Ward 2 "
                      "market corridor before winter session.",
        },
        {
            "source": "Ward 4 Farmers' Coalition",
            "doc_type": "Policy Memo",
            "demand": "Formal request for canal desiltation ahead of the "
                      "monsoon planting cycle.",
        },
    ]

    # --- Budget allocation projects (populated once engine runs) ---
    st.session_state.projects = []

    # --- Alert / activity logs ---
    st.session_state.logs = []

    # --- Publication state ---
    st.session_state.budget_published = False


def next_complaint_id():
    cid = f"CMP-{st.session_state.next_complaint_num}"
    st.session_state.next_complaint_num += 1
    return cid


def total_revenue_ceiling():
    return (
        st.session_state.federal_grant
        + st.session_state.provincial_grant
        + st.session_state.internal_revenue
    )


def allocated_expenditure():
    return sum(p["amount"] for p in st.session_state.projects)


def unallocated_reserve():
    return total_revenue_ceiling() - allocated_expenditure()


def fmt_npr(amount):
    return f"NPR {amount:,.0f}"


# --------------------------------------------------------------------------
# PUBLIC CITIZEN PORTAL
# --------------------------------------------------------------------------
def render_public_portal():
    st.markdown(
        """
        <div class="main-header">
            <h1>👤 Bajet Niti Karyakram Sambandhi Sujhav Sankalan</h1>
            <p>Public Budget Suggestions Portal — Nagarain Municipality, Dhanusa</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("✍️ Submit a New Suggestion / Complaint", expanded=True):
        with st.form("citizen_suggestion_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                ward = st.selectbox("Target Ward", WARDS)
            with col2:
                sector = st.selectbox("Sector", SECTORS)
            with col3:
                language = st.selectbox("Language", LANGUAGES)

            text = st.text_area(
                "Describe your suggestion or complaint (in your own dialect)",
                placeholder="Type in Nepali, Maithili, or Bhojpuri...",
                height=120,
            )
            submitted = st.form_submit_button("📤 Submit to AI Ingestion Agent", type="primary")

        if submitted:
            if not text.strip():
                st.warning("Please enter some text before submitting.")
            else:
                new_id = next_complaint_id()
                complaint = seed_complaint(new_id, ward, sector, language, text.strip(), 0)
                st.session_state.complaints.append(complaint)
                st.success(
                    f"✅ AI Ingestion Agent processed your entry.\n\n"
                    f"**Tracking ID:** `{new_id}`  \n"
                    f"**Detected Language:** {language}  \n"
                    f"**Priority Flag:** {complaint['priority']}"
                )

    st.markdown("### 📊 Live Transparency Matrix")
    st.caption(
        "Track every citizen suggestion from ingestion through municipal "
        "budget review and final outcome."
    )

    if not st.session_state.complaints:
        st.info("No complaints have been filed yet.")
        return

    for c in st.session_state.complaints:
        pill_class = "pill-high" if c["priority"] == "High Priority" else "pill-standard"
        header = (
            f"{c['id']} — {c['sector']} — {c['ward']} "
            f"({c['language']}) | {c['priority']}"
        )
        with st.expander(header):
            st.markdown(
                f"""
                <div class="complaint-card">
                    <b>Submitted:</b> {c['submitted_on']} &nbsp;&nbsp;
                    <b>Days Unresolved:</b> {c['days_unresolved']} &nbsp;&nbsp;
                    <span class="status-pill {pill_class}">{c['priority']}</span>
                    <br><br>
                    <i>"{c['text']}"</i>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not st.session_state.budget_published:
                st.info(
                    "🕓 The municipal assembly is reviewing your data. "
                    "You will be notified once the budget is finalized."
                )
            else:
                if c["funded"] is True:
                    st.markdown(
                        f"""
                        <span class="status-pill pill-funded">SUCCESS — FUNDED</span>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.write(f"**AI Explanation:** {c['ai_reason']}")
                    if c["admin_response"]:
                        st.write(f"**Municipal Note:** {c['admin_response']}")
                else:
                    st.markdown(
                        f"""
                        <span class="status-pill pill-rejected">REJECTED / DEFERRED</span>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.write(f"**AI Explanation:** {c['ai_reason'] or 'Awaiting municipal review.'}")
                    if c["admin_response"]:
                        st.write(f"**Municipal Note:** {c['admin_response']}")

                # --- Hello Sarkar Escalation Safeguard ---
                unresolved_and_unfavorable = c["funded"] is False or c["status"] == "Pending Review"
                if c["days_unresolved"] >= 7 and unresolved_and_unfavorable:
                    st.markdown("---")
                    if c["escalated"]:
                        st.error(
                            "🚨 This complaint has already been escalated to the "
                            "**Central Hello Sarkar Prime Minister's Dashboard**."
                        )
                    else:
                        st.warning(
                            "⚠️ This complaint has been unresolved for "
                            f"{c['days_unresolved']} days and was not funded."
                        )
                        if st.button(
                            f"🚨 Escalate {c['id']} to Hello Sarkar PM Dashboard",
                            key=f"escalate_{c['id']}",
                            type="primary",
                        ):
                            c["escalated"] = True
                            st.session_state.logs.append(
                                f"[ESCALATION] {c['id']} pushed to Central Hello Sarkar "
                                f"PM Dashboard — data packet, local budget caps, and "
                                f"multi-year failure logs transmitted."
                            )
                            st.success(
                                f"📡 Data packet for {c['id']} — including local budget "
                                f"caps and multi-year failure logs — has been transmitted "
                                f"to the Central Hello Sarkar Prime Minister's Dashboard."
                            )
                            st.rerun()


# --------------------------------------------------------------------------
# ADMIN: ALLOCATION ENGINE LOGIC
# --------------------------------------------------------------------------
def run_allocation_engine():
    projects = []
    logs = []
    remaining_budget = total_revenue_ceiling()
    random.seed(42)  # reproducible demo run

    # Process high priority first, then standard, then by days unresolved
    ordered = sorted(
        st.session_state.complaints,
        key=lambda c: (c["priority"] != "High Priority", -c["days_unresolved"]),
    )

    for c in ordered:
        if c["override_include"] == "No":
            c["status"] = "Budget Concluded"
            c["funded"] = False
            reason = "Excluded from this budget cycle per municipal override decision."
            if c["admin_response"]:
                reason += f" Municipal note: {c['admin_response']}"
            c["ai_reason"] = reason
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — REJECTED (manual override)")
            continue

        proposed_amount = random.randint(500_000, 3_200_000)

        if proposed_amount <= remaining_budget:
            remaining_budget -= proposed_amount
            climate_note = random.choice(CLIMATE_JUSTIFICATIONS)
            project_name = f"{c['ward']} {c['sector']} Improvement Initiative"
            justification = (
                f"{climate_note} and matches public complaint {c['id']}. "
                f"Aligned with Mayor's directive: "
                f"\"{st.session_state.policy_directive[:80]}...\""
            )
            projects.append(
                {
                    "project_name": project_name,
                    "ward": c["ward"],
                    "sector": c["sector"],
                    "amount": proposed_amount,
                    "justification": justification,
                    "linked_complaint": c["id"],
                }
            )
            c["status"] = "Budget Concluded"
            c["funded"] = True
            c["ai_reason"] = justification
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — FUNDED ({fmt_npr(proposed_amount)})")
        else:
            c["status"] = "Budget Concluded"
            c["funded"] = False
            c["ai_reason"] = (
                "Deferred due to conditional federal grant restrictions and "
                "insufficient remaining contingency reserve for this cycle."
            )
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (insufficient reserve)")

    st.session_state.projects = projects
    st.session_state.logs.extend(logs)


# --------------------------------------------------------------------------
# ADMIN PORTAL
# --------------------------------------------------------------------------
def render_admin_portal():
    st.markdown(
        """
        <div class="main-header">
            <h1>🏢 Municipal Admin Operations Room</h1>
            <p>Nagarain Municipality — Agentic AI Capital Budget Allocation Console</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Live metric dashboard ---
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(
            f"""<div class="metric-card"><b>💰 Total Revenue Ceiling</b><br>
            <span style="font-size:26px;">{fmt_npr(total_revenue_ceiling())}</span></div>""",
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f"""<div class="metric-card"><b>🏗️ Allocated Project Expenditure</b><br>
            <span style="font-size:26px;">{fmt_npr(allocated_expenditure())}</span></div>""",
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f"""<div class="metric-card"><b>🧾 Unallocated / Contingency Reserve</b><br>
            <span style="font-size:26px;">{fmt_npr(unallocated_reserve())}</span></div>""",
            unsafe_allow_html=True,
        )

    st.write("")

    # --- STEP 1 ---
    with st.expander("⚙️ Step 1: Manage Financial Revenues & Policy Guidelines", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state.federal_grant = st.number_input(
                "Federal Equalization Grants (NPR)",
                min_value=0,
                value=st.session_state.federal_grant,
                step=100_000,
            )
        with c2:
            st.session_state.provincial_grant = st.number_input(
                "Provincial Grants (NPR)",
                min_value=0,
                value=st.session_state.provincial_grant,
                step=100_000,
            )
        with c3:
            st.session_state.internal_revenue = st.number_input(
                "Internal Source Revenue (NPR)",
                min_value=0,
                value=st.session_state.internal_revenue,
                step=100_000,
            )

        st.info(f"**Total Revenue Ceiling:** {fmt_npr(total_revenue_ceiling())}")

        st.session_state.policy_directive = st.text_area(
            "Mayor's Policy Directive",
            value=st.session_state.policy_directive,
            height=90,
        )

    # --- STEP 2 ---
    with st.expander("📄 Step 2: Ingest Memos & Dhyanakarshan Letters", expanded=False):
        uploaded_memo = st.file_uploader(
            "Upload PDF or text memo from youth clubs / political factions",
            type=["pdf", "txt"],
            key="memo_uploader",
        )
        col_src, col_type = st.columns(2)
        with col_src:
            memo_source = st.text_input("Source Entity", placeholder="e.g. Ward 2 Youth Club")
        with col_type:
            memo_type = st.selectbox("Document Type", ["Dhyanakarshan Letter", "Policy Memo", "Petition"])

        if st.button("📥 Ingest Uploaded Memo", key="ingest_memo_btn"):
            if uploaded_memo is not None:
                extracted_demand = (
                    f"Auto-extracted structural demand from '{uploaded_memo.name}': "
                    f"requesting municipal review and capital allocation consideration."
                )
                st.session_state.memos.append(
                    {
                        "source": memo_source or "Unspecified Entity",
                        "doc_type": memo_type,
                        "demand": extracted_demand,
                    }
                )
                st.success(f"Memo '{uploaded_memo.name}' ingested and parsed.")
            else:
                st.warning("Please attach a file before ingesting.")

        st.markdown("#### Active Memorandums")
        if not st.session_state.memos:
            st.caption("No memos ingested yet.")
        else:
            for memo in st.session_state.memos:
                st.markdown(
                    f"""
                    <div class="complaint-card">
                        <b>{memo['source']}</b> &nbsp;
                        <span class="status-pill pill-standard">{memo['doc_type']}</span>
                        <br>{memo['demand']}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # --- STEP 3 ---
    with st.expander("📥 Step 3: Linked Public Suggestions & Manual Override Console", expanded=False):
        if not st.session_state.complaints:
            st.caption("No public suggestions filed yet.")
        else:
            for c in st.session_state.complaints:
                st.markdown(
                    f"""
                    <div class="complaint-card">
                        <b>{c['id']}</b> — {c['sector']} — {c['ward']} ({c['language']}) &nbsp;
                        <span class="status-pill {'pill-high' if c['priority']=='High Priority' else 'pill-standard'}">{c['priority']}</span>
                        &nbsp; <span class="status-pill pill-pending">{c['status']}</span>
                        <br><i>"{c['text']}"</i>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                oc1, oc2 = st.columns([3, 1])
                with oc1:
                    c["admin_response"] = st.text_input(
                        f"Custom response reason for {c['id']}",
                        value=c["admin_response"],
                        key=f"response_{c['id']}",
                    )
                with oc2:
                    c["override_include"] = st.selectbox(
                        f"Force-fund {c['id']}?",
                        ["Yes", "No"],
                        index=0 if c["override_include"] == "Yes" else 1,
                        key=f"override_{c['id']}",
                    )
                st.markdown("---")

    # --- STEP 4 ---
    with st.expander("🤖 Step 4: AI Agentic Capital Budget Allocation Assembly", expanded=True):
        st.write(
            "This engine cross-references financial ceilings, the Mayor's policy "
            "directive, ingested memos, and every public suggestion to produce a "
            "justified, project-wise capital budget allocation."
        )

        if st.button("🚀 Compile and Run AI Budget Allocation Engine", type="primary"):
            run_allocation_engine()
            st.success("AI Budget Allocation Engine completed successfully.")

        if st.session_state.projects:
            df = pd.DataFrame(
                [
                    {
                        "Project Name": p["project_name"],
                        "Target Ward": p["ward"],
                        "Target Sector": p["sector"],
                        "Allocated Amount (NPR)": p["amount"],
                        "AI Logic Justification": p["justification"],
                    }
                    for p in st.session_state.projects
                ]
            )
            st.markdown("#### 📋 Project-Wise Allocation Breakdown")
            st.dataframe(df, use_container_width=True)

            if st.session_state.logs:
                with st.container():
                    st.markdown("#### 🔔 System Alert Logs")
                    for log_line in st.session_state.logs[-15:]:
                        st.text(log_line)

            # --- Download engine: try Excel, fall back to CSV ---
            st.markdown("#### 📤 Export Allocation Sheet")
            try:
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Budget Allocation")
                excel_buffer.seek(0)
                st.download_button(
                    label="📥 Download Allocation Sheet (.xlsx)",
                    data=excel_buffer,
                    file_name="bajet_sunuwai_allocation.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception:
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                st.warning(
                    "⚠️ Excel export engine unavailable in this environment — "
                    "falling back to CSV export so the download always works."
                )
                st.download_button(
                    label="📥 Download Allocation Sheet (.csv)",
                    data=csv_buffer.getvalue(),
                    file_name="bajet_sunuwai_allocation.csv",
                    mime="text/csv",
                )

            # --- Manual Planning Engineer Modification Layer ---
            st.markdown("#### 🛠️ Manual Planning Engineer Modification Layer")
            st.caption(
                "If a planning engineer edits the downloaded sheet offline, "
                "upload the revised file to sync it back into the master dashboard."
            )
            revised_file = st.file_uploader(
                "Upload revised allocation sheet (.xlsx or .csv)",
                type=["xlsx", "csv"],
                key="revised_upload",
            )
            if revised_file is not None:
                if st.button("🔄 Apply Engineer Revisions to Master Dashboard"):
                    try:
                        if revised_file.name.lower().endswith(".xlsx"):
                            revised_df = pd.read_excel(revised_file, engine="openpyxl")
                        else:
                            revised_df = pd.read_csv(revised_file)

                        updated_projects = []
                        for _, row in revised_df.iterrows():
                            updated_projects.append(
                                {
                                    "project_name": row.get("Project Name", "Unnamed Project"),
                                    "ward": row.get("Target Ward", ""),
                                    "sector": row.get("Target Sector", ""),
                                    "amount": float(row.get("Allocated Amount (NPR)", 0) or 0),
                                    "justification": row.get("AI Logic Justification", ""),
                                    "linked_complaint": "",
                                }
                            )
                        st.session_state.projects = updated_projects
                        st.session_state.logs.append(
                            "[ALERT] Master dashboard synced with planning engineer's "
                            "manually revised allocation sheet (human-in-the-loop validation)."
                        )
                        st.success(
                            "✅ Master stats dashboard updated from the revised sheet."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not parse the uploaded file: {exc}")

            # --- Finalize and publish ---
            st.markdown("#### 📢 Publication")
            if st.session_state.budget_published:
                st.success("✅ This budget has already been finalized and published to citizens.")
            else:
                if st.button("📢 Finalize and Publish Budget", type="primary"):
                    st.session_state.budget_published = True
                    st.session_state.logs.append(
                        "[ALERT] Budget finalized and published — public notifications unlocked."
                    )
                    st.balloons()
                    st.success(
                        "🎉 Budget finalized and published! Citizens can now view outcomes "
                        "in the Public Citizen Portal."
                    )
        else:
            st.caption("Run the allocation engine to generate the project breakdown table.")


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    inject_css()
    init_session_state()

    st.sidebar.markdown("## 🏛️ Bajet Sunuwai")
    st.sidebar.markdown("**बजेट सुनुवाई**")
    st.sidebar.caption("Agentic AI civic-budget platform — Nagarain Municipality")
    st.sidebar.markdown("---")

    portal = st.sidebar.radio(
        "Select Portal",
        ["👤 Public Citizen Portal", "🏢 Municipal Admin Operations Room"],
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"**Budget Status:** "
        f"{'🟢 Published' if st.session_state.budget_published else '🟡 Under Review'}"
    )
    st.sidebar.markdown(f"**Total Complaints Filed:** {len(st.session_state.complaints)}")
    st.sidebar.markdown(
        '<p class="footer-note">Built for the Yantra X Softbots Agentic AI Hackathon.</p>',
        unsafe_allow_html=True,
    )

    if portal == "👤 Public Citizen Portal":
        render_public_portal()
    else:
        render_admin_portal()


if __name__ == "__main__":
    main()
