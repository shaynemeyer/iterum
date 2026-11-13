# TODO

Done items move to `work-completed.md`. Undecided questions live in `open-questions.md`, made decisions in `decision-log.md`.

## Next: what to work on, in order

Status: open, written 2026-11-10 after the merge gate was finished. The fence and merge-gate work is in `work-completed.md` and the decision log. `claude_step()` is wired into `fleet/run.py` and passed its first paid run (2026-11-11, `work-completed.md`). Most open questions wait on option B in `commit-once-design.md` (decision log, 2026-11-11). The sections after this list wait for a trigger; item 1, real feature runs, is where one would come from.

1. **Use `fleet.merge --check` on the next real runs.** Built and tested 2026-11-11 (`merge-check-design.md` section 6; moved to `work-completed.md`); first real use in the seventh Next.js run, two checks passing in about 5 s each; used again 2026-11-12 to land the notes section, whose printed command, with a quoted `[slug]` fence, pasted unchanged into zsh (`nextjs-first-run.md`). A staged refusal the same day: two branches that each built alone broke when merged, `--check` refused the second, kept its claim and left `main` alone, and after a hand fix it landed under the same fence (`nextjs-first-run.md`). The home-page copy (run `12c0572d5ec1`, 2026-11-12), the first run under `--restricted`, landed with `--check` on the first try. **No more runs just to find an unstaged refusal** (decided 2026-11-12): five Haiku runs that day (copy, links, one About link, and a concurrent pair where one read a file the other changed) each made a narrow edit with an output check and landed cleanly, and the staged refusal already showed the gate refuse, keep the claim and leave `main` alone. Keep using `--check` on every landing; record a refusal when one comes. Six Next.js feature runs (`nextjs-first-run.md`) surfaced three findings, each now handled: MCP tools and user context reaching prompt steps (decision log), a model-made syntax error (caught by the build step, fixed by hand, resumed for free), and branches that each build landing into a `main` that does not (now refused by `--check`). A free experiment showed a file-changing step that runs twice is fixed in the plan, so option B waits for an outside effect that cannot be checked first (decision log). Watch for a model mistake that gets past the build and `--check`: it would reopen the docs-hint decision (decision log, 2026-11-12, "Prompt steps stay bare"). Confirm each plan and its cap with the user before anything is billed, and record what runs surface here or in `open-questions.md`.
2. **Optional: let `reconcile()` remove the temporary worktree of an abandoned merge.** After a SIGKILL mid-check, the `iterum-check-*` worktree and the check's process are left behind and cleaned up by hand (`merge-check-design.md` section 6). Only if it happens in real use.
3. **Optional, billed: repeat short normal-exit runs.** T7 in `telemetry/claude-code-telemetry.md` showed a normal `claude -p` exit sending its last spend 0.28 s before `claude_step()` returned, in one run. A few more short Haiku runs would show whether that holds. Only with the user's go-ahead.
4. **Optional: replay gaps.** Replay `fleet/step.py` runs (covers retry classification), add attempt counts to the end state, replay releases and deadline halts. Only if a real failure needs one.
5. **Ready, run when wanted: a tags page for the Next.js app, end to end with `iterum`.** Planned 2026-11-13. The first paid run through the `iterum` command, the default database and `iterum land` reading fences from the database. The feature: `/notes/tags`, one new file (`app/notes/tags/page.tsx`) listing every tag with the notes that carry it, each linking to its note. Plan, dry plan and check script are in `docs/.local-only/` (`tags-page.json`, `tags-page-dry.json`, `check-tags-page.sh`): step 1 a Haiku prompt step, then the build, the check, a commit, every step claiming the one file. The check builds and serves the app and needs a 200 from `/notes/tags`, the title `Tags | iterum demo`, an `<h2>` for each of `claims`, `plans`, `queue` and `recovery`, links to all three notes, and `fences` listed twice (it carries two tags). Steps, from the app repo:
   1. `git switch -c feat/tags-page main`.
   2. Free: on a scratch `ITERUM_DB`, `iterum run <local>/tags-page-dry.json`; it must fail at step 3, which proves the check fails without the page. Then delete the branch and the scratch database.
   3. Confirm the plan and the cap with the user (a $0.05 cap; recent Haiku feature steps cost $0.001 to $0.002).
   4. `iterum receiver` in another terminal; `source <iterum>/.env.example`; on a fresh `feat/tags-page`, `iterum run <local>/tags-page.json --allow-claude 0.05`.
   5. `iterum land feat/tags-page --run-id <run_id> --check "bun install --frozen-lockfile && bun run build"` from a checkout other than `main`, as before.
   6. `iterum report --open`, and record the run in `nextjs-first-run.md`: cost, turns, whether the check or `--check` caught anything, and anything the new commands got wrong.
   A bolder follow-up, if this lands cleanly: a page per tag at `/notes/tags/[tag]`, a dynamic route under Cache Components, which tripped a model on 2026-11-12 (the eleventh run).

How this work has been done, and should continue: one small step at a time; reproduce a problem before fixing it; check each change against the three drills (`fleet.merge_drill`, a few seconds; `fleet.claims_drill` and `fleet.kill_drill`, about 50 seconds each, runnable in parallel) and the built-in `fleet.run` plan on a scratch `ITERUM_DB`; when a drill gains a check, break the code once to see it fail, and undo the break by reversing the edit, not with `git checkout` (that also discards uncommitted work).

## Fix loop follow-ups

Status: open, 2026-11-13. The loop is built (`work-completed.md`).

1. **`iterum recovery` may halt a retried run.** It halts a failed run whose most-proposed step reached `--max-attempts` (default 3); with 2 retries the prompt step is proposed 3 times. Not reproduced.
2. **Paid test**, with the user's OK: one Haiku feature with `--fix-retries`, to see whether a retry fixes a real mistake.

## The `pgid` write window

`_spawn()` starts a step's command (shell or `claude`), then writes `steps.pgid`. A kill between the two leaves a running command with no group to check, and a resume can overlap it. The window is one SQLite write. `Popen` cannot report the group before the child starts. The worker's `_shell()` has the same window before `queue.record_pgid()`; a reap there reruns the task alongside the command. Not reproduced; leave it unless it shows up.

## Check: `run_step` raises `StepError`, not `Uncertain`, for ambiguous failures

Status: open. Revisit when the first caller of `fleet/step.py`'s `run_step()` is written.

### What changed

`commit_once()` leaves a receipt `in_flight` when an action fails with a category in `idem.AMBIGUOUS` (`timeout`, `server_error`). `run_step()` used to classify those as `transient`, sleep, and retry, and the retry could only raise `idem.Uncertain`. It now halts on the first failure with classification `ambiguous` and re-raises the original `StepError`, so the halt reason keeps the real cause (`timeout: request timed out` instead of `key ... was started and never settled`).

### What to check

A caller that treats `idem.Uncertain` as "the action may have happened" must also treat a `StepError` whose `category` is in `idem.AMBIGUOUS` the same way. Both leave the receipt `in_flight`, and neither may be retried until a human settles it. No caller exists yet, so nothing is broken today.

