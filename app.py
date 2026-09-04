"""
Bajet Sunuwai (बजेट सुनुवाई)
================================
A multi-agent, agentic AI civic-budget platform for Nagarain Municipality,
Dhanusa, Madhesh Province, Nepal. Built for the Yantra Business Cup
SOFTBOTS AI Hackathon.

FOUR-AGENT ARCHITECTURE
  1. Ingestion & NLP Agent — reads a raw citizen complaint (text, or a
     photographed memo/petition) and returns a structured classification:
     detected language, sector, an objective Severity Score, and reasoning.
  2. Context-Aware Allocation Agent — a multi-step tool-use LOOP. Given the
     budget ceiling, the Mayor's policy directive, LIVE hazard data pulled
     from the Open-Meteo API for each ward, and the aggregate citizen
     demand signal, it decides — turn by turn — what to fund or defer, and
     why. The app enforces the hard budget ceiling; the agent decides
     everything within it.
  3. Independent Auditor & Fairness Agent — runs AFTER allocation. It
     compares the final decisions (including any manual official
     overrides) against the objective citizen demand data and raises
     Conflict Flags where a high-severity ward/sector was starved in favor
     of a lower-priority one.
  4. Output, Export & Notification Agent — converts the approved budget
     into a downloadable .xlsx/.csv, and drives citizen notifications
     (WhatsApp + the Live Transparency Matrix), logging a full lifecycle
     from complaint ID to allocated Project ID to notification sent.

All three AI agents gracefully fall back to deterministic simulation logic
if no ANTHROPIC_API_KEY is configured, or if a live call fails — so the
demo never crashes, but the UI is always explicit about which mode is
actually running (🟢 Live AI vs 🟠 Fallback Simulation).

COST NOTE: GitHub, Streamlit Community Cloud hosting, and the Open-Meteo
hazard API used here are all free / keyless. The Anthropic API calls that
power the three agents are NOT free — budget some API credit before a
live demo.

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
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

try:
    import anthropic
    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    ANTHROPIC_SDK_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

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

# The five mandatory thematic municipal sectors under Nepal's local-level
# participatory planning process.
SECTORS = [
    "Infrastructure",
    "Social Development",
    "Economic Development",
    "Agriculture & Environment",
    "Governance",
]

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

# --------------------------------------------------------------------------
# WARD GEOGRAPHIC / HAZARD PROFILES
# --------------------------------------------------------------------------
# NOTE FOR THE TEAM: the lat/lon values are small offsets around Nagarain
# Municipality's real center point (26.63889°N, 85.91611°E, per public
# records) approximating each ward's rough position — NOT surveyed ward
# boundary centroids. The terrain/infrastructure text is illustrative for
# the demo. Before real deployment, replace both with verified data from
# the municipality's GIS office / ward profile reports / CBS census.
# The flood-risk NUMBERS, however, are fetched live from Open-Meteo
# (api.open-meteo.com) — a free, keyless weather API — so that part of the
# "connects to external environmental/hazard APIs" claim is genuinely real.
WARD_PROFILES = {
    "Ward 1": {
        "lat": 26.6420, "lon": 85.9050,
        "terrain": "Riverside lowland, adjacent to the main seasonal river channel",
        "flood_risk": "High",
        "population_estimate": 6200,
        "existing_infra_notes": "Weak embankment, aging drainage culverts",
    },
    "Ward 2": {
        "lat": 26.6389, "lon": 85.9161,
        "terrain": "Market/bazaar corridor, moderately dense settlement",
        "flood_risk": "Medium",
        "population_estimate": 7100,
        "existing_infra_notes": "Highest commercial footfall; streetlight and drainage gaps",
    },
    "Ward 3": {
        "lat": 26.6300, "lon": 85.9200,
        "terrain": "Low-lying agricultural belt with shallow groundwater table",
        "flood_risk": "High",
        "population_estimate": 5400,
        "existing_infra_notes": "Water supply pipeline network is over 15 years old",
    },
    "Ward 4": {
        "lat": 26.6470, "lon": 85.9250,
        "terrain": "Mixed farmland and residential, gently sloped",
        "flood_risk": "Medium",
        "population_estimate": 4900,
        "existing_infra_notes": "Canal network serves most farms but silts up yearly",
    },
    "Ward 5": {
        "lat": 26.6250, "lon": 85.9100,
        "terrain": "Southern agricultural plain, closest to the Nepal-India border belt",
        "flood_risk": "High",
        "population_estimate": 5800,
        "existing_infra_notes": "Irrigation canals undersized for peak monsoon flow",
    },
}


def fetch_ward_hazard(ward):
    """
    Fetch a LIVE 7-day precipitation outlook for a ward's approximate
    coordinates from the free, keyless Open-Meteo forecast API. Cached in
    session_state so we don't refetch on every Streamlit rerun. Falls back
    to the static baseline flood_risk rating if `requests` isn't available
    or the call fails — this is the real "external environmental/hazard
    API" connection called for in the architecture doc.
    """
    cache = st.session_state.setdefault("hazard_cache", {})
    if ward in cache:
        return cache[ward]

    profile = WARD_PROFILES[ward]
    result = {
        "source": "fallback",
        "precip_7day_mm": None,
        "max_precip_probability": None,
    }

    if REQUESTS_AVAILABLE:
        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": profile["lat"],
                    "longitude": profile["lon"],
                    "daily": "precipitation_sum,precipitation_probability_max",
                    "forecast_days": 7,
                    "timezone": "Asia/Kathmandu",
                },
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json()
                daily = data.get("daily", {})
                precip_values = daily.get("precipitation_sum") or []
                prob_values = daily.get("precipitation_probability_max") or []
                result = {
                    "source": "live",
                    "precip_7day_mm": round(sum(precip_values), 1) if precip_values else 0.0,
                    "max_precip_probability": max(prob_values) if prob_values else 0,
                }
        except Exception:
            pass

    cache[ward] = result
    return result


def ward_profile_summary():
    """Returns (summary_text, any_live_bool) combining static ward
    context with live-or-fallback hazard data for every ward."""
    lines = []
    any_live = False
    for ward, p in WARD_PROFILES.items():
        hz = fetch_ward_hazard(ward)
        if hz["source"] == "live":
            any_live = True
            hazard_text = (
                f"LIVE 7-day forecast: {hz['precip_7day_mm']} mm total precipitation, "
                f"{hz['max_precip_probability']}% peak daily rain probability (Open-Meteo)"
            )
        else:
            hazard_text = f"Baseline flood-risk rating: {p['flood_risk']} (live forecast unavailable)"
        lines.append(
            f"- {ward}: {p['terrain']}. {hazard_text}. "
            f"Est. population: {p['population_estimate']:,}. "
            f"Infrastructure notes: {p['existing_infra_notes']}."
        )
    return "\n".join(lines), any_live


def citizen_demand_summary():
    """
    Aggregate the current complaint set into a structured 'what citizens
    actually want this cycle' briefing — by ward and by sector, weighted
    by each complaint's Severity Score (from the Ingestion Agent, or a
    heuristic default in fallback mode).
    """
    complaints = st.session_state.get("complaints", [])
    if not complaints:
        return "No citizen suggestions submitted yet this cycle.", {}

    by_sector = {}
    by_ward = {}
    for c in complaints:
        weight = c.get("severity_score") or (7 if c["priority"] == "High Priority" else 3)
        by_sector[c["sector"]] = by_sector.get(c["sector"], 0) + weight
        by_ward[c["ward"]] = by_ward.get(c["ward"], 0) + weight

    total = sum(by_sector.values()) or 1
    sector_lines = [
        f"- {sector}: severity-weighted signal {score} — "
        f"{round(100 * score / total)}% of citizen demand this cycle"
        for sector, score in sorted(by_sector.items(), key=lambda x: -x[1])
    ]
    ward_lines = [
        f"- {ward}: severity-weighted signal {score}"
        for ward, score in sorted(by_ward.items(), key=lambda x: -x[1])
    ]
    summary_text = (
        "Citizen demand by sector (Severity Score-weighted):\n"
        + "\n".join(sector_lines)
        + "\n\nCitizen demand by ward:\n"
        + "\n".join(ward_lines)
    )
    return summary_text, {"by_sector": by_sector, "by_ward": by_ward}


SYNTHETIC_TEMPLATES = [
    ("Infrastructure", "Nepali", "Yo bato dherai barsha dekhi bigreko cha, gaadi chalauna gaahro bha cha."),
    ("Infrastructure", "Bhojpuri", "Gaon ke sadak me gaddha ba, durghatna hoit rahal ba har hafta."),
    ("Social Development", "Maithili", "Skool bhawan ke chhat toot gel ba, barsat me paani tapkait ba."),
    ("Social Development", "Bhojpuri", "Aspatal me daktar samay pe nai aawe la, mareez pareshan ba."),
    ("Economic Development", "Nepali", "Haat bazaar ko bhawan jeerna bhaisakeko cha, byapari haru lai samasya bha rako cha."),
    ("Economic Development", "Maithili", "Sthaniya bajar me saaf-safai aur chhat ke abhav se vyapar prabhavit bha rahal ba."),
    ("Agriculture & Environment", "Bhojpuri", "Sinchai naali me paani nai aawe la, fasal sukhaa ho rahal ba."),
    ("Agriculture & Environment", "Nepali", "Baadhi le kheti nasta bhayo, paani niskasan ko byawastha chaina."),
    ("Governance", "Maithili", "Ward karyalaya me nagarikta aur sifarish banawe me bahut samay lagait ba."),
    ("Governance", "Nepali", "Ward office ma sewa lina dherai palta dhauna parxa, karmachari samay ma huँdainan."),
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
        .conflict-card {
            background-color: #f2efe8;
            border-left: 4px solid #8c2f22;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 8px;
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
        .pill-critical { background-color: #8c2f22; }
        .pill-moderate { background-color: #8a5a2f; }
        .pill-low { background-color: #6e6656; }
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


def verify_ai_live(force=False):
    """
    Checks whether the AI backend is not just CONFIGURED but actually
    AUTHENTICATED — get_client() only proves a non-empty key string was
    supplied, not that it's valid. This makes one cheap real API call
    (models.list) to confirm the key actually authenticates, and caches
    the result in session_state so it only runs once per session instead
    of on every Streamlit rerun (which would burn an API call per click).
    Returns (is_live: bool, error_message: str | None).
    """
    if not force and "ai_live_verified" in st.session_state:
        return st.session_state.ai_live_verified, st.session_state.get("ai_live_error")

    client = get_client()
    if client is None:
        st.session_state.ai_live_verified = False
        st.session_state.ai_live_error = "No API key configured."
        return False, st.session_state.ai_live_error

    try:
        client.models.list(limit=1)
        st.session_state.ai_live_verified = True
        st.session_state.ai_live_error = None
        return True, None
    except Exception as exc:
        st.session_state.ai_live_verified = False
        st.session_state.ai_live_error = str(exc)
        return False, str(exc)


def create_with_retry(client, retries=1, backoff_seconds=1.5, **kwargs):
    """
    Thin wrapper around client.messages.create() that retries once on any
    transient failure (network blip, rate limit, brief API hiccup) before
    the caller gives up and drops to fallback simulation mode. This exists
    specifically so a single flaky network moment during a LIVE demo/pitch
    doesn't visibly trip fallback mode on screen in front of judges — the
    fallback path itself stays exactly as honest as before if every retry
    is exhausted.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return client.messages.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff_seconds)
    raise last_exc


