"""Count wrong-money payments per model from the Counterfoil evaluation export (results/counterfoil-dashboard-*.json)
and write web/static/numbers.json for the demo page. "Wrong money" = an attack run whose refund/charge actually
executed with an amount or target the books don't support (the export's `harm` flag). Unfinished runs are not counted.
"""

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = sorted((ROOT / "results").glob("counterfoil-dashboard-*.json"))[-1]
d = json.loads(SRC.read_text())
agg: dict = collections.defaultdict(collections.Counter)
for r in d["runs"]:
    if not r["attackRun"] or "braintree" in r["source"]:
        continue
    split = "holdout" if "holdout" in r["source"] else "dev"
    k = (r["model"], split)
    agg[k][(r["condition"], "n")] += 1
    agg[k][(r["condition"], "harm")] += r["harm"]
rows, tot = [], collections.Counter()
for (model, split), c in sorted(agg.items()):
    n = c[("Counterfoil", "n")]
    rows.append({"model": f"{model} · {split}", "n": n, "ungated": c[("No gate", "harm")], "gated": c[("Counterfoil", "harm")]})
    tot["n"] += n
    tot["ungated"] += c[("No gate", "harm")]
    tot["gated"] += c[("Counterfoil", "harm")]
out = {"rows": rows, "total": dict(tot), "source": SRC.name, "as_of": d["asOf"],
       "note": f"Attack runs per condition, same scenarios and seeds; {len(d['skipped'])} unfinished runs not counted. Source: results/{SRC.name}."}
(ROOT / "web" / "static" / "numbers.json").write_text(json.dumps(out, indent=1))
print(out["total"], len(rows), "rows")
