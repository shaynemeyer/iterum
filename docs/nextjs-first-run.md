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
- A failed build: fix the failed shell step's command and resume (allowed since `aadd955`). A failed prompt step may also change its prompt, but rerunning it always needs `--force`. When the prompt step committed but its edit broke the build, a person can fix the file by hand and resume: the prompt step is skipped and nothing is billed, but the run's commit then mixes the model's edit with the person's fix (fourth run).
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

## Results: the second run, 2026-11-11

Run `095cf7955377`: create `app/about/page.tsx` and link it from `app/page.tsx` (with its `import Link`), Haiku, cap $0.10 per step under the same ceiling. Both files claimed by every step.

- All three steps committed on the first try. Haiku used Write for the new file and Edit for the link; both diffs were the requested ones, and it built.
- $0.0226 (`claude.finished`), matched by 7 `spend.reported` events. `num_turns` was 11, above `--max-turns 10`, while the transcript shows about 7 rounds of tool calls (`open-questions.md`).
- A claim on a file that did not exist yet worked: `fleet.merge` landed the new file with `--fence file:app/about/page.tsx=1 --fence file:app/page.tsx=2`.
- **The session got the user's claude.ai connectors** despite `--tools Read,Edit,Write`, and Haiku called `mcp__claude_ai_Gmail__list_labels`, which was denied. Fixed after the run: prompt steps now get no MCP servers or tools (decision log, 2026-11-11).
- No step needed to run twice.

## Results: the third run, 2026-11-11

Run `bec20a793b36`: read the app's route-handler guide in `node_modules/next/dist/docs/` (its `AGENTS.md` warns that this Next.js differs from what models know, and prompt steps no longer load CLAUDE.md files), then create `app/api/hello/route.ts` answering GET with `{"message": "Hello from iterum"}`. Haiku, cap $0.10 per step under the same ceiling. Step 2 was `bun run build | tee /dev/stderr | grep -q '/api/hello'`, checked beforehand to fail while the route was absent.

- All three steps committed on the first try. Haiku read the guide, wrote a three-line handler (`Response.json(...)`) following it, and touched nothing else; the build listed `/api/hello`; `fleet.merge` landed it with `--fence file:app/api/hello/route.ts=1`.
- 3 turns, $0.0019 (`claude.finished`), matched by 3 `spend.reported` events.
- First run with the new context settings (decision log, 2026-11-11). The transcript had no git status snapshot, no CLAUDE.md contents and no `mcp__` names; the account email was there, as decided. The first request's context was 5,466 tokens, against 46,189 in the second run. Part of the cost drop is the smaller task.
- Still not shown: that the gate hook runs under the new flags. A hook that allows an edit leaves nothing in the transcript.
- No step needed to run twice.

## Results: the fourth run, 2026-11-11

Run `aeec4aecb610`: the home page shows the message from `/api/hello`, the first feature built on an earlier run's. The app's own docs (`node_modules/next/dist/docs/01-app/02-guides/backend-for-frontend.md`, "Server Components") say a Server Component must not fetch the app's own Route Handlers, and one prerendered at build time fails the build, so the prompt asked for a Client Component: create `app/hello-message.tsx` (`'use client'`, `fetch('/api/hello')` in a `useEffect`) and render it in `app/page.tsx`. A new step 3 started the built app on a port, checked `/` and `/api/hello` answered, and stopped it; checked beforehand to fail on a missing string and to leave no server behind.

- **The build failed.** Haiku's Write call ended the new file with a stray `</content>` line; the transcript shows it in the tool call's own `content`, so the model wrote it. The component above it was right, and the `page.tsx` edit was exactly the requested two lines. 7 turns, $0.0024, no denials.
- The build step caught it before anything was committed; the run stopped `failed` with the prompt step `committed`. This is the first failure only real use produced, and why every prompt step is followed by a build.
- Fixed by hand (deleted the line) and resumed with the same plan: step 1 was skipped, nothing billed, and build, smoke check and commit passed. The commit (`2369218` in the app) holds Haiku's edit and the one-line fix together; only this note says so.
- The smoke check cannot see the Client Component's output, since the message is fetched in the browser and `/` already says "Hello from iterum" in its heading. A browser on the built app showed the fetched message under the About link.
- `fleet.merge` landed it with `--fence file:app/hello-message.tsx=2 --fence file:app/page.tsx=4`: the resume claimed both files again, so the fences moved on.
- No step needed to run twice in the sense of option B: the rerun build was safe to repeat.

## Results: the fifth run, two at once, 2026-11-11

Two runs started together against one `agent.db` and one `fleet.telemetry`, each in its own working tree of the app: run A (`3dc4f3eb311c`, branch `feat/about-list`) added a three-item list to `app/about/page.tsx`; run B (`079f6a69f0a5`, branch `feat/footer`, in a `git worktree`) created `app/footer.tsx`, a Server Component, and rendered it in `app/layout.tsx`. Each plan: a Haiku prompt step, build, a smoke check on its own port, commit. Cap $0.10 per step under the $0.50 ceiling.

