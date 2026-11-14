"""Queue a shell command as a task for `iterum worker`.

    iterum add "<cmd>" [--max-attempts N] [--repo DIR --branch NAME [--base main]]

`--max-attempts` defaults to 1: a task is usually a whole `iterum run` plan, which
retries inside itself (`--fix-retries`), and a queue rerun fails at once on the
branch the first attempt made, hiding the real cause.

With `--repo` and `--branch`, the worker makes the branch from `--base` in that repo,
runs the command there, and switches back to the base afterwards.
"""

import argparse
from pathlib import Path

from fleet import db, queue


def main():
    parser = argparse.ArgumentParser(prog="iterum add")
    parser.add_argument("cmd", help="shell command the worker runs")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--repo", help="git repo the command runs in")
    parser.add_argument("--branch", help="new branch the worker makes for the task")
    parser.add_argument("--base", default="main", help="branch to start from and return to")
    args = parser.parse_args()
    if bool(args.repo) != bool(args.branch):
        parser.error("--repo and --branch go together")

    payload = {"cmd": args.cmd}
    if args.repo:
        payload |= {"repo": str(Path(args.repo).resolve()), "branch": args.branch, "base": args.base}
    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    task_id = queue.add("shell", payload, max_attempts=args.max_attempts)
    print(f"task {task_id} queued")


if __name__ == "__main__":
    main()
