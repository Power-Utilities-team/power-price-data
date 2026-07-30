# Power Price Data — index

_Structure note (2026-07-16): new project. ENTSO-E auto-updating power-price dataset →
fixed-cell Excel → linked PowerPoint charts (Rothschild/Redburn style)._

## Orientation
- `README.md` — what it is, architecture, how to update.
- `current-status.md` — dated live state (Phase 5 complete: two update paths + shared spec).
- **`GENERATE.md`** — the two update paths (live-linked vs Claude-generated), `generate.py`, the
  `deck_spec.py` single source of truth, and the consistency guarantee. **Start here for the deck system.**
- **`WORK_MACHINE_SETUP.md`** — Fred's remaining to-do on the Windows work PC (wire 2 queries, place files). ← **the exit checklist**
- `EXCEL_SETUP.md` — one-time Power Query setup for the live-linked workbook (Path A).
- `Deliverables/updating-the-deck.{md,html,pdf}` — non-technical monthly-refresh one-pager for the team.
- `LINKING_GUIDE.md` — how to link the workbook to auto-updating PPT charts.
- `_meta/sources.jsonl` — source ledger (ENTSO-E; IT PUN proxy caveat).

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
| `_tools/refresh.sh` | one-shot update (fetch → build → summarise → excel) |
| `data/raw/` · `data/processed/` | Parquet store + DuckDB |
| `outputs/` | `PowerPriceData.xlsx` + `charts/` |
| `250428_EuropeanUtilities_RedburnAtlantic.docx` | source deck (chart spec) |

## Stable paths (don't move — PPT links depend on them)
- `outputs/PowerPriceData.xlsx`
