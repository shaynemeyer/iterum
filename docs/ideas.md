# Ideas

Things that might be worth doing, not yet planned or decided. When one is taken up, it moves to `todo.md` (or a plan), and its decisions go to `decision-log.md`.

## Notify when plans finish: Slack, email or text

Raised 2026-11-15 by the user: "the ability to send notifications when plans are complete to like slack, email or text message".

**Where it would hook in.** The worker already does something however it stops, short of SIGKILL: `write_report()` in `fleet/worker.py` writes the day's page. A notification could go out at the same point, once per night, with the night's outcome (done, failed, dead-lettered, ready to land, spend). Per run is the other choice: `fleet.run` ends each run with `run.done` or `run.failed`.

**Options.**

1. **A command hook:** an `ITERUM_NOTIFY` setting holding a shell command, run with the summary on stdin. Iterum holds no secrets and adds no dependencies; the user points it at whatever they use: `curl` to a Slack incoming webhook, a mail command, an SMS service's API, or `osascript` for a macOS notification.
2. **Built-in channels:** `--notify slack|email|sms`, each with its own settings (webhook URL, SMTP server, SMS account). More to build and test, and each needs credentials kept out of the repo, which is public.
3. **Slack only, built in:** an incoming webhook is one HTTP POST of JSON, and Python's `urllib` can send it with no new dependency.

**Open.** Per night or per run; whether a failure or a stop at `--max-usd` should notify at once rather than at the end; what the message carries (counts and spend, or also the land commands); never the app's code or file contents in a third-party channel.

**Settled by.** Which channel the user actually wants to receive on; the docs for that channel (not yet checked in this repo) set what the hook or built-in sender must do.

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
