"""
mock_data.py — Keyword mappings and test tickets.

The CUSTOMERS dict has moved to SQLite (see db_setup.py).
This module now only contains:
  - INTENT_KEYWORDS  (fallback classifier used when Gemini is unavailable)
  - TEST_TICKETS     (used by both part1_react_raw.py and part2_langgraph.py)
"""

# ---------------------------------------------------------------------------
# Keyword -> intent mapping (order matters -- first match wins)
# ---------------------------------------------------------------------------
INTENT_KEYWORDS = {
    "billing": [
        "bill", "billing", "charge", "charged", "invoice", "payment",
        "subscription", "plan", "upgrade", "downgrade", "price", "cost",
        "receipt", "overcharged", "pricing", "renewal", "renew",
    ],
    "technical": [
        "error", "bug", "crash", "broken", "not working", "down",
        "slow", "timeout", "fail", "500", "404", "login issue",
        "can't access", "cannot access", "outage", "glitch",
        "loading", "freeze", "frozen", "unresponsive", "lag",
    ],
    "refund": [
        "refund", "money back", "cancel", "cancellation", "reimburse",
        "return", "chargeback", "dispute",
    ],
    # "general" is the fallback -- no keywords needed
}

# ---------------------------------------------------------------------------
# Test tickets
# ---------------------------------------------------------------------------
TEST_TICKETS = [
    # 1. Basic billing (free tier) -> auto-reply
    {
        "customer_id": "C001",
        "message": "Hi, I was charged twice for my subscription last month. "
                   "Can you check my billing?",
        "expected": "auto-reply",
    },
    # 2. Technical (enterprise, many escalations) -> escalate
    {
        "customer_id": "C003",
        "message": "Our dashboard is throwing a 500 error again and half the "
                   "team can't access it. This is the second outage this week.",
        "expected": "escalate",
    },
    # 3. Vague message (low confidence) -> request-info
    {
        "customer_id": "C004",
        "message": "Hey there, just wondering about something.",
        "expected": "request-info",
    },
    # 4. Refund request -> always escalate
    {
        "customer_id": "C002",
        "message": "I want a refund for my last payment. The product did not "
                   "work as advertised and I'd like my money back.",
        "expected": "escalate",
    },
    # 5. Technical (pro, many open tickets) -> escalate
    {
        "customer_id": "C006",
        "message": "The export feature keeps crashing every time I click it. "
                   "I've already reported this bug twice before.",
        "expected": "escalate",
    },
    # 6. New enterprise client, billing question -> escalate (enterprise always)
    {
        "customer_id": "C007",
        "message": "Quick question: when does our next invoice go out?",
        "expected": "escalate",
    },
    # 7. Free-tier, 3 past escalations -> escalate
    {
        "customer_id": "C008",
        "message": "My account is frozen and I can't access anything.",
        "expected": "escalate",
    },
    # 8. Pro, simple technical, no history -> auto-reply
    {
        "customer_id": "C009",
        "message": "The page is loading really slowly today, is there an outage?",
        "expected": "auto-reply",
    },
    # 9. Long-standing enterprise, vague -> escalate (enterprise overrides)
    {
        "customer_id": "C010",
        "message": "We need to talk about our account.",
        "expected": "escalate",
    },
    # 10. Unknown customer -> auto-reply (unknown tier treated as free)
    {
        "customer_id": "C999",
        "message": "I'm having trouble with my billing, can someone help?",
        "expected": "auto-reply",
    },
    # 11. Brand-new free account, technical -> auto-reply
    {
        "customer_id": "C005",
        "message": "I just signed up and I'm getting a 404 error on my profile page.",
        "expected": "auto-reply",
    },
    # 12. Mixed billing+refund keywords -> billing wins (keyword order)
    {
        "customer_id": "C004",
        "message": "I was charged for a plan I didn't want. Can I get a "
                   "receipt and maybe cancel?",
        "expected": "auto-reply",
    },
]
