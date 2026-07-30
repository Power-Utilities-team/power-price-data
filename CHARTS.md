# Chart styling pipeline (Redburn look) — how it's built & maintained

The delivered workbook's 9 charts are native Excel charts (so they auto-update on
Power-Query refresh and drive PowerPoint links). They are styled to the Redburn
house look by editing ONLY the chart XML inside the .xlsx — Power Query is never
touched. **openpyxl is never used to save a query file** (it would strip PQ).

## The two scripts (run in order, on Fred's query-set-up .xlsx)
1. `_tools/redburn_charts.py "<in>.xlsx" "<styled>.xlsx"`
   - No chart titles; Arial 8.5pt; house palette (NAVY #2E3E80, TEAL #5FA1AD,
     SAGE #ACBFB7, FOREST #3D664A, GOLD #CC9F53, WINE #8A1E41).
   - Multi-year charts colour **latest year = NAVY**, older years fade through the
     palette then grey.
   - Horizontal-only #E5E5E5 gridlines; no-frame bottom legend; **clean series
     names** (no `_neg` / `DE_2024_` suffixes) written as literals so a PQ refresh
     can't revert them; accounting-negative value axis `(25)` / `(20%)`.
   - **Year cutoff (Mixed, agreed with Fred 2026-07-17):** annual-stat charts stop
     at the last COMPLETE year — Fig1 (SD), Fig3 (neg hours), Fig5 (capture),
     Fig9 (capacity) — set by `cap_row` (row-based) or `drop_last` (year-series).
     Profile/duration charts keep the latest partial year — Fig2, Fig3cum, Fig4.
2. `_tools/move_charts.py "<styled>.xlsx" "<final>.xlsx"`
   - Moves all 9 charts onto a single **`Charts`** worksheet (leftmost tab), each
     with a navy caption above it; strips the charts from the Fig data sheets.
   - Pure container surgery: PQ, tables, queryTables, sharedStrings, chart parts
     all copied byte-for-byte. Validated: openpyxl loads it; LibreOffice renders it.

Both only rewrite chart / container XML, so the file Fred set his queries up in
stays fully query-enabled.

## ⚠️ Annual maintenance — extend the chart year-ranges when a new year lands
Because the charts cap their plotted range at the last data year (to hide empty
future years), a NEW year does **not** auto-appear. This is the accepted trade-off
for the clean look. Once a year, after a year completes:
- **Annual-stat charts** (Fig1/3/5/9): bump the cutoff — in `redburn_charts.py`
  raise `cap_row` by one row (e.g. 8→9 to include 2026) and drop the `drop_last`
  once 2026 is complete.
- **Year-series charts** (Fig2/4 etc.): a new year is a new *column*; extend each
  series' `cat`/`val` ref by one column.
- Then re-run both scripts on the current query file and re-save.

This is a maintainer task (needs Python) — the **monthly value refresh** on Fred's
work PC (Data → Refresh All / refresh-on-open) needs none of this and keeps every
existing point current on its own.

## PowerPoint deck (HourlyPowerData.pptx) — linked to the workbook
`_tools/build_deck.py <template.pptx> <charts_source.xlsx> <out.pptx>` builds a
Rothschild-style deck on the **P&U Crash Course 2026** template (inherits its
master/layouts/theme, Calluna+Arial fonts, R&Co navy/blue palette). Title slide +
6 content slides group the 9 charts thematically (three 2-up, three 1-up for the
detailed multi-series charts). Each chart is a **linked chart** — a pure external
link (no embedded workbook), exactly like the team's existing decks:
`<c:externalData>` → `oleObject` rel, `TargetMode="External"`, pointing at
`file:///\\redburn.local\core\data\Oils\Oils 2.0\Power & Utilities Team Resources\Sector Presentation\HourlyPowerData.xlsx`
(the UNC form of the `H:\Oils\Oils 2.0\…` mapped drive — matches how their other
linked decks resolve). Charts display from cached data and refresh from the
workbook on the PC (File → Info → Edit Links to Files → Update, or right-click →
Edit Data). Both files must live in that one folder. Change the link path in one
constant (`LINK_TARGET`) and rebuild if the mapping differs.
