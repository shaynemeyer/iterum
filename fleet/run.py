"""Resumable runs. Every step is written to the ledger BEFORE it executes.

    uv run python -u -m fleet.run                     # the six-step drill plan below
    uv run python -u -m fleet.run --plan myplan.json  # your own plan
    uv run python -u -m fleet.run --resume <run_id>   # pick up uncommitted steps
    uv run python -u -m fleet.run --resume <run_id> --plan myplan.json   # resuming your own plan
    uv run python -u -m fleet.run --resume <run_id> --force           # resume a halted run after review

Always with `-u`. A killed process does not flush its buffers, so without it
output that is piped or redirected is lost and you conclude the wrapper did nothing.
"""

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from fleet import db, recovery
from fleet.proc import group_alive

HEARTBEAT = 10  # seconds between heartbeat_at updates; fleet.recovery's expiry must be several of these


def shell(cmd, run_id, seq):
    """One step's side effect. Returns a short result string.

    The command gets its own process group, recorded on the step, so a resume can
    tell whether a killed run.py left it running. Being outside the terminal's
    foreground group, it misses Ctrl-C, so a KeyboardInterrupt kills the group here.
    """
    p = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    with db.write() as con:
        con.execute("UPDATE steps SET pgid=? WHERE run_id=? AND seq=?", (p.pid, run_id, seq))
    try:
        stdout, stderr = p.communicate()
    except KeyboardInterrupt:
        os.killpg(p.pid, signal.SIGKILL)
        raise
    if p.returncode != 0:
        raise RuntimeError(f"step failed with exit {p.returncode}: {stderr.strip()}")
    return stdout.strip()[:200]