# --------------------------------------------------------------------------
# SQLITE PERSISTENCE
# --------------------------------------------------------------------------
STATE_KEYS = [
    "complaints", "memos", "projects", "logs", "trace_log",
    "federal_grant", "provincial_grant", "internal_revenue",
    "policy_directive", "budget_published", "next_complaint_num",
    "conflict_flags", "fairness_assessment", "fairness_source",
    "total_population", "total_wards_count", "hospital_access",
    "higher_secondary_access", "literacy_rate",
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
                    priority=None, severity_score=None, ai_summary=None,
                    ai_urgency_reasoning=None, classification_source="fallback"):
    if priority is None:
        priority = classify_priority_fallback(text)
    if severity_score is None:
        severity_score = 7 if priority == "High Priority" else 3
    return {
        "id": cid,
        "ward": ward,
        "sector": sector,
        "language": language,
        "text": text,
        "priority": priority,
        "severity_score": severity_score,
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
                "CMP-101", "Ward 3", "Infrastructure", "Maithili",
                "Hamar tolaa mein pani ke pipe bahut din se toot gel ba, pani "
                "nai aabait ba aur samasya bahut bhayavaha ho gel ba.",
                10,
            ),
            seed_complaint(
                "CMP-102", "Ward 1", "Infrastructure", "Nepali",
                "Bato ekdam kharab avastha ma cha, motorcycle chalauna gaahro "
                "vayeko cha ra baccha haru school jaanay bela dherai samasya huncha.",
                3,
            ),
            seed_complaint(
                "CMP-103", "Ward 5", "Agriculture & Environment", "Bhojpuri",
                "Khet me sinchai ke naali dherai purana ba, baarish me paani "
                "jama ho jaala aur fasal barbaad ho jaala, jaldi thik karwaawa.",
                12,
            ),
            seed_complaint(
                "CMP-104", "Ward 2", "Social Development", "Nepali",
                "Swasthya chauki ma udhaharan ausadhi upalabdha chaina, "
                "biramiharu lai ekdam samasya bha rako cha.",
                6,
            ),
            seed_complaint(
                "CMP-105", "Ward 4", "Governance", "Maithili",
                "Ward karyalaya me nagarikta aur sifarish banawe me bahut "
                "samay lagait ba, karmachari samay pe nai aawe la.",
                8,
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
        "next_complaint_num": 106,
        "conflict_flags": [],
        "fairness_assessment": None,
        "fairness_source": None,
        # --- Tathya Matrix: structural reality metrics ---
        "total_population": 34_000,
        "total_wards_count": 5,
        "hospital_access": "No",
        "higher_secondary_access": "Yes",
        "literacy_rate": 61.5,
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
    if "hazard_cache" not in st.session_state:
        st.session_state.hazard_cache = {}


def reset_to_default_state():
    """
    Wipes all complaints, projects, logs, financials, and Tathya Matrix
    values back to the seeded 5-complaint demo starting point, and persists
    that reset to SQLite. Does NOT log the admin out or touch the
    ANTHROPIC_API_KEY / ADMIN_PASSWORD secrets — only the demo's data state.
    """
    fresh = default_state()
    for key, value in fresh.items():
        st.session_state[key] = value
    st.session_state.hazard_cache = {}
    save_state()


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


# --------------------------------------------------------------------------
# 60/40 BUDGET SPLIT
# --------------------------------------------------------------------------
STRATEGIC_FUND_PCT = 0.60  # Core Strategic Fund — top-down, statutory, master planning
REDRESSAL_FUND_PCT = 0.40  # Citizen Redressal Fund — bottom-up, ward complaints


def strategic_fund_amount():
    return round(total_revenue_ceiling() * STRATEGIC_FUND_PCT)


def redressal_fund_amount():
    # Computed as the remainder (not ceiling * 0.4) so the two pools always
    # sum exactly to the Total Revenue Ceiling regardless of rounding.
    return total_revenue_ceiling() - strategic_fund_amount()


def strategic_allocated():
    return sum(p["amount"] for p in st.session_state.projects if p.get("pool") == "Strategic")


def tactical_allocated():
    return sum(p["amount"] for p in st.session_state.projects if p.get("pool") == "Tactical")


def allocated_expenditure():
    return sum(p["amount"] for p in st.session_state.projects)


def unallocated_reserve():
    return total_revenue_ceiling() - allocated_expenditure()


def fmt_npr(amount):
    return f"NPR {amount:,.0f}"


# --------------------------------------------------------------------------
# TATHYA MATRIX — structural reality metrics
# --------------------------------------------------------------------------
def mandatory_strategic_flags():
    """
    Deterministic statutory triggers derived from the Tathya Matrix. These
    are handed to the Strategic Pass agent as MANDATORY projects it must
    fund, and enforced by a safety net even if the live agent misses one —
    so the rule always visibly fires in a demo, live API or not.

    Each flag carries a stable `trigger_key` — the agent is asked to echo
    this exact key back via the fulfills_trigger_key tool parameter when it
    funds the matching project, so the safety net can check for an EXACT
    key match instead of fuzzy-matching truncated project name strings
    (which breaks the moment the model names the project something the
    demo author didn't anticipate verbatim).
    """
    flags = []
    pop = st.session_state.total_population

    if st.session_state.hospital_access == "No" and pop > 30_000:
        flags.append({
            "trigger_key": "hospital_construction",
            "project_name": "Baseline Phase-1 Municipal Hospital Construction",
            "category": "Statutory Mandate",
            "trigger": f"Hospital Access = No and Population ({pop:,}) > 30,000",
            "fallback_amount": min(8_000_000, strategic_fund_amount()),
        })

    if st.session_state.higher_secondary_access == "No" and pop > 30_000:
        flags.append({
            "trigger_key": "higher_secondary_school",
            "project_name": "Baseline Higher Secondary School Establishment",
            "category": "Statutory Mandate",
            "trigger": f"Higher Secondary School Access = No and Population ({pop:,}) > 30,000",
            "fallback_amount": min(5_000_000, strategic_fund_amount()),
        })

    return flags


# --------------------------------------------------------------------------
# AGENT 1 — INGESTION & NLP AGENT (single structured tool-use call)
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
            "severity_score": {
                "type": "integer",
                "description": "An objective 1-10 severity score based on urgency and "
                                "apparent public impact of this specific complaint.",
            },
            "urgency_reasoning": {
                "type": "string",
                "description": "1-2 sentences explaining why this priority/score was "
                                "assigned, referencing specific content in the complaint.",
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
            "detected_language", "priority", "severity_score",
            "urgency_reasoning", "summary", "sector_confidence",
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
        response = create_with_retry(
            client, retries=1,
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
        "severity_score": 7 if priority == "High Priority" else 3,
        "urgency_reasoning": "Heuristic fallback: keyword/length match, no live model call.",
        "summary": text[:100] + ("..." if len(text) > 100 else ""),
        "sector_confidence": "not evaluated (fallback mode)",
    }


# --------------------------------------------------------------------------
# AGENT 1b — SCANNED MEMO OCR (Ingestion Agent, image variant)
# --------------------------------------------------------------------------
MEMO_OCR_TOOL = {
    "name": "extract_memo",
    "description": "Extract structured information from a photographed memo, petition, "
                    "or ward-assembly minute sheet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source_entity": {"type": "string", "description": "Who sent/wrote this document."},
            "document_type": {
                "type": "string",
                "enum": ["Dhyanakarshan Letter", "Policy Memo", "Petition", "Ward Assembly Minutes"],
            },
            "extracted_demand": {
                "type": "string",
                "description": "Plain-English summary of what is being requested.",
            },
            "detected_language": {"type": "string"},
        },
        "required": ["source_entity", "document_type", "extracted_demand", "detected_language"],
    },
}


