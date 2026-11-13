"""Render fleet.report's data as one self-contained HTML page: inline CSS and SVG, no scripts.

Every value from the ledger goes through html.escape. Colours are the dataviz reference
palette (categorical slots 1-8, status good/warning/critical), validated light and dark.
"""

from datetime import datetime
from html import escape

SERIES = 8  # categorical slots; further models fold into "other"
STEP_STATUS = {"committed": "good", "failed": "critical", "proposed": "warning"}

CSS = """
:root { color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4; --s6: #008300; --s7: #6250d6; --s8: #e34948;
  --other: #898781; --good: #0ca30c; --warning: #fab219; --critical: #d03b3b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767; } }
:root[data-theme="dark"] { color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; } h2 { font-size: 1.05rem; margin: 32px 0 8px; }
.meta, .muted { color: var(--ink-2); font-size: .85rem; overflow-wrap: anywhere; }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; padding: 12px 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile .v { font-size: 1.6rem; font-weight: 600; } .tile .k { color: var(--ink-2); font-size: .85rem; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
th { text-align: left; color: var(--ink-2); font-weight: 500; border-bottom: 1px solid var(--axis); padding: 6px 8px; }
td { border-bottom: 1px solid var(--grid); padding: 6px 8px; vertical-align: top; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
code { font-size: .85em; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: .85rem; color: var(--ink-2); margin: 4px 0 8px; }
.flag { list-style: none; padding: 0; margin: 0; } .flag li { padding: 4px 0; }
svg text { fill: var(--muted); font-size: 11px; }
details summary { cursor: pointer; color: var(--ink-2); font-size: .85rem; margin-top: 8px; }
"""


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
        f'<tr><td>{clock(r["started_at"])}</td><td><code>{escape(r["run_id"])}</code></td><td>{escape(r["plan"])}</td>'
        f'<td>{escape(r["status"])}</td><td class=n>{duration(r["started_at"], r["ended_at"])}</td>'
        f'<td class=n>{usd(r["cost_usd"])}</td><td>{step_strip(r)}</td></tr>' for r in runs)
    return (f'<div class="scroll"><table><tr><th>Started</th><th>Run</th><th>Plan</th><th>Status</th><th class=n>Took</th>'
            f'<th class=n>Cost</th><th>Steps</th></tr>{rows}</table></div>')


def landed_table(landed):
    """Each merge that landed."""
    if not landed:
        return '<p class="muted">Nothing landed.</p>'
    rows = "".join(f'<tr><td>{clock(m["at"])}</td><td>{escape(m["branch"])} &rarr; {escape(m["target"])}</td>'
                   f'<td>{", ".join(escape(f) for f in m["files"])}</td></tr>' for m in landed)
    return f'<div class="scroll"><table><tr><th>At</th><th>Branch</th><th>Files</th></tr>{rows}</table></div>'


def person_list(needs):
    """What needs a person, one line each, or 'Nothing'."""
    items = [f'<li>Run <code>{escape(r["run_id"])}</code> is {escape(r["status"])}</li>' for r in needs["dead_runs"]]
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
    """True when the day has nothing to show."""
    n = data["numbers"]
    return not (data["runs"] or data["landed"] or n["spend_usd"] or n["merges_refused"] or any(data["needs_person"].values()))


def render(data):
    """The whole page for one day's report."""
    head = (f'<h1>Iterum: {escape(data["date"])}</h1><p class="meta">{escape(data["device"] or "-")} &middot; '
            f'{escape(data["db"])} &middot; generated {datetime.fromtimestamp(data["generated_at"]).strftime("%Y-%m-%d %H:%M")}</p>')
    if quiet(data):
        body = f'<p>Nothing happened on {escape(data["date"])}.</p>'
    else:
        body = (f'<h2>Needs a person</h2>{person_list(data["needs_person"])}'
                f'<h2>The day in numbers</h2>{tiles(data["numbers"])}'
                f'<h2>Runs</h2>{runs_table(data["runs"])}'
                f'<h2>Spend by hour</h2><div class="card">{spend_chart(data["spend_by_hour"])}</div>'
                f'<h2>Landed</h2>{landed_table(data["landed"])}')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Iterum report {escape(data["date"])}</title><style>{CSS}</style></head><body><main>{head}{body}</main></body></html>')
