# Annual rollover — FALLBACK ONLY

> **This is no longer a routine step.** As of 2026-07-21 the GitHub Actions run does the
> rollover itself: `build_hourly.py --absorb-prior-year` folds the completed year into the
> frozen history, and CI then runs `generate.py` to rebuild the charts with the new year.
> Verified end-to-end (run 29823518203).
>
> **Follow this document only if CI is broken** — e.g. the Status tab in the workbook warns
> that the rollover is overdue, or the Actions run has been failing. It is also the reference
> for what the automation is doing and why.

This file is written to be self-contained: hand it to any assistant (or follow it
yourself) with no other context. Read "Why" before running anything — the checks matter
more than the commands.

---

## 0. What this system is (30 seconds)

European hourly power-price analysis for five markets (Germany, Spain, Portugal, France,
Italy), 2019 → present, from the ENTSO-E Transparency Platform.

- **Repo:** `github.com/fredhill123/power-price-data`
- **Local project:** `~/Claude Projects/Power Price Data` (macOS; this is the only machine
  holding the full raw archive — `data/raw/` is deliberately NOT in the repo)
- **Python env:** `_tools/.venv` (activate with `source _tools/.venv/bin/activate`, run
  everything from inside `_tools/`)
- **API key:** `_tools/.entsoe_key` locally; `ENTSOE_API_KEY` GitHub secret in CI. Never hardcode it.
- **Monthly automation:** `.github/workflows/refresh.yml`, **07:23 UTC on the 2nd** — fetches the
  current year, rebuilds the chart CSVs, validates the packages on a Windows runner, checks that
  no published feed has shrunk, and only then commits to `published/charts/`.
  ⚠ At the January rollover the coverage guard reads the window slot labels from
  `published/charts/status.csv` to follow the slots as they advance. If you hand-edit that file
  during a rollover, do it before the run, not after — the guard compares slot `w_k` against its
  previous position and a mismatched label is what would make it fire spuriously.
- **Deliverables:** `HourlyPowerData.xlsx` (live, Power-Query linked) + `HourlyPowerData.pptx`
  (linked deck), plus a self-contained `_frozen.xlsx` / `_snapshot.pptx` pair.

## Why the rollover is necessary (do not skip — this is the failure it prevents)

`build_hourly.py` runs in two modes:

- **incremental** (what CI does every month): take the **current** year from freshly-fetched
  raw data, and stitch it onto a committed frozen history, `data/processed/master_fixed.parquet`.
- **full** (`--full`): rebuild every year from the raw archive, then **re-freeze** all
  *completed* years into `master_fixed.parquet`.

`master_fixed.parquet` currently holds **2019–2025**. CI only ever fetches the current year.
So on 2 January 2027, CI fetches 2027 and stitches it onto 2019–2025 — and **2026 disappears
from the dataset entirely**. The raw 2026 data needed to fix it exists only on the Mac.

**Consequence if skipped:** the fifteen year-pinned charts keep showing 2019–2025 (stale but
correct), while the four monthly-granularity charts (G1 solar peak, A monthly price,
B penetration, C capture erosion) develop a **visible 12-month hole** where 2026 should be.
No figure becomes silently wrong, but the deck looks broken and the dataset loses a year.

---

## 1. Pre-flight

```bash
cd ~/"Claude Projects/Power Price Data"
git pull                                  # take CI's monthly data commits first
source _tools/.venv/bin/activate
cd _tools
python -c "import pandas as pd, config as cfg, os; \
d=pd.read_parquet(os.path.join(cfg.PROC_DIR,'master_fixed.parquet'), columns=['ts_utc']); \
y=pd.to_datetime(d.ts_utc,utc=True).dt.year; print('frozen history covers', y.min(), '-', y.max())"
```

**Gate:** if `frozen history covers 2019 - <last completed year>`, the rollover has already
been done — stop. Otherwise continue.

## 2. Fetch the completed year to completion

CI only ever pulled the completed year *as it went*, so its final days may be missing, and
ENTSO-E revises data after publication. Re-fetch the whole year.

```bash
# replace 2026 with the year that just finished
python fetch.py --years 2026 --force
python fetch.py --years 2026            # second pass fills any 503 gaps
```

**Gate:** re-run the second pass until it reports no new files. ENTSO-E returns intermittent
503s; a partial fetch here silently truncates the year.

## 3. Rebuild everything and re-freeze the history

