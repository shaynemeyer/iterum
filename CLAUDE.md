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
uv run python -u -m fleet.run --plan p.json     # a plan: [[seq, intent, shell_command], ...]
uv run python -u -m fleet.run --resume <run_id> [--plan p.json] [--force]
uv run python -m fleet.recovery [--idle-seconds 60] [--max-attempts 3]   # list dead runs, halt over-retried ones
uv run python -m fleet.sync sync|export|import
uv run python -u -m fleet.worker <name> [--budget-s 30]   # claim, run and report tasks until the budget ends
uv run python -m fleet.dlq [redrive <task_id>]            # list dead-lettered tasks, or put one back on the queue
uv run python -m fleet.conflicts [resolve <task_id> "<decision>"]   # list conflicts waiting for a person, or settle one
uv run python -u -m fleet.kill_drill                      # SIGKILL a worker mid-task and check recovery (about 40s)
uv run python -m fleet.view [trace <run_id> | stages [days]]   # live sessions and runs, one run's trace, or failures per stage
```

`fleet` has no `__init__.py` (a namespace package), so its modules must run with `-m`: `python fleet/run.py` fails with `ModuleNotFoundError`. `doctor.py` imports nothing from `fleet` and runs as a script; `seed-ledger.py` adds the repo root to `sys.path` itself.

There is no test suite and no linter configured. Verify changes by running the commands against a throwaway database:

```bash
ITERUM_DB=/tmp/scratch.db ITERUM_DEVICE=test uv run python -u -m fleet.run
```

## Settings

- `ITERUM_DEVICE`: required for anything that writes an event; `db.log()` raises without it.
- `ITERUM_DB`: database path, default `agent.db` relative to the current directory.
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

`fleet/run.py` is write-ahead: each step is written `proposed` before its shell command runs and `committed` after; a failing command marks the step and run `failed`. Resume skips the set of committed seqs (not `MAX(seq)+1`). The ledger stores intents but not commands, so `check_resumable()` compares the recorded intents to the plan by seq and refuses on mismatch, an unknown run, a run already `done`, or a `halted` run without `--force`. `fleet/run.py` refreshes `runs.heartbeat_at` from a thread every `HEARTBEAT` seconds; `fleet/recovery.py` reports `failed` runs and `running` runs whose heartbeat is older than `--idle-seconds` (default 60), and halts any whose most-proposed step has reached `--max-attempts`. `claude_step()` is a billed swap-in for `shell()` and is not wired in.

`fleet/sync.py` shares only `events` across devices: each device appends its own events to `events-<ITERUM_DEVICE>.jsonl` (export never removes lines) and imports every file with `ON CONFLICT(uid) DO NOTHING`. `uid` (UUIDv7) is the global identity; `event_id` is local and differs per device. `runs`, `steps` and the coordination tables are never synced.

`fleet/queue.py` is the work queue over `tasks` and `leases`. `claim()` issues a fence per task, and a worker must present it, with a live lease, to `heartbeat()`, `finish()`, `fail()` or `release_back()`; a stale worker gets `Fenced` or `Refused` and changes nothing. A dead-lettered task halts everything waiting on it, and `redrive()` restores those tasks. `fleet/worker.py` runs the loop and does the reaping itself, so there is no separate reaper process. Ledger events use `task-<device>-<task_id>` as `run_id`, because `task_id` is local and events sync. `finish()` stores what `do_work` returns in `tasks.result`, read back with `queue.results()`. `claim()` skips tasks of kind `queue.HUMAN_KIND`; only `queue.resolve()` closes those.

The schema defines more tables (`budgets`, `evals`, `approvals`) than the code uses yet.
