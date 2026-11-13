# Open questions

Decisions not made yet. When one is answered, record it in `decision-log.md`, add any resulting work to `todo.md`, and remove it here.

## How should Iterum work on a feature unattended, overnight?

**Context.** The goal: say "implement this feature in this project", approve a plan and a budget, and let Iterum work all night. What holds up unattended today, what is missing (a fix loop, sentence-to-plan, something that keeps runs moving, a morning report), a proposed order, and the open decisions are in `overnight-design.md` (2026-11-12).

**Blocks.** Nothing yet.

**Settled by.** Deciding where to start; the note proposes the fix loop first, tested free with a fake `claude`.

## Should Iterum ship as one `iterum` command instead of `python -m fleet.*`?

**Context.** Every command is `uv run python -u -m fleet.<module> ...`, and from the app repo a run also needs `export ITERUM_DB=<absolute path>`, `export PYTHONPATH=<iterum>`, `source <iterum>/.env.example` and `uv run --project <iterum>` (`nextjs-first-run.md`). Each piece exists for a reason (`fleet` is a namespace package, so `-m`; `-u` so output is not lost; `ITERUM_DB` defaults to `agent.db` in the current folder, so a relative path in the app repo makes a second database), but none of it is the work. Reading state is also spread over seven commands (`fleet.view`, `fleet.recovery`, `fleet.governor`, `fleet.dlq`, `fleet.conflicts`, `fleet.approve`, `fleet.canary`), and nothing lists stranded tasks. A TUI was considered (2026-11-13) and set aside for now: it would keep every one of those invocations and add a dependency (`pyproject.toml` has `dependencies = []`).