```bash
python build_hourly.py --full           # rebuilds all years from raw AND re-freezes completed ones
python summaries.py
python export_csv.py
python chart_csv.py
python extra_summaries.py
```

**Gate:** the `--full` run must print `refroze history (<YYYY>)`. Then confirm:

```bash
python -c "import pandas as pd, config as cfg, os; \
d=pd.read_parquet(os.path.join(cfg.PROC_DIR,'master_fixed.parquet'), columns=['ts_utc']); \
y=pd.to_datetime(d.ts_utc,utc=True).dt.year; print('frozen history now covers', y.min(),'-',y.max()); \
print('hours in the new year:', (y==y.max()).sum())"
```
A full year for five countries is roughly 43,000–44,000 hourly rows. Materially fewer means
step 2 didn't complete — go back, don't proceed.

## 4. Rebuild the deliverables

```bash
python generate.py --deliver
```

This renders the charts, rebuilds both decks and both workbooks, re-injects all 18 Power
Query connections, and runs the consistency gate. It copies the four files to `~/Downloads`.

**Gate:** the run must end with
`CONSISTENCY: PASS — both decks match deck_spec (… ) + workbook charts 1-19`.
If it fails, stop and fix — never ship a failed consistency run.

## 5. Verify the new year actually appears

```bash
python - <<'PY'
import zipfile, re, csv
z = zipfile.ZipFile("../outputs/HourlyPowerData.xlsx")
hdr = next(csv.reader(open("../outputs/csv/charts/fig5_capture_pct.csv")))
def colnum(L):
    n = 0
    for c in L: n = n*26 + ord(c)-64
    return n
x = z.read("xl/charts/chart6.xml").decode()
cols = [re.search(r'\$([A-Z]+)\$', m).group(1)
        for m in re.findall(r"<c:val>.*?<c:f>([^<]+)</c:f>", x, re.S)]
print("Germany capture chart series:", [hdr[colnum(c)-1] for c in cols])
PY
```
The last series must be the **newly completed year**. If it still ends at the previous year,
`generate.py` ran against stale summaries — redo step 3.

Also open `HourlyPowerData.pptx` and check the single-year captions (Portugal intraday mix,
Germany daily min/max) now name the new year. They are generated from data coverage, so they
roll automatically — a caption still naming the old year means the data didn't roll.

## 6. Publish

```bash
cd ..
cp outputs/csv/charts/*.csv published/charts/
git add published data/processed/master_fixed.parquet data/processed/capacity_fixed.parquet
git commit -m "annual rollover: freeze <YYYY> into history, rebuild charts"
git push
```

**`master_fixed.parquet` and `capacity_fixed.parquet` MUST be committed** — they are what CI
uses as its history for the next twelve months. This is the single most important commit of
the year; without it CI keeps rebuilding from the old frozen history.

**Gate:** confirm the published CSVs resolve:
```bash
curl -sI https://raw.githubusercontent.com/fredhill123/power-price-data/main/published/charts/fig5_capture_pct.csv | head -1
```
Expect `HTTP/2 200`.

## 7. Hand over

Send Fred the four files from `~/Downloads` (`HourlyPowerData.xlsx`, `HourlyPowerData.pptx`,
`HourlyPowerData_frozen.xlsx`, `HourlyPowerData_snapshot.pptx`). He replaces the two live
files in the shared Redburn folder:
```
\\redburn.local\core\data\Oils\Oils 2.0\Power & Utilities Team Resources\Sector Presentation\
```
and then does **File ▸ Info ▸ Edit Links to Files ▸ Update Now** in the deck.

---

## Things that will bite you

- **Never open the live workbook with `openpyxl` and save it.** It silently drops Power Query,
  charts and drawings. All workbook edits go through the XML-surgery scripts in `_tools/`.
- **`DISPLAY_END_YEAR` in `config.py` must stay 2035.** Chart column references assume a
  17-year block per country; shrinking it shifts every country's block and the Portugal chart
  starts plotting French data.
- **If Excel ever offers to "Recover" the workbook, decline.** Recovery strips Power Query.
  Send the file to be repaired at the XML level instead.
- **Don't hand-edit `published/charts/*.csv`.** They are build outputs; CI overwrites them.
- Fifteen of the nineteen charts carry one series per year, so a new year only ever appears
  via a `generate.py` rebuild — never via a Power Query refresh alone.
