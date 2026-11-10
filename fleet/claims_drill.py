"""Drive fleet.run's declared claims through a refusal, a resume, renewal and a paused-agent takeover.

    uv run python -u -m fleet.claims_drill

Works in a temporary directory with its own repo and database, so it never
touches agent.db. Uses a 20-second claim TTL, so a run takes about a minute.
Exits 1 if any check fails.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fleet import claim, db
from fleet.proc import group_alive

CLAIM_TTL = 20  # must be several of fleet.run's 10-second HEARTBEATs
ROOT = Path(__file__).resolve().parent.parent  # the worktree is the cwd, so fleet must be found by PYTHONPATH


class Drill:
    def __init__(self, work):
        self.work = work
        self.repo = work / "shared"
        self.wt = work / "agent"
        self.results = []

    def check(self, label, actual, expected):
        held = actual == expected
        print(f"{'PASS' if held else 'FAIL'}  {label}: {actual}")
        if not held:
            print(f"      expected: {expected}")
        self.results.append(held)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def setup(self):
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "drill@localhost")
        self.git("config", "user.name", "drill")
        for name in ("a.txt", "b.txt"):
            (self.repo / name).write_text(f"{name}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.git("switch", "-q", "--detach")
        self.git("worktree", "add", "-q", "-b", "agent", str(self.wt), "main")

    def plan(self, name, steps):
        path = self.work / f"{name}.json"
        path.write_text(json.dumps(steps))
        return path

    def run_args(self, *args):
        return [sys.executable, "-u", "-m", "fleet.run", *map(str, args)]

    def run(self, *args, cwd=None):
        """Run fleet.run in the agent worktree, or cwd. Returns (exit code, output)."""
        p = subprocess.run(self.run_args(*args), cwd=cwd or self.wt, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def merge(self, run_id, fences):
        args = [sys.executable, "-m", "fleet.merge", "agent", "--run-id", run_id, "--repo", str(self.repo)]
        for resource, fence in fences.items():
            args += ["--fence", f"{resource}={fence}"]
        return subprocess.run(args, capture_output=True, text=True).returncode


def _edit(seq, path, text, sleep=0):
    """A plan step that edits path in the worktree and commits it, declaring the file."""
    pause = f"sleep {sleep} && " if sleep else ""
    return [seq, f"edit {path}", f"{pause}echo {text} > {path} && git commit -qam 'edit {path}' && echo ok", [f"file:{path}"]]


def _run_id(output):
    return re.search(r"run ([0-9a-f]{12}) started", output).group(1)


def _printed_fences(output):
    """The --fence flags from the run's 'land with:' line, as {resource: fence}."""
    line = next(l for l in output.splitlines() if l.startswith("land with:"))
    return {r: int(f) for r, f in re.findall(r"--fence (\S+)=(\d+)", line)}


