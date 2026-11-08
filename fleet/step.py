"""One step, retried only when the failure class says it is worth it.

This is where the receipts module from idem.py actually gets called. A receipts
module nobody calls protects nothing.

`run_step` UPDATEs a `steps` row, so called on its own, with no runner having
INSERTed that row, it would update zero rows: the run then looks unstarted and
a resume redoes everything. `_propose` below writes the row first, using the
same write-before-act ordering as `fleet/run.py`'s `execute()`, and it is a
no-op when the runner already wrote the row.
"""

import time

from fleet import db, idem


class StepError(Exception):
    def __init__(self, category, msg):
        super().__init__(msg)
        self.category = category


def _propose(run_id, seq, intent):
    """Write the `proposed` row before the action, if nothing else has."""
    with db.write() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO steps (run_id,seq,intent,status,started_at)"
            " VALUES (?,?,?,'proposed',?)",
            (run_id, seq, str(intent), time.time()),
        )
        if cur.rowcount:
            db.log(
                con,
                run_id,
                "step.proposed",
                stage="planning",
                seq=seq,
                intent=str(intent),
            )


def halt(run_id, seq, kind, reason):
    with db.write() as con:
        con.execute(
            "UPDATE runs SET status='halted', ended_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        db.log(
            con,
            run_id,
            "run.halted",
            stage="validation",
            seq=seq,
            classification=kind,
            reason=reason,
        )
    print(f"HALTED at step {seq}: [{kind}] {reason}")


def run_step(run_id, seq, intent, params, action, max_attempts=3):
    """One step, retried only when the failure class says it is worth retrying."""
    _propose(run_id, seq, intent)

    for attempt in range(1, max_attempts + 1):
        try:
            result, replayed = idem.commit_once(run_id, seq, intent, params, action)
            with db.write() as con:
                con.execute(
                    "UPDATE steps SET status='committed', ended_at=?"
                    " WHERE run_id=? AND seq=?",
                    (time.time(), run_id, seq),
                )
            return result, replayed

        except idem.ParamMismatch as e:
            halt(run_id, seq, "param_mismatch", str(e))
            raise
        except idem.Uncertain as e:
            halt(run_id, seq, "uncertain", str(e))
            raise

        except StepError as e:
            # commit_once leaves AMBIGUOUS receipts in_flight, so a retry can only
            # hit Uncertain. Halt now and keep the real cause in the reason.
            if e.category in idem.AMBIGUOUS:
                kind = "ambiguous"
            else:
                kind = idem.classify(e.category)
            with db.write() as con:
                db.log(
                    con,
                    run_id,
                    "step.failed",
                    stage="tool_execution",
                    seq=seq,
                    attempt=attempt,
                    category=e.category,
                    classified=kind,
                )
            if kind != "transient" or attempt == max_attempts:
                halt(run_id, seq, kind, f"{e.category}: {e}")
                raise
            time.sleep(min(2**attempt, 30))
