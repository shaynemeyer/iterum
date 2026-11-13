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

## Navigation between reports

Raised 2026-11-13. Daily reports pile up in `reports/` with nothing linking them. Each page could link to the previous and next report that exists, and `iterum report` could rewrite an `index.html` in `reports/` listing every report, newest first (date or range, runs, spend). Plain links, no scripts. To check: the links resolve from both the HTML and a PDF's folder, and a day with no report (nothing written) is skipped, not linked.

## Readable small values in report charts

Raised 2026-11-13. On a linear scale, small spend vanishes beside a large day: Haiku's spend on 2026-11-12 is invisible next to the $2.02 Opus hour, and one costly plan squeezes the cost-per-plan dots. Options: a total label on each bar, a log-scale option, or a second chart for the small series. The table views and hover titles already give the values. Settled by whether the charts are read for totals or for small series.

## Iterum's look for reports

Raised 2026-11-13. The report pages use a plain system font and the dataviz reference colours. They could take the gh-pages site's fonts, page colours and the Septa logo in the header, so a report reads as Iterum. Chart colours stay as they are (validated for colour-blind safety, light and dark). Wait until the reports have been used for a while.
