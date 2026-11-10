# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Next: what to work on, in order

Status: open, written 2026-11-10 after the merge gate was finished. The fence and merge-gate work is in `work-completed.md` and the decision log. Most open questions wait on `commit_once()` or `claude_step()` being wired into `fleet/run.py`; implementing `claude_step()` (design agreed in `claude-step-design.md`) comes first.

How this work has been done, and should continue: one small step at a time; reproduce a problem before fixing it; check each change against the three drills (`fleet.merge_drill`, a few seconds; `fleet.claims_drill` and `fleet.kill_drill`, about 50 seconds each, runnable in parallel) and the built-in `fleet.run` plan on a scratch `ITERUM_DB`; when a drill gains a check, break the code once to see it fail, and undo the break by reversing the edit, not with `git checkout` (that also discards uncommitted work).

1. **Implement `claude_step()` in `fleet/run.py` as agreed in `claude-step-design.md`.** Free checks first, with a fake `claude` script on `PATH` (the six in the note's test plan). Then one paid run, only with the user's go-ahead.

## Wire `iterum.run_id` into `claude_step()`

When `claude_step()` replaces `shell()` in `fleet/run.py`, it must start Claude Code with the `.env.example` settings plus `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<run_id>`, so spend lands under the run instead of `session-<session.id>`.

## The `pgid` write window

`shell()` starts the command, then writes `steps.pgid`. A kill between the two leaves a running command with no group to check, and a resume can overlap it. The window is one SQLite write. `Popen` cannot report the group before the child starts. The worker's `_shell()` has the same window before `queue.record_pgid()`; a reap there reruns the task alongside the command. Not reproduced; leave it unless it shows up.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

