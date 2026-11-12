"""The loop each worker runs: claim, work, report exactly one outcome.

    uv run python -u -m fleet.worker worker-1
    uv run python -u -m fleet.worker worker-1 --budget-s 30
    FLEET_WORK_MODULE=mypackage.mywork uv run python -u -m fleet.worker worker-1

`do_work` is yours. The default below runs whatever shell command the task
payload carries, because that is the smallest thing that is real work rather
than a mime of it; point FLEET_WORK_MODULE at a module of your own exporting
`do_work(task)` and this file does not change. Only the default records its
command's process group on the lease, so only it is protected from a rerun
while a killed worker's command is still running; a module of your own must
handle the processes it starts.

Raising from `do_work` is how a worker reports failure.
"""

import argparse
import importlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

from fleet import db, governor, queue
from fleet.claim import Fenced, Refused
from fleet.proc import stop_on_sigterm

BUDGET_S = float(os.environ.get("FLEET_WORKER_BUDGET_S", 12))
TASK_TIMEOUT_S = float(os.environ.get("FLEET_TASK_TIMEOUT_S", 600))
HEARTBEAT = queue.LEASE_TTL / 3  # a few beats can be lost before the lease expires
REAP_EVERY = 5


def _time_left(task):
    """Seconds this task may run: its deadline if it has one, never above TASK_TIMEOUT_S."""
    if task["deadline"] is None:
        return TASK_TIMEOUT_S
    return min(TASK_TIMEOUT_S, task["deadline"] - time.time())


def _shell(cmd, task):
    """Run the task's cmd and return (returncode, stdout, stderr).

    It gets its own process group, recorded on the lease, so that reap() waits
    for it if this worker is killed. If _shell exits early for any reason (a
    timeout, a lost lease, Ctrl-C), it kills the whole group; killing only the
    shell would leave its children holding the output pipes open.
    """
    p = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        queue.record_pgid(task["task_id"], task["fence"], p.pid)
        stdout, stderr = p.communicate(timeout=_time_left(task))
    except BaseException:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise
    return p.returncode, stdout, stderr


def _default_do_work(task):
    payload = json.loads(task["payload"] or "{}")
    if "fail" in payload:
        raise RuntimeError(payload["fail"])
    if "cmd" not in payload:
        raise RuntimeError(
            "task payload has no 'cmd': give the task a shell command, or set "
            "FLEET_WORK_MODULE to a module exporting do_work(task)"
        )
    code, stdout, stderr = _shell(payload["cmd"], task)
    if code != 0:
        raise RuntimeError(stderr.strip()[:200] or f"exit {code}")
    return stdout.strip()[:200]


def _load_do_work():
    mod = os.environ.get("FLEET_WORK_MODULE")
    if not mod:
        return _default_do_work
    return getattr(importlib.import_module(mod), "do_work")


do_work = _load_do_work()


def _beat(task, worker, stop):
    """Extend the lease until stop is set or the lease is lost. Runs in its own thread."""
    while not stop.wait(HEARTBEAT):
        try:
            queue.heartbeat(task["task_id"], worker, task["fence"])
        except (Fenced, Refused) as e:
            print(f"{worker}  task {task['task_id']}  lease lost: {e}")
            return
        except sqlite3.OperationalError as e:
            print(f"{worker}  task {task['task_id']}  heartbeat missed: {e}")


@contextmanager
def _heartbeating(task, worker):
    """Keep the lease alive for the duration of the block."""
    stop = threading.Event()
    thread = threading.Thread(target=_beat, args=(task, worker, stop), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def _reap(worker):
    """Return dead workers' tasks to the queue and halt anything past its deadline."""
    for task_id, gone, status in queue.reap():
        if status == "waiting":
            print(f"{worker}  task {task_id}: {gone}'s lease expired but its command is still running")
        else:
            print(f"{worker}  reaped task {task_id} from {gone}: now {status}")
    for task_id in queue.sweep_deadlines():
        print(f"{worker}  halted task {task_id}: deadline exceeded")


def _attempt(task, worker, work):
    """Run work under a heartbeat. Return (result, None), or (None, error text) on failure."""
    try:
        with _heartbeating(task, worker):
            return work(task), None
    except Exception as e:
        return None, str(e)


def _run_one(task, worker, work=None):
    """Do one task and report one outcome. A worker that lost its lease has nothing to report.

    work defaults to do_work; fleet.replay passes its own to reuse a recorded outcome.
    """
    task_id, fence = task["task_id"], task["fence"]
    label = f"{worker}  task {task_id} ({task['kind']})"
    result, error = _attempt(task, worker, work or do_work)
    try:
        if error is None:
            queue.finish(task_id, worker, fence, result)
        else:
            queue.fail(task_id, worker, fence, error)
    except (Fenced, Refused) as e:
        print(f"{label}  lease lost, outcome dropped: {e}")
        return
    print(f"{label}  done" if error is None else f"{label}  failed: {error}")


def stop_at_ceiling(worker):
    """Exit before claiming another task once the fleet has no headroom left.

    Checked between tasks, as fleet.run checks between steps, so no task is in
    flight and every queued task stays queued for a worker started after the
    ceiling is raised. A task can still pass the ceiling by its own spend.
    """
    left = governor.headroom()
    if left > 0:
        return
    sys.exit(
        f"{worker}  stopped: fleet headroom is {left:.4f} USD, so no task was claimed.\n"
        "raise the ceiling, then start the worker again:\n"
        "  uv run python -m fleet.governor set <usd>"
    )


def main(worker, budget_s=BUDGET_S):
    deadline = time.time() + budget_s
    next_reap = 0
    while time.time() < deadline:
        if time.time() >= next_reap:
            _reap(worker)
            next_reap = time.time() + REAP_EVERY
        stop_at_ceiling(worker)
        task = queue.claim(worker)
        if not task:
            time.sleep(0.2)
            continue
        _run_one(task, worker)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one queue worker.")
    parser.add_argument("worker", help="a name unique to this worker")
    parser.add_argument("--budget-s", type=float, default=BUDGET_S)
    args = parser.parse_args()
    stop_on_sigterm()
    db.init()
    main(args.worker, args.budget_s)
