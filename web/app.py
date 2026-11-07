"""The Quiet Page demo server.

Live mode (DEMO_MODEL set to a counterfoil.llm preset, e.g. "vultr", plus that preset's key): every case and the
"try to fool it" form run for real: the model writes the parser, the sandbox runs it, the gate decides.
Replay mode (no DEMO_MODEL): the fixed cases answer with recorded real runs from web/replays/, labelled as such,
so the page still works when no key is configured. The drills never need a model and always run live when Docker
is available.

Run: uvicorn web.app:app --port 8000   (from the repo root)
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from counterfoil.evidence import Receipt, verify
from counterfoil.llm import LLM, preset
from counterfoil.pipeline import run_case
from counterfoil.rail import SandboxRail
from counterfoil.sandbox import docker_available, run_extractor, runtime_name
from counterfoil.gateway import APPROVAL, Gateway
from counterfoil.scenarios import build, load_scenarios

from .cases import BOX_DEMO_CODE, BOX_DEMO_TEXT, CASES, DRILLS, FOOL_PRESETS, TRICK_GOAL

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
REPLAYS = ROOT / "replays"
SCENARIOS = {s["id"]: s for s in load_scenarios()}

MODEL = os.environ.get("DEMO_MODEL", "")
RATE = int(os.environ.get("DEMO_RATE_LIMIT", "6"))  # live runs per IP per window
WINDOW_S = int(os.environ.get("DEMO_RATE_WINDOW_S", "600"))
DAILY = int(os.environ.get("DEMO_DAILY_RUNS", "300"))  # live model runs per day, all visitors together
BOX_RATE = int(os.environ.get("DEMO_BOX_RATE_LIMIT", "30"))  # sandbox-only runs (drills, box demo) per IP per window
MAX_FIELD = 4000
# Which payment rail approved refunds hit: "braintree" (the real Braintree sandbox; needs BRAINTREE_* keys) or the
# simulated rail. The page names the rail that actually ran, never the other one.
RAIL = "braintree" if os.environ.get("DEMO_RAIL") == "braintree" else "simulated"

app = FastAPI(title="The Quiet Page", docs_url=None, redoc_url=None)
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
_box_hits: dict[str, deque] = defaultdict(deque)
_day = {"date": time.strftime("%Y-%m-%d"), "runs": 0}
_receipts: OrderedDict[str, dict] = OrderedDict()  # last 200 receipts, for download
_run_lock = threading.Semaphore(2)  # at most two sandboxes at once on a small VM


def _llm() -> LLM | None:
    return LLM(preset(MODEL)) if MODEL else None


def _client_ip(req: Request) -> str:
    return req.client.host if req.client else "?"


def _charge_quota(ip: str) -> None:
    now = time.time()
    with _lock:
        if _day["date"] != time.strftime("%Y-%m-%d"):
            _day.update(date=time.strftime("%Y-%m-%d"), runs=0)
        q = _hits[ip]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= RATE:
            raise HTTPException(429, f"Slow down: {RATE} live runs per {WINDOW_S // 60} minutes.")
        if _day["runs"] >= DAILY:
            raise HTTPException(429, "Today's live runs are used up; the recorded runs still work.")
        q.append(now)
        _day["runs"] += 1


def _charge_box_quota(ip: str) -> None:
    """Drills and the box demo cost no model tokens, only a short-lived container, so they get their own, looser
    per-IP limit and don't eat into the visitor's model runs or the daily model budget."""
    now = time.time()
    with _lock:
        q = _box_hits[ip]
        while q and now - q[0] > WINDOW_S:
            q.popleft()
        if len(q) >= BOX_RATE:
            raise HTTPException(429, f"Slow down: {BOX_RATE} sandbox runs per {WINDOW_S // 60} minutes.")
        q.append(now)


def _keep(receipt: dict) -> None:
    with _lock:
        _receipts[receipt["run_id"]] = receipt
        while len(_receipts) > 200:
            _receipts.popitem(last=False)


def _run(llm, sc: dict, email: dict, hostile_code: str | None = None):
    store, rail, ctx = build(sc)
    # the session's customer comes from the envelope sender: an address that is no customer of the café (Inkwell's
    # billing address) gets no verified customer, so the POS refuses any write in that session
    sender = str(email.get("from") or "").lower()
    if sender and sender not in {str(c.get("email", "")).lower() for c in store.records.get("customers", [])}:
        ctx.customer_id = None
    if RAIL == "braintree":
        rail = SandboxRail(store, run_tag=f"qp-{int(time.time())}")
    res = run_case(llm, sc, email=email, hostile_code=hostile_code, rail=rail, store=store, ctx=ctx)
    res.rail_obj = rail  # so the summary can name the real sandbox transactions
    return res


def _rail_txns(res) -> list[dict]:
    """The real Braintree sandbox ids behind a run's money calls (empty on the simulated rail)."""
    rail = getattr(res, "rail_obj", None)
    if not isinstance(rail, SandboxRail):
        return []
    out = []
    for c in rail.money_calls():
        if c[0] == "refund":
            out.append({"kind": "refund", "amount": str(c[2]), "sale": c[3], "id": c[4]})
        elif c[0] == "charge":
            out.append({"kind": "charge", "amount": str(c[2]), "id": c[4] if len(c) > 4 else None})
        elif c[0] == "void":
            out.append({"kind": "void", "sale": c[2]})
    return out


