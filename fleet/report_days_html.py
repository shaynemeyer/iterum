"""Render fleet.report_days' data as one self-contained HTML page, in the day report's style.

Spend per day is stacked by model; spend since the ceiling was set is a running total
drawn against the ceiling, on its own axis. Run statuses use the status palette with a
legend and a table. A plan's runs are dots: filled when the run finished, hollow when not.
"""

from datetime import date
from html import escape

from fleet.report_html import model_colours, page, usd

STATUS_TONE = {"done": "good", "failed": "critical", "halted": "serious", "budget_exhausted": "warning", "running": "warning"}
EXTRA_CSS = ".bar { display: inline-block; height: 8px; border-radius: 2px; background: var(--critical); vertical-align: 0; }"


def status_colours(statuses):
    """{status: css colour} from the status palette; unknown statuses read as warning."""
    return {s: f"var(--{STATUS_TONE.get(s, 'warning')})" for s in statuses}


def axis_labels(dates, left, slot, h):
    """Date labels under the bars, thinned so they never collide."""
    step = max(1, len(dates) // 8)
    return [f'<text x="{left + i * slot + slot / 2}" y="{h - 6}" text-anchor="middle">{escape(d[5:])}</text>'
            for i, d in enumerate(dates) if i % step == 0]


def stacked(dates, values, colours, label, fmt):
    """Stacked bars, one per date: values is {date: {series: amount}}; colours is {series: css colour}."""
    top = max((sum(v.values()) for v in values.values()), default=0) or 1
    w, h, left, bottom = 720, 180, 56, 22
    slot = (w - left) / len(dates)
    parts = [f'<line x1="{left}" y1="{h - bottom}" x2="{w}" y2="{h - bottom}" stroke="var(--axis)"/>',
             f'<text x="{left - 6}" y="16" text-anchor="end">{fmt(top)}</text>',
             f'<text x="{left - 6}" y="{h - bottom}" text-anchor="end">0</text>']
    for i, d in enumerate(dates):
        y = h - bottom
        for series in colours:
            amount = values.get(d, {}).get(series, 0)
            if not amount:
                continue
            bh = amount / top * (h - bottom - 10)
            y -= bh
            parts.append(f'<rect x="{left + i * slot + 3:.1f}" y="{y:.1f}" width="{max(slot - 6, 2):.1f}" height="{max(bh - 2, 1):.1f}" rx="2" '
                         f'fill="{colours[series]}"><title>{escape(d)} {escape(series)}: {fmt(amount)}</title></rect>')
    legend = "".join(f'<span><i class="dot" style="background:{c}"></i>{escape(s)}</span>' for s, c in colours.items())
    rows = "".join(f"<tr><td>{escape(d)}</td><td>{escape(s)}</td><td class=n>{fmt(v)}</td></tr>"
                   for d in dates for s, v in sorted(values.get(d, {}).items()))
    return (f'<div class="legend">{legend}</div><div class="scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{escape(label)}">'
            f'{"".join(parts + axis_labels(dates, left, slot, h))}</svg></div>'
            f'<details><summary>Table</summary><div class="scroll"><table><tr><th>Day</th><th>Series</th><th class=n>Value</th></tr>{rows}</table></div></details>')


def since_ceiling(dates, spend):
    """Running total of spend since the ceiling was set, against the ceiling."""
    limit, since = spend["ceiling_usd"], spend["ceiling_since"]
    if limit is None:
        return '<p class="muted">No ceiling set.</p>'
    per_day = {d["date"]: d["total_usd"] for d in spend["days"]}
    total, points = 0.0, []
    for d in dates:
        if d >= since:
            total += per_day.get(d, 0)
            points.append((d, total))
    if not points:
        return f'<p class="muted">The ceiling was set on {escape(since)}, after this window.</p>'
    top = max(limit, points[-1][1]) * 1.1
    w, h, left, bottom = 720, 160, 56, 22
    slot = (w - left) / len(dates)
    x = lambda d: left + dates.index(d) * slot + slot / 2
    y = lambda v: h - bottom - v / top * (h - bottom - 10)
    line = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in points)
    marks = "".join(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="4" fill="var(--s1)" stroke="var(--surface)" stroke-width="2">'
                    f'<title>{escape(d)}: {usd(v)} spent since {escape(since)}</title></circle>' for d, v in points)
    parts = [f'<line x1="{left}" y1="{h - bottom}" x2="{w}" y2="{h - bottom}" stroke="var(--axis)"/>',
             f'<line x1="{left}" y1="{y(limit):.1f}" x2="{w}" y2="{y(limit):.1f}" stroke="var(--critical)" stroke-dasharray="4 4"/>',
             f'<text x="{w}" y="{y(limit) - 4:.1f}" text-anchor="end">ceiling {usd(limit)}</text>',
             f'<text x="{left - 6}" y="{h - bottom}" text-anchor="end">0</text>',
             f'<polyline points="{line}" fill="none" stroke="var(--s1)" stroke-width="2"/>']
    return (f'<p class="muted">Spent {usd(points[-1][1])} of {usd(limit)} since {escape(since)}.</p>'
            f'<div class="scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Spend since the ceiling was set, against the ceiling">'
            f'{"".join(parts + axis_labels(dates, left, slot, h))}{marks}</svg></div>')


