---
name: fleet-plan
description: Turn a one-sentence feature request into an Iterum plan, check script and plain-words plan document, proven free before anything is billed. Run from inside the app repo.
argument-hint: "<the feature, in one sentence>"
disable-model-invocation: true
---

# /iterum:fleet-plan

Turn "$ARGUMENTS" into a plan that `iterum run` can execute unattended. Iterum lives at `${ITERUM_HOME:-~/github/iterum}`; its `docs/overnight-design.md` section 4 item 2 is the spec for this skill.

The current folder must be the app repo (a git repo whose root is the current folder). If it is not, stop and say so.

## Rule 1: no plan with open questions

An unattended run cannot ask, so any ambiguity left now becomes a guess made at night.

- If "$ARGUMENTS" is empty, ask for the feature and stop.
- Read enough of the repo to ask good questions: its layout, the files the feature would touch, `package.json` (or equivalent) for the build command, and any `AGENTS.md` or `CLAUDE.md`.
- Read what past runs cost before suggesting a model or a cap, and base both on it (spend per run, newest first; the database is `$ITERUM_DB`, else `~/.local/share/iterum/agent.db`):

  ```
  sqlite3 "${ITERUM_DB:-$HOME/.local/share/iterum/agent.db}" "SELECT run_id, json_extract(payload,'$.model') AS model, round(sum(json_extract(payload,'$.cost_usd')),5) AS usd, count(*) AS requests FROM events WHERE kind='spend.reported' AND run_id NOT LIKE 'session-%' GROUP BY run_id ORDER BY max(event_id) DESC LIMIT 10"
  ```

- Then ask clarifying questions (AskUserQuestion), and keep asking until nothing is unresolved: what the feature does, exactly which files it creates or changes, what counts as done (what the check looks for), the model, the cap per prompt step.
- Do not write any file while a question is open. A vague request gets questions only, never a plan.

## Rule 2: small chunks

Each chunk is one prompt step that touches one to three files and stays well under 100K tokens of context (context rot: `docs/context-rot.md` in Iterum).

- This version plans **one chunk**. If the feature needs more, say so, list the chunks you would make (files, dependencies, which could run in parallel), and ask which one to plan now.
- **One task per file per night** (Iterum decision log, 2026-11-14). When you list chunks, group any that share a file or depend on each other: a group becomes one plan, its chunks as consecutive prompt steps on one branch. Only groups with no file in common may be queued as separate tasks. Two tasks claiming one file collide: the second is refused by the first run's claim, which lasts until the run is landed, and a dependent chunk on its own branch from `main` would not see its parent's work.

## Write the plan

Only once nothing is open. Pick a short slug (`tag-pages`) and write to `<iterum>/plans/<slug>/` (gitignored there):

1. `check.sh`: run after the build, from the app root. Exits 0 when the feature is there; otherwise exits 1 with one line naming the first miss, **on stderr** (it becomes the step's error and the fix loop's feedback). For a web app, start the built server on a port of its own in the background, stop it and its children with a `trap` on its pid at exit, wait until it answers, then check pages with `curl` (status codes, and text or links in the HTML). Stop only that server, never every server of its kind.
2. `plan.json`: `[[seq, intent, command, [resources]], ...]`, every step claiming the same files (`"file:<path from the repo root>"`):
   1. `{"prompt": "...", "model": "..."}`: name every file to create or change, say "Create no other file and change nothing else", and what each must contain. Give no hints the user did not ask for.
   2. The build (`bun run build` or the app's own).
   3. `sh <iterum>/plans/<slug>/check.sh`.
   4. `git add <files> && git commit -m '<summary>'`.
3. `dry.json`: the same plan with step 1's command replaced by `"echo dry"`.
4. `plan.md`, in plain words: the feature; files; the prompt; build; what the check looks for; model; cap per step; `--fix-retries 2`; chunks; and a last line `Open questions: None`. If that line cannot say None, delete the files and go back to Rule 1.

## Prove it, free

In order; stop and report if one does not hold.

1. **The check fails on `main`.** In a throwaway `git worktree add --detach <scratch> main`: install, build, run `check.sh`; it must exit 1. Remove the worktree after.
2. **The dry run fails at the check.** On a new branch `feat/<slug>` from `main`, with a scratch `ITERUM_DB`: `iterum run <iterum>/plans/<slug>/dry.json`. Steps 1 and 2 must commit and step 3 fail. Delete the scratch database after.

## Ask

Show `plan.md`, then ask: **"Implement this feature?"** On yes, give the commands; do not run the paid run without that yes:

```
iterum receiver                       # in another terminal
source <iterum>/.env.example
iterum run <iterum>/plans/<slug>/plan.json --allow-claude <cap> --fix-retries 2
```

Landing stays a separate decision for a person: `iterum land feat/<slug> --run-id <run_id> --check "<install> && <build>"`. The check runs in a fresh temporary copy of the repo with no dependencies installed, so it must install them first; for a bun app, `--check "bun install --frozen-lockfile && bun run build"`. With the build alone, the landing is refused (`next: command not found`).
