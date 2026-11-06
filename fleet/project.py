"""Rebuild the knowledge table (contract 3) from the events ledger (contract 2).

Knowledge is a projection: everything in it must be derivable from
`layer.checked` events. If the rebuilt table differs from the stored one,
something wrote knowledge without recording an event.

Run from the repo root: `uv run python -m fleet.project`

Not read-only: it always replaces the knowledge table with the rebuild.
Prints MATCH and exits 0 when the fingerprints agree, or DRIFT and exits 1
when they differ, so a hook can fail on drift. A first run against an
empty knowledge table reports DRIFT.
"""

import hashlib
import json
import sys

from fleet import db


def fingerprint(con):
    """A stable hash of the knowledge table, ignoring row ids."""
    rows = con.execute(
        "SELECT subject, claim, scope, source_event FROM knowledge "
        "ORDER BY subject, claim, source_event"
    ).fetchall()
    blob = json.dumps([tuple(r) for r in rows], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def rebuild():
    with db.write() as con:
        before = fingerprint(con)
        con.execute("DELETE FROM knowledge")
        for ev in con.execute(
            "SELECT event_id, ts, payload FROM events "
            "WHERE kind = 'layer.checked' ORDER BY event_id"
        ).fetchall():
            p = json.loads(ev["payload"])
            con.execute(
                "INSERT INTO knowledge (subject, claim, source_event, scope, valid_from)"
                " VALUES (?,?,?,?,?)",
                (
                    f"layer:{p['layer']}",
                    "implemented" if p["implemented"] else "nothing",
                    ev["event_id"],
                    "project",
                    ev["ts"],
                ),
            )
        after = fingerprint(con)
    return before, after


if __name__ == "__main__":
    before, after = rebuild()
    print(f"before: {before}")
    print(f"after:  {after}")
    if before == after:
        print("MATCH - the projection is rebuildable from the ledger")
    else:
        print("DRIFT - something wrote knowledge that no event explains")
        sys.exit(1)
