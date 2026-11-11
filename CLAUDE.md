# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small Python harness for a fleet of Claude Code agents, built on one SQLite file, `agent.db`.

## Commands

Python 3.14 is required (`uuid.uuid7()`, and the unparenthesized `except A, B:` in `fleet/doctor.py`). Always run through `uv`, from the repo root.

```bash
uv run fleet/doctor.py                          # audit this machine, writes ./harness-audit.json
uv run scripts/seed-ledger.py                   # record ./harness-audit.json as layer.checked events
uv run python -m fleet.project                  # rebuild knowledge; exits 1 on DRIFT (first run always DRIFT)
uv run python -u -m fleet.run                   # the six-step kill-and-resume drill
uv run python -u -m fleet.run --plan p.json     # a plan: [[seq, intent, command, [resource, ...]], ...]; resources optional
uv run python -u -m fleet.run --plan p.json --allow-claude <usd>   # a plan with {"prompt": ...} steps: billed, each capped at <usd>
uv run python -u -m fleet.run --resume <run_id> [--plan p.json] [--allow-claude <usd>] [--force]
uv run python -m fleet.recovery [--idle-seconds 60] [--max-attempts 3]   # list dead runs, halt over-retried ones
uv run python -m fleet.sync sync|export|import
uv run python -u -m fleet.worker <name> [--budget-s 30]   # claim, run and report tasks until the budget ends
uv run python -m fleet.dlq [redrive <task_id>]            # list dead-lettered tasks, or put one back on the queue
uv run python -m fleet.conflicts [resolve <task_id> "<decision>"]   # list conflicts waiting for a person, or settle one
uv run python -u -m fleet.kill_drill                      # SIGKILL a worker mid-task and check recovery (about 50s)
uv run python -m fleet.view [trace <run_id> | stages [days] | context [session]]   # live sessions and runs, one run's trace, failures per stage, or context size per request
uv run python -u -m fleet.telemetry [--port 4318]                # receive Claude Code telemetry; settings in .env.example
uv run python -m fleet.governor [set <usd>]               # show the fleet's spend ceiling and headroom, or set the ceiling
uv run python -m fleet.merge <branch> --run-id R --fence file:path=N [--repo .] [--target main]   # land a branch if every changed file has a live claim
uv run python -u -m fleet.merge_drill                     # drive the merge gate through refusals, the lock and a crash (a few seconds)
uv run python -u -m fleet.claims_drill                    # fleet.run's declared claims: refusal, resume, renewal, paused-agent takeover (about 50s)
```

`fleet` has no `__init__.py` (a namespace package), so its modules must run with `-m`: `python fleet/run.py` fails with `ModuleNotFoundError`. `doctor.py` imports nothing from `fleet` and runs as a script; `seed-ledger.py` adds the repo root to `sys.path` itself.

There is no test suite and no linter configured. Verify changes by running the commands against a throwaway database:

```bash
ITERUM_DB=/tmp/scratch.db ITERUM_DEVICE=test uv run python -u -m fleet.run
```

## Settings

- `ITERUM_DEVICE`: required for anything that writes an event; `db.log()` raises without it.
- `ITERUM_CLAIM_TTL`: seconds a `fleet.run` claim lasts between renewals, default 300.
- `ITERUM_DB`: database path, default `agent.db` relative to the current directory.
- `ITERUM_IDLE_SECONDS`: heartbeat age after which a `running` run counts as dead, default 60; the default for `fleet.recovery --idle-seconds` and for `--resume`.
- `ITERUM_MAX_ATTEMPTS`: the default for `fleet.recovery --max-attempts`, default 3.
- `ITERUM_SYNC_DIR`: sync folder, default `~/private-data/iterum`; must sit inside a git repo with a remote for `sync`.

## Architecture

`agent.db` keeps three contracts apart, and code must not blur them:

| Contract | Tables | Rule |
| --- | --- | --- |
| Control state | `runs`, `steps`, `receipts` (and the queue/claims/budget tables) | Mutable, local to one machine |
| Event ledger | `events` | Append-only; triggers abort any UPDATE or DELETE |
| Derived knowledge | `knowledge` | Rebuilt from events by `fleet/project.py`; never written directly |

`fleet/db.py` is the only database access layer:

- Every write goes through `db.write()`, which opens `BEGIN IMMEDIATE` (connections use `isolation_level=None`, so this explicit transaction is the only one).
- A state change and its `db.log()` event go in the same `db.write()` block, so they commit together.
- `db.log()` reserves `run_id`, `kind`, `stage` and `seq`; passing one as payload raises `TypeError` at call time. Rename the payload key instead.
- `db.init()` runs `schema.sql` and is safe to repeat; entry points that may meet a fresh database call it first.