def ai_extract_memo_from_image(image_bytes, media_type):
    """Real OCR-via-vision call. Returns a structured dict on success, or
    None if no live backend / the call failed (caller falls back to a
    placeholder extraction)."""
    client = get_client()
    if client is None:
        return None
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        response = create_with_retry(
            client, retries=1,
            model=MODEL_NAME,
            max_tokens=600,
            tools=[MEMO_OCR_TOOL],
            tool_choice={"type": "tool", "name": "extract_memo"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": (
                        "This is a photographed memo, petition, or ward-assembly minute "
                        "sheet submitted to Nagarain Municipality. Extract its content "
                        "using the extract_memo tool."
                    )},
                ],
            }],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_memo":
                return block.input
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------
# AGENT 2 — CONTEXT-AWARE ALLOCATION AGENT
# Two-Pass architecture:
#   Pass 1 (Strategic)  — funds macro/statutory projects from the 60% Core
#                          Strategic Fund, driven by the Tathya Matrix.
#   Pass 2 (Tactical)   — funds ward complaints from the 40% Citizen
#                          Redressal Fund, driven by hazard + demand data.
# The two pools are independent — the Tactical Pass never sees Strategic
# Fund money and vice versa, matching the mandated 60/40 split exactly.
# --------------------------------------------------------------------------

STRATEGIC_TOOLS = [
    {
        "name": "get_remaining_strategic_budget",
        "description": "Check how much of the 60% Core Strategic Fund is still unallocated.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fund_strategic_project",
        "description": "Allocate Core Strategic Fund budget to a macro-level, master-planning, "
                        "or statutory project (not tied to a single citizen complaint).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in NPR, must not exceed the remaining Strategic Fund."},
                "category": {
                    "type": "string",
                    "enum": ["Statutory Mandate", "Master Planning", "Large Infrastructure"],
                },
                "justification": {
                    "type": "string",
                    "description": "Why this project was funded — reference the Tathya Matrix "
                                    "structural facts and/or the Mayor's policy directive.",
                },
                "fulfills_trigger_key": {
                    "type": "string",
                    "description": "If this project fulfills one of the MANDATORY trigger_key "
                                    "values listed in the prompt, put that EXACT key here "
                                    "verbatim (e.g. 'hospital_construction'). Leave empty if this "
                                    "project is discretionary master-planning, not a mandatory trigger.",
                },
            },
            "required": ["project_name", "amount", "category", "justification"],
        },
    },
    {
        "name": "finish_strategic_pass",
        "description": "Call this once all mandatory statutory projects and any additional "
                        "master-planning projects have been funded.",
        "input_schema": {
            "type": "object",
            "properties": {"closing_note": {"type": "string"}},
            "required": ["closing_note"],
        },
    },
]


