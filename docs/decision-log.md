# Decision log

Decisions and why they were made. Newest first. Entries are never deleted; a decision that is reversed is marked "Superseded by" the entry that replaces it. Open decisions live in `open-questions.md`.

## 2026-11-10: The merge gate requires a live claim, not just the current fence

**Decision.** For the open question "Should `claim.guard()` also require a live claim?": yes, but through a new `claim.require_claim()`, not by changing `guard()`. It calls `guard()` and then requires a `claims` row with the same resource and fence whose `expires_at` has not passed, and raises `Refused` otherwise. The merge gate calls `require_claim()`.

**Context.** With `guard()` alone, a holder that released its claim, or whose lease expired with no successor, can write until someone else claims the resource. The `claims` table then says nobody holds it while a write is still allowed, and a merge after `release()` (a bug) gets through. A holder that is refused can call `acquire()` again: if nobody else took the resource it gets a new fence and passes.

**Alternatives.** Keep `guard()` fence-only for the merge gate, which is the usual fencing-token check and needs no clock ([Kleppmann, "How to do distributed locking"](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)). It would not let two writers overlap, but it allows the two cases above. Put the claims check inside `guard()`: `fleet/queue.py` calls `guard()` on `task:<id>` fences and never writes `claims` rows (it checks `leases` in `_require_lease()`), so every worker would be refused.

**Evidence.** On a scratch database, before the change `guard()` accepted an expired holder with no successor and a released holder. After it, `require_claim()` refused both with `Refused`, accepted the live current holder and a holder that re-acquired after expiry (fence 1 to 2), and still refused a stale fence after takeover and a never-issued fence with `Fenced`.

**Affects.** `fleet/claim.py` and the merge gate in `todo.md`. `guard()` and the queue are unchanged. The merge process reads the clock to compare with `expires_at`. A slow holder that misses renewal is refused even when nobody else wants the resource. `renew()` can still revive an expired claim; see `open-questions.md`.

## 2026-11-10: The worker kills its command's group on any early exit

**Decision.** `_shell()` in `fleet/worker.py` kills the command's process group on any exception while it runs (`except BaseException`), not only a timeout.

**Context.** `_shell()` now calls `queue.record_pgid()`, which can raise `Fenced`, `Refused` or a busy `sqlite3.OperationalError` after the command has started. A command left running with no lease that knows its group is the overlap the fix removes. Ctrl-C is also an early exit.

**Alternatives.** List the exceptions (`TimeoutExpired`, `Fenced`, `Refused`): misses a busy database and Ctrl-C. Leave Ctrl-C alone: the command would run on with nothing waiting for it, as `fleet/run.py` did before its own Ctrl-C entry below.

**Evidence.** See the work-completed entry "A SIGKILLed worker's task command overlaps the rescuer's rerun", paragraph "Ctrl-C".

**Affects.** `fleet/worker.py`. SIGKILL and SIGTERM still leave the command running; `reap()` waits for those.

## 2026-11-10: The reaper waits for a dead worker's task command, default `do_work` only

**Decision.** For the todo "A SIGKILLed worker's task command overlaps the rescuer's rerun": only the default `do_work` records its process group on the lease. A worker module set with `FLEET_WORK_MODULE` must handle its own processes. When `reap()` skips an expired lease because its group is still alive, it prints a line and writes no ledger event.

**Context.** The overlap comes from `_shell()`, which only the default `do_work` uses. `reap()` runs every 5 seconds in every worker.

**Alternatives.** Cover every `do_work` by changing its contract, for example passing it a way to record a group id: no custom module exists to test it against. A ledger event per skipped reap: a 10-minute command would write about 120 identical events. One event per lease would need extra state to remember it was logged.

**Evidence.** See the work-completed entry "Does the worker leave a task's command running when SIGKILLed?".

**Affects.** `fleet/worker.py` (its docstring should name the limit), `fleet/queue.py`. While `reap()` waits, why the task is still `in_progress` shows only in the reaping worker's output; the ledger shows the wait as a longer gap between `task.claimed` and `task.reaped`.

## 2026-11-10: Ctrl-C kills the step's process group

**Decision.** `shell()` in `fleet/run.py` catches `KeyboardInterrupt` while waiting on a step, kills the step's process group with `os.killpg(pgid, SIGKILL)` and re-raises.

**Context.** Running each step in its own group (next entry down) took the command out of the terminal's foreground process group, so Ctrl-C stopped `run.py` but left the command running, unlike before.

