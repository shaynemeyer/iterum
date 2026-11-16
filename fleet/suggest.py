"""Suggest a night's budget from the ready tasks, before any of them runs. Reads only.

    iterum budget suggest

Per task added with `iterum add --plan`: "at most", (prompt steps + fix retries) x cap,
since retries count per run (`run_steps()` in fleet/run.py); and "typical", prompt steps x
the median past cost of one prompt step on its model (one claude session's spend.reported).
Retries are left out of "typical". A task added as a plain command has no cost settings.
The cap is Claude Code's client-side estimate, so "at most" is a close bound, not a guarantee.
"""

import json
import math
import statistics
from pathlib import Path

from fleet import db, telemetry

STEP_COSTS = """
SELECT json_extract(payload, '$.model') AS model, SUM(json_extract(payload, '$.cost_usd')) AS usd
FROM events WHERE kind=? AND run_id NOT LIKE 'session-%'
GROUP BY json_extract(payload, '$.session_id')
"""


def step_costs(con):
    """{model: [USD per past prompt step]}, from runs' claude sessions, interactive sessions left out."""
    costs = {}
    for r in con.execute(STEP_COSTS, (telemetry.KIND,)):
        costs.setdefault(r["model"], []).append(r["usd"])
    return costs


def prompt_models(plan):
    """The model of each prompt step in a plan file (None where it names none)."""
    steps = json.loads(Path(plan).read_text())
    return [s[2].get("model") for s in steps if isinstance(s[2], dict)]


def estimate(payload, costs):
    """{"at_most", "typical", "note"} for one task's payload; at_most None when it cannot be known."""
    if "plan" not in payload:
        return {"at_most": None, "typical": None, "note": "cost unknown: not added with --plan"}
    if not Path(payload["plan"]).exists():
        return {"at_most": None, "typical": None, "note": f"cost unknown: {payload['plan']} not found"}
    models = prompt_models(payload["plan"])
    if not models:
        return {"at_most": 0.0, "typical": 0.0, "note": "no prompt steps"}
    cap = payload.get("allow_claude")
    if cap is None:
        return {"at_most": None, "typical": None, "note": "iterum run will refuse it: prompt steps but no --allow-claude"}
    at_most = (len(models) + payload.get("fix_retries", 0)) * cap
    unnamed = models.count(None)
    if unnamed:  # telemetry records the model used, but the plan does not say which model the default is
        return {"at_most": at_most, "typical": None, "note": f"typical unknown: {unnamed} prompt step(s) name no model"}
    known = [statistics.median(costs[m]) for m in models if m in costs]
    if len(known) < len(models):
        missing = sorted({m for m in models if m not in costs})
        return {"at_most": at_most, "typical": None, "note": f"no past prompt steps on {', '.join(missing)}"}
    used = ", ".join(f"{m}: median of {len(costs[m])}" for m in sorted(set(models)))
    return {"at_most": at_most, "typical": sum(known), "note": f"{len(models)} prompt step(s); {used}"}


def ready_tasks(con):
    return con.execute("SELECT task_id, payload FROM tasks WHERE status='ready' ORDER BY task_id").fetchall()


def usd(x):
    return "?" if x is None else f"{x:.4f}"


def show():
    """Print each ready task's estimate, the totals and the worker command. Sets nothing."""
    con = db.connect()
    try:
        tasks, costs = ready_tasks(con), step_costs(con)
    finally:
        con.close()
    if not tasks:
        print("no ready tasks")
        return
    rows = [(t["task_id"], estimate(json.loads(t["payload"] or "{}"), costs)) for t in tasks]
    for task_id, e in rows:
        print(f"task {task_id:<4} at most {usd(e['at_most']):>8}  typical {usd(e['typical']):>8}  {e['note']}")
    at_most = sum(e["at_most"] or 0 for _, e in rows)
    typical = sum(e["typical"] or 0 for _, e in rows)
    unknown = sum(e["at_most"] is None for _, e in rows)
    print(f"total     at most {at_most:>8.4f}  typical {typical:>8.4f}  USD")
    if unknown:
        print(f"{unknown} task(s) without an 'at most' are not counted; a limit from these totals may stop them")
    no_history = sum(e["at_most"] is not None and e["typical"] is None for _, e in rows)
    if no_history:
        print(f"{no_history} task(s) have no 'typical' (see each note), so its total leaves them out")
    if at_most > 0:
        print(f"start the night with:\n  iterum worker night-1 --until-empty --max-usd {math.ceil(at_most * 100) / 100:.2f}")