def stages_table(stages):
    """Failures and events per stage, with counts beside every rate."""
    if not stages:
        return '<p class="muted">No staged events.</p>'
    most = max(s["failures"] for s in stages.values()) or 1
    rows = "".join(
        f'<tr><td>{escape(name)}</td><td class=n>{s["failures"]}</td><td class=n>{s["events"]}</td>'
        f'<td class=n>{s["failures"] / s["events"] * 100:.1f}%</td>'
        f'<td><span class="bar" style="width:{s["failures"] / most * 120:.0f}px"></span></td></tr>' for name, s in stages.items())
    return (f'<div class="scroll"><table><tr><th>Stage</th><th class=n>Failures</th><th class=n>Events</th><th class=n>Rate</th><th></th></tr>{rows}</table></div>'
            '<p class="muted">Rates on a few dozen events mean little; read the counts.</p>')


def plans_chart(plans):
    """One row per plan, one dot per run at its cost: filled if the run finished, hollow if not."""
    if not plans:
        return '<p class="muted">No runs.</p>'
    top = max(r["cost_usd"] for runs in plans.values() for r in runs) or 1
    names = sorted(plans, key=lambda p: -max(r["cost_usd"] for r in plans[p]))
    w, row, left = 720, 22, 220
    h = row * len(names) + 26
    x = lambda c: left + c / top * (w - left - 12)
    parts = [f'<line x1="{left}" y1="{h - 20}" x2="{w}" y2="{h - 20}" stroke="var(--axis)"/>',
             f'<text x="{left}" y="{h - 6}">$0</text><text x="{w - 4}" y="{h - 6}" text-anchor="end">{usd(top)}</text>']
    for i, name in enumerate(names):
        cy = i * row + 12
        parts.append(f'<text x="{left - 8}" y="{cy + 4}" text-anchor="end">{escape(name[:30])}</text>')
        for r in plans[name]:
            done = r["status"] == "done"
            parts.append(f'<a href="run-{escape(r["run_id"])}.html"><circle cx="{x(r["cost_usd"]):.1f}" cy="{cy}" r="5" fill="{"var(--s1)" if done else "var(--surface)"}" '
                         f'stroke="var(--s1)" stroke-width="2"><title>{escape(r["run_id"])} {escape(r["status"])}: {usd(r["cost_usd"])}</title></circle></a>')
    return ('<div class="legend"><span>&#9679; finished (done)</span><span>&#9675; not finished</span></div>'
            f'<div class="scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Cost of each run, by plan">{"".join(parts)}</svg></div>')


def context_table(context, top=20):
    """The sessions with the largest peak context."""
    if not context:
        return '<p class="muted">No requests.</p>'
    rows = "".join(f'<tr><td><code>{escape((c["session_id"] or "-")[:8])}</code></td><td><code>{escape(c["run_id"])}</code></td>'
                   f'<td class=n>{c["requests"]}</td><td class=n>{c["first"]:,}</td><td class=n>{c["last"]:,}</td><td class=n>{c["peak"]:,}</td></tr>'
                   for c in sorted(context, key=lambda c: -c["peak"])[:top])
    more = f'<p class="muted">Largest {top} of {len(context)} sessions; <code>iterum view context</code> lists all.</p>' if len(context) > top else ""
    return (f'<div class="scroll"><table><tr><th>Session</th><th>Run</th><th class=n>Requests</th><th class=n>First</th>'
            f'<th class=n>Last</th><th class=n>Peak</th></tr>{rows}</table></div>{more}')


def dates_of(data):
    """Every date in the window, as YYYY-MM-DD."""
    first = date.fromisoformat(data["first"])
    return [date.fromordinal(first.toordinal() + i).isoformat() for i in range(data["days"])]


def quiet(data):
    """True when the window has nothing to show; fleet.report then writes no page."""
    return not (data["runs"] or data["spend"]["days"] or data["stages"] or data["plans"])


def render(data, nav=()):
    """The whole page for a multi-day report; nav is the masthead's [(label, href)]."""
    dates = dates_of(data)
    spend = {d["date"]: d["by_model"] for d in data["spend"]["days"]}
    runs = {d["date"]: d["by_status"] for d in data["runs"]}
    statuses = sorted({s for v in runs.values() for s in v})
    body = (f'<h2>Spend per day</h2><div class="card">{stacked(dates, spend, model_colours(spend), "Spend per day by model", usd) if spend else "<p class=muted>No spend reported.</p>"}</div>'
            f'<h2>Spend against the ceiling</h2><div class="card">{since_ceiling(dates, data["spend"])}</div>'
            f'<h2>Runs per day</h2><div class="card">{stacked(dates, runs, status_colours(statuses), "Runs per day by status", str) if runs else "<p class=muted>No runs started.</p>"}</div>'
            f'<h2>Failures by stage</h2>{stages_table(data["stages"])}'
            f'<h2>Cost per plan</h2><div class="card">{plans_chart(data["plans"])}</div>'
            f'<h2>Context per session</h2>{context_table(data["context"])}')
    return page(f'Iterum report {data["first"]} to {data["last"]}', f'{data["days"]}-day report',
                f'{escape(data["first"])} to {escape(data["last"])}', f'{data["days"]} days &middot; {escape(data["db"])}', body, EXTRA_CSS, nav=nav)
