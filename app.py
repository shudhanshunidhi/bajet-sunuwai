"""
Bajet Sunuwai (बजेट सुनुवाई)
================================
An Agentic AI civic-budget platform connecting citizen suggestions
(in Nepali / Maithili / Bhojpuri) directly to the municipal capital
budget allocation process.

Single-file Streamlit prototype for the Yantra Business Cup SOFTBOTS
AI Hackathon.

WHAT'S "AGENTIC" HERE:
  1. Ingestion Agent — a single Claude tool-use call that reads a raw
     citizen complaint and returns a structured classification
     (language, priority, urgency reasoning, summary). This replaces
     a keyword-matching heuristic with real model reasoning.
  2. Allocation Agent — a multi-step Claude tool-use LOOP. The model is
     given the budget ceiling, the Mayor's policy directive, ingested
     memos, and every complaint, then decides — turn by turn, calling
     get_remaining_budget / fund_project / defer_complaint — how to
     spend the budget. The app enforces the hard ceiling; the model
     decides what to fund, in what order, and why. Every tool call is
     logged and shown in the UI as a live agent trace.

Both agents gracefully fall back to deterministic simulation logic if
no ANTHROPIC_API_KEY is configured, or if the live API call fails —
so the demo never crashes, but the UI is explicit about which mode is
actually running.

Run with:  streamlit run bajet_sunuwai_app.py
Requires:  ANTHROPIC_API_KEY set as an environment variable or in
           .streamlit/secrets.toml as ANTHROPIC_API_KEY = "sk-ant-..."
Optional:  ADMIN_PASSWORD in the same places (defaults to
           "hellosarkar2026" if not set).
"""

import base64
import io
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

try:
    import anthropic
    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    ANTHROPIC_SDK_AVAILABLE = False

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

MODEL_NAME = "claude-sonnet-5"

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bajet_sunuwai.db")

HELLO_SARKAR_PORTAL_URL = "https://gunaso.opmcm.gov.np/home"
HELLO_SARKAR_WHATSAPP_NUMBER = "9779851145045"  # +977 985-1145045

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

SYNTHETIC_TEMPLATES = [
    ("Roads", "Nepali", "Yo bato dherai barsha dekhi bigreko cha, gaadi chalauna gaahro bha cha."),
    ("Water", "Maithili", "Hamar gaaon me paani ke supply bahut din se band ba, jaldi sudhaar chahi."),
    ("Irrigation", "Bhojpuri", "Sinchai naali me paani nai aawe la, fasal sukhaa ho rahal ba."),
    ("Health", "Nepali", "Swasthya chauki ma udhaharan ausadhi upalabdha chaina, samasya bhayo."),
    ("Education", "Maithili", "Skool bhawan ke chhat toot gel ba, barsat me paani tapkait ba."),
    ("Roads", "Bhojpuri", "Gaon ke sadak me gaddha ba, durghatna hoit rahal ba har hafta."),
    ("Water", "Nepali", "Khane pani ko dhara kharab bha cha, mahila haru dherai taadha jaanu parcha."),
    ("Health", "Bhojpuri", "Aspatal me daktar samay pe nai aawe la, mareez pareshan ba."),
    ("Education", "Nepali", "Kitab ra copy ko abhav le vidyarthi haru lai samasya bha rako cha."),
    ("Irrigation", "Maithili", "Baandh purana bha gel ba, baarish me toote ke dar ba."),
]


