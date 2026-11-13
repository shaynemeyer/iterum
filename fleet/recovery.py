"""Find runs that died and decide whether it is safe to restart them.

    iterum recovery
    iterum recovery --idle-seconds 120 --max-attempts 5
    ITERUM_IDLE_SECONDS=120 iterum recovery

A run is dead if it is `failed`, or still `running` with a heartbeat older than
the idle time. A live run.py refreshes heartbeat_at every HEARTBEAT seconds,
even during a long step. Runs from before heartbeats fall back to their last
event time, which a long step can make look dead.
"""

import argparse
import os
import sys
import time

from fleet import db

IDLE_SECONDS = int(os.environ.get("ITERUM_IDLE_SECONDS", 60))
MAX_ATTEMPTS = int(os.environ.get("ITERUM_MAX_ATTEMPTS", 3))


def dead_runs(idle_seconds=IDLE_SECONDS):
    """Failed runs, and running runs whose heartbeat (or, without one, last event) is older than idle_seconds."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT r.run_id, r.agent, r.task, r.status,"
            "  COALESCE(r.heartbeat_at,"
            "    (SELECT MAX(ts) FROM events e WHERE e.run_id = r.run_id)) AS last_seen"
            " FROM runs r WHERE r.status IN ('running', 'failed')"
        ).fetchall()
    finally:
        con.close()

    now = time.time()
    return [
        (r["run_id"], r["agent"], r["task"], r["status"], now - r["last_seen"])
        for r in rows
        if r["status"] == "failed" or now - r["last_seen"] > idle_seconds
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


def halt_one(run_id, reason, found):
    """Halt a run a person gave up on. Only a run dead_runs() lists: never a done or live one."""
    if run_id not in {r[0] for r in found}:
        sys.exit(f"refused: {run_id} is not a failed or stale run")
    halt(run_id, reason)
    print(f"halted {run_id}; fleet.run resumes it only with --force")


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.recovery")
    parser.add_argument("--idle-seconds", type=int, default=IDLE_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    commands = parser.add_subparsers(dest="command")
    cmd = commands.add_parser("halt", help="give up on one failed or stale run")
    cmd.add_argument("run_id")
    cmd.add_argument("reason")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    found = dead_runs(args.idle_seconds)
    if args.command == "halt":
        halt_one(args.run_id, args.reason, found)
        return
    if not found:
        print(f"no dead runs (none failed, none quiet for more than {args.idle_seconds}s)")
        return
    for run_id, agent, task, status, idle_for in found:
        ok, why = resume_is_safe(run_id, args.max_attempts)
        verdict = "RESUME" if ok else "HALT  "
        print(f"{verdict}  {run_id}  {agent:10s}  {status:7s}  idle {idle_for:5.0f}s  {task[:30]}  ({why})")
        if ok:
            print(f"        iterum resume {run_id} [--plan <its plan>]")
        else:
            halt(run_id, why)


if __name__ == "__main__":
    main()
