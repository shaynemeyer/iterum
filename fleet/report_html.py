"""Render fleet.report's data as one self-contained HTML page: inline CSS and SVG, no scripts.

Every value from the ledger goes through html.escape. Colours are the dataviz reference
palette (categorical slots 1-8, status good/warning/critical), validated light and dark.
"""

from datetime import datetime
from html import escape
from pathlib import Path

SERIES = 8  # categorical slots; further models fold into "other"
STEP_STATUS = {"committed": "good", "failed": "critical", "proposed": "warning"}

CSS = """
:root { color-scheme: light;
  --page: #f4f8f7; --surface: #ffffff; --ink: #1e293b; --ink-2: #52606d; --muted: #7b8a96;
  --grid: #e3ecea; --axis: #c3d3cf; --ring: #d7e3e0; --accent: #0b7a6e; --band: #1e293b; --band-ink: #e8f3f1;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4; --s6: #008300; --s7: #6250d6; --s8: #e34948;
  --other: #898781; --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
  --display: "Bricolage Grotesque", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --page: #0e1520; --surface: #162030; --ink: #e8f3f1; --ink-2: #9fb0bd; --grid: #213049; --axis: #33445f; --ring: #24324a; --accent: #5cc8b8; --band: #0b1220;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767; } }
:root[data-theme="dark"] { color-scheme: dark;
  --page: #0e1520; --surface: #162030; --ink: #e8f3f1; --ink-2: #9fb0bd; --grid: #213049; --axis: #33445f; --ring: #24324a; --accent: #5cc8b8; --band: #0b1220;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.band { background: var(--band); color: var(--band-ink); }
.band .in { max-width: 960px; margin: 0 auto; padding: 14px 16px; display: flex; align-items: center; gap: 10px; font-family: var(--mono); font-weight: 700; }
.band svg { width: 28px; height: 28px; border-radius: 6px; flex: none; }
.band nav { margin-left: auto; display: flex; gap: 14px; font-weight: 400; font-size: .85rem; }
.band nav a { color: var(--band-ink); opacity: .85; text-decoration: none; } .band nav a:hover { opacity: 1; text-decoration: underline; }
@media (max-width: 600px) { .band .kind { display: none; } }
.band .kind { margin-left: 8px; padding-left: 18px; border-left: 1px solid rgba(232,243,241,.25); font-weight: 400; font-size: .8rem; letter-spacing: .12em; text-transform: uppercase; opacity: .75; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
h1, h2 { font-family: var(--display); letter-spacing: -.02em; line-height: 1.15; }
h1 { font-size: clamp(1.7rem, 4vw, 2.3rem); font-weight: 800; margin: 0 0 6px; }
h2 { font-size: 1.15rem; font-weight: 700; margin: 34px 0 10px; }
code { font-family: var(--mono); font-size: .85em; }
main a { color: var(--accent); text-decoration: none; } main a:hover { text-decoration: underline; }
.meta, .muted { color: var(--ink-2); font-size: .85rem; overflow-wrap: anywhere; }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; padding: 12px 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile .v { font-family: var(--display); font-size: 1.7rem; font-weight: 700; } .tile .k { color: var(--ink-2); font-size: .85rem; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th { text-align: left; color: var(--ink-2); font-weight: 500; border-bottom: 1px solid var(--axis); padding: 6px 8px; }
td { border-bottom: 1px solid var(--grid); padding: 6px 8px; vertical-align: top; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: .85rem; color: var(--ink-2); margin: 4px 0 8px; }
.flag { list-style: none; padding: 0; margin: 0; } .flag li { padding: 4px 0; }
svg text { fill: var(--muted); font-size: 11px; }
details summary { cursor: pointer; color: var(--ink-2); font-size: .85rem; margin-top: 8px; }
td.steps { white-space: nowrap; }
@media print { .band { background: none; color: var(--ink); border-bottom: 1px solid var(--ring); } tr, .card { break-inside: avoid; } }
"""

LOGO = Path(__file__).resolve().parent.parent / "assets" / "favicon.svg"


def logo():
    """The Iterum mark, unmodified, inline; empty when assets/ is not beside fleet/ (a non-editable install)."""
    return LOGO.read_text() if LOGO.exists() else ""


def run_link(run_id):
    """A run id linking to its run page, run-<id>.html in the same folder."""
    return f'<a href="run-{escape(run_id)}.html"><code>{escape(run_id)}</code></a>'


def nav_links(links):
    """The masthead's links: [(label, href)], skipping any without an href."""
    return "".join(f'<a href="{escape(href)}">{escape(label)}</a>' for label, href in links if href)


