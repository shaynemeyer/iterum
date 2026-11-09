"""List the conflicts waiting for a person, and settle them.

    uv run python -m fleet.conflicts
    uv run python -m fleet.conflicts resolve <task_id> "<decision>"
"""

import argparse
import sys

from fleet import db, queue


def show():
    """Print every open conflict and what it holds."""
    tasks = queue.human_tasks()
    if not tasks:
        print("no conflicts waiting")
    for t in tasks:
        print(f"{t['task_id']}  {t['payload']}")


def resolve(task_id, decision):
    """Settle one conflict. Exits 1 if it is not open."""
    if not queue.resolve(task_id, decision):
        sys.exit(f"task {task_id} is not an open conflict")
    print(f"task {task_id} resolved: {decision}")


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.conflicts")
    commands = parser.add_subparsers(dest="command")
    settle = commands.add_parser("resolve")
    settle.add_argument("task_id", type=int)
    settle.add_argument("decision")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.command == "resolve":
        resolve(args.task_id, args.decision)
    else:
        show()


if __name__ == "__main__":
    main()
