# Design note: wiring `claude_step()` into `fleet/run.py`

Status: agreed 2026-11-10 (see "Decisions" at the end). Every `claude` call is billed to the user.

Flags were checked against `claude --help` for Claude Code 2.1.322 and against the [CLI reference](https://code.claude.com/docs/en/cli-reference) and [headless docs](https://code.claude.com/docs/en/headless). Anything not checked is marked **unverified**.

## Today

`claude_step(prompt)` in `fleet/run.py` runs `claude -p <prompt> --output-format json` with `subprocess.run`, raises if `is_error` or the exit code is non-zero, and returns the JSON envelope. Nothing calls it. It does not run in its own process group, record `steps.pgid`, set any telemetry settings, or limit turns, spend or tools.

## 1. How a plan marks a prompt step, and how resume treats it

**Proposed.** The third field of a plan step is either a string (a shell command, as now) or an object `{"prompt": "..."}`:

```json
[[1, "fix the typo in a.txt", {"prompt": "In a.txt, fix the spelling of 'teh'."}, ["file:a.txt"]],
 [2, "commit it", "git add a.txt && git commit -m 'Fix typo'", ["file:a.txt"]]]
```

`load_plan()` keeps the object; `run_steps()` calls `claude_step()` for it and `shell()` otherwise. The built-in `PLAN` stays all strings.

**`check_resumable()`** is unchanged: the ledger stores intents, not commands or prompts, so it compares intents by seq as it does now. A changed prompt with the same intent is not caught, as a changed shell command is not caught today.

**Resume.** A shell step that was `proposed` but not `committed` is rerun on resume. A prompt step in that state may already have edited files, and a rerun is a second billed session that may edit them again. **Proposed:** resume refuses a run whose uncommitted step is a prompt step unless `--force` is given, and the refusal says to check `git status` on the run's branch first. This is the same "a human checks" outcome `commit_once()` would give, without receipts (see 4).

**Process group.** `claude_step()` should start `claude` the way `shell()` starts a command: `Popen` with `start_new_session=True`, `steps.pgid` written, the group killed on `KeyboardInterrupt` (which includes SIGTERM via `proc.stop_on_sigterm()`) and on a refused claim renewal. Then the existing resume guard (group still alive) and `kill_running_step()` cover it unchanged. Simplest is one `_spawn(argv, env, run_id, seq)` shared by both.

## 2. Opt-in, so the built-in plan and drills never spend

**Proposed.** Two locks:

- `fleet.run` refuses a plan that contains a prompt step unless `--allow-claude` is passed. A plan file copied from somewhere cannot spend by itself.
- `--allow-claude` takes a per-step cap in USD, with no default, passed to `claude` as `--max-budget-usd`. Every run states its own cap. The docs say this is a "client-side cost estimate" and "Spend can pass the cap", so it limits, not guarantees. Also pass `--max-turns 10` (help text: "Limit the number of agentic turns (print mode only)"). Ten is a guess, to be checked by the paid run.

The drills and the built-in plan never pass `--allow-claude`, and nothing in them is an object, so they cannot reach `claude`.

## 3. `iterum.run_id` in telemetry

**Proposed.** `claude_step()` passes the child an environment of `os.environ` plus `OTEL_RESOURCE_ATTRIBUTES=iterum.run_id=<run_id>`, appended with a comma if the variable is already set. The other telemetry settings come from `.env.example`, sourced by the user before `fleet.run`; `fleet.run` does not read `.env.example` itself.

`fleet.telemetry` already logs `spend.reported` under `iterum.run_id` when present (see `CLAUDE.md`). If the receiver is not running, spend is not recorded; the `claude` JSON envelope's `total_cost_usd` (documented on the headless page) can be logged in the `step.committed` event as a fallback.

Optional: add `iterum.seq=<seq>` as well, so spend can be tied to a step. Not required by the todo.

## 4. Through `commit_once()`?

**Proposed: no, not in the first version.**

- A `claude -p` session can fail after tools ran, so almost every failure is ambiguous. Through `commit_once()` the receipt would stay `in_flight` and every retry would raise `Uncertain`.
- There is no command to settle an `in_flight` receipt yet (open question "How does a human settle a stuck `in_flight` receipt?"), so the only way out would be editing `agent.db` by hand.
- The write-ahead `steps` row plus the `--force` rule in 1 already stops an automatic rerun and hands the decision to a person.

Revisit once the settle command exists and real failed sessions show where the final error appears (open question "Should any Claude Code account or setup errors be `REFUSED`?").

## 5. Where the edits happen

A prompt step must declare its files, so the existing rules apply: the run is on a branch other than `--target`, `claim_files()` claims the files before any step, the heartbeat renews the claims, and the run lands through `fleet.merge` with the printed fences. `claude` runs with the run's working directory, which is that branch's worktree.

Committing the edits is a following shell step in the plan (example in 1), not new code in `fleet.run`.

**Tools and permissions.** Proposed: `--permission-mode acceptEdits` and `--allowedTools Read,Edit,Write`, no Bash. The headless page: "Use `--allowedTools` to let Claude use certain tools without prompting." What a disallowed tool does in `-p` mode is **unverified**; the CLI reference says a call needing approval in a manual-mode `-p` run "is denied unless something approves it".

**Keeping edits inside the claims.** Two checks exist. `fleet.merge` refuses to land a branch if any changed file lacks a live claim (`claim.require_claim()` in `land()`), whatever the session did; this holds in either mode. `fleet/gate.py` refuses an edit to a file another run has claimed earlier, during the session, but only as a `PreToolUse` hook. The two ways to run headless differ on the hook and on billing:

| | Default `-p` | `--bare` |
| --- | --- | --- |
| Loads `~/.claude` hooks, plugins, CLAUDE.md, the project's `.claude/settings.json` and `.mcp.json` | Yes ("discovers and loads them as an interactive session would", headless page) | No |
| Runs `gate.py` passed through `--settings` | Expected, **unverified** | No: `--bare` help says it skips "hooks (those defined in settings and by installed plugins...)" |
| Auth | Subscription login | "strictly ANTHROPIC_API_KEY" (help text); "bare mode doesn't use your subscription login" (headless page) |

**Decided: default `-p`**, with `gate.py` passed through `--settings`. It uses the subscription, and the merge gate backs it up if the hook does not load. `--bare` would need an API key and drop the early check. `--setting-sources` and `--strict-mcp-config` may narrow what the default loads; **unverified**.

## 6. Test plan

**Free, first.** A fake `claude` script on `PATH` in a scratch directory that prints a fixed JSON envelope (or sleeps, or exits non-zero). With it, on a scratch `ITERUM_DB`, check without spending:

1. A plan with a prompt step is refused without `--allow-claude`.
2. The child sees `OTEL_RESOURCE_ATTRIBUTES` containing `iterum.run_id=<run_id>`, and `--max-budget-usd` and `--max-turns` in its argv.
3. SIGKILL `fleet.run` mid-step: resume refuses while the fake's group is alive, then refuses without `--force` once it is gone.
4. Ctrl-C or SIGTERM kills the fake's group.
5. A non-zero exit, or `"is_error": true`, fails the step and run.
6. The built-in plan and the three drills still pass.

**One paid run, only with the user's go-ahead.** On a throwaway branch with one claimed file, a one-sentence prompt, a cheap `--model`, `--max-turns 3` and a `--max-budget-usd` cap of a few cents, with `fleet.telemetry` running. Check:

- The file is edited and committed by the next step, and `fleet.merge` lands it.
- An edit to a file claimed by another run is refused by `gate.py` (whether the hook runs under `--settings` in `-p` mode is **unverified** until this).
- `spend.reported` events appear under the run's id, not `session-<id>`.
- The envelope of a run that worked: `"is_error": false` and exit 0. Only a failed run's envelope has been seen (below).

**Seen 2026-11-11, free.** The CLI envelope does carry `is_error`, and `subtype` cannot be trusted. `claude -p "say ok" --bare --output-format json` with no `ANTHROPIC_API_KEY` (Claude Code 2.1.322) made no API call (`"total_cost_usd": 0`), exited 1, wrote nothing to stderr, and printed one JSON object to stdout with `"is_error": true`, `"subtype": "success"`, `"terminal_reason": "api_error"` and `"result": "Not logged in · Please run /login"`. So `claude_step()` is right to branch on `is_error` and the exit code, never on `subtype`.

## Decisions (agreed 2026-11-10)

1. Plan format: `{"prompt": ...}` in the third field.
2. Resume of an uncommitted prompt step: refused without `--force`.
3. Opt-in: `--allow-claude` with a required per-step `--max-budget-usd` (no default) and `--max-turns 10`.
4. `commit_once()`: not in the first version.
5. Default `-p` with `gate.py` via `--settings` and the subscription, not `--bare`. `fleet.merge` keeps unclaimed edits off the target in either mode.
