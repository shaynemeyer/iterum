#!/usr/bin/env python3

"""fleet doctor - print which harness layers this machine actually implements.

Reads your real environment, invents nothing, changes nothing.
Run it from the root of a project where you actually use agents.

This is the one module that imports nothing from `fleet`, so it runs before the
package is on your import path.
"""

import json
import os
import subprocess
from pathlib import Path


def default_db():
    """The same default as fleet/db.py's default_path(); doctor imports nothing from fleet."""
    data = os.environ.get("XDG_DATA_HOME", "")
    base = Path(data) if Path(data).is_absolute() else Path.home() / ".local" / "share"
    return base / "iterum" / "agent.db"


DB = Path(os.environ.get("ITERUM_DB") or default_db())
PROJECT = Path.cwd()


def sh(*cmd):
    """Run a command. Return stdout on success, None on any failure."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except OSError, subprocess.TimeoutExpired:
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def db_tables():
    """Table names in agent.db. Empty set if the file is not there yet."""
    if not DB.exists():
        return set()
    import sqlite3

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def layers():
    tables = db_tables()
    agents = sorted(PROJECT.glob(".claude/agents/*.md"))
    claude_md_path = PROJECT / "CLAUDE.md"
    claude_md = claude_md_path.exists() and bool(claude_md_path.read_text().strip())

    hooks = []
    settings = PROJECT / ".claude" / "settings.json"
    if settings.exists():
        try:
            hooks = sorted(json.loads(settings.read_text()).get("hooks", {}))
        except json.JSONDecodeError, OSError:
            hooks = []

    version = sh("claude", "--version")

    live = 0
    roster = sh("claude", "agents", "--json")
    if roster:
        try:
            live = len(json.loads(roster))
        except json.JSONDecodeError:
            live = 0

    return [
        ("execution", bool(version), version or "claude CLI not on PATH"),
        (
            "tooling",
            bool(agents),
            (
                f"{len(agents)} subagent definitions"
                if agents
                else "no .claude/agents/*.md"
            ),
        ),
        (
            "context",
            claude_md,
            "CLAUDE.md present" if claude_md else "no CLAUDE.md, or it is empty",
        ),
        (
            "lifecycle",
            {"runs", "steps"} <= tables,
            (
                f"{DB} has runs+steps"
                if {"runs", "steps"} <= tables
                else f"no durable run state in {DB}"
            ),
        ),
        (
            "observability",
            "events" in tables,
            (
                f"{DB} has an events ledger"
                if "events" in tables
                else f"{live} live agents, no ledger to read them against"
            ),
        ),
        (
            "verification",
            "evals" in tables,
            (
                "eval suite wired to the ledger"
                if "evals" in tables
                else "no replayable test tasks"
            ),
        ),
        (
            "governance",
            "approvals" in tables,
            (
                f"{len(hooks)} hook events configured, approvals recorded"
                if "approvals" in tables
                else f"{len(hooks)} hook events configured, no approval trail"
            ),
        ),
    ]


def main():
    rows = layers()
    width = max(len(name) for name, _, _ in rows)
    for name, ok, evidence in rows:
        status = "IMPLEMENTED" if ok else "NOTHING"
        print(f"{name.ljust(width)}  {status.ljust(11)}  {evidence}")

    gaps = [name for name, ok, _ in rows if not ok]
    print(f"\n{len(gaps)} of {len(rows)} layers: NOTHING")

    Path("harness-audit.json").write_text(
        json.dumps(
            {n: {"implemented": ok, "evidence": ev} for n, ok, ev in rows}, indent=2
        )
        + "\n"
    )
    print("wrote harness-audit.json")


if __name__ == "__main__":
    main()
