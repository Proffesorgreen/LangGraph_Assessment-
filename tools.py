"""
tools.py — Shared tool definitions for the Support-Ticket Router.

Three tools:
  1. classify_intent(message)
       Tries Gemini (gemini-2.0-flash) first; falls back to keyword matching
       if GEMINI_API_KEY is not set or the call fails.

  2. lookup_account(customer_id)
       Queries the SQLite customers table (support_tickets.db).
       Falls back gracefully for unknown customer IDs.

  3. decide_action(intent, confidence, account_info)
       Pure rule-based router — unchanged from Part 1.
"""

import os
import json
import sqlite3
import functools

from dotenv import load_dotenv
from mock_data import INTENT_KEYWORDS

# Load .env from the project root (silently ignored if the file doesn't exist)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DB_PATH = os.path.join(os.path.dirname(__file__), "support_tickets.db")


# ── Tool 1: classify_intent ──────────────────────────────────────────────

def _keyword_classify(message: str) -> dict:
    """Keyword fallback classifier."""
    text = message.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            confidence = min(round(0.5 + hits * 0.15, 2), 0.99)
            return {"intent": intent, "confidence": confidence, "source": "keyword"}
    return {"intent": "general", "confidence": 0.30, "source": "keyword"}


def _gemini_classify(message: str) -> dict | None:
    """
    Call Gemini to classify intent.
    Returns None if the API key is missing or the call fails.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = (
            "You are a customer-support classifier.\n"
            "Classify the message below into EXACTLY ONE of:\n"
            "  billing   – charges, invoices, subscriptions, pricing\n"
            "  technical – bugs, errors, crashes, access issues, outages\n"
            "  refund    – refund requests, cancellations, chargebacks\n"
            "  general   – anything else\n\n"
            "Respond with ONLY a JSON object — no markdown, no extra text:\n"
            '{"intent": "<intent>", "confidence": <0.0-1.0>}\n\n'
            f'Message: "{message}"'
        )

        response = model.generate_content(prompt)
        raw = response.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        data["source"] = "gemini"
        return data
    except Exception as exc:
        print(f"    [classify_intent] Gemini call failed ({exc}), using keyword fallback.")
        return None


def classify_intent(message: str) -> dict:
    """
    Classify the customer message's intent.
    Tries Gemini first, falls back to keyword matching.
    """
    result = _gemini_classify(message)
    if result is None:
        result = _keyword_classify(message)
    return result


# ── Tool 2: lookup_account ───────────────────────────────────────────────

@functools.lru_cache(maxsize=128)
def lookup_account(customer_id: str) -> dict:
    """
    Query the SQLite customers table.
    Returns an 'unknown' sentinel for unrecognised customer IDs.
    (lru_cache avoids redundant DB hits for the same ID.)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
        row = cur.fetchone()
        conn.close()

        if row:
            return dict(row)
    except Exception as exc:
        print(f"    [lookup_account] DB error ({exc}), returning unknown sentinel.")

    return {
        "customer_id": customer_id,
        "name": "Unknown",
        "tier": "unknown",
        "open_tickets": 0,
        "past_escalations": 0,
        "account_age_days": 0,
    }


# ── Tool 3: decide_action ────────────────────────────────────────────────

def decide_action(
    intent: str,
    confidence: float,
    account_info: dict,
) -> dict:
    """
    Rule-based router. Returns one of:
        auto-reply / escalate / request-info
    """
    tier = account_info.get("tier", "free")
    open_tickets = account_info.get("open_tickets", 0)
    past_escalations = account_info.get("past_escalations", 0)

    # Low confidence → need more info
    if confidence < 0.45:
        return {
            "action": "request-info",
            "reason": (
                f"Intent confidence is low ({confidence}). "
                "Asking the customer to clarify their request."
            ),
        }

    # Enterprise OR repeat escalator → always escalate
    if tier == "enterprise" or past_escalations >= 3:
        return {
            "action": "escalate",
            "reason": (
                f"Customer is {tier}-tier with {past_escalations} past "
                f"escalation(s) and {open_tickets} open ticket(s). "
                f"Escalating {intent} issue to a human agent."
            ),
        }

    # Refund → always escalate
    if intent == "refund":
        return {
            "action": "escalate",
            "reason": "Refund requests require human review per policy.",
        }

    # Technical with several open tickets → escalate
    if intent == "technical" and open_tickets >= 2:
        return {
            "action": "escalate",
            "reason": (
                f"Repeated technical issue — customer already has "
                f"{open_tickets} open ticket(s). Escalating."
            ),
        }

    # Default → auto-reply
    return {
        "action": "auto-reply",
        "reason": (
            f"Straightforward {intent} query from {tier}-tier customer. "
            "Sending automated response."
        ),
    }
