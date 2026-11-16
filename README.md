<p align="center">
  <img src="assets/mascot-440.png" alt="Septa, the Iterum mascot: a nautilus holding a scroll" width="220">
</p>

# Iterum

A small Python harness for running a fleet of [Claude Code](https://code.claude.com/docs) agents, built on one SQLite system of record: `agent.db`.

The goal is a durable memory of what your agents did, instead of losing it when a session ends: events go into an append-only ledger that you can audit, rebuild state from and sync across machines. Today the ledger records the harness audit, the steps of resumable runs, queue tasks, file claims, merges and Claude Code spend.

*Iterum* is Latin for "again". Because the ledger is the source of truth, state can always be rebuilt from it.

> Early work in progress. The schema defines more than the code uses yet.

## How it works

`agent.db` keeps three contracts separate:

| Contract | Tables | Rule |
| --- | --- | --- |
| Control state | `runs`, `steps`, `receipts`, `tasks`, `leases`, `claims`, `fences` | Mutable: what is true right now, on this machine |
| Event ledger | `events` | Append-only: what happened, in order |
| Derived knowledge | `knowledge` | Rebuildable from the ledger at any time |

Every event carries a UUIDv7 `uid` and the `device` that wrote it, so ledgers from several machines merge without conflicts.

## Components

| Path | What it does |
| --- | --- |
| `fleet/cli.py` | The `iterum` command: one word per module below |
| `fleet/status.py` | One screen of fleet state; exits 1 when something needs a person |
| `fleet/report.py`, `fleet/report_html.py` | A day's work as one self-contained HTML page, or as JSON |
| `fleet/report_days.py`, `fleet/report_run.py` and their `_html` modules | `iterum report --days N` and `--run RUN_ID`: several days, or one run, as a page or JSON |
| `fleet/report_index.py`, `fleet/report_serve.py` | The `index.html` of every report page; `iterum report --serve`, live pages on 127.0.0.1 |
| `fleet/doctor.py` | Audits seven harness layers on this machine and writes `harness-audit.json` |
| `fleet/db.py` | `agent.db` access; every write runs in `BEGIN IMMEDIATE` |
| `fleet/schema.sql` | Tables for runs, events, knowledge, claims, the task queue, budgets, evals and approvals |
| `fleet/project.py` | Rebuilds `knowledge` from `events`; exits 1 on DRIFT |
| `fleet/run.py` | Runs a multi-step plan that can be killed and resumed; each step is recorded before it runs |
| `fleet/recovery.py` | Lists runs that died and halts ones retried too often |
| `fleet/step.py`, `fleet/idem.py` | Retries a step only when its failure class allows; at-most-once side effects with receipts. Not yet called by `fleet.run` (`docs/commit-once-design.md`) |
| `fleet/queue.py`, `fleet/worker.py` | A work queue with dependencies, leases, fences and a dead-letter queue, and the worker loop that drains it |
| `fleet/add.py` | `iterum add`: queues a shell command, or with `--plan` builds the `iterum run` and keeps its cap and retries, optionally on a new branch of a repo |
| `fleet/dlq.py`, `fleet/conflicts.py` | Lists dead-lettered tasks and puts one back on the queue; lists conflicts waiting for a person and settles one |
| `fleet/claim.py` | Claims on files: leases that expire, with fences that make expiry safe |
| `fleet/merge.py` | Lands a branch only while every changed file has a live claim and, with `--check`, a command passes on the merged tree |
| `fleet/gate.py` | A `PreToolUse` hook that refuses an edit to a file another run has claimed; not registered here, wire it up yourself |
| `fleet/telemetry.py` | Receives Claude Code telemetry and records each API request's cost; settings in [`.env.example`](.env.example) |
| `fleet/governor.py` | `iterum budget`: a fleet-wide spend ceiling, summed from the ledger's `spend.reported` events, and a night's limit (`iterum worker --max-usd`) on one worker's runs; runs and workers stop at either. `iterum budget suggest` (`fleet/suggest.py`) estimates the queued tasks' cost |
| `fleet/approve.py` | An approval gate for irreversible actions (`iterum approve`, `deny`; nothing calls it yet), and `iterum freeze`/`thaw` to stop new queue work |
| `fleet/view.py` | Read-only views: live sessions and runs, one run's trace, failures per stage, context size per request |
| `fleet/proc.py` | Process-group checks, and SIGTERM handled as Ctrl-C, shared by runs, the queue and the merge gate |
| `fleet/notify.py` | Runs `ITERUM_NOTIFY` once when a worker stops, with today's summary on stdin |
| `fleet/canary.py` | `iterum canary`: flags recent runs whose median events, seconds or cost moved from the runs before them; detects change, not wrong output |
| `fleet/replay.py`, `fleet/eval.py`, `fleet/scorecard.py` | Replays a run or queue task from the ledger on a scratch database; `iterum eval` turns past runs into a regression suite; `iterum scorecard` compares two git revisions on it |
| `fleet/sweep.py` | `iterum sweep`: runs each plan several times in rotated order and compares pass rate beside cost |
| `fleet/sync.py` | `sync` shares events across devices through a private git repo; `export` and `import` run single steps |
| `fleet/*_drill.py`, `fleet/drill.sh` | Drills that kill or crash the harness and check it recovers; `drill.sh` contends SQLite writers ([docs/drill.md](docs/drill.md)) |
| `install.sh` | Installs the `iterum` command and the plugin, and records this machine's audit in the ledger |
| `scripts/seed-ledger.py` | Records the harness audit in the ledger |
| `plugins/iterum/`, `.claude-plugin/marketplace.json` | A Claude Code plugin whose `/iterum:fleet-plan` skill turns a one-sentence feature into a plan, proven free before anything is billed |

[CLAUDE.md](CLAUDE.md) lists every command.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). The doctor also checks for the `claude` CLI. Built and tested on macOS. It does not run on Windows, since it relies on Unix process groups and file locks; Linux, or WSL on Windows, may work but is untested.

