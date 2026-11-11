"""Resumable runs. Every step is written to the ledger BEFORE it executes.

    uv run python -u -m fleet.run                     # the six-step drill plan below
    uv run python -u -m fleet.run --plan myplan.json  # your own plan
    uv run python -u -m fleet.run --resume <run_id>   # pick up uncommitted steps
    uv run python -u -m fleet.run --resume <run_id> --plan myplan.json   # resuming your own plan
    uv run python -u -m fleet.run --resume <run_id> --force           # resume a halted run after review
    uv run python -u -m fleet.run --plan myplan.json --allow-claude 0.50   # a plan with prompt steps, each capped at $0.50 (billed)

Always with `-u`. A killed process does not flush its buffers, so without it
output that is piped or redirected is lost and you conclude the wrapper did nothing.
"""

import argparse
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from fleet import claim, db, governor, recovery
from fleet.proc import group_alive, stop_on_sigterm

HEARTBEAT = 10  # seconds between heartbeat_at updates; fleet.recovery's expiry must be several of these
CLAIM_TTL = float(os.environ.get("ITERUM_CLAIM_TTL", claim.DEFAULT_TTL))  # seconds; must be several HEARTBEATs
MAX_TURNS = 10  # a prompt step's --max-turns; a guess until the first paid run
# Only the file tools exist in a prompt step's session; edits need no approval, and anything that
# would ask is denied, since nobody is there to answer (`claude --help`, Claude Code 2.1.322).
CLAUDE_TOOLS = ["--tools", "Read,Edit,Write", "--permission-mode", "acceptEdits", "--permission-prompts", "none"]


def _spawn(args, run_id, seq, env=None):
    """Run one step's process and return (returncode, stdout, stderr).

    The process gets its own process group, recorded on the step, so a resume can
    tell whether a killed run.py left it running. Being outside the terminal's
    foreground group, it misses Ctrl-C, so a KeyboardInterrupt kills the group here.
    A string is run by the shell; a list is run directly.
    """
    p = subprocess.Popen(
        args, shell=isinstance(args, str), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True, env=env,
    )
    with db.write() as con:
        con.execute("UPDATE steps SET pgid=? WHERE run_id=? AND seq=?", (p.pid, run_id, seq))
    try:
        stdout, stderr = p.communicate()
    except KeyboardInterrupt:
        os.killpg(p.pid, signal.SIGKILL)
        raise
    return p.returncode, stdout, stderr


