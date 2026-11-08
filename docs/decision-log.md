# Decision log

Decisions and why they were made. Newest first. Entries are never deleted; a decision that is reversed is marked "Superseded by" the entry that replaces it. Open decisions live in `open-questions.md`.

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
