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

   **Rule (user requirement, 2026-11-12): no plan with open questions.** `/fleet-plan` always asks clarifying questions first, and keeps asking until nothing about the feature is unresolved: what it should do, which files, what counts as done (the check), anything the request leaves open. Only then does it write the plan. The plan document ends with an "Open questions" line that must read "None"; if anything is still open, there is no plan and no "Implement?" question. The reason: an unattended run cannot ask, so any ambiguity left at planning time becomes a guess made at night.

   **Rule (user requirement, 2026-11-12): small, parallel chunks.** `/fleet-plan` breaks a feature into small chunks, each one prompt step (or one run), sized to use well under 100K tokens of context, and runs chunks in parallel wherever they can be. The reason is context rot: models use long contexts less reliably, and performance "consistently degrades with increasing input length" (Chroma's report, summarised in `context-rot.md`). 100K is the user's budget, not a threshold from the report, which finds degradation growing with length rather than starting at a fixed size.
   - **Parallel needs disjoint files.** Two chunks can run at once only if they claim different files; claims would refuse an overlap anyway. Chunks that build on each other run in order, as queue tasks with `depends_on`.
   - **The plan document shows the breakdown:** each chunk's files, what it depends on, which chunks run in parallel, and an estimated context size.
   - **Checking the budget after a run is already possible.** Every `spend.reported` event records `input_tokens`, `cache_read_tokens` and `cache_creation_tokens`, and `fleet.view context` sums them per request. The six feature steps of 2026-11-12 peaked at 5,801 to 7,623 tokens per request. Estimating before the run is harder: files read and turns taken are only known afterwards.
   - **Merged chunks can still break each other,** as the staged refusal showed: each chunk's check passes alone and the merged tree fails. Landing each chunk with `fleet.merge --check` in dependency order catches that.
3. **The model cannot run anything.** No shell in a prompt step. The fix loop works around it: the harness runs build and tests, the model reads the errors.
4. **Nothing keeps it moving.** No process resumes a dead run or restarts a dead telemetry receiver. Idea: each feature is a queue task whose work is one `fleet.run` plan, and a worker drains the list overnight.
5. **A morning report.** Branches that passed and are ready to land; branches that failed, with the failing step's error; cost per feature. Landing stays a morning decision for a person (proposal: no unattended landing).

## 5. Proposed order

Each step is useful alone, so the work can stop after any of them.

1. **Fix loop** in `fleet.run`. When a step after a prompt step fails, rerun the prompt step with the error text added to the prompt, at most N times (proposal: 3), each try under the per-step cap; then fail the run as today.
   - Free test: a fake `claude` script on `PATH` that writes broken code first and correct code when the prompt contains the error. The check fails once, is fed back, passes.
   - Paid test, with the user's OK: one real Haiku feature where a first try breaks the build, if it happens.
   - Unknown: how often a retry with the error text fixes a real model mistake. The paid test is the first evidence.
   - **Built 2026-11-13** as `--fix-retries N` (opt-in, default 0); the free test passed (`work-completed.md`). Open: the paid test, and the gaps listed in `todo.md`.
2. **`/fleet-plan`**: sentence, then clarifying questions until none are open, then plan document, then "Implement this feature?". A test: a deliberately vague request must produce questions, not a plan.
3. **A night's queue and a morning report.**

## 5a. Experiment: a night's queue with what exists, 2026-11-13

Free, no code: two dry plans (prompt step `echo dry`; checks for a back link on note pages and note counts on `/notes/tags` that fail on `main`), each queued with `queue.add("plan", {"cmd": "cd <app> && git switch -c feat/<slug> main && iterum run <dry plan>"})` on a scratch database, then one `iterum worker night-1 --budget-s 400`.

What held: the worker claimed and ran both plans in turn, each on its own branch from `main`; both runs failed at their check (step 3) as planned; `iterum status` (exit 1) and `iterum dlq` listed both runs and both tasks; `iterum report --json` listed the runs under `needs_person`.

What broke or is missing:

1. **No command adds a task.** Only `queue.add()` from Python.
2. **The queue retried each failed plan, and the retries buried the cause.** Plan tasks got the default `max_attempts` 3. Attempts 2 and 3 failed at once on `fatal: a branch named 'feat/<slug>' already exists`, and that became the dead letter's reason. The real cause (the check's message) is only in the first attempt's event and in the run. A plan already retries inside itself (`--fix-retries`); rerunning it whole from the queue cannot help.
3. **A task's reason is the first 200 characters of stderr** (`_default_do_work()`), here starting with git's `Switched to a new branch`. A longer error would lose the plan's message at the end.
4. **Nothing links a task to its run.** `status` lists task 1 and run `3c79b05dfdcf` apart; the morning view cannot say which feature failed where.
5. **The app is left on the last task's branch.** With dry plans the tree stayed clean. A real prompt step that fails leaves edits uncommitted, and the next task's `git switch -c` would most likely carry them onto the next branch (git keeps uncommitted changes on switch when they do not conflict). Not reproduced. *Reproduced 2026-11-14 (`todo.md`): task 2 finished `done` with task 1's edit in its tree.*

