# Design note: a check on the merged tree before `fleet.merge` lands it

Status: agreed and implemented 2026-11-11 (decisions in section 5, results in section 6). Settles the former open question "Who builds the merged result?" (decision log, 2026-11-11). Facts below come from reading `fleet/merge.py` at `eeb7ccb`; anything not checked is marked **unverified**.

## 0. The problem, reproduced 2026-11-11, free

In the fifth Next.js run two concurrent runs each built their own branch and `fleet.merge` landed both; nothing built `main` afterwards (`nextjs-first-run.md`). Reproduced in a throwaway clone of the app with a scratch database and shell steps only: branch A turned `app/footer.tsx`'s default export into `export function Footer` and updated `app/layout.tsx`; branch B, from the same `main`, added `app/credits/page.tsx` with `import Footer from "../footer"`. Each run built and committed; `fleet.merge` landed A, then B onto the moved `main`, both exit 0, since the files were disjoint and every one was claimed. `bun run build` on the merged `main` failed: "`./app/credits/page.tsx:1:1 Error: Export default doesn't exist in target module`".

## 1. What `land()` does today

1. `build()`: `git merge-tree --write-tree` makes the merged tree with no working tree, then `commit-tree` makes the merge commit. `Conflict` or `Empty` stop it here.
2. Logs `merge.started` (write-ahead, for `reconcile()`).
3. In one `db.write()` block: `require_claim()` for every changed file, then `merge.landed`, releasing the claims, and `git update-ref` with the expected old target. A refused claim logs `merge.refused` and keeps the claims.

`main()` holds an exclusive lock per repo around `reconcile()` and `land()`, so no other `fleet.merge` moves the target meanwhile. It refuses when the target is checked out in any working tree.

## 2. Proposal

`fleet.merge` takes an optional `--check "<command>"`. When given, `land()` runs it on the merged commit between steps 2 and 3:

- **Where.** `git worktree add --detach <tmp> <merge commit>` in a new temporary directory outside the repo. A detached HEAD checks out no branch, so `checked_out()` is unaffected. The tree is removed in a `finally` with `git worktree remove --force`.
- **Dependencies.** The command brings its own: untracked files such as `node_modules` are not in the merged tree. For the app, `--check "bun install --frozen-lockfile && bun run build"`. The harness stays free of any language's tooling. In run 5, `bun install` in a fresh worktree took under a second from bun's cache (`nextjs-first-run.md`).
- **How it runs.** The shell runs it in the temporary tree, in its own process group, which is killed on Ctrl-C or SIGTERM, as `fleet/run.py` does for steps. No timeout.
- **Outside any transaction.** The check runs before the `db.write()` block, never inside it: `BEGIN IMMEDIATE` would block every other writer, run heartbeats included, for the whole build.
- **On failure.** Log `merge.refused` with `reason: "check failed"`, the command, its exit code and the last 2,000 characters of its output; keep the claims; leave the target alone; exit with `refused: check failed ...`. The existing outcome kind, so `reconcile()` and `fleet.view` need no change.
- **On success.** Step 3 as today. Claims are checked after the check, so a claim that expired during a long check is refused there, as now.
- **A crash during the check.** `merge.started` has no outcome, the merge commit is not in the target, so the next `reconcile()` logs `merge.abandoned`, as today. The temporary tree is left behind; its directory is outside the repo, and `git worktree prune` drops the record once the directory is gone, but not while it exists (seen in test 6, section 6).

Without `--check`, nothing changes, so `fleet.merge_drill` and every printed `land with:` line still work.

## 3. Not in this change

- `fleet.run` printing `--check` in its `land with:` line: a plan could name its check later; for now the person adds it.
- A check every merge must pass, set per repo: no place to configure it yet.
- Running the check once for several branches queued together.

## 4. Test plan, all free

On the reproduction's throwaway clone and scratch database (section 0):

1. Land A with `--check`: passes, lands.
2. Land B with `--check`: refused with "check failed", `main` unchanged, B's claim still live, `merge.refused` carries the exit code and the build error.
3. Fix B (`import { Footer }`), commit, land again with `--check`: lands; the merged `main` builds.
4. Without `--check`, B's original branch still lands, as today.
5. `--check "exit 1"` refuses; `--check "true"` lands; no temporary worktree is left in `git worktree list` after either.
6. SIGKILL `fleet.merge` mid-check: the next run's `reconcile()` logs `merge.abandoned`; record what `git worktree list` shows.
7. `fleet.merge_drill`, `fleet.claims_drill` and `fleet.kill_drill` pass.

## 5. Decisions (agreed 2026-11-11)

1. **A flag on `fleet.merge`,** not a plan-level setting. The smallest change that closes the gap, and `fleet.merge` stays usable on its own, as the drills use it. Cost: the person must remember `--check`; revisit if a missed check lets a broken result land.
2. **Reuse `merge.refused`** with `reason: "check failed"`. A failed check has a refusal's meaning: claims kept, target untouched, the caller may retry. `reconcile()` and `fleet.view` need no change. Cost: counting check failures means filtering on `reason`.
3. **Always remove the temporary tree.** The event keeps the command, exit code and output tail, and `merge.started` keeps the merge commit's hash, so the tree can be rebuilt with `git worktree add <dir> <hash>` until git collects the unreferenced commit (**unverified** how long that is). Cost: 2,000 characters may cut a long error short.

Order: the check and its refusal first (tests 1-5), then the crash case and the drills (tests 6-7).

## 6. Implemented and tested, 2026-11-11

`fleet/merge.py`: `run_check()`, a `check=None` argument to `land()`, `CheckFailed`, the `--check` flag, and `stop_on_sigterm()` in `main()` so SIGTERM kills the check like Ctrl-C. All tests free, on the reproduction's clone (section 0) and a scratch database.

| Test | Result |
| --- | --- |
| 1. A with `--check "bun install --frozen-lockfile && bun run build"` | Landed; the check took about 5 s. |
| 2. B with the same check | Refused, exit 1, with the build error ("Export default doesn't exist in target module"). Target unchanged, B's claim live, `merge.refused` with `reason`, `exit_code`, `check` and `output`. |
| 3. B fixed by hand, landed again with the check | Landed, claim released; the merged `main` builds. |
| 4. Another branch without `--check` | Landed, as before. |
| 5. `--check "exit 1"`, then `--check "true"` | Refused (`merge.refused`, process exit 1), then landed. After every test `git worktree list` showed only the clone's own tree and no `iterum-check-*` directory was left. |
| 6. SIGKILL of `fleet.merge` (the Python process, not only `uv`) during `--check "sleep 60"` | Target unchanged; only `merge.started` logged. The next `fleet.merge` of the branch: `reconcile()` logged `merge.abandoned` (`recovered`), then it landed. Left behind: the temporary worktree, which `git worktree prune` kept while its directory existed and dropped once the directory was deleted, and the check's process (`sleep 60`), in its own group, still running. |
| 7. `fleet.merge_drill`, `fleet.claims_drill`, `fleet.kill_drill` | All passed. |

Found while testing: the check runs before the claims check, so a branch with stale fences pays for a whole check before it is refused (seen with a branch holding no claim). Accepted: claims must be checked after the check anyway, since one can expire during it.

First real use (seventh Next.js run, `nextjs-first-run.md`): two concurrent branches landed one after the other, each with `--check "bun install --frozen-lockfile && bun run build"`; both checks passed in about 5 s, and no temporary worktree was left.

Left as is: after a SIGKILL, the stale worktree and the check's process are cleaned up by hand. A later change could let `reconcile()` remove `iterum-check-*` worktrees of abandoned merges.