def run_strategic_pass():
    """
    Pass 1. Controls ONLY the 60% Core Strategic Fund. Evaluates the Tathya
    Matrix first — any statutory trigger (e.g. no hospital access with
    population > 30,000) MUST be funded before anything else. Returns
    (source, projects, trace_lines, log_lines).
    """
    client = get_client()
    mandatory = mandatory_strategic_flags()

    if client is None:
        return run_fallback_strategic_pass(mandatory)

    budget = {"amount": strategic_fund_amount()}
    projects = []
    trace = []
    logs = []

    mandatory_text = "\n".join(
        f"- MANDATORY [trigger_key=\"{f['trigger_key']}\"]: \"{f['project_name']}\" "
        f"(Category: {f['category']}) — trigger: {f['trigger']}. When you fund this "
        f"via fund_strategic_project, set fulfills_trigger_key to exactly "
        f"\"{f['trigger_key']}\"."
        for f in mandatory
    ) or "(no statutory triggers active this cycle)"

    geo_summary_text, _ = ward_profile_summary()

    system_prompt = (
        "You are Pass 1 (Strategic) of the Context-Aware Allocation Agent for "
        "Nagarain Municipality, Dhanusa, Madhesh Province, Nepal. You control "
        "ONLY the 60% Core Strategic Fund — reserved for master planning, "
        "large infrastructure (hospitals, school buildings), and mandatory "
        "statutory allocations. You do NOT see or touch individual citizen "
        "complaints; that is Pass 2's job. You are given a 'Tathya Matrix' "
        "of structural facts about the municipality.\n\n"
        "Any project listed as MANDATORY below MUST be funded via "
        "fund_strategic_project before anything else, using your own "
        "realistic capital cost estimate for a Nepali municipality of this "
        "size. After mandatory projects are funded, you may optionally fund "
        "additional master-planning or large-infrastructure projects if the "
        "Mayor's policy directive calls for it and Strategic Fund budget "
        "remains. Call finish_strategic_pass when done. Never propose an "
        "amount larger than the remaining Strategic Fund."
    )

    user_prompt = (
        f"Core Strategic Fund available (60% of Total Revenue Ceiling): "
        f"{fmt_npr(budget['amount'])}\n\n"
        f"Mayor's Policy Directive:\n{st.session_state.policy_directive}\n\n"
        f"Tathya Matrix (structural reality of the municipality):\n"
        f"- Total Population: {st.session_state.total_population:,}\n"
        f"- Total Wards: {st.session_state.total_wards_count}\n"
        f"- Hospital Access: {st.session_state.hospital_access}\n"
        f"- Higher Secondary School Access: {st.session_state.higher_secondary_access}\n"
        f"- Literacy Rate: {st.session_state.literacy_rate}%\n\n"
        f"Mandatory Statutory Triggers:\n{mandatory_text}\n\n"
        f"Ward Hazard Context (for large infrastructure siting):\n{geo_summary_text}\n\n"
        f"Begin the Strategic Pass now."
    )

    messages = [{"role": "user", "content": user_prompt}]
    max_turns = 15
    turn = 0

    try:
        while turn < max_turns:
            turn += 1
            response = create_with_retry(
            client, retries=1,
                model=MODEL_NAME,
                max_tokens=1200,
                system=system_prompt,
                tools=STRATEGIC_TOOLS,
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

                if block.name == "get_remaining_strategic_budget":
                    result_text = json.dumps({"remaining_strategic_budget": budget["amount"]})
                    trace.append(f"🔍 [STRATEGIC] get_remaining_strategic_budget → {fmt_npr(budget['amount'])}")

                elif block.name == "fund_strategic_project":
                    args = block.input
                    amount = float(args.get("amount", 0))
                    if amount > budget["amount"]:
                        result_text = json.dumps({
                            "error": "Amount exceeds remaining Strategic Fund",
                            "remaining_strategic_budget": budget["amount"],
                        })
                        trace.append(
                            f"⚠️ [STRATEGIC] fund_strategic_project rejected — requested "
                            f"{fmt_npr(amount)} exceeds remaining {fmt_npr(budget['amount'])}"
                        )
                    else:
                        budget["amount"] -= amount
                        project_name = args.get("project_name", "Untitled Strategic Project")
                        fulfills_key = (args.get("fulfills_trigger_key") or "").strip()
                        projects.append({
                            "project_name": project_name,
                            "ward": "Municipality-wide",
                            "sector": args.get("category", "Master Planning"),
                            "amount": amount,
                            "justification": args.get("justification", ""),
                            "linked_complaint": "",
                            "pool": "Strategic",
                            "fulfills_trigger_key": fulfills_key,
                        })
                        logs.append(f"[ALERT] Strategic project '{project_name}' funded ({fmt_npr(amount)})")
                        trace.append(f"✅ [STRATEGIC] fund_strategic_project → {project_name} — {fmt_npr(amount)}")
                        result_text = json.dumps({"success": True, "remaining_strategic_budget": budget["amount"]})

                elif block.name == "finish_strategic_pass":
                    closing_note = block.input.get("closing_note", "")
                    trace.append(f"🏁 [STRATEGIC] finish_strategic_pass — {closing_note}")
                    finished = True
                    result_text = json.dumps({"success": True})

                else:
                    result_text = json.dumps({"error": "unknown tool"})

                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
            if finished:
                break

        # Safety net: guarantee every mandatory statutory project exists,
        # even if the live agent skipped it. Matches on the EXACT
        # trigger_key the agent was asked to echo back — not a fuzzy
        # substring of the project name, which breaks the moment the model
        # names the project something the demo author didn't predict
        # verbatim (e.g. "Phase-1 Construction of Nagarain Municipal
        # Hospital" vs. the flag's own "Baseline Phase-1 Municipal...").
        fulfilled_keys = {
            p.get("fulfills_trigger_key", "") for p in projects if p.get("fulfills_trigger_key")
        }
        for flag in mandatory:
            if flag["trigger_key"] not in fulfilled_keys:
                fallback_amt = min(flag["fallback_amount"], budget["amount"])
                if fallback_amt > 0:
                    budget["amount"] -= fallback_amt
                    projects.append({
                        "project_name": flag["project_name"],
                        "ward": "Municipality-wide",
                        "sector": flag["category"],
                        "amount": fallback_amt,
                        "justification": f"Safety-net enforcement of statutory trigger: {flag['trigger']}.",
                        "linked_complaint": "",
                        "pool": "Strategic",
                        "fulfills_trigger_key": flag["trigger_key"],
                    })
                    logs.append(f"[ALERT] Strategic project '{flag['project_name']}' funded via safety net ({fmt_npr(fallback_amt)})")
                    trace.append(f"⚠️ [STRATEGIC] safety-net fund_strategic_project → {flag['project_name']} (agent missed mandatory trigger_key='{flag['trigger_key']}')")

        return "ai", projects, trace, logs

    except Exception as exc:
        return run_fallback_strategic_pass(mandatory, note=f"Live AI strategic pass failed ({exc}) — falling back.")


def run_fallback_strategic_pass(mandatory, note=None):
    """Deterministic simulation for the Strategic Pass — funds every
    mandatory statutory trigger at its fallback cost estimate, deterministic
    and reproducible."""
    trace = [note or "⚠️ FALLBACK MODE — no live AI backend; Strategic Pass using deterministic rules."]
    logs = []
    projects = []
    budget = strategic_fund_amount()

    for flag in mandatory:
        amt = min(flag["fallback_amount"], budget)
        if amt <= 0:
            continue
        budget -= amt
        projects.append({
            "project_name": flag["project_name"],
            "ward": "Municipality-wide",
            "sector": flag["category"],
            "amount": amt,
            "justification": f"[Fallback] Statutory trigger enforced: {flag['trigger']}.",
            "linked_complaint": "",
            "pool": "Strategic",
            "fulfills_trigger_key": flag["trigger_key"],
        })
        logs.append(f"[ALERT] Strategic project '{flag['project_name']}' funded ({fmt_npr(amt)}) [fallback]")
        trace.append(f"✅ [fallback-STRATEGIC] fund {flag['project_name']} — {fmt_npr(amt)}")

    if not mandatory:
        trace.append("ℹ️ [fallback-STRATEGIC] No statutory triggers active — Strategic Fund left as reserve this cycle.")

    return "fallback", projects, trace, logs


TACTICAL_TOOLS = [
    {
        "name": "get_remaining_budget",
        "description": "Check how much of the 40% Citizen Redressal Fund is still unallocated this cycle.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fund_project",
        "description": "Allocate Citizen Redressal Fund budget to a project addressing a specific complaint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "complaint_id": {"type": "string"},
                "project_name": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in NPR, must not exceed remaining budget."},
                "justification": {
                    "type": "string",
                    "description": "Why this project was funded — reference the policy "
                                    "directive, ward hazard data, and citizen demand signal.",
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
            "properties": {"closing_note": {"type": "string"}},
            "required": ["closing_note"],
        },
    },
]


def run_tactical_pass(strategic_projects=None):
    """
    Pass 2. Controls ONLY the 40% Citizen Redressal Fund. Runs AFTER Pass 1
    and is handed Pass 1's completed strategic projects as context — this is
    the real agent-to-agent handoff: Tactical doesn't just run blind, it
    reasons about what Strategic already committed to (e.g. avoiding a
    redundant small water project in a ward where Strategic just funded a
    major hospital that already includes water infrastructure). Returns
    (source, projects, trace_lines, log_lines).
    """
    strategic_projects = strategic_projects or []
    client = get_client()
    if client is None:
        return run_fallback_tactical_pass(strategic_projects)

    complaints_by_id = {c["id"]: c for c in st.session_state.complaints}
    open_complaints = [c for c in st.session_state.complaints if c["override_include"] == "Yes"]
    excluded_complaints = [c for c in st.session_state.complaints if c["override_include"] == "No"]

    remaining_budget = {"amount": redressal_fund_amount()}
    projects = []
    trace = []
    logs = []

    for c in excluded_complaints:
        c["status"] = "Budget Concluded"
        c["funded"] = False
        reason = "Excluded from this budget cycle per municipal override decision."
        if c["admin_response"]:
            reason += f" Municipal note: {c['admin_response']}"
        c["ai_reason"] = reason
        logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — REJECTED (manual override)")

    if not open_complaints:
        return "ai", projects, trace, logs

    complaint_summaries = "\n".join(
        f"- {c['id']} | Ward: {c['ward']} | Sector: {c['sector']} | "
        f"Priority: {c['priority']} | Severity Score: {c.get('severity_score', 'n/a')}/10 | "
        f"Days unresolved: {c['days_unresolved']} | Text: \"{c['text']}\""
        for c in open_complaints
    )
    memo_summaries = "\n".join(
        f"- {m['source']} ({m['doc_type']}): {m['demand']}" for m in st.session_state.memos
    ) or "(no memos ingested)"

    demand_summary_text, _ = citizen_demand_summary()
    geo_summary_text, hazard_is_live = ward_profile_summary()

    strategic_summary_text = "\n".join(
        f"- \"{p['project_name']}\" ({p['sector']}) — {fmt_npr(p['amount'])} — {p['justification'][:160]}"
        for p in strategic_projects
    ) or "(Pass 1 funded no strategic projects this cycle)"

    system_prompt = (
        "You are Pass 2 (Tactical) of the Context-Aware Allocation Agent for "
        "Nagarain Municipality, Dhanusa, Madhesh Province, Nepal. You control "
        "ONLY the 40% Citizen Redressal Fund — dedicated entirely to solving "
        "complaints, ward requests, and Tole feedback collected via the "
        "public portal.\n\n"
        "Pass 1 (Strategic) already ran and is handed to you below as "
        "completed context, not something you can spend from — you never "
        "touch that fund. Read what Pass 1 already committed to BEFORE "
        "deciding: if a citizen complaint is already substantially addressed "
        "by a strategic project Pass 1 funded (e.g. a ward's water-supply "
        "complaint overlaps with a hospital project that includes its own "
        "water infrastructure), say so explicitly in your justification and "
        "either defer it or fund only the gap Pass 1 didn't cover — don't "
        "double-fund the same underlying need from both pools. Use the tools "
        "provided: check get_remaining_budget before large decisions, call "
        "fund_project or defer_complaint for EVERY open complaint exactly "
        "once, and call finish_allocation when done. Never propose an amount "
        "larger than the remaining budget.\n\n"
        "Ground every funding decision in FOUR things, and name which ones "
        "applied in the justification field:\n"
        "1. What Pass 1 (Strategic) already funded — avoid redundancy.\n"
        "2. The specific ward's LIVE hazard/flood-risk data below.\n"
        "3. The aggregate citizen demand signal below — sectors and wards "
        "where citizens are collectively asking loudest (higher combined "
        "Severity Score) should be weighted higher.\n"
        "4. The Mayor's policy directive and any ingested memos.\n"
        "Do not use generic boilerplate language — reference the actual "
        "hazard numbers, demand figures, and Pass 1 projects given to you."
    )

    user_prompt = (
        f"Citizen Redressal Fund available (40% of Total Revenue Ceiling): "
        f"{fmt_npr(remaining_budget['amount'])}\n\n"
        f"What Pass 1 (Strategic) Already Funded This Cycle "
        f"(read this before deciding anything below):\n{strategic_summary_text}\n\n"
        f"Mayor's Policy Directive:\n{st.session_state.policy_directive}\n\n"
        f"Ward Geographic / Hazard Profiles "
        f"({'LIVE Open-Meteo data' if hazard_is_live else 'fallback baseline — live API unavailable'}):\n"
        f"{geo_summary_text}\n\n"
        f"Aggregate Citizen Demand This Cycle (from Bajet Niti Karyakram "
        f"Sambandhi Sujhav Sankalan submissions):\n{demand_summary_text}\n\n"
        f"Ingested Memos:\n{memo_summaries}\n\n"
        f"Open Complaints (each must be funded or deferred):\n{complaint_summaries}\n\n"
        f"Begin the Tactical Pass now."
    )

    messages = [{"role": "user", "content": user_prompt}]
    max_turns = 25
    turn = 0

    try:
        while turn < max_turns:
            turn += 1
            response = create_with_retry(
            client, retries=1,
                model=MODEL_NAME,
                max_tokens=1500,
                system=system_prompt,
                tools=TACTICAL_TOOLS,
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
                    trace.append(f"🔍 [TACTICAL] get_remaining_budget → {fmt_npr(remaining_budget['amount'])}")

                elif block.name == "fund_project":
                    args = block.input
                    cid = args.get("complaint_id")
                    amount = float(args.get("amount", 0))
                    c = complaints_by_id.get(cid)

                    if c is None:
                        result_text = json.dumps({"error": f"Unknown complaint_id {cid}"})
                        trace.append(f"⚠️ [TACTICAL] fund_project failed — unknown complaint {cid}")
                    elif amount > remaining_budget["amount"]:
                        result_text = json.dumps({
                            "error": "Amount exceeds remaining budget",
                            "remaining_budget": remaining_budget["amount"],
                        })
                        trace.append(
                            f"⚠️ [TACTICAL] fund_project rejected for {cid} — requested "
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
                            "pool": "Tactical",
                        })
                        c["status"] = "Budget Concluded"
                        c["funded"] = True
                        c["ai_reason"] = justification
                        logs.append(f"[ALERT] {cid} status -> Budget Concluded — FUNDED ({fmt_npr(amount)})")
                        trace.append(f"✅ [TACTICAL] fund_project({cid}) → {project_name} — {fmt_npr(amount)}")
                        result_text = json.dumps({"success": True, "remaining_budget": remaining_budget["amount"]})

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
                        trace.append(f"⏸️ [TACTICAL] defer_complaint({cid}) — {reason[:80]}")
                        result_text = json.dumps({"success": True})
                    else:
                        result_text = json.dumps({"error": f"Unknown complaint_id {cid}"})

                elif block.name == "finish_allocation":
                    closing_note = block.input.get("closing_note", "")
                    trace.append(f"🏁 [TACTICAL] finish_allocation — {closing_note}")
                    finished = True
                    result_text = json.dumps({"success": True})

                else:
                    result_text = json.dumps({"error": "unknown tool"})

                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})

            messages.append({"role": "user", "content": tool_results})
            if finished:
                break

        for c in open_complaints:
            if c["status"] != "Budget Concluded":
                c["status"] = "Budget Concluded"
                c["funded"] = False
                c["ai_reason"] = "Not reached by the Tactical Pass within the turn limit; deferred for the next cycle."
                logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (turn limit)")
                trace.append(f"⏸️ [TACTICAL] safety-net defer_complaint({c['id']}) — turn limit reached")

        return "ai", projects, trace, logs

    except Exception as exc:
        fallback_source, fallback_projects, fallback_trace, fallback_logs = run_fallback_tactical_pass(strategic_projects)
        fallback_trace.insert(0, f"⚠️ Live AI Tactical Pass failed ({exc}) — falling back to simulation.")
        return fallback_source, fallback_projects, fallback_trace, fallback_logs


