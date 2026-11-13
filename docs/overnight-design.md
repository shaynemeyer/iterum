# Design: tell Iterum to implement a feature, and let it work all night

Status: idea, not started. Written 2026-11-12 at the end of a session, to start the discussion in a new one. Nothing here is decided; the open decisions are listed at the end.

## 1. The goal

Say, in one sentence, "work on this project and implement this feature", approve a plan and a budget, and leave. Iterum works unattended overnight. In the morning there are branches that passed their checks, ready to land, a list of what failed and why, and what it cost.

## 2. How a feature is shipped today

Six Haiku feature runs on 2026-11-12 (`nextjs-first-run.md`) all followed one routine, run by hand in a Claude Code session:

1. Pick a small feature and the one to three files it touches; make a branch in the app repo.
2. Write a plan (`[[seq, intent, command, [resources]], ...]`): a prompt step, build, an output check, commit, every step claiming the same files.
3. Write a check script and run it on `main`: it must fail.
4. Dry-run the plan on a scratch database with the prompt replaced by `echo dry`: it must fail at the check and nowhere else.
5. Start `fleet.telemetry`, `source .env.example`, run the plan with `--allow-claude 0.05`.
6. Read the diff and the cost; land with `fleet.merge ... --check "<build>"`; stop the receiver.

Every run passed first time, at $0.0011 to $0.0020 per prompt step. Each paid step and each landing waited for a person's OK.

## 3. What already holds up unattended

| Need | What exists | Evidence |
| --- | --- | --- |
| Survive crashes and kills | Write-ahead steps; resume skips the committed set | the kill drill, `fleet.kill_drill` |
| Stop before overspending | Fleet ceiling checked before every step and every queue claim | decision log; soft by about one step's spend per concurrent run (decision log, 2026-11-12) |
| Parallel work without collisions | File claims with fences; the gate hook; the merge gate with `--check` | `fleet.claims_drill`, `fleet.merge_drill`, the staged refusal in `nextjs-first-run.md` |
| A list of work | The queue: dependencies, leases, backoff, dead letters, redrive | `fleet.kill_drill`, replayed cases in `fleet.eval` |
| A record for the morning | The ledger; `fleet.view`, `fleet.view trace` | |
| A bounded model session | Prompt steps: Read/Edit/Write only, `--restricted`, 10 turns, a cap | decision log, 2026-11-12 |

## 4. What is missing, most important first

1. **A failure ends the work.** When the build or check fails after a prompt step, the run fails and waits for a person. (One earlier run had a model-made syntax error, fixed by hand and resumed.) Working all night needs a **fix loop**: feed the failing step's output back into the prompt step and try again, a few times, within the cap.
2. **Turning a sentence into a plan.** Today a person, or Claude in a session, writes the plan and check. Idea: a `/fleet-plan` skill that reads the repo, writes the plan, the check script and a short plan document in plain words (files, prompt, build, what the check looks for, model, cap), proves the check fails on `main`, and asks "Implement this feature?". For an overnight run this happens before leaving: the plan and the budget are approved up front, not per step.
3. **The model cannot run anything.** No shell in a prompt step. The fix loop works around it: the harness runs build and tests, the model reads the errors.
4. **Nothing keeps it moving.** No process resumes a dead run or restarts a dead telemetry receiver. Idea: each feature is a queue task whose work is one `fleet.run` plan, and a worker drains the list overnight.
5. **A morning report.** Branches that passed and are ready to land; branches that failed, with the failing step's error; cost per feature. Landing stays a morning decision for a person (proposal: no unattended landing).

## 5. Proposed order

Each step is useful alone, so the work can stop after any of them.

1. **Fix loop** in `fleet.run`. When a step after a prompt step fails, rerun the prompt step with the error text added to the prompt, at most N times (proposal: 3), each try under the per-step cap; then fail the run as today.
   - Free test: a fake `claude` script on `PATH` that writes broken code first and correct code when the prompt contains the error. The check fails once, is fed back, passes.
   - Paid test, with the user's OK: one real Haiku feature where a first try breaks the build, if it happens.
   - Unknown: how often a retry with the error text fixes a real model mistake. The paid test is the first evidence.
2. **`/fleet-plan`**: sentence to plan document to "Implement this feature?".
3. **A night's queue and a morning report.**

## 6. Open decisions

- **Where `/fleet-plan` lives.** (A) In this repo, started from a session in the Iterum folder with the app path as an argument. (B) As a user-level skill (`~/.claude/skills/fleet-plan/`), started from inside the app repo, with one setting such as `ITERUM_HOME` pointing at this repo. Leaning B: it matches working from inside the app, as the user's spec-driven `/feature` skill does.
- **Where generated plans are kept.** Proposal: a gitignored `plans/` folder in this repo, so the app's working tree stays clean and app details stay out of the public repo; resume uses the same file.
- **Retries:** how many, whether each retry gets the full cap, and whether the error text is trimmed (the merge gate keeps the last 2,000 characters of a failed check).
- **Unattended landing:** proposal no; the morning report lists the land commands.
- **Budget for a night:** the fleet ceiling as is, or a separate ceiling per night.

## 7. Related discussion from the same session

- **The plan format is a lot to write by hand.** Per-step file lists only matter as one set (`claim_files()` claims the union before step 1; `check_prompt_steps()` only needs each prompt step to list some file), and the step number must match its position anyway. Considered and not chosen, to avoid complexity: TOML plans with plan-level files; a `fleet.feature "<prompt>" --files ... --check ...` command that generates the usual plan; a `/feature run` action in the user's spec-driven `/feature` skill. `/fleet-plan` (section 4, item 2) would make the format something a person reads in the plan document rather than writes.
- **Several repos on one `agent.db`.** A claim's name is the file's path from its git root, with no repo in it (`fleet/claim.py`, `file_resource()`), so `README.md` in two repos is one resource: a run in one repo would be refused while a run in the other holds it. Fails safe, but confusing. Found by reading the code; not reproduced. Matters once the overnight queue spans repos.
- **Prompt steps fit small, bounded features.** Read/Edit/Write and 10 turns suit one to three files. A larger spec would need several prompt steps, or stays with an interactive session.

## 8. State at the end of the session

- All Iterum work is committed on `main`.
- A user guide was written (`gh-pages` change prepared, not pushed: `guide.html` plus nav links in `index.html`, in a worktree of `gh-pages`). It describes today's JSON plans; the "Shipping a feature" chapter would change if `/fleet-plan` lands.
