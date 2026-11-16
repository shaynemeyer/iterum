# Ideas

Things that might be worth doing, not yet planned or decided. When one is taken up, it moves to `todo.md` (or a plan), and its decisions go to `decision-log.md`.

## Windows support

Raised 2026-11-15 by the user, asking whether notifications would work on Windows. Iterum does not run natively on Windows today; nothing in the docs says it does, and it has never been tried on one.

**What is Unix-only** (found by reading the code, not by running it on Windows):

- `fcntl`, Unix-only per Python's docs (https://docs.python.org/3/library/fcntl.html): `fleet/merge.py` imports it at the top for the per-repo merge lock, so `iterum land` fails on import; `fleet/merge_drill.py` too.
- `os.killpg`, Unix-only per Python's docs (https://docs.python.org/3/library/os.html#os.killpg): `fleet/run.py`, `fleet/worker.py` and `fleet/merge.py` kill a step's, task's or check's whole process group with it, and `fleet/proc.py` tests whether a group is alive. That is what stops a resume or a reap from running beside a killed run's command.
- `start_new_session=True` on `Popen` (a new Unix session per command), which those groups rely on.
- Plans' shell strings run with `shell=True`, which is `cmd.exe` on Windows, not `sh`: plans and checks written for `sh` (`check.sh`, `&&`, `trap`) would not run as written.
- Smaller: `iterum report --open` calls macOS `open`; `--pdf` looks for Chrome on `PATH` or the macOS app path.

**Options.**

1. **WSL:** run Iterum inside WSL, a Linux environment, unchanged. Untested; a desktop notification would have to reach Windows from Linux.
2. **Native:** a Windows path for each item above (a lock that is not `fcntl`, process groups through Windows job objects or `CREATE_NEW_PROCESS_GROUP`, a shell choice for plans), each checked on a Windows machine. The process-group safety is the hard part.
3. **Say so:** state in the README that Iterum needs macOS or Linux (or WSL), and leave it there. Done 2026-11-15: the README's Setup says it is built and tested on macOS, does not run on Windows, and that Linux or WSL may work but is untested.

**Settled by.** Whether anyone needs it on Windows, and a Windows machine (or WSL) to test on.

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

## Notifications from "Iterum" with its logo, not Script Editor

Raised 2026-11-15 by the user: "wouldn't it be more prefessional to have it from Iterum with the logo?" The documented macOS `ITERUM_NOTIFY` example uses `osascript`'s `display notification`, which shows as from Script Editor and has no option to change the sender ([Apple: Displaying Notifications](https://developer.apple.com/library/archive/documentation/LanguageUt/Conceptual/MacAutomationScriptingGuide/DisplayNotifications.html)).

**Tried, did not work.** An AppleScript applet, `Iterum.app`, built with `osacompile` (bundle id `dev.iterum.notify`, the gh-pages `favicon.svg` as its icon via `sips` and `iconutil`, `LSUIElement`, signed ad hoc), launched with `open`, reading its message from a file. It ran and quit, and no notification appeared: `usernoted` logged `Denying message 3` and `Denying message 7 from connection <LegacyConnection identifier: dev.iterum.notify ...>`, with no permission prompt and no Notifications settings entry. Script Editor's notification over the same legacy path, minutes before, was "successfully processed ... Presenting ... as banner". Registering the applet with `lsregister -f` (the log had said `Failed to find dev.iterum.notify in LaunchServices`) changed nothing: the same two denials. Why it is denied is not known; untested guesses are that a new app cannot gain permission through the legacy path, or that an ad-hoc signature without a Team ID is refused.

**Options.**

1. **A small Swift app** using `UserNotifications`, whose `requestAuthorization` asks the user for permission ([Apple](https://developer.apple.com/documentation/usernotifications/unusernotificationcenter/requestauthorization(options:completionhandler:))); `install.sh` would build it on macOS (needs Xcode's command-line tools), and `ITERUM_NOTIFY` would call it. Whether an ad-hoc-signed app is allowed is the same open question.
2. **`terminal-notifier`** (Homebrew, third-party): `-sender` and `-appIcon`; the latter relies on a private method, and it uses the deprecated `NSUserNotification` API, which a replacement project says breaks parts of it on macOS 26 ([send/macnotifier](https://github.com/send/macnotifier)); not verified.
3. **Leave it:** Script Editor, documented in the setup guide.

**Settled by.** Whether a Swift app, ad-hoc signed, gets a permission prompt and shows "Iterum" with the logo, tried once on this Mac.
