"""Receive Claude Code telemetry and record each API request's cost in the ledger.

    uv run python -m fleet.telemetry [--port 4318]

Claude Code posts OTLP logs as http/json to /v1/logs (see .env.example).
Each `claude_code.api_request` record becomes one `spend.reported` event,
stage `governance`. The run comes from the `iterum.run_id` attribute, or
`session-<session.id>` for sessions fleet did not start. Identity fields are
never stored. A `request_id` already in the ledger is skipped.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from fleet import db

KIND = "spend.reported"
API_REQUEST = "claude_code.api_request"
KEEP = (
    "request_id",
    "model",
    "cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "duration_ms",
)


def _value(v):
    """Python value of an OTLP AnyValue. OTLP JSON may send int64 as a string."""
    if "intValue" in v:
        return int(v["intValue"])
    for key in ("stringValue", "doubleValue", "boolValue"):
        if key in v:
            return v[key]
    return None


def _attrs(items):
    """OTLP attribute list as a dict."""
    return {a["key"]: _value(a["value"]) for a in items or ()}


def spend(body):
    """Yield (run_id, payload) for every api_request record in an OTLP logs body."""
    for rl in body.get("resourceLogs", ()):
        resource = _attrs(rl.get("resource", {}).get("attributes"))
        for sl in rl.get("scopeLogs", ()):
            for rec in sl.get("logRecords", ()):
                if rec.get("body", {}).get("stringValue") != API_REQUEST:
                    continue
                attrs = resource | _attrs(rec.get("attributes"))
                session = attrs.get("session.id")
                run_id = attrs.get("iterum.run_id") or f"session-{session}"
                payload = {k: attrs[k] for k in KEEP if k in attrs}
                payload["session_id"] = session
                yield run_id, payload


def record(entries):
    """Log each entry unless its request_id is already recorded. Returns (written, skipped)."""
    written = skipped = 0
    with db.write() as con:
        for run_id, payload in entries:
            seen = con.execute(
                "SELECT 1 FROM events WHERE kind=? AND json_extract(payload, '$.request_id')=?",
                (KIND, payload["request_id"]),
            ).fetchone()
            if seen:
                skipped += 1
                continue
            db.log(con, run_id, KIND, stage="governance", **payload)
            written += 1
    return written, skipped


class Receiver(BaseHTTPRequestHandler):
    """Accepts POST /v1/logs; every other path is 404."""

    def do_POST(self):
        if self.path != "/v1/logs":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        written, skipped = record(list(spend(body)))
        if written or skipped:
            print(f"spend: {written} written, {skipped} already recorded", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):
        """Silence the per-request access log; do_POST prints what matters."""


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.telemetry")
    parser.add_argument("--port", type=int, default=4318)
    args = parser.parse_args()

    db.device()  # fail now, not on the first POST, if ITERUM_DEVICE is unset
    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    server = HTTPServer(("127.0.0.1", args.port), Receiver)
    print(f"listening on http://127.0.0.1:{args.port}/v1/logs", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
