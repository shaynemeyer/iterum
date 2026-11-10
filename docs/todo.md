# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Wire `iterum.run_id` into `claude_step()`

When `claude_step()` replaces `shell()` in `fleet/run.py`, it must start Claude Code with the `.env.example` settings plus `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<run_id>`, so spend lands under the run instead of `session-<session.id>`.

## Should SIGTERM stop a step's command?

`kill -TERM` on `fleet/run.py` mid-step leaves the step's command running (tested 2026-11-10, see `work-completed.md`); the resume guard waits for it. It did the same before steps had their own group. A SIGTERM handler that raises like Ctrl-C would let `shell()` kill the group on a polite stop. Decide whether a polite stop should end the step; SIGKILL can never be covered this way.

## The `pgid` write window

`shell()` starts the command, then writes `steps.pgid`. A kill between the two leaves a running command with no group to check, and a resume can overlap it. The window is one SQLite write. `Popen` cannot report the group before the child starts. The worker's `_shell()` has the same window before `queue.record_pgid()`; a reap there reruns the task alongside the command. Not reproduced; leave it unless it shows up.

## `commit_once` logs nothing on an ambiguous failure

When an action fails without a `REFUSED` category, `commit_once()` leaves the receipt `in_flight` and writes no event, so the ledger shows `action.claimed` with no outcome. `run_step()` covers this with `step.failed` and `run.halted`, but a direct caller of `commit_once()` leaves no record of why the receipt is stuck. Log an event (for example `action.uncertain`, with the category) before re-raising.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

## Build the merge gate that checks fences

Status: open. Items 2, 3 and 5 are done, and 4 is started: `uv run python -m fleet.merge <branch> --run-id R --fence RESOURCE=FENCE ...` is the merge process. Items 1 and the rest of 4 remain.

`land()` builds the merge with `git merge-tree --write-tree` and `git commit-tree`, so no working tree is touched. It lists the changed files with `--no-renames` (a rename needs claims on both paths). Then, in one `db.write()` block, it calls `require_claim()` for each file and either logs `merge.landed` and runs `git update-ref` with the old value, or logs `merge.refused` and raises. Checked: a live claim landed; a file with no claim, an expired claim and a stale fence after a takeover were refused with `main` unchanged; a conflict raised `Conflict`; a target moved between build and update raised `CalledProcessError` and left no `merge.landed` event; a retry then landed.

Found while testing: the target branch must not be checked out in any working tree. `update-ref` moves the branch but not that tree's index, so the next commit made there reverted the landed change (seen in the scratch repo: an "edit b" commit also reverted `a.txt`).

A fence protects nothing unless whatever accepts the write checks it. An agent cannot check its own fence, because it can pause right after checking. A `PreToolUse` hook has the same gap, and one that times out does not block the call.

1. Agents edit only in their own git worktrees.
2. A single merge process lands each change on the shared branch. It builds the merge outside any transaction. Then, inside one `db.write()` block, it calls `claim.require_claim()` and moves the branch with `git update-ref` and the expected old value, so no newer fence can be issued between the check and the update. Do not hold the write lock for the whole merge: other writers fail after the 5-second busy timeout.
3. Done 2026-11-10: `land()` writes `merge.started` ahead, and `merge.reconcile()` settles a crash when the merge process starts (see the decision log). `python -m fleet.merge` takes an exclusive `flock` on `iterum-merge.lock` in the repo's git common dir, refuses if the target is checked out in any worktree, then calls `reconcile()` and `land()`. Tested 2026-11-10 against a shared repo with a detached HEAD and one worktree per agent: a checked-out `main` was refused; a live claim landed (exit 0); no fence and a paused agent's stale fence after a takeover were refused (exit 1); a second merge waited about 2 seconds for a process holding the lock, then landed; after a crash right after `update-ref`, the next merge logged `merge.landed` recovered before landing its own branch.
4. Wire claims into `fleet/run.py`, and renew them while a step runs. A step longer than `claim.DEFAULT_TTL` (300 seconds) would otherwise lose its lease.
   - Done 2026-11-10: plans declare resources and `fleet.run` claims them all before any step (see the decision log).
   - Still to do: renew the claims from the heartbeat thread, with `renew()` refusing an expired claim and a refused renewal failing the step. Claims are released on landing (see the decision log).
5. Done 2026-11-10: `uv run python -u -m fleet.merge_drill` covers the paused-agent case, the other refusals, the lock, a crash after `update-ref` and a moved target, in about 3.5 seconds. Removing the live-claim check from `require_claim()` made it fail on the expired claim; removing `reconcile()` from the merge process made it fail on the crash.

File claims do not catch changes in different files that break each other, even when the merge is clean. Tests or CI still have to catch those.
