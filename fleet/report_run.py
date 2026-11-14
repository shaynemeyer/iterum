"""One fleet.run run from agent.db, as plain data. Reads only.

The failing stage is the stage of the run's first failure event, the rule `iterum view trace` uses.
"""

import json
from pathlib import Path

from fleet import db, telemetry, view


def plan_name(task):
    """A run's plan as people name it: the folder of a `plan.json` (as /iterum:fleet-plan writes them), else the file name."""
    path = Path(task)
    return path.parent.name if path.name == "plan.json" and path.parent.name else path.name


def run_report(run_id):
    """The run, its steps, its events in order, its spend and its merges; None if there is no such run."""
    con = db.connect()
    try:
        run = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            return None
        steps = [dict(s) for s in con.execute(
            "SELECT seq, intent, status, started_at, ended_at FROM steps WHERE run_id=? ORDER BY seq", (run_id,))]
        events = [{"ts": e["ts"], "stage": e["stage"], "seq": e["seq"], "kind": e["kind"],
                   "failure": view.is_failure(e["kind"]), "payload": json.loads(e["payload"])}
                  for e in con.execute("SELECT ts, stage, seq, kind, payload FROM events WHERE run_id=? ORDER BY event_id", (run_id,))]
    finally:
        con.close()
    first = next((e for e in events if e["failure"]), None)
    spend = [e["payload"] for e in events if e["kind"] == telemetry.KIND]
    return {
        "run_id": run_id, "plan": plan_name(run["task"]), "agent": run["agent"], "status": run["status"],
        "started_at": run["started_at"], "ended_at": run["ended_at"],
        "cost_usd": sum(p.get("cost_usd") or 0 for p in spend), "requests": len(spend),
        "failing_stage": first["stage"] if first else None,
        "failing_seq": first["seq"] if first else None,
        "steps": steps, "events": events,
        "merges": [dict(e["payload"], kind=e["kind"], ts=e["ts"]) for e in events if e["kind"].startswith("merge.")],
        "db": str(Path(db.DB).resolve()),
    }
