"""
part2_langgraph.py — LangGraph agent for the Support-Ticket Router.

Upgrades over the original version:
  - SQLite checkpointer (SqliteSaver) — state persists across restarts
  - Gemini LLM for classify_intent (keyword fallback if key missing)
  - lookup_account reads from SQLite DB (with lru_cache)
  - Real human-in-the-loop: terminal prompt lets reviewer approve OR override
    the recommended action before the graph commits it

Run:
    python part2_langgraph.py

Set your API key first (optional — keyword fallback fires if missing):
    $env:GEMINI_API_KEY = "your-key-here"   # PowerShell
    set GEMINI_API_KEY=your-key-here        # CMD
"""

import os
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from tools import classify_intent, lookup_account, decide_action

DB_PATH = os.path.join(os.path.dirname(__file__), "support_tickets.db")

# ═══════════════════════════════════════════════════════════════════════════
# 1. STATE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

class TicketState(TypedDict):
    message:      str
    customer_id:  str
    intent:       Optional[str]
    confidence:   Optional[float]
    source:       Optional[str]   # "gemini" or "keyword"
    account_info: Optional[dict]
    action:       Optional[str]
    reason:       Optional[str]


# ═══════════════════════════════════════════════════════════════════════════
# 2. GRAPH NODES
# ═══════════════════════════════════════════════════════════════════════════

def classify_node(state: TicketState) -> dict:
    """Node 1 — classify message intent via Gemini (or keyword fallback)."""
    print("\n  [classify] Classifying message intent...")
    result = classify_intent(state["message"])
    src = result.get("source", "keyword")
    print(f"     -> intent={result['intent']}, confidence={result['confidence']}  ({src})")
    return {
        "intent":     result["intent"],
        "confidence": result["confidence"],
        "source":     src,
    }


def lookup_node(state: TicketState) -> dict:
    """Node 2 — look up customer account from SQLite (cached)."""
    print("\n  [lookup] Querying customer account from DB...")
    cache_before = lookup_account.cache_info()
    result = lookup_account(state["customer_id"])
    cache_after = lookup_account.cache_info()
    hit = cache_after.hits > cache_before.hits
    tag = "[CACHE HIT]" if hit else "[DB QUERY ]"
    print(f"     {tag} tier={result.get('tier')}, "
          f"open_tickets={result.get('open_tickets')}, "
          f"past_escalations={result.get('past_escalations')}")
    return {"account_info": result}


def decide_node(state: TicketState) -> dict:
    """
    Node 3 — rule-based routing decision.
    Respects a human override already written into state['action'].
    """
    # Human may have injected an override via update_state()
    if state.get("action") and state.get("reason"):
        print(f"\n  [decide] Using human override: {state['action'].upper()}")
        return {}   # state already has action + reason — nothing to change

    print("\n  [decide] Computing routing decision...")
    result = decide_action(
        intent=state["intent"],
        confidence=state["confidence"],
        account_info=state["account_info"],
    )
    print(f"     -> action={result['action']}")
    print(f"     -> reason={result['reason']}")
    return {"action": result["action"], "reason": result["reason"]}


def output_node(state: TicketState) -> dict:
    """Node 4 — terminal node, display final decision."""
    print("\n  " + "=" * 60)
    print(f"  DECISION : {state['action'].upper()}")
    print(f"  Reason   : {state['reason']}")
    print("  " + "=" * 60)
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 3. BUILD THE GRAPH
# ═══════════════════════════════════════════════════════════════════════════

def build_graph(checkpointer):
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

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["decide"],
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. HITL HELPER — real terminal interaction
# ═══════════════════════════════════════════════════════════════════════════

VALID_ACTIONS = {"auto-reply", "escalate", "request-info"}


