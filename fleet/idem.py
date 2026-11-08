"""Exactly-once side effects: keys, receipts, and a retry classifier."""

import hashlib
import json
import sqlite3
import time

from fleet import db

# Axis 1 - is it worth trying again?
# Except timeout, not_found, permission_denied and schema_invalid (our own),
# these are `error` values Claude Code emits on system/api_retry.
# https://code.claude.com/docs/en/headless#handle-api-retries
# TRANSIENT follows what Claude Code itself retries: server errors, overloaded,
# timeouts, and 429 throttles. https://code.claude.com/docs/en/errors
# LOGICAL adds account and setup failures a retry will not fix. Claude Code's
# own "unknown" stays unclassified on purpose.
TRANSIENT = {"rate_limit", "overloaded", "server_error", "timeout"}
LOGICAL = {
    "invalid_request",
    "not_found",
    "permission_denied",
    "schema_invalid",
    "authentication_failed",
    "oauth_org_not_allowed",
    "account_on_hold",
    "billing_error",
    "model_not_found",
    "max_output_tokens",
    "cloud_credential_error",
}

# Axis 2 - might the side effect have happened anyway?
# A refusal is proof it did not. A timeout is proof of nothing.
REFUSED = {
    "rate_limit",
    "overloaded",
    "invalid_request",
    "not_found",
    "permission_denied",
    "schema_invalid",
}
# Used by future code
AMBIGUOUS = {"timeout", "server_error"}


class ParamMismatch(Exception):
    """A key was replayed with different parameters. Never guess; refuse."""


class Uncertain(Exception):
    """A previous attempt started this action and never reported back."""


def key_for(run_id, seq, intent):
    h = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()[:12]
    return f"{run_id}:{seq}:{h}"


def _hash(params):
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def classify(error_category):
    """Return "transient", "logical", or "unknown" for an error category.

    Callers retry only "transient", so "unknown" stops like "logical" does,
    deliberately: guessing "transient" on an unknown failure is how you get
    forty-seven retries. Keeping it distinct tells you which category to add.
    """
    if error_category in TRANSIENT:
        return "transient"
    if error_category in LOGICAL:
        return "logical"
    return "unknown"


def commit_once(run_id, seq, intent, params, action):
    """Run action at most once for this (run, step, intent). Returns (result, replayed)."""
    key = key_for(run_id, seq, intent)
    ph = _hash(params)

    con = db.connect()
    try:
        row = con.execute("SELECT * FROM receipts WHERE idem_key=?", (key,)).fetchone()
    finally:
        con.close()

    if row:
        if row["params_hash"] != ph:
            raise ParamMismatch(f"key {key} replayed with different parameters")
        if row["status"] == "in_flight":
            raise Uncertain(f"key {key} was started and never settled")
        if row["status"] == "failed":
            # Refused, so it definitely did not take effect. Clear it and retry.
            # The status guard stops a racing worker deleting a fresh in_flight claim.
            with db.write() as con:
                con.execute(
                    "DELETE FROM receipts WHERE idem_key=? AND status='failed'", (key,)
                )
        else:
            return json.loads(row["body"]), True

    # Claim the key BEFORE the side effect. The PRIMARY KEY makes this atomic:
    # a second worker racing the same action loses here, not after the fact.
    try:
        with db.write() as con:
            con.execute(
                "INSERT INTO receipts (idem_key,run_id,seq,params_hash,status,created_at)"
                " VALUES (?,?,?,?,'in_flight',?)",
                (key, run_id, seq, ph, time.time()),
            )
            db.log(
                con,
                run_id,
                "action.claimed",
                stage="tool_execution",
                seq=seq,
                idem_key=key,
            )
    except sqlite3.IntegrityError:
        raise Uncertain(f"key {key} claimed by another worker")

    try:
        result = action()  # <-- the side effect, exactly here
    except Exception as exc:
        # Did the action get far enough to matter? A refusal frees the key.
        # Anything ambiguous leaves the receipt in_flight, on purpose.
        category = getattr(exc, "category", None)
        if category in REFUSED:
            with db.write() as con:
                con.execute(
                    "UPDATE receipts SET status='failed', body=?, settled_at=?"
                    " WHERE idem_key=?",
                    (json.dumps({"error": category}), time.time(), key),
                )
                db.log(
                    con,
                    run_id,
                    "action.refused",
                    stage="tool_execution",
                    seq=seq,
                    idem_key=key,
                    category=category,
                )
        raise

    with db.write() as con:
        con.execute(
            "UPDATE receipts SET status='ok', body=?, settled_at=? WHERE idem_key=?",
            (json.dumps(result), time.time(), key),
        )
        db.log(
            con,
            run_id,
            "action.committed",
            stage="tool_execution",
            seq=seq,
            idem_key=key,
        )
    return result, False