`fleet/run.py` is write-ahead: each step is written `proposed` before its shell command runs and `committed` after; a failing command marks the step and run `failed`. Resume skips the set of committed seqs (not `MAX(seq)+1`). The ledger stores intents and, in `step.proposed`, a `command_hash` (of the shell string or the whole prompt object), so `check_resumable()` compares the recorded intents to the plan by seq and refuses on mismatch, refuses a changed command unless that step is `failed` (a failed step's command may be fixed; runs logged before the hash existed are not checked), an unknown run, a run already `done`, or, without `--force`, a `halted` run or a `running` run whose heartbeat is younger than `recovery.IDLE_SECONDS` (`ITERUM_IDLE_SECONDS`, default 60), or a run with an uncommitted step whose command's process group (`steps.pgid`; each step runs in its own, killed by `_spawn()` on Ctrl-C or SIGTERM) is still alive. `fleet/run.py` refreshes `runs.heartbeat_at` from a thread every `HEARTBEAT` seconds; `fleet/recovery.py` reports `failed` runs and `running` runs whose heartbeat is older than `--idle-seconds` (default 60), and halts any whose most-proposed step has reached `--max-attempts`. Every `fleet.run` start prints those stale `running` runs and a count of `failed` ones (`notice_dead_runs()`, read-only); nothing calls `fleet.recovery` itself. A plan step's optional fourth field lists resources (`"file:a.txt"`); a plan that declares any must run on a branch other than `--target` (default `main`); `claim_files()` claims them all, in sorted order, before any step runs and again on resume, the heartbeat thread renews them at half `ITERUM_CLAIM_TTL`, and a refused renewal kills the step and fails the run; the run prints the `fleet.merge` command with its fences when done. Before proposing each step it checks `governor.headroom()`: a shell step needs more than zero and a prompt step its whole cap, or the run is marked `budget_exhausted` and exits; a resume checks again.

A plan step's command is a shell string or `{"prompt": "...", "model": "..."}` (`model` optional, passed as `--model`; without it the user's default model). A prompt step runs `claude_step()`: `claude -p` in its own process group, billed to the user, so `check_prompt_steps()` refuses a plan with any prompt step unless `--allow-claude <usd>` is given, and refuses a prompt step that declares no files. The session gets `--max-turns 10`, `--max-budget-usd <usd>`, only the `Read,Edit,Write` tools with `acceptEdits` and `--permission-prompts none`, `iterum.run_id` in `OTEL_RESOURCE_ATTRIBUTES`, and `fleet/gate.py` as a `PreToolUse` hook through `--settings` (`gate_settings()`, with `ITERUM_DB` and `FLEET_RUN_ID` in the hook's own command). It logs `claude.finished` (stage `tool_execution`: `exit_code` and the result envelope's `session_id`, `total_cost_usd`, `num_turns`, `is_error`, `permission_denials`, null when stdout is not JSON), then fails on a non-zero exit or `"is_error": true`, never on `subtype`. Resume refuses a prompt step that did not commit (`proposed` or `failed`) without `--force`, since it may have edited files and a rerun is billed again. One paid run (2026-11-11, `docs/claude-step-design.md` section 6) showed the hook runs in `-p` mode and refuses a claimed file.

`fleet/sync.py` shares only `events` across devices: each device appends its own events to `events-<ITERUM_DEVICE>.jsonl` (export never removes lines) and imports every file with `ON CONFLICT(uid) DO NOTHING`. `uid` (UUIDv7) is the global identity; `event_id` is local and differs per device. `runs`, `steps` and the coordination tables are never synced.

`fleet/queue.py` is the work queue over `tasks` and `leases`. `claim()` issues a fence per task, and a worker must present it, with a live lease, to `heartbeat()`, `finish()`, `fail()` or `release_back()`; a stale worker gets `Fenced` or `Refused` and changes nothing. A dead-lettered task halts everything waiting on it, and `redrive()` restores those tasks. `fleet/worker.py` runs the loop and does the reaping itself, so there is no separate reaper process. The default `do_work` runs each command in its own process group, stored in `leases.pgid`; `reap()` leaves an expired lease alone while that group is alive (`fleet/proc.py`), and `_shell()` kills the group if it exits early. `fleet.run` and `fleet.worker` turn SIGTERM into `KeyboardInterrupt` (`proc.stop_on_sigterm()`), so a polite stop kills the command as Ctrl-C does; both then exit with -2, not -15. Ledger events use `task-<device>-<task_id>` as `run_id`, because `task_id` is local and events sync. `finish()` stores what `do_work` returns in `tasks.result`, read back with `queue.results()`. `claim()` skips tasks of kind `queue.HUMAN_KIND`; only `queue.resolve()` closes those.

`fleet/merge.py` is the merge gate. `land()` builds the merge with `git merge-tree --write-tree`, then in one `db.write()` block calls `claim.require_claim()` for every changed file and moves the target with `git update-ref` and the expected old value; landing releases every claim it was given, in that block. A merge that would not change the target's files raises `Empty`. It logs `merge.started` first; `reconcile()`, run by `main()` under an exclusive lock before `land()`, settles a merge a crash left without an outcome. The target branch must not be checked out in any working tree: `update-ref` leaves that tree's index behind.

`fleet/gate.py` is a `PreToolUse` hook that refuses (exit 2) an edit to a file another run has claimed, and exits 2 on any failure of its own, since any other exit code lets the edit through. It needs an absolute `ITERUM_DB` and a `FLEET_RUN_ID`, and runs as a script. Nothing in this repo registers it, deliberately: a checked-in `.claude/settings.json` would run it against anyone who clones the repo.

`fleet/telemetry.py` receives Claude Code's OTLP logs as `http/json` on `/v1/logs` and logs each `claude_code.api_request` as a `spend.reported` event, stage `governance`, under `iterum.run_id` (or `session-<session.id>`). It stores no identity fields and skips a `request_id` already logged. Metrics are not imported; `runs.cost_usd` is not written. `GET /v1/logs` answers `{"db": <resolved path>}`, the database it writes to.

`fleet/governor.py` is the fleet-wide spend ceiling. Spend is the sum of `cost_usd` over `spend.reported` events since the ceiling was first set (`budgets.window_start`); it keeps no counter, and `budgets.spent_usd` is unused. It counts only what `fleet.telemetry` received, and a run can pass the ceiling by up to one step's spend. So a plan with prompt steps under a ceiling refuses to start or resume (`check_receiver()` in `fleet/run.py`) unless `CLAUDE_CODE_ENABLE_TELEMETRY=1` and `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` are set (`source .env.example`) and the receiver answers with the run's own database; a receiver that dies mid-run is still missed.

The schema defines more tables (`evals`, `approvals`) than the code uses yet.
