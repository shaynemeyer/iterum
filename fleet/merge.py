"""Land an agent's branch on the shared branch, only while it holds a live claim on every file it changed."""

import argparse
import fcntl
import json
import subprocess
import sys
import uuid
from pathlib import Path

from fleet import claim, db


class Conflict(Exception):
    """The branch does not merge cleanly into the target."""


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
    new = _git(repo, "commit-tree", tree, "-p", old, "-p", branch, "-m", f"Merge {branch} into {target}")
    return old, new


def changed_resources(repo, old, branch):
    """The claim resources for every file the branch changed since it left old. A rename names both paths."""
    names = _git(repo, "diff", "--name-only", "--no-renames", f"{old}...{branch}")
    return sorted(f"file:{name}" for name in names.splitlines())


def land(repo, branch, run_id, fences, target="main"):
    """Merge branch into target if fences (resource -> fence) holds a live claim on every changed file.

    Landing releases every claim in fences, in the same block. A refusal keeps them, so the caller can retry.
    Raises Conflict, Refused or Fenced, or CalledProcessError if target moved since the build.
    """
    old, new = build(repo, target, branch)
    needed = changed_resources(repo, old, branch)
    # Write-ahead: a crash after update-ref but before the block commits leaves this for reconcile().
    merge_id = str(uuid.uuid7())  # the commit hash can repeat: commit-tree timestamps to the second
    with db.write() as con:
        db.log(con, run_id, "merge.started", stage="coordination", merge_id=merge_id, branch=branch, target=target, old=old, commit=new, fences=fences)
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
    args = parser.parse_args()
    fences = {r: int(f) for r, f in (s.rsplit("=", 1) for s in args.fence)}

    if checked_out(args.repo, args.target):
        sys.exit(f"refused: {args.target} is checked out in a worktree; landing would leave its index behind")
    db.init()
    lock = Path(_git(args.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "iterum-merge.lock"
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # one merge process per repo, so reconcile() sees no merge in flight
        reconcile(args.repo)
        try:
            new = land(args.repo, args.branch, args.run_id, fences, args.target)
        except (Conflict, claim.Refused, claim.Fenced) as e:
            sys.exit(f"refused: {e}")
        except subprocess.CalledProcessError as e:
            sys.exit(f"refused: {e.stderr.strip()}")
    print(f"landed {args.branch} on {args.target} as {new[:12]}")


if __name__ == "__main__":
    main()
