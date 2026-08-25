# Generating & maintaining the deck — the two update paths

There are **two ways** the Hourly Power Data deck gets updated. They are kept **consistent by
construction** (one shared spec + a check that fails the build on drift).

## The two paths

| | **Path A — live-linked** (team self-serve) | **Path B — Claude-generated** (on demand) |
|---|---|---|
| Who runs it | anyone on the team, in Excel/PowerPoint | Claude, via `generate.py` |
| Data source | Power Query pulls the published CSVs on open | fresh ENTSO-E pull (or CSVs on disk) |
| Files | `HourlyPowerData.xlsx` + `HourlyPowerData.pptx` | `HourlyPowerData_frozen.xlsx` + `HourlyPowerData_snapshot.pptx` |
| Self-contained? | no — deck links to the workbook | yes — charts embedded as images / hardcoded cells |
| Best for | the routine scheduled refresh (see `EXCEL_SETUP.md`) | ad-hoc "give me the latest now" |

Both paths render the **same exhibits, captions and layout** — see the consistency guarantee below.

## The four deliverables (all rebuilt by one command)
- **`HourlyPowerData.xlsx`** — live workbook, Power-Query linked, refresh-on-open.
- **`HourlyPowerData.pptx`** — deck with charts *linked* to that workbook.
- **`HourlyPowerData_frozen.xlsx`** — identical structure + charts, but data **hardcoded** and all Power
  Query stripped (charts recalc from static cells). Drop-in for a fixed month; the linked deck can be
  re-pointed at it.
- **`HourlyPowerData_snapshot.pptx`** — fully self-contained deck (all exhibits embedded as images).

## `generate.py` — one command
```bash
cd _tools && source .venv/bin/activate
python generate.py              # rebuild all 4 from data already on disk
python generate.py --fresh      # pull ENTSO-E to today first, then rebuild
python generate.py --deliver    # also copy the 4 files to ~/Downloads
```
Pipeline: `[--fresh] fetch → fetch_uk → fetch_hydro → build_hourly → summaries → chart_csv →
extra_summaries → summarise_hydro → build_status → publish` then `render_all → build_static_deck`,
`build_frozen_excel`, `add_phase4_charts → add_extra_charts → build_deck`, and finally
`check_consistency` (which **fails the run** if the two decks disagree).

**Three ordering facts that are load-bearing, all fixed 2026-08-25:**
- `chart_csv` runs BEFORE `extra_summaries`, because the latter's `line_windows` reads the
  fig2/fig3/fig4 CSVs the former writes. The old order built that table from the PREVIOUS run's
  files, which was invisible until a new country's columns did not exist there yet and its charts
  came out blank.
- The built CSVs are staged into `published/` BEFORE the workbook is built, the way CI has always
  done it. `add_power_queries` and `add_extra_charts` both read `published/charts` to size load
  targets and resolve chart columns, so building from last run's copies gives charts pointing at
  last month's layout.
- `add_extra_charts` runs after `add_status_sheet` (its charts name their year series from the
  Status sheet's rolling cells) and before `add_power_queries` (it creates two tabs that script
  then wires).

> **Freshness note:** `--fresh` refreshes the static + frozen outputs to today. The **linked** workbook is
> rebuilt structurally; its live data currency comes from the team's Power Query refresh (by design).

## Single source of truth — `deck_spec.py`
Every builder reads `_tools/deck_spec.py` and nothing else for structure/captions. It holds the ordered
slides, and per exhibit: `id`, `caption` (navy bar), `box` (L/R/1up), `chart` (linked workbook chart #),
`png` (static image), and a `render` recipe (how `render_all` draws it, incl. country + gating).

**To relabel or move a chart:** edit its entry in `deck_spec.py`, run `generate.py`. Both paths follow.

**To ADD a chart:**
1. add an exhibit to `deck_spec.py` (caption, box, next chart #, png stem, render recipe);
2. add its workbook chart in `add_phase4_charts.py` (for Path A) — clone the nearest Redburn chart XML;
3. the render recipe already covers Path B (via `render_all.py`'s dispatch);
4. run `generate.py` — `check_consistency.py` fails if the paths don't match.

## Consistency guarantee — `check_consistency.py`
Asserts both built decks' slide titles + kickers + navy-bar captions equal `deck_spec`, in order, and the
workbook holds charts 1–19. Runs at the end of `generate.py`; exit 1 on any drift. **This is what keeps the
two update methods from silently diverging.**

## Data-completeness gating — `completeness.py`
Period charts never show a half-finished period. From the data's coverage end it computes the last complete
year / quarter / month; then:
- annual-stat charts → years ≤ last complete year;
- single-year charts (Fig6 min/max, Fig7 gen-mix) → the last complete year;
- intraday **profiles** → keep the current partial year, labelled **"<yr> YTD"** (both paths);
- G1 solar-share (quarterly-avg) → complete quarters only.

## Environment
All scripts run on **`_tools/.venv`** (uv-managed: pandas, pyarrow, matplotlib, openpyxl, python-pptx,
lxml). ENTSO-E key at `_tools/.entsoe_key`. The house chart style comes from the `chart-style` skill.

## Where each country's data comes from
DE, ES, PT, FR and IT are ENTSO-E. **GB is not, and cannot be**: Great Britain stopped publishing to
the Transparency Platform on 15 June 2021 under the post-Brexit Trade and Cooperation Agreement.
`fetch_uk.py` fills it from Elexon (generation, load), the ECB (GBP/EUR) and DESNZ DUKES 5.12.A
(capacity), writing the same raw parquet shapes so nothing downstream needs a GB branch. Its header
carries the full evidence, including why the `UK` ENTSO-E domain is a trap (it returns Northern
Ireland alone) and why the GB price is a market index rather than a day-ahead auction.

**The twelve inherited figure tabs are frozen at five countries.** Their Excel tables are a fixed 86
columns and are not rebuilt from their CSVs, so a sixth market's columns would land outside the table
where no chart or refresh reaches them. Every chart reads a rolling-window tab instead, and those ARE
rebuilt, so they widen on their own. See `config.LEGACY_CSV_COUNTRIES`.

## The workbook charts
Charts 1–15 are the original figures + Phase-4 country variants + G1/G2. Charts **16–19** are the
2026-07-19 "market-state" block, all live-linked: **16** monthly baseload price by market (A),
**17** wind+solar penetration 12-mo avg (B), **18** solar/wind capture erosion, Germany (C),
**19** net-load duck, Germany (D). The 5th new exhibit — **price-cannibalisation scatter** (F) — is a
**static image** in BOTH decks (a 9k-point year-coloured scatter is not a viable live Excel chart), so it
has no workbook chart and needs no query. Both decks stay consistent because F renders the identical PNG in each.

## Still to wire once (Path A only)
Six Power Query connections remain to be added in the live workbook (see `EXCEL_SETUP.md` /
`WORK_MACHINE_SETUP.md`): `G1_SolarPeak`, `G2_MonthDuck`, `A_MonthPrice`, `B_Penetration`,
`C_CaptureErosion`, `D_NetloadDuck` ← their matching CSVs. The frozen workbook already has all six filled.
