"""Claim work before doing it. Leases expire; fences make expiry safe."""

import subprocess
import time
from pathlib import Path

from fleet import db

DEFAULT_TTL = 300


class Refused(Exception):
    """Somebody else holds this work."""


class Fenced(Exception):
    """You woke up holding a lease the world has moved past."""


def file_resource(path):
    """The resource name for a file: `file:` plus its path from its git root, or None outside any repo.

    Using the git root gives a file the same name from any directory and in every worktree.
    """
    path = Path(path).resolve()
    existing = next(p for p in path.parents if p.is_dir())  # a new file's folder may not exist yet
    git = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=existing,
        capture_output=True,
        text=True,
        check=False,
    )
    if git.returncode != 0:
        return None
    return f"file:{path.relative_to(Path(git.stdout.strip()).resolve())}"


def acquire(resource, run_id, agent, ttl=DEFAULT_TTL):
    """Claim resource and return a new fence. Logs claim.refused and raises Refused if another holder's lease is live.

    The same run and agent claiming again also gets a new fence, so a paused
    process from before a resume is left holding a stale one.
    """
    now = time.time()
    with db.write() as con:
        row = con.execute(
            "SELECT * FROM claims WHERE resource=?", (resource,)
        ).fetchone()
        held = (
            row
            and row["expires_at"] > now
            and (row["run_id"], row["agent"]) != (run_id, agent)
        )
        if held:
            db.log(
                con,
                run_id,
                "claim.refused",
                stage="coordination",
                resource=resource,
                agent=agent,
                held_by=row["agent"],
                held_by_run=row["run_id"],
                fence=row["fence"],
            )
        else:
            fence = _grant(con, row, resource, run_id, agent, now, ttl)
    # Raised after the block: raising inside it would roll back the claim.refused event.
    if held:
        raise Refused(
            f"{resource} held by {row['agent']} (run {row['run_id']}) "
            f"for another {row['expires_at'] - now:.0f}s"
        )
    return fence


def _grant(con, row, resource, run_id, agent, now, ttl):
    """Replace any existing claim with a new one under the next fence, and return that fence."""
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


def require_claim(con, resource, fence):
    """Refuse a fence that is not current or whose claim is released or expired. Call inside the db.write() block.

    guard() alone lets a released or expired holder write until someone else
    claims the resource. The queue checks its own leases, so it uses guard().
    """
    guard(con, resource, fence)
    live = con.execute(
        "SELECT 1 FROM claims WHERE resource=? AND fence=? AND expires_at>?",
        (resource, fence, time.time()),
    ).fetchone()
    if not live:
        raise Refused(f"{resource}: the claim under fence {fence} was released or has expired")


def renew(resource, run_id, fence, ttl=DEFAULT_TTL):
    """Extend the live lease held under fence. Raises Refused if it expired or is no longer the current claim.

    An expired holder must acquire() again and take a new fence, even if nobody else has claimed the resource.
    """
    now = time.time()
    with db.write() as con:
        cur = con.execute(
            "UPDATE claims SET expires_at=? WHERE resource=? AND fence=? AND expires_at>?",
            (now + ttl, resource, fence, now),
        )
        if cur.rowcount == 0:
            raise Refused(f"{resource}: the claim under fence {fence} expired or is no longer yours")
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
        release_in(con, resource, run_id, fence)


def release_in(con, resource, run_id, fence):
    """release() inside the caller's db.write() block, so the release commits with the caller's write."""
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
