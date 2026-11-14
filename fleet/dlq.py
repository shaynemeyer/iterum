"""List dead-lettered tasks, put them back on the queue, or give up on them.

    iterum dlq
    iterum dlq redrive <task_id>
    iterum dlq drop <task_id> "<reason>"
"""

import argparse
import sys

from fleet import db, queue


def show():
    """Print every dead-lettered task and why it is there."""
    tasks = queue.dead_letters()
    if not tasks:
        print("no dead-lettered tasks")
    for t in tasks:
        print(
            f"{t['task_id']}  {t['kind']:12s}  attempts {t['attempts']}/{t['max_attempts']}"
            f"  {t['waiting']} waiting  {t['reason']}"
        )


def redrive(task_id):
    """Redrive one task. Exits 1 if it is not dead-lettered."""
    restored = queue.redrive(task_id)
    if restored is None:
        sys.exit(f"task {task_id} is not dead-lettered")
    print(f"task {task_id} is back on the queue, with {len(restored)} waiting tasks restored")


def drop(task_id, reason):
    """Drop one task, so it no longer needs a person. Exits 1 if it is not dead-lettered."""
    waiting = queue.drop(task_id, reason)
    if waiting is None:
        sys.exit(f"task {task_id} is not dead-lettered")
    print(f"dropped task {task_id}" + (f"; tasks waiting on it stay halted: {waiting}" if waiting else ""))


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.dlq")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("redrive").add_argument("task_id", type=int)
    cmd = commands.add_parser("drop", help="give up on one dead-lettered task")
    cmd.add_argument("task_id", type=int)
    cmd.add_argument("reason")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.command == "redrive":
        redrive(args.task_id)
    elif args.command == "drop":
        drop(args.task_id, args.reason)
    else:
        show()


if __name__ == "__main__":
    main()
