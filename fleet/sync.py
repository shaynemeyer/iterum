"""Share the event ledger across devices through a private sync folder.

Each device writes only the events it created to its own events-<device>.jsonl,
so files never conflict and every event lives in exactly one file. Keep files
from retired or renamed devices: they are the only shared copy of those events.

Settings: ITERUM_DEVICE (required) names this device. ITERUM_SYNC_DIR is the
sync folder, default ~/private-data/iterum.

From any folder:
  iterum sync           # export, commit, pull, push, import, rebuild
  iterum sync export    # write this device's events
  iterum sync import    # merge every device's events

`sync` needs ITERUM_SYNC_DIR to sit inside a git repo with a remote. It commits
only this device's file, so other data in the same repo is left alone.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from fleet import db, project

SYNC_DIR = Path(os.environ.get("ITERUM_SYNC_DIR", "~/private-data/iterum")).expanduser()
COLUMNS = "uid, device, run_id, seq, ts, stage, kind, payload"


def export():
    """Add this device's events to its file, ordered by uid.

    The file is append-only, like the ledger: it keeps every event already in it,
    so a device whose agent.db was lost or rebuilt can never shrink its file.
    """
    device = db.device()
    path = SYNC_DIR / f"events-{device}.jsonl"
    con = db.connect()
    try:
        rows = con.execute(f"SELECT {COLUMNS} FROM events WHERE device = ?", (device,)).fetchall()
    finally:
        con.close()
    events = {e["uid"]: e for e in map(json.loads, path.read_text().splitlines())} if path.exists() else {}
    before = len(events)
    events.update((r["uid"], dict(r)) for r in rows)
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(events[uid]) + "\n" for uid in sorted(events)))
    print(f"exported {len(events) - before} new events to {path} ({len(events)} total)")


def import_events():
    """Merge every events-*.jsonl in the sync folder into the local ledger.

    Events already present (same uid) are skipped. A malformed line raises and
    the whole import rolls back, so the ledger never holds half a sync.
    """
    names = COLUMNS.split(", ")
    insert = (
        f"INSERT INTO events ({COLUMNS}) VALUES ({', '.join(':' + c for c in names)})"
        " ON CONFLICT(uid) DO NOTHING"
    )
    files = sorted(SYNC_DIR.glob("events-*.jsonl"))
    with db.write() as con:
        before = con.total_changes
        for path in files:
            for line in path.read_text().splitlines():
                con.execute(insert, json.loads(line))
        added = con.total_changes - before
    print(f"imported {added} new events from {len(files)} files in {SYNC_DIR}")
    return added


def import_only():
    """The `import` command: merge events, then point at the rebuild step."""
    if import_events():
        print("rebuild knowledge next: iterum project")


def git(*args):
    """Run git in the sync folder. Exit with a clear message on failure."""
    if subprocess.run(["git", "-C", str(SYNC_DIR), *args], check=False).returncode != 0:
        sys.exit(f"git {args[0]} failed in {SYNC_DIR}. Fix it, then rerun sync: every step is safe to repeat.")


def commit_own_file():
    """Commit this device's export file if it changed."""
    name = f"events-{db.device()}.jsonl"
    git("add", "--", name)
    staged = subprocess.run(
        ["git", "-C", str(SYNC_DIR), "diff", "--cached", "--quiet", "--", name], check=False
    )
    if staged.returncode == 1:
        git("commit", "--quiet", "-m", f"iterum: sync {db.device()}", "--", name)
    else:
        print("no new local events to commit")


def sync():
    """Export, commit, pull, push, import and rebuild knowledge."""
    export()
    commit_own_file()
    git("pull", "--rebase", "--autostash", "--quiet")
    git("push", "--quiet")
    import_events()
    project.rebuild()
    print("knowledge rebuilt")


if __name__ == "__main__":
    commands = {"sync": sync, "export": export, "import": import_only}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: iterum sync [{'|'.join(c for c in commands if c != 'sync')}]")
    db.init()  # a brand-new device has no tables yet; safe to repeat
    commands[sys.argv[1]]()
