"""Record real runs of the demo's model cases into web/replays/ (used when the server has no live model).

    python scripts/record_replays.py --model qwen2.5        # local Ollama
    python scripts/record_replays.py --model vultr          # Vultr Serverless Inference (needs the key)

Each file says which model produced it and when; the page shows that label, so a replay is never passed off as live.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from counterfoil.llm import LLM, preset  # noqa: E402
from web.app import RAIL, SCENARIOS, _fool_email, _run, _scenario_and_email, _summary  # noqa: E402
from web.cases import CASES, FOOL_PRESETS  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "web" / "replays"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5")
    ap.add_argument("--cases", nargs="*", default=[c for c, v in CASES.items() if not v.get("drill") and not v.get("recording")])
    ap.add_argument("--fool", nargs="*", default=list(FOOL_PRESETS), help="ready-made step-08 attempts to record")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    llm = LLM(preset(a.model))
    for cid in a.cases:
        sc, email = _scenario_and_email(CASES[cid])
        res = _run(llm, sc, email)
        data = _summary(res, cid, "replay", f"{a.model} ({llm.config.model}), recorded {time.strftime('%Y-%m-%d %H:%M')}", RAIL)
        (OUT / f"{cid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))
        print(f"{cid}: {res.outcome}", (res.extractor.result.events if res.extractor and res.extractor.result else ""))
    for pid in a.fool:
        p = FOOL_PRESETS[pid]
        res = _run(llm, SCENARIOS["CLEAN-01"], _fool_email(p["subject"], p["body_text"], p["attachment_text"]))
        data = _summary(res, f"fool-{pid}", "replay", f"{a.model} ({llm.config.model}), recorded {time.strftime('%Y-%m-%d %H:%M')}", RAIL)
        (OUT / f"fool-{pid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))
        money = [s for s in res.steps if s["tool"] in ("refund", "charge", "void")]
        print(f"fool-{pid}: {res.outcome}", [(s["tool"], s["args"].get("amount"), s["decision"]) for s in money])


if __name__ == "__main__":
    main()
