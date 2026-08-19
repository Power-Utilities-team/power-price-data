# Power Price Data — conventions

Self-refreshing ENTSO-E price pipeline. THE ORIENTATION DOC IS `INDEX.md`; the eight
root docs each own one concern:
README (overview) · GITHUB.md (Actions ops + handover + GH_TOKEN rotation) ·
GENERATE.md (rebuild) · CHARTS.md · ROLLOVER.md (year-freeze) · EXCEL_SETUP.md ·
WORK_MACHINE_SETUP.md · LINKING_GUIDE.md.
Sanctioned exceptions: this project embeds its own `.git`/`.github` (it IS the GitHub
pipeline repo `Power-Utilities-team/power-price-data`) and keeps `assets/` + `published/`
(stable raw-URL surface for the workbook). No sources.jsonl — provenance is the
pipeline itself (ENTSO-E API, fetch logged in CI).