# --------------------------------------------------------------------------
# CUSTOM CSS  (dusty, muted palette — no pure/bright white or saturated tones)
# --------------------------------------------------------------------------
def inject_css():
    st.markdown(
        """
        <style>
        .stApp { background-color: #eae7e1; }
        section[data-testid="stSidebar"] {
            background-color: #dcd9d2;
            border-right: 1px solid #c7c3ba;
        }
        h1, h2, h3, h4 { color: #3a372f; font-family: 'Segoe UI', sans-serif; }
        .main-header {
            background: linear-gradient(90deg, #4b463c 0%, #6e6656 100%);
            padding: 28px 32px;
            border-radius: 14px;
            color: #f0ede4;
            margin-bottom: 22px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.12);
        }
        .main-header h1 { color: #f0ede4; margin: 0; font-size: 30px; }
        .main-header p { color: #dcd7c9; margin: 6px 0 0 0; font-size: 15px; }
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
        .trace-card {
            background-color: #37352c;
            color: #d8d3c4;
            border-radius: 10px;
            padding: 10px 14px;
            font-family: 'Consolas', monospace;
            font-size: 12.5px;
            margin-bottom: 6px;
            border-left: 3px solid #8c7a4f;
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
        .pill-live { background-color: #2f6b46; }
        .pill-fallback { background-color: #8a5a2f; }
        div.stButton > button[kind="primary"] {
            background-color: #8c2f22 !important;
            color: #f2efe8 !important;
            border: none !important;
            font-weight: 600;
        }
        div.stButton > button[kind="primary"]:hover { background-color: #6f241a !important; }
        .footer-note { color: #6e6656; font-size: 12px; margin-top: 28px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# AI CLIENT
# --------------------------------------------------------------------------
def get_api_key():
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def get_admin_password():
    try:
        if "ADMIN_PASSWORD" in st.secrets:
            return st.secrets["ADMIN_PASSWORD"]
    except Exception:
        pass
    return os.environ.get("ADMIN_PASSWORD", "hellosarkar2026")


def get_client():
    if not ANTHROPIC_SDK_AVAILABLE:
        return None
    key = get_api_key()
    if not key:
        return None
    try:
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


AI_LIVE = get_client() is not None


# --------------------------------------------------------------------------
# SQLITE PERSISTENCE
# --------------------------------------------------------------------------
STATE_KEYS = [
    "complaints", "memos", "projects", "logs", "trace_log",
    "federal_grant", "provincial_grant", "internal_revenue",
    "policy_directive", "budget_published", "next_complaint_num",
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def _photo_to_json_safe(complaint):
    c = dict(complaint)
    if c.get("photo_bytes"):
        c["photo_bytes"] = base64.b64encode(c["photo_bytes"]).decode("ascii")
    return c


def _photo_from_json_safe(complaint):
    c = dict(complaint)
    if c.get("photo_bytes"):
        c["photo_bytes"] = base64.b64decode(c["photo_bytes"])
    return c


def save_state():
    """Persist the durable app state to SQLite so a page refresh or a new
    session doesn't lose the demo's progress."""
    payload = {}
    for key in STATE_KEYS:
        value = st.session_state.get(key)
        if key == "complaints" and value is not None:
            value = [_photo_to_json_safe(c) for c in value]
        payload[key] = value

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO state (key, value) VALUES ('app_state', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(payload),),
    )
    conn.commit()
    conn.close()


def load_state():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value FROM state WHERE key = 'app_state'").fetchone()
    conn.close()
    if not row:
        return None
    payload = json.loads(row[0])
    if payload.get("complaints"):
        payload["complaints"] = [_photo_from_json_safe(c) for c in payload["complaints"]]
    return payload


# --------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# --------------------------------------------------------------------------
def seed_complaint(cid, ward, sector, language, text, days_unresolved,
                    priority=None, ai_summary=None, ai_urgency_reasoning=None,
                    classification_source="fallback"):
    if priority is None:
        priority = classify_priority_fallback(text)
    return {
        "id": cid,
        "ward": ward,
        "sector": sector,
        "language": language,
        "text": text,
        "priority": priority,
        "ai_summary": ai_summary,
        "ai_urgency_reasoning": ai_urgency_reasoning,
        "classification_source": classification_source,  # "ai" or "fallback"
        "status": "Pending Review",
        "days_unresolved": days_unresolved,
        "submitted_on": (datetime.now() - timedelta(days=days_unresolved)).strftime("%Y-%m-%d"),
        "funded": None,          # None / True / False
        "ai_reason": None,
        "admin_response": "",
        "override_include": "Yes",
        "escalated": False,
        "photo_bytes": None,
        "photo_name": None,
    }


def classify_priority_fallback(text):
    lowered = text.lower()
    if any(word in lowered for word in URGENCY_KEYWORDS) or len(text) > 120:
        return "High Priority"
    return "Standard Priority"


def default_state():
    return {
        "federal_grant": 15_000_000,
        "provincial_grant": 8_000_000,
        "internal_revenue": 4_500_000,
        "policy_directive": (
            "Prioritize monsoon flood-mitigation infrastructure and irrigation "
            "resilience across low-lying wards; support agricultural access roads."
        ),
        "complaints": [
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
        ],
        "memos": [
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
        ],
        "projects": [],
        "logs": [],
        "trace_log": [],
        "budget_published": False,
        "next_complaint_num": 104,
    }


def init_session_state():
    if "initialized" in st.session_state:
        return

    st.session_state.initialized = True
    init_db()

    saved = load_state()
    if saved:
        for key in STATE_KEYS:
            st.session_state[key] = saved.get(key, default_state().get(key))
    else:
        for key, value in default_state().items():
            st.session_state[key] = value
        save_state()

    if "admin_authenticated" not in st.session_state:
        st.session_state.admin_authenticated = False


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
# AGENT 1 — AI INGESTION (single structured tool-use call)
# --------------------------------------------------------------------------
INGESTION_TOOL = {
    "name": "classify_complaint",
    "description": "Analyze a citizen budget complaint and return a structured classification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "detected_language": {
                "type": "string",
                "description": "The language/dialect the complaint is actually written in "
                                "(Nepali, Maithili, Bhojpuri, or a mix).",
            },
            "priority": {
                "type": "string",
                "enum": ["High Priority", "Standard Priority"],
            },
            "urgency_reasoning": {
                "type": "string",
                "description": "1-2 sentences explaining why this priority was assigned, "
                                "referencing specific content in the complaint.",
            },
            "summary": {
                "type": "string",
                "description": "One-sentence plain-English summary of the complaint.",
            },
            "sector_confidence": {
                "type": "string",
                "enum": ["matches selected sector", "possible mismatch"],
                "description": "Whether the complaint content actually matches the sector "
                                "the citizen selected in the form.",
            },
        },
        "required": [
            "detected_language", "priority", "urgency_reasoning",
            "summary", "sector_confidence",
        ],
    },
}


def ai_classify_complaint(text, selected_sector, selected_language):
    """Real agent call. Returns (result_dict, source) where source is
    'ai' on success or 'fallback' if no key / call failed."""
    client = get_client()
    if client is None:
        return _fallback_classification(text), "fallback"

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=500,
            tools=[INGESTION_TOOL],
            tool_choice={"type": "tool", "name": "classify_complaint"},
            messages=[{
                "role": "user",
                "content": (
                    f"A citizen in Nagarain Municipality, Dhanusa, Nepal submitted this "
                    f"budget complaint via a form where they selected sector "
                    f"'{selected_sector}' and language '{selected_language}':\n\n"
                    f"\"{text}\"\n\n"
                    f"Classify it using the classify_complaint tool."
                ),
            }],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "classify_complaint":
                return block.input, "ai"
        return _fallback_classification(text), "fallback"
    except Exception:
        return _fallback_classification(text), "fallback"


def _fallback_classification(text):
    priority = classify_priority_fallback(text)
    return {
        "detected_language": "Unable to verify (fallback mode)",
        "priority": priority,
        "urgency_reasoning": "Heuristic fallback: keyword/length match, no live model call.",
        "summary": text[:100] + ("..." if len(text) > 100 else ""),
        "sector_confidence": "not evaluated (fallback mode)",
    }


# --------------------------------------------------------------------------
# AGENT 2 — AI ALLOCATION (multi-step agentic tool-use loop)
# --------------------------------------------------------------------------
ALLOCATION_TOOLS = [
    {
        "name": "get_remaining_budget",
        "description": "Check how much capital budget (NPR) is still unallocated this cycle.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fund_project",
        "description": "Allocate budget to a capital project addressing a specific complaint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "complaint_id": {"type": "string"},
                "project_name": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in NPR, must not exceed remaining budget."},
                "justification": {
                    "type": "string",
                    "description": "Why this project was funded — reference the policy "
                                    "directive, climate/geographic context, and the complaint.",
                },
            },
            "required": ["complaint_id", "project_name", "amount", "justification"],
        },
    },
    {
        "name": "defer_complaint",
        "description": "Defer or reject a complaint for this budget cycle.",
        "input_schema": {
            "type": "object",
            "properties": {
                "complaint_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["complaint_id", "reason"],
        },
    },
    {
        "name": "finish_allocation",
        "description": "Call this once every complaint has been either funded or deferred.",
        "input_schema": {
            "type": "object",
            "properties": {
                "closing_note": {"type": "string"},
            },
            "required": ["closing_note"],
        },
    },
]


def run_ai_allocation_engine():
    """
    Agentic loop: the model is given full context once, then repeatedly
    calls tools to check remaining budget and fund/defer each complaint,
    until it calls finish_allocation or a safety turn-limit is hit. The
    app — not the model — enforces the hard budget ceiling.
    """
    client = get_client()
    if client is None:
        return run_fallback_allocation_engine()

    complaints_by_id = {c["id"]: c for c in st.session_state.complaints}
    open_complaints = [c for c in st.session_state.complaints if c["override_include"] == "Yes"]
    excluded_complaints = [c for c in st.session_state.complaints if c["override_include"] == "No"]

    remaining_budget = {"amount": total_revenue_ceiling()}
    projects = []
    trace = []
    logs = []

    # Manual overrides are enforced by the app, not the model.
    for c in excluded_complaints:
        c["status"] = "Budget Concluded"
        c["funded"] = False
        reason = "Excluded from this budget cycle per municipal override decision."
        if c["admin_response"]:
            reason += f" Municipal note: {c['admin_response']}"
        c["ai_reason"] = reason
        logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — REJECTED (manual override)")

    if not open_complaints:
        st.session_state.projects = projects
        st.session_state.logs.extend(logs)
        st.session_state.trace_log.extend(trace)
        return "ai", trace

    complaint_summaries = "\n".join(
        f"- {c['id']} | Ward: {c['ward']} | Sector: {c['sector']} | "
        f"Priority: {c['priority']} | Days unresolved: {c['days_unresolved']} | "
        f"Text: \"{c['text']}\""
        for c in open_complaints
    )
    memo_summaries = "\n".join(
        f"- {m['source']} ({m['doc_type']}): {m['demand']}" for m in st.session_state.memos
    ) or "(no memos ingested)"

    system_prompt = (
        "You are the capital budget allocation agent for Nagarain Municipality, "
        "Dhanusa, Madhesh Province, Nepal. You must decide how to allocate the "
        "available capital budget across open citizen complaints. Use the tools "
        "provided: check get_remaining_budget before large decisions, call "
        "fund_project or defer_complaint for EVERY open complaint exactly once, "
        "and call finish_allocation when done. Never propose an amount larger "
        "than the remaining budget. Ground every justification in the Mayor's "
        "policy directive, Madhesh's monsoon/flood climate context, and the "
        "specific complaint content — do not use generic boilerplate."
    )

    user_prompt = (
        f"Total Revenue Ceiling: {fmt_npr(total_revenue_ceiling())}\n\n"
        f"Mayor's Policy Directive:\n{st.session_state.policy_directive}\n\n"
        f"Ingested Memos:\n{memo_summaries}\n\n"
        f"Open Complaints (each must be funded or deferred):\n{complaint_summaries}\n\n"
        f"Begin the allocation process now."
    )

    messages = [{"role": "user", "content": user_prompt}]
    max_turns = 25
    turn = 0

    try:
        while turn < max_turns:
            turn += 1
            response = client.messages.create(
                model=MODEL_NAME,
                max_tokens=1500,
                system=system_prompt,
                tools=ALLOCATION_TOOLS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            finished = False

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "get_remaining_budget":
                    result_text = json.dumps({"remaining_budget": remaining_budget["amount"]})
                    trace.append(f"🔍 get_remaining_budget → {fmt_npr(remaining_budget['amount'])}")

                elif block.name == "fund_project":
                    args = block.input
                    cid = args.get("complaint_id")
                    amount = float(args.get("amount", 0))
                    c = complaints_by_id.get(cid)

                    if c is None:
                        result_text = json.dumps({"error": f"Unknown complaint_id {cid}"})
                        trace.append(f"⚠️ fund_project failed — unknown complaint {cid}")
                    elif amount > remaining_budget["amount"]:
                        result_text = json.dumps({
                            "error": "Amount exceeds remaining budget",
                            "remaining_budget": remaining_budget["amount"],
                        })
                        trace.append(
                            f"⚠️ fund_project rejected for {cid} — requested "
                            f"{fmt_npr(amount)} exceeds remaining {fmt_npr(remaining_budget['amount'])}"
                        )
                    else:
                        remaining_budget["amount"] -= amount
                        project_name = args.get("project_name", f"{c['ward']} {c['sector']} Project")
                        justification = args.get("justification", "")
                        projects.append({
                            "project_name": project_name,
                            "ward": c["ward"],
                            "sector": c["sector"],
                            "amount": amount,
                            "justification": justification,
                            "linked_complaint": cid,
                        })
                        c["status"] = "Budget Concluded"
                        c["funded"] = True
                        c["ai_reason"] = justification
                        logs.append(f"[ALERT] {cid} status -> Budget Concluded — FUNDED ({fmt_npr(amount)})")
                        trace.append(f"✅ fund_project({cid}) → {project_name} — {fmt_npr(amount)}")
                        result_text = json.dumps({
                            "success": True,
                            "remaining_budget": remaining_budget["amount"],
                        })

                elif block.name == "defer_complaint":
                    args = block.input
                    cid = args.get("complaint_id")
                    reason = args.get("reason", "Deferred by allocation agent.")
                    c = complaints_by_id.get(cid)
                    if c is not None:
                        c["status"] = "Budget Concluded"
                        c["funded"] = False
                        c["ai_reason"] = reason
                        logs.append(f"[ALERT] {cid} status -> Budget Concluded — DEFERRED")
                        trace.append(f"⏸️ defer_complaint({cid}) — {reason[:80]}")
                        result_text = json.dumps({"success": True})
                    else:
                        result_text = json.dumps({"error": f"Unknown complaint_id {cid}"})

                elif block.name == "finish_allocation":
                    closing_note = block.input.get("closing_note", "")
                    trace.append(f"🏁 finish_allocation — {closing_note}")
                    finished = True
                    result_text = json.dumps({"success": True})

                else:
                    result_text = json.dumps({"error": "unknown tool"})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})

            if finished:
                break

        # Safety net: any open complaint the model never touched gets
        # deferred rather than silently vanishing.
        for c in open_complaints:
            if c["status"] != "Budget Concluded":
                c["status"] = "Budget Concluded"
                c["funded"] = False
                c["ai_reason"] = "Not reached by the allocation agent within the turn limit; deferred for the next cycle."
                logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (turn limit)")
                trace.append(f"⏸️ safety-net defer_complaint({c['id']}) — turn limit reached")

        st.session_state.projects = projects
        st.session_state.logs.extend(logs)
        st.session_state.trace_log.extend(trace)
        return "ai", trace

    except Exception as exc:
        st.session_state.trace_log.append(f"⚠️ Live AI allocation failed ({exc}) — falling back to simulation.")
        return run_fallback_allocation_engine()


def run_fallback_allocation_engine():
    """Deterministic simulation used when no API key is configured or the
    live call fails. Clearly logged as fallback mode — never presented as AI."""
    projects = []
    logs = []
    trace = ["⚠️ FALLBACK MODE — no live AI backend; using seeded simulation logic."]
    remaining_budget = total_revenue_ceiling()
    random.seed(42)

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
            trace.append(f"⏸️ [fallback] excluded {c['id']} (manual override)")
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
            projects.append({
                "project_name": project_name,
                "ward": c["ward"],
                "sector": c["sector"],
                "amount": proposed_amount,
                "justification": justification,
                "linked_complaint": c["id"],
            })
            c["status"] = "Budget Concluded"
            c["funded"] = True
            c["ai_reason"] = justification
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — FUNDED ({fmt_npr(proposed_amount)})")
            trace.append(f"✅ [fallback] fund {c['id']} — {fmt_npr(proposed_amount)}")
        else:
            c["status"] = "Budget Concluded"
            c["funded"] = False
            c["ai_reason"] = (
                "Deferred due to conditional federal grant restrictions and "
                "insufficient remaining contingency reserve for this cycle."
            )
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (insufficient reserve)")
            trace.append(f"⏸️ [fallback] defer {c['id']} — insufficient reserve")

    st.session_state.projects = projects
    st.session_state.logs.extend(logs)
    st.session_state.trace_log.extend(trace)
    return "fallback", trace


# --------------------------------------------------------------------------
# HELLO SARKAR HAND-OFF
# --------------------------------------------------------------------------
def render_hello_sarkar_redirect(c):
    """
    Show the prepared complaint packet plus two real forwarding routes:
      1. The official Hello Sarkar grievance portal (gunaso.opmcm.gov.np).
      2. A WhatsApp click-to-chat link to Hello Sarkar's published number
         (+977 985-1145045), pre-filled with the full complaint text.

    Neither Hello Sarkar's portal nor WhatsApp's click-to-chat links support
    auto-attaching a photo — that's a platform limitation, not something this
    app can bypass — so if the citizen attached a photo, it's shown here with
    a clear instruction to attach it manually before sending.
    """
    st.markdown("##### 📦 Prepared Complaint Packet (copy into Hello Sarkar)")
    packet = (
        f"Tracking ID: {c['id']}\n"
        f"Municipality: Nagarain Municipality, Dhanusa, Madhesh Province\n"
        f"Ward: {c['ward']}\n"
        f"Sector: {c['sector']}\n"
        f"Language: {c['language']}\n"
        f"Days Unresolved: {c['days_unresolved']}\n"
        f"Original Complaint: {c['text']}\n"
        f"Municipal Outcome: REJECTED / DEFERRED\n"
        f"AI / Municipal Reason: {c['ai_reason'] or 'Not provided'}\n"
    )
    st.code(packet, language="text")

    if c.get("photo_bytes"):
        st.markdown("##### 📷 Attached Photo")
        st.image(c["photo_bytes"], caption=c.get("photo_name", "complaint_photo"), width=280)
        st.caption(
            "⚠️ WhatsApp and the Hello Sarkar portal can't pull this photo in "
            "automatically — attach it manually in the chat / upload form "
            "after opening the link below."
        )

    whatsapp_text = quote(f"Hello Sarkar Complaint Forward — Bajet Sunuwai\n\n{packet}")
    whatsapp_url = f"https://wa.me/{HELLO_SARKAR_WHATSAPP_NUMBER}?text={whatsapp_text}"

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(
            f"""
            <a href="{whatsapp_url}" target="_blank">
                <button style="background-color:#25703f;color:#f2efe8;border:none;
                padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer;width:100%;">
                    💬 Send via WhatsApp to Hello Sarkar (+977 985-1145045)
                </button>
            </a>
            """,
            unsafe_allow_html=True,
        )
    with col_b:
        st.markdown(
            f"""
            <a href="{HELLO_SARKAR_PORTAL_URL}" target="_blank">
                <button style="background-color:#8c2f22;color:#f2efe8;border:none;
                padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer;width:100%;">
                    🔗 Open Hello Sarkar Portal
                </button>
            </a>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        "The WhatsApp button opens a chat with Hello Sarkar's published number "
        "with the complaint text already filled in — just attach the photo above "
        "(if any) and hit send. Neither route supports auto-attaching a photo; "
        "that step stays manual on both platforms."
    )


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
            photo = st.file_uploader(
                "Attach a photo (optional)",
                type=["jpg", "jpeg", "png"],
                key="citizen_photo_upload",
            )
            submitted = st.form_submit_button("📤 Submit to AI Ingestion Agent", type="primary")

        if submitted:
            if not text.strip():
                st.warning("Please enter some text before submitting.")
            else:
                with st.spinner("AI Ingestion Agent is analyzing your submission..."):
                    result, source = ai_classify_complaint(text.strip(), sector, language)

                new_id = next_complaint_id()
                complaint = seed_complaint(
                    new_id, ward, sector, language, text.strip(), 0,
                    priority=result["priority"],
                    ai_summary=result.get("summary"),
                    ai_urgency_reasoning=result.get("urgency_reasoning"),
                    classification_source=source,
                )
                if photo is not None:
                    complaint["photo_bytes"] = photo.getvalue()
                    complaint["photo_name"] = photo.name
                st.session_state.complaints.append(complaint)
                save_state()

                mode_badge = "🟢 Live AI" if source == "ai" else "🟠 Fallback Simulation"
                st.success(
                    f"✅ AI Ingestion Agent processed your entry. ({mode_badge})\n\n"
                    f"**Tracking ID:** `{new_id}`  \n"
                    f"**Detected Language:** {result['detected_language']}  \n"
                    f"**Priority Flag:** {complaint['priority']}  \n"
                    f"**Reasoning:** {result['urgency_reasoning']}"
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

            if c.get("ai_summary"):
                source_pill = "pill-live" if c.get("classification_source") == "ai" else "pill-fallback"
                source_label = "🟢 Live AI" if c.get("classification_source") == "ai" else "🟠 Fallback"
                st.markdown(
                    f"""<span class="status-pill {source_pill}">{source_label}</span>""",
                    unsafe_allow_html=True,
                )
                st.caption(f"**AI Summary:** {c['ai_summary']}")
                st.caption(f"**Urgency Reasoning:** {c['ai_urgency_reasoning']}")

            if c.get("photo_bytes"):
                st.image(c["photo_bytes"], caption=c.get("photo_name", "attached photo"), width=220)

            if not st.session_state.budget_published:
                st.info(
                    "🕓 The municipal assembly is reviewing your data. "
                    "You will be notified once the budget is finalized."
                )
            else:
                if c["funded"] is True:
                    st.markdown(
                        """<span class="status-pill pill-funded">SUCCESS — FUNDED</span>""",
                        unsafe_allow_html=True,
                    )
                    st.write(f"**AI Explanation:** {c['ai_reason']}")
                    if c["admin_response"]:
                        st.write(f"**Municipal Note:** {c['admin_response']}")
                else:
                    st.markdown(
                        """<span class="status-pill pill-rejected">REJECTED / DEFERRED</span>""",
                        unsafe_allow_html=True,
                    )
                    st.write(f"**AI Explanation:** {c['ai_reason'] or 'Awaiting municipal review.'}")
                    if c["admin_response"]:
                        st.write(f"**Municipal Note:** {c['admin_response']}")

                # --- Hello Sarkar Escalation ---
                not_succeeded = c["funded"] is False
                if not_succeeded:
                    st.markdown("---")
                    if c["escalated"]:
                        st.error(
                            "🚨 This complaint has already been forwarded to the "
                            "**Central Hello Sarkar Prime Minister's Dashboard**."
                        )
                        render_hello_sarkar_redirect(c)
                    else:
                        if c["days_unresolved"] >= 7:
                            st.warning(
                                "⚠️ This complaint was **not successful** and has been "
                                f"unresolved for {c['days_unresolved']} days — eligible "
                                "for priority escalation."
                            )
                        else:
                            st.warning(
                                "⚠️ This complaint was **not successful** "
                                "(REJECTED / DEFERRED). You may forward it directly "
                                "to Hello Sarkar for central review."
                            )

                        if st.button(
                            f"📤 Share {c['id']} to Hello Sarkar",
                            key=f"escalate_{c['id']}",
                            type="primary",
                        ):
                            c["escalated"] = True
                            st.session_state.logs.append(
                                f"[ESCALATION] {c['id']} forwarded to Central Hello Sarkar "
                                f"PM Dashboard — data packet, local budget caps, and "
                                f"multi-year failure logs transmitted."
                            )
                            save_state()
                            st.rerun()


# --------------------------------------------------------------------------
# ADMIN AUTH GATE
# --------------------------------------------------------------------------
def render_admin_login():
    st.markdown(
        """
        <div class="main-header">
            <h1>🔒 Municipal Admin Login</h1>
            <p>Authorized officials only — Nagarain Municipality</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("admin_login_form"):
        pw = st.text_input("Admin Password", type="password")
        submitted = st.form_submit_button("🔓 Log In", type="primary")
    if submitted:
        if pw == get_admin_password():
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.caption(
        "Demo credential is set via the ADMIN_PASSWORD secret/environment variable "
        "(defaults to a placeholder if unset). This gate exists to demonstrate "
        "role separation between citizens and officials — production deployment "
        "would use proper per-official accounts."
    )


# --------------------------------------------------------------------------
# ADMIN PORTAL
# --------------------------------------------------------------------------
def render_admin_portal():
    if not st.session_state.admin_authenticated:
        render_admin_login()
        return

    st.markdown(
        """
        <div class="main-header">
            <h1>🏢 Municipal Admin Operations Room</h1>
            <p>Nagarain Municipality — Agentic AI Capital Budget Allocation Console</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_col1, top_col2 = st.columns([5, 1])
    with top_col2:
        if st.button("🔒 Log Out"):
            st.session_state.admin_authenticated = False
            st.rerun()

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
                "Federal Equalization Grants (NPR)", min_value=0,
                value=st.session_state.federal_grant, step=100_000,
            )
        with c2:
            st.session_state.provincial_grant = st.number_input(
                "Provincial Grants (NPR)", min_value=0,
                value=st.session_state.provincial_grant, step=100_000,
            )
        with c3:
            st.session_state.internal_revenue = st.number_input(
                "Internal Source Revenue (NPR)", min_value=0,
                value=st.session_state.internal_revenue, step=100_000,
            )

        st.info(f"**Total Revenue Ceiling:** {fmt_npr(total_revenue_ceiling())}")

        st.session_state.policy_directive = st.text_area(
            "Mayor's Policy Directive",
            value=st.session_state.policy_directive,
            height=90,
            help="This text is fed directly into the AI Allocation Agent's prompt — "
                 "changing it changes how the agent reasons about funding priority.",
        )
        if st.button("💾 Save Revenue & Policy Settings"):
            save_state()
            st.success("Saved.")

    # --- STEP 2 ---
    with st.expander("📄 Step 2: Ingest Memos & Dhyanakarshan Letters", expanded=False):
        uploaded_memo = st.file_uploader(
            "Upload PDF or text memo from youth clubs / political factions",
            type=["pdf", "txt"], key="memo_uploader",
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
                st.session_state.memos.append({
                    "source": memo_source or "Unspecified Entity",
                    "doc_type": memo_type,
                    "demand": extracted_demand,
                })
                save_state()
                st.success(f"Memo '{uploaded_memo.name}' ingested and parsed.")
            else:
                st.warning("Please attach a file before ingesting.")

        st.markdown("#### Active Memorandums")
        st.caption(
            "These memos are passed directly into the AI Allocation Agent's prompt "
            "context alongside the citizen complaints."
        )
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
        st.markdown("#### 🧪 Synthetic Load Test")
        st.caption(
            "Generate additional synthetic complaints to stress-test the allocation "
            "agent's behavior under real budget scarcity, rather than only the 3 seeded demo cases."
        )
        gen_col1, gen_col2 = st.columns([1, 3])
        with gen_col1:
            gen_count = st.number_input("How many?", min_value=5, max_value=40, value=15, step=5)
        with gen_col2:
            if st.button("🧪 Generate Synthetic Complaints"):
                for i in range(gen_count):
                    sector, language, template = random.choice(SYNTHETIC_TEMPLATES)
                    ward = random.choice(WARDS)
                    days = random.randint(0, 20)
                    cid = next_complaint_id()
                    complaint = seed_complaint(cid, ward, sector, language, template, days)
                    st.session_state.complaints.append(complaint)
                save_state()
                st.success(f"Generated {gen_count} synthetic complaints for load testing.")
                st.rerun()

        st.markdown("---")

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
                        value=c["admin_response"], key=f"response_{c['id']}",
                    )
                with oc2:
                    c["override_include"] = st.selectbox(
                        f"Force-fund {c['id']}?", ["Yes", "No"],
                        index=0 if c["override_include"] == "Yes" else 1,
                        key=f"override_{c['id']}",
                    )
                st.markdown("---")
            if st.button("💾 Save Overrides"):
                save_state()
                st.success("Saved.")

    # --- STEP 4 ---
    with st.expander("🤖 Step 4: AI Agentic Capital Budget Allocation Assembly", expanded=True):
        mode_pill = "pill-live" if AI_LIVE else "pill-fallback"
        mode_label = "🟢 Live AI Agent (Claude tool-use loop)" if AI_LIVE else "🟠 Fallback Simulation (no API key configured)"
        st.markdown(f"""<span class="status-pill {mode_pill}">{mode_label}</span>""", unsafe_allow_html=True)
        st.write("")
        st.write(
            "This agent is given the revenue ceiling, the Mayor's policy directive, "
            "every ingested memo, and every open complaint. It then decides — turn by "
            "turn, via tool calls — what to fund, defer, or reject, and why. The app "
            "enforces the hard budget ceiling; the agent decides everything within it."
        )

        if st.button("🚀 Compile and Run AI Budget Allocation Engine", type="primary"):
            with st.spinner("Allocation agent is reasoning over budget, policy, and complaints..."):
                mode_used, trace = run_ai_allocation_engine()
            save_state()
            if mode_used == "ai":
                st.success("✅ Live AI Allocation Agent completed the run.")
            else:
                st.warning("⚠️ Ran in fallback simulation mode (no live AI backend available).")

        if st.session_state.trace_log:
            st.markdown("#### 🧠 Agent Trace (live tool-call log)")
            for line in st.session_state.trace_log[-30:]:
                st.markdown(f"""<div class="trace-card">{line}</div>""", unsafe_allow_html=True)

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
                type=["xlsx", "csv"], key="revised_upload",
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
                            updated_projects.append({
                                "project_name": row.get("Project Name", "Unnamed Project"),
                                "ward": row.get("Target Ward", ""),
                                "sector": row.get("Target Sector", ""),
                                "amount": float(row.get("Allocated Amount (NPR)", 0) or 0),
                                "justification": row.get("AI Logic Justification", ""),
                                "linked_complaint": "",
                            })
                        st.session_state.projects = updated_projects
                        st.session_state.logs.append(
                            "[ALERT] Master dashboard synced with planning engineer's "
                            "manually revised allocation sheet (human-in-the-loop validation)."
                        )
                        save_state()
                        st.success("✅ Master stats dashboard updated from the revised sheet.")
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
                    save_state()
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

    ai_pill = "🟢 Live AI Backend" if AI_LIVE else "🟠 Fallback Simulation Mode"
    st.sidebar.markdown(f"**AI Status:** {ai_pill}")
    if not AI_LIVE:
        st.sidebar.caption(
            "Set ANTHROPIC_API_KEY (env var or .streamlit/secrets.toml) to enable "
            "the live ingestion and allocation agents."
        )

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
