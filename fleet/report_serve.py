"""A live view of the reports on 127.0.0.1: every page rebuilt from the database per request, refreshing itself.

    iterum report --serve [--port 8780]

/ is today; /report-YYYY-MM-DD.html is that day; /run-<id>.html is that run. Requests whose Host
header is not 127.0.0.1 or localhost are refused, so a web page cannot reach the ledger through
DNS rebinding. Reads only.
"""

import re
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fleet import report, report_html, report_run, report_run_html
from fleet.proc import stop_on_sigterm

REFRESH = 5  # seconds between a page's reloads
DAY = re.compile(r"/report-(\d{4}-\d{2}-\d{2})\.html")
RUN = re.compile(r"/run-([0-9a-zA-Z_-]+)\.html")


def day_page(day):
    """The day's report, with previous and next day links that always resolve here."""
    nav = [("Today", "/"), ("Previous day", f"/report-{(day - timedelta(days=1)).isoformat()}.html"),
           ("Next day", f"/report-{(day + timedelta(days=1)).isoformat()}.html" if day < date.today() else None)]
    return report_html.render(report.report(day), nav)


def run_page(run_id):
    """The run's page, or None for an unknown run."""
    run = report_run.run_report(run_id)
    if run is None:
        return None
    day = datetime.fromtimestamp(run["started_at"]).date().isoformat()
    return report_run_html.render(run, [("Today", "/"), (f"Day {day}", f"/report-{day}.html")])


def page_for(path):
    """(status, html) for a request path."""
    if path in ("/", "/index.html"):
        return 200, day_page(date.today())
    if m := DAY.fullmatch(path):
        try:
            return 200, day_page(date.fromisoformat(m.group(1)))
        except ValueError:
            return 404, None
    if m := RUN.fullmatch(path):
        html = run_page(m.group(1))
        return (200, html) if html else (404, None)
    return 404, None


class Handler(BaseHTTPRequestHandler):
    """GET only; pages carry a meta refresh."""

    def do_GET(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self.send_error(403, "only 127.0.0.1 or localhost")
            return
        status, html = page_for(self.path.split("?", 1)[0])
        if html is None:
            self.send_error(status)
            return
        body = html.replace("<head>", f'<head><meta http-equiv="refresh" content="{REFRESH}">', 1).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Quiet: one refresh every few seconds would flood the terminal."""


def serve(port):
    """Serve until Ctrl-C or SIGTERM."""
    stop_on_sigterm()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"serving the reports at http://127.0.0.1:{port}/ (Ctrl-C stops)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        server.server_close()