**Alternatives.** Leave it, and let the resume guard wait for the command: Ctrl-C would no longer stop what it visibly stopped before. SIGTERM to the group instead of SIGKILL: gives the command a chance to clean up, but `fleet/worker.py` already uses SIGKILL on a timeout, and one rule is simpler.

**Evidence.** See the work-completed entry "A killed run.py leaves its step's command running", paragraph "Ctrl-C".

**Affects.** `fleet/run.py`. Covers Ctrl-C only; SIGTERM and SIGKILL still leave the command running, and the resume guard covers those.

## 2026-11-10: `--resume` refuses while a step's process group is alive

**Decision.** `fleet/run.py` runs each step's command in its own process group, stores the group id in `steps.pgid`, and `check_resumable()` refuses (unless `--force`) while an uncommitted step's group has any process left.

**Context.** A SIGKILLed `run.py` leaves its step's command running. The heartbeat check does not help once the command keeps running past the expiry: a resume then ran the step a second time alongside it.

**Alternatives.** Kill the leftover group on resume: a stored group id can be reused by an unrelated process, and killing it would be wrong; a refusal only costs a wait or `--force`. Longer expiry: any fixed value is beaten by a long enough step. The worker's approach (kill the group on timeout, from the worker): the dying process cannot run it.

**Evidence.** See the work-completed entry "A killed run.py leaves its step's command running".

**Affects.** `fleet/run.py`, `fleet/schema.sql`, `fleet/db.py`, `CLAUDE.md`. A kill between starting the command and writing `pgid` leaves no group to check; that window is one SQLite write. Ctrl-C no longer reaches the command on its own; see the next entry up. `os.killpg` is POSIX only.

## 2026-11-10: `--resume` treats a fresh heartbeat as a live run

**Decision.** `check_resumable()` refuses a `running` run whose `heartbeat_at` is younger than `recovery.IDLE_SECONDS` (`ITERUM_IDLE_SECONDS`, default 60). `--force` overrides it.

**Context.** `--resume` checked only the status, so it started a second `run.py` on a run whose first process was still alive, and both ran the remaining steps.

**Alternatives.** A separate expiry for resume: two numbers that mean "dead" could disagree, so `fleet.recovery` would list a run that `--resume` refuses, or the reverse. No override: a person who knows the process is gone would have to wait out the expiry; `--force` already means "a human has looked" for `halted` runs.

**Evidence.** See the work-completed entry "`--resume` refuses a run that may still be alive" for before and after runs on scratch databases.

**Affects.** `fleet/run.py`, `CLAUDE.md`. `run.py` now imports `fleet.recovery`. A run without a heartbeat is not checked. Note `fleet.recovery --idle-seconds` changes only recovery's cutoff; resume reads the environment variable.

## 2026-11-10: Claude Code exports telemetry logs every second

**Decision.** `.env.example` sets `OTEL_LOGS_EXPORT_INTERVAL=1000`, down from the documented default of 5000 ms.

**Context.** Claude Code buffers events between exports. A session killed with SIGKILL loses every `api_request` that finished since the last export, so `fleet/telemetry.py` never sees that spend.

**Alternatives.** Keep the default: in the test below it lost two of three requests. Go below one second: one second already lost nothing in the test, and each step down adds POSTs for no measured gain.

**Evidence.** Two runs against `fleet.telemetry` on a scratch database, each a Haiku session killed at 10 s after three completed requests (by `requestId` in its transcript). At 5000 ms, 1 of 3 arrived; at 1000 ms, 3 of 3. One run per setting.

**Affects.** `.env.example`, `docs/telemetry/claude-code-telemetry.md`. A busy session sends at most one small POST per second to the local receiver. A request in flight at the kill is still unrecorded.

## 2026-11-10: Spend events are `spend.reported`, stage `governance`

**Decision.** `fleet/telemetry.py` logs each Claude Code `api_request` as kind `spend.reported` with stage `governance`. The payload keeps `request_id`, `model`, `cost_usd`, the token counts, `duration_ms` and `session_id`. The `run_id` is `iterum.run_id`, or `session-<session.id>` when that is missing. A `request_id` already in the ledger is skipped, checked with `json_extract` inside the same `db.write()`.

**Context.** The earlier entry today chose ledger events for spend but left the kind, the stage and the receiver open.