def _summary(res, case_id: str, mode: str, model: str, rail: str = RAIL) -> dict:
    ext = res.extractor
    return {
        "case": case_id,
        "mode": mode,
        "model": model,
        "rail": rail,
        "rail_txns": _rail_txns(res),
        "outcome": res.outcome,
        "sandbox": None if not ext or not ext.result else {
            "events": ext.result.events, "runtime": ext.result.runtime, "limits": ext.result.limits,
            "exit_code": ext.result.exit_code, "duration_s": ext.result.duration_s, "output": ext.result.output,
            "code": ext.code[:6000], "stderr_tail": ext.result.stderr_tail[-800:],
        },
        "steps": [
            {"tool": s["tool"], "args": s["args"], "decision": s["decision"], "rail_state": s["rail_state"],
             "findings": [f for f in s["findings"] if f.get("severity") != "PASS"]}
            for s in res.steps
        ],
        "receipt": res.receipt,
    }


def _scenario_and_email(case: dict) -> tuple[dict, dict]:
    sc = SCENARIOS[case["scenario"]]
    email = copy.deepcopy(sc["email"])
    email.update(case.get("email_patch", {}))
    return sc, email


@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": "live" if MODEL else "replay", "model": MODEL or None, "rail": RAIL,
            "sandbox_runtime": runtime_name(), "docker": docker_available()}


@app.get("/api/cases")
def cases():
    out = []
    for cid, c in CASES.items():
        sc, email = _scenario_and_email(c)
        out.append({"id": cid, "title": c["title"], "story": c["story"], "drill": c.get("drill"),
                    "email": {k: email.get(k) for k in ("from", "subject", "body_text", "attachment_text")},
                    "drill_code": DRILLS[c["drill"]][1] if c.get("drill") else None,
                    "has_replay": (REPLAYS / f"{cid}.json").exists(),
                    "trick": bool(c.get("trick")), "goal": TRICK_GOAL.get(cid),
                    "attempt": SCENARIOS[c["scenario"]]["preconditions"]["target_attempt"] if c.get("trick") else None})
    return {"mode": "live" if MODEL else "replay", "model": MODEL or None, "cases": out}


@app.post("/api/run/{case_id}")
def run(case_id: str, request: Request):
    case = CASES.get(case_id)
    if not case:
        raise HTTPException(404, "unknown case")
    sc, email = _scenario_and_email(case)
    drill = case.get("drill")
    if drill:  # no model involved: always live
        if not docker_available():
            raise HTTPException(503, "The sandbox needs Docker on this host.")
        _charge_box_quota(_client_ip(request))
        with _run_lock:
            res = _run(None, sc, email, hostile_code=DRILLS[drill][1])
        _keep(res.receipt)
        return _summary(res, case_id, "live", "none (fixed hostile code)")
    if not MODEL:
        f = REPLAYS / f"{case_id}.json"
        if not f.exists():
            raise HTTPException(404, "no recorded run for this case and no live model configured")
        data = json.loads(f.read_text())
        _keep(data["receipt"])
        return data
    _charge_quota(_client_ip(request))
    with _run_lock:
        res = _run(_llm(), sc, email)
    _keep(res.receipt)
    return _summary(res, case_id, "live", MODEL)


