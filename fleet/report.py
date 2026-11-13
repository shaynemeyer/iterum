"""A day's work from agent.db: an HTML page, or the data as JSON. Reads only.

    iterum report [--date YYYY-MM-DD] [--out page.html] [--open]   # writes reports/report-<date>.html beside the database
    iterum report --json [--date YYYY-MM-DD]                       # the same data as JSON

A run belongs to the day it started. Spend counts every `spend.reported` event in
the day, interactive sessions included. Times are epoch seconds; the day is local.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fleet import approve, db, governor, queue, recovery, report_html, telemetry


def day_window(day):
    """(start, end) epoch seconds for local midnight to the next midnight."""
    start = datetime.combine(day, datetime.min.time())
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def payloads(con, kind, start, end):
    """(run_id, ts, payload dict) for each event of `kind` in the window, oldest first."""
    rows = con.execute(
        "SELECT run_id, ts, payload FROM events WHERE kind=? AND ts>=? AND ts<? ORDER BY ts",
        (kind, start, end),
    )
    return [(r["run_id"], r["ts"], json.loads(r["payload"])) for r in rows]


def runs(con, start, end):
    """Runs started in the window, each with its plan file name, cost and steps."""
    out = []
    for r in con.execute("SELECT * FROM runs WHERE started_at>=? AND started_at<? ORDER BY started_at", (start, end)):
        cost = con.execute(
            "SELECT COALESCE(SUM(json_extract(payload,'$.cost_usd')),0) FROM events WHERE run_id=? AND kind=?",
            (r["run_id"], telemetry.KIND),
        ).fetchone()[0]
        steps = con.execute(
            "SELECT seq, intent, status, started_at, ended_at FROM steps WHERE run_id=? ORDER BY seq", (r["run_id"],)
        )
        out.append({
            "run_id": r["run_id"], "plan": Path(r["task"]).name, "status": r["status"],
            "started_at": r["started_at"], "ended_at": r["ended_at"], "cost_usd": cost,
            "steps": [dict(s) for s in steps],
        })
    return out


def numbers(con, start, end, day_runs):
    """Counts and spend for the day, and the fleet's headroom now."""
    statuses = {}
    for r in day_runs:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    count = lambda kind: con.execute(
        "SELECT COUNT(*) FROM events WHERE kind=? AND ts>=? AND ts<?", (kind, start, end)
    ).fetchone()[0]
    spent = sum(p.get("cost_usd") or 0 for _, _, p in payloads(con, telemetry.KIND, start, end))
    ceiling = governor.status()
    return {
        "runs_started": len(day_runs), "runs_by_status": statuses,
        "steps_committed": count("step.committed"),
        "merges_landed": count("merge.landed"), "merges_refused": count("merge.refused"),
        "spend_usd": spent,
        "ceiling_usd": ceiling[0] if ceiling else None,
        "headroom_usd": ceiling[0] - ceiling[1] if ceiling else None,
    }


def needs_person(con, start, end, now):
    """Merges refused in the window and, when `now` (today's report), what iterum status flags at this moment.

    Dead runs, pending approvals and conflicts are current state, not the day's, so a past day leaves them out.
    """
    return {
        "dead_runs": [{"run_id": r[0], "status": r[3], "idle_s": r[4]} for r in recovery.dead_runs()] if now else [],
        "refused_merges": [
            {"run_id": run_id, "branch": p["branch"], "reason": p.get("reason")}
            for run_id, _, p in payloads(con, "merge.refused", start, end)
        ],
        "approvals": [{"fingerprint": a["fingerprint"], "action": a["action"], "scope": a["run_id"], "seq": a["seq"]}
                      for a in approve.pending()] if now else [],
        "conflicts": [t["task_id"] for t in queue.human_tasks()] if now else [],
    }


def spend_by_hour(con, start, end):
    """{hour 0-23: {model: usd}} for the window, hours with spend only."""
    hours = {}
    for _, ts, p in payloads(con, telemetry.KIND, start, end):
        h = hours.setdefault(datetime.fromtimestamp(ts).hour, {})
        model = p.get("model") or "unknown"
        h[model] = h.get(model, 0) + (p.get("cost_usd") or 0)
    return dict(sorted(hours.items()))


def landed(con, start, end):
    """Each merge.landed in the window: branch, target and the files it covered."""
    return [{"run_id": run_id, "at": ts, "branch": p["branch"], "target": p["target"], "files": p.get("resources", [])}
            for run_id, ts, p in payloads(con, "merge.landed", start, end)]


def report(day):
    """Every section of the day's report, as one dict."""
    start, end = day_window(day)
    con = db.connect()
    try:
        day_runs = runs(con, start, end)
        return {
            "date": day.isoformat(), "device": os.environ.get("ITERUM_DEVICE"),
            "db": str(Path(db.DB).resolve()), "generated_at": time.time(),
            "needs_person": needs_person(con, start, end, now=day == date.today()),
            "numbers": numbers(con, start, end, day_runs),
            "runs": day_runs,
            "spend_by_hour": spend_by_hour(con, start, end),
            "landed": landed(con, start, end),
        }
    finally:
        con.close()


def default_out(day):
    """reports/report-<date>.html in the database's folder."""
    return Path(db.DB).resolve().parent / "reports" / f"report-{day.isoformat()}.html"


def main():
    """Write the day's page and print its path, or print the data as JSON."""
    parser = argparse.ArgumentParser(prog="iterum report")
    parser.add_argument("--json", action="store_true", help="print the data as JSON instead of writing the page")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD, default today")
    parser.add_argument("--out", type=Path, help="where to write the page (default: reports/ beside the database)")
    parser.add_argument("--open", action="store_true", help="open the page afterwards (macOS `open`)")
    args = parser.parse_args()
    if not Path(db.DB).exists():
        sys.exit(f"no database at {Path(db.DB).resolve()}")
    data = report(args.date)
    if args.json:
        print(json.dumps(data, indent=2))
        return
    out = args.out or default_out(args.date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_html.render(data))
    print(out)
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
