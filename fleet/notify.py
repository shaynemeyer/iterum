"""Tell a person the worker stopped, through the shell command in ITERUM_NOTIFY.

Unset, nothing is sent. The command gets a short plain-text summary on stdin, built from
the day's report data; it never carries code, file contents, plan intents or error text.
A failing or slow command changes nothing but one printed line (decision log, 2026-11-15).
"""

import os
import signal
import subprocess
from datetime import date

from fleet import report

TIMEOUT_S = 30


def summary(worker, data, page):
    """The lines a notification carries, from report.report() and the page write_day() returned."""
    n = data["numbers"]
    runs = ", ".join(f"{count} {status}" for status, count in sorted(n["runs_by_status"].items())) or "none"
    waiting = sum(len(items) for items in data["needs_person"].values())
    return "\n".join([
        f"Iterum: {worker} stopped",
        f"runs: {runs}",
        f"ready to land: {len(data['ready_to_land'])}",
        f"needs a person: {waiting}",
        f"spend today: ${n['spend_usd']:.2f} (runs ${n['spend_runs_usd']:.2f})",
        f"report: {page or 'none, no activity today'}",
    ]) + "\n"


def worker_stopped(worker, page):
    """Send today's summary if ITERUM_NOTIFY is set; page is what report.write_day() returned."""
    cmd = os.environ.get("ITERUM_NOTIFY")
    if cmd:
        send(worker, cmd, summary(worker, report.report(date.today()), page))


def send(worker, cmd, text):
    """Run cmd with text on stdin, in its own process group, killed whole after TIMEOUT_S."""
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE, text=True, start_new_session=True)
    try:
        p.communicate(text, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        print(f"{worker}  notify: timed out after {TIMEOUT_S}s")
        return
    except BaseException:
        os.killpg(p.pid, signal.SIGKILL)  # its own session, so Ctrl-C never reached it
        p.wait()
        raise
    if p.returncode:
        print(f"{worker}  notify: exit {p.returncode}")
