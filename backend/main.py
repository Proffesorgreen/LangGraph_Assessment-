"""
backend/main.py — FastAPI server for the Support-Ticket Router.

Exposes the LangGraph agent over REST so a browser UI can:
  - Submit a ticket  (POST /api/tickets)
  - Poll its state   (GET  /api/tickets/{thread_id})
  - Resume at HITL   (POST /api/tickets/{thread_id}/resume)
  - List all tickets (GET  /api/tickets)

Run from the project root:
    uvicorn backend.main:app --reload
"""

import os
import sys
import uuid
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Resolve project root so we can import tools, mock_data, db_setup ─────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import TypedDict

from tools import classify_intent, lookup_account, decide_action
from db_setup import init_db

DB_PATH     = os.path.join(ROOT, "support_tickets.db")
FRONTEND    = os.path.join(ROOT, "frontend")

# ═══════════════════════════════════════════════════════════════════════════
# 1. STATE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

class TicketState(TypedDict):
    message:      str
    customer_id:  str
    intent:       Optional[str]
    confidence:   Optional[float]
    source:       Optional[str]
    account_info: Optional[dict]
    action:       Optional[str]
    reason:       Optional[str]


# ═══════════════════════════════════════════════════════════════════════════
# 2. GRAPH NODES
# ═══════════════════════════════════════════════════════════════════════════

def classify_node(state: TicketState) -> dict:
    result = classify_intent(state["message"])
    return {
        "intent":     result["intent"],
        "confidence": result["confidence"],
        "source":     result.get("source", "keyword"),
    }

def lookup_node(state: TicketState) -> dict:
    result = lookup_account(state["customer_id"])
    return {"account_info": dict(result)}

def decide_node(state: TicketState) -> dict:
    # If a human override was already injected, nothing to do
    if state.get("action") and state.get("reason"):
        return {}
    result = decide_action(
        intent      = state["intent"],
        confidence  = state["confidence"],
        account_info= state["account_info"],
    )
    return {"action": result["action"], "reason": result["reason"]}

def output_node(state: TicketState) -> dict:
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 3. GRAPH BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_graph(checkpointer: SqliteSaver):
    builder = StateGraph(TicketState)
    builder.add_node("classify", classify_node)
    builder.add_node("lookup",   lookup_node)
    builder.add_node("decide",   decide_node)
    builder.add_node("output",   output_node)
    builder.add_edge(START,      "classify")
    builder.add_edge("classify", "lookup")
    builder.add_edge("lookup",   "decide")
    builder.add_edge("decide",   "output")
    builder.add_edge("output",   END)
    return builder.compile(checkpointer=checkpointer, interrupt_before=["decide"])


# ═══════════════════════════════════════════════════════════════════════════
# 4. IN-MEMORY TICKET STORE  (resets on server restart)
# ═══════════════════════════════════════════════════════════════════════════

tickets: dict[str, dict] = {}
_lock   = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════
# 5. APP + LIFESPAN
# ═══════════════════════════════════════════════════════════════════════════

_checkpointer: SqliteSaver = None
_graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _checkpointer, _graph
    init_db(DB_PATH)
    conn         = sqlite3.connect(DB_PATH, check_same_thread=False)
    _checkpointer = SqliteSaver(conn)
    _graph        = build_graph(_checkpointer)
    yield
    conn.close()

app = FastAPI(title="Support-Ticket Router", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
# 6. REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════

class SubmitBody(BaseModel):
    customer_id: str
    message:     str

class ResumeBody(BaseModel):
    action: str   # "approve" | "auto-reply" | "escalate" | "request-info"

VALID_ACTIONS = {"approve", "auto-reply", "escalate", "request-info"}


# ═══════════════════════════════════════════════════════════════════════════
# 7. API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/tickets")
def submit_ticket(body: SubmitBody):
    """
    Submit a new support ticket.
    Runs the graph through classify → lookup, then pauses at the HITL
    checkpoint (before decide).  Returns the paused state so the UI
    can show the review panel.
    """
    thread_id = f"ticket-{uuid.uuid4().hex[:8]}"
    config: dict = {"configurable": {"thread_id": thread_id}}

    initial: TicketState = {
        "message":      body.message,
        "customer_id":  body.customer_id,
        "intent":       None,
        "confidence":   None,
        "source":       None,
        "account_info": None,
        "action":       None,
        "reason":       None,
    }

    # Run until interrupt_before=["decide"]
    for _ in _graph.stream(initial, config, stream_mode="values"):
        pass

    paused = _graph.get_state(config)
    vals   = paused.values

    # Compute a preview recommendation (non-destructive — doesn't run the node)
    preview = decide_action(
        intent      = vals.get("intent"),
        confidence  = vals.get("confidence"),
        account_info= vals.get("account_info", {}),
    )

    entry = {
        "thread_id":           thread_id,
        "customer_id":         body.customer_id,
        "message":             body.message,
        "status":              "pending_review",
        "intent":              vals.get("intent"),
        "confidence":          vals.get("confidence"),
        "source":              vals.get("source"),
        "account_info":        vals.get("account_info"),
        "recommended_action":  preview["action"],
        "recommended_reason":  preview["reason"],
        "final_action":        None,
        "final_reason":        None,
        "decided_by":          None,
    }

    with _lock:
        tickets[thread_id] = entry

    return entry


@app.get("/api/tickets")
def list_tickets():
    """Return all tickets (newest first)."""
    with _lock:
        return list(reversed(list(tickets.values())))


@app.get("/api/tickets/{thread_id}")
def get_ticket(thread_id: str):
    """Return a single ticket's current state."""
    with _lock:
        if thread_id not in tickets:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return tickets[thread_id]


@app.post("/api/tickets/{thread_id}/resume")
def resume_ticket(thread_id: str, body: ResumeBody):
    """
    Resume the paused graph with a human decision.

    action = "approve"        → let decide_node run normally
    action = "auto-reply" |
             "escalate"      |
             "request-info"  → inject override, skip decide_node
    """
    with _lock:
        if thread_id not in tickets:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket = dict(tickets[thread_id])

    if ticket["status"] == "completed":
        raise HTTPException(status_code=400, detail="Ticket already completed")

    if body.action not in VALID_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid action '{body.action}'. Choose from: {sorted(VALID_ACTIONS)}"
        )

    config: dict  = {"configurable": {"thread_id": thread_id}}
    decided_by    = "agent"

    if body.action == "approve":
        # Resume normally — decide_node runs and produces the final action
        for _ in _graph.stream(None, config, stream_mode="values"):
            pass
    else:
        # Inject the human's choice directly into state, skip decide_node
        decided_by = "human-override"
        _graph.update_state(
            config,
            {
                "action": body.action,
                "reason": (
                    f"Human override: '{body.action}' "
                    f"(agent recommended '{ticket['recommended_action']}')."
                ),
            },
            as_node="decide",
        )
        for _ in _graph.stream(None, config, stream_mode="values"):
            pass

    final = _graph.get_state(config)
    final_action = final.values.get("action")
    final_reason = final.values.get("reason")

    with _lock:
        tickets[thread_id].update({
            "status":       "completed",
            "final_action": final_action,
            "final_reason": final_reason,
            "decided_by":   decided_by,
        })
        return tickets[thread_id]


# ═══════════════════════════════════════════════════════════════════════════
# 8. SERVE FRONTEND
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))
