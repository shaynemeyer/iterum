<p align="center">
  <img src="assets/mascot-440.png" alt="Septa, the Iterum mascot: a nautilus holding a scroll" width="220">
</p>

# Iterum

A small Python harness for running a fleet of coding agents, built on one SQLite system of record: `agent.db`.

*Iterum* is Latin for "again". Every action is appended to an event ledger, so state can always be rebuilt and shared across machines.

> Early work in progress. The schema defines more than the code uses yet.

## How it works

`agent.db` keeps three contracts separate:

| Contract | Tables | Rule |
| --- | --- | --- |
| Control state | `runs`, `steps` | Mutable: what is true right now |
| Event ledger | `events` | Append-only: what happened, in order |
| Derived knowledge | `knowledge` | Rebuildable from the ledger at any time |

Every event carries a UUIDv7 `uid` and the `device` that wrote it, so ledgers from several machines merge without conflicts.

## Components

| Path | What it does |
| --- | --- |
| `fleet/doctor.py` | Audits seven harness layers on this machine and writes `harness-audit.json` |
| `fleet/db.py` | `agent.db` access; every write runs in `BEGIN IMMEDIATE` |
| `fleet/schema.sql` | Tables for runs, events, knowledge, claims, the task queue, budgets, evals and approvals |
| `fleet/project.py` | Rebuilds `knowledge` from `events`; exits 1 on DRIFT |
| `fleet/sync.py` | `sync` shares events across devices through a private git repo; `export` and `import` run single steps |
| `scripts/seed-ledger.py` | Records the harness audit in the ledger |

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). The doctor also checks for the `claude` CLI.

Run from the repo root, in order:

```bash
export ITERUM_DEVICE=laptop       # name this device; every event records it
uv run fleet/doctor.py            # audit this machine, writes harness-audit.json
uv run scripts/seed-ledger.py     # record the audit in agent.db
uv run python -m fleet.project    # rebuild knowledge from the ledger
```

The first `fleet.project` run reports DRIFT and exits 1 while the knowledge table is still empty. Run it again to confirm MATCH.

## Sync across devices

Put `ITERUM_SYNC_DIR` inside a private git repo with a remote, then run:

```bash
uv run python -m fleet.sync sync
```

It exports this device's events, commits only that file, pulls, pushes, imports every device's events and rebuilds knowledge. A new device runs the same command to restore everything. See [docs/sync.md](docs/sync.md) for setup, rules and troubleshooting.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `ITERUM_DEVICE` | required | Names this device in every event |
| `ITERUM_DB` | `agent.db` | Path to the database |
| `ITERUM_SYNC_DIR` | `~/private-data/iterum` | Private folder for exported events |

`agent.db` and `harness-audit.json` hold local data and are git-ignored. Keep the sync folder in a private repo.
