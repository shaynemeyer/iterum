# Plan: the first real task, a Next.js app one feature at a time

Status: steps 1 to 3 done 2026-11-11 (results below; `work-completed.md`). Step 4 is `todo.md` item 1. Every run here is billed; confirm the plan and the cap with the user before each one.

## Why one feature, not a SaaS

The harness limits what one run can do (`CLAUDE.md`):

| Limit | Effect on a Next.js app |
| --- | --- |
| `fleet.merge` lands a branch only if every changed file has a live claim | Scaffolding with `create-next-app` inside a plan would create dozens of files, each to be declared. Scaffold by hand instead. |
| A prompt step has only Read, Edit and Write; no Bash | The session cannot run `npm run build` or tests. Checks are separate shell steps after it. |
| A prompt step must declare the files it may edit | The files are known before the run, which fits one feature, not a whole app. |
| `--max-turns 10`, a cap per step, Haiku | Enough for a focused edit (the first paid run used 5 turns on a two-file fix), too little for an app. |
| Prompt steps load the user's Claude Code setup | Auth and payments bring secrets; keep them out of the first runs. |

## Steps

1. **By hand, outside the harness.** Create the app in a new repo and commit it on `main`. Check the current `create-next-app` docs for its flags first; nothing here assumes them. Done: Next 16.4.6, installed with bun, home page at `app/page.tsx`.
2. **Before writing the plan.** In the scaffolded repo, run the build once and `git status`: list every tracked file a build or install changes (for example `package-lock.json`). Each must be declared in the plan, or `fleet.merge` refuses. Done: `bun run build` changed no tracked file.
3. **First run, one feature,** on a branch other than `main`, under a ceiling, with `fleet.telemetry` running and `.env.example` sourced (`check_receiver()` requires both):

   ```json
   [[1, "change the home page", {"prompt": "<one-sentence change>", "model": "claude-haiku-5-5"}, ["file:app/page.tsx"]],
    [2, "build", "bun run build", ["file:app/page.tsx"]],
    [3, "commit it", "git add app/page.tsx && git commit -m '<message>'", ["file:app/page.tsx"]]]
   ```

   Then land it with the `fleet.merge` command the run prints.

   `fleet.run` runs each step, and checks the branch, in the directory it starts from, so start it from the app's repo, not this one. From there, `fleet` needs `PYTHONPATH` pointing at this repo, and `ITERUM_DB` must be one absolute path shared by `fleet.telemetry`, `fleet.run` and `fleet.merge` (`check_receiver()` compares the receiver's database with the run's):

   ```bash
   source <iterum>/.env.example
   export ITERUM_DB=<iterum>/agent.db ITERUM_DEVICE=<device> PYTHONPATH=<iterum>
   uv run --project <iterum> python -u -m fleet.run --plan <plan.json> --allow-claude 0.10
   uv run --project <iterum> python -m fleet.merge <branch> --run-id <run_id> --fence file:app/page.tsx=<n>
   ```

   Before the paid run, the same plan with step 1 replaced by a shell `echo` and step 3 by `git status`, on a scratch `ITERUM_DB`, checks the paths, the branch and the claims for free.
4. **Later runs,** one feature each (an API route, a second page), each on its own branch, growing toward the app.

## What to watch, and record

- Whether Haiku's edits build, and how many turns they take against the cap of 10.
- Declaring files before a run: what is missed, and what `fleet.merge` refuses.
- A failed build: fix the failed shell step's command and resume (allowed since `aadd955`). A failed prompt step may also change its prompt, but rerunning it always needs `--force`.
- Cost per step against the first paid run's $0.0172.
- Any step that must not run twice (the trigger for option B in `commit-once-design.md`).

Findings go in `todo.md`, `open-questions.md` or the decision log.

## Results: the first run, 2026-11-11

Run `111d83b085ae`: "replace the existing `<h1>`'s content with: Hello from iterum", Haiku, cap $0.10 per step under a $0.50 ceiling.

- All three steps committed on the first try. The edit was the requested one and nothing else (four lines out, one in), and it built.
- Haiku used 3 turns of 10 and cost $0.0171 (`claude.finished`), against the first paid run's $0.0172.
- `fleet.telemetry` logged 3 `spend.reported` events summing to $0.0171, matching the envelope; the governor showed $0.0171 spent.
- `fleet.merge` landed the branch with `--fence file:app/page.tsx=1`. No file was missed and nothing was refused.
- No step needed to run twice, so nothing triggered option B in `commit-once-design.md`.