**Options.** (a) A packaged CLI: `[project.scripts]` defines `iterum` ([uv: entry points](https://docs.astral.sh/uv/concepts/projects/config/#entry-points)), installed once with `uv tool install --editable <iterum>` ([uv: tools](https://docs.astral.sh/uv/concepts/tools/)); subcommands (`iterum status`, `run`, `resume`, `land`, `receiver`, `freeze`, `approve`, `queue`, `dlq`, `doctor`, `eval`, `sweep`, ...) call each module's existing `main()`; the database defaults to one fixed place instead of the current folder. (b) The same plus an `iterum status` dashboard, plain or with Rich (Iterum's first dependency). (c) A Textual TUI later, on top of (a). (d) Keep `python -m` and document it better.

**To verify first.** How the build backend packages a namespace package with no `__init__.py`; that `gate_settings()` still finds `fleet/gate.py` from an installed tool; that the entry point keeps output unbuffered as `-u` does; where the fixed database lives and how `ITERUM_DB` still overrides it.

**Plan.** `cli-plan.md` (2026-11-13): packaging and a thin dispatcher with no behaviour change, then `iterum status`, shortcuts, a fixed default database, and docs, each checked before the next.

**Blocks.** Nothing. Every command works today.

**Settled by.** Choosing (a) to (d), where the default database lives, and whether a first dependency (Rich) is acceptable for the dashboard.

## Should `claude.finished` keep the whole result envelope?

**Context.** `claude_step()` logs only `exit_code`, `session_id`, `total_cost_usd`, `num_turns`, `is_error` and `permission_denials`. The first paid run (2026-11-11) therefore kept no full copy of a success envelope for `claude-step-design.md`. Its `num_turns` was 5 against 3 API requests in telemetry, for reasons not known. The second Next.js run (`095cf7955377`) reported `num_turns: 11` under `--max-turns 10`, without failing, while its transcript shows about 7 rounds of tool calls; 7 `spend.reported` events arrived.

**Options.** Log the whole parsed envelope; log a few more named fields; or leave it.

**Blocks.** Nothing.

**Settled by.** Whether anything needs the other fields. The `result` text can be long, so logging it whole has a cost.

## How does a human settle a stuck `in_flight` receipt?

**Context.** An ambiguous failure leaves the receipt `in_flight`, and every later attempt raises `Uncertain` (see the decision log). Today the only way out is editing `agent.db` by hand.

**Options.** A command in `fleet.recovery` that lists `in_flight` receipts and marks one `failed` ("checked, it did not happen") or `ok` ("checked, it did"), writing the change and a `db.log()` event in one `db.write()`. Or a separate module.

**Blocks.** Wiring `commit_once()` into `fleet/run.py`, which waits (decision log, 2026-11-11: option B in `commit-once-design.md`, opt-in per step, comes first).

**Revisit when.** Before `commit_once()` or `run_step()` is wired into `fleet/run.py` or `claude_step()`. Until then nothing writes receipts.

**Settled by.** Choosing where the command lives, what it records in the ledger, and whether it needs `--force` like a halted run.

## Should settling an irreversible action go through `approvals`?

**Context.** For an irreversible action that can neither take a key nor be checked, an `in_flight` receipt older than its timeout should be treated as an incident for a human, not retried. The schema has an `approvals` table (`run_id`, `seq`, `action`, `fingerprint`, `decision`, `decided_by`) for recording such decisions. Since 2026-11-13, `fleet/approve.py` writes it: `require()` records a pending request for an action in `IRREVERSIBLE` and `fleet.approve approve|deny` settles it. But nothing calls `require()`: `fleet.run` plan steps carry no action name to pass it, so the gate exists and stops nothing.

**Options.** Have the settle command (see the question above) write an `approvals` row as well as its `action.settled` event; require an `approved` row before an irreversible action runs at all; or leave `approvals` unused until a concrete action needs it.

**Blocks.** Nothing yet. Matters once an irreversible action runs through `commit_once()`.

**Settled by.** Deciding which actions count as irreversible, and whether the human decision belongs on the settle path, before the action, or both.

## How should a `fleet.run` step call `approve.require()`?

**Context.** `fleet/approve.py` (2026-11-13, `0627be3`) records and settles approvals, but nothing calls `require()`. A plan step is `[seq, intent, command, resources]`, and its command is an opaque shell string or prompt, so `fleet.run` cannot tell that a step is, say, a `git.push`; guessing from the shell text would be the verb-level matching that `IRREVERSIBLE`'s exact names avoid. A run also has no way to wait: `runs.status` allows `running`, `done`, `failed`, `halted` and `budget_exhausted`, and SQLite cannot change that CHECK in place. Iterum performs no irreversible action itself; the app's plans would.

**Options.** (a) An optional `action` field on a step (`{"action": "git.push", "params": {...}}`). Before proposing it, `fleet.run` calls `require(run_id, seq, action, params)` (a resume keeps the `run_id`, so it is a stable scope). On `NeedsApproval` it marks the run `halted` and prints the fingerprint and the approve command, and the human approves, then resumes with `--force`. No schema change, and `fleet.replay` already refuses halted runs. (b) The same, with a new `awaiting_approval` run status, which needs a `runs` table rebuild. (c) Wait until a real plan has an irreversible step, and design from that.

**Blocks.** Nothing yet. Matters once an app plan includes an irreversible step.

**Settled by.** A plan that needs it, and choosing whether a waiting run reuses `halted` or gets its own status. Test plan for (a): a scratch-database drill that pauses, restarts, approves and resumes, and checks that a changed param asks again.

## Should `fleet.run` refuse a prompt plan with no output check?

**Context.** A wrong answer that passes every check ends `done`, and no layer closes that; an output check written per plan and proven to fail on `main` is what shrinks it (`overnight-design.md`). It has worked once: the free dry run's unawaited `params` got past the build and was caught only by the output check (`nextjs-first-run.md`). But nothing enforces one. `check_prompt_steps()` refuses a prompt step without `--allow-claude` or without files, and runs a plan whose only check is the build, or none. And `fleet.run` cannot tell which step is the check: a step's command is an opaque shell string, the same problem as `approve.require()` (question above).

**Options.** (a) Mark a check step in the plan (a field or a step kind), and refuse a plan with a prompt step and no marked check after it. (b) Require a `--check CMD` on `fleet.run` for prompt plans, run after the last prompt step. (c) Leave it to `/fleet-plan`, which already requires a check that fails on `main` (`overnight-design.md`), and enforce nothing in `fleet.run`.

**Blocks.** Nothing yet. Matters for unattended runs, where nobody reads the diff before morning.

**Settled by.** Whether hand-written plans should be held to the same rule as `/fleet-plan`'s, and whether a marked check step is worth another plan field.

## Should some actions get exactly-once, not just at-most-once?

**Context.** `commit_once()` guarantees at most once. A failure after the side effect leaves the receipt `in_flight`, and the step stays blocked until a human checks. Getting exactly once across that failure needs the target system to take part, and `commit_once()` cannot involve it: it calls `action()` with no arguments, so the key never leaves `agent.db`.

**Options.** Pass the key to the action, so a target that deduplicates by key can drop a repeat. Or give an action a check that asks the target whether the effect already happened, and settle the receipt from the answer. Or stay at most once and rely on a human to settle.

**Blocks.** Nothing yet. Matters once real actions run through `commit_once()`.

**Settled by.** Knowing which actions the fleet will run and whether their targets accept a key or can be queried.

## Which actions can prove nothing ran?

**Context.** An action that knows it failed before taking effect can raise an error whose `category` is in `REFUSED`, freeing its key. Anything else stays locked.

**Options.** `shell()`: a command that is not found, or a plan step rejected before it starts. `claude_step()`: a failure on the first API request, before any tool ran.

**Blocks.** Wrapping `shell()` in `commit_once()` without locking every failed command.

**Settled by.** Listing each action's failure modes and which of them are certain.

## Should any Claude Code account or setup errors be `REFUSED`?

**Context.** `authentication_failed`, `billing_error` and the others are `LOGICAL` but not `REFUSED`, so their receipt stays `in_flight`. For a single API call that is too cautious; for a whole `claude -p` session it may be right, since the error can arrive after tools have run.

**Options.** Leave as is; add some to `REFUSED`; or let `claude_step()` decide per failure, based on whether any tool ran.

**Blocks.** Nothing yet. `claude_step()` is wired in (2026-11-11) but does not go through `commit_once()`, so a prompt step writes no receipt. The first paid run succeeded, so it gave no failure to inspect.

**Settled by.** Wiring `claude_step()` in and inspecting real failed runs: where the final error appears (the `result` message or the last `api_retry` event) and whether tools ran before it.
