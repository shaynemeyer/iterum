"""Turn your own failures into a regression suite.

    iterum eval                                  # replay every case
    iterum eval add <name> <run_id>              # a regression case
    iterum eval add <name> <run_id> --expect J   # a capability case
    iterum eval --json                           # {case: passed}, nothing stored (fleet.scorecard)

The cases come from your own ledger, so nothing ships with this repo. Each case is
replayed through fleet.run's own code (see fleet.replay). A regression case expects
the end state its run reached. A capability case expects a hand-written
end state (JSON with the keys `end`, `failed_stage` and `committed`) and may stay red:
it is reported but never fails the suite. Exits 1 if a regression case fails.
"""

import argparse
import json
import sys
import time
import uuid

from fleet import db, replay


def add_from_failure(name, run_id):
    """Store the end state run_id actually reached as the regression case `name`. Refuses a run replay cannot drive."""
    replay.replay(run_id)
    return _add(name, run_id, "regression", replay.recorded_state(run_id))


def add_capability(name, run_id, expect):
    """Store `expect`, the end state a working harness would reach, as the capability case `name`.

    The recorded end state would be the wrong expect here: a case that expects the
    failure it already produces starts green and can never move.
    """
    keys = replay.replay(run_id).keys()
    if expect.keys() != keys:
        raise ValueError(f"expect must have exactly the keys {sorted(keys)}")
    return _add(name, run_id, "capability", expect)


def _add(name, run_id, kind, expect):
    """Insert the case, or update the one with this name in place so its results keep their eval_id."""
    with db.write() as con:
        con.execute(
            "INSERT INTO evals (name, source_run, kind, expect, created_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET source_run=excluded.source_run,"
            " kind=excluded.kind, expect=excluded.expect, created_at=excluded.created_at",
            (name, run_id, kind, json.dumps(expect), time.time()),
        )
    return expect


def replay_cases():
    """Replay every case. Returns [(case row, passed, actual end state)], in eval_id order."""
    con = db.connect()
    try:
        cases = con.execute("SELECT * FROM evals ORDER BY eval_id").fetchall()
    finally:
        con.close()
    results = []
    for case in cases:
        actual = replay.replay(case["source_run"])
        results.append((case, actual == json.loads(case["expect"]), actual))
    return results


def run_suite():
    """Replay every case, store and print the results. Returns the names of failed regression cases."""
    suite_run = uuid.uuid4().hex[:12]
    results = replay_cases()

    with db.write() as con:
        con.executemany(
            "INSERT INTO eval_results (eval_id, suite_run, passed, detail, ts) VALUES (?,?,?,?,?)",
            [(c["eval_id"], suite_run, int(ok), json.dumps(a), time.time()) for c, ok, a in results],
        )

    print(f"{'CASE':<34} {'KIND':<11} RESULT")
    for case, ok, _ in results:
        print(f"{case['name']:<34} {case['kind']:<11} {'pass' if ok else 'FAIL'}")
    _summary(results, suite_run)
    return [c["name"] for c, ok, _ in results if c["kind"] == "regression" and not ok]


def _summary(results, suite_run):
    """Print pass counts per kind."""
    for kind in ("regression", "capability"):
        oks = [ok for c, ok, _ in results if c["kind"] == kind]
        print(f"{kind}: {sum(oks)} of {len(oks)} passing")
    print(f"suite run {suite_run}")


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.eval")
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("add")
    add.add_argument("name")
    add.add_argument("run_id")
    add.add_argument("--expect", type=json.loads, help="a capability case's end state, as JSON")
    parser.add_argument("--json", action="store_true", help="print {case: passed} as one JSON line and store nothing")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.json:
        print(json.dumps({c["name"]: ok for c, ok, _ in replay_cases()}))
        return
    if args.command == "add":
        if args.expect is None:
            print(json.dumps(add_from_failure(args.name, args.run_id)))
        else:
            print(json.dumps(add_capability(args.name, args.run_id, args.expect)))
        return
    sys.exit(1 if run_suite() else 0)


if __name__ == "__main__":
    main()
