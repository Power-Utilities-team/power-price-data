# Windows Excel setup (one-time) — connect the workbook to the live data

> This is the **live-linked path (Path A)** setup. For the whole picture — the two update
> paths, the `generate.py` one-command rebuild, and how the two stay consistent — see
> **`GENERATE.md`**. The non-technical monthly refresh is in **`Deliverables/updating-the-deck`**.

Do this **once**, on the Windows PC, in a fresh workbook. After that, the data
refreshes itself (the GitHub Action) and the workbook refreshes on open — so a
non-technical person just opens the file.

Data lives at these URLs (chart-ready, one flat table per chart):
```
BASE = https://raw.githubusercontent.com/fredhill123/power-price-data/main/published/charts/
```
| File | Chart it feeds |
|------|----------------|
| `fig1_price_sd.csv`         | Fig 1 price-volatility (SD) by year |
| `fig2_intraday_indexed.csv` | Fig 2 indexed intraday price |
| `fig2_intraday_avg.csv`     | (avg €/MWh version of Fig 2) |
| `fig3_neg_hours_annual.csv` | Fig 3 negative-hour counts |
| `fig3_cum_near_neg.csv`     | Fig 3 cumulative curve |
| `fig4_duration_curve.csv`   | Fig 4 price duration curves |
| `fig5_capture_pct.csv`      | Fig 5 capture price vs base (%) |
| `fig5_capture_abs.csv`      | (absolute €/MWh version of Fig 5) |
| `fig6_daily_minmax.csv`     | Fig 6 daily min/max spread |
| `fig7_gen_mix.csv`          | Fig 7 intraday generation mix |
| `fig9_capacity.csv`         | Fig 9 installed capacity |
| `capture_monthly.csv`       | monthly capture price |
| `g1_solar_peakhour.csv`     | **G1_SolarPeak** — solar share of the peak hour (quarterly avg) |
| `g2_price_by_month.csv`     | **G2_MonthDuck** — intraday price by month (the monthly duck) |
| `figA_monthly_price.csv`    | **A_MonthPrice** — monthly baseload price by market |
| `figB_penetration.csv`      | **B_Penetration** — wind+solar % of generation (12-mo avg) by market |
| `figC_capture_erosion.csv`  | **C_CaptureErosion** — solar/wind capture vs baseload (Germany) |
| `figD_netload_duck.csv`     | **D_NetloadDuck** — net-load duck (demand − wind − solar) by year (Germany) |

The last six (**G1_SolarPeak**, **G2_MonthDuck**, **A_MonthPrice**, **B_Penetration**,
**C_CaptureErosion**, **D_NetloadDuck**) are the newest tabs — load them the same way
(From Web → Load To → that tab's `$A$1`). The price-cannibalisation scatter, quarterly-duck and
July-spaghetti exhibits are **static images** (no query needed).

---
## PART A — 2-minute smoke test (do this first)
Prove the mechanism with one file before loading them all.
1. **Data** ▸ **Get Data** ▸ **From Other Sources** ▸ **From Web**
2. URL = `BASE` + `fig1_price_sd.csv` (i.e. the full link to that file) ▸ **OK**
3. In the preview you'll see a table (year, Germany, Spain, …) ▸ **Load**
4. A new sheet appears with the data as a table. ✅ That's it working.
5. Test **Data ▸ Refresh All** — it re-pulls from the web.

If that worked, continue. If "From Web" isn't under Get Data, it may be **Data ▸
From Web** directly — tell me what you see.

---
## PART B — load all the tables
Repeat Part A step 1–3 for each file in the table above. After each loads:
- Rename the sheet to match the file (optional but tidy).
- The loaded **table** keeps the file's name (e.g. `fig1_price_sd`) — leave it.

Tip: you can duplicate a query (right-click in **Queries & Connections** ▸
Duplicate) and just change the URL, which is faster than starting each from
scratch.

---
## PART C — set refresh-on-open (the key step)
So anyone just opens the file and it's current:
1. **Data ▸ Queries & Connections** (opens the side pane)
2. For **each** query: right-click ▸ **Properties…**
3. Tick **"Refresh data when opening the file"**
4. Untick **"Enable background refresh"** (so it finishes before the charts draw)
5. OK. Save the workbook.

---
## PART D — build the charts
Each CSV is already shaped for its chart. Use the reference PNGs in
`outputs/charts/` (the Rothschild-style versions) as the visual target.
- Select the table columns you want (e.g. for Fig 1: the `year` column + the
  five country columns) ▸ **Insert ▸ Chart**.
- The columns run out to 2035 with blanks — that's deliberate: future years fill
  in automatically on refresh with no re-linking.
- Country-year columns are named `DE_2024`, `ES_2024`, … (Fig 6/7 add a series
  suffix, e.g. `PT_2024_Solar`).

---
## PART E — link into PowerPoint (auto-updating)
1. Build/copy the chart in Excel ▸ in PowerPoint **Paste Special ▸ Paste Link**.
2. In PowerPoint: **File ▸ Info ▸ Edit Links to Files ▸** set to **Automatic**.
3. Keep the Excel file at a **stable path** (e.g. a fixed SharePoint/OneDrive or
   local folder) — the PPT links point at that path.

---
## Ongoing (no technical skill needed)
- The GitHub Action refreshes the data monthly (and can be run on demand — see
  `GITHUB.md`).
- Whoever needs the deck just **opens the Excel file** (it refreshes on open),
  then opens the PowerPoint (links update). Done.
