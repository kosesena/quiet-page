"""One email, end to end, with both boundaries and a receipt:

email → [sandbox] Reader-written parser for the attachment → quarantine if the box saw anything
      → Reader hand-off → payments agent → [Counterfoil gate] → rail (fake or Braintree sandbox)

Every step goes into a hash-chained receipt (evidence.py). The receipt is what the demo page offers for download.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from .agents import email_text, read_email, run_transaction_agent
from .evidence import Receipt
from .extractor import ExtractorRun, run_given_code, write_and_run
from .gateway import Gateway
from .llm import LLM
from .scenarios import build

QUARANTINED = "quarantined"


@dataclass
class CaseResult:
    outcome: str  # quarantined | done | held_or_blocked | turn_budget | call_budget | model_error | reader_failed
    receipt: dict
    extractor: ExtractorRun | None
    steps: list[dict]


def run_case(
    llm: LLM,
    scenario: dict,
    *,
    email: dict | None = None,
    hostile_code: str | None = None,
    rail=None,
    store=None,
    ctx=None,
) -> CaseResult:
    """`email` overrides the scenario's email (the demo's "try to fool it" form). `hostile_code` replaces the
    model-written parser with fixed code: the compromised-model drill."""
    store0, rail0, ctx0 = build(scenario)
    store, rail, ctx = store or store0, rail or rail0, ctx or ctx0
    email = email or scenario["email"]
    receipt = Receipt(run_id=f"{scenario['id']}-{uuid.uuid4().hex[:8]}")
    receipt.add("email", {
        "scenario": scenario["id"], "from": email.get("from"), "subject": email.get("subject"),
        "sha256": hashlib.sha256(email_text(email).encode()).hexdigest(),
        "has_attachment": bool(email.get("attachment_text")),
    })

    ext = None
    if email.get("attachment_text"):
        ext = run_given_code(hostile_code, email) if hostile_code else write_and_run(llm, email)
        r = ext.result
        receipt.add("sandbox", {
            "runtime": r.runtime, "limits": r.limits, "events": r.events, "exit_code": r.exit_code,
            "duration_s": r.duration_s, "code_sha256": r.code_sha256, "input_sha256": r.input_sha256,
            "output": r.output, "written_by": "fixed drill code" if hostile_code else "model",
        })
        if ext.quarantined:
            receipt.add("quarantine", {
                "reason": "the parser written for this email tripped the sandbox: " + ", ".join(r.events),
                "payments_agent_called": False,
            })
            return CaseResult(QUARANTINED, receipt.to_dict(), ext, [])

    # what the sandboxed parser really returned goes back to the model, so executed work feeds the hand-off
    parser_output = ext.result.output if ext and ext.result and isinstance(ext.result.output, dict) else None
    handoff, raw = read_email(llm, email, parser_output)
    receipt.add("reader", {"handoff": handoff, "parsed": handoff is not None})
    if handoff is None:
        return CaseResult("reader_failed", receipt.to_dict(), ext, [])
    ctx.reader = handoff
    gate = Gateway(store, rail)
    run = run_transaction_agent(llm, gate, ctx, handoff)
    steps = [s.__dict__ for s in run.steps]
    for s in steps:
        receipt.add("gate", {"tool": s["tool"], "args": s["args"], "decision": s["decision"],
                             "rail_state": s["rail_state"],
                             "findings": [f for f in s["findings"] if f.get("severity") != "PASS"]})
    receipt.add("end", {"stopped": run.stopped, "final_message": run.final_message[:500]})
    return CaseResult(run.stopped, receipt.to_dict(), ext, steps)
