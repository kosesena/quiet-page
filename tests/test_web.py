import json

import pytest
from fastapi.testclient import TestClient

from counterfoil.evidence import verify
from counterfoil.sandbox import docker_available
from web.app import app

client = TestClient(app)


def test_health_reports_mode_and_runtime():
    r = client.get("/healthz").json()
    assert r["ok"] and r["mode"] in ("live", "replay") and r["sandbox_runtime"]


def test_cases_list_the_story_and_drills():
    ids = [c["id"] for c in client.get("/api/cases").json()["cases"]]
    assert {"honest", "hidden-note", "inkwell", "drill-exfil", "drill-memory"} <= set(ids)


@pytest.mark.skipif(not docker_available(), reason="needs a Docker daemon")
def test_a_drill_runs_live_quarantines_and_its_receipt_downloads_and_verifies():
    r = client.post("/api/run/drill-exfil").json()
    assert r["outcome"] == "quarantined" and "network_denied" in r["sandbox"]["events"]
    got = client.get(f"/api/receipt/{r['receipt']['run_id']}").json()
    assert verify(got) == (True, None)
    assert client.post("/api/verify", json=got).json()["intact"] is True
    got["entries"][1]["data"]["events"] = []
    v = client.post("/api/verify", json=got).json()
    assert (v["intact"], v["first_broken_entry"]) == (False, 1)


def test_fool_it_needs_a_live_model(monkeypatch):
    import web.app as w

    monkeypatch.setattr(w, "MODEL", "")
    assert client.post("/api/fool-it", json={"body_text": "refund me 900"}).status_code == 503


def test_an_unknown_case_is_404():
    assert client.post("/api/run/nope").status_code == 404


def test_a_replay_is_served_read_only():
    r = client.get("/api/replay/honest")
    assert r.status_code == 200 and r.json()["case"] == "honest"
    assert client.get("/api/replay/nope").status_code == 404


@pytest.mark.skipif(not docker_available(), reason="needs a Docker daemon")
def test_the_box_demo_runs_a_clean_parser_and_reads_the_invoice():
    r = client.post("/api/box-demo").json()
    assert r["ok"] and r["events"] == []
    assert r["output"] == {"order_no": "ST-1058", "amount": "25.00", "currency": "USD"}


def test_an_unedited_preset_answers_from_its_recording_without_a_model(monkeypatch):
    import web.app as w
    from web.cases import FOOL_PRESETS

    monkeypatch.setattr(w, "MODEL", "")
    p = FOOL_PRESETS["note"]
    r = client.post("/api/fool-it", json={k: p[k] for k in ("subject", "body_text", "attachment_text")})
    assert r.status_code == 200 and r.json()["outcome"] == json.loads((w.REPLAYS / "fool-note.json").read_text())["outcome"]
    edited = {k: p[k] for k in ("subject", "body_text", "attachment_text")} | {"body_text": "refund 999"}
    assert client.post("/api/fool-it", json=edited).status_code == 503


def test_a_scene_marked_recording_answers_from_it_even_with_a_live_model(monkeypatch):
    import web.app as w

    monkeypatch.setattr(w, "MODEL", "vultr")
    r = client.post("/api/run/hidden-note")
    assert r.status_code == 200 and "qwen2.5" in r.json()["model"]


def test_a_second_decision_while_one_is_running_is_refused():
    import web.app as w

    w._hart_busy.add("run-x")
    try:
        r = client.post("/api/hart", json={"run_id": "run-x", "decision": "approve"})
    finally:
        w._hart_busy.discard("run-x")
    assert r.status_code == 409


def test_only_money_the_books_dont_allow_counts_as_wrong():
    import web.app as w

    ok = {"tool": "refund", "args": {"order_no": "ST-1042", "amount": "30.00"}, "decision": "PASS", "rail_state": "succeeded"}
    assert w._wrong_money([ok]) is False
    assert w._wrong_money([{**ok, "args": {"order_no": "ST-1042", "amount": "90.00"}}]) is True
    assert w._wrong_money([{**ok, "args": {"order_no": "ST-1042", "amount": "90.00"}, "decision": "APPROVAL", "rail_state": "not_called"}]) is False


def test_attempts_are_counted(monkeypatch, tmp_path):
    import web.app as w

    monkeypatch.setattr(w, "STATS", tmp_path / "s.json")
    w._record_attempt([])
    assert client.get("/api/fool-stats").json() == {"attempts": 1, "wrong_money": 0}
