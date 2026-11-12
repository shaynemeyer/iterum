"""Compare two versions of the harness code on the same eval cases. Show what moved.

    uv run python -m fleet.scorecard <before> [<after>]

Each version is a git revision, scored by its own `fleet.eval --json` in a temporary
worktree (`fleet.merge.run_check`). Without <after>, the working tree as it is now,
uncommitted changes included. Both versions read the cases from the same database.
A revision from before `fleet.eval --json` existed cannot be scored.
Exits 1 if a case that passed before fails after.
"""

import argparse
import json
import os
import sys

from fleet import db, merge
from fleet import eval as evals

SCORE = "uv run python -m fleet.eval --json"


def score_at(rev):
    """{case: passed} from the code at git revision rev."""
    code, output = merge.run_check(".", rev, SCORE)
    if code != 0:
        sys.exit(f"cannot score {rev}: `{SCORE}` exited {code}:\n{output[-2000:]}")
    return json.loads(output.strip().splitlines()[-1])


def score_here():
    """{case: passed} from the code in this working tree."""
    return {c["name"]: ok for c, ok, _ in evals.replay_cases()}


def compare(before, after, before_label="before", after_label="after"):
    """Print each case's result in both versions and a verdict. Returns (fixed, broke)."""
    width = max(len(n) for n in [*before, "CASE"])
    print(f"{'CASE':<{width}}  {before_label:>8}  {after_label:>8}")
    fixed = broke = 0
    for name, was in before.items():
        now = after.get(name, False)
        mark = ""
        if not was and now:
            mark, fixed = "<- FIXED", fixed + 1
        elif was and not now:
            mark, broke = "<- BROKE", broke + 1
        print(f"{name:<{width}}  {'pass' if was else 'FAIL':>8}  {'pass' if now else 'FAIL':>8}  {mark}")

    total = len(before)
    print(f"\n{sum(before.values())}/{total} -> {sum(after.values())}/{total}   fixed {fixed}, broke {broke}")
    if broke:
        print("REJECT: this change breaks cases that used to pass.")
    elif fixed:
        print("ACCEPT: better on the cases you have, and worse on none.")
    else:
        # Green, and about nothing: the suite has no opinion on this change.
        print("NO SIGNAL: nothing moved. The change is not covered by this suite.")
    return fixed, broke


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.scorecard")
    parser.add_argument("before", help="the git revision to compare against, e.g. main")
    parser.add_argument("after", nargs="?", help="the git revision to score (default: the working tree)")
    args = parser.parse_args()

    os.environ["ITERUM_DB"] = str(db.DB.resolve())  # the worktrees run from elsewhere
    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    before = score_at(args.before)
    after = score_at(args.after) if args.after else score_here()
    _, broke = compare(before, after, args.before, args.after or "working")
    sys.exit(1 if broke else 0)


if __name__ == "__main__":
    main()