For a step-by-step walkthrough, from install to a first landed run, with the `/iterum:fleet-plan` skill for creating plans, see [docs/setup-guide.md](docs/setup-guide.md).

```bash
git clone https://github.com/shaynemeyer/iterum.git && cd iterum
./install.sh
```

`install.sh` asks for a name for this machine (every event records it; set `ITERUM_DEVICE` to skip the question), installs the `iterum` command, audits the machine and records the audit in the ledger, builds knowledge, and installs the Claude Code plugin that adds `/iterum:fleet-plan` (skipped if `claude` is not installed). It stops at the first failed step. At the end it prints the `export` lines to add to your shell profile (for example `~/.zshrc`): `ITERUM_DEVICE`, and `ITERUM_HOME` if you cloned somewhere other than `~/github/iterum`.

If your shell cannot find `iterum`, run `uv tool update-shell` and open a new terminal. The install is editable, so a `git pull` updates the command.

## Everyday commands

```bash
iterum status                     # one screen; exits 1 when something needs a person
iterum report --open              # today's work as an HTML page
iterum run plan.json              # run a plan, from the repo it works on
iterum land <branch> --run-id R   # land the run's branch while its claims are live
```

`iterum --help` lists the rest, and `uv run python -m fleet.<module>` still works for each.

## Sync across devices

Put `ITERUM_SYNC_DIR` inside a private git repo with a remote, then run:

```bash
iterum sync
```

It exports this device's events, commits only that file, pulls, pushes, imports every device's events and rebuilds knowledge. A new device runs the same command to restore everything. See [docs/sync.md](docs/sync.md) for setup, rules and troubleshooting.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `ITERUM_DEVICE` | required | Names this device in every event |
| `ITERUM_DB` | `~/.local/share/iterum/agent.db` | Path to the database (`$XDG_DATA_HOME/iterum/agent.db` when that is set) |
| `ITERUM_SYNC_DIR` | `~/private-data/iterum` | Private folder for exported events |
| `ITERUM_CLAIM_TTL` | `300` | Seconds a `fleet.run` file claim lasts between renewals |
| `ITERUM_IDLE_SECONDS` | `60` | Heartbeat age after which a `running` run counts as dead |
| `ITERUM_MAX_ATTEMPTS` | `3` | Attempts at one step before `fleet.recovery` halts the run |
| `ITERUM_NOTIFY` | unset | A shell command each worker runs when it stops, with a summary on stdin, e.g. a macOS notification ([setup guide](docs/setup-guide.md#notifications)) |
| `FLEET_TASK_TIMEOUT_S` | `600` | Seconds one queue task's command may run (or until its deadline, if sooner); then it is killed and the task fails |
| `FLEET_WORKER_BUDGET_S` | `12` | `iterum worker`'s default `--budget-s`, used when neither `--budget-s` nor `--until-empty` is given |
| `FLEET_WORK_MODULE` | unset | A module exporting `do_work(task)` that `iterum worker` uses instead of running the task's shell command |

`agent.db` lives outside the repo by default; `harness-audit.json` is written to the current folder and git-ignored. Keep the sync folder in a private repo.

## License

The code is released under the [MIT License](LICENSE).

The Iterum logo, the Septa mascot and the favicons in [`assets/`](assets/) are **not** covered by the MIT License; see [assets/LICENSE.md](assets/LICENSE.md).
