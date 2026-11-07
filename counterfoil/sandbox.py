"""Run model-written code in a throwaway container: no network, read-only filesystem, capped memory/CPU/processes,
a wall-clock limit, no Linux capabilities, an unprivileged user. One container per job, removed afterwards.

On the Vultr VM the container runtime is gVisor (SANDBOX_RUNTIME=runsc), so the code also talks to a user-space
kernel instead of the host's. On a laptop without gVisor the same limits apply with the default runtime (runc).

The code must define `extract(text: str) -> dict`. The runner calls it on the job's input text and prints the result
as JSON. Anything the code tries beyond that (opening a socket, writing outside /tmp, spawning processes, eating
memory, looping forever) either fails inside the box or gets the container killed; the result records which.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.13-slim")
STARTUP_S = float(os.environ.get("SANDBOX_STARTUP_S", "5"))  # container start-up allowance on top of the job limit
MAX_OUTPUT = 64 * 1024  # bytes of stdout kept; a bigger answer is itself a finding

RUNNER = r'''
import json, resource, sys, traceback
# CPU-seconds cap inside the box (the hard limit cannot be raised by an unprivileged process)
resource.setrlimit(resource.RLIMIT_CPU, (__CPU__, __CPU__))
src = open("/job/extractor.py", encoding="utf-8").read()
text = open("/job/input.txt", encoding="utf-8").read()
ns = {}
try:
    exec(compile(src, "extractor.py", "exec"), ns)
    fn = ns.get("extract")
    if not callable(fn):
        raise RuntimeError("extractor.py does not define extract(text)")
    out = fn(text)
    if not isinstance(out, dict):
        raise TypeError(f"extract() returned {type(out).__name__}, not dict")
    sys.stdout.write(json.dumps(out, default=str))
except BaseException as e:
    sys.stderr.write("".join(traceback.format_exception(e)))
    sys.exit(3)
'''

# stderr fragments → the containment event they mean
SIGNATURES = (
    ("network_denied", ("Network is unreachable", "Temporary failure in name resolution", "gaierror",
                        "Name or service not known", "[Errno 101]", "[Errno 99]")),
    ("filesystem_readonly", ("Read-only file system", "[Errno 30]")),
    ("permission_denied", ("Permission denied", "[Errno 13]", "Operation not permitted", "[Errno 1]")),
    ("process_limit", ("Resource temporarily unavailable", "[Errno 11]", "can't start new thread")),
    ("memory_limit", ("MemoryError",)),
)


@dataclass
class SandboxResult:
    ok: bool  # extract() returned a dict and the container exited cleanly
    output: dict | None
    events: list[str]  # containment events, e.g. ["network_denied"]; empty for a clean run
    exit_code: int | None
    duration_s: float
    runtime: str
    limits: dict
    stderr_tail: str = ""
    code_sha256: str = ""
    input_sha256: str = ""
    output_sha256: str = ""
    container: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def contained(self) -> bool:
        return bool(self.events)

    def to_dict(self) -> dict:
        return asdict(self)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def runtime_name() -> str:
    return os.environ.get("SANDBOX_RUNTIME", "runc")


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_extractor(
    code: str,
    text: str,
    *,
    timeout_s: float = 10.0,
    memory: str = "128m",
    cpus: str = "0.5",
    pids: int = 32,
    runtime: str | None = None,
    image: str = IMAGE,
) -> SandboxResult:
    """Run `code` (which defines extract(text)) on `text` inside a fresh locked-down container."""
    runtime = runtime or runtime_name()
    limits = {"network": "none", "memory": memory, "cpus": cpus, "pids": pids, "timeout_s": timeout_s,
              "rootfs": "read-only", "tmpfs": "/tmp 16m noexec", "user": "65534", "capabilities": "none"}
    name = f"cf-sbx-{uuid.uuid4().hex[:12]}"
    job = Path(tempfile.mkdtemp(prefix="cf-job-"))
    try:
        (job / "extractor.py").write_text(code, encoding="utf-8")
        (job / "input.txt").write_text(text, encoding="utf-8")
        (job / "runner.py").write_text(RUNNER.replace("__CPU__", str(max(1, int(timeout_s)))), encoding="utf-8")
        os.chmod(job, 0o755)
        for f in job.iterdir():
            os.chmod(f, 0o644)
        cmd = [
            "docker", "run", "--name", name, "--runtime", runtime,
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--memory", memory, "--memory-swap", memory, "--cpus", cpus, "--pids-limit", str(pids),
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
            "--ulimit", "nofile=64:64", "-v", f"{job}:/job:ro", "-w", "/tmp",
            image, "python", "-I", "-S", "/job/runner.py",
        ]
        t0 = time.monotonic()
        events: list[str] = []
        notes: list[str] = []
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout_s + STARTUP_S)
            exit_code: int | None = p.returncode
            stdout, stderr = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            exit_code, stdout, stderr = None, e.stdout or b"", e.stderr or b""
        duration = time.monotonic() - t0
        if exit_code is None:  # wall-clock limit hit: kill before inspecting so FinishedAt is set
            subprocess.run(["docker", "kill", name], capture_output=True)
        state = _inspect(name)
        if state.get("OOMKilled"):
            events.append("memory_limit")
        run_s = _run_seconds(state)
        if exit_code is None or (run_s is not None and run_s > timeout_s) or exit_code in (152, -24):
            events.append("time_limit")  # 152 = 128+SIGXCPU: the CPU-seconds cap fired
        err = stderr.decode("utf-8", "replace")
        for ev, needles in SIGNATURES:
            if any(n in err for n in needles) and ev not in events:
                events.append(ev)
        if len(stdout) > MAX_OUTPUT:
            events.append("output_limit")
            stdout = stdout[:MAX_OUTPUT]
        output = None
        if exit_code == 0 and not events:
            try:
                output = json.loads(stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                notes.append("stdout was not JSON")
        if exit_code not in (0, None) and not events:
            notes.append("extract() raised; see stderr_tail")
        return SandboxResult(
            ok=output is not None,
            output=output,
            events=events,
            exit_code=exit_code,
            duration_s=round(duration, 3),
            runtime=runtime,
            limits=limits,
            stderr_tail=err[-1500:],
            code_sha256=_sha(code.encode()),
            input_sha256=_sha(text.encode()),
            output_sha256=_sha(stdout),
            container=name,
            notes=notes,
        )
    finally:
        _remove(name)
        shutil.rmtree(job, ignore_errors=True)


def _remove(name: str, attempts: int = 4) -> None:
    """Remove the job's container. A busy Docker daemon can fail one `rm -f`, which would leave a killed (or
    still-running) container behind, so retry until Docker says it is gone."""
    for i in range(attempts):
        try:
            r = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode == 0 or "No such container" in r.stderr:
            return
        time.sleep(0.5 * (i + 1))


def _inspect(name: str) -> dict:
    p = subprocess.run(["docker", "inspect", "--format", "{{json .State}}", name], capture_output=True)
    if p.returncode != 0:
        return {}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {}


def _run_seconds(state: dict) -> float | None:
    from datetime import datetime

    def parse(s: str):
        if not s or s.startswith("0001"):
            return None
        s = s.rstrip("Z")
        main, _, frac = s.partition(".")
        return datetime.fromisoformat(main + ("." + frac[:6] if frac else ""))

    a, b = parse(state.get("StartedAt", "")), parse(state.get("FinishedAt", ""))
    if a and b:
        return (b - a).total_seconds()
    return None