@app.post("/api/box-demo")
def box_demo(request: Request):
    """Run a known-good parser on a plain invoice in a fresh sandbox container. No model, no money: this only shows
    the box working (limits, output, the container removed afterwards)."""
    if not docker_available():
        raise HTTPException(503, "The sandbox needs Docker on this host.")
    _charge_box_quota(_client_ip(request))
    with _run_lock:
        r = run_extractor(BOX_DEMO_CODE, BOX_DEMO_TEXT, timeout_s=8)
    return {"code": BOX_DEMO_CODE, "input": BOX_DEMO_TEXT, "ok": r.ok, "output": r.output, "events": r.events,
            "runtime": r.runtime, "limits": r.limits, "duration_s": r.duration_s, "container": r.container,
            "exit_code": r.exit_code, "code_sha256": r.code_sha256, "output_sha256": r.output_sha256}


@app.get("/api/replay/{case_id}")
def replay(case_id: str):
    """A recorded real run, read-only (no quota, no receipt kept): the story steps use it to show what the agents
    did without starting a run."""
    if case_id not in CASES:
        raise HTTPException(404, "unknown case")
    f = REPLAYS / f"{case_id}.json"
    if not f.exists():
        raise HTTPException(404, "no recorded run for this case")
    return json.loads(f.read_text())


class FoolIt(BaseModel):
    subject: str = Field("", max_length=300)
    body_text: str = Field("", max_length=MAX_FIELD)
    attachment_text: str = Field("", max_length=MAX_FIELD)


def _fool_email(subject: str, body_text: str, attachment_text: str) -> dict:
    email = copy.deepcopy(SCENARIOS["CLEAN-01"]["email"])
    email.update(subject=subject or email["subject"], body_text=body_text, attachment_text=attachment_text or None,
                 body_html=None)
    return email


def _preset_of(payload: FoolIt) -> str | None:
    norm = lambda t: " ".join((t or "").split())  # noqa: E731
    for pid, p in FOOL_PRESETS.items():
        if all(norm(getattr(payload, k)) == norm(p[k]) for k in ("subject", "body_text", "attachment_text")):
            return pid
    return None


@app.get("/api/fool-presets")
def fool_presets():
    return {"presets": [{"id": k, **v, "has_replay": (REPLAYS / f"fool-{k}.json").exists()} for k, v in FOOL_PRESETS.items()],
            "mode": "live" if MODEL else "replay"}


@app.post("/api/fool-it")
def fool_it(payload: FoolIt, request: Request):
    """The visitor writes the email; the order, return record and books are those of scenario CLEAN-01
    (a 30.00 USD refund open on ST-1042). Can they get the agents to move more, or move it elsewhere?
    Without a live model, an unedited ready-made attempt answers with its recorded run."""
    if not MODEL:
        pid = _preset_of(payload)
        f = REPLAYS / f"fool-{pid}.json" if pid else None
        if f and f.exists():
            data = json.loads(f.read_text())
            _keep(data["receipt"])
            return data
        raise HTTPException(503, "The live model is not configured on this host; the ready-made attempts still work.")
    _charge_quota(_client_ip(request))
    sc = SCENARIOS["CLEAN-01"]
    email = _fool_email(payload.subject, payload.body_text, payload.attachment_text)
    with _run_lock:
        res = _run(_llm(), sc, email)
    _keep(res.receipt)
    return _summary(res, "fool-it", "live", MODEL)


def _gate_for(sc: dict, handoff: dict | None):
    """A fresh POS over the scenario's books, on the rail this server uses."""
    store, rail, ctx = build(sc)
    if RAIL == "braintree":
        rail = SandboxRail(store, run_tag=f"qp-{int(time.time())}")
    if handoff is not None:
        ctx.reader = handoff
    return Gateway(store, rail), ctx, rail


def _step(tool: str, args: dict, out) -> dict:
    return {"tool": tool, "args": args, "decision": out.decision, "rail_state": out.rail_state,
            "findings": [f.__dict__ for f in out.findings if f.severity != "PASS"]}


class HartDecision(BaseModel):
    run_id: str = Field(..., max_length=100)
    decision: str = Field(..., pattern="^(approve|refuse)$")


