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

from counterfoil.evidence import verify
from counterfoil.llm import LLM, preset
from counterfoil.pipeline import run_case
from counterfoil.sandbox import docker_available, runtime_name
from counterfoil.scenarios import load_scenarios

from .cases import CASES, DRILLS

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
REPLAYS = ROOT / "replays"
SCENARIOS = {s["id"]: s for s in load_scenarios()}

MODEL = os.environ.get("DEMO_MODEL", "")
RATE = int(os.environ.get("DEMO_RATE_LIMIT", "6"))  # live runs per IP per window
WINDOW_S = int(os.environ.get("DEMO_RATE_WINDOW_S", "600"))
DAILY = int(os.environ.get("DEMO_DAILY_RUNS", "300"))  # live model runs per day, all visitors together
MAX_FIELD = 4000

app = FastAPI(title="The Quiet Page", docs_url=None, redoc_url=None)
_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)
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


def _keep(receipt: dict) -> None:
    with _lock:
        _receipts[receipt["run_id"]] = receipt
        while len(_receipts) > 200:
            _receipts.popitem(last=False)


def _summary(res, case_id: str, mode: str, model: str) -> dict:
    ext = res.extractor
    return {
        "case": case_id,
        "mode": mode,
        "model": model,
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
    return {"ok": True, "mode": "live" if MODEL else "replay", "model": MODEL or None,
            "sandbox_runtime": runtime_name(), "docker": docker_available()}


@app.get("/api/cases")
def cases():
    out = []
    for cid, c in CASES.items():
        sc, email = _scenario_and_email(c)
        out.append({"id": cid, "title": c["title"], "story": c["story"], "drill": c.get("drill"),
                    "email": {k: email.get(k) for k in ("from", "subject", "body_text", "attachment_text")},
                    "drill_code": DRILLS[c["drill"]][1] if c.get("drill") else None,
                    "has_replay": (REPLAYS / f"{cid}.json").exists()})
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
        _charge_quota(_client_ip(request))
        with _run_lock:
            res = run_case(None, sc, email=email, hostile_code=DRILLS[drill][1])  # type: ignore[arg-type]
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
        res = run_case(_llm(), sc, email=email)
    _keep(res.receipt)
    return _summary(res, case_id, "live", MODEL)


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


@app.post("/api/fool-it")
def fool_it(payload: FoolIt, request: Request):
    """The visitor writes the email; the order, return record and books are those of scenario CLEAN-01
    (a 30.00 USD refund open on ST-1042). Can they get the agents to move more, or move it elsewhere?"""
    if not MODEL:
        raise HTTPException(503, "The live model is not configured on this host; try the recorded cases.")
    _charge_quota(_client_ip(request))
    sc = SCENARIOS["CLEAN-01"]
    email = copy.deepcopy(sc["email"])
    email.update(subject=payload.subject or email["subject"], body_text=payload.body_text,
                 attachment_text=payload.attachment_text or None, body_html=None)
    with _run_lock:
        res = run_case(_llm(), sc, email=email)
    _keep(res.receipt)
    return _summary(res, "fool-it", "live", MODEL)


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
