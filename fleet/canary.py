"""Cheap early warning for the failure no gate catches.

This does NOT detect wrongness. It detects CHANGE: finished fleet.run runs in
the last window that look unlike the runs before them, by median events,
seconds and cost per run. Cost is the run's `spend.reported` events, so it is
zero without fleet.telemetry, and a zero baseline is never compared.
Queue tasks are not runs and are not watched.

    uv run python -m fleet.canary [--baseline-hours 24] [--window-hours 1] [--tolerance 0.5]

Prints each alert and logs one `canary.fired` event when any fire.
"""

import argparse
import statistics
import time

from fleet import db, telemetry


def recent(hours):
    """Finished runs started in the last `hours`, with their event count and reported cost."""
    since = time.time() - hours * 3600
    con = db.connect()
    try:
        return con.execute(
            "SELECT run_id, started_at, ended_at,"
            "  (SELECT COUNT(*) FROM events e WHERE e.run_id = r.run_id) AS events,"
            "  (SELECT COALESCE(SUM(json_extract(payload, '$.cost_usd')), 0) FROM events e"
            "     WHERE e.run_id = r.run_id AND e.kind = ?) AS cost_usd"
            " FROM runs r WHERE started_at > ? AND ended_at IS NOT NULL",
            (telemetry.KIND, since),
        ).fetchall()
    finally:
        con.close()


def check(baseline_hours=24, window_hours=1, tolerance=0.5):
    """[(measure, baseline median, window median, direction)], or None with under 5 baseline runs or none in the window."""
    cutoff = time.time() - window_hours * 3600
    base = [r for r in recent(baseline_hours) if r["started_at"] < cutoff]
    now = recent(window_hours)
    if len(base) < 5 or not now:
        return None
    alerts = []
    for label, fn in (
        ("events per run", lambda r: r["events"]),
        ("seconds per run", lambda r: r["ended_at"] - r["started_at"]),
        ("cost per run", lambda r: r["cost_usd"]),
    ):
        b = statistics.median(fn(r) for r in base)
        n = statistics.median(fn(r) for r in now)
        if b and abs(n - b) / b > tolerance:
            # DOWN is what an agent that has started short-circuiting looks like.
            alerts.append((label, round(b, 4), round(n, 4), "up" if n > b else "DOWN"))
    return alerts


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.canary")
    parser.add_argument("--baseline-hours", type=float, default=24)
    parser.add_argument("--window-hours", type=float, default=1)
    parser.add_argument("--tolerance", type=float, default=0.5)
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    alerts = check(args.baseline_hours, args.window_hours, args.tolerance)
    if alerts is None:
        print("insufficient data: need 5 baseline runs and 1 in the window")
        return
    if not alerts:
        print("quiet")
        return
    for a in alerts:
        print(a)
    with db.write() as con:
        db.log(con, "fleet", "canary.fired", stage="governance",
               alerts=[list(a) for a in alerts])


if __name__ == "__main__":
    main()
