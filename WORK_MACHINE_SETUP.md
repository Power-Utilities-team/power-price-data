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
- **At the turn of the year** the same run folds the completed year into the frozen history and
  rebuilds the charts so they carry the new year — on the repo's copy. Mechanically: the January
  run notices the frozen history still ends two years back, fetches the just-completed year as
  well as the current one, absorbs it via `build_hourly.py --absorb-prior-year`, and commits the
  extended history. It does not depend on the Mac's raw archive.

### The two halves: DATA refreshes itself, the FILE does not

This is the single thing worth understanding about how this works, because everything
else follows from it.

|  | Comes from | How you get it |
|---|---|---|
| **The numbers** | `published/` CSVs on GitHub | Automatically, on open. Never download anything. |
| **The workbook itself** — which technologies a chart plots, how many year-series it has, tab order, the banner | The `.xlsx` file | Only by replacing the file from `deliverables/`. |

CI rebuilds **both** every run: it republishes the CSVs *and* builds a fresh
`HourlyPowerData.xlsx` / `.pptx` into `deliverables/`. Your copy on the share picks up
the first half by itself and **never** picks up the second.

Why: Power Query writes *values into cells*. A chart's category range, its series list
and its formatting live in the file's own XML. Refreshing cannot change them.

**Worked example (2026-07-30).** German nuclear was dropped from the Fig 5 capture chart
because the fleet closed in April 2023, leaving empty bars. That change moved the chart's
range from `$A$2:$A$12` to `$A$2:$A$11`. A workbook built before that change still reads
`$A$2:$A$12` after any number of refreshes — so it still draws the empty Nuclear bar. The
only way to get the fix is to take the rebuilt file.

**Rule of thumb:** if the numbers look wrong or old → refresh. If the *chart itself* is
wrong — a missing year, an unwanted technology, a gap — → replace the file.

### ⚠️ Once a year you MUST replace your workbook file. Refreshing is not enough.

This is the one genuine annual action, and it is easy to miss because everything else is automatic.

**Why refreshing cannot do it.** Each year is a separate **chart series**, and the number of series
is fixed when the workbook is built. Today's file carries seven — 2019 … 2025. The CSVs already
contain 2026 (it is excluded on purpose: an incomplete year must never be plotted). When 2026
completes, the chart needs an **eighth series**, and no refresh can add one — Power Query loads
data into cells, it does not create series. So a refreshed 2026-vintage file will keep showing
2019–2025 forever, with correct but visibly out-of-date charts.

**What to do, every January:**
1. Open the workbook and read the **Status** tab.
2. If it says **ANNUAL ROLLOVER OVERDUE — charts were built for YYYY**, that is this situation.
3. Download the newest `HourlyPowerData.xlsx` **and** `.pptx` from `deliverables/` in the repo,
   and replace both files on the network share (they must stay together — the deck links to the
   workbook by path).
4. Re-open. The Status tab should go green and the charts should show the new year.

The alarm is what tells you; you do not need to track the date yourself. And if the tab instead
says nothing is wrong but the charts are missing a completed year, the January CI run failed —
see `ROLLOVER.md`. That is the one failure with a real deadline: CI only ever fetches the current
year, so a completed year never absorbed sits in neither the history nor the fetch. The Mac holds
the full raw archive so it is always recoverable, but the longer it goes unnoticed the more the
monthly-granularity charts show a visible 12-month hole.

### For the team — who does what

Almost nobody needs to "update" anything. The three situations, in the order they come up:

| Situation | What to do | Who can |
|---|---|---|
| **Normal use** — you want current numbers | **Just open the workbook.** It pulls the latest published data on open. | Anyone |
| **You want data fresher than the last monthly run** | Open the status page and press **Start a refresh** (~20 min), then re-open the workbook. | Anyone with the link |
| **The chart itself is wrong** — a missing year, an unwanted technology | Download the newest workbook + deck from the status page and replace both on the share. | Anyone |

**The status page is the one link to share:**
<https://power-price-data.fredhill.workers.dev>
It shows when the data was last refreshed, when the next automatic run is due, download
links for all four files, and the refresh button. No login, no GitHub account, nothing to
install — it works from a locked-down machine because it is just a web page. The link is
also in cell A6 of the workbook's `READ_ME_FIRST` tab.

**What the team does NOT need:** a GitHub account, Power Query knowledge, this Mac, or any
admin rights. Nobody should hand-edit the data tabs — they are Power Query load targets and
anything typed there is overwritten on the next refresh, and can shift columns and detach a
chart.

**The refresh button is rate-limited on purpose:** it refuses if a run is already going or
one finished in the last 30 minutes, so two people pressing it cannot start duplicate runs.

### Triggering a refresh yourself, without a terminal

You do **not** need the Mac, Claude Code, admin rights, or any local install. `workflow_dispatch`
is enabled, so the workflow has a **Run workflow** button in the browser:

> github.com/fredhill123/power-price-data → **Actions** → *Refresh ENTSO-E power-price data* →
> **Run workflow** → **Run workflow**

It takes ~20 minutes, then commits fresh CSVs and rebuilt deliverables. A browser and a GitHub
login with **write** access to the repo is the only requirement — the sandboxed Windows machine
can do this, since it is just a web page.

Note it cannot be triggered *from inside Excel*: Power Query only issues unauthenticated GETs,
while starting a run needs an authenticated POST. It is technically possible to POST from Power
Query with a personal access token in the query — **do not do this.** It would put a credential
with write access to the repo inside a workbook sitting on a shared drive.

The only reason to fetch a fresh copy from `deliverables/` is to make the *charts* show a newly
completed year — the data in your existing file is current either way. That is not optional once
a year has completed, though: see the annual-replacement section above.

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