def page(title, kind, heading, meta, body, extra_css="", nav=()):
    """A whole report page: the masthead band with its links, then the heading, meta line and body."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><style>{CSS}{extra_css}</style></head><body>'
            f'<div class="band"><div class="in">{logo()}<span>iterum</span><nav>{nav_links(nav)}</nav><span class="kind">{escape(kind)}</span></div></div>'
            f'<main><h1>{heading}</h1><p class="meta">{meta}</p>{body}</main></body></html>')


def clock(ts):
    """Local HH:MM for an epoch time, or a dash."""
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "-"


def usd(x):
    """Dollars to four places, or a dash for None."""
    return "-" if x is None else f"${x:.4f}"


def duration(start, end):
    """A run or step length as 1h 02m, 3m 05s or 12s."""
    if not end:
        return "-"
    s = int(end - start)
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def worked_until(run):
    """When the run's last step ended (or started), else its ended_at.

    ended_at is set when the run is halted, which can be a day after its last step ran.
    """
    ends = [s["ended_at"] or s["started_at"] for s in run["steps"]]
    return max(ends) if ends else run["ended_at"]


def model_colours(spend_by_hour):
    """{model: css var}, slots assigned in sorted model order so a colour follows its model."""
    models = sorted({m for h in spend_by_hour.values() for m in h})
    return {m: f"var(--s{i + 1})" if i < SERIES else "var(--other)" for i, m in enumerate(models)}


def spend_chart(spend_by_hour):
    """Stacked bars of spend per hour, by model, with a legend and a table view."""
    if not spend_by_hour:
        return '<p class="muted">No spend reported.</p>'
    colours = model_colours(spend_by_hour)
    top = max(sum(h.values()) for h in spend_by_hour.values())
    w, h, left, bottom, slot = 720, 180, 52, 22, 28
    bars = []
    for hour, models in spend_by_hour.items():
        x, y = left + int(hour) * slot + 4, h - bottom
        for model in sorted(models):
            bh = models[model] / top * (h - bottom - 10)
            y -= bh
            bars.append(f'<rect x="{x}" y="{y:.1f}" width="{slot - 8}" height="{max(bh - 2, 1):.1f}" rx="2" fill="{colours[model]}">'
                        f'<title>{int(hour):02d}:00 {escape(model)}: {usd(models[model])}</title></rect>')
    axis = [f'<line x1="{left}" y1="{h - bottom}" x2="{w}" y2="{h - bottom}" stroke="var(--axis)"/>',
            f'<text x="{left - 6}" y="16" text-anchor="end">{usd(top)}</text>',
            f'<text x="{left - 6}" y="{h - bottom}" text-anchor="end">$0</text>']
    axis += [f'<text x="{left + hr * slot + slot / 2}" y="{h - 6}" text-anchor="middle">{hr:02d}</text>' for hr in range(0, 24, 3)]
    legend = "".join(f'<span><i class="dot" style="background:{c}"></i>{escape(m)}</span>' for m, c in colours.items())
    rows = "".join(f"<tr><td>{int(hr):02d}:00</td><td>{escape(m)}</td><td class=n>{usd(v)}</td></tr>"
                   for hr, ms in spend_by_hour.items() for m, v in sorted(ms.items()))
    return (f'<div class="legend">{legend}</div><div class="scroll"><svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'aria-label="Spend per hour by model">{"".join(axis + bars)}</svg></div>'
            f'<details><summary>Table</summary><table><tr><th>Hour</th><th>Model</th><th class=n>Spend</th></tr>{rows}</table></details>')


def step_strip(run):
    """A strip of the run's steps, widths by duration, coloured by status, each with a hover title."""
    steps = run["steps"]
    if not steps:
        return ""
    lengths = [max((s["ended_at"] or s["started_at"]) - s["started_at"], 0.5) for s in steps]
    total, x, parts = sum(lengths), 0.0, []
    for s, length in zip(steps, lengths):
        width = max(length / total * 160, 4)
        tone = STEP_STATUS.get(s["status"], "warning")
        parts.append(f'<rect x="{x:.1f}" y="0" width="{max(width - 2, 2):.1f}" height="10" rx="2" fill="var(--{tone})">'
                     f'<title>step {s["seq"]} {escape(s["intent"])}: {escape(s["status"])}, {duration(s["started_at"], s["ended_at"])}</title></rect>')
        x += width
    done = sum(s["status"] == "committed" for s in steps)
    return (f'<svg viewBox="0 0 {x:.0f} 10" width="{x:.0f}" height="10" role="img" aria-label="{done} of {len(steps)} steps committed">'
            f'{"".join(parts)}</svg> <span class="muted">{done}/{len(steps)}</span>')


