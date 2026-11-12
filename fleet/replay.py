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
A reaped claim runs no work: the clock moves past the lease and `worker._reap` runs, as
another worker's loop would. A clock skips past each retry backoff. A task with a
dependency gets a chain of stand-in ancestors, as deep as the recorded depends_on chain
up to the dead letter its halt reason names; the replay dead-letters the first where the
task's ledger shows it halted, and redrives it where it shows it restored, so the real
queue does both. Releases and deadline halts are not replayed.

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
TASK_REPLAYABLE = {"task.added", "task.claimed", "task.done", "task.failed", "task.reaped",
                   "task.dead_lettered", "task.redriven", "task.halted", "task.restored"}
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
    """The task.added payload, and the actions in order: ["claim", outcome], ["redrive", None],
    ["halt", None] or ["restore", None].

    An outcome is ("done", None), ("failed", reason), ("reaped", reason), or None for a
    claim with no outcome yet. Refuses a deadline halt, since the deadline is not recorded.
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
        elif ev["kind"] == "task.reaped":
            actions[-1][1] = ("reaped", payload["reason"])
        elif ev["kind"] == "task.redriven":
            actions.append(["redrive", None])
        elif ev["kind"] == "task.halted":
            added.setdefault("depth", chain_depth(run_id, added["depends_on"], payload["reason"]))
            actions.append(["halt", None])
        elif ev["kind"] == "task.restored":
            actions.append(["restore", None])
    return added, actions


def chain_depth(run_id, depends_on, reason):
    """How many tasks up the recorded depends_on chain the dead-lettered task named in reason is.

    Refuses a halt for any other reason (a deadline), since replay can only cause it by a dead letter.
    """
    prefix = queue._blocked_by("")
    if depends_on is None or not reason.startswith(prefix):
        raise ValueError(f"task {run_id} was halted ({reason}), not behind a dead letter")
    dead, device = int(reason.removeprefix(prefix)), run_id.rsplit("-", 1)[0]
    depth, ancestor = 1, depends_on
    while ancestor != dead:
        ancestor = json.loads(recorded_events(f"{device}-{ancestor}")[0]["payload"])["depends_on"]
        depth += 1
    return depth


def recorded_work(outcome):
    """A do_work that plays back one recorded outcome instead of running anything."""
    status, reason = outcome

    def work(task):
        if status == "failed":
            raise RuntimeError(reason)
    return work


def _status(task_id):
    """The task's status in the scratch database."""
    con = db.connect()
    try:
        return con.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()["status"]
    finally:
        con.close()


def _expect(task_id, status, after):
    """Raise Diverged unless the harness left the task in status after the recorded action."""
    now = _status(task_id)
    if now != status:
        raise Diverged(f"diverged at {after}: the task is {now}, not {status}")


def _run_parent(parent, outcome):
    """Claim a stand-in ancestor and run it to outcome: done, or failed, which dead-letters it."""
    task = queue.claim("replay")
    if task is None or task["task_id"] != parent:
        raise Diverged("diverged: the queue did not offer a stand-in ancestor")
    worker._run_one(task, "replay", recorded_work(outcome))


def _claim(task_id, ancestors, outcome, n, clock):
    """Claim the task, after finishing its stand-in ancestors, and play back one recorded outcome."""
    for ancestor in ancestors:
        if _status(ancestor) != "done":
            _run_parent(ancestor, ("done", None))
    task = queue.claim("replay")
    if task is None or task["task_id"] != task_id:
        raise Diverged(f"diverged at claim {n}: the queue did not offer the task")
    if outcome and outcome[0] == "reaped":
        clock.skipped += queue.LEASE_TTL + 1  # the worker died; its lease runs out
        worker._reap("replay")
    elif outcome:
        worker._run_one(task, "replay", recorded_work(outcome))


def drive_task(added, actions):
    """Re-add the task, then claim, run, redrive, halt and restore it as the ledger shows.

    A task with a dependency gets a chain of stand-in ancestors (the first with
    max_attempts 1) as deep as its recorded halt reason shows, else one, left unfinished
    until the task's next claim. A recorded halt dead-letters the first, so the real queue
    halts the chain down to the task; a recorded restore redrives it. Returns the task's
    scratch run_id.
    """
    clock = Clock()
    with mock.patch.object(queue, "time", clock):
        ancestors = []
        if added["depends_on"] is not None:
            for _ in range(added.get("depth", 1)):
                parent = ancestors[-1] if ancestors else None
                ancestors.append(queue.add("stand-in ancestor", depends_on=parent, max_attempts=1))
        task_id = queue.add(
            added["task_kind"], depends_on=ancestors[-1] if ancestors else None,
            max_attempts=added["max_attempts"],
        )
        claims = 0
        for action, outcome in actions:
            clock.skipped += SKIP_AHEAD_S
            if action == "redrive":
                queue.redrive(task_id)
            elif action == "halt":
                _run_parent(ancestors[0], ("failed", "stand-in ancestor failed"))
                _expect(task_id, "halted", "halt")
            elif action == "restore":
                queue.redrive(ancestors[0])
                _expect(task_id, "ready", "restore")
            else:
                claims += 1
                _claim(task_id, ancestors, outcome, claims, clock)
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
    task = recorded_task(run_id, events) if is_task else None  # reads the real ledger, so before scratch_db
    with scratch_db(), contextlib.redirect_stdout(io.StringIO()):
        try:
            replayed = drive_task(*task) if is_task else drive(events)
            return end_state(recorded_events(replayed))
        except Diverged as e:
            return {"end": str(e), "failed_stage": None, "committed": []}
