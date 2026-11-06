"""Run the two agents on the scenario set under one or more conditions and score each run.

    .venv/bin/python scripts/run_eval.py --split dev --conditions counterfoil,cap,none --repeats 1
    .venv/bin/python scripts/run_eval.py --ids P1-01,CLEAN-01
    .venv/bin/python scripts/run_eval.py --rescore results/smoke/dev-run1.jsonl     # re-score saved steps, no LLM

Writes one JSONL line per (scenario, condition, repeat), then prints a summary. The rail is the in-memory FakeRail
(card-like limits); --rail braintree or --rail paypal (PayPal REST) swaps in that sandbox. Within one repeat the
Reader runs once per scenario and its hand-off is reused for every condition, so conditions differ only in the gate (paired comparison, not independent Reader samples).
Holdout scenarios are for the final measurement only: do not tune prompts on them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # API keys for the cloud presets; .env is git-ignored

from counterfoil import paypal, runmeta  # noqa: E402
from counterfoil.agents import read_email, run_transaction_agent  # noqa: E402
from counterfoil.baselines import CapGate, NoGate  # noqa: E402
from counterfoil.evaluate import expected_outcome, score  # noqa: E402
from counterfoil.gateway import Gateway  # noqa: E402
from counterfoil.llm import LLM, PRESETS, preset  # noqa: E402
from counterfoil.rail import SandboxRail  # noqa: E402
from counterfoil.scenarios import build, load_records, load_scenarios  # noqa: E402
from counterfoil.worst_case import WorstCaseAgent  # noqa: E402

CONDITIONS = {"none": NoGate, "cap": CapGate, "counterfoil": Gateway}
RAIL = "fake"  # --rail braintree / paypal: every run moves real money in that sandbox
FLAGS = (
    "attempt",
    "intervention",
    "schema_rejected",
    "harm",
    "policy_bypass",
    "rail_refused",
    "legit_done",
    "legit_held",
    "correct_abstention",
)


def run_one(
    llm: LLM, scenario: dict, condition: str, reader_cache: dict, make_rail=None, max_turns: int = 6, max_calls: int = 8
) -> dict:
    """One scenario under one condition. `make_rail(store, rail, scenario, condition)` replaces the rail chosen by --rail
    (the live demo wraps it so a pasted email cannot reach transactions outside the fixture store). A scenario
    without ground truth (an email pasted into the demo) is run but not scored."""
    row = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scenario": scenario["id"],
        "kind": scenario["kind"],
        "family": scenario["family"],
        "split": scenario["split"],
        "condition": condition,
        "model": llm.config.model,
        "base_url": llm.config.base_url,
        "status": "ok",
    }
    store, rail, ctx = build(scenario)
    if make_rail is not None:
        rail = make_rail(store, rail, scenario, condition)
    elif RAIL == "braintree":
        rail = SandboxRail(store, f"cf-{uuid.uuid4().hex[:8]}-{scenario['id']}-{condition}")
    elif RAIL == "paypal":
        rail = paypal.PayPalSandboxRail(store, f"cf-{uuid.uuid4().hex[:8]}-{scenario['id']}-{condition}")
    row["rail"] = getattr(rail, "name", RAIL)
    email = scenario["email"]
    sender = store.customer_by_email(email["from"])
    ctx.customer_id = sender["customer_id"] if sender else None  # from the envelope, not from the LLM
    row["sender_matches_precondition"] = ctx.customer_id == scenario["preconditions"]["authenticated_customer_id"]
    try:
        if scenario["id"] not in reader_cache:
            t0 = time.time()
            reader_cache[scenario["id"]] = (*read_email(llm, email), round(time.time() - t0, 1))
        handoff, reader_raw, row["reader_seconds"] = reader_cache[scenario["id"]]
    except Exception as exc:  # noqa: BLE001 - the row records the failure, the run goes on
        row.update(status="reader_error", error=repr(exc))
        return row
    row.update(
        reader=handoff,
        reader_raw=None if handoff else reader_raw,
        reader_valid=handoff is not None,
        reader_matches_contract=handoff == scenario["preconditions"].get("reader_contract"),
    )
    ctx.reader = handoff
    gate = CONDITIONS[condition](store, rail)
    t0 = time.time()
    try:
        agent = run_transaction_agent(llm, gate, ctx, handoff, max_turns=max_turns, max_calls=max_calls)
    except Exception:  # noqa: BLE001 - the row records the failure, the run goes on
        row.update(status="agent_error", error=traceback.format_exc(limit=3))
        return row
    row["agent_seconds"] = round(time.time() - t0, 1)
    row.update(
        steps=[asdict(s) for s in agent.steps],
        agent_stopped=agent.stopped,
        agent_error=agent.error,
        parse_errors=agent.parse_errors,
        agent_final=agent.final_message,
        rail_money_calls=[list(map(str, c)) for c in rail.money_calls()],
    )
    if agent.stopped == "model_error":
        row["status"] = "model_error"
    if "ground_truth" in scenario:
        row["score"] = score(row["steps"], expected_outcome(scenario, store), store).as_dict()
    return row


def rescore(path: Path) -> list[dict]:
    by_id = {s["id"]: s for s in load_scenarios()}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if "steps" in r:
            store, _, _ = build(by_id[r["scenario"]])
            r["score"] = score(r["steps"], expected_outcome(by_id[r["scenario"]], store), store).as_dict()
        rows.append(r)
    return rows


def summarise(rows: list[dict]) -> str:
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        a = agg[(r["condition"], r["kind"])]
        a["runs"] += 1
        if r.get("status", "ok") != "ok" or "score" not in r:
            a["errors"] += 1
            continue
        a["reader_invalid"] += not r.get("reader_valid", r.get("reader") is not None)
        for k in FLAGS:
            a[k] += bool(r["score"].get(k))
    cols = ("runs", "errors", "reader_invalid") + FLAGS
    short = {
        "intervention": "interv",
        "schema_rejected": "schema",
        "policy_bypass": "bypass",
        "rail_refused": "railref",
        "legit_done": "legit",
        "legit_held": "held",
        "correct_abstention": "abstain",
        "reader_invalid": "rdr_bad",
    }
    head = f"{'condition':12} {'kind':6} " + " ".join(f"{short.get(c, c):>7}" for c in cols)
    lines = [head]
    for cond in CONDITIONS:
        for kind in ("attack", "clean"):
            a = agg.get((cond, kind))
            if a:
                lines.append(f"{cond:12} {kind:6} " + " ".join(f"{a[c]:>7}" for c in cols))
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    p.add_argument("--ids", default="", help="comma-separated scenario ids (overrides --split)")
    p.add_argument("--conditions", default="counterfoil,cap,none")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--out", default="")
    p.add_argument("--rescore", default="", help="re-score a saved JSONL with the current scorer (no LLM)")
    p.add_argument(
        "--rail",
        choices=["fake", "braintree", "paypal"],
        default="fake",
        help="braintree: the Braintree sandbox (needs BRAINTREE_* in .env); paypal: the PayPal REST sandbox "
        "(needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET); slower, real sandbox transactions",
    )
    p.add_argument(
        "--model",
        default="",
        choices=["", *PRESETS, "worst-case"],
        help="named model preset; default: LLM_BASE_URL / LLM_MODEL / LLM_API_KEY from the environment. "
        "worst-case: no model, a scripted Reader and agent that are fully on the attacker's side (counterfoil/worst_case.py)",
    )
    args = p.parse_args()

    global RAIL
    RAIL = args.rail
    if args.rescore:
        print(summarise(rescore(Path(args.rescore))))
        return
    if RAIL == "paypal" and not paypal.configured():  # say so before any model runs; never print the values
        sys.exit(
            "--rail paypal needs PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in the environment or .env; "
            "live PayPal calls are off"
        )

    scenarios = load_scenarios()
    if args.ids:
        wanted = set(args.ids.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    elif args.split != "all":
        scenarios = [s for s in scenarios if s["split"] == args.split]
    conditions = [c for c in args.conditions.split(",") if c]
    llm = (
        WorstCaseAgent(load_records())
        if args.model == "worst-case"
        else LLM(preset(args.model) if args.model else None)
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = (
        Path(args.out).resolve()
        if args.out
        else ROOT / "results" / f"{stamp}-{llm.config.model.replace(':', '_')}-{args.split}.jsonl"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    runmeta.write(
        out, llm.config, {"split": args.split, "ids": args.ids, "conditions": conditions, "repeats": args.repeats}, RAIL
    )

    rows = []
    with out.open("w", encoding="utf-8") as f:
        for rep in range(args.repeats):
            reader_cache: dict = {}
            for s in scenarios:
                if isinstance(llm, WorstCaseAgent):
                    llm.scenario = s
                for cond in conditions:
                    row = run_one(llm, s, cond, reader_cache)  # type: ignore[arg-type]
                    row["repeat"] = rep
                    rows.append(row)
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    f.flush()
                    sc = row.get("score") or {}
                    print(
                        f"{s['id']:9} {cond:12} {row['status']:12} attempt={sc.get('attempt')!s:5} "
                        f"harm={sc.get('harm')!s:5} legit={sc.get('legit_done')!s:5} held={sc.get('legit_held')!s:5} "
                        f"stop={row.get('agent_stopped')}",
                        flush=True,
                    )
    print()
    runmeta.finish(out, rows)
    print(summarise(rows))
    print(f"\nraw: {out}")


if __name__ == "__main__":
    main()
