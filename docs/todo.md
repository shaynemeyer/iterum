# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Next: what to work on, in order

Status: open, written 2026-11-10 after the merge gate was finished. The fence and merge-gate work is in `work-completed.md` and the decision log. `claude_step()` is wired into `fleet/run.py` and passed its first paid run (2026-11-11, `work-completed.md`). Most open questions wait on option B in `commit-once-design.md` (decision log, 2026-11-11). The sections after this list wait for a trigger; item 1 is how to find one.

1. **Use `fleet.merge --check` on the next real runs.** Built and tested 2026-11-11 (`merge-check-design.md` section 6; moved to `work-completed.md`); first real use in the seventh Next.js run, two checks passing in about 5 s each. Six Next.js feature runs (`nextjs-first-run.md`) surfaced three findings, each now handled: MCP tools and user context reaching prompt steps (decision log), a model-made syntax error (caught by the build step, fixed by hand, resumed for free), and branches that each build landing into a `main` that does not (now refused by `--check`). A free experiment showed a file-changing step that runs twice is fixed in the plan, so option B waits for an outside effect that cannot be checked first (decision log). Confirm each plan and its cap with the user before anything is billed, and record what runs surface here or in `open-questions.md`.
2. **Optional: let `reconcile()` remove the temporary worktree of an abandoned merge.** After a SIGKILL mid-check, the `iterum-check-*` worktree and the check's process are left behind and cleaned up by hand (`merge-check-design.md` section 6). Only if it happens in real use.
3. **Optional, billed: repeat short normal-exit runs.** T7 in `telemetry/claude-code-telemetry.md` showed a normal `claude -p` exit sending its last spend 0.28 s before `claude_step()` returned, in one run. A few more short Haiku runs would show whether that holds. Only with the user's go-ahead.
4. **`fleet/sweep.py`: a model sweep.** Run each model-mix plan N times in alternating order (the first request pays to write the prompt cache, `nextjs-first-run.md` eighth run), record each run's outcome and cost from `spend.reported`, print pass rate beside cost per mix, and report no signal when the spread within a mix overlaps the gap between mixes. Build and dry-run it free first (scratch database, `echo` in place of prompt steps). Any paid run only with the user's go-ahead and a stated ceiling. Run mixes one after another: an unlanded branch keeps its file claims until `ITERUM_CLAIM_TTL`.
5. **Optional: replay gaps.** Replay `fleet/step.py` runs (covers retry classification), add attempt counts to the end state, replay releases and deadline halts. Only if a real failure needs one.

How this work has been done, and should continue: one small step at a time; reproduce a problem before fixing it; check each change against the three drills (`fleet.merge_drill`, a few seconds; `fleet.claims_drill` and `fleet.kill_drill`, about 50 seconds each, runnable in parallel) and the built-in `fleet.run` plan on a scratch `ITERUM_DB`; when a drill gains a check, break the code once to see it fail, and undo the break by reversing the edit, not with `git checkout` (that also discards uncommitted work).

## The `pgid` write window

`_spawn()` starts a step's command (shell or `claude`), then writes `steps.pgid`. A kill between the two leaves a running command with no group to check, and a resume can overlap it. The window is one SQLite write. `Popen` cannot report the group before the child starts. The worker's `_shell()` has the same window before `queue.record_pgid()`; a reap there reruns the task alongside the command. Not reproduced; leave it unless it shows up.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

