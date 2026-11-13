"""One screen of fleet state: freeze, spend and runs. Reads only; exits 1 when a run needs a person.

    uv run python -m fleet.status        (or: iterum status)
"""

import os
import sys
import time
from pathlib import Path

from fleet import approve, db, governor, recovery


def header():
    """The first line: device, resolved database path, local time."""
    device = os.environ.get("ITERUM_DEVICE", "-")
    return f"iterum  {device}  {Path(db.DB).resolve()}  {time.strftime('%H:%M')}"


def fleet_line(con):
    """Whether queue claims are frozen."""
    return f"FLEET     {'FROZEN' if approve.frozen(con) else 'not frozen'}"


def spend_line():
    """The ceiling, the spend counted against it, and the headroom."""
    s = governor.status()
    if s is None:
        return "SPEND     no ceiling set"
    limit, spent, _ = s
    return f"SPEND     ceiling {limit:.2f}  spent {spent:.4f}  headroom {limit - spent:.4f} USD"


def run_lines(con):
    """Run counts by status, then one line per stale or failed run. Returns (lines, needs_person)."""
    counts = con.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status ORDER BY status").fetchall()
    summary = "   ".join(f"{r['n']} {r['status']}" for r in counts) or "none"
    lines = [f"RUNS      {summary}"]
    dead = recovery.dead_runs()
    for run_id, _, _, status, idle in dead:
        label = "stale" if status == "running" else "failed"
        lines.append(f"  {label:<7}  {run_id}  last seen {idle / 60:.0f}m ago")
    return lines, bool(dead)


def main():
    """Print the status screen; exit 1 when a run needs a person."""
    if not Path(db.DB).exists():
        sys.exit(f"no database at {Path(db.DB).resolve()}")
    con = db.connect()
    try:
        runs, needs_person = run_lines(con)
        print("\n".join([header(), "", fleet_line(con), spend_line(), "", *runs]))
    finally:
        con.close()
    sys.exit(1 if needs_person else 0)


if __name__ == "__main__":
    main()