@app.post("/api/hart")
def hart(payload: HartDecision, request: Request):
    """Mrs. Hart decides on a held call. No model is involved: the held call is read from the run's receipt, handed
    to a fresh POS over the same books (which holds it again, for the same reasons), and her decision goes through
    the gate's own approve/reject. An approval is single-use and re-checked; only then does the rail run. Both the
    decision and the result are appended to the run's receipt."""
    rec = _receipts.get(payload.run_id)
    if not rec:
        raise HTTPException(404, "This run's receipt has expired on the server; run the case again.")
    held = next((e for e in reversed(rec["entries"]) if e["step"] == "gate" and e["data"].get("decision") == APPROVAL), None)
    if held is None or any(e["step"] == "human" for e in rec["entries"]):
        raise HTTPException(409, "Nothing in this run is waiting for Mrs. Hart.")
    sid = (next((e for e in rec["entries"] if e["step"] == "email"), {}).get("data") or {}).get("scenario")
    if sid not in SCENARIOS:
        raise HTTPException(409, "Unknown scenario for this run.")
    handoff = (next((e for e in rec["entries"] if e["step"] == "reader"), {}).get("data") or {}).get("handoff")
    _charge_box_quota(_client_ip(request))
    tool, args = held["data"]["tool"], dict(held["data"]["args"])
    gate, ctx, rail = _gate_for(SCENARIOS[sid], handoff)
    with _run_lock:
        first = gate.handle(ctx, tool, args)
        if first.decision != APPROVAL:  # the books say something else now: report it, decide nothing
            raise HTTPException(409, f"The POS no longer holds this call ({first.decision}).")
        if payload.decision == "approve":
            out = gate.approve(first.approval_id)
        else:
            gate.reject(first.approval_id)
            out = None
    r = Receipt(run_id=rec["run_id"], entries=[dict(e) for e in rec["entries"]])
    r.add("human", {"who": "Mrs. Hart", "decision": payload.decision, "tool": tool, "args": args,
                    "saw": [f.code for f in first.findings if f.severity == APPROVAL]})
    step = None
    if out is not None:
        step = _step(tool, args, out)
        r.add("gate", {**step, "human_approved": True})
    receipt = r.to_dict()
    _keep(receipt)
    txns = []
    if isinstance(rail, SandboxRail):
        fake = type("R", (), {"rail_obj": rail})()
        txns = _rail_txns(fake)
    return {"decision": payload.decision, "step": step, "rail": RAIL, "rail_txns": txns, "receipt": receipt}


@app.post("/api/pos-direct/{case_id}")
def pos_direct(case_id: str, request: Request):
    """Assume Milo himself is turned: the attacker's exact call goes straight to the POS, no model in between.
    Deterministic and live; nothing is executed unless the POS passes it (none of these do)."""
    case = CASES.get(case_id)
    if not case or not case.get("trick"):
        raise HTTPException(404, "unknown trick")
    _charge_box_quota(_client_ip(request))
    sc = SCENARIOS[case["scenario"]]
    a = dict(sc["preconditions"]["target_attempt"])
    tool = a.pop("tool")
    a = {k: v for k, v in a.items() if v is not None and k != "braintree_transaction_id"}
    gate, ctx, _rail = _gate_for(sc, sc["preconditions"].get("reader_contract"))
    with _run_lock:
        out = gate.handle(ctx, tool, a)
    return {"case": case_id, "step": _step(tool, a, out), "expected": sc["expected_gateway_decision"]}


@app.get("/api/receipt/{run_id}")
def receipt(run_id: str):
    r = _receipts.get(run_id)
    if not r:
        raise HTTPException(404, "receipt expired or unknown")
    return JSONResponse(r, headers={"Content-Disposition": f'attachment; filename="{run_id}.receipt.json"'})


@app.post("/api/verify")
async def verify_receipt(request: Request):
    try:
        data = await request.json()
    except ValueError as e:
        raise HTTPException(400, "not JSON") from e
    ok, broken = verify(data)
    return {"intact": ok, "first_broken_entry": broken}


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    page = STATIC / "index.html"
    if not page.exists():
        return JSONResponse({"hint": "web/static/index.html not built yet", "api": ["/api/cases", "/healthz"]})
    return FileResponse(page)
