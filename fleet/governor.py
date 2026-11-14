"""A fleet-wide spend ceiling, read from the ledger, halting resumably.

Spend is the sum of `cost_usd` over the `spend.reported` events that
fleet.telemetry logs, one per Claude Code API request (docs/decision-log.md,
2026-11-10). The governor keeps no count of its own: events sync across
devices, and `budgets.spent_usd` does not, so it is left unused.

Nothing is reserved between a headroom check and the step it allows, so runs
that check at the same moment each pass on the same headroom and each can
pass the ceiling by one step's spend (decision log, 2026-11-12).

    iterum budget
    iterum budget set <usd>
    iterum budget reset
"""

import argparse
import sys
import time
from datetime import datetime

from fleet import db, telemetry

SCOPE = "fleet"


def set_ceiling(limit_usd):
    """Set the fleet's ceiling. Spend counts from the first time a ceiling is set."""
    with db.write() as con:
        con.execute(
            "INSERT INTO budgets (scope, limit_usd, window_start) VALUES (?,?,?)"
            " ON CONFLICT(scope) DO UPDATE SET limit_usd=excluded.limit_usd",
            (SCOPE, limit_usd, time.time()),
        )


def reset():
    """Count spend from now on, keeping the ceiling. Returns the spend it stopped counting, or None with no ceiling.

    Logs `budget.reset` with that spend and the old window start, so the ledger shows what was set aside.
    """
    with db.write() as con:
        row = con.execute("SELECT window_start FROM budgets WHERE scope=?", (SCOPE,)).fetchone()
        if not row:
            return None
        before = spent(con, row["window_start"])
        con.execute("UPDATE budgets SET window_start=? WHERE scope=?", (time.time(), SCOPE))
        db.log(con, "fleet", "budget.reset", stage="governance",
               spent_usd=before, window_was=row["window_start"])
        return before


def spent(con, since):
    """Total reported spend in USD since the given time."""
    return con.execute(
        "SELECT COALESCE(SUM(json_extract(payload, '$.cost_usd')), 0)"
        " FROM events WHERE kind=? AND ts>=?",
        (telemetry.KIND, since),
    ).fetchone()[0]


def status():
    """(limit_usd, spent_usd, window_start) for the fleet, or None when no ceiling is set."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT limit_usd, window_start FROM budgets WHERE scope=?", (SCOPE,)
        ).fetchone()
        if not row:
            return None
        return row["limit_usd"], spent(con, row["window_start"]), row["window_start"]
    finally:
        con.close()


def headroom():
    """USD left under the ceiling; infinite when no ceiling is set, negative once over."""
    s = status()
    return float("inf") if s is None else s[0] - s[1]


def halt_resumable(run_id, reason):
    """Stop a run at the ceiling. Its committed steps stay committed and it can resume."""
    with db.write() as con:
        con.execute(
            "UPDATE runs SET status='budget_exhausted', ended_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        db.log(con, run_id, "run.budget_exhausted", stage="governance", reason=reason)


def show():
    """Print the ceiling, the spend counted against it, and the headroom."""
    s = status()
    if s is None:
        print("no ceiling set")
        return
    limit_usd, spent_usd, since = s
    print(
        f"ceiling {limit_usd:.2f}  spent {spent_usd:.4f}  headroom {limit_usd - spent_usd:.4f} USD"
        f"  (since {datetime.fromtimestamp(since):%Y-%m-%d %H:%M})"
    )


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.governor")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("set").add_argument("usd", type=float)
    commands.add_parser("reset", help="count spend from now on, keeping the ceiling")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.command == "set":
        set_ceiling(args.usd)
    elif args.command == "reset":
        before = reset()
        if before is None:
            sys.exit("no ceiling set: iterum budget set <usd>")
        print(f"reset: {before:.4f} USD no longer counted")
    show()


if __name__ == "__main__":
    main()