**Alternatives.** Kind `claude.api_request`: every other kind is a noun and a past-tense verb (`run.started`, `step.committed`, `task.reaped`), and it named the source rather than what happened. Stage `scheduling`: it is queue bookkeeping, used only in `fleet/queue.py`. Stage `governance` already names the hooks and approvals layer in `fleet/doctor.py`, and is not in `STAGES`, so `fleet.view stages` does not count spend as a failure.

**Evidence.** A synthetic OTLP body posted twice to `fleet.telemetry` on a scratch database wrote two events and skipped the duplicate and the repeat; the `user_prompt` record and a fake `user.email` were not stored, and a string `intValue` was read as a number. A real `claude -p` session on Haiku sent three requests, which became three `spend.reported` events under `iterum.run_id`. `fleet.view trace` shows them; `fleet.view stages` leaves them out.

**Affects.** `fleet/telemetry.py`, `.env.example`, `docs/telemetry/claude-code-telemetry.md`. The dedupe query scans every `spend.reported` event; add an index if it gets slow.

## 2026-11-10: Claude Code spend lands in the ledger, one event per API request

**Decision.** Spend is recorded as ledger events, one per Claude Code `claude_code.api_request` telemetry event. Each event's `run_id` comes from a custom resource attribute, `iterum.run_id`, which `fleet` sets through `OTEL_RESOURCE_ATTRIBUTES` when it starts a session. Sessions `fleet` did not start fall back to `session.id`. The ledger event keeps `request_id`, `cost_usd`, `model` and token counts, and drops `user.email`, `user.id`, `user.account_uuid`, `user.account_id` and `organization.id`. `request_id` is the dedupe key. The `claude_code.cost.usage` metric is not imported. `runs.cost_usd` is not written.

