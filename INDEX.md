# Power Price Data — index

_Structure note (2026-07-16): new project. ENTSO-E auto-updating power-price dataset →
fixed-cell Excel → linked PowerPoint charts (Rothschild/Redburn style)._

_Updated 2026-08-26: Great Britain added as a sixth market (Elexon, ECB, DESNZ, because GB
left ENTSO-E in June 2021), plus the hydro-reservoir exhibits and 65 further charts. The
workbook is now 26 sheets and 84 charts, built end to end by CI._

## Orientation
- `README.md` — what it is, architecture, how to update.
- `current-status.md` — dated live state (Phase 5 complete: two update paths + shared spec).
- **`GENERATE.md`** — the two update paths (live-linked vs Claude-generated), `generate.py`, the
  `deck_spec.py` single source of truth, and the consistency guarantee. **Start here for the deck system.**
- **`WORK_MACHINE_SETUP.md`** — Fred's remaining to-do on the Windows work PC (wire 2 queries, place files). ← **the exit checklist**
- `EXCEL_SETUP.md` — one-time Power Query setup for the live-linked workbook (Path A).
- `Deliverables/updating-the-deck.{md,html,pdf}` — non-technical monthly-refresh one-pager for the team.
- `LINKING_GUIDE.md` — how to link the workbook to auto-updating PPT charts.
- Source provenance: the pipeline itself (ENTSO-E API; IT PUN proxy caveat in CHARTS.md). (A stray 2-row `_meta/sources.jsonl` DID exist despite the 2026-08-05 correction saying otherwise — archived 2026-08-08 to `archive/orphan-sources-jsonl-2026-08-08.jsonl`; provenance remains the pipeline itself.)
- Also at root: `CHARTS.md`, `ROLLOVER.md`, `GITHUB.md` (ops + handover + GH_TOKEN rotation), `CLAUDE.md` (added 2026-08-05).
- `assets/`, `published/` — stable raw-URL surface for the workbook; `.git`/`.github` — this project IS the GitHub pipeline repo (sanctioned).

## Map
| Path | What |
|---|---|
| `_tools/` | pipeline (`.venv` here — do not rename this dir) |
| `_tools/config.py` | countries, zones, tech taxonomy, year handling, paths |
| `_tools/fetch.py` | pull raw ENTSO-E → `data/raw/` (resumable) |
| `_tools/build_hourly.py` | hourly UTC master → `data/processed/` + DuckDB |
| `_tools/summaries.py` | 10 derived tables → `data/processed/summaries/` |
| `_tools/build_excel.py` | fixed-cell workbook → `outputs/PowerPriceData.xlsx` |
| `_tools/charts.py` | Rothschild-style reference PNGs → `outputs/charts/` |
| `_tools/validate.py` | adversarial checks vs Redburn figures |
| `_tools/check_coverage.py` | published data may not SHRINK vs the previous commit — gates the CI publish |
| `_tools/fetch_uk.py` | Great Britain: Elexon (price, generation, load), ECB (GBP/EUR), DUKES (capacity) |
| `_tools/fetch_hydro.py` · `summarise_hydro.py` | ENTSO-E A72 weekly reservoir levels → the shaded-band exhibits |
| `_tools/add_extra_charts.py` | CaptureVsBase plus the per-country, monthly and hydro charts |
| `_tools/capture_vs_base.py` | the CaptureVsBase layout, as data rather than as a hand-built sheet |
| `_tools/bake_frozen_values.py` | fills every chart cache so the frozen copy renders without recalculating |
| `_tools/check_reference_stability.py` | refuses a layout that MOVED an existing column or row (linked decks depend on this) |
| `_tools/check_chart_captions.py` | does the chart captioned "X" actually plot X's data |
| `_tools/check_split_parity.py` | the legacy five and the `_extra` sixth must reach the same period |
| `_tools/opc_validate.py` · `opc_validate_fixtures.py` | package joins and OOXML child order, with fixtures proving the checks still fire |
| `_tools/repoint_workbook.py` | every query must name the repo we actually publish to |
| `_tools/coverage_eyeball.py` | draws what that guard counts → `outputs/coverage.png` |
| `_tools/refresh.sh` | one-shot update (fetch → build → summarise → excel) |
| `data/raw/` · `data/processed/` | Parquet store + DuckDB |
| `outputs/` | `PowerPriceData.xlsx` + `charts/` |
| `250428_EuropeanUtilities_RedburnAtlantic.docx` | source deck (chart spec) |

## Stable paths (don't move — PPT links depend on them)
- `outputs/PowerPriceData.xlsx`