def runs_table(runs):
    """One row per run started that day."""
    if not runs:
        return '<p class="muted">No runs started.</p>'
    rows = "".join(
        f'<tr><td>{clock(r["started_at"])}</td><td>{run_link(r["run_id"])}</td><td>{escape(r["plan"])}</td>'
        f'<td>{escape(r["status"])}</td><td class=n>{duration(r["started_at"], worked_until(r))}</td>'
        f'<td class=n>{usd(r["cost_usd"])}</td><td class=steps>{step_strip(r)}</td></tr>' for r in runs)
    return (f'<div class="scroll"><table><tr><th>Started</th><th>Run</th><th>Plan</th><th>Status</th><th class=n>Took</th>'
            f'<th class=n>Cost</th><th>Steps</th></tr>{rows}</table></div>')


def earlier_table(earlier):
    """Runs started on an earlier day that something happened to on this one."""
    rows = "".join(
        f'<tr><td>{datetime.fromtimestamp(r["started_at"]).strftime("%Y-%m-%d")}</td><td>{run_link(r["run_id"])}</td>'
        f'<td>{escape(r["plan"])}</td><td>{", ".join(f"{escape(k)}" + (f" &times;{n}" if n > 1 else "") for k, n in r["events"].items())}</td>'
        f'<td>{escape(r["status"])}</td></tr>' for r in earlier)
    return (f'<div class="scroll"><table><tr><th>Started</th><th>Run</th><th>Plan</th><th>That day</th><th>Status now</th></tr>'
            f'{rows}</table></div>')


def landed_table(landed):
    """Each merge that landed."""
    if not landed:
        return '<p class="muted">Nothing landed.</p>'
    rows = "".join(f'<tr><td>{clock(m["at"])}</td><td>{escape(m["branch"])} &rarr; {escape(m["target"])}</td>'
                   f'<td>{", ".join(escape(f) for f in m["files"])}</td></tr>' for m in landed)
    return f'<div class="scroll"><table><tr><th>At</th><th>Branch</th><th>Files</th></tr>{rows}</table></div>'


def person_list(needs):
    """What needs a person, one line each, or 'Nothing'."""
    items = [f'<li>Run {run_link(r["run_id"])} is {escape(r["status"])}</li>' for r in needs["dead_runs"]]
    items += [f'<li>Merge of {escape(m["branch"])} refused: {escape(m["reason"] or "")}</li>' for m in needs["refused_merges"]]
    items += [f'<li>Approval {escape(a["fingerprint"][:16])}: {escape(a["action"])} ({escape(a["scope"])} step {a["seq"]})</li>' for a in needs["approvals"]]
    items += [f'<li>Conflict, task {t}</li>' for t in needs["conflicts"]]
    return f'<ul class="flag">{"".join(items)}</ul>' if items else '<p class="muted">Nothing.</p>'


def tiles(n):
    """The day in numbers."""
    statuses = ", ".join(f"{v} {escape(k)}" for k, v in sorted(n["runs_by_status"].items())) or "none"
    head = f'{usd(n["headroom_usd"])} headroom of {usd(n["ceiling_usd"])}' if n["ceiling_usd"] is not None else "no ceiling set"
    cells = [(n["runs_started"], f"runs started ({statuses})"), (n["steps_committed"], "steps committed"),
             (n["merges_landed"], f'merges landed, {n["merges_refused"]} refused'), (usd(n["spend_usd"]), f"spent; {head}")]
    return '<div class="tiles">' + "".join(f'<div class="card tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in cells) + "</div>"


def quiet(data):
    """True when the day has nothing to show; fleet.report then writes no page."""
    n = data["numbers"]
    return not (data["runs"] or data["earlier_runs"] or data["landed"] or n["spend_usd"] or n["merges_refused"] or any(data["needs_person"].values()))


def render(data, nav=()):
    """The whole page for one day's report; nav is the masthead's [(label, href)]."""
    meta = (f'{escape(data["device"] or "-")} &middot; {escape(data["db"])} &middot; '
            f'generated {datetime.fromtimestamp(data["generated_at"]).strftime("%Y-%m-%d %H:%M")}')
    body = (f'<h2>Needs a person</h2>{person_list(data["needs_person"])}'
            f'<h2>The day in numbers</h2>{tiles(data["numbers"])}'
            f'<h2>Runs</h2>{runs_table(data["runs"])}'
            + (f'<h2>Earlier runs with activity</h2>{earlier_table(data["earlier_runs"])}' if data["earlier_runs"] else "") +
            f'<h2>Spend by hour</h2><div class="card">{spend_chart(data["spend_by_hour"])}</div>'
            f'<h2>Landed</h2>{landed_table(data["landed"])}')
    return page(f'Iterum report {data["date"]}', "Daily report", escape(data["date"]), meta, body, nav=nav)
