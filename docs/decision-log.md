# Decision log

Decisions and why they were made. Newest first. Entries are never deleted; a decision that is reversed is marked "Superseded by" the entry that replaces it. Open decisions live in `open-questions.md`.

## 2026-11-14: `/fleet-plan` ships in this repo as the `iterum` plugin

**Decision.** The skill lives at `plugins/iterum/skills/fleet-plan/SKILL.md`, in a plugin named `iterum`, listed by a marketplace at `.claude-plugin/marketplace.json`; it runs as `/iterum:fleet-plan`. The personal copy in `~/.claude/skills/fleet-plan/` is deleted. Supersedes the "user-level skill" part of the 2026-11-13 entry; plans still go in the gitignored `plans/` of the Iterum checkout (`ITERUM_HOME`).

**Context.** The user asked whether to keep a copy in the project and how to give it to other users, 2026-11-14. A project skill in `.claude/skills/` would not load from the app repo, where the skill runs: project skills load from the start folder and its parents up to the repository root, and personal skills win over project ones with the same name (https://code.claude.com/docs/en/skills, "Choose where skills load", "Resolve skills that share a name"). A plugin skill loads wherever the plugin is enabled, as `/plugin-name:skill-name` (same page).

**Alternatives.** Keep it personal only (not versioned, not shareable); a project copy beside the personal one (never loaded where it runs, and would drift).

**Evidence.** `claude plugin validate` passes on the plugin and the marketplace, with warnings only (no `version`, `author`, icon or marketplace description). From the app, `claude --plugin-dir ~/github/iterum/plugins/iterum` listed `/iterum:fleet-plan`, and with no argument it asked for a feature and wrote nothing (the user's screenshot). The one private reference in the skill (`docs/.local-only/check-*.sh`) was replaced by the check style itself. Install: `claude plugin marketplace add <path or owner/repo>`, then `claude plugin install iterum@iterum` (https://code.claude.com/docs/en/plugins/publish.md).

**Affects.** `.claude-plugin/`, `plugins/iterum/`. `${CLAUDE_PLUGIN_ROOT}` is the plugin's install folder, not necessarily the Iterum checkout, so the skill keeps `ITERUM_HOME`.

## 2026-11-14: One task per file per night

**Decision.** In one night's queue, at most one task claims a given file. `/fleet-plan` puts chunks that share a file, or that depend on each other, into one plan as consecutive prompt steps on one branch; only chunks with no file in common become separate tasks. Nothing in `fleet/` enforces it.

**Context.** The user chose option (a), 2026-11-14. In the overnight rerun (`overnight-design.md` section 5c), two queued plans claimed the same file: the first finished and kept its claim until landing, so the second was refused inside the claim's 300 s and dead-lettered on its one attempt. And each task's branch starts from `--base`, so a dependent chunk would not see its parent's work until a person lands it in the morning.

**Alternatives.** (b) The same rule, also refused by `iterum add` when a queued task already declares one of a plan's files: the fallback if a hand-queued night collides. (c) Stacked branches, a dependent task starting from its parent's branch and taking over its claims: claim handover and a landing order for a problem not yet met.

**Evidence.** The rerun's `claim.refused` event (run `ede3e38e348d`, held by `cdbe66143945`, scratch database). Parallel chunks already needed disjoint files (`overnight-design.md` section 4). Not tested: a task started after the claim expires, then the first run's landing.

**Affects.** `~/.claude/skills/fleet-plan/SKILL.md` (Rule 2). A plan with several prompt steps runs them one after another, so less of a big feature runs in parallel.

## 2026-11-14: A dirty app tree before a task stops the worker

**Decision.** When a task names a repo (`iterum add --repo`) and that repo has uncommitted changes before the task starts, the worker stops and leaves the queue as it is; it does not fail the task. Settles the first open question of `overnight-design.md` section 5b. Not built yet (step 2 of that sketch).

**Context.** The user chose this, 2026-11-14. Tasks get one attempt by default, so failing the task would dead-letter it, and every later task would meet the same tree and dead-letter too: one stray edit would empty the night's queue.

**Alternatives.** Fail the task (above); clean the tree (would throw away someone's work).

**Evidence.** The worker already stops this way at the spend ceiling, leaving queued tasks queued (`fleet/worker.py`, `governor.headroom()`).

**Affects.** `fleet/worker.py`.

## 2026-11-13: `/fleet-plan` is a user-level skill; its plans go in a gitignored `plans/`

*Superseded in part by 2026-11-14, "`/fleet-plan` ships in this repo as the `iterum` plugin": the skill is no longer user-level; plans still go in `plans/`.*

**Decision.** `/fleet-plan` lives at `~/.claude/skills/fleet-plan/SKILL.md`, started from inside the app repo, with Iterum at `${ITERUM_HOME:-~/github/iterum}`. It writes each plan, dry plan, check script and plan document to `plans/<slug>/` in this repo, which is gitignored. Settles the first two open decisions in `overnight-design.md` section 6. The first version plans one chunk; a bigger feature gets a list of chunks and a question.

**Context.** The user chose both options, 2026-11-13. Personal skills load in every project on the machine (https://code.claude.com/docs/en/skills, "Choose where skills load"); `disable-model-invocation: true` keeps it to `/fleet-plan` only, and `$ARGUMENTS` carries the sentence (same page).

**Alternatives.** The skill in this repo, run from the Iterum folder with the app path as an argument; plans in `docs/.local-only/` (mixes generated plans with private notes) or in the app repo (its tree would carry them).

**Evidence.** First test, 2026-11-13, by the user in the app repo (session `f4ea394a`): `/fleet-plan make the notes better` read the repo, asked with AskUserQuestion (four one- or two-file improvements, model, cap), wrote nothing until the user approved its recommendation (tags as links to tag pages, Haiku, $0.10), then wrote `plans/tag-links/` (`Open questions: None`), showed the check failing on `main` and the dry run failing at step 3, and asked "Implement this feature?" without running anything billed. Its first cap options ($1, $2, $5) ignored past costs, so the skill now reads spend per run from the ledger before suggesting a model or cap.

**Affects.** `.gitignore`; nothing in `fleet/`.

## 2026-11-13: The merge gate accepts a run's own expired claim nobody has taken since

**Decision.** `land()` accepts a changed file whose claim has expired when the `claims` row still holds the landing run's id and the presented fence (`claim.expired_own()`); every other file still needs `require_claim()`. `merge.landed` lists such files under `expired`. No new fence is taken: the claim is released in the same transaction that lands, so nothing could present one. Supersedes in part the 2026-11-10 entry "The merge gate requires a live claim".

**Context.** The tag-pages landing (`22cee9881c5c`) was refused because its 300 s claim expired 5 minutes after a 9-second run; nothing renews a claim once a run ends. An overnight run landed in the morning would always be refused. `acquire()` replaces the row and `release()` deletes it, so an unchanged row means nobody claimed the file since.

**Alternatives.** Re-acquire under a new fence, then release it (proposed first; two extra events and no use for the fence); extend a finished run's claims to a long landing window (blocks other runs on those files until landed); a separate `iterum reclaim` command (one more morning step).

**Evidence.** Reproduced on a scratch database with `ITERUM_CLAIM_TTL=5`: refused. After the change: lands with `expired=["file:a.txt"]`; refused when another run took the file (fence 2), and when another run took and released it. `fleet.merge_drill` now expects the expired, no-successor case to land, refuses it under another run's id and after a take-and-release, and fails on the old code. The tag pages then landed as `cc81006`.

**Affects.** `fleet/claim.py`, `fleet/merge.py`, `fleet/merge_drill.py`. A run's paused process could still edit its branch after expiry; landing takes the branch as it is, as before.

## 2026-11-13: `--max-attempts` leaves out the fix loop's reruns

**Decision.** `fleet.recovery`'s attempt count for a step is its `step.proposed` events less the `fix.retry` events covering it, so `--max-attempts` limits restarts and `--fix-retries` limits the fix loop.

**Context.** With the defaults, `--fix-retries 2` reproposes the prompt and check steps twice, so a run that failed after its retries had 3 proposals and was halted without ever being resumed (reproduced, `work-completed.md`).

**Alternatives.** Leave it and document it (a halted run only needs `--force`, and nothing resumes runs by itself yet, but the overnight work would); count only process starts (the ledger has no per-process event to count). A run killed partway through a retry pass is undercounted by one for the steps that pass did not reach.

**Evidence.** `work-completed.md`, 2026-11-13.

**Affects.** `fleet/recovery.py`, `resume_is_safe()`.

## 2026-11-13: The fix loop is opt-in, feeds back 2,000 characters, and counts retries per process

**Decision.** `fleet.run --fix-retries N` (default 0): when a step after a prompt step fails, the last prompt step before it reruns with the failing step's error (last 2,000 characters) appended, then every step after it. Each attempt is logged (`step.failed`, `fix.retry`); the run fails as before once retries run out. Each retry gets the full per-step cap and passes the ceiling check like any step. Retries count per process.

**Context.** The user chose the fix loop as the first overnight increment (`overnight-design.md` section 5). The design left open how many retries, the cap per retry and trimming (section 6).

**Alternatives.** On by default (a plan would start spending on retries without being asked); counting retries across resumes from `fix.retry` events (more code, and a resume is already a person's decision); feeding back the whole error (the merge gate already trims to 2,000).

**Evidence.** Free test with a fake `claude` that writes broken code until the prompt carries the check's error: fails without the flag; with `--fix-retries 2`, one retry, then `done`; a fake that never fixes fails after two `fix.retry` events. The built-in plan still runs. `work-completed.md`, 2026-11-13.

**Affects.** `fleet/run.py`, `fleet/replay.py` (refuses `fix.retry` runs through its allow-list).

## 2026-11-13: Report pages carry one inline script

**Decision.** Report pages include one fixed inline script for sortable tables and instant chart tooltips. It is a constant in `fleet/report_html.py` with no ledger data in it; it reads only the page's already-escaped DOM, fetches nothing and stores nothing. Pages stay self-contained and offline, and work unchanged with scripts off. Supersedes "no scripts" in the entry "A day's report is a static page beside the database" below.

**Context.** The user asked for interactivity among four ways to make the reports richer (2026-11-13), after Iterum's look, links between pages and a richer layout.

**Alternatives.** No script (the earlier rule: no sorting, native tooltips only); a script from a CDN (a network request per view, and code not in this repo); a theme toggle as well (built, then dropped: the page already follows the system setting, and the toggle was the only part that stored anything).

**Evidence.** `reporting-plan.md`, "Making the reports look like Iterum", step 4.

**Affects.** `fleet/report_html.py`.

## 2026-11-13: No report on a day with no activity; older runs count on the day they change

**Decision.** When a day has no activity (no runs started, no events on older runs, no spend, nothing landed or refused, and for today nothing needing a person), `iterum report` writes no page or PDF: it says so on stderr, with the dates the ledger covers ("no activity recorded on 2026-11-10; the ledger has events from 2026-11-06 to 2026-11-13; no report written"), and exits 0; `--json` still prints the empty data with the same message. A run started on an earlier day that logs events on this one (a halt, a resume) is listed under "Earlier runs with activity". Supersedes the one-line "Nothing happened" page in the entry below.

**Context.** The user, 2026-11-13: the report "should also tell the user when there is no data for the day", "and not generate a report if there is nothing". Today's report had read "Nothing happened" although two runs were halted that morning: runs were listed only on the day they started.

**Alternatives.** A one-line page (the earlier behavior: the empty file looks like a report until opened); exit 1 on an empty day (it is not a failure).

**Evidence.** 2026-11-10 on the real database wrote no file, even with `--pdf`, and printed the span; an empty ledger says so; today's report lists the two `run.halted` runs; the 2026-11-12 page is unchanged apart from its generated time; a run backdated a day and resumed twice shows `step.proposed ×4, step.failed ×3`.

**Affects.** `fleet/report.py`, `fleet/report_html.py`, `reporting-plan.md`, `CLAUDE.md`.

## 2026-11-13: A day's report is a static page beside the database

**Decision.** `iterum report` writes one self-contained HTML page for a day (option A of the open question "What should Iterum's reports look like, and where?"): inline CSS and SVG, no scripts, every ledger value through `html.escape`. It goes to `reports/report-<date>.html` in the database's folder (`~/.local/share/iterum/reports/` by default), with `--out` to put it elsewhere and `--json` for the data. A run belongs to the day it started. "Needs a person" lists merges refused that day, and only in today's report the current dead runs, pending approvals and conflicts. It stays a command; `fleet.run` does not write it. The open question keeps B to E and automatic writing.

**Context.** `reporting-plan.md`, increments 1 and 2. The location was the plan's recommendation; the user went ahead without choosing another ("do next").

**Alternatives.** The current folder (a report lands in whichever repo you ran it from); counting a run on every day it had events (the same run in two reports); showing current state in every report (built first: a past day with no activity showed today's failed run under "Needs a person", so an empty day never read as empty).

**Evidence.** Increment 2's checks, 2026-11-13: the 2026-11-12 page's tiles, 38 run rows, 9 landed merges and 10 spend segments equal `--json`; a step intent `<script>alert(1)</script>` and a plan `<i>evil.json` render as text, with no `<script>` element in any page; 2026-01-01 reads "Nothing happened"; in Chrome, light and dark render, and at 390 px no page scrolls sideways.

**Affects.** `fleet/report.py`, `fleet/report_html.py`, `reporting-plan.md`, `open-questions.md`.

## 2026-11-13: The default database lives in the XDG data folder

**Decision.** Without `ITERUM_DB`, the database is `$XDG_DATA_HOME/iterum/agent.db`, or `~/.local/share/iterum/agent.db` when `XDG_DATA_HOME` is unset or empty. `ITERUM_DB` still wins. The existing `<iterum>/agent.db` moves there once, while nothing has it open, so no `ITERUM_DB` is needed afterwards. A command that finds no database creates it (and its folder), as `db.init()` does today; `iterum status` still refuses a missing one. Settles the open question "Where should the default database live?" (`cli-plan.md` increment 4).

**Context.** The default was `agent.db` in the current folder, so `iterum` run in the app repo without `ITERUM_DB` would quietly create a second, empty database there.

**Alternatives.** `~/.iterum/agent.db` (the plan's proposal; shorter, but a new dot-folder outside any convention); `~/Library/Application Support/iterum` (macOS-only, a path with a space); the iterum checkout (no move, but data in the source tree, and wrong for a non-editable install); keeping `ITERUM_DB` in the shell profile instead of moving the file.

**Evidence.** The XDG base directory spec: user data goes in `$XDG_DATA_HOME`, and "If $XDG_DATA_HOME is either not set or empty, a default equal to $HOME/.local/share should be used" ([spec](https://specifications.freedesktop.org/basedir-spec/latest/)). uv already keeps its tools under `~/.local/share/uv` on this machine. The real `agent.db` had no `-wal`/`-shm` files while nothing held it open (2026-11-13), so a move needs only the main file then.

**Affects.** `fleet/db.py`, `fleet/doctor.py`, `cli-plan.md` increment 4; README and `CLAUDE.md` (increment 5); the `ITERUM_DB=<iterum>/agent.db` setup in `nextjs-first-run.md` becomes optional.

## 2026-11-13: A failed run needs a person until it is resumed or halted

**Decision.** `iterum status` keeps counting every `failed` run as needing a person (exit 1), with no time window. A person closes one with `fleet.recovery halt <run_id> "<reason>"`, which calls the existing `recovery.halt()` (status `halted`, `run.halted` event with the reason) and refuses any run `dead_runs()` does not list, so never a `done` or live run.

**Context.** The first `status` slice exited 1 on the real `agent.db` for two failed runs from 2026-11-12, and would have forever: `dead_runs()` returns every failed run.

**Alternatives.** Count a failed run only within a recent window (say 24 hours): needs no new command, but a failure nobody read drops out of view by itself, the wrong default for unattended runs (`overnight-design.md`).

**Evidence.** Scratch databases, 2026-11-13: halting a failed run moved `status` from exit 1 to 0 and logged `run.halted` (stage `validation`) with the reason; resume then refused without `--force` and resumed with it; halt refused a `done` run, a run with a fresh heartbeat and an unknown id, changing no row and no event; `fleet.recovery` with no arguments still listed a failed run and halted it at 3 attempts.

**Affects.** `fleet/recovery.py`, `CLAUDE.md`, `cli-plan.md`.

## 2026-11-13: Iterum ships as one `iterum` command

**Decision.** Option (a) of the open question "Should Iterum ship as one `iterum` command instead of `python -m fleet.*`?": a packaged CLI. `pyproject.toml` builds `fleet` with `uv_build` as a namespace package and defines `[project.scripts] iterum = "fleet.cli:main"`; it is installed once with `uv tool install --editable .`. `fleet/cli.py` maps one word per command to a module and runs it with `runpy.run_module(..., run_name="__main__")`, so no module changes; it line-buffers stdout and stderr in place of `-u`. `python -m fleet.*` keeps working. The rest of the question moves into `cli-plan.md`: a plain `iterum status` (increment 2) before any Rich dependency, and where the fixed default database lives (increment 4). Removed from `open-questions.md`.

**Context.** Every command needed `uv run python -u -m fleet.<module>`, and a run from the app repo also needed `PYTHONPATH`, `--project` and an absolute `ITERUM_DB` (`nextjs-first-run.md`).

**Alternatives.** (b) the same with a Rich dashboard: Iterum's first dependency, deferred to after a plain `iterum status`. (c) a Textual TUI: set aside 2026-11-13. (d) keep `python -m` and document it better: keeps every piece of setup.

**Evidence.** `cli-plan.md` increment 1's six checks, 2026-11-13, through the installed tool (`~/.local/bin/iterum`), each on a scratch `ITERUM_DB`. 1: `iterum <cmd> --help` reaches each argparse module's own help. 2: `iterum drill merge|claims|kill`, run in parallel from a folder outside the repo, passed with no FAIL line. 3: `iterum drill run` committed 6 of 6 steps (from the repo root: the built-in plan's step 2 is `ls fleet`, which fails from any other folder, under `python -m` too); `iterum resume` of a killed run skipped 3 committed steps and finished. 4: SIGINT and SIGTERM during step 4 gave returncode -2 under `iterum`, the same as `.venv/bin/python -u -m fleet.run` (through `uv run` the baseline reads 130, uv's own exit), and the last committed step line reached the piped file. 5: `uv run python -m fleet.<module>` still starts every module. 6: the hook command `gate_settings()` builds under the tool's Python refused an edit to a file another run had claimed (exit 2) and allowed an unclaimed one (exit 0).

**Affects.** `pyproject.toml`, `fleet/cli.py`; `cli-plan.md`; README and `CLAUDE.md` wait for increment 5.

## 2026-11-12: Concurrent runs may each pass the ceiling by one step; accepted, not reserved

**Decision.** Keep the spend ceiling as it is: a headroom check reserves nothing, so each run that checks at the same moment can pass the ceiling by one step's spend. Stated in `fleet/governor.py` and `CLAUDE.md`. Settles the open question "Can concurrent runs share one spend ceiling?"

**Context.** `stop_at_ceiling()` in `fleet/run.py` reads `governor.headroom()` and starts the step; shell and prompt steps both go through it. The ceiling was already soft: one run can pass it by one step's spend, and spend `fleet.telemetry` never received is not counted.

**Alternatives.** Reserve each step's cap in a table under `BEGIN IMMEDIATE` and release it when the step ends: closes the gap on one machine, at the cost of new mutable state, a release on every exit path, and cleanup of reservations a killed run leaves; it does nothing across devices, since `budgets` is per machine. Rely on a limit the biller enforces in the Anthropic Console: would cover every device, but what it offers and whether it applies to Claude Code sessions is not checked.

**Evidence.** Reproduced on a scratch database, nothing billed: ceiling $0.03 with $0.02 spent, each step logging a fake $0.02. One run passed the ceiling by $0.01 and stopped before step 2; two runs started together both started step 1 (proposed 5 ms apart) and passed it by $0.03, in 4 of 4 tries. The bound is one step's spend per concurrent run; with the $0.05 caps used in recent runs, two runs could pass by about $0.10, while the real Haiku steps of 2026-11-12 cost $0.001 to $0.002 each.

**Revisit when.** Paid runs routinely overlap near the ceiling, more than two run at once, or step caps grow large (Opus steps). Then reservation, or a checked biller limit, comes first.

**Affects.** `fleet/governor.py` (docstring), `CLAUDE.md`; no behavior change.

## 2026-11-12: No more runs just to find an unstaged `--check` refusal

**Decision.** Stop planning feature runs whose purpose is to catch `fleet.merge --check` refusing a branch nobody broke on purpose. Every landing still uses `--check`, and a refusal is recorded when one comes (`todo.md` item 1).

**Context.** The staged refusal (`nextjs-first-run.md`) showed `--check` refuse a merged tree that does not build, keep the claim, leave `main` alone, and land the fixed branch under the same fence. What was left was seeing it happen without staging.

**Alternatives.** Keep running billed features until one breaks a merge: each costs little (about $0.001 to $0.002 on Haiku), but nothing says when, or whether, one will.

**Evidence.** Five Haiku runs on 2026-11-12 (home-page copy, links, one About link, and a concurrent pair where one run read a file the other changed), each a narrow edit with an output check, all landed with `--check` on the first try (`nextjs-first-run.md`).

**Affects.** `todo.md` item 1; no code.

## 2026-11-12: Prompt steps run with `--restricted`

**Decision.** `CLAUDE_TOOLS` in `fleet/run.py` adds `--restricted`. A prompt step's file tools are confined to its working directory, and the session ignores user, project and local settings files; `--settings`, which carries the gate hook, still applies. Settles the open question "Should prompt steps run with `--restricted`?" and supersedes the "default `claude -p`" part of the 2026-11-10 entry "How `claude_step()` will be wired into `fleet.run`".

**Context.** `claude --help` (2.1.322): `--restricted` "ignores user, project and local settings files (managed settings and --settings still apply...)" and "confines the file tools to the working directories". Default `-p` loads the user's and the project's settings, so a repo's own `.claude/settings.json` could widen where a prompt step may write.

**Alternatives.** Keep default `-p` (the 2026-11-10 choice), so a prompt step loads the user's setup like an interactive session. In every case tried it also stayed inside the repo, so the flag guards against a case not yet seen.

**Evidence.** Six Haiku sessions outside `fleet`, with `claude_step()`'s flags and gate settings, in a scratch repo where another run held `file:held.txt` ($0.0052, not in the ledger):

| Session | Default `-p` | `--restricted` |
| --- | --- | --- |
| Edit the claimed `held.txt`, then the unclaimed `free.txt` | not run here; the gate refused a claimed file in the 2026-11-11 paid run | gate refused `held.txt` (its message reached the model), `free.txt` edited |
| Write a file in a sibling directory outside the repo | denied: "Path is outside allowed working directories" | denied: "--restricted confines the file tools to the working directory" |
| Edit an outside `.env.example` named by the user settings' `Edit(**/.env*.example)` allow rule | denied, same message | not run |
| Write outside, with the repo's `.claude/settings.json` adding that folder to `additionalDirectories` | denied; stderr: "Ignoring 1 permissions.additionalDirectories entry ... this workspace has not been trusted" | denied |

After the change, a `fleet.run` plan in the scratch repo (run `f682a2441f4c`, Haiku, cap $0.05) committed a prompt step that edited its one claimed file and a check step: $0.00054, 3 turns, no denials. The three drills and the built-in plan pass.

**Not shown.** A trusted workspace whose project settings add a directory: default `-p`'s warning implies it would apply it, which is what `--restricted` removes. Whether the `.env.example` rule could match outside the repo (a pattern without `/` or `//` is likely relative to the working directory; not checked against the docs). (Telemetry under `--restricted` was shown the same day: run `12c0572d5ec1`'s `spend.reported` events equal its `claude.finished` cost, `nextjs-first-run.md`.)

**Affects.** `fleet/run.py` (`CLAUDE_TOOLS`), `CLAUDE.md`, `claude-step-design.md` section 5.

## 2026-11-12: Prompt steps stay bare; a docs hint names files, and only for a known change

**Decision.** Prompts in a plan carry no general "read the docs" hint. When a task touches an API known to have changed, the prompt names the doc files that state the rule (for the notes task, `dynamicParams.md` and `generate-static-params.md` under `node_modules/next/dist/docs/01-app/03-api-reference/`). Otherwise the build step and `fleet.merge --check` catch the mistake, and the failed step is rerun. Settles the open question "Should prompt steps tell the model to read the app's docs?"

**Context.** Prompt steps do not see the app's `AGENTS.md` (`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `nextjs-first-run.md`), so a hint can only go in the prompt. On a dynamic route under Cache Components, Opus without a hint added `dynamicParams` and failed the build in 2 of 3 runs (eleventh run); with a general hint it passed 5 of 5 (twelfth run). Haiku passed 3 of 3 without one.

**Alternatives.** A general hint in every prompt: 5/5, but about $0.37 a run against $0.05, and about 39,000 cache-write tokens against 2,000, which fits reading many of the 475 bundled doc files (inferred; the ledger does not record files read). A paid sweep of a file-naming hint: would show it cheaper, but only for a trap already known, and would use most of the $0.62 left under the ceiling.

**Evidence.** Both failures were caught by the build at about $0.05 each, so three bare tries cost less than one hinted run. The two rules Opus broke sit in two files of about 20 KB together, against 3.4 MB of bundled docs (measured 2026-11-12). Thin: a 3-run baseline, one task, one app.

**Revisit when.** A model mistake gets past the build and `--check`, as the dry run's unawaited `params` got past the build and was caught only by the output check. Then a failure costs more than a rerun and a hint may pay.

**Affects.** Plans with prompt steps; no code.

## 2026-11-12: Replay drives the real harness code, and refuses what it cannot reproduce

**Decision.** `fleet.replay` runs the real `fleet.run` and queue code against a scratch database, with each side effect replaced by the recorded outcome. It never calls a model or a command. A regression case expects the end state its run actually reached; a capability case's expect is written by hand and never fails the suite. A run with events replay cannot reproduce is refused rather than approximated. `fleet.scorecard` compares git revisions, each scored in a temporary worktree by its own `fleet.eval --json`.

**Context.** The first draft folded events through a `harness_fn` defined inside `replay.py`, so a stored case could only fail if that function changed: bugs in `fleet.run` or the queue could not turn it red.

**Alternatives.** Keep the event fold (tests nothing outside itself). Re-sample the model (nondeterministic and billed; that is a separate tool, the model sweep). Approximate unsupported events (a case that passes because it skipped the hard part).

**Evidence.** The deliberate breaks listed in `work-completed.md` (2026-11-12) each turned a case red; the first draft's suite could not.

**Affects.** `fleet/run.py` (`do_step`), `fleet/worker.py` (`work`), `fleet/queue.py` (`max_attempts` on `task.added`), `fleet/replay.py`, `fleet/eval.py`, `fleet/scorecard.py`.

## 2026-11-11: Claim refusals name the holder's run id; agent names stay

**Decision.** `claim.acquire()`'s refusal and `fleet/gate.py`'s message name the holder's run id after its agent, as in "`file:a.txt` held by worker-1 (run 813631d110df) for another 300s", and the `claim.refused` event gains `held_by_run`. `fleet.run` still names every run's agent `worker-1`. Settles the open question "Should `fleet.run` give each run its own agent name?"

**Context.** That question was to be settled by whether concurrent runs became routine; the fifth and seventh Next.js runs each ran two at once. Reproduced on a scratch database: a second run of a plan was refused with "`file:a.txt` held by worker-1 for another 300s", the gate said "claimed by worker-1 until ...", and `claim.refused` carried only `held_by: worker-1`, while the `claims` row held the run id.

**Alternatives.** A distinct agent name per run, from a flag or `ITERUM_DEVICE`: changes what every event and claim records for an answer the run id already gives. Leave it: with two runs, the message cannot say which one holds the file.

**Evidence.** The same reproduction after the change: both messages name run `813631d110df`, and the event's `held_by_run` matches the `claims` row. No drill matches on the message text; the three drills pass.

**Affects.** `fleet/claim.py`, `fleet/gate.py`.

## 2026-11-11: `fleet.merge` gets an optional check on the merged tree

**Decision.** `fleet.merge --check "<command>"` runs the command in a temporary detached worktree of the merge commit, after `merge.started` and before the claims block; a failure logs `merge.refused` with `reason: "check failed"`, keeps the claims and leaves the target alone. The tree is always removed. Implemented the same day; design, test plan and results in `merge-check-design.md`. Settles the open question "Who builds the merged result?"

**Context.** Reproduced for free: two branches that each built landed through `fleet.merge` into a `main` that failed to build (`merge-check-design.md` section 0).

**Alternatives.** A plan-level setting passed on by `fleet.run`: changes the plan format before any plan needs it. A new event kind: adds nothing `merge.refused` lacks. Keeping the failed tree: the event and the merge commit's hash are enough. Building the target after landing: catches the break only once it is on `main`. Not running related changes at once: needs knowing in advance which changes are related.

**Evidence.** The reproduction; reading `fleet/merge.py` at `eeb7ccb`.

**Affects.** `fleet/merge.py`.

## 2026-11-11: Option B waits for an outside effect that cannot be checked first

**Decision.** Option A stands (`commit-once-design.md`). A plan step that changes files in the repo must be written to be safe to rerun: check before acting, as in `grep -qxF ... || echo ... >>`. Option B's trigger narrows from "a step that must not run twice" to a step with an effect outside the repo that cannot be checked before acting (a message, a charge). No plan has one yet.

**Context.** Four Next.js feature runs produced no step that must not run twice, so a changelog entry, ordinary release work that is not safe to repeat, was tried on purpose.

**Alternatives.** Build option B now for such steps: needs the settle command first (decision 3 in `commit-once-design.md`), and every kill would wait for a person, while a check in the command fixes this case for free. Leave the trigger as it was: it would count a step the plan can fix.

**Evidence.** `commit-once-design.md` section 6: killed mid-command and resumed, the plain append committed the entry twice and the run finished `done`; the guarded version committed it once. A rerun file change also shows up in the diff, which is reviewed before `fleet.merge` lands it; an outside effect does not. Not shown: a crash of `fleet.run` itself (the kill reached only the step), and any outside effect.

**Affects.** How plans are written; no code.

## 2026-11-11: Prompt steps keep the account email; git status and CLAUDE.md files are dropped

**Decision.** Accept that a prompt step's session sees the user's claude.ai account email. `claude_env()` sets `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1` and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, so the git status snapshot (with the git user name) and every CLAUDE.md file stay out of the session. Settles the open question "Should prompt steps keep the user's claude.ai account context?"

**Context.** The second Next.js run's transcript showed Claude Code adds a context block for a claude.ai login with `# userEmail` and `# gitStatus`, and the session also loaded the user's global CLAUDE.md. None of it is needed by a prompt step.

**Alternatives.** `IS_DEMO=1` or `--system-prompt`: tested, neither removes the email (below). `--bare` with an `ANTHROPIC_API_KEY`: probably removes it, since there is no claude.ai login, but untested, billed separately, and changes `claude_step()`'s auth. Leave the question open: nothing presses on it. Keeping CLAUDE.md files: a project's own CLAUDE.md might help a prompt step, but the prompt already names the change and its files.

**Evidence.** No page of the [env-vars](https://code.claude.com/docs/en/env-vars), [settings](https://code.claude.com/docs/en/settings), [CLI reference](https://code.claude.com/docs/en/cli-reference) or [headless](https://code.claude.com/docs/en/headless) docs mentions `userEmail`; `IS_DEMO` is documented only for "the header and `/status` output". Three billed one-turn Haiku sessions with `claude_step()`'s flags ($0.0015 in all), each transcript searched for the block: control, `IS_DEMO=1`, and `--system-prompt` all contained it. The env-vars page documents both variables set here (verbatim): `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS` "remove[s] built-in commit and PR workflow instructions and the git status snapshot from Claude's context"; `CLAUDE_CODE_DISABLE_CLAUDE_MDS` "prevent[s] loading any CLAUDE.md memory files into context". Not yet checked in a session: their effect (the three sessions ran outside a git repo, so no git snapshot appeared in any). Checked later the same day in the third Next.js run (`bec20a793b36`, inside a git repo): its transcript had no git status snapshot and no CLAUDE.md contents, and its first request's context was 5,466 tokens against 46,189 in the second run. Why the email is acceptable: prompt steps have no MCP tools and no shell (decision log, 2026-11-11), so the only way it leaves the machine is in a claimed file's diff, which `fleet.merge` lands only from a branch the user can review.

**Affects.** `fleet/run.py` (`claude_env()`). A prompt step no longer sees a project's CLAUDE.md or AGENTS.md conventions unless its prompt states them.

## 2026-11-11: Prompt steps get no MCP servers or tools

**Decision.** `CLAUDE_TOOLS` in `fleet/run.py` adds `--disallowedTools "mcp__*"` and `--strict-mcp-config` to `--tools Read,Edit,Write`, and `claude_env()` sets `ENABLE_CLAUDEAI_MCP_SERVERS=false`.

**Context.** The second Next.js run (`095cf7955377`, `nextjs-first-run.md`) was given `--tools Read,Edit,Write`, yet partway through, the session was told the user's claude.ai Gmail connector tools "just became available", and Haiku called `mcp__claude_ai_Gmail__list_labels` after writing "Now a type check". It was denied only because the tool needed approval and `--permission-prompts none` leaves no one to give it; `claude.finished` recorded the denial. `claude --help` (2.1.322) says `--tools` picks "from the built-in set"; the [CLI reference](https://code.claude.com/docs/en/cli-reference) says it does not affect MCP tools and that `--disallowedTools "mcp__*"` "removes every MCP tool". The [MCP docs](https://code.claude.com/docs/en/mcp) say claude.ai connectors load automatically for a claude.ai login, can arrive after a background retry, and are turned off by `ENABLE_CLAUDEAI_MCP_SERVERS=false` (read from a summarized fetch of the page, not verbatim).

**Alternatives.** Only `--disallowedTools "mcp__*"`: blocks the tools, but the first check showed 13 MCP servers still starting (the user's `supabase` and plugin servers, some connected), each a process with the user's credentials. Only the environment variable: covers claude.ai connectors, not user or plugin servers. `--restricted`: still an open question; it ignores user settings files but, per `--help`, needs `--strict-mcp-config` to skip MCP servers too. `--bare`: needs `ANTHROPIC_API_KEY` auth.

**Evidence.** Two billed Haiku checks with `claude_step()`'s exact flags and environment, `--max-turns 1`, asking for every tool name, read from the `stream-json` init message. Without `--strict-mcp-config` ($0.0012): tools `Edit, Read, Write`, 13 MCP servers in `mcp_servers`, none from claude.ai. With it ($0.0006): tools `Edit, Read, Write`, `mcp_servers` empty; Haiku listed the same three tools both times. One-turn sessions cannot show whether connectors would have arrived later; if they do, `--disallowedTools "mcp__*"` still removes their tools. Not yet checked: that the gate hook still runs with these flags (no edit was made). Checked later the same day (`claude-step-design.md` section 6, "Seen 2026-11-11, paid, gate under the new flags"): the hook refused an edit to a file claimed by another run.

**Affects.** `fleet/run.py`. The user's claude.ai account context (it included the user's email address) still reaches the session; see `open-questions.md`.

## 2026-11-11: Resume refuses a changed command, unless the step failed

**Decision.** `step.proposed` records a `command_hash` (the first 16 hex digits of a SHA-256 over the JSON of the shell string or the whole prompt object). `check_resumable()` refuses a resume when a recorded step's latest hash differs from the plan's command, unless that step's status is `failed`. Events logged before the hash existed carry none and are not checked.

**Context.** Resume compared intents only. Reproduced on a scratch database: a step `echo v1 > marker.txt && sleep 30`, killed mid-command, resumed without `--force` under the same intent with `echo v2 > marker.txt`, committed, and the run finished `done` with the marker reading `v2`; the ledger showed two identical `step.proposed` events. A first version refused any changed command, and `fleet.claims_drill` failed: its resume part fixes a failing step's command (`exit 1`) under the same intent, a workflow the repo supports.

**Alternatives.** Refuse every changed command and allow it with `--force`: `--force` also skips the live-heartbeat and live-process-group checks, which fixing a typo should not need. Check only committed steps: leaves the reproduced gap open, since the killed step was `proposed`. Store commands in `steps`: a schema change, where a hash in the existing event needs none.

**Evidence.** Seven cases on scratch databases: a killed step with a changed command, a committed step with a changed command, and a cut-off prompt step with a changed model are refused; the original plan resumes; a failed step with a fixed command resumes and runs it; a prompt step with its original plan reaches the existing `--force` refusal; a run with no hashes resumes. The three drills (`claims_drill` included) and the built-in plan pass.

**Affects.** `fleet/run.py`.

## 2026-11-11: `commit_once()` stays out of `fleet/run.py` for now

**Decision.** Option A in `commit-once-design.md`: `fleet/run.py` keeps its own write-ahead and resume rules, and `commit_once()` is not wired in. Option B, opt-in per step, waits for a plan with a step that must not run twice, and then needs the settle command first. `fleet/step.py` stays, unused. Next: catch a changed command on resume.

**Context.** Nothing calls `fleet/idem.py` or `fleet/step.py`. Through `commit_once()`, a shell step that is killed or exits non-zero has no category, so its receipt stays `in_flight` and resume halts until a person settles it, and no command does that yet. Today such a step reruns, which is safe for every current plan step. Prompt steps already need `--force`.

**Alternatives.** Every step through `commit_once()` (option C): every kill and failing command would need a person, and the built-in drill's kill-and-resume would halt. Opt-in per step now (option B): no plan needs it yet. Removing `fleet/step.py`: unused, but documented in this log and `todo.md`.

**Evidence.** Reading the code at `425cd63` (`commit-once-design.md` sections 1-3). `fleet.merge` already lands at most once: `git update-ref` with the expected old value, and `reconcile()` from `merge.started` (`fleet/merge.py`).

**Affects.** No code. The open questions that waited on wiring `commit_once()` in stay open; they matter again under option B.

## 2026-11-11: A run with prompt steps refuses to start when the ceiling could not see their spend

**Decision.** When a plan has prompt steps and a ceiling is set, `fleet.run` refuses to start or resume (`check_receiver()`) unless three things hold: `CLAUDE_CODE_ENABLE_TELEMETRY=1` and `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` are set in its environment; a GET to that endpoint answers; and the receiver's database, which `fleet.telemetry` now returns from `GET /v1/logs`, is the run's own (`db.DB.resolve()`). With no prompt steps or no ceiling, nothing is checked.

**Context.** `fleet/governor.py` counts only `spend.reported` events, which only `fleet.telemetry` writes. Reading `fleet/telemetry.py` and `claude_env()` showed two more ways to be blind besides a receiver that is down: the receiver writes to its own `ITERUM_DB`, which can differ from the run's; and `claude_env()` adds only `OTEL_RESOURCE_ATTRIBUTES`, so without the `.env.example` settings Claude Code exports nothing. The first paid run (`claude-step-design.md` section 6) worked only because those settings were sourced first.

**Alternatives.** Warn and run: the ceiling would stop counting without anyone noticing. Only check the port: misses both cases above. Send a zero-cost `api_request` through the receiver as an end-to-end probe: proves the whole path, but writes a permanent fake `spend.reported` event to the append-only ledger, which syncs. Count `claude.finished`'s `total_cost_usd` when no `spend.reported` arrived: it matched telemetry in one run, but a session killed mid-step logs no `claude.finished`, and mixing two sources risks counting a step twice.

**Evidence.** Tests on scratch databases with a fake `claude`: no ceiling and a shell-only plan run without settings; missing settings, a refused connection, and a receiver on another database are each refused with the fix; a receiver given the `/tmp/...` form of the run's `/private/tmp/...` path passes, since both sides compare resolved paths; a resume is refused the same way. The three drills and the built-in plan pass.

**Affects.** `fleet/run.py`, `fleet/telemetry.py`. Still missed: a receiver that dies, or a session that stops exporting, after the run starts.

## 2026-11-11: `claude_step()` details settled while implementing it

**Decision.** Five details beyond the 2026-11-10 entry below. (1) The session's tools are limited with `--tools Read,Edit,Write`, plus `--permission-mode acceptEdits` and `--permission-prompts none`. (2) The gate hook's `ITERUM_DB` (made absolute) and `FLEET_RUN_ID` go in the hook's own command, run with `fleet.run`'s Python. (3) Resume needs `--force` for a prompt step that is `failed`, not only `proposed`. (4) Every prompt step must declare at least one file. (5) A prompt step starts only if the fleet's headroom covers its whole cap; there is no `min(cap, headroom)`.

**Context.** `claude-step-design.md` section 5 proposed `--allowedTools Read,Edit,Write`. Whether a hook inherits Claude Code's environment is unverified. A `claude -p` session can fail after editing files. Without declared files, `gate.py` allows every edit and the run is not forced off `--target`.

**Alternatives.** (1) `--allowedTools`: per `claude --help` (2.1.322) it is a "list of tool names to allow", which pre-approves them but leaves every other tool, Bash included, in the session; `--tools` "Specify the list of available tools from the built-in set". `--restricted` would also confine file tools to the working directories but ignores user, project and local settings, against the 2026-11-10 choice of default `-p`; left as an open question. (2) Setting the variables in `claude`'s environment only. (5) Starting a step with headroom above zero and `--max-budget-usd min(cap, headroom)`: a session could run out of budget mid-edit, an ambiguous failure that needs `--force`.

**Evidence.** `claude --help`, Claude Code 2.1.322. The real `claude` accepted every flag and the `--settings` JSON with `--bare` and no `ANTHROPIC_API_KEY` (`"total_cost_usd": 0`, `"duration_api_ms": 0`); a bad `--permission-mode` and broken settings JSON were rejected, so the flags were parsed, not ignored. Fake-`claude` checks: `work-completed.md`, 2026-11-11.

**Affects.** `fleet/run.py`. Unverified until the paid run: what the flags do in a real session, and whether the hook runs in `-p` mode.

## 2026-11-11: The spend ceiling reads `spend.reported` events and halts a run before a step

**Decision.** `fleet/governor.py` has no counter of its own. A run's spend is the sum of `cost_usd` over `spend.reported` events whose `ts` is at or after the ceiling's `window_start`; `budgets` holds only the ceiling (`limit_usd`, `window_start`), and `spent_usd` is left unused. `fleet.run` checks `governor.headroom()` before proposing each step and, at or below zero, marks the run `budget_exhausted` and exits; a resume checks again. `fleet/rates.json` and `scripts/check-rates.py` were dropped (moved to the gitignored `docs/.local-only/rates/`).

**Context.** The first draft metered spend with `charge()` and priced tokens with `rates.json`. It wrote `runs.cost_usd`, which `db.finish_run()` resets to 0 at the end of every run (reproduced on a scratch database), and which the 2026-11-10 spend entry below had already rejected. `price()` returned `None` for full model IDs such as `claude-opus-5-5`, because `rates.json` was keyed by family.

**Alternatives.** A second counter in `budgets.spent_usd`: it does not sync, and can disagree with the ledger. Pricing tokens with `rates.json`: it misses cache writes and reads, Haiku 5.5's rate above 100,000 tokens, batch, fast mode, data residency and older model versions (`pricing.md`). Counting the `claude -p` envelope's `total_cost_usd` too: it would count the same requests twice. Killing a step when the ceiling is crossed: a killed `claude -p` session is an ambiguous failure that needs `--force` to resume (`claude-step-design.md` section 4).

**Evidence.** Scratch databases, 2026-11-11: spend before the ceiling was set is not counted, a repeated `request_id` is skipped, and a three-step shell plan whose second step recorded $1.50 against a $1.00 ceiling halted before step 3, halted again on resume, and finished after `fleet.governor set 5`. A run with no ceiling set was not affected. `fleet/sync.py` imports `ts` unchanged, so synced spend counts.

**Affects.** `fleet/governor.py`, `fleet/run.py`, `pricing.md`. Spend counts only while `fleet.telemetry` runs. A run can pass the ceiling by up to one step's spend (see `todo.md`, "Reserve each prompt step's cap against the ceiling").

## 2026-11-10: How `claude_step()` will be wired into `fleet.run`

**Decision.** The five decisions at the end of `claude-step-design.md`: a prompt step is `{"prompt": ...}` in a plan step's third field; resume refuses an uncommitted prompt step without `--force`; prompt steps need `--allow-claude` with a required `--max-budget-usd` and run with `--max-turns 10`; no `commit_once()` in the first version; default `claude -p` with `gate.py` via `--settings`, not `--bare`.

**Context.** Every call is billed to the user. A rerun prompt is billed again and may repeat edits. No command settles a stuck `in_flight` receipt yet. `--bare` skips settings hooks and accepts only `ANTHROPIC_API_KEY` (`claude --help`, Claude Code 2.1.322; https://code.claude.com/docs/en/headless).

**Alternatives.** A separate kind field; rerunning prompt steps like shell steps; a default budget; `commit_once()` now; `--bare`. Reasons in the note.

**Evidence.** `claude-step-design.md`; flags checked against `claude --help` and https://code.claude.com/docs/en/cli-reference. Not yet verified: `is_error` in the envelope, the gate hook under `--settings` in `-p` mode, a disallowed tool's behavior in `-p` mode.

**Affects.** `fleet/run.py` once implemented. Nothing changed yet.

**Superseded in part 2026-11-12** by "Prompt steps run with `--restricted`": the session is `claude -p --restricted`, not default `-p`.

**Update 2026-11-11.** `is_error` is now verified: a free failing run (`claude -p --bare` with no API key, Claude Code 2.1.322) printed `"is_error": true` alongside `"subtype": "success"` and exited 1. Details in `claude-step-design.md`. The other two items remain unverified.

## 2026-11-10: fleet.run prints dead runs when it starts; halting stays manual

**Decision.** For the open question "Who runs `fleet.recovery`?": every `fleet.run` start, fresh or `--resume`, calls `notice_dead_runs()` after `db.init()`. It lists each `running` run whose heartbeat is older than `ITERUM_IDLE_SECONDS`, counts `failed` runs without listing them, and prints the `fleet.recovery` command. It only reads; halting stays a manual `fleet.recovery` step.

**Context.** A SIGKILLed run stays `running` with nothing left to report it, and nothing ran `fleet.recovery`. `recovery.dead_runs()` returns every `failed` run however old, so listing them all would grow without bound; a failed run already reported itself when it exited.

**Alternatives.** Keep it manual: the gap stays. A scheduler (cron, launchd): something to install and keep alive per machine, needed only if dead runs must be noticed when nobody starts runs; can be added later. List failures from a recent window: a time limit with no evidence for any value.

**Evidence.** See the work-completed entry "Who runs `fleet.recovery`?".

**Affects.** `fleet/run.py`. One read query per start. `fleet.claims_drill` output now includes `1 failed run(s).` from its own scenarios.

## 2026-11-10: SIGTERM stops a run's step and a worker's task command

**Decision.** For the todo "Should SIGTERM stop a step's command?": yes. `fleet.run` and `fleet.worker` call `proc.stop_on_sigterm()`, which makes SIGTERM raise `KeyboardInterrupt` and so kill the command's process group as Ctrl-C does. The step or task is left as Ctrl-C leaves it (`proposed`, or `in_progress` with its lease) for a resume or a reap.

**Context.** Ctrl-C, a worker's early exit and a lost claim already kill the command; SIGTERM was the one stop that left it running. Supervisors stop processes with SIGTERM: `docker stop` sends SIGTERM, then SIGKILL after a grace period (https://docs.docker.com/reference/cli/docker/container/stop/). Not tested under any supervisor.

**Alternatives.** Leave SIGTERM alone: the command runs on, unsupervised, and a resume waits for it. A separate SIGTERM path: two cleanups to keep in step.

**Evidence.** See the work-completed entry "Should SIGTERM stop a step's command?".

**Affects.** `fleet/proc.py`, `fleet/run.py`, `fleet/worker.py`, both drills. Both processes now exit -2 (`KeyboardInterrupt` ends Python via SIGINT) instead of -15 on SIGTERM. SIGKILL still leaves the command running; the resume guard and `reap()` wait for it.

## 2026-11-10: A run that declares files must be on its own branch, not in a linked worktree

**Decision.** For merge-gate item 1 ("agents edit only in their own git worktrees"): `fleet.run` refuses a plan that declares files unless HEAD is on a branch other than the target. It does not check that the directory is a linked worktree, and it does not check plans that declare nothing.

**Context.** The harm is a run whose steps commit straight onto the target, skipping every claim check: reproduced with a declared plan run with `main` checked out. A run in a separate clone cannot do that harm: its branch is not in the shared repo, so `fleet.merge` cannot find it. The built-in drill runs from the repo root on `main` and declares nothing.

**Alternatives.** Require a linked worktree (`git rev-parse --git-dir` differs from `--git-common-dir`): adds a rule that guards against nothing the branch check misses. Check every plan: breaks `uv run python -u -m fleet.run` from the repo root.

**Evidence.** See the work-completed entry "Build the merge gate that checks fences", item 1.

**Affects.** `fleet/run.py` (`run_branch()`, `--target`), `fleet/claims_drill.py`. An agent can still write outside its worktree by other means; the `gate.py` hook is the only check there.

## 2026-11-10: A run renews its claims at half the TTL and stops its step when a renewal is refused

**Decision.** `fleet/run.py`'s heartbeat thread renews the run's claims once half of `CLAIM_TTL` (`ITERUM_CLAIM_TTL`, default 300 seconds) has passed since the last renewal, not on every 10-second beat. A refused renewal kills the running step's process group, and the step and run are marked `failed` with "claim lost". This implements the decision above that `renew()` refuses an expired claim.

**Context.** Renewing on every beat would write a `claim.renewed` event per claim every 10 seconds, the same kind of repeated event avoided for skipped reaps. A run whose claim was taken can no longer land, so letting its step carry on only edits files someone else now holds.

**Alternatives.** Renew every beat: 30 events per claim per 300 seconds instead of 2. Let the step finish and fail only at the merge: the step keeps writing to a file another run holds.

**Evidence.** See the work-completed entry "Wire claims into `fleet/run.py` and renew them".

**Affects.** `fleet/run.py`, `fleet/claim.py`. `ITERUM_CLAIM_TTL` must be several `HEARTBEAT`s (10 seconds), or a renewal can come too late. A process paused for less than the TTL keeps its claims.

## 2026-11-10: Landing a merge releases the claims it was given

**Decision.** For the open question "Who releases a run's claims after its branch lands?": `land()` releases every claim passed in `fences`, not only the changed files', in the same `db.write()` block as `merge.landed`, through a new `claim.release_in(con, ...)` (the body of `release()`). A refusal, conflict or moved target keeps the claims so the caller can retry. `merge.started` now records the fences, and `reconcile()` releases them when it settles a crashed merge as landed.

**Context.** After a run's branch landed, its claims stayed live and every later run on those files was refused for the rest of the 300-second lease. The merge process is the only place that knows a change landed; `fleet.run` finishes before the merge and may never see it.

**Alternatives.** The run releases its own claims: it would have to wait for or poll the merge. A separate release command: one more step to forget. Release only the changed files: a claimed but unchanged file stays held until expiry.

**Evidence.** Three new `fleet.merge_drill` checks failed on the old code (claims for `a.txt` and an unchanged `e.txt` still held after landing; the crashed merge's `b.txt` claim still held after `reconcile()`), while "conflict: claim still held" passed. After the change all 31 checks passed. The `fleet.run` end-to-end script showed no claims after its branch landed. Before this change the drill had 28 checks, not the 31 reported when it was added.

**Affects.** `fleet/claim.py`, `fleet/merge.py`, `fleet/merge_drill.py`. A run that keeps editing the same files after landing must `acquire()` again. A `merge.started` from before this change has no fences, and `reconcile()` releases nothing for it.

## 2026-11-10: A run declares its files in the plan and claims them all before any step

**Decision.** For merge-gate item 4: a plan step may carry a fourth field, a list of resources such as `"file:a.txt"`. `fleet.run` claims every resource in the plan, in sorted order, before any step runs, and again on resume. A refusal releases what it took, marks the run `failed`, and runs no step. A run that holds claims prints the `fleet.merge` command with its `--fence` flags when it finishes. Plans with three fields still work and claim nothing.

**Context.** A plan step is a shell command, and `claude_step()` (the only way a Claude edit could run through `fleet.run`) is billed and not wired in, so a hook that claims as the agent edits could not be tested without paying. The merge needs claims on every file the run changed, including committed steps, and a resumed process gets new fences by design.

**Alternatives.** Claim each step's files when it is proposed: a resume would still have to re-claim committed steps' files, and two runs could each hold a file the other needs next. Claim through the `gate.py` hook as the agent edits: a timed-out hook does not block, hook processes are short-lived so something else must renew, the fences must be stored for the merge, and a refusal mid-step leaves partial edits. It can come later, once `claude_step()` is wired in.

**Evidence.** On a scratch repo with an agent worktree: a two-step plan claimed `a.txt` and `b.txt`, committed both, and its printed flags landed through `fleet.merge`. With `b.txt` held by another run, a new run was refused with no steps and status `failed`, and its claim on `a.txt` was released. A run that failed at step 2 and was resumed went from fence 3 to 4; the merge refused fence 3 and landed with 4. The built-in drill plan still ran to `done`.

**Affects.** `fleet/run.py`. Claims are not renewed yet, so a run longer than 300 seconds loses them, and nothing releases them after landing (see `open-questions.md`).

## 2026-11-10: `renew()` will refuse an expired claim

**Decision.** For the open question "May `renew()` revive an expired claim?": no. `renew()` will match only an unexpired claim, so a holder that missed renewal must call `acquire()` again and gets a new fence. When the run's renewal is refused, the run stops its step and marks it `failed`. Not implemented yet; it comes with claim renewal in `fleet/run.py`.

**Context.** Renewal will run from `fleet/run.py`'s heartbeat thread. Reviving an expired claim is safe when nobody else took it, but it lets the `claims` table show an expired claim for a holder still about to write, which is what the stricter merge guard was chosen to rule out.

**Alternatives.** Leave `renew()` as it is: an expired holder skips `acquire()` and keeps its old fence.

**Evidence.** None yet beyond the 2026-11-10 test that showed an expired holder could renew and pass `require_claim()`.

**Affects.** `fleet/claim.py` and `fleet/run.py`, when renewal is built.

## 2026-11-10: The merge gate writes ahead, and reconcile() settles a crash on restart

**Decision.** For merge-gate item 3 (a crash during the update): `land()` logs `merge.started` (with a UUIDv7 `merge_id`, the old and new commits) in its own `db.write()` before the locked block. The locked block logs `merge.landed` or `merge.refused` as before. If `update-ref` fails, the block rolls back and `land()` logs `merge.abandoned` in a new write. `merge.reconcile(repo)`, run when the merge process starts, finds this device's `merge.started` events with no outcome and logs `merge.landed` (if the commit is an ancestor of the target) or `merge.abandoned`, both with `recovered: true`.

**Context.** `update-ref` runs inside the SQLite transaction so no newer fence can be issued between the check and the move. A crash after `update-ref` and before COMMIT moved the branch with no event: reproduced by `os._exit(9)` right after `update-ref`, which left `main` merged and the ledger with no `merge.*` events.

**Alternatives.** Commit SQLite first, then `update-ref` outside the lock: reopens the gap between the check and the move. Accept the gap and treat git as the only record: nothing reads `merge.*` events yet, but `fleet/project.py` would build wrong knowledge once something does. Pair events by commit hash: `commit-tree` timestamps to the second, and two crash runs built the same hash (`18c9637a0a73`). Reconcile at the start of every `land()`: two concurrent `land()` calls would mark each other's in-flight merge abandoned.

**Evidence.** Crash after `update-ref`, then `reconcile()`: `merge.landed` recovered, `main` merged. Crash before `update-ref`: `merge.abandoned` recovered, `main` unchanged. A second `reconcile()` logged nothing. The ten-case scratch script still passed, and its moved-target attempt logged `merge.abandoned` with git's `cannot lock ref` message, so nine `merge.started` events had nine outcomes (the conflict fails before the write-ahead).

**Affects.** `fleet/merge.py`. `reconcile()` assumes one merge process per device and must run before it lands anything. A failed `update-ref` still raises `CalledProcessError` to the caller.

## 2026-11-10: The merge gate requires a live claim, not just the current fence

*Superseded in part by "The merge gate accepts a run's own expired claim nobody has taken since" (2026-11-13): an expired claim with no successor now lands for its own run.*

**Decision.** For the open question "Should `claim.guard()` also require a live claim?": yes, but through a new `claim.require_claim()`, not by changing `guard()`. It calls `guard()` and then requires a `claims` row with the same resource and fence whose `expires_at` has not passed, and raises `Refused` otherwise. The merge gate calls `require_claim()`.

**Context.** With `guard()` alone, a holder that released its claim, or whose lease expired with no successor, can write until someone else claims the resource. The `claims` table then says nobody holds it while a write is still allowed, and a merge after `release()` (a bug) gets through. A holder that is refused can call `acquire()` again: if nobody else took the resource it gets a new fence and passes.

**Alternatives.** Keep `guard()` fence-only for the merge gate, which is the usual fencing-token check and needs no clock ([Kleppmann, "How to do distributed locking"](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)). It would not let two writers overlap, but it allows the two cases above. Put the claims check inside `guard()`: `fleet/queue.py` calls `guard()` on `task:<id>` fences and never writes `claims` rows (it checks `leases` in `_require_lease()`), so every worker would be refused.

**Evidence.** On a scratch database, before the change `guard()` accepted an expired holder with no successor and a released holder. After it, `require_claim()` refused both with `Refused`, accepted the live current holder and a holder that re-acquired after expiry (fence 1 to 2), and still refused a stale fence after takeover and a never-issued fence with `Fenced`.

**Affects.** `fleet/claim.py` and the merge gate in `todo.md`. `guard()` and the queue are unchanged. The merge process reads the clock to compare with `expires_at`. A slow holder that misses renewal is refused even when nobody else wants the resource. `renew()` can still revive an expired claim; see `open-questions.md`.

## 2026-11-10: The worker kills its command's group on any early exit

**Decision.** `_shell()` in `fleet/worker.py` kills the command's process group on any exception while it runs (`except BaseException`), not only a timeout.

**Context.** `_shell()` now calls `queue.record_pgid()`, which can raise `Fenced`, `Refused` or a busy `sqlite3.OperationalError` after the command has started. A command left running with no lease that knows its group is the overlap the fix removes. Ctrl-C is also an early exit.

**Alternatives.** List the exceptions (`TimeoutExpired`, `Fenced`, `Refused`): misses a busy database and Ctrl-C. Leave Ctrl-C alone: the command would run on with nothing waiting for it, as `fleet/run.py` did before its own Ctrl-C entry below.

**Evidence.** See the work-completed entry "A SIGKILLed worker's task command overlaps the rescuer's rerun", paragraph "Ctrl-C".

**Affects.** `fleet/worker.py`. SIGKILL and SIGTERM still leave the command running; `reap()` waits for those.

## 2026-11-10: The reaper waits for a dead worker's task command, default `do_work` only

**Decision.** For the todo "A SIGKILLed worker's task command overlaps the rescuer's rerun": only the default `do_work` records its process group on the lease. A worker module set with `FLEET_WORK_MODULE` must handle its own processes. When `reap()` skips an expired lease because its group is still alive, it prints a line and writes no ledger event.

**Context.** The overlap comes from `_shell()`, which only the default `do_work` uses. `reap()` runs every 5 seconds in every worker.

**Alternatives.** Cover every `do_work` by changing its contract, for example passing it a way to record a group id: no custom module exists to test it against. A ledger event per skipped reap: a 10-minute command would write about 120 identical events. One event per lease would need extra state to remember it was logged.

**Evidence.** See the work-completed entry "Does the worker leave a task's command running when SIGKILLed?".

**Affects.** `fleet/worker.py` (its docstring should name the limit), `fleet/queue.py`. While `reap()` waits, why the task is still `in_progress` shows only in the reaping worker's output; the ledger shows the wait as a longer gap between `task.claimed` and `task.reaped`.

## 2026-11-10: Ctrl-C kills the step's process group

**Decision.** `shell()` in `fleet/run.py` catches `KeyboardInterrupt` while waiting on a step, kills the step's process group with `os.killpg(pgid, SIGKILL)` and re-raises.

**Context.** Running each step in its own group (next entry down) took the command out of the terminal's foreground process group, so Ctrl-C stopped `run.py` but left the command running, unlike before.

**Alternatives.** Leave it, and let the resume guard wait for the command: Ctrl-C would no longer stop what it visibly stopped before. SIGTERM to the group instead of SIGKILL: gives the command a chance to clean up, but `fleet/worker.py` already uses SIGKILL on a timeout, and one rule is simpler.

**Evidence.** See the work-completed entry "A killed run.py leaves its step's command running", paragraph "Ctrl-C".

**Affects.** `fleet/run.py`. Covers Ctrl-C only; SIGTERM and SIGKILL still leave the command running, and the resume guard covers those.

## 2026-11-10: `--resume` refuses while a step's process group is alive

**Decision.** `fleet/run.py` runs each step's command in its own process group, stores the group id in `steps.pgid`, and `check_resumable()` refuses (unless `--force`) while an uncommitted step's group has any process left.

**Context.** A SIGKILLed `run.py` leaves its step's command running. The heartbeat check does not help once the command keeps running past the expiry: a resume then ran the step a second time alongside it.

**Alternatives.** Kill the leftover group on resume: a stored group id can be reused by an unrelated process, and killing it would be wrong; a refusal only costs a wait or `--force`. Longer expiry: any fixed value is beaten by a long enough step. The worker's approach (kill the group on timeout, from the worker): the dying process cannot run it.

**Evidence.** See the work-completed entry "A killed run.py leaves its step's command running".

**Affects.** `fleet/run.py`, `fleet/schema.sql`, `fleet/db.py`, `CLAUDE.md`. A kill between starting the command and writing `pgid` leaves no group to check; that window is one SQLite write. Ctrl-C no longer reaches the command on its own; see the next entry up. `os.killpg` is POSIX only.

## 2026-11-10: `--resume` treats a fresh heartbeat as a live run

**Decision.** `check_resumable()` refuses a `running` run whose `heartbeat_at` is younger than `recovery.IDLE_SECONDS` (`ITERUM_IDLE_SECONDS`, default 60). `--force` overrides it.

**Context.** `--resume` checked only the status, so it started a second `run.py` on a run whose first process was still alive, and both ran the remaining steps.

**Alternatives.** A separate expiry for resume: two numbers that mean "dead" could disagree, so `fleet.recovery` would list a run that `--resume` refuses, or the reverse. No override: a person who knows the process is gone would have to wait out the expiry; `--force` already means "a human has looked" for `halted` runs.

**Evidence.** See the work-completed entry "`--resume` refuses a run that may still be alive" for before and after runs on scratch databases.

**Affects.** `fleet/run.py`, `CLAUDE.md`. `run.py` now imports `fleet.recovery`. A run without a heartbeat is not checked. Note `fleet.recovery --idle-seconds` changes only recovery's cutoff; resume reads the environment variable.

## 2026-11-10: Claude Code exports telemetry logs every second

**Decision.** `.env.example` sets `OTEL_LOGS_EXPORT_INTERVAL=1000`, down from the documented default of 5000 ms.

**Context.** Claude Code buffers events between exports. A session killed with SIGKILL loses every `api_request` that finished since the last export, so `fleet/telemetry.py` never sees that spend.

**Alternatives.** Keep the default: in the test below it lost two of three requests. Go below one second: one second already lost nothing in the test, and each step down adds POSTs for no measured gain.

**Evidence.** Two runs against `fleet.telemetry` on a scratch database, each a Haiku session killed at 10 s after three completed requests (by `requestId` in its transcript). At 5000 ms, 1 of 3 arrived; at 1000 ms, 3 of 3. One run per setting.

**Affects.** `.env.example`, `docs/telemetry/claude-code-telemetry.md`. A busy session sends at most one small POST per second to the local receiver. A request in flight at the kill is still unrecorded.

## 2026-11-10: Spend events are `spend.reported`, stage `governance`

**Decision.** `fleet/telemetry.py` logs each Claude Code `api_request` as kind `spend.reported` with stage `governance`. The payload keeps `request_id`, `model`, `cost_usd`, the token counts, `duration_ms` and `session_id`. The `run_id` is `iterum.run_id`, or `session-<session.id>` when that is missing. A `request_id` already in the ledger is skipped, checked with `json_extract` inside the same `db.write()`.

**Context.** The earlier entry today chose ledger events for spend but left the kind, the stage and the receiver open.

**Alternatives.** Kind `claude.api_request`: every other kind is a noun and a past-tense verb (`run.started`, `step.committed`, `task.reaped`), and it named the source rather than what happened. Stage `scheduling`: it is queue bookkeeping, used only in `fleet/queue.py`. Stage `governance` already names the hooks and approvals layer in `fleet/doctor.py`, and is not in `STAGES`, so `fleet.view stages` does not count spend as a failure.

**Evidence.** A synthetic OTLP body posted twice to `fleet.telemetry` on a scratch database wrote two events and skipped the duplicate and the repeat; the `user_prompt` record and a fake `user.email` were not stored, and a string `intValue` was read as a number. A real `claude -p` session on Haiku sent three requests, which became three `spend.reported` events under `iterum.run_id`. `fleet.view trace` shows them; `fleet.view stages` leaves them out.

**Affects.** `fleet/telemetry.py`, `.env.example`, `docs/telemetry/claude-code-telemetry.md`. The dedupe query scans every `spend.reported` event; add an index if it gets slow.

## 2026-11-10: Claude Code spend lands in the ledger, one event per API request

**Decision.** Spend is recorded as ledger events, one per Claude Code `claude_code.api_request` telemetry event. Each event's `run_id` comes from a custom resource attribute, `iterum.run_id`, which `fleet` sets through `OTEL_RESOURCE_ATTRIBUTES` when it starts a session. Sessions `fleet` did not start fall back to `session.id`. The ledger event keeps `request_id`, `cost_usd`, `model` and token counts, and drops `user.email`, `user.id`, `user.account_uuid`, `user.account_id` and `organization.id`. `request_id` is the dedupe key. The `claude_code.cost.usage` metric is not imported. `runs.cost_usd` is not written.

**Context.** `runs.cost_usd` was always 0 because nothing passed a cost to `db.finish_run()`. Claude Code exports cost as OpenTelemetry metrics and events (https://code.claude.com/docs/en/monitoring-usage). The `cost_usd` field is described there as "Estimated cost in USD", so these figures compare agents and are not billing.

**Alternatives.** Update `runs.cost_usd`: `runs` is local to one machine and never synced, so spend would stay on the device that recorded it, and an update keeps no history. Import the `cost.usage` metric: it is a cumulative counter per session, the wrong shape for an append-only ledger, and the events already sum to it.

**Evidence.** Two `claude -p` sessions on Haiku, Claude Code 2.1.322, with console exporters and `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<id>`. `iterum.run_id` and `session.id` were on every event and metric datapoint. The four-request session produced four `api_request` events with four distinct `request_id`s; their `cost_usd` summed to 0.00541548, equal to the final `cost.usage` value. `cost_usd_micros` is rounded per request (4125 for 0.00412534), so `cost_usd` is stored instead. The five identity fields were on every record. A third session with `OTEL_LOGS_EXPORTER=otlp`, `OTEL_METRICS_EXPORTER=none`, `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json` and `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:14318/v1/logs` posted three `application/json` requests to `/v1/logs`, received by a standard-library `http.server`; the `api_request` record carried `iterum.run_id`, `request_id`, `cost_usd` (`doubleValue`) and the token counts (`intValue`).

**Affects.** A receiver in `fleet` (not written yet) that takes OTLP logs as `http/json` with the standard library alone, and `claude_step()` when it is wired in. Not yet tested: a session using more than one model, and how much a killed session loses before export.

## 2026-11-10: Queue failures are tagged with the stage where they happened

**Decision.** `_spend_attempt()` always logs the cause of a spent attempt in its own stage: `task.failed` as `tool_execution`, `task.reaped` as `coordination`. When no attempts are left, `task.dead_lettered` follows as `scheduling`. `fleet/view.py` counts `failed`, `halted`, `dead_letter`, `refused` and `reaped` kinds as failures.

**Context.** Every queue event was tagged `scheduling`, which is outside the seven failure stages, so `view stages` never saw a queue failure. On the last attempt only `task.dead_lettered` was logged, so the cause was lost. `trace()` did not count `reaped`, so it named `scheduling` as the failing stage.

**Alternatives.** Retag only, keeping one event per attempt: the last attempt would still lose its cause. Add `scheduling` to the failure stages: it records consequences, and counting them would make one failure show up twice. Tag `task.reaped` as `tool_execution`: a dead worker needs a different fix from a failing command, and a reap is the lease system's call, the same family as a refused claim.

**Evidence.** On scratch databases, before: a task failing its only attempt logged `task.claimed` then `task.dead_lettered`, both `scheduling`. After: `task.failed` (`tool_execution`) then `task.dead_lettered`; `view stages` shows 3 of 3 failures under `tool_execution`. A reaped task shows `task.reaped` as `coordination`, and `view trace` reports `FAILED AT STAGE: coordination`. `fleet.kill_drill` passes unchanged.

**Affects.** `fleet/queue.py`, `fleet/view.py`. A final failure now writes one more event. Events already in a ledger keep their old `scheduling` tag, since `events` is append-only.

## 2026-11-09: Conflicts wait on the queue for a person

**Decision.** `tasks.result` keeps what `do_work` returns. `claim()` skips tasks of kind `resolve_conflict`, and only `queue.resolve()`, reached through `fleet.conflicts`, closes them. Tasks that depend on a conflict wait until a person settles it.

**Context.** The worker discarded `do_work`'s return value, so there was nothing to compare. A `resolve_conflict` task was claimed like any other: under the default worker it failed three times on a missing `cmd` and was dead-lettered, so it never reached a person.

**Alternatives.** A separate table for human work: more schema for what is still a task with a status. Keeping results only in the ledger: events sync to every device and results can be large. A list of kinds for `claim()` to skip: only one kind exists.

**Evidence.** Tested on throwaway databases: a worker leaves the task `ready`, `resolve` closes it and logs `task.resolved`, and its dependent then runs.

**Affects.** `fleet/queue.py`, `fleet/worker.py`, `fleet/conflicts.py`, `fleet/schema.sql`, `fleet/db.py`. `depends_on` holds one parent, so a merge task cannot wait on both reviewers; the caller polls `queue.results()`.

## 2026-11-09: Queue workers prove ownership with a fence, and failure cascades

**Decision.** `queue.claim()` issues a fence per task from the `fences` table, and `heartbeat`, `finish`, `fail` and `release_back` require that fence and a live lease. A dead-lettered task halts everything waiting on it with a reason naming the task, and `redrive()` restores tasks halted for that reason. Retries wait in a new `tasks.not_before` column, 5 seconds doubling per attempt. Workers reap inside their own loop every 5 seconds. Shell tasks run in their own process group and stop at the task's deadline or `FLEET_TASK_TIMEOUT_S` (600), whichever is sooner.

**Context.** `worker` was logged but never checked, so after a reap and re-claim the old worker's `finish` marked the task done and deleted the new worker's lease, and `finish` could turn `dead_letter` into `done`. Children of a dead-lettered task stayed `ready` forever with nothing to say why. Without backoff, a failing task spent all 3 attempts in about 0.2 seconds.

**Alternatives.** Check only the worker name: a restarted process reusing its name would pass. Leave children `ready` so that a redrive needs no restore: they stay stranded with no visible reason, and never reach a terminal state. Sleep in the worker after a failure: another worker could re-claim the task at once. A separate reaper process: one more thing to forget to start.

**Evidence.** Reproduced before and after on throwaway databases: a stale `finish` is refused with `Fenced` even under the current holder's name; a 1-second task on a 0.3-second lease ran once under heartbeats, and twice without them. The 600-second default and the backoff values are starting guesses, not measurements.

**Affects.** `fleet/queue.py`, `fleet/worker.py`, `fleet/schema.sql`, `fleet/db.py`. Reaping pauses while every worker is busy, and a command keeps running after its lease is lost until it exits or times out.

## 2026-11-09: `fleet/drill.sh` pipes one statement per line into `sqlite3 -bail`

**Decision.** Each worker in `fleet/drill.sh` pipes its statements, one per line, into `sqlite3 -bail`. The script runs in a temporary directory that it removes on exit.

**Context.** With all statements in one command-line argument, a failed `BEGIN IMMEDIATE` did not stop the rest. The `INSERT` could land outside a transaction and `COMMIT` then failed with `no transaction is active`, so the rows figure was too high and the reported error hid the lock.

**Alternatives.** Add `-bail` and keep the single argument: it still ran the later statements on the CLI builds tested (3.54.0 and 3.53.4). Or rewrite the drill in Python around `db.write()`, which would exercise the harness but needs the timeout in `db.py` to be configurable.

**Evidence.** At `busy_timeout=1` the old script printed `rows=100/100` with up to 23 errors. With the change, every failure was `database is locked` and rows + errors was 100 in each run. https://sqlite.org/cli.html documents `.bail` but not this case.

**Affects.** `fleet/drill.sh`. It uses the `sqlite3` CLI, not the SQLite bundled with Python, and does not exercise `db.write()`.

## 2026-11-08: The edit hook fails closed and names files from the git root

**Decision.** `fleet/gate.py` exits 2 on any failure, including a missing `FLEET_RUN_ID` or a relative `ITERUM_DB`. File resources are `file:` plus the path from the git root, built by `claim.file_resource()`. Files outside any git repo are allowed, and unclaimed files are allowed for now.

**Context.** A `PreToolUse` hook that exits with anything but 2 does not block, so a crash let the edit through. A key built from the current directory missed claims from a subdirectory, and a relative database path opened a different, empty database in each worktree.

**Alternatives.** Fail open, so a broken database never blocks work. Or keep `module:` names, which would need a mapping from paths to modules. Blocking `Bash` writes was rejected, because parsing shell commands cannot be complete; the merge gate covers those. Requiring a claim on every edit waits until agents have a way to claim.

**Evidence.** Eighteen cases run as a subprocess in a throwaway git repo with a linked worktree, covering each earlier failure. The hook has not yet been registered in a live Claude Code session.

**Affects.** `fleet/gate.py`, `fleet/claim.py`. A broken database blocks edits until it is repaired.

## 2026-11-08: Claiming again always issues a new fence

**Decision.** `claim.acquire()` issues a new fence even when the same run and agent already hold a live claim. `renew()` and `release()` match on the fence, and `guard()` takes the `db.write()` connection that does the write.

**Context.** `--resume` reuses a `run_id`, and `fleet.recovery` lists a run as dead after 60 seconds while a lease lasts 300. Returning the existing fence would leave a paused process and its resumed copy holding the same one. A `guard()` that only reads leaves a gap between the check and the write.

**Alternatives.** Return the existing fence when `run_id` and `agent` match. Simpler, but it does not separate the old process from the new one.

**Evidence.** On a throwaway database, a second claim by the same run and agent made the first fence stale, and a `release()` or `renew()` with that fence left the new claim alone. A claim attempted during a `db.write()` block that had passed `guard()` was granted only after that block committed.

**Affects.** `fleet/claim.py`. A caller that claims twice invalidates its own earlier fence.

## 2026-11-08: Pin a uv-managed Python for SQLite 3.51.3 or later

**Decision.** Pin Python 3.14.10 in `.python-version`, which bundles SQLite 3.53.1.

**Context.** Python 3.14.4 from uv bundled SQLite 3.50.4, inside the range of a WAL-reset bug fixed in 3.51.3. `sqlite3` uses the SQLite built into the Python build.

**Alternatives.** Build the virtualenv from Homebrew's Python 3.14.7 (SQLite 3.53.4). No download needed, but it ties the project to one machine's Homebrew install.

**Evidence.** `uv run python -c "import sqlite3; print(sqlite3.sqlite_version)"` reports 3.53.1. The six-step drill plan and `fleet.recovery` ran cleanly on it.

**Affects.** `.python-version`. Each device needs a uv that can install 3.14.10.

## 2026-11-08: Freeing a failed receipt checks its status

**Decision.** `commit_once()` clears a `failed` receipt with `DELETE ... WHERE idem_key=? AND status='failed'`, not by key alone.

**Context.** Two workers could both read a `failed` receipt. The first deleted it and claimed the key `in_flight`; the second then deleted that fresh claim and claimed the key again, so the action ran twice.

**Alternatives.** Do the read, the delete and the claim in one `db.write()` transaction. Also correct, but a larger change to the function.

**Evidence.** A two-thread test that holds both workers after their first read ran the action twice before the fix and once after (three runs). The losing worker now gets `Uncertain` from its failed claim.

**Affects.** `fleet/idem.py`.

## 2026-11-08: `receipts` is the only receipt store

**Decision.** Keep the `receipts` table and remove the unused `steps.idem_key` and `steps.receipt` columns from `fleet/schema.sql`. No migration for existing databases.

**Context.** The schema offered two places for an idempotency key. Only `receipts` holds a status, a parameter hash and a settle time, and its primary key is what makes a claim atomic.

**Alternatives.** Keep both; or drop the columns from existing databases too.

**Evidence.** No code read or wrote the two columns, and they were empty in `agent.db`. SQLite 3.50.4 refuses `ALTER TABLE steps DROP COLUMN idem_key` with `cannot drop UNIQUE column`, so removing it from old databases would mean rebuilding `steps`. Old databases keep two empty columns; every query on `steps` names its columns, so nothing depends on them.

**Affects.** `fleet/schema.sql`, `CLAUDE.md` (lists `receipts` as control state).

## 2026-11-08: Claude Code's account and setup errors are `LOGICAL`, not `REFUSED`

**Decision.** Add `authentication_failed`, `oauth_org_not_allowed`, `account_on_hold`, `billing_error`, `model_not_found`, `max_output_tokens` and `cloud_credential_error` to `idem.LOGICAL`. Do not add them to `REFUSED`. Claude Code's own `unknown` stays unclassified.

**Context.** These are `error` values Claude Code emits on `system/api_retry`. A retry will not fix them, and Claude Code has usually retried already. `REFUSED` frees the key, which is only safe if nothing happened; a `claude -p` session can fail on these partway through, after tools have run.

**Alternatives.** Add them to both sets; or leave them unclassified.

**Evidence.** https://code.claude.com/docs/en/headless#handle-api-retries lists the categories. https://code.claude.com/docs/en/errors says Claude Code retries server errors, overloaded responses, timeouts and 429s up to 10 times. That a mid-session failure can follow side effects is a reading of the docs, not tested.

**Affects.** `fleet/idem.py`. Whether any belong in `REFUSED` is an open question.

## 2026-11-08: `run_step` halts at once on `AMBIGUOUS` failures

**Decision.** In `fleet/step.py`, a `StepError` whose category is in `idem.AMBIGUOUS` (`timeout`, `server_error`) is classified `ambiguous` and halts on the first attempt, re-raising the `StepError`.

**Context.** Those categories were classified `transient`, so `run_step` slept and retried. But `commit_once()` leaves their receipt `in_flight`, so the retry could only raise `Uncertain`, and the halt reason lost the real cause.

**Alternatives.** Keep retrying; or move `timeout` and `server_error` out of `TRANSIENT`, which would also change `classify()` for every caller.

**Evidence.** Before: one action call, a 2.0s sleep, halt reason `key ... was started and never settled`. After: one call, no sleep, halt reason `timeout: request timed out`. `rate_limit` still retries three times.

**Affects.** `fleet/step.py`. Callers now get `StepError` instead of `Uncertain` for these categories; tracked in `todo.md`.

## 2026-11-08: An ambiguous failure keeps the key locked

**Decision.** When an action fails without proof that nothing happened (no category, or a category outside `REFUSED`), `commit_once()` leaves the receipt `in_flight` and every later attempt raises `Uncertain` until a human settles it. Actions that know nothing ran may say so by raising an error whose `category` is in `REFUSED`.

**Context.** `commit_once()` sees only its own `receipts` table and cannot ask the outside system whether the action took effect.

**Alternatives.** Free the key on any failure. Rejected: an action that did half its work would run again, which is the failure the module exists to prevent.

**Evidence.** Reasoning, not a test: a wrong lock costs one halt and a human check; a wrong unlock can repeat a deploy, a message or a charge.

**Affects.** `fleet/idem.py`. Makes a way to settle stuck receipts necessary; open question.
