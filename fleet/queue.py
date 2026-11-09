"""A work queue with dependencies, leases, heartbeats, a DLQ and redrive.

`release_back` exists because contention is not failure: spending a retry budget
on queueing is how a healthy fleet convinces itself it is broken.
"""

import json
import time

from fleet import db
from fleet.claim import Refused, guard

LEASE_TTL = 30
RETRY_BASE_S = 5  # doubles with each attempt


def _run_id(task_id):
    """The ledger's run_id. task_id is local to this device and events are synced, so name the device."""
    return f"task-{db.device()}-{task_id}"


def _blocked_by(task_id):
    """The reason on tasks halted behind a dead letter. redrive() finds them by it."""
    return f"blocked by dead-lettered task {task_id}"


def _require_lease(con, task_id, worker, fence):
    """Refuse a worker that no longer holds this task. Call inside the db.write() block.

    Every terminal status deletes the lease, so this also keeps a finished task finished.
    """
    guard(con, f"task:{task_id}", fence)
    lease = con.execute(
        "SELECT 1 FROM leases WHERE task_id=? AND worker=?", (task_id, worker)
    ).fetchone()
    if not lease:
        raise Refused(f"task {task_id}: {worker} no longer holds the lease")


def _children(con, task_id):
    rows = con.execute("SELECT task_id FROM tasks WHERE depends_on=?", (task_id,))
    return [r["task_id"] for r in rows.fetchall()]


def _halt(con, task_ids, reason, now):
    """Halt these tasks and everything waiting on them. Returns the ids actually halted."""
    halted = []
    frontier = list(task_ids)
    while frontier:
        task_id = frontier.pop()
        cur = con.execute(
            "UPDATE tasks SET status='halted', reason=?, ended_at=?"
            " WHERE task_id=? AND status IN ('ready','in_progress')",
            (reason, now, task_id),
        )
        if cur.rowcount == 0:
            continue
        con.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
        db.log(con, _run_id(task_id), "task.halted", stage="scheduling", reason=reason)
        halted.append(task_id)
        frontier += _children(con, task_id)
    return halted


def _spend_attempt(con, task_id, worker, reason, retry_event):
    """Charge one attempt: retry after a backoff, or dead-letter and halt what waits on it.

    Returns the task's new status.
    """
    row = con.execute(
        "SELECT attempts, max_attempts FROM tasks WHERE task_id=?", (task_id,)
    ).fetchone()
    attempts = row["attempts"] + 1
    now = time.time()
    con.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
    if attempts >= row["max_attempts"]:
        con.execute(
            "UPDATE tasks SET status='dead_letter', attempts=?, reason=?, ended_at=?"
            " WHERE task_id=?",
            (attempts, reason, now, task_id),
        )
        db.log(
            con,
            _run_id(task_id),
            "task.dead_lettered",
            stage="scheduling",
            worker=worker,
            attempts=attempts,
            reason=reason,
        )
        _halt(con, _children(con, task_id), _blocked_by(task_id), now)
        return "dead_letter"
    con.execute(
        "UPDATE tasks SET status='ready', attempts=?, reason=?, not_before=?"
        " WHERE task_id=?",
        (attempts, reason, now + RETRY_BASE_S * 2 ** (attempts - 1), task_id),
    )
    db.log(
        con,
        _run_id(task_id),
        retry_event,
        stage="scheduling",
        worker=worker,
        attempts=attempts,
        reason=reason,
    )
    return "ready"


def add(kind, payload=None, depends_on=None, max_attempts=3, deadline=None):
    """Queue a task. A child inherits its parent's deadline, and is halted if the parent already failed."""
    now = time.time()
    with db.write() as con:
        parent = con.execute(
            "SELECT deadline, status, reason FROM tasks WHERE task_id=?", (depends_on,)
        ).fetchone()
        if parent and deadline is None:
            deadline = parent["deadline"]
        task_id = con.execute(
            "INSERT INTO tasks (kind,payload,status,depends_on,max_attempts,deadline,created_at)"
            " VALUES (?,?,'ready',?,?,?,?)",
            (kind, json.dumps(payload or {}), depends_on, max_attempts, deadline, now),
        ).lastrowid
        db.log(
            con,
            _run_id(task_id),
            "task.added",
            stage="scheduling",
            task_kind=kind,
            depends_on=depends_on,
        )
        if parent and parent["status"] == "dead_letter":
            _halt(con, [task_id], _blocked_by(depends_on), now)
        elif parent and parent["status"] == "halted":
            _halt(con, [task_id], parent["reason"], now)
        return task_id


