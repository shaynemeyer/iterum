# Open questions

Decisions not made yet. When one is answered, record it in `decision-log.md`, add any resulting work to `todo.md`, and remove it here.

## How does a human settle a stuck `in_flight` receipt?

**Context.** An ambiguous failure leaves the receipt `in_flight`, and every later attempt raises `Uncertain` (see the decision log). Today the only way out is editing `agent.db` by hand.

**Options.** A command in `fleet.recovery` that lists `in_flight` receipts and marks one `failed` ("checked, it did not happen") or `ok` ("checked, it did"), writing the change and a `db.log()` event in one `db.write()`. Or a separate module.

**Blocks.** Wiring `commit_once()` into `fleet/run.py`.

**Revisit when.** Before `commit_once()` or `run_step()` is wired into `fleet/run.py` or `claude_step()`. Until then nothing writes receipts.

**Settled by.** Choosing where the command lives, what it records in the ledger, and whether it needs `--force` like a halted run.

## Which actions can prove nothing ran?

**Context.** An action that knows it failed before taking effect can raise an error whose `category` is in `REFUSED`, freeing its key. Anything else stays locked.

**Options.** `shell()`: a command that is not found, or a plan step rejected before it starts. `claude_step()`: a failure on the first API request, before any tool ran.

**Blocks.** Wrapping `shell()` in `commit_once()` without locking every failed command.

**Settled by.** Listing each action's failure modes and which of them are certain.

## Should any Claude Code account or setup errors be `REFUSED`?

**Context.** `authentication_failed`, `billing_error` and the others are `LOGICAL` but not `REFUSED`, so their receipt stays `in_flight`. For a single API call that is too cautious; for a whole `claude -p` session it may be right, since the error can arrive after tools have run.

**Options.** Leave as is; add some to `REFUSED`; or let `claude_step()` decide per failure, based on whether any tool ran.

**Blocks.** Nothing yet. `claude_step()` is not wired in.

**Settled by.** Wiring `claude_step()` in and inspecting real failed runs: where the final error appears (the `result` message or the last `api_retry` event) and whether tools ran before it.

## Who runs `fleet.recovery`?

**Context.** `fleet.recovery` lists dead runs and halts over-retried ones, but nothing runs it.

**Options.** By hand; at the start of every `run.py` invocation; or a scheduler.

**Blocks.** Dead runs being noticed without a human looking.

**Settled by.** Deciding how often a dead run must be noticed, and whether `run.py` should pay that cost on every start.
