"""An approval gate for irreversible actions, and a freeze that stops new queue work.

An approval row records that someone, under the name given, decided about one
exact action at one time. Nothing checks who typed the name, and `approvals` is
mutable control state; the append-only record is the event logged with it.

    uv run python -m fleet.approve
    uv run python -m fleet.approve approve|deny <fingerprint> <who>
    uv run python -m fleet.approve freeze <who> <reason>
    uv run python -m fleet.approve thaw <who>
"""

import argparse
import hashlib
import json
import sys
import time

from fleet import db

IRREVERSIBLE = frozenset({"payment.capture", "email.send", "deploy", "db.migrate", "git.push"})
FROZEN = "FROZEN"  # a budgets scope; its row existing is the freeze


class NeedsApproval(Exception):
    """Paused until a human decides. Asking again returns the same pending request."""


class Denied(Exception):
    """A human said no to this exact action."""


def fingerprint(scope, seq, action, params):
    """Hash the work, not the attempt: `scope` names the work (a task id), never a run id.

    A run id changes on every retry, so hashing it asks again on each attempt.
    Hashing the params binds an approval to the exact action a human saw.
    """
    blob = json.dumps([scope, seq, action, params], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def require(scope, seq, action, params):
    """Return if the action is reversible or approved; otherwise record a request and raise.

    `scope` is stored in the `run_id` column and used as the event's run_id.
    """
    if action not in IRREVERSIBLE:
        return
    fp = fingerprint(scope, seq, action, params)
    with db.write() as con:
        row = con.execute("SELECT * FROM approvals WHERE fingerprint=?", (fp,)).fetchone()
        if not row:
            con.execute(
                "INSERT INTO approvals (run_id,seq,action,fingerprint,decision,requested_at)"
                " VALUES (?,?,?,?,'pending',?)",
                (scope, seq, action, fp, time.time()),
            )
            db.log(con, scope, "approval.requested", stage="governance", seq=seq,
                   action=action, fingerprint=fp)
    if row and row["decision"] == "approved":
        return
    if row and row["decision"] == "denied":
        raise Denied(f"{action} was denied by {row['decided_by']} ({fp})")
    raise NeedsApproval(f"{action} needs a human ({fp})")


def decide(fp, decision, who):
    """Settle one pending request. Raises LookupError if none is pending under `fp`."""
    if decision not in ("approved", "denied"):
        raise ValueError(f"decision must be approved or denied, not {decision!r}")
    with db.write() as con:
        row = con.execute(
            "UPDATE approvals SET decision=?, decided_by=?, decided_at=?"
            " WHERE fingerprint=? AND decision='pending' RETURNING run_id, seq, action",
            (decision, who, time.time(), fp),
        ).fetchone()
        if not row:
            raise LookupError(f"no pending approval {fp}")
        db.log(con, row["run_id"], f"approval.{decision}", stage="governance",
               seq=row["seq"], action=row["action"], decided_by=who, fingerprint=fp)


def pending():
    """Every request still waiting for a human, oldest first."""
    con = db.connect()
    try:
        return con.execute(
            "SELECT * FROM approvals WHERE decision='pending' ORDER BY requested_at"
        ).fetchall()
    finally:
        con.close()


def frozen(con):
    """True while the freeze row exists. Takes a connection so a claim can check inside its transaction."""
    return con.execute("SELECT 1 FROM budgets WHERE scope=?", (FROZEN,)).fetchone() is not None


def freeze(who, reason):
    """Stop queue.claim() handing out tasks. Tasks already claimed run on."""
    with db.write() as con:
        con.execute(
            "INSERT INTO budgets (scope,limit_usd,window_start) VALUES (?,0,?)"
            " ON CONFLICT(scope) DO NOTHING",
            (FROZEN, time.time()),
        )
        db.log(con, "fleet", "fleet.frozen", stage="governance", by=who, reason=reason)


def thaw(who):
    """Lift the freeze. The last step of the runbook, never the first."""
    with db.write() as con:
        con.execute("DELETE FROM budgets WHERE scope=?", (FROZEN,))
        db.log(con, "fleet", "fleet.thawed", stage="governance", by=who)


def show():
    """Print whether the fleet is frozen and every pending request."""
    con = db.connect()
    try:
        print("FROZEN" if frozen(con) else "not frozen")
    finally:
        con.close()
    rows = pending()
    if not rows:
        print("no pending approvals")
    for r in rows:
        print(f"{r['fingerprint']}  {r['action']:16s}  {r['run_id']}  step {r['seq']}")


def main():
    parser = argparse.ArgumentParser(prog="uv run python -m fleet.approve")
    commands = parser.add_subparsers(dest="command")
    for name in ("approve", "deny"):
        cmd = commands.add_parser(name)
        cmd.add_argument("fingerprint")
        cmd.add_argument("who")
    cmd = commands.add_parser("freeze")
    cmd.add_argument("who")
    cmd.add_argument("reason")
    commands.add_parser("thaw").add_argument("who")
    args = parser.parse_args()

    db.init()  # a fresh agent.db has no tables yet; safe to repeat
    if args.command in ("approve", "deny"):
        try:
            decide(args.fingerprint, "approved" if args.command == "approve" else "denied", args.who)
        except LookupError as e:
            sys.exit(str(e))
    elif args.command == "freeze":
        freeze(args.who, args.reason)
    elif args.command == "thaw":
        thaw(args.who)
    show()


if __name__ == "__main__":
    main()