def _query(sql, *params):
    con = db.connect()
    try:
        return [tuple(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def _claims():
    return _query("SELECT resource, run_id FROM claims ORDER BY resource")


def _wrong_branch(d):
    plan = d.plan("wrong", [_edit(1, "a.txt", "a1")])
    head = d.git("rev-parse", "agent")
    code, out = d.run("--plan", plan, "--target", "agent")
    d.check("on the target branch: exit code", code, 1)
    d.check("on the target branch: reason", "must not run on agent" in out, True)
    code, out = d.run("--plan", plan, cwd=d.repo)
    d.check("detached HEAD: exit code", code, 1)
    d.check("detached HEAD: reason", "HEAD is detached" in out, True)
    d.check("wrong branch: no run recorded, no commit", (_query("SELECT count(*) FROM runs"), d.git("rev-parse", "agent")), ([(0,)], head))


def _declared(d):
    code, out = d.run("--plan", d.plan("declared", [_edit(1, "a.txt", "a2"), _edit(2, "b.txt", "b2")]))
    run_id = _run_id(out)
    d.check("declared: run exit code", code, 0)
    d.check("declared: claims granted", _query(
        "SELECT json_extract(payload,'$.resource') FROM events WHERE run_id=? AND kind='claim.granted' ORDER BY 1", run_id),
        [("file:a.txt",), ("file:b.txt",)])
    d.check("declared: lands with the printed fences", d.merge(run_id, _printed_fences(out)), 0)
    d.check("declared: no claims after landing", _claims(), [])


def _held(d):
    held = claim.acquire("file:b.txt", "other", "X")
    code, out = d.run("--plan", d.plan("held", [_edit(1, "a.txt", "a3"), _edit(2, "b.txt", "b3")]))
    run_id = _run_id(out)
    d.check("held file: run exit code", code, 1)
    d.check("held file: run status", _query("SELECT status FROM runs WHERE run_id=?", run_id), [("failed",)])
    d.check("held file: steps run", _query("SELECT count(*) FROM steps WHERE run_id=?", run_id), [(0,)])
    d.check("held file: first file released", _claims(), [("file:b.txt", "other")])
    claim.release("file:b.txt", "other", held)


def _resume(d):
    failing = d.plan("failing", [_edit(1, "a.txt", "a4"), [2, "edit b.txt", "exit 1", ["file:b.txt"]]])
    code, out = d.run("--plan", failing)
    run_id = _run_id(out)
    d.check("resume: first attempt exit code", code, 1)
    old = dict(_query("SELECT resource, fence FROM claims WHERE run_id=?", run_id))
    code, out = d.run("--resume", run_id, "--plan", d.plan("fixed", [_edit(1, "a.txt", "a4"), _edit(2, "b.txt", "b4")]))
    new = _printed_fences(out)
    d.check("resume: exit code", code, 0)
    d.check("resume: every fence is new", all(new[r] > old[r] for r in old), True)
    d.check("resume: old fences refused", d.merge(run_id, old), 1)
    d.check("resume: new fences land", d.merge(run_id, new), 0)


def _renewed(d):
    code, out = d.run("--plan", d.plan("long", [_edit(1, "a.txt", "a5", sleep=CLAIM_TTL + 5)]))
    run_id = _run_id(out)
    renewals = _query("SELECT count(*) FROM events WHERE run_id=? AND kind='claim.renewed'", run_id)[0][0]
    d.check(f"step longer than the {CLAIM_TTL}s TTL: exit code", code, 0)
    d.check("step longer than the TTL: renewed", renewals > 0, True)
    d.check("step longer than the TTL: lands", d.merge(run_id, _printed_fences(out)), 0)


def _expired_renew(d):
    fence = claim.acquire("file:z.txt", "lapsed", "L", ttl=0.01)
    time.sleep(0.05)
    try:
        claim.renew("file:z.txt", "lapsed", fence)
        refused = False
    except claim.Refused:
        refused = True
    d.check("renew of an expired claim, nobody else holding it: refused", refused, True)


def _taken(d):
    p = subprocess.Popen(d.run_args("--plan", d.plan("taken", [_edit(1, "b.txt", "b6", sleep=60)])),
                         cwd=d.wt, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while not _query("SELECT 1 FROM claims WHERE resource='file:b.txt'"):
        time.sleep(0.2)
    os.kill(p.pid, signal.SIGSTOP)
    print(f"paused fleet.run; waiting about {CLAIM_TTL}s for its claim to expire")
    while True:
        try:
            claim.acquire("file:b.txt", "thief", "T")
            break
        except claim.Refused:
            time.sleep(1)
    os.kill(p.pid, signal.SIGCONT)
    out = p.communicate(timeout=60)[0]
    run_id = _run_id(out)
    error = _query("SELECT json_extract(payload,'$.error') FROM events WHERE run_id=? AND kind='step.failed'", run_id)
    pgid = _query("SELECT pgid FROM steps WHERE run_id=?", run_id)[0][0]
    d.check("paused agent taken over: exit code", p.returncode, 1)
    d.check("paused agent taken over: step", _query("SELECT status FROM steps WHERE run_id=?", run_id), [("failed",)])
    d.check("paused agent taken over: reason", [e[0].startswith("claim lost: file:b.txt") for e in error], [True])
    d.check("paused agent taken over: step's command killed", group_alive(pgid), False)
    d.check("paused agent taken over: file untouched", (d.wt / "b.txt").read_text(), "b4\n")


def _terminated(d):
    p = subprocess.Popen(d.run_args("--plan", d.plan("term", [_edit(1, "a.txt", "a7", sleep=60)])),
                         cwd=d.wt, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while not (row := _query("SELECT pgid FROM steps WHERE status='proposed' AND pgid IS NOT NULL")):
        time.sleep(0.2)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=10)
    time.sleep(0.2)
    d.check("SIGTERM mid-step: step's command killed", group_alive(row[0][0]), False)
    d.check("SIGTERM mid-step: file untouched", (d.wt / "a.txt").read_text(), "a5\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        os.environ.update(ITERUM_DB=str(work / "drill.db"), ITERUM_DEVICE="drill",
                          ITERUM_CLAIM_TTL=str(CLAIM_TTL), PYTHONPATH=str(ROOT))
        db.DB = work / "drill.db"
        db.init()
        d = Drill(work)
        d.setup()
        for part in (_wrong_branch, _declared, _held, _resume, _expired_renew, _renewed, _taken, _terminated):
            part(d)
        passed = all(d.results)
    print("drill passed" if passed else "drill FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
