"""Land an agent's branch on the shared branch, only while it holds a live claim on every file it changed."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from fleet import claim, db
from fleet.proc import stop_on_sigterm

OUTPUT_TAIL = 2000


class Conflict(Exception):
    """The branch does not merge cleanly into the target."""


class Empty(Exception):
    """Merging the branch would not change the target's files, for example because it already landed."""


class CheckFailed(Exception):
    """The check command failed on the merged tree."""


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def build(repo, target, branch):
    """Build the merge commit without touching any working tree. Return (old target commit, merge commit)."""
    old = _git(repo, "rev-parse", f"refs/heads/{target}")
    merged = subprocess.run(
        ["git", "-C", str(repo), "merge-tree", "--write-tree", old, branch],
        capture_output=True,
        text=True,
    )
    if merged.returncode == 1:
        raise Conflict(f"{branch} does not merge cleanly into {target}:\n{merged.stdout}")
    merged.check_returncode()
    tree = merged.stdout.splitlines()[0]
    if tree == _git(repo, "rev-parse", f"{old}^{{tree}}"):
        raise Empty(f"merging {branch} would not change {target}")
    new = _git(repo, "commit-tree", tree, "-p", old, "-p", branch, "-m", f"Merge {branch} into {target}")
    return old, new


def changed_resources(repo, old, branch):
    """The claim resources for every file the branch changed since it left old. A rename names both paths."""
    names = _git(repo, "diff", "--name-only", "--no-renames", f"{old}...{branch}")
    return sorted(f"file:{name}" for name in names.splitlines())