**Context.** `runs.cost_usd` was always 0 because nothing passed a cost to `db.finish_run()`. Claude Code exports cost as OpenTelemetry metrics and events (https://code.claude.com/docs/en/monitoring-usage). The `cost_usd` field is described there as "Estimated cost in USD", so these figures compare agents and are not billing.

**Alternatives.** Update `runs.cost_usd`: `runs` is local to one machine and never synced, so spend would stay on the device that recorded it, and an update keeps no history. Import the `cost.usage` metric: it is a cumulative counter per session, the wrong shape for an append-only ledger, and the events already sum to it.

**Evidence.** Two `claude -p` sessions on Haiku, Claude Code 2.1.322, with console exporters and `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<id>`. `iterum.run_id` and `session.id` were on every event and metric datapoint. The four-request session produced four `api_request` events with four distinct `request_id`s; their `cost_usd` summed to 0.00541548, equal to the final `cost.usage` value. `cost_usd_micros` is rounded per request (4125 for 0.00412534), so `cost_usd` is stored instead. The five identity fields were on every record. A third session with `OTEL_LOGS_EXPORTER=otlp`, `OTEL_METRICS_EXPORTER=none`, `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json` and `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:14318/v1/logs` posted three `application/json` requests to `/v1/logs`, received by a standard-library `http.server`; the `api_request` record carried `iterum.run_id`, `request_id`, `cost_usd` (`doubleValue`) and the token counts (`intValue`).

**Affects.** A receiver in `fleet` (not written yet) that takes OTLP logs as `http/json` with the standard library alone, and `claude_step()` when it is wired in. Not yet tested: a session using more than one model, and how much a killed session loses before export.

## 2026-11-10: Queue failures are tagged with the stage where they happened

**Decision.** `_spend_attempt()` always logs the cause of a spent attempt in its own stage: `task.failed` as `tool_execution`, `task.reaped` as `coordination`. When no attempts are left, `task.dead_lettered` follows as `scheduling`. `fleet/view.py` counts `failed`, `halted`, `dead_letter`, `refused` and `reaped` kinds as failures.

**Context.** Every queue event was tagged `scheduling`, which is outside the seven failure stages, so `view stages` never saw a queue failure. On the last attempt only `task.dead_lettered` was logged, so the cause was lost. `trace()` did not count `reaped`, so it named `scheduling` as the failing stage.

**Alternatives.** Retag only, keeping one event per attempt: the last attempt would still lose its cause. Add `scheduling` to the failure stages: it records consequences, and counting them would make one failure show up twice. Tag `task.reaped` as `tool_execution`: a dead worker needs a different fix from a failing command, and a reap is the lease system's call, the same family as a refused claim.

**Evidence.** On scratch databases, before: a task failing its only attempt logged `task.claimed` then `task.dead_lettered`, both `scheduling`. After: `task.failed` (`tool_execution`) then `task.dead_lettered`; `view stages` shows 3 of 3 failures under `tool_execution`. A reaped task shows `task.reaped` as `coordination`, and `view trace` reports `FAILED AT STAGE: coordination`. `fleet.kill_drill` passes unchanged.

**Affects.** `fleet/queue.py`, `fleet/view.py`. A final failure now writes one more event. Events already in a ledger keep their old `scheduling` tag, since `events` is append-only.

## 2026-11-09: Conflicts wait on the queue for a person

**Decision.** `tasks.result` keeps what `do_work` returns. `claim()` skips tasks of kind `resolve_conflict`, and only `queue.resolve()`, reached through `fleet.conflicts`, closes them. Tasks that depend on a conflict wait until a person settles it.

**Context.** The worker discarded `do_work`'s return value, so there was nothing to compare. A `resolve_conflict` task was claimed like any other: under the default worker it failed three times on a missing `cmd` and was dead-lettered, so it never reached a person.

**Alternatives.** A separate table for human work: more schema for what is still a task with a status. Keeping results only in the ledger: events sync to every device and results can be large. A list of kinds for `claim()` to skip: only one kind exists.

**Evidence.** Tested on throwaway databases: a worker leaves the task `ready`, `resolve` closes it and logs `task.resolved`, and its dependent then runs.

**Affects.** `fleet/queue.py`, `fleet/worker.py`, `fleet/conflicts.py`, `fleet/schema.sql`, `fleet/db.py`. `depends_on` holds one parent, so a merge task cannot wait on both reviewers; the caller polls `queue.results()`.

## 2026-11-09: Queue workers prove ownership with a fence, and failure cascades

**Decision.** `queue.claim()` issues a fence per task from the `fences` table, and `heartbeat`, `finish`, `fail` and `release_back` require that fence and a live lease. A dead-lettered task halts everything waiting on it with a reason naming the task, and `redrive()` restores tasks halted for that reason. Retries wait in a new `tasks.not_before` column, 5 seconds doubling per attempt. Workers reap inside their own loop every 5 seconds. Shell tasks run in their own process group and stop at the task's deadline or `FLEET_TASK_TIMEOUT_S` (600), whichever is sooner.

**Context.** `worker` was logged but never checked, so after a reap and re-claim the old worker's `finish` marked the task done and deleted the new worker's lease, and `finish` could turn `dead_letter` into `done`. Children of a dead-lettered task stayed `ready` forever with nothing to say why. Without backoff, a failing task spent all 3 attempts in about 0.2 seconds.

**Alternatives.** Check only the worker name: a restarted process reusing its name would pass. Leave children `ready` so that a redrive needs no restore: they stay stranded with no visible reason, and never reach a terminal state. Sleep in the worker after a failure: another worker could re-claim the task at once. A separate reaper process: one more thing to forget to start.

**Evidence.** Reproduced before and after on throwaway databases: a stale `finish` is refused with `Fenced` even under the current holder's name; a 1-second task on a 0.3-second lease ran once under heartbeats, and twice without them. The 600-second default and the backoff values are starting guesses, not measurements.

**Affects.** `fleet/queue.py`, `fleet/worker.py`, `fleet/schema.sql`, `fleet/db.py`. Reaping pauses while every worker is busy, and a command keeps running after its lease is lost until it exits or times out.

## 2026-11-09: `fleet/drill.sh` pipes one statement per line into `sqlite3 -bail`

**Decision.** Each worker in `fleet/drill.sh` pipes its statements, one per line, into `sqlite3 -bail`. The script runs in a temporary directory that it removes on exit.

**Context.** With all statements in one command-line argument, a failed `BEGIN IMMEDIATE` did not stop the rest. The `INSERT` could land outside a transaction and `COMMIT` then failed with `no transaction is active`, so the rows figure was too high and the reported error hid the lock.

**Alternatives.** Add `-bail` and keep the single argument: it still ran the later statements on the CLI builds tested (3.54.0 and 3.53.4). Or rewrite the drill in Python around `db.write()`, which would exercise the harness but needs the timeout in `db.py` to be configurable.

**Evidence.** At `busy_timeout=1` the old script printed `rows=100/100` with up to 23 errors. With the change, every failure was `database is locked` and rows + errors was 100 in each run. https://sqlite.org/cli.html documents `.bail` but not this case.

**Affects.** `fleet/drill.sh`. It uses the `sqlite3` CLI, not the SQLite bundled with Python, and does not exercise `db.write()`.

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
