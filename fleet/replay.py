"""Replay a run's recorded events from the ledger.

This replays recorded step results. It never calls a model, so it checks the
harness's reading of a run deterministically and says nothing about whether a
model would make the same choices today. That question needs re-sampling,
which is a separate tool; mixing the two makes a red case impossible to read.
"""

import json

from fleet import db

END_KINDS = {
    "run.done", "run.failed", "run.halted", "run.budget_exhausted",
    "task.done", "task.dead_lettered", "task.halted", "task.resolved",
}
FAIL_KINDS = {"step.failed", "task.failed", "run.halted"}


def recorded_events(run_id):
    """The run's events in ledger order. Raises LookupError if the ledger has none."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT seq, stage, kind, payload FROM events WHERE run_id=? ORDER BY event_id",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise LookupError(f"no events for run {run_id}")
    return rows


def replay(run_id, harness_fn=None):
    """Feed the recorded events through harness_fn and return the end state."""
    harness_fn = harness_fn or default_harness
    state = {"end": None, "failed_stage": None, "committed": []}
    for ev in recorded_events(run_id):
        harness_fn(state, ev["kind"], ev["stage"], ev["seq"], json.loads(ev["payload"]))
    return state


def default_harness(state, kind, stage, seq, payload):
    """Fold one event into state: the last ending, the first failure's stage, the committed seqs."""
    if kind == "step.committed":
        state["committed"].append(seq)
    elif kind in FAIL_KINDS and state["failed_stage"] is None:
        state["failed_stage"] = stage
    if kind in END_KINDS:
        state["end"] = kind
