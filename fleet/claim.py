"""Claim work before doing it. Leases expire; fences make expiry safe."""

import time

from fleet import db

DEFAULT_TTL = 300


class Refused(Exception):
    """Somebody else holds this work."""


class Fenced(Exception):
    """You woke up holding a lease the world has moved past."""


def acquire(resource, run_id, agent, ttl=DEFAULT_TTL):
    """Claim resource and return a new fence. Raises Refused if another holder's lease is live.

    The same run and agent claiming again also gets a new fence, so a paused
    process from before a resume is left holding a stale one.
    """
    now = time.time()
    with db.write() as con:
        row = con.execute(
            "SELECT * FROM claims WHERE resource=?", (resource,)
        ).fetchone()
        if (
            row
            and row["expires_at"] > now
            and (row["run_id"], row["agent"]) != (run_id, agent)
        ):
            raise Refused(
                f"{resource} held by {row['agent']} "
                f"for another {row['expires_at'] - now:.0f}s"
            )
        if row:
            db.log(
                con,
                run_id,
                "claim.reclaimed",
                stage="coordination",
                resource=resource,
                from_agent=row["agent"],
            )
            con.execute("DELETE FROM claims WHERE resource=?", (resource,))

        # Monotonic fence: never reused, never reset, even across reclaims.
        con.execute(
            "INSERT INTO fences (resource, high) VALUES (?, 0)"
            " ON CONFLICT(resource) DO NOTHING",
            (resource,),
        )
        con.execute("UPDATE fences SET high = high + 1 WHERE resource=?", (resource,))
        fence = con.execute(
            "SELECT high FROM fences WHERE resource=?", (resource,)
        ).fetchone()["high"]

        con.execute(
            "INSERT INTO claims (resource,run_id,agent,fence,granted_at,expires_at)"
            " VALUES (?,?,?,?,?,?)",
            (resource, run_id, agent, fence, now, now + ttl),
        )
        db.log(
            con,
            run_id,
            "claim.granted",
            stage="coordination",
            resource=resource,
            agent=agent,
            fence=fence,
            ttl=ttl,
        )
    return fence


def guard(con, resource, fence):
    """Refuse a fence that is not current. Call inside the db.write() block that does the write.

    Checking outside that block would let a newer fence be issued between the
    check and the write.
    """
    row = con.execute(
        "SELECT high FROM fences WHERE resource=?", (resource,)
    ).fetchone()
    if not row or fence > row["high"]:
        raise Fenced(f"{resource}: fence {fence} was never issued")
    if fence < row["high"]:
        raise Fenced(
            f"{resource}: your fence {fence} is behind the current {row['high']}"
        )


def renew(resource, run_id, fence, ttl=DEFAULT_TTL):
    """Extend the lease held under fence. Raises Refused if it is no longer the current claim."""
    with db.write() as con:
        cur = con.execute(
            "UPDATE claims SET expires_at=? WHERE resource=? AND fence=?",
            (time.time() + ttl, resource, fence),
        )
        if cur.rowcount == 0:
            raise Refused(f"{resource} is no longer yours")
        db.log(
            con,
            run_id,
            "claim.renewed",
            stage="coordination",
            resource=resource,
            fence=fence,
            ttl=ttl,
        )


def release(resource, run_id, fence):
    """Drop the claim held under fence. A stale fence changes nothing and logs nothing."""
    with db.write() as con:
        cur = con.execute(
            "DELETE FROM claims WHERE resource=? AND fence=?", (resource, fence)
        )
        if cur.rowcount == 1:
            db.log(
                con,
                run_id,
                "claim.released",
                stage="coordination",
                resource=resource,
                fence=fence,
            )