def committed_seqs(run_id):
    """The seqs of this run's committed steps. Everything else still has to run."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT seq FROM steps WHERE run_id=? AND status='committed'",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    return {r["seq"] for r in rows}


def check_resumable(run_id, plan, force=False):
    """Exit unless run_id exists, is not done, is not halted or still alive (unless force), and every recorded step matches the plan by seq.

    Alive means running with a heartbeat younger than recovery.IDLE_SECONDS, the same rule fleet.recovery uses,
    or an uncommitted step whose command's process group still exists.
    """
    con = db.connect()
    try:
        run = con.execute("SELECT status, heartbeat_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
        recorded = con.execute(
            "SELECT seq, intent, status, pgid FROM steps WHERE run_id=? ORDER BY seq",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    if not run:
        sys.exit(f"no run {run_id!r} in {db.DB}")
    if run["status"] == "done":
        sys.exit(f"run {run_id} is already done; nothing to resume")
    if run["status"] == "halted" and not force:
        sys.exit(
            f"run {run_id} was halted for review; resume it only after a human has looked:\n"
            f"  uv run python -u -m fleet.run --resume {run_id} --force"
        )
    if run["status"] == "running" and run["heartbeat_at"] and not force:
        age = time.time() - run["heartbeat_at"]
        if age < recovery.IDLE_SECONDS:
            sys.exit(
                f"run {run_id} may still be alive: its heartbeat is {age:.0f}s old.\n"
                f"wait until it is older than {recovery.IDLE_SECONDS}s, or, if you know the process is gone:\n"
                f"  uv run python -u -m fleet.run --resume {run_id} --force"
            )
    for r in recorded:
        if r["status"] != "committed" and r["pgid"] and not force and group_alive(r["pgid"]):
            sys.exit(
                f"run {run_id} step {r['seq']} may still be running: process group {r['pgid']} exists.\n"
                f"  ps -o pid,command -g {r['pgid']}\n"
                f"wait for it to exit, or, if you know it is safe to run the step again:\n"
                f"  uv run python -u -m fleet.run --resume {run_id} --force"
            )
    planned = {seq: intent for seq, intent, _ in plan}
    for r in recorded:
        if planned.get(r["seq"]) != r["intent"]:
            sys.exit(
                f"run {run_id} does not match this plan at step {r['seq']}.\n"
                f"  recorded: {r['intent']!r}\n"
                f"  plan:     {planned.get(r['seq'])!r}\n"
                "resume it with the same plan you started it with:\n"
                f"  uv run python -u -m fleet.run --resume {run_id} --plan yourplan.json"
            )


def record_failure(run_id, seq, error):
    """Mark the step and the run failed, so the ledger tells a failure from a crash."""
    with db.write() as con:
        con.execute(
            "UPDATE steps SET status='failed', ended_at=? WHERE run_id=? AND seq=?",
            (time.time(), run_id, seq),
        )
        db.log(con, run_id, "step.failed", stage="tool_execution", seq=seq, error=error)
    db.finish_run(run_id, "failed")


def mark_running(run_id):
    """Set the run back to running; a resumed run may have been marked failed."""
    with db.write() as con:
        con.execute(
            "UPDATE runs SET status='running', ended_at=NULL, heartbeat_at=? WHERE run_id=?",
            (time.time(), run_id),
        )


def beat(run_id, stop):
    """Refresh heartbeat_at every HEARTBEAT seconds until stop is set. Runs in its own thread.

    A locked database skips one beat, since losing the thread would make a live run look dead.
    """
    while not stop.wait(HEARTBEAT):
        try:
            with db.write() as con:
                con.execute(
                    "UPDATE runs SET heartbeat_at=? WHERE run_id=?", (time.time(), run_id)
                )
        except sqlite3.OperationalError as e:
            if e.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise


def execute(run_id, plan):
    mark_running(run_id)
    stop = threading.Event()
    threading.Thread(target=beat, args=(run_id, stop), daemon=True).start()
    try:
        run_steps(run_id, plan)
    finally:
        stop.set()


def run_steps(run_id, plan):
    done = committed_seqs(run_id)
    if done:
        print(f"resuming {run_id}, {len(done)} step(s) already committed")

    for seq, intent, cmd in plan:
        if seq in done:
            print(f"  step {seq}  already committed, skipping")
            continue

        # ---- write BEFORE the side effect ----
        with db.write() as con:
            con.execute(
                "INSERT OR REPLACE INTO steps (run_id,seq,intent,status,started_at)"
                " VALUES (?,?,?,'proposed',?)",
                (run_id, seq, intent, time.time()),
            )
            db.log(
                con, run_id, "step.proposed", stage="planning", seq=seq, intent=intent
            )

        try:
            result = shell(cmd, run_id, seq)  # <-- the side effect
        except RuntimeError as e:
            record_failure(run_id, seq, str(e))
            raise

        # ---- record the commit AFTER ----
        with db.write() as con:
            con.execute(
                "UPDATE steps SET status='committed', ended_at=? WHERE run_id=? AND seq=?",
                (time.time(), run_id, seq),
            )
            db.log(
                con,
                run_id,
                "step.committed",
                stage="tool_execution",
                seq=seq,
                result=result,
            )

        print(f"  step {seq}  {intent}  -> committed")

    db.finish_run(run_id, "done")
    print(f"run {run_id} done")


def claude_step(prompt):
    """The swap-in that points this wrapper at real work.

    THIS COSTS MONEY. It shells out to your own Claude Code and every call is
    billed to you. It is not a drop-in for shell(): the plan's third field must
    be a prompt instead of a shell command, and this returns the whole JSON
    envelope instead of a string. Log env["result"] as the step's result, and
    keep env["session_id"] so a later call can pass it to `claude -p --resume`.
    """
    p = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
    )
    env = json.loads(p.stdout)
    if env["is_error"] or p.returncode != 0:  # never branch on subtype
        raise RuntimeError(env.get("result") or "claude failed")
    return env


# The drill plan. Shell commands on purpose, so you can run the kill-and-resume
# without spending anything and without waiting on a model. Step 4 does its side
# effect and then sleeps, so a kill can land in the gap between the effect and
# the commit; step 5 sleeps long enough to be a comfortable kill window.
PLAN = [
    (1, "create the work directory", "mkdir -p out && echo ok"),
    (2, "fetch the file list", "ls fleet > out/filelist.txt && echo ok"),
    (3, "count the lines", "wc -l < out/filelist.txt > out/count.txt && echo ok"),
    (4, "the slow one", "echo ok > out/step4.txt && sleep 3"),
    (5, "write the summary", "sleep 20 && echo summary > out/summary.txt"),
    (6, "verify", "ls out | wc -l"),
]


def load_plan(path):
    """Read a plan from JSON: [[seq, intent, shell_command], ...].

    A tool whose only input is a literal in its own source is a demonstration.
    Point this at your own steps and the rest of the module does not change.
    """
    raw = json.loads(open(path).read())
    return [(int(seq), str(intent), str(cmd)) for seq, intent, cmd in raw]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="uv run python -u -m fleet.run")
    parser.add_argument("--plan", help="JSON plan file (default: the built-in drill)")
    parser.add_argument("--resume", metavar="RUN_ID", help="resume this run")
    parser.add_argument("--force", action="store_true", help="resume a halted run")
    args = parser.parse_args()
    plan = load_plan(args.plan) if args.plan else PLAN

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.resume:
        run_id = args.resume
        # a resume has to re-read the plan from somewhere, and the ledger stores
        # intents but not commands. so if you resumed a run of your own without
        # passing --plan again, we would silently execute the demo's steps under
        # your run id, which is worse than failing. the same goes for passing the
        # wrong --plan file, so compare on every resume and refuse on mismatch.
        check_resumable(run_id, plan, args.force)
    else:
        run_id = db.start_run("worker-1", args.plan or "six step demo")
        print(f"run {run_id} started")
    execute(run_id, plan)
