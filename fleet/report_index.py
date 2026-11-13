"""reports/index.html: every report in a folder, newest first, rebuilt from the files each time."""

import re
from html import escape

from fleet.report_html import page

DAY = re.compile(r"report-(\d{4}-\d{2}-\d{2})\.html")
RANGE = re.compile(r"report-(\d{4}-\d{2}-\d{2})-to-(\d{4}-\d{2}-\d{2})\.html")
RUN = re.compile(r"run-([0-9a-zA-Z_-]+)\.html")


def day_files(folder):
    """Dates with a day report in the folder, oldest first."""
    return sorted(m.group(1) for f in folder.glob("report-*.html") if (m := DAY.fullmatch(f.name)))


def neighbours(folder, day):
    """(previous, next) day report file names around `day` that exist in the folder, or None."""
    days = day_files(folder)
    before = [d for d in days if d < day]
    after = [d for d in days if d > day]
    return (f"report-{before[-1]}.html" if before else None, f"report-{after[0]}.html" if after else None)


def render(folder):
    """The index page for the folder's reports."""
    days = day_files(folder)[::-1]
    ranges = sorted((m.groups() for f in folder.glob("report-*-to-*.html") if (m := RANGE.fullmatch(f.name))), reverse=True)
    runs = sorted(m.group(1) for f in folder.glob("run-*.html") if (m := RUN.fullmatch(f.name)))
    link = lambda href, text: f'<li><a href="{escape(href)}">{escape(text)}</a></li>'
    body = ('<h2>Days</h2>' + (f'<ul class="flag">{"".join(link(f"report-{d}.html", d) for d in days)}</ul>' if days else '<p class="muted">None yet.</p>')
            + '<h2>Several days</h2>' + (f'<ul class="flag">{"".join(link(f"report-{a}-to-{b}.html", f"{a} to {b}") for a, b in ranges)}</ul>' if ranges else '<p class="muted">None yet.</p>')
            + f'<h2>Runs</h2><details><summary>{len(runs)} run pages</summary><ul class="flag">{"".join(link(f"run-{r}.html", r) for r in runs)}</ul></details>')
    return page("Iterum reports", "Reports", "Reports", escape(str(folder)), body)