def claim(worker, ttl=LEASE_TTL):
    """Take one ready task whose dependency is satisfied. Atomic by BEGIN IMMEDIATE.

    The returned dict carries `fence`, which the worker presents on every later call.
    """
    now = time.time()
    with db.write() as con:
        row = con.execute(
            "SELECT t.* FROM tasks t"
            " LEFT JOIN tasks d ON d.task_id = t.depends_on"
            " WHERE t.status='ready'"
            "   AND (t.depends_on IS NULL OR d.status='done')"
            "   AND (t.not_before IS NULL OR t.not_before <= ?)"
            "   AND (t.deadline IS NULL OR t.deadline >= ?)"
            " ORDER BY t.task_id LIMIT 1",
            (now, now),
        ).fetchone()
        if not row:
            return None
        con.execute(
            "UPDATE tasks SET status='in_progress' WHERE task_id=?", (row["task_id"],)
        )
        con.execute(
            "INSERT OR REPLACE INTO leases (task_id,worker,granted_at,expires_at,heartbeat_at)"
            " VALUES (?,?,?,?,?)",
            (row["task_id"], worker, now, now + ttl, now),
        )
        fence = con.execute(
            "INSERT INTO fences (resource, high) VALUES (?, 1)"
            " ON CONFLICT(resource) DO UPDATE SET high = high + 1 RETURNING high",
            (f"task:{row['task_id']}",),
        ).fetchone()["high"]
        # task_kind, not kind: `kind` is a reserved parameter of db.log and
        # passing it as payload raises TypeError at call time.
        db.log(
            con,
            _run_id(row["task_id"]),
            "task.claimed",
            stage="scheduling",
            worker=worker,
            task_kind=row["kind"],
        )
        return dict(row, fence=fence)


def heartbeat(task_id, worker, fence, ttl=LEASE_TTL):
    """Extend the lease. Raises Fenced or Refused if the worker has lost it."""
    with db.write() as con:
        _require_lease(con, task_id, worker, fence)
        now = time.time()
        con.execute(
            "UPDATE leases SET heartbeat_at=?, expires_at=? WHERE task_id=? AND worker=?",
            (now, now + ttl, task_id, worker),
        )


def finish(task_id, worker, fence):
    """Mark the task done. Raises Fenced or Refused if the worker has lost it."""
    with db.write() as con:
        _require_lease(con, task_id, worker, fence)
        con.execute(
            "UPDATE tasks SET status='done', ended_at=? WHERE task_id=?",
            (time.time(), task_id),
        )
        con.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
        db.log(con, _run_id(task_id), "task.done", stage="scheduling", worker=worker)


def fail(task_id, worker, fence, reason):
    """Retry until max_attempts, then dead-letter with the reason attached."""
    with db.write() as con:
        _require_lease(con, task_id, worker, fence)
        _spend_attempt(con, task_id, worker, reason, "task.failed")


def release_back(task_id, worker, fence, reason):
    """Contention is not failure. Return the task without spending an attempt."""
    with db.write() as con:
        _require_lease(con, task_id, worker, fence)
        con.execute(
            "UPDATE tasks SET status='ready', reason=? WHERE task_id=?",
            (reason, task_id),
        )
        con.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
        db.log(
            con,
            _run_id(task_id),
            "task.released",
            stage="coordination",
            worker=worker,
            reason=reason,
        )


def reap():
    """Expired lease = the worker is gone. Give the task back, or bury it."""
    reaped = []
    with db.write() as con:
        for row in con.execute(
            "SELECT task_id, worker FROM leases WHERE expires_at < ?", (time.time(),)
        ).fetchall():
            reason = f"lease expired ({row['worker']} stopped reporting)"
            status = _spend_attempt(
                con, row["task_id"], row["worker"], reason, "task.reaped"
            )
            reaped.append((row["task_id"], row["worker"], status))
    return reaped


def redrive(task_id):
    """Put a dead-lettered task back on the queue, with the tasks halted behind it.

    A DLQ you cannot replay from is a graveyard. Returns the restored task ids, or
    None if the task is not dead-lettered, which changes nothing and logs nothing.
    """
    with db.write() as con:
        cur = con.execute(
            "UPDATE tasks SET status='ready', attempts=0, reason=NULL, ended_at=NULL,"
            " not_before=NULL WHERE task_id=? AND status='dead_letter'",
            (task_id,),
        )
        if cur.rowcount == 0:
            return None
        db.log(con, _run_id(task_id), "task.redriven", stage="scheduling")
        restored = con.execute(
            "UPDATE tasks SET status='ready', reason=NULL, ended_at=NULL"
            " WHERE status='halted' AND reason=? RETURNING task_id",
            (_blocked_by(task_id),),
        ).fetchall()
        for row in restored:
            db.log(con, _run_id(row["task_id"]), "task.restored", stage="scheduling")
        return [row["task_id"] for row in restored]


def dead_letters():
    """Dead-lettered tasks, oldest first, each with `waiting`: how many are halted behind it."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT * FROM tasks WHERE status='dead_letter' ORDER BY task_id"
        ).fetchall()
        return [
            dict(
                row,
                waiting=con.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status='halted' AND reason=?",
                    (_blocked_by(row["task_id"]),),
                ).fetchone()[0],
            )
            for row in rows
        ]
    finally:
        con.close()


def sweep_deadlines():
    """Halt anything past its deadline, and everything waiting on it."""
    now = time.time()
    with db.write() as con:
        rows = con.execute(
            "SELECT task_id FROM tasks"
            " WHERE deadline IS NOT NULL AND deadline < ?"
            "   AND status IN ('ready','in_progress')",
            (now,),
        ).fetchall()
        return _halt(con, [r["task_id"] for r in rows], "deadline exceeded", now)
