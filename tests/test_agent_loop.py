"""The transaction agent's loop with a scripted fake LLM: budgets, malformed arguments, stop-after-hold."""

import json
from types import SimpleNamespace

from counterfoil.agents import read_email, run_transaction_agent
from counterfoil.gateway import Gateway
from counterfoil.scenarios import build, load_scenarios

BY_ID = {s["id"]: s for s in load_scenarios()}


def call(i, name, args):
    raw = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(
        id=f"c{i}",
        function=SimpleNamespace(name=name, arguments=raw),
        model_dump=lambda: {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": raw}},
    )


class ScriptedLLM:
    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def chat(self, messages, tools=None, json_mode=False):
        self.seen.append(messages)
        if not self.turns:
            return SimpleNamespace(content="done", tool_calls=None)
        t = self.turns.pop(0)
        if isinstance(t, Exception):
            raise t
        if isinstance(t, str):
            return SimpleNamespace(content=t, tool_calls=None)
        return SimpleNamespace(content="", tool_calls=t)


def setup(sid):
    store, rail, ctx = build(BY_ID[sid])
    return Gateway(store, rail), rail, ctx


REFUND = {"order_no": "ST-1042", "rma_id": "RMA-1042", "amount": "30.00", "currency": "USD"}


def test_call_budget_counts_tool_calls_not_turns():
    gw, rail, ctx = setup("CLEAN-01")
    llm = ScriptedLLM([[call(i, "lookup_transaction", {"order_no": "ST-1042"}) for i in range(9)]])
    run = run_transaction_agent(llm, gw, ctx, ctx.reader, max_turns=1, max_calls=3)
    assert len(run.steps) == 3 and run.stopped == "call_budget"


def test_malformed_arguments_never_reach_the_gate():
    gw, rail, ctx = setup("CLEAN-01")
    llm = ScriptedLLM([[call(0, "refund", "{not json")], "ok"])
    run = run_transaction_agent(llm, gw, ctx, ctx.reader)
    assert run.steps[0].decision == "PARSE_ERROR" and run.parse_errors == 1 and not rail.calls and not gw.log


def test_held_money_call_ends_the_run_and_skips_the_rest():
    gw, rail, ctx = setup("P1-01")
    held = dict(REFUND, amount="60.00")
    llm = ScriptedLLM([[call(0, "refund", held), call(1, "refund", REFUND)]])
    run = run_transaction_agent(llm, gw, ctx, ctx.reader)
    assert run.stopped == "held_or_blocked" and len(run.steps) == 1 and not rail.money_calls()


def test_model_error_is_recorded_not_raised():
    gw, rail, ctx = setup("CLEAN-01")
    run = run_transaction_agent(ScriptedLLM([RuntimeError("ollama down")]), gw, ctx, ctx.reader)
    assert run.stopped == "model_error" and "ollama down" in run.error


def test_successful_refund_then_answer():
    gw, rail, ctx = setup("CLEAN-01")
    llm = ScriptedLLM(
        [[call(0, "lookup_transaction", {"order_no": "ST-1042"})], [call(1, "refund", REFUND)], "Refunded."]
    )
    run = run_transaction_agent(llm, gw, ctx, ctx.reader)
    assert [s.rail_state for s in run.steps] == ["succeeded", "succeeded"] and run.final_message == "Refunded."


def test_reader_rejects_non_object_output():
    llm = ScriptedLLM(["[1, 2]"])
    handoff, raw = read_email(llm, BY_ID["CLEAN-01"]["email"])
    assert handoff is None and raw == "[1, 2]"


def test_reader_sees_hidden_html():
    llm = ScriptedLLM(["{}"])
    read_email(llm, BY_ID["P1-01"]["email"])
    user = llm.seen[0][1]["content"]
    assert "[HTML part]" in user and "display:none" in user
