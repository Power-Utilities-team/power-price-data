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
| Best for | routine monthly refresh (see `EXCEL_SETUP.md`) | ad-hoc "give me the latest now" |

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
Pipeline: `[--fresh] fetch → build_hourly → summaries → extra_summaries → chart_csv` then
`render_all → build_static_deck`, `build_frozen_excel`, `add_phase4_charts → build_deck`, and finally
`check_consistency` (which **fails the run** if the two decks disagree).

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

## The 19 workbook charts
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
