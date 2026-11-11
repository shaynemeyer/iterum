"""A fleet-wide spend ceiling, read from the ledger, halting resumably.

Spend is the sum of `cost_usd` over the `spend.reported` events that
fleet.telemetry logs, one per Claude Code API request (docs/decision-log.md,
2026-11-10). The governor keeps no count of its own: events sync across
devices, and `budgets.spent_usd` does not, so it is left unused.
"""

import time

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


def spent(con, since):
    """Total reported spend in USD since the given time."""
    return con.execute(
        "SELECT COALESCE(SUM(json_extract(payload, '$.cost_usd')), 0)"
        " FROM events WHERE kind=? AND ts>=?",
        (telemetry.KIND, since),
    ).fetchone()[0]


def headroom():
    """USD left under the ceiling; infinite when no ceiling is set, negative once over."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT limit_usd, window_start FROM budgets WHERE scope=?", (SCOPE,)
        ).fetchone()
        if not row:
            return float("inf")
        return row["limit_usd"] - spent(con, row["window_start"])
    finally:
        con.close()


def halt_resumable(run_id, reason):
    """Stop a run at the ceiling. Its committed steps stay committed and it can resume."""
    with db.write() as con:
        con.execute(
            "UPDATE runs SET status='budget_exhausted', ended_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        db.log(con, run_id, "run.budget_exhausted", stage="governance", reason=reason)
