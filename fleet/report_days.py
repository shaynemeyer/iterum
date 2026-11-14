"""Several days of work from agent.db, as plain data. Reads only.

The window is today plus the N-1 days before it, in local calendar days. Stages and
context reuse fleet.view's definitions, so the numbers match `iterum view`.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fleet import db, governor, telemetry, view
from fleet.report_run import plan_name


def window(days, today=None):
    """(first day, start, end) for the last `days` calendar days, ending at tomorrow's midnight."""
    first = (today or date.today()) - timedelta(days=days - 1)
    start = datetime.combine(first, datetime.min.time())
    return first, start.timestamp(), (start + timedelta(days=days)).timestamp()


def day_of(ts):
    """Local date of an epoch time, as YYYY-MM-DD."""
    return datetime.fromtimestamp(ts).date().isoformat()


def spend_per_day(con, start, end):
    """[{date, total_usd, by_model}] for days with spend, and the ceiling now."""
    days = {}
    for r in con.execute("SELECT ts, payload FROM events WHERE kind=? AND ts>=? AND ts<? ORDER BY ts",
                         (telemetry.KIND, start, end)):
        p = json.loads(r["payload"])
        d = days.setdefault(day_of(r["ts"]), {})
        model = p.get("model") or "unknown"
        d[model] = d.get(model, 0) + (p.get("cost_usd") or 0)
    ceiling = governor.status()
    return {
        "days": [{"date": d, "total_usd": sum(m.values()), "by_model": m} for d, m in sorted(days.items())],
        "ceiling_usd": ceiling[0] if ceiling else None,
        "ceiling_since": day_of(ceiling[2]) if ceiling else None,
    }


def runs_per_day(con, start, end):
    """[{date, by_status}] for runs started in the window."""
    days = {}
    for r in con.execute("SELECT started_at, status FROM runs WHERE started_at>=? AND started_at<?", (start, end)):
        d = days.setdefault(day_of(r["started_at"]), {})
        d[r["status"]] = d.get(r["status"], 0) + 1
    return [{"date": d, "by_status": s} for d, s in sorted(days.items())]


def failures_by_stage(con, start, end):
    """{stage: {failures, events}} over view.STAGES, as `iterum view stages` counts them."""
    marks = ",".join("?" * len(view.STAGES))
    counts = {}
    for r in con.execute(f"SELECT stage, kind FROM events WHERE ts>=? AND ts<? AND stage IN ({marks})",
                         (start, end, *view.STAGES)):
        c = counts.setdefault(r["stage"], {"failures": 0, "events": 0})
        c["failures"] += view.is_failure(r["kind"])
        c["events"] += 1
    return dict(sorted(counts.items(), key=lambda c: -c[1]["failures"]))


def context_per_session(con, start, end):
    """[{session_id, run_id, requests, first, last, peak, sizes}] for sessions with requests in the window."""
    sessions = {}
    for r in con.execute(view.CONTEXT_SQL):
        if start <= r["ts"] < end:
            sessions.setdefault(r["session_id"], []).append(r)
    return [{"session_id": sid, "run_id": reqs[0]["run_id"], "requests": len(reqs), "first": reqs[0]["context"],
             "last": reqs[-1]["context"], "peak": max(q["context"] for q in reqs), "sizes": [q["context"] for q in reqs]}
            for sid, reqs in sessions.items()]


def cost_per_plan(con, start, end):
    """{plan file name: [{run_id, status, cost_usd}]} for runs started in the window."""
    plans = {}
    for r in con.execute(
        "SELECT r.run_id, r.task, r.status, (SELECT COALESCE(SUM(json_extract(payload,'$.cost_usd')),0)"
        " FROM events e WHERE e.run_id=r.run_id AND e.kind=?) AS cost FROM runs r"
        " WHERE r.started_at>=? AND r.started_at<? ORDER BY r.started_at",
        (telemetry.KIND, start, end),
    ):
        plans.setdefault(plan_name(r["task"]), []).append({"run_id": r["run_id"], "status": r["status"], "cost_usd": r["cost"]})
    return plans


def days_report(days, today=None):
    """Every section of the multi-day report, as one dict."""
    first, start, end = window(days, today)
    con = db.connect()
    try:
        return {
            "first": first.isoformat(), "last": (first + timedelta(days=days - 1)).isoformat(), "days": days,
            "db": str(Path(db.DB).resolve()),
            "spend": spend_per_day(con, start, end),
            "runs": runs_per_day(con, start, end),
            "stages": failures_by_stage(con, start, end),
            "context": context_per_session(con, start, end),
            "plans": cost_per_plan(con, start, end),
        }
    finally:
        con.close()
