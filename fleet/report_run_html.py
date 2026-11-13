"""Render one run's data as a self-contained HTML page, in the day report's style.

The timeline has one row per step, placed by its start and end within the run, coloured by
status with the status written beside it. Events follow in order, failures marked, as
`iterum view trace` lists them.
"""

import json
from datetime import datetime
from html import escape

from fleet.report_html import RUN_STATUS, STEP_STATUS, banner, clock, duration, page, usd, worked_until

EXTRA_CSS = "tr.fail td { color: var(--critical); } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: .8rem; margin: 4px 0; }"


def timeline(run):
    """One row per step: a bar from its start to its end within the run, status written at its end."""
    steps = run["steps"]
    if not steps:
        return '<p class="muted">No steps recorded.</p>'
    t0 = run["started_at"]
    t1 = worked_until(run)
    span = max(t1 - t0, 1)
    w, row, left, right = 720, 26, 220, 110
    x = lambda t: left + (t - t0) / span * (w - left - right)
    parts = []
    for i, s in enumerate(steps):
        y = i * row + 4
        x0, x1 = x(s["started_at"]), x(s["ended_at"] or s["started_at"])
        tone = STEP_STATUS.get(s["status"], "warning")
        parts.append(f'<text x="{left - 8}" y="{y + 13}" text-anchor="end">{s["seq"]}. {escape(s["intent"][:28])}</text>'
                     f'<rect x="{x0:.1f}" y="{y + 3}" width="{max(x1 - x0, 3):.1f}" height="14" rx="2" fill="var(--{tone})">'
                     f'<title>step {s["seq"]} {escape(s["intent"])}: {escape(s["status"])}, {duration(s["started_at"], s["ended_at"])}</title></rect>'
                     f'<text x="{max(x1, x0 + 3) + 6:.1f}" y="{y + 14}">{escape(s["status"])} {duration(s["started_at"], s["ended_at"])}</text>')
    h = row * len(steps) + 8
    return (f'<div class="scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'aria-label="Steps of run {escape(run["run_id"])} over time">{"".join(parts)}</svg></div>')


def payload_cell(e):
    """A failure's payload in full (folded when long); other events show nothing."""
    if not e["failure"]:
        return ""
    text = json.dumps(e["payload"], indent=1)
    body = f"<pre>{escape(text)}</pre>"
    return f"<details><summary>details</summary>{body}</details>" if len(text) > 300 else body


def events_table(run):
    """Every event in order, with seconds since the first."""
    if not run["events"]:
        return '<p class="muted">No events.</p>'
    t0 = run["events"][0]["ts"]
    rows = "".join(
        f'<tr{" class=fail" if e["failure"] else ""}><td class=n>+{e["ts"] - t0:.2f}s</td><td>{escape(e["stage"] or "")}</td>'
        f'<td class=n>{"" if e["seq"] is None else e["seq"]}</td><td>{escape(e["kind"])}{payload_cell(e)}</td></tr>'
        for e in run["events"])
    return (f'<div class="scroll"><table><tr><th class=n>Time</th><th>Stage</th><th class=n>Step</th><th>Event</th></tr>'
            f'{rows}</table></div>')


def merges_table(run):
    """The run's merge events: started, landed or refused."""
    if not run["merges"]:
        return '<p class="muted">No merges.</p>'
    rows = "".join(f'<tr><td>{clock(m["ts"])}</td><td>{escape(m["kind"])}</td><td>{escape(m.get("branch", ""))} &rarr; {escape(m.get("target", ""))}</td>'
                   f'<td>{escape(m.get("reason") or "")}</td></tr>' for m in run["merges"])
    return f'<div class="scroll"><table><tr><th>At</th><th>Event</th><th>Branch</th><th>Reason</th></tr>{rows}</table></div>'


def ended_note(run):
    """'started 09:27', plus when the run ended if that was after its last step (a halt)."""
    note = f'working time, started {clock(run["started_at"])}'
    end, worked = run["ended_at"], worked_until(run)
    if end and worked and end - worked > 60:
        note += f'; ended {datetime.fromtimestamp(end).strftime("%Y-%m-%d %H:%M")}'
    return note


def render(run, nav=()):
    """The whole page for one run; nav is the masthead's [(label, href)]."""
    failed = (f'first failure at stage <b>{escape(run["failing_stage"])}</b>'
              + (f', step {run["failing_seq"]}' if run["failing_seq"] is not None else "")) if run["failing_stage"] else "no failure recorded"
    tiles = [(escape(run["status"]), failed), (duration(run["started_at"], worked_until(run)), ended_note(run)),
             (sum(s["status"] == "committed" for s in run["steps"]), f'of {len(run["steps"])} steps committed'),
             (usd(run["cost_usd"]), f'{run["requests"]} model requests')]
    tiles_html = '<div class="tiles">' + "".join(f'<div class="card tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in tiles) + "</div>"
    outcome = f'{escape(run["status"].capitalize())}: {failed}.'
    icon = "&#10003;" if RUN_STATUS.get(run["status"]) == "good" else "!"
    body = (f'<h2>Steps</h2><div class="card">{timeline(run)}</div>'
            f'<h2>Events</h2>{events_table(run)}<h2>Merges</h2>{merges_table(run)}')
    return page(f'Iterum run {run["run_id"]}', "Run report", escape(run["run_id"]),
                f'{escape(run["plan"])} &middot; {escape(run["agent"])} &middot; {escape(run["db"])}', banner(RUN_STATUS.get(run["status"], "warning"), icon, outcome) + tiles_html + body, EXTRA_CSS, nav=nav)
