"""A day's work from agent.db: an HTML page, or the data as JSON. Reads only.

    iterum report [--date YYYY-MM-DD] [--out page.html] [--open] [--pdf]   # writes reports/report-<date>.html beside the database
    iterum report --json [--date YYYY-MM-DD]                       # the same data as JSON
    iterum report --days N [--out page.html] [--open] [--pdf] [--json]   # the last N days
    iterum report --run RUN_ID [--out page.html] [--open] [--pdf] [--json]   # one run

A run belongs to the day it started. Spend counts every `spend.reported` event in
the day, interactive sessions included. Times are epoch seconds; the day is local.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fleet import approve, db, governor, queue, recovery, report_days, report_days_html, report_html, report_run, report_run_html, telemetry


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


def earlier_runs(con, start, end):
    """Runs started before the window that logged events in it: what happened to them that day."""
    out = []
    for r in con.execute(
        "SELECT r.run_id, r.task, r.status, r.started_at, GROUP_CONCAT(e.kind, ' ') AS kinds FROM runs r"
        " JOIN events e USING (run_id) WHERE r.started_at<? AND e.ts>=? AND e.ts<?"
        " GROUP BY r.run_id ORDER BY MIN(e.ts)", (start, start, end),
    ):
        kinds = {}
        for k in r["kinds"].split(" "):
            kinds[k] = kinds.get(k, 0) + 1
        out.append({"run_id": r["run_id"], "plan": Path(r["task"]).name, "status": r["status"],
                    "started_at": r["started_at"], "events": kinds})
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


def ledger_span(con):
    """(first, last) local dates with any event, or None for an empty ledger."""
    lo, hi = con.execute("SELECT MIN(ts), MAX(ts) FROM events").fetchone()
    return None if lo is None else [datetime.fromtimestamp(lo).date().isoformat(), datetime.fromtimestamp(hi).date().isoformat()]


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
            "earlier_runs": earlier_runs(con, start, end),
            "spend_by_hour": spend_by_hour(con, start, end),
            "landed": landed(con, start, end),
            "ledger_span": ledger_span(con),
        }
    finally:
        con.close()


CHROME = ("google-chrome", "chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def find_chrome():
    """The first Chrome on PATH or at the macOS app path, or None."""
    return next((c for c in CHROME if shutil.which(c) or Path(c).exists()), None)


def print_pdf(page):
    """Print the HTML page to a PDF beside it with headless Chrome; return the PDF's path."""
    chrome = find_chrome()
    if not chrome:
        sys.exit("no Chrome found for --pdf; tried: " + ", ".join(CHROME))
    pdf = page.with_suffix(".pdf")
    done = subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                           f"--print-to-pdf={pdf}", page.resolve().as_uri()], capture_output=True, text=True)
    if done.returncode != 0 or not pdf.exists():
        sys.exit(f"Chrome could not print {page} (exit {done.returncode}):\n{done.stderr.strip()}")
    return pdf


def reports_dir():
    """reports/ in the database's folder."""
    return Path(db.DB).resolve().parent / "reports"


def write(page, out, args):
    """Write the page, print its path, then the PDF and open as asked."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(out)
    if args.pdf:
        out = print_pdf(out)
        print(out)
    if args.open:
        subprocess.run(["open", str(out)], check=False)


def span_note(span):
    """'; the ledger has events from A to B', or that it is empty."""
    return f"; the ledger has events from {span[0]} to {span[1]}" if span else "; the ledger is empty"


def main():
    """Write the page for a day (or the last N days) and print its path, or print the data as JSON."""
    parser = argparse.ArgumentParser(prog="iterum report")
    parser.add_argument("--json", action="store_true", help="print the data as JSON instead of writing the page")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD, default today")
    parser.add_argument("--days", type=int, metavar="N", help="the last N days, today included, instead of one day")
    parser.add_argument("--run", metavar="RUN_ID", help="one run: its steps over time, its events and its merges")
    parser.add_argument("--out", type=Path, help="where to write the page (default: reports/ beside the database)")
    parser.add_argument("--open", action="store_true", help="open the page (or the PDF) afterwards (macOS `open`)")
    parser.add_argument("--pdf", action="store_true", help="also print the page to a PDF beside it, with headless Chrome")
    args = parser.parse_args()
    if not Path(db.DB).exists():
        sys.exit(f"no database at {Path(db.DB).resolve()}")
    if args.run:
        data = report_run.run_report(args.run)
        if data is None:
            sys.exit(f"no run {args.run!r} in {Path(db.DB).resolve()}")
        if args.json:
            print(json.dumps(data, indent=2))
            return
        write(report_run_html.render(data), args.out or reports_dir() / f"run-{args.run}.html", args)
        return
    if args.days:
        data, quiet = report_days.days_report(args.days), report_days_html.quiet
        label, name, render = f"{data['first']} to {data['last']}", f"report-{data['first']}-to-{data['last']}.html", report_days_html.render
    else:
        data, quiet = report(args.date), report_html.quiet
        label, name, render = data["date"], f"report-{data['date']}.html", report_html.render
    if quiet(data):
        con = db.connect()
        try:
            note = span_note(ledger_span(con))
        finally:
            con.close()
        print(f"no activity recorded {'from' if args.days else 'on'} {label}{note}; no report written", file=sys.stderr)
        if not args.json:
            return
    if args.json:
        print(json.dumps(data, indent=2))
        return
    write(render(data), args.out or reports_dir() / name, args)


if __name__ == "__main__":
    main()