def shell(cmd, run_id, seq):
    """One shell step's side effect. Returns a short result string."""
    code, stdout, stderr = _spawn(cmd, run_id, seq)
    if code != 0:
        raise RuntimeError(f"step failed with exit {code}: {stderr.strip()}")
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
    An uncommitted prompt step also needs force: it may have edited files, and a rerun is billed again.
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
    planned = {seq: intent for seq, intent, *_ in plan}
    for r in recorded:
        if planned.get(r["seq"]) != r["intent"]:
            sys.exit(
                f"run {run_id} does not match this plan at step {r['seq']}.\n"
                f"  recorded: {r['intent']!r}\n"
                f"  plan:     {planned.get(r['seq'])!r}\n"
                "resume it with the same plan you started it with:\n"
                f"  uv run python -u -m fleet.run --resume {run_id} --plan yourplan.json"
            )
    commands = {seq: cmd for seq, _, cmd, _ in plan}
    for r in recorded:
        if r["status"] != "committed" and is_prompt(commands[r["seq"]]) and not force:
            sys.exit(
                f"run {run_id} step {r['seq']} is a prompt step that did not commit: it may already have edited files,\n"
                "and running it again is a second billed session. Check the run's branch first:\n"
                "  git status && git diff\n"
                "then resume, which runs the step again:\n"
                f"  uv run python -u -m fleet.run --resume {run_id} --plan yourplan.json --allow-claude <usd> --force"
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


def beat(run_id, stop, fences, lost):
    """Refresh heartbeat_at every HEARTBEAT seconds, and renew the run's claims once half CLAIM_TTL has passed, until stop is set. Runs in its own thread.

    A refused renewal appends the reason to lost, kills the running step's process group and ends the thread.
    A locked database skips one beat, since losing the thread would make a live run look dead.
    """
    renewed_at = time.time()
    while not stop.wait(HEARTBEAT):
        try:
            with db.write() as con:
                con.execute(
                    "UPDATE runs SET heartbeat_at=? WHERE run_id=?", (time.time(), run_id)
                )
            if fences and time.time() - renewed_at >= CLAIM_TTL / 2:
                for resource, fence in fences.items():
                    claim.renew(resource, run_id, fence, CLAIM_TTL)
                renewed_at = time.time()
        except sqlite3.OperationalError as e:
            if e.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise
        except claim.Refused as e:
            lost.append(str(e))
            kill_running_step(run_id)
            return


def kill_running_step(run_id):
    """Kill the process group of the run's proposed step, if it has one still alive."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT pgid FROM steps WHERE run_id=? AND status='proposed' AND pgid IS NOT NULL", (run_id,)
        ).fetchone()
    finally:
        con.close()
    if row and group_alive(row["pgid"]):
        os.killpg(row["pgid"], signal.SIGKILL)


def fail_if_lost(run_id, seq, lost):
    """Fail the step and the run if the heartbeat thread lost a claim."""
    if lost:
        error = f"claim lost: {lost[0]}"
        record_failure(run_id, seq, error)
        raise RuntimeError(error)


def claim_files(run_id, plan):
    """Claim every resource the plan declares, in sorted order, before any step runs. Returns {resource: fence}.

    All up front, because the merge needs claims on committed steps' files too and a
    resumed process gets new fences. On a refusal it releases what it took and re-raises.
    """
    con = db.connect()
    try:
        agent = con.execute("SELECT agent FROM runs WHERE run_id=?", (run_id,)).fetchone()["agent"]
    finally:
        con.close()
    fences = {}
    try:
        for resource in sorted({r for *_, resources in plan for r in resources}):
            fences[resource] = claim.acquire(resource, run_id, agent, CLAIM_TTL)
    except claim.Refused:
        for resource, fence in fences.items():
            claim.release(resource, run_id, fence)
        raise
    return fences


def run_branch(target):
    """The current branch. Exits on a detached HEAD, outside a repo, or on target.

    A run that declares files must reach target only through fleet.merge; its commits
    would otherwise land on target directly, past every claim check.
    """
    head = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        sys.exit(f"a plan that declares files must run on a branch: {head.stderr.strip() or 'HEAD is detached'}")
    branch = head.stdout.strip()
    if branch == target:
        sys.exit(f"a plan that declares files must not run on {target}: its commits would skip fleet.merge. Use your own branch.")
    return branch


def execute(run_id, plan, branch=None, target="main", cap_usd=None):
    try:
        fences = claim_files(run_id, plan)
    except claim.Refused as e:
        db.finish_run(run_id, "failed")
        sys.exit(f"run {run_id} refused before any step ran: {e}")
    mark_running(run_id)
    stop = threading.Event()
    lost = []  # the heartbeat thread appends why it lost a claim
    threading.Thread(target=beat, args=(run_id, stop, fences, lost), daemon=True).start()
    try:
        run_steps(run_id, plan, lost, cap_usd)
    finally:
        stop.set()
    if fences:
        flags = " ".join(f"--fence {r}={f}" for r, f in fences.items())
        to = "" if target == "main" else f" --target {target}"
        print(f"land with: uv run python -m fleet.merge {branch} --run-id {run_id}{to} {flags}")


def stop_at_ceiling(run_id, seq, cap_usd=None):
    """Halt the run, resumably, unless the fleet's headroom covers the next step.

    A prompt step needs headroom of at least its whole cap (cap_usd), so it is never
    started with less than its --max-budget-usd; a shell step needs headroom above zero.
    Checked before a step is proposed, so a halted run has no step in flight.
    The cap is Claude Code's own estimate and spend can pass it, so a run can still
    pass the ceiling by however far one step passes its cap.
    """
    left = governor.headroom()
    need = f"its cap of {cap_usd:.4f} USD" if cap_usd is not None else "more than 0 USD"
    if (left >= cap_usd) if cap_usd is not None else (left > 0):
        return
    governor.halt_resumable(run_id, f"headroom {left:.4f} USD before step {seq}, which needs {need}")
    sys.exit(
        f"run {run_id} stopped before step {seq}: fleet headroom is {left:.4f} USD and the step needs {need}.\n"
        "raise the ceiling (or lower --allow-claude), then resume with the same plan:\n"
        "  uv run python -m fleet.governor set <usd>\n"
        f"  uv run python -u -m fleet.run --resume {run_id} [--plan yourplan.json]"
    )


def is_prompt(cmd):
    """True for a prompt step, {"prompt": ...}; False for a shell command string."""
    return isinstance(cmd, dict)


def run_steps(run_id, plan, lost, cap_usd=None):
    done = committed_seqs(run_id)
    if done:
        print(f"resuming {run_id}, {len(done)} step(s) already committed")

    for seq, intent, cmd, _ in plan:
        if seq in done:
            print(f"  step {seq}  already committed, skipping")
            continue

        stop_at_ceiling(run_id, seq, cap_usd if is_prompt(cmd) else None)

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

        fail_if_lost(run_id, seq, lost)
        try:
            if is_prompt(cmd):  # <-- the side effect
                result = claude_step(cmd["prompt"], run_id, seq, cap_usd, cmd.get("model"))
            else:
                result = shell(cmd, run_id, seq)
        except RuntimeError as e:
            fail_if_lost(run_id, seq, lost)  # a step killed for a lost claim reports why
            record_failure(run_id, seq, str(e))
            raise
        fail_if_lost(run_id, seq, lost)  # the step may have finished before the kill reached it

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


def claude_env(run_id):
    """os.environ plus iterum.run_id in OTEL_RESOURCE_ATTRIBUTES, so telemetry logs spend under this run."""
    env = dict(os.environ)
    attrs = env.get("OTEL_RESOURCE_ATTRIBUTES")
    env["OTEL_RESOURCE_ATTRIBUTES"] = f"{attrs},iterum.run_id={run_id}" if attrs else f"iterum.run_id={run_id}"
    return env


def gate_settings(run_id):
    """--settings JSON that runs fleet/gate.py before every Edit or Write, as this run.

    ITERUM_DB and FLEET_RUN_ID are set in the hook's own command, so the hook does not
    depend on inheriting claude's environment. gate.py refuses an edit to a file another
    run has claimed; fleet.merge still checks every changed file if the hook does not run.
    """
    command = shlex.join([
        "env", f"ITERUM_DB={db.DB.resolve()}", f"FLEET_RUN_ID={run_id}",
        sys.executable, str(Path(__file__).with_name("gate.py").resolve()),
    ])
    hook = {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": command}]}
    return json.dumps({"hooks": {"PreToolUse": [hook]}})


def parse_envelope(stdout):
    """claude's JSON result envelope, or {} when stdout is not JSON.

    A failing claude still prints its envelope (exit 1, "Not logged in", docs/claude-step-design.md);
    a step killed for a lost claim prints nothing.
    """
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def log_finished(run_id, seq, code, envelope):
    """Log claude.finished: the exit code and the envelope fields that make a paid run evidence."""
    fields = ("session_id", "total_cost_usd", "num_turns", "is_error", "permission_denials")
    with db.write() as con:
        db.log(
            con, run_id, "claude.finished", stage="tool_execution", seq=seq,
            exit_code=code, **{k: envelope.get(k) for k in fields},
        )


def claude_step(prompt, run_id, seq, cap_usd, model=None):
    """One prompt step: `claude -p`. Returns a short result string.

    model, if given, goes to --model (an alias or a full name such as "claude-haiku-5-5");
    without it the session uses the user's default model.

    THIS COSTS MONEY. Every call is billed to you. Only reached with --allow-claude,
    whose cap goes to --max-budget-usd, a client-side estimate that spend can pass.
    Fails on a non-zero exit or "is_error": true; never on subtype, which can read
    "success" on an error (docs/claude-step-design.md).
    """
    argv = [
        "claude", "-p", prompt, "--output-format", "json",
        "--max-turns", str(MAX_TURNS), "--max-budget-usd", str(cap_usd),
        *CLAUDE_TOOLS, "--settings", gate_settings(run_id),
        *(["--model", model] if model else []),
    ]
    code, stdout, stderr = _spawn(argv, run_id, seq, env=claude_env(run_id))
    envelope = parse_envelope(stdout)
    log_finished(run_id, seq, code, envelope)
    if code != 0:
        raise RuntimeError(f"claude failed with exit {code}: {(stdout or stderr).strip()[:200]}")
    if envelope["is_error"]:
        raise RuntimeError(f"claude reported an error: {envelope.get('result')}")
    return str(envelope.get("result", ""))[:200]


# The drill plan. Shell commands on purpose, so you can run the kill-and-resume
# without spending anything and without waiting on a model. Step 4 does its side
# effect and then sleeps, so a kill can land in the gap between the effect and
# the commit; step 5 sleeps long enough to be a comfortable kill window.
PLAN = [
    (1, "create the work directory", "mkdir -p out && echo ok", ()),
    (2, "fetch the file list", "ls fleet > out/filelist.txt && echo ok", ()),
    (3, "count the lines", "wc -l < out/filelist.txt > out/count.txt && echo ok", ()),
    (4, "the slow one", "echo ok > out/step4.txt && sleep 3", ()),
    (5, "write the summary", "sleep 20 && echo summary > out/summary.txt", ()),
    (6, "verify", "ls out | wc -l", ()),
]


def notice_dead_runs():
    """Print stale running runs and a count of failed ones, with the fleet.recovery command. Reads only.

    A SIGKILLed run stays `running` with nothing left to report it, so it is listed.
    A failed run reported itself when it exited, so it is only counted.
    """
    dead = recovery.dead_runs()
    if not dead:
        return
    stale = [(run_id, idle) for run_id, _, _, status, idle in dead if status == "running"]
    failed = sum(1 for *_, status, _ in dead if status == "failed")
    if stale:
        print(f"{len(stale)} run(s) look dead (no heartbeat for over {recovery.IDLE_SECONDS}s):")
        for run_id, idle in stale:
            print(f"  {run_id}  running  idle {idle:.0f}s")
    if failed:
        print(f"{failed} failed run(s).")
    print("see: uv run python -m fleet.recovery")


def check_prompt_steps(plan, cap_usd):
    """Exit if the plan has prompt steps without --allow-claude, or a prompt step that declares no files.

    A prompt step's files are claimed like any other, which puts the run on its own branch,
    lets gate.py refuse edits to other runs' files, and lets fleet.merge land the edits.
    """
    prompts = [(seq, resources) for seq, _, cmd, resources in plan if is_prompt(cmd)]
    if prompts and cap_usd is None:
        sys.exit("this plan has prompt steps, which are billed to you. Pass --allow-claude <usd>, the cap for each step.")
    for seq, resources in prompts:
        if not resources:
            sys.exit(
                f"prompt step {seq} declares no files. List the files it may edit as its fourth field,\n"
                '  e.g. [1, "fix the typo", {"prompt": "..."}, ["file:a.txt"]]'
            )


def load_plan(path):
    """Read a plan from JSON: [[seq, intent, command, [resource, ...]], ...]. The resources are optional.

    A command is a shell command string, or {"prompt": "...", "model": "..."} ("model" optional) for a prompt step run by
    claude_step(). Each resource, such as "file:src/a.py", is claimed before any step runs; see claim_files().

    A tool whose only input is a literal in its own source is a demonstration.
    Point this at your own steps and the rest of the module does not change.
    """
    raw = json.loads(open(path).read())
    return [
        (int(seq), str(intent), cmd if is_prompt(cmd) else str(cmd), tuple(rest[0]) if rest else ())
        for seq, intent, cmd, *rest in raw
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="uv run python -u -m fleet.run")
    parser.add_argument("--plan", help="JSON plan file (default: the built-in drill)")
    parser.add_argument("--resume", metavar="RUN_ID", help="resume this run")
    parser.add_argument("--force", action="store_true", help="resume a halted run")
    parser.add_argument("--target", default="main", help="the branch fleet.merge lands on; a plan that declares files may not run on it")
    parser.add_argument("--allow-claude", metavar="USD", type=float, help="run prompt steps, each capped at this many USD (billed)")
    args = parser.parse_args()
    stop_on_sigterm()
    plan = load_plan(args.plan) if args.plan else PLAN
    check_prompt_steps(plan, args.allow_claude)
    branch = run_branch(args.target) if any(resources for *_, resources in plan) else None

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    notice_dead_runs()
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
    execute(run_id, plan, branch, args.target, args.allow_claude)
