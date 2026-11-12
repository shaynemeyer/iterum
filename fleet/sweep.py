"""Run each model-mix plan several times and compare pass rate beside cost.

    uv run python -u -m fleet.sweep plan-a.json plan-b.json [...] [--repeats 5] [--base main] [--allow-claude <usd>]

Run it from the repo the plans work on, as fleet.run. Each repeat starts every plan
in a rotated order (the first request pays to write the prompt cache, so a fixed order
skews cost), each run on its own new branch from --base, as `fleet.run` in a subprocess.
The branches are never landed, so each run's claims are released when it ends.
What a run that did not finish leaves behind is committed on its branch, so it counts
as a fail. The sweep refuses a dirty tree, and stops if a finished run leaves one.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from fleet import claim, db, telemetry


def git(*args):
    """Run git in the current directory; exit with its message on failure."""
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def require_clean(after=None):
    """Exit if the working tree has changes. Nothing is cleaned for you."""
    dirty = git("status", "--porcelain")
    if dirty:
        where = f"run {after} left" if after else "the working tree has"
        sys.exit(f"{where} uncommitted changes; the next run would start from them:\n{dirty}")


def order(plans, i):
    """The plans rotated by i, so each takes every position equally often."""
    k = i % len(plans)
    return plans[k:] + plans[:k]


def run_plan(plan, allow_claude):
    """Run fleet.run on plan, echoing its output. Returns the run id, or None if it never started."""
    cmd = [sys.executable, "-u", "-m", "fleet.run", "--plan", str(plan)]
    if allow_claude is not None:
        cmd += ["--allow-claude", str(allow_claude)]
    run_id = None
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as p:
        for line in p.stdout:
            print("    " + line, end="")
            if line.startswith("run ") and line.rstrip().endswith(" started"):
                run_id = line.split()[1]
    return run_id


def release_claims(run_id):
    """Release every claim run_id still holds: its branch will not be landed."""
    with db.connect() as con:
        rows = con.execute("SELECT resource, fence FROM claims WHERE run_id=?", (run_id,)).fetchall()
    for r in rows:
        claim.release(r["resource"], run_id, r["fence"])


def keep_leftovers(run_id):
    """Commit what a run that did not finish left behind, on its own sweep branch.

    A failed step (a check, say) stops before the plan's commit step. Committing here
    keeps the tree clean for the next run and keeps the failed output for inspection.
    A run that finished and still left changes is a plan without a commit step; require_clean() stops on it.
    """
    status, _ = outcome(run_id)
    if status != "done" and git("status", "--porcelain"):
        git("add", "--all")
        git("commit", "--quiet", "-m", f"sweep: what run {run_id} ({status}) left behind")


def sweep(plans, repeats, base, allow_claude):
    """Run every plan repeats times. Returns [(plan, run_id)]."""
    tag = time.strftime("%Y%m%d-%H%M%S")
    start = git("symbolic-ref", "--short", "HEAD")
    runs = []
    for i in range(repeats):
        for plan in order(plans, i):
            branch = f"sweep/{tag}/{plan.stem}-{i + 1}"
            print(f"repeat {i + 1}/{repeats}  {plan.stem}  on {branch}")
            git("switch", "--quiet", "-c", branch, base)
            run_id = run_plan(plan, allow_claude)
            if run_id is not None:
                keep_leftovers(run_id)
            git("switch", "--quiet", start)
            if run_id is None:
                sys.exit(f"{plan} did not start a run; sweep stopped")
            release_claims(run_id)
            runs.append((plan, run_id))
            require_clean(run_id)
    return runs


def outcome(run_id):
    """(status, cost in USD from spend.reported) for one run."""
    with db.connect() as con:
        status = con.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()["status"]
        cost = con.execute(
            "SELECT COALESCE(SUM(json_extract(payload, '$.cost_usd')), 0) FROM events WHERE kind=? AND run_id=?",
            (telemetry.KIND, run_id),
        ).fetchone()[0]
    return status, cost


def report(runs):
    """Print pass rate and cost range per plan, then a verdict for each pair of plans."""
    by_plan = {}
    for plan, run_id in runs:
        by_plan.setdefault(plan.stem, []).append(outcome(run_id))
    width = max(len(n) for n in [*by_plan, "MIX"])
    print(f"\n{'MIX':<{width}}  {'PASS':>5}  {'MEAN USD':>9}  {'MIN USD':>9}  {'MAX USD':>9}")
    ranges = {}
    for name, results in by_plan.items():
        costs = [c for _, c in results]
        passed = sum(s == "done" for s, _ in results)
        ranges[name] = (min(costs), max(costs))
        print(f"{name:<{width}}  {passed:>2}/{len(results):<2}  {sum(costs) / len(costs):>9.4f}"
              f"  {min(costs):>9.4f}  {max(costs):>9.4f}")
    names = list(ranges)
    for a in range(len(names)):
        for b in names[a + 1:]:
            print(verdict(names[a], b, ranges))


def verdict(a, b, ranges):
    """'no signal' when the two cost ranges overlap, else which plan cost less on every run."""
    (lo_a, hi_a), (lo_b, hi_b) = ranges[a], ranges[b]
    if hi_a < lo_b:
        return f"{a} vs {b}: {a} cost less on every run"
    if hi_b < lo_a:
        return f"{a} vs {b}: {b} cost less on every run"
    return f"{a} vs {b}: NO SIGNAL, the cost ranges overlap"


def main():
    parser = argparse.ArgumentParser(prog="uv run python -u -m fleet.sweep")
    parser.add_argument("plans", nargs="+", type=Path, help="one plan file per model mix")
    parser.add_argument("--repeats", type=int, default=5, help="runs per plan (default 5)")
    parser.add_argument("--base", default="main", help="the branch each run's branch starts from")
    parser.add_argument("--allow-claude", metavar="USD", type=float, help="passed to fleet.run: each prompt step's cap (billed)")
    args = parser.parse_args()
    db.init()
    require_clean()
    runs = sweep(args.plans, args.repeats, args.base, args.allow_claude)
    report(runs)


if __name__ == "__main__":
    main()