Items 1 to 3 are fixed (`work-completed.md`, 2026-11-14): `iterum add` with one attempt by default, and the reason keeps the end of stderr.

## 5b. Sketch: the worker owns the task's branch, 2026-11-14

Status: proposal, nothing built. For item 5 above.

**Why the worker, not the task's command.** Today the branch is made inside the task's shell string (`cd <app> && git switch -c feat/x main && iterum run ...`), so the worker knows neither the repo nor the branch. It cannot tell where leftovers belong, and if the command fails before its own `git switch`, the tree is on whatever branch the last task left, possibly `main`. Committing leftovers there would be wrong. `fleet/sweep.py` avoids this because it makes each branch itself.

**Proposal.**

1. `iterum add "<cmd>" --repo <app> --branch feat/x [--base main]`. `repo` (absolute), `branch` and `base` go in the task's payload, which is already JSON, so no schema change. Without `--repo`, a task runs as today.
2. Before the command, in the repo: refuse a dirty tree, then `git switch -c <branch> <base>`, then run the command there (the command no longer needs its own `cd` or `switch`).
3. After the command:
   - failed, tree dirty: `git add --all` and commit on `<branch>` ("iterum: what task N left behind"), as `keep_leftovers()` does; the failed output stays for the morning;
   - done, tree dirty: a plan without a commit step; leave it and stop the worker, as `require_clean()` stops a sweep;
   - then `git switch <base>`, so the app is never left on a task's branch.

**Open questions.**

- **A dirty tree before a task:** fail that task (with one attempt it dead-letters; the next task meets the same tree and fails too, so one stray edit dead-letters the night), or stop the worker and leave the queue queued, as the ceiling check does (`governor.headroom()`). Leaning: stop the worker.
- **Redrive:** a redriven task's branch already exists, so `switch -c` fails. Switch to it instead (continuing on top of the leftovers commit), or refuse and ask for a new branch name. Only matters once a redrive happens.
- **Shared code with `fleet/sweep.py`:** its `git()`, `require_clean()` and `keep_leftovers()` exit the process; the worker needs exceptions so a failed task does not end the worker. Copy the three small helpers, or move them to a shared module that raises. Leaning: a shared module, if the two stay this alike.
- **Several repos:** a worker with tasks for two repos is fine under this sketch (each task names its repo), but claims still collide on same-named files across repos (section 7).

**Free test.** The two tasks of the 2026-11-14 reproduction, rewritten with `--repo` and `--branch`: task 1's edit is committed on `feat/a`, task 2 starts clean on `feat/b`, the app ends on `main`. Then a stray edit in the app before the worker starts: the worker stops and both tasks stay `ready`.

## 5c. Rerun with the fixes, 2026-11-14

Free, no prompt steps: scratch database, the real app, tasks queued with `iterum add "iterum run <plan>" --repo <app> --branch feat/night-<x>`, one `iterum worker night-1`. Plan A: `echo dry`, build, the tag-pages check (passes on `main`, the feature has landed). Plan B: append a line to a file (stands in for a half-done prompt step), build, a check that fails.

What held:

