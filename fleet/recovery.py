"""Find runs that died and decide whether it is safe to restart them.

    uv run python -m fleet.recovery
    uv run python -m fleet.recovery --idle-seconds 900 --max-attempts 5
    ITERUM_IDLE_SECONDS=900 uv run python -m fleet.recovery

A run is dead if it is `failed`, or still `running` with no event for longer
than the idle time. Idle time is a proxy for death, not a proof of it: no event
is written while a step runs, so a live run in a long step looks identical to a
killed one. Set the idle time longer than your slowest step.
"""

import argparse
import os
import time

from fleet import db

IDLE_SECONDS = int(os.environ.get("ITERUM_IDLE_SECONDS", 600))
MAX_ATTEMPTS = int(os.environ.get("ITERUM_MAX_ATTEMPTS", 3))


def dead_runs(idle_seconds=IDLE_SECONDS):
    """Failed runs, and running runs whose last event is older than idle_seconds."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT r.run_id, r.agent, r.task, r.status,"
            "  (SELECT MAX(ts) FROM events e WHERE e.run_id = r.run_id) AS last_event"
            " FROM runs r WHERE r.status IN ('running', 'failed')"
        ).fetchall()
    finally:
        con.close()

    now = time.time()
    return [
        (r["run_id"], r["agent"], r["task"], r["status"], now - r["last_event"])
        for r in rows
        if r["status"] == "failed" or now - r["last_event"] > idle_seconds
    ]


def resume_is_safe(run_id, max_attempts=MAX_ATTEMPTS):
    """Validate against retry history before restarting anything."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT seq, COUNT(*) AS attempts FROM events"
            " WHERE run_id=? AND kind='step.proposed' AND seq IS NOT NULL"
            " GROUP BY seq ORDER BY attempts DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    finally:
        con.close()
    if row and row["attempts"] >= max_attempts:
        return False, f"step {row['seq']} already proposed {row['attempts']} times"
    return True, "ok"


def halt(run_id, reason):
    """Mark the run halted so fleet.run refuses to resume it without --force."""
    with db.write() as con:
        con.execute(
            "UPDATE runs SET status='halted', ended_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        db.log(con, run_id, "run.halted", stage="validation", reason=reason)


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.recovery")
    parser.add_argument("--idle-seconds", type=int, default=IDLE_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    found = dead_runs(args.idle_seconds)
    if not found:
        print(f"no dead runs (none failed, none quiet for more than {args.idle_seconds}s)")
        return
    for run_id, agent, task, status, idle_for in found:
        ok, why = resume_is_safe(run_id, args.max_attempts)
        verdict = "RESUME" if ok else "HALT  "
        print(f"{verdict}  {run_id}  {agent:10s}  {status:7s}  idle {idle_for:5.0f}s  {task[:30]}  ({why})")
        if ok:
            print(f"        uv run python -u -m fleet.run --resume {run_id} [--plan <its plan>]")
        else:
            halt(run_id, why)


if __name__ == "__main__":
    main()