def hitl_checkpoint(graph, config: dict) -> None:
    """
    Pause at the HITL checkpoint.
    Show the human a preview of the recommended action.
    Accept 'approve' or an explicit override action.
    """
    state = graph.get_state(config)
    acct  = state.values.get("account_info", {})

    # Compute preview recommendation (non-destructive — does NOT run the node)
    preview = decide_action(
        intent      = state.values.get("intent"),
        confidence  = state.values.get("confidence"),
        account_info= acct,
    )

    print("\n" + "~" * 62)
    print("  HUMAN-IN-THE-LOOP CHECKPOINT")
    print(f"  Graph paused before : {state.next}")
    print(f"  Intent              : {state.values.get('intent')}  "
          f"(confidence={state.values.get('confidence')}, "
          f"source={state.values.get('source')})")
    print(f"  Customer            : {acct.get('name', '?')}  |  "
          f"tier={acct.get('tier')}  |  "
          f"open_tickets={acct.get('open_tickets')}  |  "
          f"past_escalations={acct.get('past_escalations')}")
    print(f"  Recommended action  : {preview['action'].upper()}")
    print(f"  Reason              : {preview['reason']}")
    print("~" * 62)

    while True:
        raw = input(
            "\n  Type 'approve' to accept, or override "
            "[auto-reply / escalate / request-info]: "
        ).strip().lower()

        if raw == "approve":
            print("  -> Approved. Resuming graph...")
            # Resume normally — decide_node will run and produce the action
            for _ in graph.stream(None, config, stream_mode="values"):
                pass
            break

        elif raw in VALID_ACTIONS:
            print(f"  -> Human override: {raw.upper()}. Injecting into state...")
            # Write override directly into state AS IF decide_node already ran.
            # This advances the graph cursor past 'decide' to 'output'.
            graph.update_state(
                config,
                {"action": raw, "reason": f"Human override — agent recommended '{preview['action']}'."},
                as_node="decide",
            )
            for _ in graph.stream(None, config, stream_mode="values"):
                pass
            break

        else:
            print(f"  Invalid input '{raw}'. "
                  "Enter 'approve', 'auto-reply', 'escalate', or 'request-info'.")


# ═══════════════════════════════════════════════════════════════════════════
# 5. RUN ONE TICKET
# ═══════════════════════════════════════════════════════════════════════════

def run_ticket(graph, message: str, customer_id: str, thread_id: str) -> None:
    config: dict = {"configurable": {"thread_id": thread_id}}
    initial: TicketState = {
        "message":      message,
        "customer_id":  customer_id,
        "intent":       None,
        "confidence":   None,
        "source":       None,
        "account_info": None,
        "action":       None,
        "reason":       None,
    }

    print("\n" + "=" * 62)
    print(f"  TICKET   | customer={customer_id}  thread={thread_id}")
    print(f"  MESSAGE  | {message}")
    print("=" * 62)

    # Phase 1 — run up to the interrupt
    print("\n  Phase 1: classify -> lookup  (pausing before decide)...")
    for _ in graph.stream(initial, config, stream_mode="values"):
        pass

    # Phase 2 — real HITL interaction
    hitl_checkpoint(graph, config)


# ═══════════════════════════════════════════════════════════════════════════
# 6. MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from mock_data import TEST_TICKETS
    from db_setup import init_db

    # Ensure the DB and schema exist
    init_db()

    print("\n  Part 2 — LangGraph Agent (Support-Ticket Router)")
    print("  SQLite checkpointer | Gemini classify | Real HITL\n")

    # SqliteSaver persists graph state to disk — survives process restarts
    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_graph(checkpointer)

        for i, ticket in enumerate(TEST_TICKETS, 1):
            print(f"\n{'#' * 62}")
            print(f"#  TEST TICKET {i}")
            print(f"{'#' * 62}")
            run_ticket(
                graph,
                message     = ticket["message"],
                customer_id = ticket["customer_id"],
                thread_id   = f"ticket-{i}",
            )

            sep = input("\n  Press Enter for next ticket (or Ctrl-C to quit)...")
            if sep.lower() == "q":
                break

    print("\n  Done. Cache stats:", lookup_account.cache_info())