- **The dirty-tree stop.** The first start met an untracked `harness-audit.json` (an `iterum doctor` run in the wrong folder): the worker stopped (exit 1), listed it, handed task 1 back; both tasks stayed `ready`, the app untouched. Without the stop, `git switch` would have carried it and a failed task's `git add --all` committed it.
- **Branches.** Task 1 ran on `feat/night-a` and finished `done`; the app ended on `main`, clean.
- **Leftovers.** Plan B alone (on `app/notes/page.tsx`): the run failed at its check, the dead letter's reason is the check's message, the half-done edit is committed on `feat/night-b2` as "iterum: what task 3 left behind", and the app ended clean on `main`.
- **The link.** Every run's `run.started` names its task (`task-test-1`, `-2`, `-3`).

What broke or is missing:

1. **Two tasks on the same file in one night: the second is refused.** Plans A and B both claimed `app/notes/tags/[tag]/page.tsx`. Run A finished and kept its claim, as every run does until it is landed; run B started 2.5 minutes later, inside the claim's 300 s, and was refused before any step ran (`claim.refused`), so its one attempt dead-lettered. By design, and the test plans should not have shared a file, but `/fleet-plan` chunks of one feature could. Not tested: a task started after the claim expires would take it, and run A's landing would then be refused (`claim.expired_own()` accepts only an unchanged row). Dependent chunks have a second problem: each branch starts from `main`, so a chunk does not see the chunk it depends on until that one is landed.
2. **A finished task keeps a stale reason.** Task 1 was handed back once ("repo has uncommitted changes") and then finished `done`, but `tasks.reason` still says "repo has uncommitted changes". `finish()` does not clear it. Cosmetic: `dlq` does not list done tasks.

## 6. Open decisions

- *Settled 2026-11-13 (decision log): `/fleet-plan` is user-level, plans go in a gitignored `plans/`.*
- **Where `/fleet-plan` lives.** (A) In this repo, started from a session in the Iterum folder with the app path as an argument. (B) As a user-level skill (`~/.claude/skills/fleet-plan/`), started from inside the app repo, with one setting such as `ITERUM_HOME` pointing at this repo. Leaning B: it matches working from inside the app, as the user's spec-driven `/feature` skill does.
- **Where generated plans are kept.** Proposal: a gitignored `plans/` folder in this repo, so the app's working tree stays clean and app details stay out of the public repo; resume uses the same file.
- **Retries:** how many, whether each retry gets the full cap, and whether the error text is trimmed (the merge gate keeps the last 2,000 characters of a failed check).
- **Unattended landing:** proposal no; the morning report lists the land commands.
- **Budget for a night:** the fleet ceiling as is, or a separate ceiling per night.
- **The 100K context budget:** how to estimate a chunk's size before running it, and what happens when a run exceeds it (split the chunk and retry, or only report it in the morning).
- **One chunk, one run, or one queue task?** Parallel chunks need separate branches (each run claims on its own branch); dependent chunks need ordering. Whether a feature becomes several `fleet.run` plans driven by the queue, or one plan with several prompt steps, is open.

## 7. Related discussion from the same session

- **The plan format is a lot to write by hand.** Per-step file lists only matter as one set (`claim_files()` claims the union before step 1; `check_prompt_steps()` only needs each prompt step to list some file), and the step number must match its position anyway. Considered and not chosen, to avoid complexity: TOML plans with plan-level files; a `fleet.feature "<prompt>" --files ... --check ...` command that generates the usual plan; a `/feature run` action in the user's spec-driven `/feature` skill. `/fleet-plan` (section 4, item 2) would make the format something a person reads in the plan document rather than writes.
- **Several repos on one `agent.db`.** A claim's name is the file's path from its git root, with no repo in it (`fleet/claim.py`, `file_resource()`), so `README.md` in two repos is one resource: a run in one repo would be refused while a run in the other holds it. Fails safe, but confusing. Found by reading the code; not reproduced. Matters once the overnight queue spans repos.
- **Prompt steps fit small, bounded features.** Read/Edit/Write and 10 turns suit one to three files. A larger spec would need several prompt steps, or stays with an interactive session.

## 8. State at the end of the session

- All Iterum work is committed on `main`.
- A user guide was written (`gh-pages` change prepared, not pushed: `guide.html` plus nav links in `index.html`, in a worktree of `gh-pages`). It describes today's JSON plans; the "Shipping a feature" chapter would change if `/fleet-plan` lands.
