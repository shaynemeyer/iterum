"""Queue a shell command as a task for `iterum worker`.

    iterum add "<cmd>" [--max-attempts N]

`--max-attempts` defaults to 1: a task is usually a whole `iterum run` plan, which
retries inside itself (`--fix-retries`), and a queue rerun fails at once on the
branch the first attempt made, hiding the real cause.
"""

import argparse

from fleet import db, queue


def main():
    parser = argparse.ArgumentParser(prog="iterum add")
    parser.add_argument("cmd", help="shell command the worker runs")
    parser.add_argument("--max-attempts", type=int, default=1)
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    task_id = queue.add("shell", {"cmd": args.cmd}, max_attempts=args.max_attempts)
    print(f"task {task_id} queued")


if __name__ == "__main__":
    main()
