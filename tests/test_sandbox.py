"""Containment checks against a real container. Skipped where Docker is not available (CI without Docker)."""

import pytest

from counterfoil.sandbox import docker_available, run_extractor

pytestmark = pytest.mark.skipif(not docker_available(), reason="needs a Docker daemon")

TEXT = "INVOICE QP-2041\nTotal: 42.50 USD\n"


def run(code, **kw):
    return run_extractor(code, TEXT, timeout_s=kw.pop("timeout_s", 5), **kw)


def test_a_clean_extractor_returns_its_fields():
    r = run("import re\ndef extract(text):\n    m = re.search(r'Total: ([0-9.]+) (\\w+)', text)\n"
            "    return {'amount': m.group(1), 'currency': m.group(2)}\n")
    assert r.ok and r.events == [] and r.output == {"amount": "42.50", "currency": "USD"}


def test_an_outbound_connection_is_denied():
    r = run("import socket\ndef extract(text):\n    s = socket.socket(); s.settimeout(2)\n"
            "    s.connect(('93.184.216.34', 80))\n    return {}\n")
    assert not r.ok and "network_denied" in r.events


def test_a_dns_lookup_fails_inside_the_box():
    r = run("import urllib.request\ndef extract(text):\n"
            "    urllib.request.urlopen('http://example.com/', timeout=2)\n    return {}\n")
    assert not r.ok and "network_denied" in r.events


def test_writing_outside_tmp_is_refused():
    r = run("def extract(text):\n    open('/job/x', 'w').write('x')\n    return {}\n")
    assert not r.ok and "filesystem_readonly" in r.events


def test_a_memory_bomb_is_killed():
    r = run("def extract(text):\n    a = []\n    while True:\n        a.append(bytearray(10**7))\n")
    assert not r.ok and "memory_limit" in r.events


def test_a_fork_bomb_is_stopped():
    r = run("import os\ndef extract(text):\n    while True:\n        os.fork()\n")
    assert not r.ok and r.events  # pids cap or memory cap, whichever trips first


def test_a_job_that_never_ends_is_killed():
    r = run("import time\ndef extract(text):\n    while True:\n        time.sleep(1)\n", timeout_s=3)
    assert not r.ok and "time_limit" in r.events


def test_a_cpu_spin_is_killed():
    r = run("def extract(text):\n    while True:\n        pass\n", timeout_s=3)
    assert not r.ok and "time_limit" in r.events


def test_no_container_is_left_behind():
    import subprocess

    run("def extract(text):\n    return {}\n")
    left = subprocess.run(["docker", "ps", "-a", "--filter", "name=cf-sbx-", "-q"], capture_output=True, text=True)
    assert left.stdout.strip() == ""
