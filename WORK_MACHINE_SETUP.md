# Your workflow — Windows work machine

_Verified end-to-end on 2026-07-21 by running the full GitHub Actions workflow
(run 29823518203): data fetched, CSVs published, and all four deliverables rebuilt
and committed by CI, with `CONSISTENCY: PASS`._

**There is no setup left, and nothing you need to run.** All **19** Power Query connections
ship inside the workbook with refresh-on-open already ticked.

> ⚠️ **Ignore the `READ_ME_FIRST` tab.** It is left over from the original build and still
> walks you through adding queries by hand (`Get Data > From Web > …`). That work is done —
> all 19 are wired. Nothing on that tab needs doing. (Being fixed; see `pending-updates.md`.)

---

## The whole routine

1. **Open `HourlyPowerData.xlsx`** — it refreshes itself on open.
2. **Open `HourlyPowerData.pptx`** ▸ **File ▸ Info ▸ Edit Links to Files ▸ Update Now**
   (or set the links to **Automatic** once, and even this goes away).

That's it, monthly and forever.

Both files must sit **together** at the path the deck links to:
```
\\redburn.local\core\data\Oils\Oils 2.0\Power & Utilities Team Resources\Sector Presentation\
```
(the `H:\Oils\Oils 2.0\…` mapped drive). If that path ever changes, the deck's links must be
rebuilt to match — that is the one change that needs someone to rebuild the file.

## What happens without you

- **Monthly** (2nd of each month, 06:00 UTC) GitHub Actions pulls fresh ENTSO-E data,
  republishes the chart CSVs, and **rebuilds all four deliverables**, committing them to
  `deliverables/` in the repo. Your workbook picks the data up on open.
- **At the turn of the year** the same run folds the completed year into the frozen history
  and rebuilds the charts so they carry the new year. Nothing manual, no rollover to remember.
  Mechanically: the January run notices the frozen history still ends two years back, fetches
  the just-completed year as well as the current one, absorbs it via
  `build_hourly.py --absorb-prior-year`, and commits the extended history. It does not depend
  on the Mac's raw archive.

  **The one thing worth doing yourself: in mid-January, open the workbook and read the Status
  tab.** If it is green, the rollover worked and there is nothing to do. If it says
  *ANNUAL ROLLOVER OVERDUE*, the January run did not do its job — and that is the one failure
  with a real deadline, because CI only ever fetches the current year, so a completed year that
  is never absorbed is not in the history either and the dataset loses it. `ROLLOVER.md` is the
  manual fallback and the Mac holds the full raw archive, so it is recoverable — but the longer
  it goes unnoticed the more the monthly-granularity charts show a visible 12-month hole.

The only reason to fetch a fresh copy from `deliverables/` is if you want the *charts* to show
a newly completed year — the data in your existing file is current either way. Grab the newest
`HourlyPowerData.xlsx` / `.pptx` from the repo when the Status tab tells you to.

## The Status tab — read this if something looks off

The workbook **opens on a `Status` sheet**. It compares the published refresh record against
today's date on your machine and says one of:

- ✅ *"OK - data is current. Last refreshed …, data through …"* — nothing to do.
- ⚠️ *"STALE DATA - the monthly refresh has not run for N days"* — the GitHub job has stopped
  running. Someone needs to look at the Actions tab.
- ⚠️ *"ANNUAL ROLLOVER OVERDUE - charts were built for YYYY"* — download the latest files from
  `deliverables/`.

Both warnings are in large red text and cannot be missed. Green means genuinely fine.

**To answer "how fresh is this file?" — that green line is the answer, and it is always on
screen when you open the workbook.** It reads e.g. *"Last refreshed 2026-07-21, data through
2026-07-21 09:00"*: the first date is when the GitHub job last ran, the second is the last hour
of actual price data. Nothing else needs checking, and you do not need the repo to find out.

Two things the banner is deliberately not: it does not fire the instant a run is missed (the
tolerance is 45 days, which has to exceed the ~30-day cadence plus slack, so one missed run is
survived and two are caught), and it cannot tell you a run *failed* — a failed run simply does
not update the record, so the day count keeps climbing until it trips. GitHub emails the repo
owner when a scheduled run fails, which is the faster signal.

## Two things not to do
- **Never click "Recover"** if Excel offers to repair the workbook. Repair strips Power Query,
  which is the one thing that would cost real work. Send the file to be fixed instead.
- **Don't hand-edit the data tabs.** They are Power Query load targets; anything typed there is
  overwritten on refresh, and pre-seeded cells can shift the columns and detach a chart.

## What needs no setup at all
`HourlyPowerData_frozen.xlsx` and `HourlyPowerData_snapshot.pptx` are fully self-contained —
open and use. They're rebuilt monthly alongside the live pair.

_System overview: `GENERATE.md`. Manual rollover fallback (only if CI is broken): `ROLLOVER.md`._