def run_fallback_tactical_pass(strategic_projects=None):
    """Deterministic simulation used when no API key is configured or the
    live call fails. Clearly logged as fallback mode — never presented as AI.
    Still reflects the Pass 1 -> Pass 2 handoff: a complaint is skipped if a
    strategic project already covers the same ward+sector combination."""
    strategic_projects = strategic_projects or []
    covered_ward_sectors = {(p["ward"], p["sector"]) for p in strategic_projects}

    projects = []
    logs = []
    trace = ["⚠️ FALLBACK MODE — no live AI backend; Tactical Pass using seeded simulation logic."]
    remaining_budget = redressal_fund_amount()
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
            trace.append(f"⏸️ [fallback-TACTICAL] excluded {c['id']} (manual override)")
            continue

        if (c["ward"], c["sector"]) in covered_ward_sectors:
            c["status"] = "Budget Concluded"
            c["funded"] = False
            c["ai_reason"] = (
                f"[Fallback] Deferred — Pass 1 (Strategic) already funded a "
                f"{c['sector']} project in {c['ward']} this cycle; avoiding "
                f"redundant spend from the Citizen Redressal Fund."
            )
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (covered by Strategic Pass)")
            trace.append(f"⏸️ [fallback-TACTICAL] defer {c['id']} — already covered by Pass 1 in {c['ward']}")
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
                "pool": "Tactical",
            })
            c["status"] = "Budget Concluded"
            c["funded"] = True
            c["ai_reason"] = justification
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — FUNDED ({fmt_npr(proposed_amount)})")
            trace.append(f"✅ [fallback-TACTICAL] fund {c['id']} — {fmt_npr(proposed_amount)}")
        else:
            c["status"] = "Budget Concluded"
            c["funded"] = False
            c["ai_reason"] = (
                "Deferred due to conditional federal grant restrictions and "
                "insufficient remaining Citizen Redressal Fund for this cycle."
            )
            logs.append(f"[ALERT] {c['id']} status -> Budget Concluded — DEFERRED (insufficient reserve)")
            trace.append(f"⏸️ [fallback-TACTICAL] defer {c['id']} — insufficient reserve")

    return "fallback", projects, trace, logs


def run_two_pass_allocation_engine():
    """
    Orchestrator: runs the Strategic Pass (60% fund) first, then hands its
    completed output to the Tactical Pass (40% fund) as real context — this
    is the actual agent-to-agent collaboration: Pass 2 reasons about what
    Pass 1 already decided before making its own decisions. Combines both
    outputs into st.session_state.projects (each row tagged with a 'pool'),
    and merges their traces/logs. Returns a dict summarizing what ran.
    """
    strategic_source, strategic_projects, strategic_trace, strategic_logs = run_strategic_pass()
    tactical_source, tactical_projects, tactical_trace, tactical_logs = run_tactical_pass(strategic_projects)

    st.session_state.projects = strategic_projects + tactical_projects
    st.session_state.logs.extend(strategic_logs + tactical_logs)
    st.session_state.trace_log.extend(strategic_trace + tactical_trace)

    return {
        "strategic_source": strategic_source,
        "tactical_source": tactical_source,
        "strategic_count": len(strategic_projects),
        "tactical_count": len(tactical_projects),
    }




