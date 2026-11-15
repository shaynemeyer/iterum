"""Queue a shell command as a task for `iterum worker`.

    iterum add "<cmd>" [--max-attempts N] [--repo DIR --branch NAME [--base main]]
    iterum add --plan p.json [--allow-claude USD] [--fix-retries N] [--land-check CMD] [--repo ...]

`--max-attempts` defaults to 1: a task is usually a whole `iterum run` plan, which
retries inside itself (`--fix-retries`), and a queue rerun fails at once on the
branch the first attempt made, hiding the real cause.

With `--plan`, the `iterum run` command is built here, and the plan's absolute path,
cap and retries are kept in the task's payload, so `iterum budget suggest` can read
them; a task given as a plain command has none.

With `--repo` and `--branch`, the worker makes the branch from `--base` in that repo,
runs the command there, and switches back to the base afterwards.
"""

import argparse
import shlex
from pathlib import Path

from fleet import db, queue


def run_command(plan, allow_claude, fix_retries, land_check):
    """The `iterum run` command for a plan, as `iterum run` takes it."""
    cmd = f"iterum run --plan {shlex.quote(plan)}"
    if allow_claude is not None:
        cmd += f" --allow-claude {allow_claude}"
    if fix_retries:
        cmd += f" --fix-retries {fix_retries}"
    if land_check:
        cmd += f" --land-check {shlex.quote(land_check)}"
    return cmd


def main():
    parser = argparse.ArgumentParser(prog="iterum add")
    parser.add_argument("cmd", nargs="?", help="shell command the worker runs (or use --plan)")
    parser.add_argument("--plan", help="a plan file: builds the iterum run command and records its cost settings")
    parser.add_argument("--allow-claude", type=float, metavar="USD", help="with --plan: the cap per prompt step")
    parser.add_argument("--fix-retries", type=int, default=0, metavar="N", help="with --plan: fix retries per run")
    parser.add_argument("--land-check", metavar="CMD", help="with --plan: the check for iterum land")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--repo", help="git repo the command runs in")
    parser.add_argument("--branch", help="new branch the worker makes for the task")
    parser.add_argument("--base", default="main", help="branch to start from and return to")
    args = parser.parse_args()
    if bool(args.repo) != bool(args.branch):
        parser.error("--repo and --branch go together")
    if bool(args.cmd) == bool(args.plan):
        parser.error("give a command or --plan, not both")
    if not args.plan and (args.allow_claude is not None or args.fix_retries or args.land_check):
        parser.error("--allow-claude, --fix-retries and --land-check go with --plan")

    if args.plan:
        plan = str(Path(args.plan).resolve())
        payload = {"cmd": run_command(plan, args.allow_claude, args.fix_retries, args.land_check),
                   "plan": plan, "allow_claude": args.allow_claude, "fix_retries": args.fix_retries}
    else:
        payload = {"cmd": args.cmd}
    if args.repo:
        payload |= {"repo": str(Path(args.repo).resolve()), "branch": args.branch, "base": args.base}
    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    task_id = queue.add("shell", payload, max_attempts=args.max_attempts)
    print(f"task {task_id} queued: {payload['cmd']}" if args.plan else f"task {task_id} queued")


if __name__ == "__main__":
    main()
