"""Every scenario's target call, without any LLM, under three conditions.

These are rule tests: they show what each condition does with the call an attacker wants, not whether a real
agent makes that call (that is the agent evaluation).
- Counterfoil must reach the scenario's expected decision, and an attack must not reach the rail at all.
- Clean scenarios that should pass must actually complete on the rail.
- Baselines: the attack reaches the rail exactly when the scenario says neither the rail nor a 200 cap stops it.
"""

import pytest

from counterfoil.baselines import CapGate, NoGate
from counterfoil.gateway import APPROVAL, BLOCK, PASS, Gateway
from counterfoil.scenarios import attempt, build, load_scenarios

SCENARIOS = load_scenarios()
ATTACKS = [s for s in SCENARIOS if s["kind"] == "attack"]
RAIL_TOOLS = {"refund", "charge", "void", "lookup_transaction"}


def run(cls, scenario):
    store, rail, ctx = build(scenario)
    gate = cls(store, rail)
    tool, args = attempt(scenario)
    return gate, rail, ctx, gate.handle(ctx, tool, args)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_counterfoil_decision(scenario):
    *_, out = run(Gateway, scenario)
    assert out.decision == scenario["expected_gateway_decision"], out.summary()
    if out.decision != PASS:
        assert scenario["expected_reason"].split(":")[0] in {f.code for f in out.findings}, out.summary()


@pytest.mark.parametrize("scenario", ATTACKS, ids=lambda s: s["id"])
def test_attack_makes_no_money_call_through_counterfoil(scenario):
    _, rail, _, out = run(Gateway, scenario)
    assert out.rail_state == "not_called" and rail.money_calls() == [], out.summary()


@pytest.mark.parametrize(
    "scenario",
    [s for s in SCENARIOS if s["kind"] == "clean" and s["expected_gateway_decision"] == PASS],
    ids=lambda s: s["id"],
)
def test_clean_request_completes(scenario):
    _, rail, _, out = run(Gateway, scenario)
    assert out.rail_state == "succeeded" and len(rail.money_calls()) == 1, out.summary()


@pytest.mark.parametrize("scenario", ATTACKS, ids=lambda s: s["id"])
def test_baselines_match_scenario_flags(scenario):
    tool = scenario["preconditions"]["target_attempt"]["tool"]
    if tool not in RAIL_TOOLS:
        pytest.skip("no rail endpoint for this tool")
    *_, none = run(NoGate, scenario)
    *_, cap = run(CapGate, scenario)
    assert none.reached_rail == (not scenario["rail_would_block"]), none.summary()
    expect_cap = not scenario["rail_would_block"] and not scenario["cap_200_would_block"]
    assert cap.reached_rail == expect_cap, cap.summary()
    if scenario["cap_200_would_block"]:
        assert cap.decision == APPROVAL


@pytest.mark.parametrize(
    "scenario",
    [s for s in SCENARIOS if "subsequent_money_movement_decision" in s["preconditions"]],
    ids=lambda s: s["id"],
)
def test_money_move_after_blocked_attempt_is_held(scenario):
    gate, _, ctx, out = run(Gateway, scenario)
    assert out.decision == BLOCK
    r = ctx.reader
    order = gate.store.orders[r["siparis_no"]]
    follow = gate.handle(
        ctx,
        "refund",
        {
            "amount": r["tutar"],
            "order_no": order["order_no"],
            "currency": r["para_birimi"],
            "rma_id": r["iade_kaydi_no"],
            "braintree_transaction_id": order["braintree_transaction_id"],
        },
    )
    assert "PRIOR_BLOCKED_ATTEMPT" in {f.code for f in follow.findings}
    assert follow.decision in (APPROVAL, BLOCK) and not follow.reached_rail
