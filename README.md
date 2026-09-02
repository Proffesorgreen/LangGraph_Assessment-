# Support-Ticket Router — ReAct Implementation

Two implementations of the same multi-step problem: **classifying a support ticket, looking up the customer, and routing it**.

## Problem

Given an incoming customer support message:
1. **Classify** the message intent (billing / technical / refund / general)
2. **Look up** the customer's account history (tier, open tickets, past escalations)
3. **Decide** the action: `auto-reply` | `escalate` | `request-info`

## Project Structure

| File | Purpose |
|------|---------|
| `mock_data.py` | Fake customer DB + keyword mappings |
| `tools.py` | 3 shared tools: `classify_intent`, `lookup_account`, `decide_action` |
| `part1_react_raw.py` | **Part 1** — Raw Python ReAct loop (no frameworks) |
| `part2_langgraph.py` | **Part 2** — LangGraph agent (caching + HITL) |

## Setup

```bash
pip install -r requirements.txt
```

> Part 1 has **zero** external dependencies (pure Python).  
> Part 2 requires `langgraph`.

## Running

### Part 1 — Raw Python ReAct Loop

```bash
python part1_react_raw.py
```

You'll see the Reason → Act → Observe loop printed step-by-step for each test ticket.

### Part 2 — LangGraph Agent

```bash
python part2_langgraph.py
```

You'll see:
- The graph nodes executing in order
- A **HITL checkpoint** pause before the `decide` node (simulated human approval)
- **Cache hits** when the same customer is looked up again

## Test Tickets

| # | Customer | Message | Expected Action |
|---|----------|---------|----------------|
| 1 | C001 (free) | Billing double-charge | `auto-reply` |
| 2 | C003 (enterprise, 4 past escalations) | Dashboard 500 error | `escalate` |
| 3 | C004 (pro) | Vague message | `request-info` |

## Key Features

### Part 1 — What it demonstrates
- **Explicit `while` loop** — nothing hidden
- **`TOOLS` dict** of callables
- **`reason()` function** — the agent's policy, deciding which tool to call next
- **Observe** → update state → loop until terminal tool fires

### Part 2 — What it adds
- **`StateGraph`** with typed state schema
- **`interrupt_before=["decide"]`** — HITL checkpoint before the sensitive routing decision
- **`functools.lru_cache`** on `lookup_account` — demonstrates caching
- **`MemorySaver`** checkpointer for state persistence across the interrupt
