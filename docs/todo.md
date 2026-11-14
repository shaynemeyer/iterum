# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Next: what to work on, in order

Status: open, written 2026-11-10 after the merge gate was finished. The fence and merge-gate work is in `work-completed.md` and the decision log. `claude_step()` is wired into `fleet/run.py` and passed its first paid run (2026-11-11, `work-completed.md`). Most open questions wait on option B in `commit-once-design.md` (decision log, 2026-11-11). The sections after this list wait for a trigger; item 1, real feature runs, is where one would come from.

1. **Use `fleet.merge --check` on the next real runs.** Built and tested 2026-11-11 (`merge-check-design.md` section 6; moved to `work-completed.md`); first real use in the seventh Next.js run, two checks passing in about 5 s each; used again 2026-11-12 to land the notes section, whose printed command, with a quoted `[slug]` fence, pasted unchanged into zsh (`nextjs-first-run.md`). A staged refusal the same day: two branches that each built alone broke when merged, `--check` refused the second, kept its claim and left `main` alone, and after a hand fix it landed under the same fence (`nextjs-first-run.md`). The home-page copy (run `12c0572d5ec1`, 2026-11-12), the first run under `--restricted`, landed with `--check` on the first try. **No more runs just to find an unstaged refusal** (decided 2026-11-12): five Haiku runs that day (copy, links, one About link, and a concurrent pair where one read a file the other changed) each made a narrow edit with an output check and landed cleanly, and the staged refusal already showed the gate refuse, keep the claim and leave `main` alone. Keep using `--check` on every landing; record a refusal when one comes. Six Next.js feature runs (`nextjs-first-run.md`) surfaced three findings, each now handled: MCP tools and user context reaching prompt steps (decision log), a model-made syntax error (caught by the build step, fixed by hand, resumed for free), and branches that each build landing into a `main` that does not (now refused by `--check`). A free experiment showed a file-changing step that runs twice is fixed in the plan, so option B waits for an outside effect that cannot be checked first (decision log). Watch for a model mistake that gets past the build and `--check`: it would reopen the docs-hint decision (decision log, 2026-11-12, "Prompt steps stay bare"). Confirm each plan and its cap with the user before anything is billed, and record what runs surface here or in `open-questions.md`.
2. **Optional: let `reconcile()` remove the temporary worktree of an abandoned merge.** After a SIGKILL mid-check, the `iterum-check-*` worktree and the check's process are left behind and cleaned up by hand (`merge-check-design.md` section 6). Only if it happens in real use.
3. **Optional, billed: repeat short normal-exit runs.** T7 in `telemetry/claude-code-telemetry.md` showed a normal `claude -p` exit sending its last spend 0.28 s before `claude_step()` returned, in one run. A few more short Haiku runs would show whether that holds. Only with the user's go-ahead.
4. **Optional: replay gaps.** Replay `fleet/step.py` runs (covers retry classification), add attempt counts to the end state, replay releases and deadline halts. Only if a real failure needs one.
5. **Next paid fix-loop test: a page per tag** at `/notes/tags/[tag]`, a dynamic route under Cache Components, which tripped a model on 2026-11-12 (the eleventh run), so a first-try mistake and a real `fix.retry` are likelier. Same pattern as the tags page (`work-completed.md`, 2026-11-13). Plan, dry plan and check written 2026-11-13 in `docs/.local-only/` (`tag-pages.json`, `tag-pages-dry.json`, `check-tag-pages.sh`): one new file, `app/notes/tags/[tag]/page.tsx`; the prompt gives no hint about this Next.js version, as in the eleventh run. The check fails on `main` ("/notes/tags/claims did not answer 200"), passes on a hand-written correct page, and fails two wrong ones that build cleanly: `params` not awaited ("did not answer 200") and every note under every tag ("/notes/tags/queue links to /notes/resume"). The dry run on `feat/tag-pages` failed at step 3. Next: the paid run, `--allow-claude 0.05 --fix-retries 2`, after the user confirms the cap.

How this work has been done, and should continue: one small step at a time; reproduce a problem before fixing it; check each change against the three drills (`fleet.merge_drill`, a few seconds; `fleet.claims_drill` and `fleet.kill_drill`, about 50 seconds each, runnable in parallel) and the built-in `fleet.run` plan on a scratch `ITERUM_DB`; when a drill gains a check, break the code once to see it fail, and undo the break by reversing the edit, not with `git checkout` (that also discards uncommitted work).

## Fix loop follow-ups

Status: open, 2026-11-13. The loop is built (`work-completed.md`).

1. **Paid test**, with the user's OK: one Haiku feature with `--fix-retries`, to see whether a retry fixes a real mistake. The tags page (2026-11-13) passed first try, so no retry ran; item 5 of the list above is the next try.

## `/fleet-plan` follow-ups

Status: open, 2026-11-13, from the first test (decision log, "`/fleet-plan` is a user-level skill").

1. **The check is never shown to pass on a correct change.** `/fleet-plan` proves a check fails on `main`, but not that it passes on a correct version, as the hand-written checks were (`nextjs-first-run.md`, the tag pages). A wrong check fails a correct change, and the fix loop then pays for retries that cannot succeed. Until something covers it, the paid run is the first time a generated check meets a correct version. First case, 2026-11-13: the `tag-links` check passed on the run's correct change (`nextjs-first-run.md`). One case, so the gap stays open.

## The `pgid` write window

`_spawn()` starts a step's command (shell or `claude`), then writes `steps.pgid`. A kill between the two leaves a running command with no group to check, and a resume can overlap it. The window is one SQLite write. `Popen` cannot report the group before the child starts. The worker's `_shell()` has the same window before `queue.record_pgid()`; a reap there reruns the task alongside the command. Not reproduced; leave it unless it shows up.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

