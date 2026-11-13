"""Read-only views of the fleet.

    iterum view                   # live sessions, then ledger runs per agent
    iterum view trace <run_id>    # one run, stage by stage, failing stage named
    iterum view stages [days]     # failures per stage, default last 7 days
    iterum view context [session] # context size per session, or per request in one

`roster()` shells out to `claude agents --json` and returns [] when the CLI is
not there, so every command above works with no Claude Code installed. You get
the ledger half and lose the live half, which is the honest degradation.
"""

import json
import subprocess
import sys
import time

from fleet import db

# No standard exists for this; these are the seven places a run can go wrong
# that are worth telling apart.
STAGES = (
    "planning",
    "retrieval",
    "tool_selection",
    "tool_execution",
    "validation",
    "coordination",
    "response",
)

# Substrings of an event kind that mark a failure, shared by trace() and stages().
FAILURE_KINDS = ("failed", "halted", "dead_letter", "refused", "reaped")

USAGE = "usage: iterum view [trace <run_id> | stages [days] | context [session]]"


def is_failure(kind):
    """True when an event kind records a failure."""
    return any(k in kind for k in FAILURE_KINDS)


def roster():
    """claude agents --json gives the roster. It carries no cost field."""
    try:
        p = subprocess.run(
            ["claude", "agents", "--json"], capture_output=True, text=True, timeout=30
        )
        return json.loads(p.stdout) if p.returncode == 0 else []
    except OSError, subprocess.TimeoutExpired, json.JSONDecodeError:
        return []


def runs_by_agent():
    """Run counts per agent and status, from the ledger's runs table."""
    con = db.connect()
    try:
        return con.execute(
            "SELECT agent, status, COUNT(*) AS runs FROM runs"
            " GROUP BY agent, status ORDER BY agent, status"
        ).fetchall()
    finally:
        con.close()


def status():
    """Live sessions and ledger runs, side by side but not joined.

    Session names and run agents share no key until claude_step() is wired in,
    and runs.cost_usd stays 0 until telemetry fills it, so neither is shown joined.
    """
    now = time.time()
    print(f"{'SESSION':<22} {'STATUS':<9} {'RUNTIME':>8}")
    for a in roster():
        name = a.get("name") or a.get("sessionId", "?")
        runtime = f"{(now - a['startedAt'] / 1000) / 60:.0f}m" if a.get("startedAt") else "-"
        print(f"{name[:22]:<22} {a.get('status', '?'):<9} {runtime:>8}")

    print()
    print(f"{'AGENT':<22} {'STATUS':<16} {'RUNS':>5}")
    for r in runs_by_agent():
        print(f"{r['agent'][:22]:<22} {r['status']:<16} {r['runs']:>5}")


def trace(run_id):
    """Print one run's events in order and name the stage of its first failure."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT event_id, ts, stage, kind, seq, payload FROM events"
            " WHERE run_id=? ORDER BY event_id",
            (run_id,),
        ).fetchall()
        run = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    finally:
        con.close()

    if not rows:
        print(f"no events for {run_id}")
        return

    t0 = rows[0]["ts"]
    print(
        f"run {run_id}  agent={run['agent'] if run else '?'}  "
        f"status={run['status'] if run else '?'}"
    )
    print(f"{'+SEC':>7}  {'STAGE':<16} {'STEP':>4}  EVENT")

    failing = None
    for r in rows:
        marker = " "
        if is_failure(r["kind"]):
            marker = ">"
            # FIRST failure, not last. Everything after it is consequence.
            if failing is None:
                failing = r
        print(
            f"{r['ts']-t0:7.2f}{marker} {r['stage']:<16} "
            f"{(r['seq'] if r['seq'] is not None else '-'):>4}  {r['kind']}"
        )

    if failing:
        print()
        print(
            f"FAILED AT STAGE: {failing['stage']}  (event {failing['event_id']}"
            f"{', step ' + str(failing['seq']) if failing['seq'] is not None else ''})"
        )
        payload = json.loads(failing["payload"])
        for k, v in payload.items():
            print(f"  {k}: {v}")


def stages(days=7):
    """Which stage fails most often, across every run in the ledger.

    Percentages on small denominators lie. Ignore any stage with fewer than
    about thirty events, and remember that a stage which never fails may just
    be untagged.
    """
    since = time.time() - days * 86400
    marks = ",".join("?" * len(STAGES))
    con = db.connect()
    try:
        rows = con.execute(
            f"SELECT stage, kind FROM events WHERE ts > ? AND stage IN ({marks})",
            (since, *STAGES),
        ).fetchall()
    finally:
        con.close()

    counts = {}
    for r in rows:
        failures, events = counts.get(r["stage"], (0, 0))
        counts[r["stage"]] = (failures + is_failure(r["kind"]), events + 1)

    print(f"{'STAGE':<16} {'FAILURES':>9} {'EVENTS':>8} {'RATE':>7}")
    for stage, (failures, events) in sorted(counts.items(), key=lambda c: -c[1][0]):
        print(f"{stage:<16} {failures:>9} {events:>8} {failures / events * 100:>6.1f}%")


CONTEXT_SQL = """
SELECT run_id,
       json_extract(payload, '$.session_id') AS session_id,
       ts,
       CAST(json_extract(payload, '$.input_tokens') AS INTEGER)
     + CAST(json_extract(payload, '$.cache_read_tokens') AS INTEGER)
     + CAST(json_extract(payload, '$.cache_creation_tokens') AS INTEGER) AS context
FROM events
WHERE kind = 'spend.reported'
ORDER BY session_id, ts
"""


def context(session=None):
    """Context size per API request: input plus cache read plus cache write tokens.

    With no session, one line per session: requests, first, last and peak
    context. With a session id, every request in order, to see the slope.
    """
    con = db.connect()
    try:
        rows = con.execute(CONTEXT_SQL).fetchall()
    finally:
        con.close()

    if session:
        print(f"{'#':>4} {'TIME':<19} {'CONTEXT':>9}")
        mine = [r for r in rows if r["session_id"] == session]
        for n, r in enumerate(mine, 1):
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            print(f"{n:>4} {when:<19} {r['context']:>9,}")
        return

    sessions = {}
    for r in rows:
        sessions.setdefault(r["session_id"], []).append(r)
    print(f"{'SESSION':<38} {'REQS':>5} {'FIRST':>9} {'LAST':>9} {'PEAK':>9}  RUN")
    for sid, reqs in sessions.items():
        sizes = [r["context"] for r in reqs]
        print(
            f"{sid:<38} {len(sizes):>5} {sizes[0]:>9,} {sizes[-1]:>9,}"
            f" {max(sizes):>9,}  {reqs[0]['run_id']}"
        )


def main(args):
    """Dispatch to status, trace, stages or context."""
    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    match args:
        case []:
            status()
        case ["trace", run_id]:
            trace(run_id)
        case ["stages"]:
            stages()
        case ["stages", days]:
            stages(int(days))
        case ["context"]:
            context()
        case ["context", session]:
            context(session)
        case _:
            sys.exit(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
