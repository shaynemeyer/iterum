# Decision log

Decisions and why they were made. Newest first. Entries are never deleted; a decision that is reversed is marked "Superseded by" the entry that replaces it. Open decisions live in `open-questions.md`.

## 2026-11-08: The edit hook fails closed and names files from the git root

**Decision.** `fleet/gate.py` exits 2 on any failure, including a missing `FLEET_RUN_ID` or a relative `ITERUM_DB`. File resources are `file:` plus the path from the git root, built by `claim.file_resource()`. Files outside any git repo are allowed, and unclaimed files are allowed for now.

**Context.** A `PreToolUse` hook that exits with anything but 2 does not block, so a crash let the edit through. A key built from the current directory missed claims from a subdirectory, and a relative database path opened a different, empty database in each worktree.

**Alternatives.** Fail open, so a broken database never blocks work. Or keep `module:` names, which would need a mapping from paths to modules. Blocking `Bash` writes was rejected, because parsing shell commands cannot be complete; the merge gate covers those. Requiring a claim on every edit waits until agents have a way to claim.

**Evidence.** Eighteen cases run as a subprocess in a throwaway git repo with a linked worktree, covering each earlier failure. The hook has not yet been registered in a live Claude Code session.

**Affects.** `fleet/gate.py`, `fleet/claim.py`. A broken database blocks edits until it is repaired.

## 2026-11-08: Claiming again always issues a new fence

**Decision.** `claim.acquire()` issues a new fence even when the same run and agent already hold a live claim. `renew()` and `release()` match on the fence, and `guard()` takes the `db.write()` connection that does the write.

**Context.** `--resume` reuses a `run_id`, and `fleet.recovery` lists a run as dead after 60 seconds while a lease lasts 300. Returning the existing fence would leave a paused process and its resumed copy holding the same one. A `guard()` that only reads leaves a gap between the check and the write.

**Alternatives.** Return the existing fence when `run_id` and `agent` match. Simpler, but it does not separate the old process from the new one.

**Evidence.** On a throwaway database, a second claim by the same run and agent made the first fence stale, and a `release()` or `renew()` with that fence left the new claim alone. A claim attempted during a `db.write()` block that had passed `guard()` was granted only after that block committed.

**Affects.** `fleet/claim.py`. A caller that claims twice invalidates its own earlier fence.

## 2026-11-08: Pin a uv-managed Python for SQLite 3.51.3 or later

**Decision.** Pin Python 3.14.10 in `.python-version`, which bundles SQLite 3.53.1.

**Context.** Python 3.14.4 from uv bundled SQLite 3.50.4, inside the range of a WAL-reset bug fixed in 3.51.3. `sqlite3` uses the SQLite built into the Python build.

**Alternatives.** Build the virtualenv from Homebrew's Python 3.14.7 (SQLite 3.53.4). No download needed, but it ties the project to one machine's Homebrew install.

**Evidence.** `uv run python -c "import sqlite3; print(sqlite3.sqlite_version)"` reports 3.53.1. The six-step drill plan and `fleet.recovery` ran cleanly on it.

**Affects.** `.python-version`. Each device needs a uv that can install 3.14.10.

## 2026-11-08: Freeing a failed receipt checks its status

**Decision.** `commit_once()` clears a `failed` receipt with `DELETE ... WHERE idem_key=? AND status='failed'`, not by key alone.

**Context.** Two workers could both read a `failed` receipt. The first deleted it and claimed the key `in_flight`; the second then deleted that fresh claim and claimed the key again, so the action ran twice.

**Alternatives.** Do the read, the delete and the claim in one `db.write()` transaction. Also correct, but a larger change to the function.

**Evidence.** A two-thread test that holds both workers after their first read ran the action twice before the fix and once after (three runs). The losing worker now gets `Uncertain` from its failed claim.

**Affects.** `fleet/idem.py`.

## 2026-11-08: `receipts` is the only receipt store

**Decision.** Keep the `receipts` table and remove the unused `steps.idem_key` and `steps.receipt` columns from `fleet/schema.sql`. No migration for existing databases.

**Context.** The schema offered two places for an idempotency key. Only `receipts` holds a status, a parameter hash and a settle time, and its primary key is what makes a claim atomic.

**Alternatives.** Keep both; or drop the columns from existing databases too.

**Evidence.** No code read or wrote the two columns, and they were empty in `agent.db`. SQLite 3.50.4 refuses `ALTER TABLE steps DROP COLUMN idem_key` with `cannot drop UNIQUE column`, so removing it from old databases would mean rebuilding `steps`. Old databases keep two empty columns; every query on `steps` names its columns, so nothing depends on them.

**Affects.** `fleet/schema.sql`, `CLAUDE.md` (lists `receipts` as control state).

## 2026-11-08: Claude Code's account and setup errors are `LOGICAL`, not `REFUSED`

**Decision.** Add `authentication_failed`, `oauth_org_not_allowed`, `account_on_hold`, `billing_error`, `model_not_found`, `max_output_tokens` and `cloud_credential_error` to `idem.LOGICAL`. Do not add them to `REFUSED`. Claude Code's own `unknown` stays unclassified.

**Context.** These are `error` values Claude Code emits on `system/api_retry`. A retry will not fix them, and Claude Code has usually retried already. `REFUSED` frees the key, which is only safe if nothing happened; a `claude -p` session can fail on these partway through, after tools have run.

**Alternatives.** Add them to both sets; or leave them unclassified.

**Evidence.** https://code.claude.com/docs/en/headless#handle-api-retries lists the categories. https://code.claude.com/docs/en/errors says Claude Code retries server errors, overloaded responses, timeouts and 429s up to 10 times. That a mid-session failure can follow side effects is a reading of the docs, not tested.

**Affects.** `fleet/idem.py`. Whether any belong in `REFUSED` is an open question.

## 2026-11-08: `run_step` halts at once on `AMBIGUOUS` failures

**Decision.** In `fleet/step.py`, a `StepError` whose category is in `idem.AMBIGUOUS` (`timeout`, `server_error`) is classified `ambiguous` and halts on the first attempt, re-raising the `StepError`.

**Context.** Those categories were classified `transient`, so `run_step` slept and retried. But `commit_once()` leaves their receipt `in_flight`, so the retry could only raise `Uncertain`, and the halt reason lost the real cause.

**Alternatives.** Keep retrying; or move `timeout` and `server_error` out of `TRANSIENT`, which would also change `classify()` for every caller.

**Evidence.** Before: one action call, a 2.0s sleep, halt reason `key ... was started and never settled`. After: one call, no sleep, halt reason `timeout: request timed out`. `rate_limit` still retries three times.

**Affects.** `fleet/step.py`. Callers now get `StepError` instead of `Uncertain` for these categories; tracked in `todo.md`.

## 2026-11-08: An ambiguous failure keeps the key locked

**Decision.** When an action fails without proof that nothing happened (no category, or a category outside `REFUSED`), `commit_once()` leaves the receipt `in_flight` and every later attempt raises `Uncertain` until a human settles it. Actions that know nothing ran may say so by raising an error whose `category` is in `REFUSED`.

**Context.** `commit_once()` sees only its own `receipts` table and cannot ask the outside system whether the action took effect.

**Alternatives.** Free the key on any failure. Rejected: an action that did half its work would run again, which is the failure the module exists to prevent.

**Evidence.** Reasoning, not a test: a wrong lock costs one halt and a human check; a wrong unlock can repeat a deploy, a message or a charge.

**Affects.** `fleet/idem.py`. Makes a way to settle stuck receipts necessary; open question.
