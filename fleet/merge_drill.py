"""Drive the merge gate through refusals, a paused agent, the lock and a crash, and check each outcome.

    uv run python -u -m fleet.merge_drill

Works in a temporary directory with its own repo and database, so it never
touches agent.db. Takes a few seconds. Exits 1 if any check fails.
"""

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fleet import claim, db, merge

# Runs land() in a child that dies right after update-ref, before SQLite commits.
CRASH = """
import os, sys
from fleet import merge
real = merge._git
def die_after_update_ref(repo, *args):
    out = real(repo, *args)
    if args[0] == "update-ref":
        os._exit(9)
    return out
merge._git = die_after_update_ref
merge.land(sys.argv[1], sys.argv[2], sys.argv[3], {sys.argv[4]: int(sys.argv[5])})
"""


class Drill:
    def __init__(self, work):
        self.repo = work / "shared"
        self.wt = work / "agent"
        self.results = []

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def main_sha(self):
        return self.git("rev-parse", "refs/heads/main")

    def check(self, label, actual, expected):
        held = actual == expected
        print(f"{'PASS' if held else 'FAIL'}  {label}: {actual}")
        if not held:
            print(f"      expected: {expected}")
        self.results.append(held)

    def setup(self):
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "drill@localhost")
        self.git("config", "user.name", "drill")
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.repo / name).write_text(f"{name}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def branch(self, name, edits, base="main", renames=()):
        """Commit edits ({path: text}) and renames ((old, new), ...) on a new branch from base, in the agent worktree."""
        self.git("switch", "-q", "-c", name, base, cwd=self.wt)
        for path, text in edits.items():
            (self.wt / path).write_text(text)
        for old, new in renames:
            self.git("mv", old, new, cwd=self.wt)
        self.git("add", "-A", cwd=self.wt)
        self.git("commit", "-qm", name, cwd=self.wt)

    def merge(self, branch, run_id, fences):
        """Run the merge process. Returns its exit code."""
        args = [sys.executable, "-m", "fleet.merge", branch, "--run-id", run_id, "--repo", str(self.repo)]
        for resource, fence in fences.items():
            args += ["--fence", f"{resource}={fence}"]
        return subprocess.run(args, capture_output=True, text=True).returncode

    def refused(self, label, branch, run_id, fences):
        before = self.main_sha()
        self.check(f"{label}: exit code", self.merge(branch, run_id, fences), 1)
        self.check(f"{label}: main unchanged", self.main_sha() == before, True)

    def landed(self, label, branch, run_id, fences):
        self.check(f"{label}: exit code", self.merge(branch, run_id, fences), 0)
        self.check(f"{label}: main merges {branch}", self.git("rev-parse", "main^2") == self.git("rev-parse", branch), True)


def _claims():
    """[(resource, run_id), ...] for every claim row, sorted."""
    con = db.connect()
    try:
        return [tuple(r) for r in con.execute("SELECT resource, run_id FROM claims ORDER BY resource")]
    finally:
        con.close()


def _merge_events():
    con = db.connect()
    try:
        rows = con.execute("SELECT kind, payload FROM events WHERE kind LIKE 'merge.%' ORDER BY event_id")
        return [(r["kind"], json.loads(r["payload"])) for r in rows]
    finally:
        con.close()


def _refusals(d):
    d.check("main checked out: exit code", d.merge("main", "run-x", {}), 1)
    d.git("switch", "-q", "--detach")
    d.git("worktree", "add", "-q", "--detach", str(d.wt), "main")

    d.branch("live", {"a.txt": "a2\n"})
    d.landed("live claim", "live", "run-a", {"file:a.txt": claim.acquire("file:a.txt", "run-a", "A"),
                                             "file:e.txt": claim.acquire("file:e.txt", "run-a", "A")})
    d.check("live claim: every presented claim released", _claims(), [])

    d.branch("unclaimed", {"b.txt": "b2\n"})
    d.refused("no fence", "unclaimed", "run-b", {})
    expired = claim.acquire("file:b.txt", "run-b", "B", ttl=0.01)
    time.sleep(0.05)
    d.refused("expired claim, no successor", "unclaimed", "run-b", {"file:b.txt": expired})

    paused = claim.acquire("file:b.txt", "run-b", "B", ttl=0.01)
    time.sleep(0.05)
    successor = claim.acquire("file:b.txt", "run-c", "C")
    d.refused("paused agent after takeover", "unclaimed", "run-b", {"file:b.txt": paused})
    d.landed("successor", "unclaimed", "run-c", {"file:b.txt": successor})

    d.branch("clash", {"a.txt": "other\n"}, base=d.git("rev-list", "--max-parents=0", "main"))
    d.refused("conflict", "clash", "run-a", {"file:a.txt": claim.acquire("file:a.txt", "run-a", "A")})
    d.check("conflict: claim still held", ("file:a.txt", "run-a") in _claims(), True)

    d.branch("rename", {}, renames=[("c.txt", "d.txt")])
    new_path = claim.acquire("file:d.txt", "run-a", "A")
    d.refused("rename, only new path claimed", "rename", "run-a", {"file:d.txt": new_path})
    d.landed("rename, both paths claimed", "rename", "run-a",
             {"file:d.txt": new_path, "file:c.txt": claim.acquire("file:c.txt", "run-a", "A")})


def _lock(d):
    d.branch("waits", {"a.txt": "a3\n"})
    fence = claim.acquire("file:a.txt", "run-a", "A")
    lock = Path(d.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "iterum-merge.lock"
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        child = subprocess.Popen([sys.executable, "-m", "fleet.merge", "waits", "--run-id", "run-a",
                                  "--repo", str(d.repo), "--fence", f"file:a.txt={fence}"])
        time.sleep(2)
        d.check("lock held: merge still waiting", child.poll(), None)
    d.check("lock released: exit code", child.wait(timeout=30), 0)


def _crash(d):
    d.branch("crashes", {"b.txt": "b3\n"})
    fence = claim.acquire("file:b.txt", "run-c", "C")
    code = subprocess.run([sys.executable, "-c", CRASH, str(d.repo), "crashes", "run-c", "file:b.txt", str(fence)]).returncode
    d.check("crash after update-ref: exit code", code, 9)
    d.check("crash after update-ref: main merges crashes", d.git("rev-parse", "main^2") == d.git("rev-parse", "crashes"), True)
    d.check("crash after update-ref: last event", _merge_events()[-1][0], "merge.started")

    d.branch("next", {"a.txt": "a5\n"})
    d.landed("next merge after the crash", "next", "run-a", {"file:a.txt": claim.acquire("file:a.txt", "run-a", "A")})
    recovered = [(k, p["branch"]) for k, p in _merge_events() if p.get("recovered")]
    d.check("crash settled by the next merge", recovered, [("merge.landed", "crashes")])
    d.check("crash settled: its claim released", ("file:b.txt", "run-c") in _claims(), False)


def _moved(d):
    d.branch("moved", {"a.txt": "a4\n"})
    fence = claim.acquire("file:a.txt", "run-a", "A")
    real = merge.build

    def build_then_move(repo, target, branch):
        built = real(repo, target, branch)
        d.git("update-ref", "refs/heads/main", d.git("commit-tree", "main^{tree}", "-p", "main", "-m", "someone else"))
        return built

    merge.build = build_then_move
    try:
        merge.land(d.repo, "moved", "run-a", {"file:a.txt": fence})
        d.check("target moved after build: refused", False, True)
    except subprocess.CalledProcessError:
        d.check("target moved after build: refused", True, True)
    finally:
        merge.build = real
    d.check("target moved after build: outcome", _merge_events()[-1][0], "merge.abandoned")


def _every_start_settled(d):
    events = _merge_events()
    started = sorted(p["merge_id"] for k, p in events if k == "merge.started")
    settled = sorted(p["merge_id"] for k, p in events if k != "merge.started")
    d.check("every merge.started has one outcome", started == settled, True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        os.environ.update(ITERUM_DB=str(work / "drill.db"), ITERUM_DEVICE="drill")
        db.DB = work / "drill.db"
        db.init()
        d = Drill(work)
        d.setup()
        for part in (_refusals, _lock, _crash, _moved, _every_start_settled):
            part(d)
        passed = all(d.results)
    print("drill passed" if passed else "drill FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