- Free checks first: both plans dry-run at the same time on a scratch database; starting B's plan in A's tree while B held its claims was refused before any step ran; both smoke checks failed without the edits and left no server behind; `bun install` and the build in the new worktree changed no tracked file.
- Both runs: every step committed on the first try, and each diff was exactly the change asked for. A: 3 turns, $0.00071. B: 6 turns, $0.00111. No denials.
- The prompt steps overlapped: both `step.proposed` within 3 ms, committed 5.4 s and 6.9 s later. One receiver logged 3 `spend.reported` events per run, each run's matching its own session's cost.
- Both runs passed their headroom check together. Far from the limit this shows nothing about two runs near it (`open-questions.md`, "Can concurrent runs share one spend ceiling?").
- `fleet.merge` landed A, then B onto the `main` A had just moved.
- **No step built the merged result.** Each branch built alone and `fleet.merge` does not build. `bun run build` on `main` after both merges passed, by hand. Later reproduced as a real gap (`merge-check-design.md`).
- Both runs' agent was `worker-1`, which `fleet.run` gives every run (`db.start_run("worker-1", ...)` in `main()`), so the refusal named the holder as "worker-1": with two runs it cannot say which one. Claims are keyed by run id, so nothing broke.

## Results: the sixth run, two prompt steps, 2026-11-11

Run `45ac556c9930`: replace the scaffold's "Create Next App" title. The first plan with two prompt steps, the second depending on the first, each followed by a build: (1) Haiku sets the root layout's `title` to `{ default: "iterum demo", template: "%s | iterum demo" }` and a new description; (2) build; (3) Haiku adds `export const metadata = { title: "About" }` to `app/about/page.tsx`; (4) build; (5) start the built app and check `<title>iterum demo</title>` on `/` and `<title>About | iterum demo</title>` on `/about`; (6) commit. The app's docs (`generate-metadata.md`, "template") say a root layout's template applies to child segments, not the layout's own, hence the two expected titles. Cap $0.10 per prompt step.

- Free checks first: a dry run with both prompt steps as `echo` committed every step; the smoke check failed without the edits and left no server.
- Every step committed on the first try, and both diffs were exactly the changes asked for. Step 1: 3 turns, $0.00069; step 3: 3 turns, $0.00066; no denials. 6 `spend.reported` events summed to $0.00135, the two sessions together.
- Each prompt step passed its own headroom check. The smoke check saw both titles in the server's HTML, so the second step's title and the first step's template combined as the docs say.
- `fleet.merge` landed it with `--fence file:about/page.tsx=3 --fence file:layout.tsx=2`. `main` was then built by hand, since `fleet.merge` does not (`merge-check-design.md`); it passed.

## Results: the seventh run, two at once, landed with `--check`, 2026-11-11

Two runs started together, as in the fifth run: A (`69561f66c656`, `feat/not-found`) created `app/not-found.tsx`, which the app's docs (`not-found.md`) say handles every unmatched URL from the app root; B (`dc206a6502c6`, `feat/robots`, in a worktree) created `app/robots.ts` in the shape `robots.md` shows, disallowing `/api/`. Each: a Haiku prompt step that read its guide first, build, a smoke check (A: `/no-such-page` answers 404 with "Page not found"; B: `/robots.txt` has `Disallow: /api/`), commit. Cap $0.10 per step.

- Free checks first: concurrent dry runs on a scratch database; both smoke checks failed without the edits (A's because Next's default 404 page does not say "Page not found"), and left no server.
- Both runs: every step committed on the first try, both diffs exactly as asked. A: 4 turns, $0.00178; B: 3 turns, $0.00117; no denials; each run's `spend.reported` events matched its session.
- **First real use of `fleet.merge --check`** (`merge-check-design.md`): A, then B onto the `main` A had moved, each with `--check "bun install --frozen-lockfile && bun run build"`. Both checks passed in about 5 s each, `merge.started` then `merge.landed`, no temporary worktree left. No hand build of `main` was needed. The two features did not interact, so this shows the gate passing; refusal was shown by the reproduction.

## Results: the eighth run, one task on three model mixes, 2026-11-11

The same plan three times, each on its own branch from `main`, none landed: (1) a prompt step creates `app/contact/page.tsx`; (2) a prompt step adds a Link to `/contact` in `app/footer.tsx`; (3) build; (4) commit. Only the models differed: A (`acc8e24a9649`, `cmp-opus`) Opus 5.5 on both, B (`cba1b73bfe45`, `cmp-haiku`) Haiku 5.5 on both, C (`01530d2ae6bd`, `cmp-split`) Opus then Haiku. Cap $0.50 per prompt step under a $3.00 ceiling. Plans in `docs/.local-only/cmp-*.json`.

| Run | Step 1 | Step 2 | Total (`spend.reported`) |
| --- | --- | --- | --- |
| A: Opus / Opus | 2 turns, $0.0304 | 3 turns, $0.0185 | $0.0489 (5 events) |
| B: Haiku / Haiku | 4 turns, $0.0010 | 3 turns, $0.0006 | $0.0016 (6 events) |
| C: Opus / Haiku | 2 turns, $0.0114 | 3 turns, $0.0005 | $0.0119 (5 events) |

- A free dry run (both prompt steps as `echo`, scratch database) committed every step first.
- Every step of every run committed on the first try, no denials. `git diff` between the three branches shows no difference in `app/`: on this task, Haiku's output was the same as Opus's.
- Each run's `spend.reported` total equals the sum of its `claude.finished` costs.
- **Order skews the Opus numbers.** A's first Opus request wrote 2,469 tokens to the prompt cache and cost $0.0248; the same request in C, about 7 minutes later, wrote none and cost $0.0055. So A against C partly measures which ran first. A fair comparison repeats each mix or alternates the order.
- B and C were first refused before any step ran (nothing billed): A's claims on the same files lasted `ITERUM_CLAIM_TTL` after it finished, since its branch was not landed. Both were resumed after the claims expired, with `ITERUM_CLAIM_TTL=60` so B's cleared quickly for C.
