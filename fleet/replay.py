"""Replay a fleet.run run or a queue task through the harness's own code, from the ledger.

Each step's side effect is replaced by what the ledger recorded for it: a committed
step returns its recorded result, a failed step raises its recorded error, and a step
proposed with no outcome is a kill (KeyboardInterrupt). Everything else is
`fleet.run.run_steps`, against a scratch database: write-ahead, skipping committed
steps on resume, recording a failure, ending the run. A killed or failed run that was
resumed is resumed again here, as many times as the ledger shows.

It never calls a model or a shell command, so it tests the harness, not whether a
model would make the same choices today. That needs re-sampling, a separate tool.
Claims, the heartbeat and check_resumable() are not replayed.

A queue task (run_id `task-<device>-<id>`) is re-added with its recorded kind and
max_attempts, then claimed with `queue.claim` and run with `worker._run_one` once per
recorded claim, each attempt's work playing back the recorded outcome (done, or failed
with its reason), and redriven with `queue.redrive` where the ledger shows a redrive.
A clock skips past each retry backoff. A task with a dependency gets a stand-in parent,
finished first. Reaps, releases, deadlines and halts are not replayed.

Needs ITERUM_DEVICE, since the harness logs events (into the scratch database only).
"""

import contextlib
import io
import json
import tempfile
import time
from pathlib import Path
from unittest import mock

from fleet import db, queue, run, worker

END_KINDS = {"run.done", "run.failed", "run.halted", "run.budget_exhausted",
             "task.done", "task.dead_lettered", "task.halted", "task.resolved"}
FAIL_KINDS = {"step.failed", "task.failed", "run.halted"}
REPLAYABLE = {"run.started", "step.proposed", "step.committed", "step.failed", "run.done",
              "run.failed", "claude.finished", "spend.reported",
              "claim.granted", "claim.reclaimed", "claim.released"}
TASK_REPLAYABLE = {"task.added", "task.claimed", "task.done", "task.failed",
                   "task.dead_lettered", "task.redriven"}
SKIP_AHEAD_S = 86400  # past any retry backoff, so a recorded retry is claimable at once


class Diverged(Exception):
    """The harness ran a step, or offered a task, a different number of times than the ledger recorded."""


class Clock:
    """Stands in for fleet.queue's time module: real time, plus however far replay has skipped ahead."""

    def __init__(self):
        self.skipped = 0.0

    def time(self):
        return time.time() + self.skipped


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


def recorded_task(run_id, events):
    """The task.added payload, and the actions in order: ["claim", outcome] or ["redrive", None].

    An outcome is ("done", None), ("failed", reason), or None for a claim with no outcome yet.
    """
    added = json.loads(events[0]["payload"])
    if "max_attempts" not in added:
        raise ValueError(f"task {run_id} was added before task.added recorded max_attempts")
    actions = []
    for ev in events:
        payload = json.loads(ev["payload"])
        if ev["kind"] == "task.claimed":
            actions.append(["claim", None])
        elif ev["kind"] == "task.done":
            actions[-1][1] = ("done", None)
        elif ev["kind"] == "task.failed":
            actions[-1][1] = ("failed", payload["reason"])
        elif ev["kind"] == "task.redriven":
            actions.append(["redrive", None])
    return added, actions


def recorded_work(outcome):
    """A do_work that plays back one recorded outcome instead of running anything."""
    status, reason = outcome

    def work(task):
        if status == "failed":
            raise RuntimeError(reason)
    return work


def drive_task(added, actions):
    """Re-add the task, then claim, run and redrive it as the ledger shows. Returns its scratch run_id."""
    clock = Clock()
    with mock.patch.object(queue, "time", clock):
        parent = None
        if added["depends_on"] is not None:
            parent = queue.add("stand-in parent")
            worker._run_one(queue.claim("replay"), "replay", recorded_work(("done", None)))
        task_id = queue.add(added["task_kind"], depends_on=parent, max_attempts=added["max_attempts"])
        claims = 0
        for action, outcome in actions:
            if action == "redrive":
                queue.redrive(task_id)
                continue
            claims += 1
            clock.skipped += SKIP_AHEAD_S
            task = queue.claim("replay")
            if task is None:
                raise Diverged(f"diverged at claim {claims}: the queue did not offer the task")
            if outcome:
                worker._run_one(task, "replay", recorded_work(outcome))
    return queue._run_id(task_id)


def replay(run_id):
    """The end state the harness reaches today when fed run_id's recorded outcomes.

    If it runs a step or offers a task a different number of times than the ledger
    shows, `end` says where it diverged.
    """
    events = recorded_events(run_id)
    is_task = events[0]["kind"] == "task.added"
    other = {ev["kind"] for ev in events} - (TASK_REPLAYABLE if is_task else REPLAYABLE)
    if other:
        raise ValueError(f"run {run_id} is not replayable: it has {sorted(other)}")
    with scratch_db(), contextlib.redirect_stdout(io.StringIO()):
        try:
            replayed = drive_task(*recorded_task(run_id, events)) if is_task else drive(events)
            return end_state(recorded_events(replayed))
        except Diverged as e:
            return {"end": str(e), "failed_stage": None, "committed": []}
