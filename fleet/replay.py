"""Replay a fleet.run run through fleet.run's own code, from the ledger.

Each step's side effect is replaced by what the ledger recorded for it: a committed
step returns its recorded result, a failed step raises its recorded error, and a step
proposed with no outcome is a kill (KeyboardInterrupt). Everything else is
`fleet.run.run_steps`, against a scratch database: write-ahead, skipping committed
steps on resume, recording a failure, ending the run. A killed or failed run that was
resumed is resumed again here, as many times as the ledger shows.

It never calls a model or a shell command, so it tests the harness, not whether a
model would make the same choices today. That needs re-sampling, a separate tool.
Claims, the heartbeat and check_resumable() are not replayed. Needs ITERUM_DEVICE,
since run_steps logs events (into the scratch database only).
"""

import contextlib
import io
import json
import tempfile
from pathlib import Path

from fleet import db, run

END_KINDS = {"run.done", "run.failed", "run.halted", "run.budget_exhausted",
             "task.done", "task.dead_lettered", "task.halted", "task.resolved"}
FAIL_KINDS = {"step.failed", "task.failed", "run.halted"}
REPLAYABLE = {"run.started", "step.proposed", "step.committed", "step.failed", "run.done",
              "run.failed", "claude.finished", "spend.reported",
              "claim.granted", "claim.reclaimed", "claim.released"}


class Diverged(Exception):
    """fleet.run asked to run a step more times than the ledger recorded."""


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


def end_state(events):
    """The last ending, the first failure's stage, and the committed seqs in order."""
    state = {"end": None, "failed_stage": None, "committed": []}
    for ev in events:
        if ev["kind"] == "step.committed":
            state["committed"].append(ev["seq"])
        elif ev["kind"] in FAIL_KINDS and state["failed_stage"] is None:
            state["failed_stage"] = ev["stage"]
        if ev["kind"] in END_KINDS:
            state["end"] = ev["kind"]
    return state


def recorded_state(run_id):
    """The end state the run actually reached."""
    return end_state(recorded_events(run_id))


def recorded_plan(events):
    """The plan, and each seq's attempts in order: ("committed", result), ("failed", error) or ("killed", None)."""
    intents, attempts, prompts = {}, {}, set()
    for ev in events:
        seq, payload = ev["seq"], json.loads(ev["payload"])
        if ev["kind"] == "step.proposed":
            intents.setdefault(seq, payload["intent"])
            attempts.setdefault(seq, []).append(("killed", None))
        elif ev["kind"] == "step.committed":
            attempts[seq][-1] = ("committed", payload["result"])
        elif ev["kind"] == "step.failed":
            attempts[seq][-1] = ("failed", payload["error"])
        elif ev["kind"] == "claude.finished":
            prompts.add(seq)
    plan = [(seq, intents[seq], {"prompt": "recorded"} if seq in prompts else "recorded", ())
            for seq in sorted(intents)]
    return plan, attempts


def recorded_do_step(attempts):
    """A run_steps do_step that plays back each seq's recorded attempts instead of running anything."""
    def do_step(cmd, run_id, seq, cap_usd):
        if not attempts[seq]:
            raise Diverged(f"diverged at step {seq}")
        outcome, value = attempts[seq].pop(0)
        if outcome == "failed":
            raise RuntimeError(value)
        if outcome == "killed":
            raise KeyboardInterrupt
        return value
    return do_step


@contextlib.contextmanager
def scratch_db():
    """Point fleet.db at a fresh database in a temporary directory, then back."""
    saved = db.DB
    with tempfile.TemporaryDirectory() as d:
        db.DB = Path(d) / "replay.db"
        try:
            db.init()
            yield
        finally:
            db.DB = saved


def drive(events):
    """Run the recorded plan through run_steps, resuming after each failure or kill the ledger shows."""
    plan, attempts = recorded_plan(events)
    do_step = recorded_do_step(attempts)
    run_id = db.start_run("replay", "replay")
    while True:
        try:
            run.run_steps(run_id, plan, [], do_step=do_step)
            return run_id
        except (RuntimeError, KeyboardInterrupt):
            if not any(attempts.values()):
                return run_id
            run.mark_running(run_id)


def replay(run_id):
    """The end state fleet.run reaches today when fed run_id's recorded step results.

    If it runs a step more often than the ledger shows, `end` says where it diverged.
    """
    events = recorded_events(run_id)
    other = {ev["kind"] for ev in events} - REPLAYABLE
    if other:
        raise ValueError(f"run {run_id} is not a replayable fleet.run run: it has {sorted(other)}")
    with scratch_db(), contextlib.redirect_stdout(io.StringIO()):
        try:
            return end_state(recorded_events(drive(events)))
        except Diverged as e:
            return {"end": str(e), "failed_stage": None, "committed": []}
