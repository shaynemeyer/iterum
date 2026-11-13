"""Kill a worker with SIGKILL mid-task and prove the queue recovers.

    iterum drill kill

Works in a temporary directory with its own database, so it never touches
agent.db. It uses the real lease, so a run takes about 50 seconds. Exits 1 if
any check fails.
"""

import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fleet import db, queue
from fleet.proc import group_alive

TIMEOUT_S = 90
RECOVERED_EVENTS = [
    "task.added",
    "task.claimed",
    "task.reaped",
    "task.claimed",
    "task.done",
]


def _start_worker(name):
    return subprocess.Popen(
        [sys.executable, "-u", "-m", "fleet.worker", name, "--budget-s", str(TIMEOUT_S)]
    )


def _wait_until(ready, what):
    """Poll until ready() is true. Exits 1 if it never is."""
    give_up = time.time() + TIMEOUT_S
    while not ready():
        if time.time() > give_up:
            sys.exit(f"FAIL  timed out after {TIMEOUT_S}s waiting for {what}")
        time.sleep(0.1)


def _query(sql, *params):
    con = db.connect()
    try:
        return [tuple(row) for row in con.execute(sql, params)]
    finally:
        con.close()


def _status(task_id):
    return _query("SELECT status FROM tasks WHERE task_id=?", task_id)[0][0]


def _check(label, actual, expected):
    """Print the result of one comparison and return whether it held."""
    held = actual == expected
    print(f"{'PASS' if held else 'FAIL'}  {label}: {actual}")
    if not held:
        print(f"      expected: {expected}")
    return held


def _run_drill(work):
    """Run the drill in the directory work. Returns True if every check held."""
    runs = work / "runs.txt"
    quoted = shlex.quote(str(runs))
    # The first run outlives the lease; the rerun finishes at once. Overlapping
    # copies write "start start end end", one after the other "start end start end".
    first_run = f"echo start >> {quoted}; sleep {queue.LEASE_TTL + 15}; echo end >> {quoted}"
    rerun = f"echo start >> {quoted}; echo end >> {quoted}"
    parent = queue.add("parent", {"cmd": f"if [ -s {quoted} ]; then {rerun}; else {first_run}; fi"})
    child = queue.add("child", {"cmd": f"echo child >> {quoted}"}, depends_on=parent)

    victim = _start_worker("victim")
    _wait_until(runs.exists, "the victim to start its command")
    victim.kill()
    victim.wait()
    print("victim killed; waiting for the lease to expire")
    results = [
        _check("victim exit code", victim.returncode, -9),
        _check("task left behind", _status(parent), "in_progress"),
        _check(
            "lease left behind",
            _query("SELECT worker FROM leases WHERE task_id=?", parent),
            [("victim",)],
        ),
    ]

    rescuer = _start_worker("rescuer")
    _wait_until(lambda: _status(child) == "done", "the rescuer to finish both tasks")
    rescuer.terminate()
    rescuer.wait()

    events = _query(
        "SELECT kind FROM events WHERE run_id=? ORDER BY event_id",
        f"task-drill-{parent}",
    )
    return results + [
        _check("parent", _status(parent), "done"),
        _check("attempts charged", _query("SELECT attempts FROM tasks WHERE task_id=?", parent), [(1,)]),
        _check("parent events", [e[0] for e in events], RECOVERED_EVENTS),
        _check("leases remaining", _query("SELECT COUNT(*) FROM leases"), [(0,)]),
        _check(
            "commands in order, never overlapping",
            runs.read_text().split(),
            ["start", "end", "start", "end", "child"],
        ),
    ]


def _run_sigterm():
    """SIGTERM a worker mid-task. Returns the check results."""
    task = queue.add("polite stop", {"cmd": "sleep 60"})
    worker = _start_worker("polite")
    _wait_until(lambda: _query("SELECT pgid FROM leases WHERE task_id=? AND pgid IS NOT NULL", task),
                "the worker to start its command")
    pgid = _query("SELECT pgid FROM leases WHERE task_id=?", task)[0][0]
    worker.send_signal(signal.SIGTERM)
    worker.wait()
    time.sleep(0.2)
    return [_check("SIGTERM: task's command killed", group_alive(pgid), False)]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        os.environ.update(ITERUM_DB=str(work / "drill.db"), ITERUM_DEVICE="drill")
        db.DB = work / "drill.db"
        db.init()
        passed = all(_run_drill(work) + _run_sigterm())
    print("drill passed" if passed else "drill FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
