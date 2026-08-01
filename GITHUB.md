# Auto-refresh (GitHub Actions) — operations & handover

This repo keeps the ENTSO-E power-price CSVs fresh automatically, so the Excel
workbook (set to *refresh-on-open*) is always current — a non-technical user
just opens the file. Nobody has to run anything.

## How it works
- `.github/workflows/refresh.yml` runs on a schedule (monthly, **2nd @ 07:23 UTC**)
  and on demand. It fetches ENTSO-E, rebuilds the summaries, and publishes CSVs
  to `published/` (served at stable raw URLs).
- The workbook's Power Query connections point at those URLs and refresh on open.

### The four jobs, and why they are in that order
`fetch` → `build` → `validate` → `publish`. Only the **last** one writes to the
repository, and that is the whole point: everything that can reject a build runs
first, so a bad package or a shrunken feed never reaches `main`.

| job | runner | what it does |
|---|---|---|
| `fetch` | ubuntu ×5 | one country each, in parallel; caches `data/raw` between runs |
| `build` | ubuntu | assembles, summarises, exports, rebuilds the workbook and decks. **Commits nothing** — it uploads everything as the `publish-payload` artifact |
| `validate` | windows | Microsoft's own Open XML SDK on all four deliverables. Free and unlimited on a public repo, and it catches the schema faults our hand-written checks do not |
| `publish` | ubuntu | asserts coverage has not shrunk, then commits and pushes |

Until 2026-07-31 the build job committed and `validate` ran afterwards, so an
invalid workbook landed in `deliverables/` and only then turned the run red.

### The coverage gate
`publish` runs `_tools/check_coverage.py` before it commits. Every other check asks
whether the data is *valid*; this asks whether it is the data we already had, **plus
more**. It compares each published feed against the previous commit on row count and
on populated cells per column, and fails the run on a large drop.

It exists because on 2026-07-31 a cold cache made the incremental fetch publish a
31-day "year" in place of 212 days. It shipped because the run was fast and green and
every validator passed — correctly, since a 31-day series is perfectly valid data. It
is just the wrong data.

**If it trips**, do not loosen the tolerance. Either the fetch lost data (re-run with
`full_refetch=true`), or the shrink is deliberate — a clipping fix, a chart
restructure — in which case commit that change yourself and push, since the gate only
runs in CI. `_tools/coverage_eyeball.py` draws the coverage so you can see which.

The same script also asserts that the month which has just closed actually **arrived** in
the monthly exhibits. That is a different failure from a shrink and the shrink check
cannot see it: if the month never appears, last month's feed ended in June and this
month's also ends in June, so nothing got smaller. It happens when coverage has not yet
passed the month's final hour at run time — the run then succeeds and silently omits the
month for a further month. This is why the schedule sits on the 2nd rather than the 1st;
see the reasoning block above the `cron:` line.

## Run it manually (anyone with repo access)
GitHub → **Actions** tab → *Refresh ENTSO-E power-price data* → **Run workflow**.
Takes ~10–15 min (it only re-fetches the current year; 2019–2025 history is
frozen in `data/processed/master_fixed.parquet`). When it finishes,
`published/*.csv` is updated; open the workbook and it pulls the new data.

## Once a year (fold the completed year into the frozen history)
In January, after a year finishes, re-freeze so it stops being re-fetched:
```
cd _tools && python fetch.py && python build_hourly.py --full
```
then commit the updated `data/processed/master_fixed.parquet` +
`capacity_fixed.parquet`. (Optional — skipping it just means the just-ended year
keeps being re-fetched live, which still works, only slightly slower.)

## The API key
Stored as the encrypted repo **Secret** `ENTSOE_API_KEY` (Settings → Secrets and
variables → Actions). It is never in the code. Get a free key at
https://transparency.entsoe.eu/ (register → request API access).

## Handover to a colleague / your company
1. **Give them access** — add them as a collaborator (Settings → Collaborators),
   or **transfer** the repo into your company's GitHub Organization
   (Settings → General → Transfer ownership).
2. **Swap the API key** — the successor creates their own ENTSO-E key and updates
   the `ENTSOE_API_KEY` Secret. (Do this if the original key owner leaves.)
3. **If the repo path changed** (e.g. personal → org), update the CSV URLs in the
   workbook once: Data → Queries & Connections → edit each query's source URL to
   the new `raw.githubusercontent.com/<owner>/<repo>/main/published/<name>.csv`.
   Keeping the repo in a stable org avoids this entirely.
4. Nothing else is account-specific. The pipeline, schedule and docs travel with
   the repo.

## Change the refresh cadence
Edit the `cron:` line in `.github/workflows/refresh.yml` (uses standard cron, UTC).

## If a run fails
Open the failed run under **Actions** to see logs. Most failures are transient
ENTSO-E 503s — just re-run. The workflow already does a second fetch pass to fill
any gaps; a re-run fills the rest.
