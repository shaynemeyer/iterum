# Design note: wiring `commit_once()` into `fleet/run.py`

Status: agreed 2026-11-11 (see "Decisions" at the end): option A, `commit_once()` stays out of `fleet/run.py` for now.

Facts below come from reading the code at commit `425cd63`. Anything not checked is marked **unverified**.

## 1. What exists

`fleet/idem.py`, `commit_once(run_id, seq, intent, params, action)`:

- The key is `run_id:seq:<hash of intent>`; `params` is hashed separately.
- Before the action it inserts a receipt `in_flight`. The primary key makes the claim atomic, so a second process racing the same key gets `Uncertain`.
- After: `ok` with the result as `body`. On an exception whose `category` is in `REFUSED`: `failed`, and the next call clears it and runs again. Any other exception, including one with no category: the receipt stays `in_flight` (`action.uncertain` is logged).
- A later call with the same key: `ok` returns the stored result (`replayed=True`); `in_flight` raises `Uncertain`; different params raise `ParamMismatch`.

`fleet/step.py`, `run_step()`: wraps `commit_once()`, retries only `transient` categories, and on anything else sets the run `halted` and logs `run.halted`.

Nothing calls either module (`git grep`, 2026-11-11). No receipt has been written outside tests.

## 2. What `fleet.run` already guarantees without it

- Write-ahead: a step is `proposed` before its command runs and `committed` after.
- Resume skips committed steps and reruns the rest. A shell step killed after its side effect but before `committed` therefore runs twice; the built-in drill's step 4 exists to show that gap (`fleet/run.py`, comment above `PLAN`).
- Resume refuses while the run's heartbeat is young or an uncommitted step's process group is alive, unless `--force`.
- Resume refuses an uncommitted prompt step unless `--force` (`claude-step-design.md`, decision 2).
- Resume compares recorded intents with the plan's. Commands were not in the ledger, so a changed command under the same intent was not caught; since `aadd955` (decision 4) resume refuses it unless the step failed.
- Claims and `fleet.merge` keep edits to declared files.

So shell steps are at-least-once today, and prompt steps are at-most-once by a person's `--force`.

## 3. What going through `commit_once()` would change

| Situation | Today | Through `commit_once()` |
| --- | --- | --- |
| Shell step killed mid-command | Resume reruns it | Receipt `in_flight`: resume raises `Uncertain` until a person settles it |
| Shell step exits non-zero | Step and run `failed`; resume reruns it | No category, so ambiguous: receipt `in_flight`, same as above |
| Shell step's command changed, same intent, on resume | Not caught (refused since `aadd955`, unless the step failed) | `ParamMismatch`, if `params` is the command |
| Crash after the receipt is `ok`, before `step.committed` | Resume reruns it | Resume returns the stored result, no rerun |
| Two processes run the same step at once | Prevented by heartbeat, process group and claim checks | Also prevented by the receipt's primary key |
| Prompt step fails | Resume needs `--force` | Almost every failure is ambiguous (`claude-step-design.md` section 4): receipt `in_flight` |

The first two rows are the cost: every kill and every failing shell command would need a person, and there is no command to settle a receipt yet (open question "How does a human settle a stuck `in_flight` receipt?"). The built-in drill's kill-and-resume would halt instead of finishing. The last four rows are the gain, and for steps that can safely run twice it is small.

## 4. Options

**A. Do not wire it in.** `fleet.run`'s own rules stay the mechanism. `idem.py` and `step.py` wait for an action with an outside target (a deploy, a message, a charge). Cost: none now. Leaves `ParamMismatch` unused and the changed-command gap open.

**B. Opt in per step.** A plan step marked, for example, `"once": true` runs through `commit_once()`; others behave as today. Gives at-most-once where a rerun would hurt (a `git push`, a deploy), without changing the drills or ordinary shell steps. Needs the settle command first. The plan format and its name are **unverified** ideas, not a proposal yet.

**C. Every step.** All of section 3 applies. Needs the settle command, a way for shell steps to report `REFUSED` (open question "Which actions can prove nothing ran?"), and changes to the built-in drill.

`step.py`'s retries are a separate choice: `fleet.run` has none today, and a retry of a shell step is a rerun.

## 5. Proposed

**A for now, B when a plan has a step that must not run twice.** No current plan has one. The built-in drill's steps rewrite the same files when rerun. In the paid-run plan, `--force` already guards the prompt step, and a rerun `git commit` after a commit that landed finds nothing to commit and exits non-zero: the run fails, but nothing changes twice. Under A, the next small step would be catching a changed command on resume without receipts, by recording each step's command hash in `step.proposed`. That is a separate change, **unverified** as a design.

## Decisions (agreed 2026-11-11)

1. **Option A.** No plan has a step that must not run twice yet. The one action here that must not repeat, landing a branch, already has its own guard: `fleet.merge` moves the target with `git update-ref` and the expected old value, so a second attempt is refused, and `reconcile()` settles a merge a crash interrupted from its `merge.started` event. Revisit with option B when a plan needs a step such as a push, a deploy or a message.
2. **`fleet/step.py` stays**, unused. It is small, and the decision log and `todo.md` describe it. Option B would not necessarily use it: B needs `commit_once()`, and retries are a separate choice.
3. **Under B, the settle command comes first**, as its own step. Without it the first stuck receipt can only be cleared by editing `agent.db` by hand.
4. **Catch a changed command on resume.** Done 2026-11-11 (`aadd955`): `step.proposed` records a `command_hash`, and resume refuses a changed command unless the step failed (decision log, 2026-11-11).
