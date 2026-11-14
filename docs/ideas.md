# Ideas

Things that might be worth doing, not yet planned or decided. When one is taken up, it moves to `todo.md` (or a plan), and its decisions go to `decision-log.md`.

## CSV export for reports

Raised 2026-11-13. `iterum report` writes an HTML page (and a PDF with `--pdf`) or JSON with `--json`; there is no CSV. The report is nested (sections, runs with steps, spend by hour and model), and a CSV is one flat table, so an export means one or more tables.

**Options.**

1. **One CSV per table, in a folder** (preferred so far): `iterum report --csv` writes `reports/report-<date>/` with `runs.csv` (one row per run), `steps.csv` (one row per step, with its run id), `spend.csv` (hour or day, model, cost) and `landed.csv`; the same for `--days N`. Complete, and each file opens in a spreadsheet.
2. **One chosen table to stdout**: `iterum report --csv runs > runs.csv`. Simple and pipeable; you have to know the table names.
3. **Nothing new**: `--json` already holds every value, and `jq` can make any CSV (`iterum report --json | jq -r '.runs[] | [.run_id, .plan, .status, .cost_usd] | @csv'`).

**Details either way.** Python's standard `csv` module, no dependency. Times as local `YYYY-MM-DD HH:MM:SS`, not epoch seconds. Costs at full precision. Plan names as file names only, as on the page.

**To check when built.** Row counts equal `--json` (runs, steps, spend pairs, landed merges); a file opens in Numbers or Excel; a plan or intent with commas, quotes or newlines stays one cell.

**Settled by.** What the CSVs are for (a spreadsheet, another tool, sharing): one specific table favours option 2.

## Readable small values in report charts

Raised 2026-11-13. On a linear scale, small spend vanishes beside a large day: Haiku's spend on 2026-11-12 is invisible next to the $2.02 Opus hour, and one costly plan squeezes the cost-per-plan dots. Options: a total label on each bar, a log-scale option, or a second chart for the small series. The table views and hover titles already give the values. Settled by whether the charts are read for totals or for small series.

## A spend limit for one night

Raised 2026-11-14, when the first attended night stopped at headroom -$0.79: the fleet ceiling's window had been open since 2026-11-11, and three interactive Opus sessions that day counted against it ($1.49), started from a shell where `.env.example` was sourced. `iterum budget reset` (decision log, 2026-11-14) fixes it by hand, before each night.

**Options.**

1. **Manual reset** (what exists): `iterum budget set <usd>`, `iterum budget reset`, then start the worker. Simple; easy to forget, and resets the one ceiling for the whole machine.
2. **A daily reset at a chosen hour**: `iterum budget set 1 --resets-at 17:00`, the window computed at each check as the most recent 17:00, so an evening and the night after it share one window. Not at midnight: a night crossing 00:00 would get two days' ceilings. Needs a column for the hour in `budgets`, the repo's first schema migration. No scheduler.
3. **A limit on the worker**: `iterum worker night-1 --max-usd 1` stops claiming once the spend of its own tasks' runs (found through `run.started`'s `queue_task`) reaches the limit. Counts only the night's work, not interactive sessions; leaves the fleet ceiling alone; no schema change.

**Either way.** Interactive sessions count against any ledger-based limit while their shell has `.env.example` sourced; options 1 and 2 count them, 3 does not.

**Settled by.** A night that started with a stale window because the reset was forgotten (favours 2), or interactive sessions eating into a night's budget (favours 3).

## Iterum suggests a budget for the night

Raised 2026-11-14 by the user: "it would be a nice feature if iterum could recommend a budget for the night". Nothing in `fleet/` estimates cost before a run; `/iterum:fleet-plan` writes a bound and a typical figure into each `plan.md` by hand.

**Sketch.** `iterum budget suggest` reads the queued tasks and prints, per task, prompt steps x tries (1 + `--fix-retries`) x `--allow-claude` cap ("at most") and the median past cost of prompt steps on the same model from `spend.reported` ("typical"); then a suggested ceiling (the sum of the bounds, so no task within its own caps is stopped) and an expected total, and the command to apply it (`iterum budget set <usd> && iterum budget reset`). It sets nothing itself.

**Needs first.** A task stores only a shell string, so the plan, cap and retries would have to be parsed back out of it, which breaks on any other command shape. Instead, `iterum add --plan <p.json> --allow-claude <usd> --fix-retries N` builds the `iterum run` command and stores the three as payload fields; `suggest` reads them and the plan file (its number of prompt steps, its models). A task added as a plain shell string shows "cost unknown".

**Limits.** The cap is Claude Code's `--max-budget-usd`, "a client-side estimate that spend can pass" (`fleet/run.py`), so "at most" is a close bound, not a guarantee. The typical figure rests on small Haiku features (highest prompt step so far $0.00211); a bigger feature or another model has little history, and `suggest` should say so. One run so far has used retries, so the expected total leaves them out.

**To check when built.** On a scratch database: two tasks added with `--plan`, the bound equals steps x tries x cap summed; the typical figure equals the median of the `spend.reported` totals per prompt step for that model; a plain shell-string task shows "cost unknown"; nothing in `budgets` changes.

**Settled by.** Tonight's first real night: whether its actual cost lands near the typical figure.
