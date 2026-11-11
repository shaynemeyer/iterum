# Open questions

Decisions not made yet. When one is answered, record it in `decision-log.md`, add any resulting work to `todo.md`, and remove it here.

## Should prompt steps run with `--restricted`?

**Context.** `claude --help` (2.1.322) lists `--restricted`: it removes code-running tools and WebFetch unless `--tools` names them, "ignores user, project and local settings files (managed settings and --settings still apply...)", "confines the file tools to the working directories", and refuses `bypassPermissions`. Prompt steps today run default `-p` with `--tools Read,Edit,Write` (decision log, 2026-11-11), which loads the user's settings and does not confine edits to the worktree; `fleet.merge` still refuses unclaimed files.

**Options.** Add `--restricted` to `CLAUDE_TOOLS` in `fleet/run.py`. Or keep default `-p`, as decided 2026-11-10, so the session loads the user's settings like an interactive one.

**Blocks.** Nothing.

**Settled by.** The paid run: whether a default `-p` session edits outside the worktree, and whether the gate hook still runs under `--restricted` through `--settings`.

## What should the spend ceiling do when the telemetry receiver is down?

**Context.** `fleet/governor.py` counts only `spend.reported` events, which exist only while `fleet.telemetry` is running. If it is down, a paid run spends without the ceiling seeing it.

**Options.** With `--allow-claude` and a ceiling set, `fleet.run` refuses to start unless the receiver answers. Or it warns and runs. A receiver that dies mid-run is missed either way, unless the heartbeat thread checks it too.

**Blocks.** Paid runs. `claude_step()` is wired in (2026-11-11), so a prompt step run while the receiver is down spends without the ceiling seeing it; shell steps spend nothing.

**Settled by.** Choosing refuse or warn, and how `fleet.run` checks the receiver.

## Can concurrent runs share one spend ceiling?

**Context.** Two runs that check `governor.headroom()` at the same moment can both start a step and together pass the ceiling by two steps' spend. `budgets` is local to one machine, so each device has its own ceiling, while the spend it counts includes synced events from every device.

**Options.** Accept and document it. Reserve each step's cap in a table under `BEGIN IMMEDIATE`, which still covers one machine only. Rely on a limit enforced by the biller, such as an API spend limit in the Anthropic Console (not checked yet: what it offers, and whether it applies to Claude Code sessions).

**Blocks.** Nothing until more than one paid run goes at once.

**Settled by.** Running concurrent paid runs, or checking what the Console's limits cover.

## How does a human settle a stuck `in_flight` receipt?

**Context.** An ambiguous failure leaves the receipt `in_flight`, and every later attempt raises `Uncertain` (see the decision log). Today the only way out is editing `agent.db` by hand.

**Options.** A command in `fleet.recovery` that lists `in_flight` receipts and marks one `failed` ("checked, it did not happen") or `ok` ("checked, it did"), writing the change and a `db.log()` event in one `db.write()`. Or a separate module.

**Blocks.** Wiring `commit_once()` into `fleet/run.py`.

**Revisit when.** Before `commit_once()` or `run_step()` is wired into `fleet/run.py` or `claude_step()`. Until then nothing writes receipts.

**Settled by.** Choosing where the command lives, what it records in the ledger, and whether it needs `--force` like a halted run.

## Should settling an irreversible action go through `approvals`?

**Context.** For an irreversible action that can neither take a key nor be checked, an `in_flight` receipt older than its timeout should be treated as an incident for a human, not retried. The schema has an `approvals` table (`run_id`, `seq`, `action`, `fingerprint`, `decision`, `decided_by`) for recording such decisions, but nothing writes to it: `fleet/doctor.py` only checks that the table exists. So the approval trail is a schema, not a working feature.

**Options.** Have the settle command (see the question above) write an `approvals` row as well as its `action.settled` event; require an `approved` row before an irreversible action runs at all; or leave `approvals` unused until a concrete action needs it.

**Blocks.** Nothing yet. Matters once an irreversible action runs through `commit_once()`.

**Settled by.** Deciding which actions count as irreversible, and whether the human decision belongs on the settle path, before the action, or both.

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

**Blocks.** Nothing yet. `claude_step()` is wired in (2026-11-11) but does not go through `commit_once()`, so a prompt step writes no receipt.

**Settled by.** Wiring `claude_step()` in and inspecting real failed runs: where the final error appears (the `result` message or the last `api_retry` event) and whether tools ran before it.
