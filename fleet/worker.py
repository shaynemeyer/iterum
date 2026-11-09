"""The loop each worker runs: claim, work, report exactly one outcome.

    uv run python -u -m fleet.worker worker-1
    uv run python -u -m fleet.worker worker-1 --budget-s 30
    FLEET_WORK_MODULE=mypackage.mywork uv run python -u -m fleet.worker worker-1

`do_work` is yours. The default below runs whatever shell command the task
payload carries, because that is the smallest thing that is real work rather
than a mime of it; point FLEET_WORK_MODULE at a module of your own exporting
`do_work(task)` and this file does not change.

Raising from `do_work` is how a worker reports failure.
"""

import argparse
import importlib
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager

from fleet import db, queue
from fleet.claim import Fenced, Refused

BUDGET_S = float(os.environ.get("FLEET_WORKER_BUDGET_S", 12))
TASK_TIMEOUT_S = float(os.environ.get("FLEET_TASK_TIMEOUT_S", 600))
HEARTBEAT = queue.LEASE_TTL / 3  # a few beats can be lost before the lease expires
REAP_EVERY = 5


def _time_left(task):
    """Seconds this task may run: its deadline if it has one, never above TASK_TIMEOUT_S."""
    if task["deadline"] is None:
        return TASK_TIMEOUT_S
    return min(TASK_TIMEOUT_S, task["deadline"] - time.time())


def _shell(cmd, timeout):
    """Run cmd and return (returncode, stdout, stderr).

    It gets its own process group so that a timeout kills everything it started;
    killing only the shell would leave its children holding the output pipes open.
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
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
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
    code, stdout, stderr = _shell(payload["cmd"], _time_left(task))
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
        print(f"{worker}  reaped task {task_id} from {gone}: now {status}")
    for task_id in queue.sweep_deadlines():
        print(f"{worker}  halted task {task_id}: deadline exceeded")


def _attempt(task, worker):
    """Run do_work under a heartbeat. Return the error text, or None on success."""
    try:
        with _heartbeating(task, worker):
            do_work(task)
    except Exception as e:
        return str(e)
    return None


def _run_one(task, worker):
    """Do one task and report one outcome. A worker that lost its lease has nothing to report."""
    task_id, fence = task["task_id"], task["fence"]
    label = f"{worker}  task {task_id} ({task['kind']})"
    error = _attempt(task, worker)
    try:
        if error is None:
            queue.finish(task_id, worker, fence)
        else:
            queue.fail(task_id, worker, fence, error)
    except (Fenced, Refused) as e:
        print(f"{label}  lease lost, outcome dropped: {e}")
        return
    print(f"{label}  done" if error is None else f"{label}  failed: {error}")


def main(worker, budget_s=BUDGET_S):
    deadline = time.time() + budget_s
    next_reap = 0
    while time.time() < deadline:
        if time.time() >= next_reap:
            _reap(worker)
            next_reap = time.time() + REAP_EVERY
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
    db.init()
    main(args.worker, args.budget_s)
