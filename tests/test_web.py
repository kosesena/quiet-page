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
    assert client.post("/api/verify", json=got).json() == {"intact": False, "first_broken_entry": 1}


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
