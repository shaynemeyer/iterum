# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Wire `iterum.run_id` into `claude_step()`

When `claude_step()` replaces `shell()` in `fleet/run.py`, it must start Claude Code with the `.env.example` settings plus `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<run_id>`, so spend lands under the run instead of `session-<session.id>`.

## A killed run.py leaves its step's command running

Found in the `kill -9` test (see `work-completed.md`). `shell()` starts each step with `subprocess.run(cmd, shell=True)`. After `kill -9` on run.py mid step 5, `/bin/sh -c sleep 20 && echo summary > out/summary.txt` and its `sleep 20` were still alive, reparented, and later wrote `out/summary.txt`. A resume before that finishes runs step 5 a second time while the first copy is still going. Reproduced 2026-11-10: SIGKILL 8 seconds into the drill, then `--resume` at once. Two seconds later two `sleep 20` processes were alive, started 07:42:45 and 07:42:50, matching the two `step.proposed` events for step 5. The resume ran to `done` without noticing.

`--resume` now refuses a run whose heartbeat is fresh (see `work-completed.md`). That narrows this gap but does not close it. The drill's leftover `sleep 20` ran about 15 seconds past the kill, well inside the 60-second expiry, but a step that runs longer than the expiry after a kill (a `claude_step()` can take minutes) would still overlap with the resume. Reproduced 2026-11-10 with a one-step plan, `sleep 60 && echo done >> out/long.txt`, and `ITERUM_IDLE_SECONDS=15`: SIGKILL at 07:49:58, `--resume` without `--force` accepted at 07:50:15. Two `sleep 60` processes were alive at 07:50:17 (started 07:49:55 and 07:50:15), step 1 has two `step.proposed` events, and `out/long.txt` holds `done` twice: the side effect ran twice.

Copying the worker's process group would not fix this. The worker's group only helps on a timeout, when the worker itself calls `os.killpg` (`fleet/worker.py`); a SIGKILLed process calls nothing. A resume would have to detect the leftover command itself, for example by storing the step's process group id in `steps` and refusing to resume while that group is alive. Untested idea; refusing avoids killing a reused process id. The worker likely has the same gap under SIGKILL; not checked.

## `commit_once` logs nothing on an ambiguous failure

When an action fails without a `REFUSED` category, `commit_once()` leaves the receipt `in_flight` and writes no event, so the ledger shows `action.claimed` with no outcome. `run_step()` covers this with `step.failed` and `run.halted`, but a direct caller of `commit_once()` leaves no record of why the receipt is stuck. Log an event (for example `action.uncertain`, with the category) before re-raising.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

## Enforce the `fences` rules in the database

Status: open. Do this before anything relies on `fleet/claim.py`, which writes `fences` through `acquire()`.

`fleet/schema.sql` says `fences` rows are never deleted and `high` only counts up, but nothing enforces it. A reset is silent: a stale agent's fence can match or beat the new one.

1. Add these after the `fences` table in `fleet/schema.sql`:

   ```sql
   CREATE TRIGGER IF NOT EXISTS fences_no_delete BEFORE DELETE ON fences
   BEGIN SELECT RAISE(ABORT, 'fences rows are never deleted'); END;

   CREATE TRIGGER IF NOT EXISTS fences_only_up BEFORE UPDATE ON fences
   WHEN NEW.high <= OLD.high OR NEW.resource IS NOT OLD.resource
   BEGIN SELECT RAISE(ABORT, 'fences.high only counts up'); END;
   ```

2. Add `con.execute("PRAGMA recursive_triggers = ON")` to `connect()` in `fleet/db.py`. Without it, `INSERT OR REPLACE` resets a fence without firing either trigger (tested against the schema in memory, SQLite 3.50.4). `steps` is the only table written with `REPLACE` today and has no triggers, so nothing else changes.

`claim.acquire()` already raises the fence in the same `db.write()` block as the `claims` update, and issued 1, 2, 3, 4 with these triggers and the `PRAGMA` in place.

These guard against bugs, not a hostile agent: anything with shell access can still drop the triggers or connect without the `PRAGMA`.

## Build the merge gate that checks fences

Status: open. `fleet/claim.py` issues fences and provides `guard()`, but nothing calls it yet.

A fence protects nothing unless whatever accepts the write checks it. An agent cannot check its own fence, because it can pause right after checking. A `PreToolUse` hook has the same gap, and one that times out does not block the call.

1. Agents edit only in their own git worktrees.
2. A single merge process lands each change on the shared branch. It builds the merge outside any transaction. Then, inside one `db.write()` block, it calls `claim.guard()` and moves the branch with `git update-ref` and the expected old value, so no newer fence can be issued between the check and the update. Do not hold the write lock for the whole merge: other writers fail after the 5-second busy timeout.
3. Decide how to recover from a crash during the update. Git and SQLite do not commit together.
4. Wire claims into `fleet/run.py`, and renew them while a step runs. A step longer than `claim.DEFAULT_TTL` (300 seconds) would otherwise lose its lease.
5. Add a drill for the paused-agent case: Agent A claims a resource and stops, its lease expires, Agent B claims it, then Agent A tries to merge and is refused.

File claims do not catch changes in different files that break each other, even when the merge is clean. Tests or CI still have to catch those.
