"""Run record ("künye") for an evaluation output: where, when, with what code and which exact model it ran.

Written next to each results file as <name>.meta.json, so a number in the README can be traced to a machine, a
commit and a model build. Never contains keys: only the model's base URL host is kept.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=ROOT).stdout.strip()  # noqa: S603 - fixed argv
    except Exception:  # noqa: BLE001 - a missing tool leaves the field empty
        return ""


def machine() -> dict:
    info: dict[str, object] = {"os": platform.platform(), "arch": platform.machine(), "python": sys.version.split()[0]}
    if sys.platform == "darwin":
        info["cpu"] = _run("sysctl", "-n", "machdep.cpu.brand_string")
        mem = _run("sysctl", "-n", "hw.memsize")
        info["memory_gb"] = round(int(mem) / 2**30) if mem.isdigit() else None
    elif os.path.exists("/proc/meminfo"):
        with open("/proc/meminfo") as f:
            kb = next((int(line.split()[1]) for line in f if line.startswith("MemTotal")), 0)
        info["memory_gb"] = round(kb / 2**20, 1)
    info["container"] = os.path.exists("/.dockerenv") or bool(os.environ.get("ASTRO_GATEWAY_URL"))
    return info


def code() -> dict:
    commit = _run("git", "rev-parse", "HEAD")
    dirty = bool(_run("git", "status", "--porcelain", "--", "counterfoil", "scripts", "docs/senaryolar"))
    return {"commit": commit or None, "dirty": dirty if commit else None}


def model(cfg) -> dict:
    """The model as the client sees it; for a local Ollama model also its build (digest) and parameters."""
    host = urlparse(cfg.base_url).netloc
    out = {
        "model": cfg.model,
        "endpoint_host": host,
        "temperature": cfg.temperature,
        "seed": cfg.seed,
        "reasoning_effort": getattr(cfg, "reasoning_effort", None),
    }
    if host.startswith(("localhost", "127.0.0.1")):
        base = f"{urlparse(cfg.base_url).scheme}://{host}"
        try:
            out["ollama_version"] = json.load(urllib.request.urlopen(f"{base}/api/version", timeout=5)).get("version")
            req = urllib.request.Request(
                f"{base}/api/show",
                data=json.dumps({"model": cfg.model}).encode(),
                headers={"Content-Type": "application/json"},
            )
            show = json.load(urllib.request.urlopen(req, timeout=10))
            out["parameters"] = show.get("parameters")
            out["family"] = (show.get("details") or {}).get("family")
            out["parameter_size"] = (show.get("details") or {}).get("parameter_size")
            out["quantization"] = (show.get("details") or {}).get("quantization_level")
            tags = json.load(urllib.request.urlopen(f"{base}/api/tags", timeout=5)).get("models", [])
            tag = cfg.model if ":" in cfg.model else f"{cfg.model}:latest"
            out["digest"] = next((m.get("digest") for m in tags if m.get("name") == tag), None)
        except Exception as exc:  # noqa: BLE001 - the run still counts; the record says what it could not see
            out["ollama_error"] = repr(exc)
    elif host.endswith("astropods.ai"):
        out["provider_route"] = "Astro AI Gateway (Astropods) → Amazon Bedrock"
    return out


def write(out_path: Path, cfg, args: dict, rail: str) -> Path:
    meta = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "argv": sys.argv[1:],
        "selection": args,
        "rail": rail,
        "machine": machine(),
        "code": code(),
        "model": model(cfg),
    }
    path = out_path.with_suffix(".meta.json")
    path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def finish(out_path: Path, rows: list[dict]) -> None:
    """Add the end time and status counts once the run is over."""
    path = out_path.with_suffix(".meta.json")
    meta = json.loads(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    meta.update(finished_at=datetime.now(UTC).isoformat(timespec="seconds"), rows=len(rows), status=counts)
    path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
