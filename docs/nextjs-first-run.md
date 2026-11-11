# Plan: the first real task, a Next.js app one feature at a time

Status: proposed 2026-11-11, not started. `todo.md` item 1. Every run here is billed; confirm the plan and the cap with the user before each one.

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

1. **By hand, outside the harness.** Create the app in a new repo and commit it on `main`. Check the current `create-next-app` docs for its flags first; nothing here assumes them.
2. **Before writing the plan.** In the scaffolded repo, run the build once and `git status`: list every tracked file a build or install changes (for example `package-lock.json`). Each must be declared in the plan, or `fleet.merge` refuses.
3. **First run, one feature,** on a branch other than `main`, under a ceiling, with `fleet.telemetry` running and `.env.example` sourced (`check_receiver()` requires both):

   ```json
   [[1, "change the home page", {"prompt": "<one-sentence change>", "model": "claude-haiku-5-5"}, ["file:app/page.tsx"]],
    [2, "build", "npm run build", ["file:app/page.tsx"]],
    [3, "commit it", "git add app/page.tsx && git commit -m '<message>'", ["file:app/page.tsx"]]]
   ```

   Then land it with the `fleet.merge` command the run prints. The paths are an example until step 1 shows the real layout.
4. **Later runs,** one feature each (an API route, a second page), each on its own branch, growing toward the app.

## What to watch, and record

- Whether Haiku's edits build, and how many turns they take against the cap of 10.
- Declaring files before a run: what is missed, and what `fleet.merge` refuses.
- A failed build: fix the failed shell step's command and resume (allowed since `aadd955`). A failed prompt step may also change its prompt, but rerunning it always needs `--force`.
- Cost per step against the first paid run's $0.0172.
- Any step that must not run twice (the trigger for option B in `commit-once-design.md`).

Findings go in `todo.md`, `open-questions.md` or the decision log.
