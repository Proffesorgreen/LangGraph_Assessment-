
import json
from tools import classify_intent, lookup_account, decide_action


TOOLS: dict[str, callable] = {
    "classify_intent": classify_intent,
    "lookup_account": lookup_account,
    "decide_action": decide_action,
}


def reason(state: dict) -> dict:
    """
    Inspect the current state and decide which tool to call next.

    Returns:
        {"tool": <name>, "args": {…}}
    """
    observations = state["observations"]

    if "classify_intent" not in observations:
        return {
            "tool": "classify_intent",
            "args": {"message": state["message"]},
            "thought": "I need to classify the customer's message intent first.",
        }

    if "lookup_account" not in observations:
        return {
            "tool": "lookup_account",
            "args": {"customer_id": state["customer_id"]},
            "thought": "Intent classified. Now I need the customer's account history.",
        }

    intent_data = observations["classify_intent"]
    account_data = observations["lookup_account"]
    return {
        "tool": "decide_action",
        "args": {
            "intent": intent_data["intent"],
            "confidence": intent_data["confidence"],
            "account_info": account_data,
        },
        "thought": (
            f"I have intent='{intent_data['intent']}' (conf={intent_data['confidence']}) "
            f"and account info for {account_data.get('name', '?')}. Ready to decide."
        ),
    }


def react_loop(message: str, customer_id: str) -> dict:
    """
    Run the full Reason → Act → Observe loop until a terminal action is taken.

    Returns the final decision dict.
    """
    state = {
        "message": message,
        "customer_id": customer_id,
        "observations": {},
        "done": False,
    }

    step = 0
    print("=" * 70)
    print(f"  TICKET  |  customer={customer_id}")
    print(f"  MESSAGE |  {message}")
    print("=" * 70)

    while not state["done"]:
        step += 1

        action = reason(state)
        tool_name = action["tool"]
        tool_args = action["args"]
        thought = action.get("thought", "")

        print(f"\n--- Step {step}: REASON ---")
        print(f"  Thought : {thought}")
        print(f"  Action  : call {tool_name}({json.dumps(tool_args, indent=2)})")

        tool_fn = TOOLS[tool_name]
        result = tool_fn(**tool_args)

        state["observations"][tool_name] = result
        print(f"  Observe : {json.dumps(result, indent=2)}")

        if tool_name == "decide_action":
            state["done"] = True

    final = state["observations"]["decide_action"]
    print("\n" + "=" * 70)
    print(f"  ✅ DECISION: {final['action'].upper()}")
    print(f"  Reason    : {final['reason']}")
    print("=" * 70 + "\n")
    return final


if __name__ == "__main__":
    from mock_data import TEST_TICKETS

    print("\n🔁  Part 1 — Raw Python ReAct Loop (Support-Ticket Router)\n")

    for i, ticket in enumerate(TEST_TICKETS, 1):
        print(f"\n{'#' * 70}")
        print(f"# TEST TICKET {i}")
        print(f"{'#' * 70}")
        result = react_loop(ticket["message"], ticket["customer_id"])