def run_check(repo, commit, command):
    """Run command in a temporary detached worktree of commit. Return (exit code, combined output).

    The worktree is always removed. The command runs in its own process group, killed on Ctrl-C.
    """
    tmp = tempfile.mkdtemp(prefix="iterum-check-")
    tree = Path(tmp) / "tree"
    _git(repo, "worktree", "add", "--detach", str(tree), commit)
    try:
        p = subprocess.Popen(
            command, shell=True, cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        try:
            output, _ = p.communicate()
        except KeyboardInterrupt:
            os.killpg(p.pid, signal.SIGKILL)
            raise
        return p.returncode, output
    finally:
        _git(repo, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(tmp, ignore_errors=True)


def land(repo, branch, run_id, fences, target="main", check=None):
    """Merge branch into target if fences (resource -> fence) holds a live claim on every changed file.

    With check, a shell command, it must first exit 0 in a worktree of the merged commit.
    Landing releases every claim in fences, in the same block. A refusal keeps them, so the caller can retry.
    Raises Conflict, Empty, CheckFailed, Refused or Fenced, or CalledProcessError if target moved since the build.
    """
    old, new = build(repo, target, branch)
    needed = changed_resources(repo, old, branch)
    # Write-ahead: a crash after update-ref but before the block commits leaves this for reconcile().
    merge_id = str(uuid.uuid7())  # the commit hash can repeat: commit-tree timestamps to the second
    with db.write() as con:
        db.log(con, run_id, "merge.started", stage="coordination", merge_id=merge_id, branch=branch, target=target, old=old, commit=new, fences=fences)
    if check:
        # Outside any db.write(): BEGIN IMMEDIATE would block every other writer for the whole check.
        code, output = run_check(repo, new, check)
        if code != 0:
            with db.write() as con:
                db.log(con, run_id, "merge.refused", stage="coordination", merge_id=merge_id, branch=branch, target=target,
                       commit=new, reason="check failed", check=check, exit_code=code, output=output[-OUTPUT_TAIL:])
            raise CheckFailed(f"check failed with exit {code}: {check}\n{output[-OUTPUT_TAIL:]}")
    refused = None
    try:
        with db.write() as con:
            try:
                for resource in needed:
                    if resource not in fences:
                        raise claim.Refused(f"{resource}: changed by {branch} but not claimed")
                    claim.require_claim(con, resource, fences[resource])
            except (claim.Refused, claim.Fenced) as e:
                refused = e
                db.log(con, run_id, "merge.refused", stage="coordination", merge_id=merge_id, branch=branch, target=target, commit=new, reason=str(e))
            else:
                db.log(con, run_id, "merge.landed", stage="coordination", merge_id=merge_id, branch=branch, target=target, commit=new, resources=needed)
                for resource, fence in fences.items():
                    claim.release_in(con, resource, run_id, fence)
                # Inside the block: no newer fence can be issued between the check and the move.
                _git(repo, "update-ref", f"refs/heads/{target}", new, old)
    except subprocess.CalledProcessError as e:
        # update-ref refused, so the block rolled back. Record the outcome now rather than at the next reconcile().
        with db.write() as con:
            db.log(con, run_id, "merge.abandoned", stage="coordination", merge_id=merge_id, branch=branch, target=target, commit=new, reason=e.stderr.strip())
        raise
    # Raised after the block: raising inside it would roll back the merge.refused event.
    if refused:
        raise refused
    return new


def _unsettled(con):
    """This device's merge.started events with no outcome. Other devices' merges are not in this repo."""
    return con.execute(
        "SELECT run_id, payload FROM events s WHERE kind='merge.started' AND device=?"
        " AND NOT EXISTS (SELECT 1 FROM events o"
        "  WHERE o.kind IN ('merge.landed','merge.refused','merge.abandoned')"
        "  AND json_extract(o.payload,'$.merge_id') = json_extract(s.payload,'$.merge_id'))",
        (db.device(),),
    ).fetchall()


def reconcile(repo):
    """Settle merges a crash left without an outcome. Run when the merge process starts, before any land().

    A merge commit already in its target landed, and its claims are released; any other was abandoned.
    """
    with db.write() as con:
        for row in _unsettled(con):
            p = json.loads(row["payload"])
            ancestor = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", p["commit"], f"refs/heads/{p['target']}"]
            )
            kind = "merge.landed" if ancestor.returncode == 0 else "merge.abandoned"
            fields = {k: p[k] for k in ("merge_id", "branch", "target", "commit")}
            db.log(con, row["run_id"], kind, stage="coordination", recovered=True, **fields)
            if kind == "merge.landed":
                for resource, fence in p.get("fences", {}).items():  # merge.started had no fences before 2026-11-10
                    claim.release_in(con, resource, row["run_id"], fence)
            print(f"{kind}: {p['branch']} -> {p['target']} ({p['commit'][:12]})")


def checked_out(repo, target):
    """True if any worktree of repo has target checked out. update-ref would leave its index behind."""
    lines = _git(repo, "worktree", "list", "--porcelain").splitlines()
    return f"branch refs/heads/{target}" in lines


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.merge")
    parser.add_argument("branch")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fence", action="append", default=[], metavar="RESOURCE=FENCE",
                        help="one per changed file, e.g. file:src/a.py=3")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--target", default="main")
    parser.add_argument("--check", metavar="COMMAND",
                        help="a shell command that must exit 0 in a worktree of the merged commit, e.g. a build")
    args = parser.parse_args()
    stop_on_sigterm()
    fences = {r: int(f) for r, f in (s.rsplit("=", 1) for s in args.fence)}

    if checked_out(args.repo, args.target):
        sys.exit(f"refused: {args.target} is checked out in a worktree; landing would leave its index behind")
    db.init()
    lock = Path(_git(args.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "iterum-merge.lock"
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # one merge process per repo, so reconcile() sees no merge in flight
        reconcile(args.repo)
        try:
            new = land(args.repo, args.branch, args.run_id, fences, args.target, args.check)
        except (Conflict, Empty, CheckFailed, claim.Refused, claim.Fenced) as e:
            sys.exit(f"refused: {e}")
        except subprocess.CalledProcessError as e:
            sys.exit(f"refused: {e.stderr.strip()}")
    print(f"landed {args.branch} on {args.target} as {new[:12]}")


if __name__ == "__main__":
    main()
