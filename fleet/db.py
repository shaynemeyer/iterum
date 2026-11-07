"""agent.db access. Every write path goes through write()"""

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DB = Path(os.environ.get("ITERUM_DB", "agent.db"))
SCHEMA = Path(__file__).with_name("schema.sql")


def connect():
    # isolation_level=None turns OFF the module's implicit transaction
    # handling, so our explicit BEGIN IMMEDIATE is the one that counts.
    con = sqlite3.connect(DB, isolation_level=None, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def write():
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
    except Exception:
        con.close()  # no transaction was opened, so there is nothing to roll back
        raise
    try:
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def device():
    """This device's name, from ITERUM_DEVICE."""
    name = os.environ.get("ITERUM_DEVICE")
    if not name:
        raise RuntimeError("ITERUM_DEVICE is not set. Name this device first, e.g. export ITERUM_DEVICE=laptop")
    return name


def init():
    """Create the schema, and add columns that CREATE TABLE IF NOT EXISTS skips on old databases."""
    con = connect()
    try:
        con.executescript(SCHEMA.read_text())
        columns = {r["name"] for r in con.execute("PRAGMA table_info(runs)")}
        if "heartbeat_at" not in columns:
            con.execute("ALTER TABLE runs ADD COLUMN heartbeat_at REAL")
    finally:
        con.close()


def log(con, run_id, kind, stage="harness", seq=None, **payload):
    """Append one event.

    `run_id`, `kind`, `stage` and `seq` are RESERVED payload names. Passing any of them as keyword data raises `TypeError: log() got multiple values for argument 'kind'` at CALL time, not import time, so it survives a smoke test and blows up in a drill. Rename the payload key instead: queue.claim logs `task_kind=row["kind"]` for exactly this reason.
    """
    con.execute(
        "INSERT INTO events (uid, device, run_id, seq, ts, stage, kind, payload)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid7()), device(), run_id, seq, time.time(), stage, kind, json.dumps(payload)),
    )


def start_run(agent, task):
    run_id = uuid.uuid4().hex[:12]
    with write() as con:
        con.execute(
            "INSERT INTO runs (run_id, agent, task, status, started_at) VALUES (?,?,?,'running',?)",
            (run_id, agent, task, time.time()),
        )
        log(con, run_id, "run.started", agent=agent, task=task)
    return run_id


def finish_run(run_id, status, cost_usd=0.0, session_id=None):
    with write() as con:
        con.execute(
            "UPDATE runs SET status=?, ended_at=?, cost_usd=?, session_id=? WHERE run_id=?",
            (status, time.time(), cost_usd, session_id, run_id),
        )
        log(con, run_id, "run." + status, cost_usd=cost_usd)
