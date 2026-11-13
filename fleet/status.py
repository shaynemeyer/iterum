"""One screen of fleet state: freeze, spend, receiver, runs, queue, what needs a person, canary. Reads only; exits 1 when something needs a person.

    iterum status        (or: uv run python -m fleet.status)
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from fleet import approve, canary, db, governor, queue, recovery


def header():
    """The first line: device, resolved database path, local time."""
    device = os.environ.get("ITERUM_DEVICE", "-")
    return f"iterum  {device}  {Path(db.DB).resolve()}  {time.strftime('%H:%M')}"


def fleet_line(con):
    """Whether queue claims are frozen."""
    return f"FLEET     {'FROZEN' if approve.frozen(con) else 'not frozen'}"


def spend_line():
    """The ceiling, the spend counted against it, and the headroom."""
    s = governor.status()
    if s is None:
        return "SPEND     no ceiling set"
    limit, spent, _ = s
    return f"SPEND     ceiling {limit:.2f}  spent {spent:.4f}  headroom {limit - spent:.4f} USD"


def receiver_line():
    """Whether the telemetry receiver answers, and with which database. Informational: no exit code.

    The same probe as fleet.run's check_receiver(): GET on the logs endpoint answers {"db": path}.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if not endpoint:
        return "RECEIVER  not configured (OTEL_EXPORTER_OTLP_LOGS_ENDPOINT unset; source .env.example)"
    try:
        with urllib.request.urlopen(endpoint, timeout=2) as r:
            receiver_db = json.load(r)["db"]
    except OSError:
        return f"RECEIVER  not answering at {endpoint}"
    if receiver_db != str(Path(db.DB).resolve()):
        return f"RECEIVER  up at {endpoint}, but writing to {receiver_db}"
    return f"RECEIVER  up at {endpoint}, writing to this database"


def run_lines(con):
    """Run counts by status, then one line per stale or failed run. Returns (lines, needs_person)."""
    counts = con.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status ORDER BY status").fetchall()
    summary = "   ".join(f"{r['n']} {r['status']}" for r in counts) or "none"
    lines = [f"RUNS      {summary}"]
    dead = recovery.dead_runs()
    for run_id, _, _, status, idle in dead:
        label = "stale" if status == "running" else "failed"
        lines.append(f"  {label:<7}  {run_id}  last seen {idle / 60:.0f}m ago")
    return lines, bool(dead)


STRANDED_SQL = """
SELECT t.task_id, l.worker, l.expires_at FROM tasks t JOIN leases l USING (task_id)
WHERE t.status = 'in_progress' AND l.expires_at < ? ORDER BY t.task_id
"""


def queue_lines(con):
    """Task counts by status, then stranded and dead-lettered tasks. Returns (lines, needs_person).

    Stranded: in progress with an expired lease, which no worker has reaped yet.
    """
    counts = dict(con.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall())
    stranded = con.execute(STRANDED_SQL, (time.time(),)).fetchall()
    dead = queue.dead_letters()
    order = ["ready", "in_progress", "dead_letter", "halted", "done"]
    summary = "   ".join(f"{counts[s]} {s}" for s in order if s in counts)
    if stranded:
        summary += f"   ({len(stranded)} stranded)"
    lines = [f"QUEUE     {summary or 'none'}"]
    for task_id, worker, expires_at in stranded:
        lines.append(f"  stranded task {task_id}  {worker}  lease expired {(time.time() - expires_at) / 60:.0f}m ago")
    for t in dead:
        lines.append(f"  dead     task {t['task_id']}  {t['kind']}  attempts {t['attempts']}/{t['max_attempts']}  {t['waiting']} waiting")
    return lines, bool(stranded or dead)


def person_lines():
    """Pending approvals and conflicts waiting for a person. Returns (lines, needs_person)."""
    approvals = approve.pending()
    conflicts = queue.human_tasks()
    lines = ["NEEDS A PERSON" + ("" if approvals or conflicts else "  nothing")]
    for a in approvals:
        lines.append(f"  approval  {a['fingerprint'][:16]}  {a['action']}  {a['run_id']} step {a['seq']}")
    for t in conflicts:
        lines.append(f"  conflict  task {t['task_id']}")
    return lines, bool(approvals or conflicts)


def canary_line():
    """canary.check() with its defaults, not logged. Informational: a fired canary cannot be cleared."""
    alerts = canary.check()
    if alerts is None:
        return "CANARY    insufficient data (needs 5 runs in the last 24h and 1 in the last hour)"
    if not alerts:
        return "CANARY    quiet"
    return "CANARY    changed: " + ";  ".join(f"{m} {b} -> {n} {d}" for m, b, n, d in alerts)


def main():
    """Print the status screen; exit 1 when a run, task, approval or conflict needs a person."""
    if not Path(db.DB).exists():
        sys.exit(f"no database at {Path(db.DB).resolve()}")
    con = db.connect()
    try:
        runs, runs_need = run_lines(con)
        tasks, tasks_need = queue_lines(con)
        person, person_need = person_lines()
        print("\n".join([header(), "", fleet_line(con), spend_line(), receiver_line(), "", *runs, "", *tasks, "", *person, "", canary_line()]))
    finally:
        con.close()
    sys.exit(1 if runs_need or tasks_need or person_need else 0)


if __name__ == "__main__":
    main()