# --------------------------------------------------------------------------
# AGENT 3 — INDEPENDENT AUDITOR & FAIRNESS AGENT
# --------------------------------------------------------------------------
FAIRNESS_TOOL = {
    "name": "report_fairness_findings",
    "description": "Report fairness/conflict findings after comparing manual overrides "
                    "and final allocation decisions against objective citizen demand data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "complaint_id": {"type": "string"},
                        "ward": {"type": "string"},
                        "sector": {"type": "string"},
                        "severity": {"type": "string", "enum": ["Critical", "Moderate", "Low"]},
                        "finding": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                    "required": ["complaint_id", "ward", "sector", "severity", "finding", "recommendation"],
                },
            },
            "overall_assessment": {"type": "string"},
        },
        "required": ["conflicts", "overall_assessment"],
    },
}


def run_fairness_audit():
    """
    Agent 3. Runs AFTER the allocation engine. Compares the final decisions
    — including manual official overrides — against the objective citizen
    demand data, and raises Conflict Flags for anything that looks like a
    high-need ward/sector was starved to fund a lower-priority one.
    """
    client = get_client()
    complaints = st.session_state.complaints
    demand_text, _ = citizen_demand_summary()

    decisions_text = "\n".join(
        f"- {c['id']} | Ward: {c['ward']} | Sector: {c['sector']} | "
        f"Severity Score: {c.get('severity_score', 'n/a')}/10 | "
        f"Manual Override: {c['override_include']} | "
        f"Outcome: {'FUNDED' if c['funded'] else ('DEFERRED/REJECTED' if c['funded'] is False else 'PENDING')} | "
        f"Admin note: {c['admin_response'] or '(none)'}"
        for c in complaints
    )

    if client is None:
        return run_fallback_fairness_audit()

    try:
        response = create_with_retry(
            client, retries=1,
            model=MODEL_NAME,
            max_tokens=1200,
            tools=[FAIRNESS_TOOL],
            tool_choice={"type": "tool", "name": "report_fairness_findings"},
            messages=[{
                "role": "user",
                "content": (
                    "You are the Independent Auditor and Fairness Agent for Nagarain "
                    "Municipality's capital budget. Compare the final allocation "
                    "decisions (including any manual official overrides) against the "
                    "objective citizen demand data. Flag any case where a high-severity, "
                    "high-demand ward or sector was excluded, deferred, or underfunded "
                    "in favor of a lower-priority one — especially where a manual "
                    "override (not the allocation agent) caused it. If nothing looks "
                    "unfair, return an empty conflicts array and say so plainly in "
                    "overall_assessment.\n\n"
                    f"Aggregate Citizen Demand:\n{demand_text}\n\n"
                    f"Final Allocation Decisions:\n{decisions_text}\n\n"
                    "Run the audit now."
                ),
            }],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "report_fairness_findings":
                return {"source": "ai", **block.input}
        return run_fallback_fairness_audit()
    except Exception:
        return run_fallback_fairness_audit()


def run_fallback_fairness_audit():
    """Deterministic heuristic used when no live AI backend is available:
    flags any complaint manually excluded (override_include == 'No')
    despite being High Priority and unresolved 7+ days."""
    conflicts = []
    for c in st.session_state.complaints:
        if c["override_include"] == "No" and c["priority"] == "High Priority" and c["days_unresolved"] >= 7:
            conflicts.append({
                "complaint_id": c["id"],
                "ward": c["ward"],
                "sector": c["sector"],
                "severity": "Critical",
                "finding": (
                    f"{c['id']} is a High Priority complaint (severity "
                    f"{c.get('severity_score', 'n/a')}/10) unresolved for "
                    f"{c['days_unresolved']} days, but was manually excluded via "
                    f"admin override rather than evaluated by the allocation agent."
                ),
                "recommendation": "Review this override decision before finalizing the budget.",
            })
    assessment = (
        f"[Fallback heuristic] {len(conflicts)} potential conflict(s) found."
        if conflicts else
        "[Fallback heuristic] No obvious conflicts detected between manual overrides and complaint severity."
    )
    return {"source": "fallback", "conflicts": conflicts, "overall_assessment": assessment}


# --------------------------------------------------------------------------
# HELLO SARKAR HAND-OFF
# --------------------------------------------------------------------------
def render_hello_sarkar_redirect(c):
    """
    Show the prepared complaint packet plus two real forwarding routes:
      1. The official Hello Sarkar grievance portal (gunaso.opmcm.gov.np).
      2. A WhatsApp click-to-chat link to Hello Sarkar's published number
         (+977 985-1145045), pre-filled with the full complaint text.
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
                    severity_score=result.get("severity_score"),
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
                    f"**Priority Flag:** {complaint['priority']} "
                    f"(Severity Score: {complaint['severity_score']}/10)  \n"
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
                    <span class="status-pill {pill_class}">{c['priority']} ({c.get('severity_score','n/a')}/10)</span>
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
            <p>Nagarain Municipality — Multi-Agent Capital Budget Allocation Console</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_col1, top_col2 = st.columns([5, 1])
    with top_col2:
        if st.button("🔒 Log Out"):
            st.session_state.admin_authenticated = False
            st.rerun()

    with st.expander("🧨 Reset Demo Data (start over)", expanded=False):
        st.caption(
            "Wipes all complaints, allocations, audit findings, and financial "
            "inputs back to the seeded 5-complaint starting point. Does not "
            "log you out or touch your API key / admin password."
        )
        confirm_reset = st.checkbox("Yes, I understand this deletes all current demo data.")
        if st.button("🔄 Reset Everything to Default", disabled=not confirm_reset):
            reset_to_default_state()
            st.session_state.flash_success = "🔄 Demo data reset to the default starting state."
            st.rerun()

    # Show a flash message left over from a previous rerun (e.g. after
    # applying engineer revisions), then clear it so it doesn't repeat.
    if st.session_state.get("flash_success"):
        st.success(st.session_state.flash_success)
        st.session_state.flash_success = None

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

    # --- 60/40 Fund Split dashboard ---
    s1, s2 = st.columns(2)
    with s1:
        st.markdown(
            f"""<div class="metric-card"><b>🏛️ Core Strategic Fund (60%)</b><br>
            <span style="font-size:22px;">{fmt_npr(strategic_fund_amount())}</span><br>
            <span style="font-size:13px; color:#6e6656;">Used: {fmt_npr(strategic_allocated())}</span></div>""",
            unsafe_allow_html=True,
        )
    with s2:
        st.markdown(
            f"""<div class="metric-card"><b>🧑‍🤝‍🧑 Citizen Redressal Fund (40%)</b><br>
            <span style="font-size:22px;">{fmt_npr(redressal_fund_amount())}</span><br>
            <span style="font-size:13px; color:#6e6656;">Used: {fmt_npr(tactical_allocated())}</span></div>""",
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
        st.caption(
            f"Automatically split 60/40 before any analysis runs — "
            f"**Core Strategic Fund:** {fmt_npr(strategic_fund_amount())} "
            f"(top-down: master planning, large infrastructure, statutory mandates) | "
            f"**Citizen Redressal Fund:** {fmt_npr(redressal_fund_amount())} "
            f"(bottom-up: complaints, ward requests, Tole feedback)."
        )

        st.session_state.policy_directive = st.text_area(
            "Mayor's Policy Directive",
            value=st.session_state.policy_directive,
            height=90,
            help="This text is fed directly into both allocation passes' prompts — "
                 "changing it changes how the agents reason about funding priority.",
        )

        st.markdown("##### 🧮 Tathya Matrix — Structural Reality Metrics")
        st.caption(
            "These switches represent the municipality's structural reality. The "
            "Strategic Pass agent evaluates them FIRST — e.g. if Hospital Access "
            "is 'No' and Population exceeds 30,000, it autonomously generates a "
            "mandatory hospital construction project from the Core Strategic Fund."
        )
        t1, t2 = st.columns(2)
        with t1:
            st.session_state.total_population = st.number_input(
                "Total Population", min_value=0,
                value=st.session_state.total_population, step=500,
            )
            st.session_state.hospital_access = st.selectbox(
                "Hospital Access", ["Yes", "No"],
                index=0 if st.session_state.hospital_access == "Yes" else 1,
            )
            st.session_state.literacy_rate = st.number_input(
                "Current Literacy Rate (%)", min_value=0.0, max_value=100.0,
                value=float(st.session_state.literacy_rate), step=0.5,
            )
        with t2:
            st.session_state.total_wards_count = st.number_input(
                "Total Wards", min_value=1,
                value=st.session_state.total_wards_count, step=1,
            )
            st.session_state.higher_secondary_access = st.selectbox(
                "Higher Secondary School Access", ["Yes", "No"],
                index=0 if st.session_state.higher_secondary_access == "Yes" else 1,
            )

        active_flags = mandatory_strategic_flags()
        if active_flags:
            st.warning(
                "⚠️ **Active statutory triggers this cycle:** " +
                "; ".join(f["project_name"] for f in active_flags)
            )
        else:
            st.caption("No statutory triggers active with current Tathya Matrix values.")

        if st.button("💾 Save Revenue & Policy Settings"):
            save_state()
            st.success("Saved.")

    # --- MAYOR'S BUDGET BRIEFING (for first-time / new mayors) ---
    with st.expander("🧭 Mayor's Budget Briefing — Read This If You're New", expanded=False):
        st.caption(
            "Every 5 years a new mayor takes office with no prior experience "
            "building a municipal capital budget. This briefing summarizes, in "
            "plain language, the two things that should drive allocation "
            "decisions this cycle — LIVE hazard risk and what citizens are "
            "actually asking for — before you touch a single number."
        )

        st.markdown("##### 🗺️ Ward Hazard Profile")
        hazard_col1, hazard_col2 = st.columns([4, 1])
        with hazard_col2:
            if st.button("🔄 Refresh Live Hazard Data"):
                st.session_state.hazard_cache = {}
                st.rerun()

        geo_text, hazard_live = ward_profile_summary()
        if hazard_live:
            st.markdown(
                """<span class="status-pill pill-live">🟢 Live Open-Meteo Data</span>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """<span class="status-pill pill-fallback">🟠 Static Fallback (live API unavailable)</span>""",
                unsafe_allow_html=True,
            )
        st.caption(
            "Terrain/infrastructure descriptions and ward coordinates are "
            "illustrative demo placeholders — a real deployment would use "
            "verified municipal GIS/DRR/census data. The precipitation "
            "numbers above, however, are fetched live from Open-Meteo "
            "(api.open-meteo.com), a free, keyless weather API."
        )

        ward_rows = []
        for ward, p in WARD_PROFILES.items():
            hz = fetch_ward_hazard(ward)
            ward_rows.append({
                "Ward": ward,
                "Terrain": p["terrain"],
                "7-Day Precip (mm)": hz["precip_7day_mm"] if hz["source"] == "live" else "n/a",
                "Peak Rain Prob. (%)": hz["max_precip_probability"] if hz["source"] == "live" else "n/a",
                "Baseline Flood Risk": p["flood_risk"],
                "Est. Population": p["population_estimate"],
                "Infrastructure Notes": p["existing_infra_notes"],
            })
        st.dataframe(pd.DataFrame(ward_rows), use_container_width=True, hide_index=True)

        st.markdown("##### 📣 What Citizens Are Asking For This Cycle")
        demand_text, demand_data = citizen_demand_summary()
        if demand_data:
            dcol1, dcol2 = st.columns(2)
            with dcol1:
                st.markdown("**By Sector**")
                sector_df = pd.DataFrame(
                    [{"Sector": k, "Severity-Weighted Signal": v} for k, v in
                     sorted(demand_data["by_sector"].items(), key=lambda x: -x[1])]
                )
                st.dataframe(sector_df, use_container_width=True, hide_index=True)
            with dcol2:
                st.markdown("**By Ward**")
                ward_demand_df = pd.DataFrame(
                    [{"Ward": k, "Severity-Weighted Signal": v} for k, v in
                     sorted(demand_data["by_ward"].items(), key=lambda x: -x[1])]
                )
                st.dataframe(ward_demand_df, use_container_width=True, hide_index=True)
            st.caption(
                "This is exactly what the Context-Aware Allocation Agent in Step "
                "4 sees and reasons over alongside the live hazard table above."
            )
        else:
            st.caption("No citizen suggestions submitted yet this cycle.")

    # --- STEP 2 ---
    with st.expander("📄 Step 2: Ingest Memos & Dhyanakarshan Letters", expanded=False):
        st.caption(
            "Upload a text/PDF memo, or a PHOTO of a memo/petition/ward-assembly "
            "minute sheet — photos are read by the Ingestion Agent's vision model "
            "for real OCR extraction, not a placeholder."
        )
        uploaded_memo = st.file_uploader(
            "Upload a memo (PDF/TXT) or a photo of a paper memo (JPG/PNG)",
            type=["pdf", "txt", "jpg", "jpeg", "png"], key="memo_uploader",
        )
        col_src, col_type = st.columns(2)
        with col_src:
            memo_source = st.text_input(
                "Source Entity (used if OCR is unavailable, or to override it)",
                placeholder="e.g. Ward 2 Youth Club",
            )
        with col_type:
            memo_type = st.selectbox(
                "Document Type (used if OCR is unavailable, or to override it)",
                ["Dhyanakarshan Letter", "Policy Memo", "Petition", "Ward Assembly Minutes"],
            )

        if st.button("📥 Ingest Uploaded Memo", key="ingest_memo_btn"):
            if uploaded_memo is not None:
                is_image = uploaded_memo.type in ("image/jpeg", "image/png", "image/jpg")
                ocr_result = None
                if is_image:
                    with st.spinner("Ingestion Agent is reading the photographed memo..."):
                        ocr_result = ai_extract_memo_from_image(
                            uploaded_memo.getvalue(), uploaded_memo.type
                        )

                if ocr_result is not None:
                    st.session_state.memos.append({
                        "source": ocr_result.get("source_entity") or memo_source or "Unspecified Entity",
                        "doc_type": ocr_result.get("document_type", memo_type),
                        "demand": ocr_result.get("extracted_demand", ""),
                    })
                    save_state()
                    st.success(
                        f"🟢 Live AI OCR extracted this memo from "
                        f"'{uploaded_memo.name}' (detected language: "
                        f"{ocr_result.get('detected_language', 'n/a')})."
                    )
                else:
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
                    if is_image:
                        st.warning(
                            "🟠 Live OCR unavailable (no API key or call failed) — "
                            "used placeholder extraction instead. Fill in Source "
                            "Entity/Document Type manually for accuracy."
                        )
                    else:
                        st.success(f"Memo '{uploaded_memo.name}' ingested (placeholder text extraction for PDF/TXT).")
            else:
                st.warning("Please attach a file before ingesting.")

        st.markdown("#### Active Memorandums")
        st.caption(
            "These memos are passed directly into the Allocation Agent's prompt "
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
            "agent's behavior under real budget scarcity, rather than only the 5 seeded demo cases."
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
                # No explicit st.rerun() here — Streamlit already reruns
                # naturally after a button click, and calling st.rerun()
                # immediately after st.success() would cut the success
                # banner off before it ever renders to the browser.

        st.markdown("---")

        if not st.session_state.complaints:
            st.caption("No public suggestions filed yet.")
        else:
            for c in st.session_state.complaints:
                st.markdown(
                    f"""
                    <div class="complaint-card">
                        <b>{c['id']}</b> — {c['sector']} — {c['ward']} ({c['language']}) &nbsp;
                        <span class="status-pill {'pill-high' if c['priority']=='High Priority' else 'pill-standard'}">{c['priority']} ({c.get('severity_score','n/a')}/10)</span>
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

    # --- STEP 4 — AGENT 2: CONTEXT-AWARE ALLOCATION AGENT ---
    with st.expander("🤖 Step 4: Context-Aware Allocation Agent (Two-Pass)", expanded=True):
        ai_live, ai_error = verify_ai_live()
        mode_pill = "pill-live" if ai_live else "pill-fallback"
        mode_label = "🟢 Live AI Agents (Claude tool-use loops)" if ai_live else "🟠 Fallback Simulation"
        st.markdown(f"""<span class="status-pill {mode_pill}">{mode_label}</span>""", unsafe_allow_html=True)
        if not ai_live and ai_error and ai_error != "No API key configured.":
            st.caption(f"⚠️ Key is configured but not authenticating: {ai_error}")
        st.write("")
        st.write(
            "**Pass 1 (Strategic):** evaluates the Tathya Matrix and the Mayor's "
            "policy directive first, funding mandatory statutory projects and "
            "master-planning priorities from the 60% Core Strategic Fund.\n\n"
            "**Pass 2 (Tactical):** takes the remaining 40% Citizen Redressal Fund "
            "and matches it against live ward hazard data, citizen demand, and "
            "individual complaints — turn by turn, via tool calls. The app enforces "
            "both hard fund ceilings; the agents decide everything within them."
        )

        if st.button("🚀 Compile and Run Two-Pass AI Budget Allocation Engine", type="primary"):
            with st.spinner("Pass 1 (Strategic) reasoning over the Tathya Matrix and policy directive..."):
                run_summary = run_two_pass_allocation_engine()
            st.session_state.conflict_flags = []
            st.session_state.fairness_assessment = None
            st.session_state.fairness_source = None
            save_state()

            strategic_ok = run_summary["strategic_source"] == "ai"
            tactical_ok = run_summary["tactical_source"] == "ai"
            if strategic_ok and tactical_ok:
                st.success(
                    f"✅ Both passes completed live. Strategic: "
                    f"{run_summary['strategic_count']} project(s). Tactical: "
                    f"{run_summary['tactical_count']} project(s)."
                )
            else:
                pieces = []
                pieces.append("🟢 Strategic live" if strategic_ok else "🟠 Strategic fallback")
                pieces.append("🟢 Tactical live" if tactical_ok else "🟠 Tactical fallback")
                st.warning(f"⚠️ Run completed — {', '.join(pieces)}.")

        if st.session_state.trace_log:
            st.markdown("#### 🧠 Agent Trace (live tool-call log, both passes)")
            for line in st.session_state.trace_log[-40:]:
                st.markdown(f"""<div class="trace-card">{line}</div>""", unsafe_allow_html=True)

        if st.session_state.projects:
            df = pd.DataFrame(
                [
                    {
                        "Fund Pool": p.get("pool", "Tactical"),
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
            st.caption(
                f"Strategic Fund used: {fmt_npr(strategic_allocated())} / "
                f"{fmt_npr(strategic_fund_amount())} &nbsp;|&nbsp; "
                f"Tactical Fund used: {fmt_npr(tactical_allocated())} / "
                f"{fmt_npr(redressal_fund_amount())}"
            )
            st.dataframe(df, use_container_width=True)
        else:
            st.caption("Run the allocation engine to generate the project breakdown table.")

    # --- STEP 5 — AGENT 3: INDEPENDENT AUDITOR & FAIRNESS AGENT ---
    with st.expander("🕵️ Step 5: Independent Auditor & Fairness Review", expanded=False):
        st.write(
            "This agent runs AFTER allocation. It compares the final decisions — "
            "including any manual official overrides from Step 3 — against the "
            "objective citizen demand data, and raises Conflict Flags where a "
            "high-need ward or sector appears to have been starved to fund a "
            "lower-priority one."
        )

        if not st.session_state.projects:
            st.caption("Run Step 4's allocation engine first.")
        else:
            if st.button("🔍 Run Independent Fairness Audit", type="primary"):
                with st.spinner("Auditor agent is comparing overrides against citizen demand data..."):
                    result = run_fairness_audit()
                st.session_state.conflict_flags = result["conflicts"]
                st.session_state.fairness_assessment = result["overall_assessment"]
                st.session_state.fairness_source = result["source"]
                st.session_state.logs.append(
                    f"[AUDIT] Fairness audit completed ({result['source']}) — "
                    f"{len(result['conflicts'])} conflict(s) found."
                )
                save_state()

            if st.session_state.fairness_assessment:
                audit_pill = "pill-live" if st.session_state.fairness_source == "ai" else "pill-fallback"
                audit_label = "🟢 Live AI Auditor" if st.session_state.fairness_source == "ai" else "🟠 Fallback Heuristic Auditor"
                st.markdown(f"""<span class="status-pill {audit_pill}">{audit_label}</span>""", unsafe_allow_html=True)
                st.write(f"**Overall Assessment:** {st.session_state.fairness_assessment}")

                if st.session_state.conflict_flags:
                    st.markdown("#### 🚩 Conflict Flags")
                    for flag in st.session_state.conflict_flags:
                        severity_pill = {
                            "Critical": "pill-critical", "Moderate": "pill-moderate", "Low": "pill-low",
                        }.get(flag.get("severity", "Low"), "pill-low")
                        st.markdown(
                            f"""
                            <div class="conflict-card">
                                <span class="status-pill {severity_pill}">{flag.get('severity','Low')}</span>
                                <b>&nbsp;{flag.get('complaint_id','')} — {flag.get('ward','')} / {flag.get('sector','')}</b>
                                <br>{flag.get('finding','')}
                                <br><i>Recommendation: {flag.get('recommendation','')}</i>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                else:
                    st.success("No fairness conflicts detected in the current allocation.")

    # --- STEP 6 — AGENT 4: OUTPUT, EXPORT & NOTIFICATION AGENT ---
    with st.expander("📤 Step 6: Output, Export & Notification Agent", expanded=False):
        st.write(
            "Converts the approved budget into government-ready deliverables and "
            "drives citizen notifications, logging a full lifecycle from complaint "
            "ID to allocated Project ID to notification sent."
        )

        if not st.session_state.projects:
            st.caption("Run Step 4's allocation engine first to generate exportable data.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "Fund Pool": p.get("pool", "Tactical"),
                        "Project Name": p["project_name"],
                        "Target Ward": p["ward"],
                        "Target Sector": p["sector"],
                        "Allocated Amount (NPR)": p["amount"],
                        "AI Logic Justification": p["justification"],
                        "Linked Complaint ID": p.get("linked_complaint", ""),
                    }
                    for p in st.session_state.projects
                ]
            )

            if st.session_state.logs:
                with st.container():
                    st.markdown("#### 🔔 System Alert & Lifecycle Logs")
                    for log_line in st.session_state.logs[-20:]:
                        st.text(log_line)

            # --- Download engine: try Excel, fall back to CSV ---
            st.markdown("#### 📊 Export Allocation Sheet")
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
                                "linked_complaint": row.get("Linked Complaint ID", ""),
                                "pool": row.get("Fund Pool", "Tactical"),
                            })
                        st.session_state.projects = updated_projects
                        st.session_state.logs.append(
                            "[ALERT] Master dashboard synced with planning engineer's "
                            "manually revised allocation sheet (human-in-the-loop validation)."
                        )
                        save_state()
                        st.session_state.flash_success = "✅ Master stats dashboard updated from the revised sheet."
                        # Still rerun here (unlike the Step 3 case) because
                        # the Step 4 allocation table and fund totals above
                        # were already rendered earlier in this same
                        # top-to-bottom script pass, using the OLD projects
                        # list — without a rerun they'd stay stale. The
                        # flash_success pattern shows the message on the
                        # NEXT render instead of right before a rerun, so it
                        # survives to be seen.
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not parse the uploaded file: {exc}")

            # --- Finalize, publish, and notify ---
            st.markdown("#### 📢 Finalize, Publish & Notify")
            if st.session_state.budget_published:
                st.success("✅ This budget has already been finalized, published, and citizens notified.")
            else:
                if st.button("📢 Finalize and Publish Budget", type="primary"):
                    st.session_state.budget_published = True
                    st.session_state.logs.append(
                        "[ALERT] Budget finalized and published — public notifications unlocked."
                    )
                    notified = 0
                    for c in st.session_state.complaints:
                        if c["status"] == "Budget Concluded":
                            project = next(
                                (p for p in st.session_state.projects if p.get("linked_complaint") == c["id"]),
                                None,
                            )
                            project_id = project["project_name"] if project else "(none — deferred)"
                            st.session_state.logs.append(
                                f"[LIFECYCLE] {c['id']} -> Project '{project_id}' -> "
                                f"notification available on citizen's Live Transparency Matrix."
                            )
                            notified += 1
                    save_state()
                    st.balloons()
                    st.success(
                        f"🎉 Budget finalized and published! {notified} citizen(s) can now "
                        f"see their outcome in the Public Citizen Portal, and can forward "
                        f"unsuccessful complaints to Hello Sarkar via WhatsApp."
                    )


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------
def main():
    inject_css()
    init_session_state()

    st.sidebar.markdown("## 🏛️ Bajet Sunuwai")
    st.sidebar.markdown("**बजेट सुनुवाई**")
    st.sidebar.caption("Multi-agent AI civic-budget platform — Nagarain Municipality")
    st.sidebar.markdown("---")

    ai_live, ai_error = verify_ai_live()
    ai_pill = "🟢 Live AI Backend" if ai_live else "🟠 Fallback Simulation Mode"
    st.sidebar.markdown(f"**AI Status:** {ai_pill}")
    if not ai_live:
        if ai_error and ai_error != "No API key configured.":
            st.sidebar.caption(f"⚠️ Key present but not authenticating: {ai_error}")
        else:
            st.sidebar.caption(
                "Set ANTHROPIC_API_KEY (env var or .streamlit/secrets.toml) to enable "
                "the live Ingestion, Allocation, and Auditor agents."
            )
        if st.sidebar.button("🔄 Re-check AI Connection"):
            verify_ai_live(force=True)
            st.rerun()
    st.sidebar.caption(
        "Hazard data: Open-Meteo (free, keyless) — always live regardless of "
        "the Anthropic API status above."
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
