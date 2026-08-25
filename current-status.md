# Power Price Data — current status

> **Open items do NOT live in this file.** This is dated history — entries below may be
> superseded by later ones further down. The authority on what is still open is
> `pending-updates.md` § OPEN COMMITMENTS. Add an open item there, not here.

_Last updated: 2026-08-10_

## Update 2026-08-10 — folding in the 2 to 8 August work

Written by the 2026-08-09 friction audit's fold, which found this file eight days behind
substantive changes. The entry below it, dated 1 August, is SUPERSEDED on the schedule.

- **The schedule is `23 7 2,10,18,26 * *`** — four fixed dates a month, verified in
  `.github/workflows/refresh.yml`. It replaced both the `23 7 2 * *` monthly line the entry
  below describes and the weekly line that briefly followed it. Fixed dates were chosen over
  a weekday cron because the dates are themselves a complete answer to when it runs.
- **Every run re-pulls the whole year with `--force`.** The incremental path and the GitHub
  raw cache are deleted. The cache's apparent reliability rested on a coincidence: roughly
  7-day eviction meant a monthly schedule always found it cold, so it rebuilt the year
  without anyone designing that, and running more often would have kept it warm and quietly
  ended the self-repair.
- **The first unattended run fired on 2026-08-02** and succeeded, all eight jobs green. Every
  run before it had been a manual `workflow_dispatch`.
- **A failed run now opens a GitHub issue** that @-mentions the owner, rather than relying on
  owner email. ⚠ Still unproven against real GitHub permissions: no run has failed since.
- **Dependencies are pinned exactly.** The 2026-08-02 CI log showed the resolver had already
  walked to pandas 3.0.5, pyarrow 25.0.0 and duckdb 1.5.5, three unreviewed majors that came
  up green by luck.
- **The status page and workbook no longer advertise the wrong day**, and the page's Refresh
  token runs to 15 July 2027.
- `CLAUDE.md` was added at the project root 2026-08-05, and a stray two-row
  `_meta/sources.jsonl` was archived 2026-08-08. Provenance remains the pipeline itself.

The full reasoning for each sits in `pending-updates.md`, which is where these were worked.

## Update 2026-08-01 — schedule moved to the 2nd, and a missing month is now caught

**The cron is now `23 7 2 * *` — 07:23 UTC on the 2nd.** Fred's call, after asking why it was on the
3rd and whether the 1st carried any risk. What sets the floor is not ENTSO-E's publication lag but
the MONTH GATE: a month counts complete only once coverage passes its final hour, and coverage
trails the run by ~1h34m. Allowance for a late publication is 7h23m on the 1st, 31h23m on the 2nd,
55h23m on the 3rd.

The 1st was rejected on the failure MODE rather than the odds. Exceeding the allowance does not fail
the run — it succeeds, publishes, and silently omits the month from every monthly exhibit until the
next scheduled run a month later.

**`check_coverage.check_month_arrived` closes that gap.** The shrink guard structurally cannot see
it: if a month never arrives, last month's feed ended in June and this month's also ends in June, so
nothing got smaller and the gate passes. Absence and shrinkage are different failures. The new check
asserts that the month which has just closed is present in every monthly-axis feed, detecting those
feeds structurally (first column `date`, every value a month-first) so `capture_monthly` — keyed
`month` and deliberately ungated — is excluded. A 24-hour grace after the month boundary keeps an
ad-hoc dispatch in the first hours of a month from tripping it.

Verified three ways: passes on the current data (June is the closed month and is present); fails all
three monthly feeds when the build clock is moved to 2 August with July absent; skips with a note
when the build clock is 7h23m into a new month.

## Update 2026-07-31 (later) — nothing reaches `main` unchecked

The publish path was restructured so that every gate runs BEFORE anything is written to the
repository, and a new gate was added for the one failure mode nothing covered.

**Job order is now `fetch → build → validate → publish`.** `build` commits nothing; it hands
everything on as the `publish-payload` artifact. `publish` is the only job that writes to the repo
and it runs last. Previously the Windows Open XML validator ran *after* the build job had already
committed, so an invalid package landed in `deliverables/` and only then turned the run red.

**`_tools/check_coverage.py` — published data may not SHRINK.** Every other check asks whether the
data is valid; this asks whether it is the data we already had, plus more. It compares each
published feed against the previous commit on two measures — row count, and populated cells per
COLUMN. Both are needed: the wide chart CSVs Excel loads are fixed-shape, so a coverage collapse
blanks cells without moving a single row. It is rollover-aware, reading the window slot labels from
`status.csv` so the January run compares slot `w_k` against its previous position. Replayed over all
24 published transitions in this repo's history: silent on every ordinary refresh, fires on the
commits that shipped bad data.

**The commit step no longer reverts human work.** It used `git reset --soft origin/main`, which
leaves the index holding the run-start checkout, so `git commit` wrote back every file that had
changed on `main` during the ~40-minute run. It is now a mixed reset, plus a guard that fails the
run if anything outside the publish set is staged.

**Verified by artefact, not by claim:** the 31-day collapse really did reach `published/` in commits
`d4bdc58` and `8db1093` (`fig7_gen_mix` DE_2026: 480 populated cells → 48) and really is restored in
`81873cb` (back to 480). `_tools/coverage_eyeball.py` draws this — 212 solid days across all five
countries, nothing past the cutoff.

**The gate caught a real bug on its first live run.** Run 30648716543 passed fetch, build and Open
XML validation and was refused at the gate: France and Italy had lost January–June 2026 from
`capture_monthly` — six months of capture prices — while DE/ES/PT were fine. `_merge_into` treated
any column-set difference as a schema change and returned the 30-day window, discarding the stored
year (`generation 20213 -> 2880 rows`). ENTSO-E returns a column per generation type that actually
reported, so a technology idle for 30 days changes the column set — the normal case, not a schema
change. The merge now takes the union of columns and refuses to return fewer rows than it was given.

**And looking would NOT have caught it** — worth knowing, because "open the workbook and look" is the
habit that found three chart faults the day before. Plotting the blocked run's `capture_monthly`
against main's shows the two lines identical for 85 of 91 months, and then the damaged one simply
draws a *smoother, straighter* line across the six missing ones. Excel and matplotlib both bridge
missing points rather than leaving a gap, so six months of France and Italy disappearing renders as a
slightly calmer chart, not a broken one. Looking catches RENDERING faults; it does not catch missing
data a renderer interpolates over. The two checks are complementary, not substitutes.

**Still open:** `pending-updates.md` row 5 — see the 2026-08-01 update above for the current date.

## Update 2026-07-21 — new chart data published to GitHub (unblocks the Windows setup)
The four new CSVs and their producer had never been pushed — the Phase-6 charts' From-Web URLs
would have 404'd, and the monthly Action (which runs `extra_summaries.py` from HEAD) would never
have published them. Commit `0468ad9` pushes `figA–figD_*.csv` + `_tools/completeness.py` (a new
import of `extra_summaries.py`; without it the Action's build step would crash and kill the refresh
for **every** chart). All six pending URLs verified HTTP 200 with headers matching the chart ranges.
- ~~**Still local-only (deliberate follow-up commit):** `_tools/config.py` (`DISPLAY_END_YEAR`
  2035→2030 …) and the untracked deck-builder scripts …~~
  **❌ WRONG — corrected 2026-07-30. None of this was true.** Verified against the repo:
  `DISPLAY_END_YEAR` is **2035** in the working tree and has never been 2030 in any commit
  (`git log -S "DISPLAY_END_YEAR = 2030"` returns nothing), and `config.py` was not even modified.
  All six "untracked" deck-builder scripts are **tracked**. There were no unpushed commits
  (`HEAD == origin/main`). The 2035→2030 change was *planned and recorded as if made*, then never
  made — so nothing was ever pending a push. **2035 vs 2030 remains a genuinely open decision**
  (it reshapes the trailing blanks in the 12 already-wired CSVs), and is now recorded as such
  rather than as done. This false entry is what queue row 2 was built on.
- ~~**Fred's Windows to-do unchanged:** wire the 6 queries~~ **❌ ALSO DONE — corrected 2026-07-30.**
  The shipped workbook carries all **19** Power Query connections, including `g1_solar_peakhour`
  and `g2_price_by_month` (the two recorded as outstanding), each with its queryTable, table and
  load-target tab (`G1_SolarPeak`, `G2_MonthDuck` both present). `WORK_MACHINE_SETUP.md` no longer
  documents query-wiring at all — commit `b981ee5` reduced the routine to open-Excel/refresh-links.

## Update 2026-07-19 — Phase 6: +5 monthly "market-state" charts (both paths)
Added 5 new deck exhibits from previously-unused columns (`load`, generation mix), keeping BOTH update
paths consistent (`check_consistency.py` PASS, workbook now **charts 1–19**):
- **A** monthly baseload price by market · **B** wind+solar penetration (12-mo avg) · **C** solar/wind
  capture erosion, DE · **D** net-load "duck" (demand − wind − solar), DE — all **live-linked** (charts 16–19).
- **F** price-cannibalisation scatter (hourly price vs renewable share, DE) — **static image** in both decks
  (no query; a 9k-point scatter isn't a viable live Excel chart).
- 3 new slides; captions/render recipes in `deck_spec.py`; CSVs from `extra_summaries.py`
  (`figA–figD_*.csv`); Excel clones in `add_phase4_charts.py` (empty-target, tabs appended last).
- Dropped from the 7 candidates: **G** monthly neg-hours (overlaps Fig3) and **E** cross-border flows.
- **Fred's remaining Windows to-do grew from 2 → 6 queries** to wire — see `WORK_MACHINE_SETUP.md`.
- Review PNGs of all 7 candidates kept in `outputs/review_charts/`; scratch builder `_tools/build_review_charts.py`.

## State: ✅ Built & validated — v1 complete
Full ENTSO-E dataset (2019–2026, 5 countries) fetched, assembled, summarised, and
written to a fixed-cell-reference Excel workbook. Reference charts reproduce all 8
Redburn ENTSO-E figures. Ready for PowerPoint linking.

## What exists
- **Data store**: `data/raw/*.parquet` (337 raw pulls) → `data/processed/hourly_master.parquet`
  (330,430 hourly rows × 26 cols) + `capacity_annual.parquet` + `power.duckdb`.
- **Summaries**: `data/processed/summaries/*.parquet` (10 tables).
- **Deliverable**: `outputs/PowerPriceData.xlsx` (11 tabs, fixed cells, pre-allocated to 2035).
- **Charts**: `outputs/charts/*.png` (8 Rothschild-style reference renders).
- **Pipeline**: `_tools/{config,fetch,build_hourly,summaries,build_excel,charts,validate}.py`,
  `refresh.sh`, `.venv`.

## Validation (2026-07-16): 6/6 checks pass
- 100% price & generation coverage across all 40 country-years.
- DE 2024 avg daily spread €112 (Redburn: €112; min €32 vs ref €33, max €144 vs ref €144).
- DE 2024 near-negative hours 628 (Redburn: ">600"); negative(<0) 457.
- Solar capture −41%, Gas +21% (matches Fig 5). IT PUN proxy €108.5 (actual ~€108).

## Key decisions (locked with Fred)
- Charts: Figs 1–6 + Fig 7 + Fig 9. · Italy price = load-weighted PUN proxy.
- Delivery = fixed-cell data; Fred links PPT charts once (see `LINKING_GUIDE.md`).
- Intraday buckets = **UTC hour**. · Everything stored UTC (DST-safe).
- Future-proof: pipeline auto-fetches new years; workbook pre-allocated to 2035.

## To refresh
`cd _tools && ./refresh.sh` (auto-targets current + previous year), then update links in PPT.

## Open / possible next steps (Phase 1 polish)
- Confirm the workbook tab structure suits your PPT workflow (trim/rearrange if needed).
- If you want the intraday charts in **local** clock instead of UTC, it's a one-line change.
- Fig 6/Fig 7 currently hold all country-years; say if you want them trimmed for size.

---

## PHASE 2 — GitHub-hosted auto-refresh (2026-07-17, in progress)
**Chosen approach** (superseded Option C direct-from-Excel — Mac Excel can't author PQ / has no
"From Web", and Mac testing was unreliable under CRD/virtual displays). Constraint: must be
refreshable by a **non-technical person while Fred is away**, on a **Windows** work PC.

**Design:** scheduled GitHub Action runs the Python pipeline monthly (+ on-demand), publishes
chart-ready CSVs to public raw URLs. Windows Excel loads them via **From Web** with
**refresh-on-open** → a non-technical user just OPENS the file and it's current. PPT links auto-update.

**Built & live:**
- Public repo **github.com/Power-Utilities-team/power-price-data** (owner Power-Utilities-team). Pushed pipeline +
  workflow. `ENTSOE_API_KEY` set as encrypted Actions Secret (key NOT in code — resolves from env or
  git-ignored `_tools/.entsoe_key`).
- `.github/workflows/refresh.yml` (cron 2nd@06:00 UTC + workflow_dispatch, double-fetch pass).
- `_tools/export_csv.py` (tidy CSVs) + `_tools/chart_csv.py` (chart-ready WIDE CSVs, pre-allocated to
  2035). Validated vs Phase-1 numbers. Published raw URLs confirmed HTTP 200.
- Docs: `GITHUB.md` (ops + handover — repo is transferable to a colleague/org; successor swaps their
  own ENTSO-E key), `EXCEL_SETUP.md` (one-time Windows setup: load CSVs, refresh-on-open, charts, PPT).
- First Action run triggered (run 29559544914) to prove the cloud pipeline end-to-end.

**Uncommitted locally (push after the running Action finishes, to avoid push conflict):** workflow
update adding chart_csv step, `chart_csv.py`, seeded `published/charts/*.csv`, `EXCEL_SETUP.md`.

**Division of labour (agreed):** Claude builds the CHARTS (openpyxl can't add Power Query, and would
STRIP it if it saved a file that had queries — so Claude must go FIRST, Fred adds queries LAST in Excel
which preserves the charts). Never open Fred's query-file with openpyxl and save.

**BUILT since:** `_tools/build_linked.py` -> `outputs/PowerPriceData_Linked.xlsx` (13 sheets): each
figure sheet has its chart CSV's data at A1 + a pre-built native Excel chart wired to the Redburn-relevant
columns (Fig1 line, Fig2/3cum/4 line, Fig3/5/9 clustered bar, Fig6 scatter, Fig7 stacked-col+price-line
combo), styled navy/teal. All chart types validated by rendering to PDF via soffice (charts display OK).
Delivered to Fred. Each sheet carries a red SETUP note with its From-Web URL + load target; READ_ME_FIRST
tab included.

**INCREMENTAL refresh (2026-07-17):** history (2019-2025) frozen as committed `data/processed/
master_fixed.parquet` (24MB) + `capacity_fixed.parquet`. Each Action run fetches ONLY the current year
(2026) per country, `build_hourly.py` (default = incremental) stitches it onto the frozen history →
runs drop from ~65min to ~5-10min. `build_hourly.py --full` re-freezes everything (annual rollover /
bootstrap). Regression-checked: identical numbers (DE24 457/628, Fig5 Solar -41.1, Fig1 SD 52.73).
Workflow fetch step now `--years $CURRENT --force`. Annual TODO: after a year completes, run a `--full`
build once to fold it into master_fixed.

**Fig1 calibration PASSED** on the no-seed file: chart reads live query table (B-F), G-L empty, no shift.
Mechanism proven end-to-end on Fred's Windows Excel. Fred clear to wire the remaining sheets.
Gotcha learned: the SEED (data at load target) caused Power Query to insert+shift; empty target loads in
place. Also: two same-named downloads confused which file was tested (the `(1)` file was the real one).

**NEXT / where we paused:** (1) Fred wires just the **Fig1** query on Windows (From Web -> Load to
'Fig1_PriceSD'!A1), saves, sends the file BACK. Claude opens it READ-ONLY (safe — reading never strips PQ)
to confirm Power Query's exact table layout matches the chart's cell refs; adjust build_linked.py if
needed, resend. (2) Fred then wires the remaining queries + ticks refresh-on-open on each. (3) Paste-link
charts into PPT (set links Automatic). (4) Verify Action run went green + auto-committed fresh CSVs.
Known wrinkle: fig6/fig7 CSVs are very wide (fig7=1701 cols) — functional but could be narrowed later.

## PHASE 4 — New charts from deck slides 27-35 (2026-07-17, in progress)
Fred asked which deck charts (pre-update_2026-06-12.pptx sl.27-35) are ENTSO-E-derivable but
NOT producible from the summary file. Verdict: summary CSVs already carry all 5 countries+years,
so most "missing" charts are just chart-objects to add. True gaps = G1 solar-peak-hour share,
G2 quarterly/monthly duck curves, G3 July daily spaghetti (need raw hourly granularity).
Battery arbitrage (G4) + pre-2019 history + reservoir/M&A = out of scope (Fred).
**DONE:** `_tools/extra_summaries.py` builds g1_solar_peakhour, g2_price_by_quarter,
g2_price_by_month, g3_price_july_daily → published + wired into the Action (auto-updates).
Verified vs deck (DE Jul24 peak-hr solar 56.9%; ES-25 Q3 duck 85→18→120). Static snapshot
PNGs for the two slide-31 exhibits (G2-quarterly + G3, Iberia=mean(ES,PT), 2025 vs 2019) via
`_tools/render_snapshots.py` → `outputs/deck_img/`.
**Decisions (Fred):** live-link G1 + G2-monthly + country-variants; G2-quarterly + G3 = static
images (no query). New PQ queries Fred must wire = 2: g1_solar_peakhour→tab G1_SolarPeak,
g2_price_by_month→tab G2_MonthDuck.
**REMAINING:** (a) add live charts to summary workbook — country-variant charts on existing tabs
(clone chart XML + repoint DE→ES/PT cols) + G1/G2m charts on 2 new empty tabs; MIND localSheetId
on any sheet insert. (b) add deck slides (linked charts + the 2 static PNGs). (c) validate
(OPC + Excel-semantic incl localSheetId + openpyxl normal load) + deliver + Fred wires 2 queries.

**✅ DONE (2026-07-17 eve) — Phase 4 charts + slides built, validated, delivered.**
Workbook: `_tools/add_phase4_charts.py` (byte-preserves all PQ) added 6 charts to
`Downloads/HourlyPowerData.xlsx` (now 16 sheets / 15 charts):
- chart10 Iberia(=Spain) intraday · chart11 Germany duck (absolute, Fig2_Intraday_avg) · chart12
  Portugal capture · chart13 Iberia(=Spain) cumulative near-neg — all cloned from the Redburn
  chart XML (chart2/4/6), `<c:val>` cols shifted (ES=+17, PT=+34) + numCache rebuilt from loaded
  cells; anchored on the 'Charts' tab (drawing10, below chart9) with navy captions. Piggyback the
  existing Fig-sheet queries → no new query needed.
- chart14 G1 solar-peak-hour share (DE/ES/PT quarterly-avg lines) on NEW empty tab **G1_SolarPeak**;
  chart15 Germany monthly duck (12 lines, DE 2025) on NEW empty tab **G2_MonthDuck**. Empty-target
  pattern (refs point at where PQ loads; numCache seeded from CSV for preview). New tabs APPENDED at
  end → every existing localSheetId index untouched (verified PASS).
Deck: `build_deck.py` extended (SLIDES +3 chart slides = charts 10-15; new STATIC_SLIDES with
add_picture) → rebuilt `Downloads/HourlyPowerData.pptx` (12 slides: title + 9 chart + 2 image).
Template = the existing HourlyPowerData.pptx (carries the real UpSlide master/layouts). 2 static
slides embed the 4 Iberia snapshot PNGs (quarterly + July, 2019 vs 2025).
Validation ALL PASS: OPC 103 parts/0 malformed; localSheetId integrity PASS; openpyxl normal load;
PQ parts (connections+12 tables+12 queryTables+customXml) byte-identical; original chart1-9
unchanged; soffice render confirms all new charts display; deck opens, 15 linked charts w/
externalData, no duplicate content-types. Originals archived to `archive/phase4_2026-07-17/`.
**Fred's 2 queries to wire (From Web → Load To → that tab's $A$1, tick refresh-on-open):**
- G1_SolarPeak ← https://raw.githubusercontent.com/Power-Utilities-team/power-price-data/main/published/charts/g1_solar_peakhour.csv
- G2_MonthDuck ← https://raw.githubusercontent.com/Power-Utilities-team/power-price-data/main/published/charts/g2_price_by_month.csv
**Design calls:** G1 = the `_qavg` (quarterly-smoothed) lines; G2 monthly = Germany 2025.
**Iberia→Spain (RESOLVED 2026-07-17, Fred):** checked the source deck — capture was **Portugal**
(sl.33/35, matches chart12); the volatility/intraday/neg-hour "Iberia" exhibits used the Iberian
MIBEL price (ES≈PT; our data mean|ES−PT|=1.1 €/MWh 2025). Fred's call: the two live "Iberia" charts
(chart10 intraday, chart13 cum-neg) are **Spain (ES)** and now **labelled "Spain"** (no "Iberia").
The 2 STATIC snapshot slides were ALSO switched to Spain (regenerated ES-only via render_snapshots.py, relabelled) — Fred wants no "Iberia" anywhere; deck now 0×Iberia / 8×Spain. Rebuild is
idempotent: `add_phase4_charts.py` SRC + deck template now point at
`archive/phase4_2026-07-17/HourlyPowerData_pre-phase4.{xlsx,pptx}` (clean pre-Phase-4 bases).

## PHASE 3 — Redburn chart restyle + Charts tab (2026-07-17)
Fred: native charts looked bad → make them truly Redburn, all on one leftmost tab, no
re-doing queries. Found the canonical Redburn spec in `Power & Utilities/tools/chartgen.py`
(no title; Arial 8.5; palette NAVY #2E3E80/TEAL/SAGE/FOREST/GOLD/WINE; latest-year=NAVY;
horizontal-only #E5E5E5 gridlines; no-frame bottom legend; accounting-negative axis).
Built two XML-surgery scripts (PQ-preserving, openpyxl never saves): `_tools/redburn_charts.py`
(restyle + Mixed year-cutoff + clean names + recolour) and `_tools/move_charts.py` (all 9
charts → new leftmost `Charts` tab with navy captions; strips charts from Fig sheets).
Year cutoff = **Mixed**: annual-stat charts (Fig1/3/5/9) stop at 2025; profile/duration
(Fig2/3cum/4) keep 2026. Validated: PQ/tables/sharedStrings byte-identical, openpyxl loads,
LibreOffice renders all 9 with captions + Redburn look. Delivered
`Downloads/PowerPriceData_REDBURN.xlsx` (drop-in for Fred's query file). config
DISPLAY_END_YEAR 2035→2030 [**❌ never actually made — see the correction at the top of this file
(2026-07-30); the value is still 2035 and the change remains an open decision**]. Pipeline + annual
range-extension documented in `CHARTS.md`.

### (archived) Option C attempt — direct-from-Excel
**Goal:** update the workbook on Fred's **Windows work PC** (locked down: no terminal, no installs,
Excel only, can reach any external URL) purely via Excel **Power Query** hitting ENTSO-E — so the
Python pipeline here is the initial build, but ongoing refresh is Excel-native. Trigger = manual
(Data > Refresh All). Decided to **build C** and test on THIS Mac's Excel first.

**Progress:**
- Confirmed raw ENTSO-E REST works with a plain GET (HTTP 200, parseable XML). Key gotcha: prices are
  now `PT15M` — M must parse TimeSeries>Period>Point, compute UTC ts from period start + resolution,
  resample to hourly.
- Drafted first M query: `_tools/powerquery/01_DE_prices.m` (DE prices -> hourly UTC).
- Made scratch `outputs/Test_PQ.xlsx`; began driving Excel via AppleScript automation.

**⚠️ ~~BLOCKER~~ — RESOLVED 2026-07-31: this Mac DOES have Power Query.** The note below looked at
the MENU BAR only and paused before checking the ribbon, so the open question sat unanswered for two
weeks and drove a "we may need a Windows VM" plan that was never necessary.

Checked against the installed app instead of the UI: `Microsoft Excel.app/Contents/SharedSupport/`
ships **`Microsoft.Mashup.Container.app` (16.111.2)** — Mashup is Power Query's engine — and the
en_GB string bundle contains **Get Data · From Web · New Query · Launch Power Query Editor ·
Queries & Connections · Refresh All**. Only **Advanced Editor** (hand-writing M) is absent, which
matters for authoring raw M and for nothing else this project does.

So: refreshing the workbook, and creating a From-Web query through the UI, both work here. On-device
testing needs no VM and no work PC. The commands live on the **Data tab of the ribbon**, not the
menu bar — which is why they were missed.

~~**Open question:** does Mac Excel 16.111 have Power Query authoring in the ribbon…~~ Answered above.

**Excel is currently open** with Test_PQ.xlsx; M code was on the clipboard.

**Resume by:** reading `excel_state.png`, checking the Data-tab RIBBON for a "Get Data"/Power Query
control (System Events AXToolbar), and determining whether Advanced-Editor authoring exists on this
build. If yes → paste `01_DE_prices.m`, Close & Load, test Refresh. If no → discuss alternative test
path with Fred before building further.

## PHASE 5 — Two update paths + consistency (2026-07-18, in progress)
Fred wants, ALONGSIDE the live Excel-linked path: (1) a "generate the latest deck via Claude"
path (self-contained, no Excel), and (2) a frozen/hardcoded Excel snapshot in the SAME structure
as the live workbook, so charts can pull from it for a given month. And (3) both paths kept
strictly consistent whenever charts/data/deck change.

**Data-completeness gating (Fred's key requirement):** period-based charts must never show a
partial period. `_tools/completeness.py` computes last-complete year/quarter/month from the
hourly_master max non-null price ts (min across countries). Rule applied in render_all:
- annual-stat charts (fig1,fig3-annual,fig5,fig9,portugal_capture) → years ≤ last_complete_year (2025)
- intraday PROFILES (fig2,fig4,fig3cumneg + Spain/Germany variants) → keep current yr, LABEL "<yr> YTD"
- G1 solar-peak (quarterly-avg) → dates ≤ last_complete_quarter end
- single-year exhibits (fig6,fig7) → default to last_complete_year
- G2 monthly (DE) → last_complete_year; if partial yr, months ≤ last_complete_month.

**BUILT & validated (static path complete):**
- `completeness.py` (tested: coverage 2026-07-16 → yr2025/Q2026Q2/M2026-06).
- `render_all.py` → `outputs/deck_charts/*.png` (15 house-style charts via chart-style skill, gated).
  Reuses `charts.py`'s country-parametrized renderers (fig2/4/5/6/7/9 + fig1/fig3-annual/g1/g2).
- `render_snapshots.py` (already Spain-only) → 4 snapshot PNGs.
- `build_static_deck.py` → `outputs/HourlyPowerData_snapshot.pptx` (12 slides, all embedded images,
  0 linked charts, "Data as of <coverage>"). Mirrors the linked deck slide/caption-for-slide.
  Validated (render OK, branding matches). Delivered sample to Downloads.
- **venv fix:** project venv is `_tools/.venv` (uv-managed; my earlier builds silently ran on the
  harness python which lacks pyarrow). Installed python-pptx(+openpyxl) into `_tools/.venv` so ALL
  scripts run on ONE env. Use `_tools/.venv` for everything now.

**Decisions (Fred, 2026-07-18):** freshness = fresh-to-today live pull (key present at
`_tools/.entsoe_key`), BUT completeness-gated as above. Consistency mechanism = **shared spec
(single source of truth)**: extract `deck_spec.py` all builders import; refactor build_deck +
build_static_deck + render_all + build_frozen_excel to read it; `check_consistency.py` asserts the
decks match; one unified "generate everything" command.

**REMAINING (Phase 5):** (A) `build_frozen_excel.py` — same 16-sheet structure + styled charts,
data hardcoded into cells (+fill G1/G2), Power Query stripped. (B) `deck_spec.py` shared spec +
refactor the 4 builders to consume it + `check_consistency.py` + unified `generate.sh`/`generate.py`
(fresh fetch → summaries → csvs → render_all → static deck → frozen excel → refresh linked
workbook+deck → check_consistency). Re-validate linked deck builds identically after refactor.

### Phase 5 — decisions locked (2026-07-18) + remaining B work
**Static path + frozen Excel: BUILT & delivered.** `build_frozen_excel.py` → `HourlyPowerData_frozen.xlsx`
(16 sheets, 15 charts, data hardcoded via inlineStr/`<v>`, ALL PQ stripped — connections/tables/
queryTables/customXml/ExternalData names removed; charts recalc from static cells; validated OPC+
openpyxl+soffice-render). Delivered to Downloads.

**Single-year charts (Fig6 daily min/max, Fig7 gen-mix) — year policy CONFIRMED (Fred): latest
complete year in BOTH paths.** Evidence: source sector deck (pre-update_2026-06-12) slide 30 titles
the gen-mix "…Portugal/Germany (2025)" = last complete year, NOT YTD. The current-year-so-far (YTD)
treatment in the source is on the DUCK/indexed-intraday-price + neg-hour charts (sl.29 "2019-2026 YTD",
sl.32 "…so far in 2026") — which the static path already renders as YTD profiles. So: repoint the LINKED
workbook's Fig6 (chart7) + Fig7 (chart8) from 2024 → 2025 to match the static path.

**REMAINING (B — consistency, shared-spec approach chosen by Fred):**
1. `deck_spec.py` = single source of truth: ordered SLIDES with per-exhibit {id, caption, box (L/R/1up),
   linked chart#, png, render-recipe (kind+country+gating)}. Canonical data already enumerated in the
   two deck builders' SLIDES lists + render_all.main().
2. Refactor `build_deck.py` (linked), `build_static_deck.py` (static), `render_all.py` to import deck_spec
   (delete their local SLIDES copies). Re-validate BOTH decks build byte-comparably (same titles/captions).
   NOTE current drift the spec fixes: build_deck captions say "(Portugal, 2024)"/"(Germany, 2024)";
   static says year-agnostic — unify to ONE caption.
3. Repoint linked workbook Fig6(chart7)/Fig7(chart8) 2024→2025 (XML surgery: <c:f> cols + numCache from
   the 2025 columns on Fig6_MinMax/Fig7_GenMix sheets). Rebuild HourlyPowerData.xlsx + frozen + decks.
4. `check_consistency.py`: assert both built decks' slide titles+captions+exhibit order == deck_spec, and
   the workbook has charts 1-15; fail on any mismatch. Run before every delivery.
5. `generate.py`/`generate.sh` unified: [--fresh] fetch→build_hourly→summaries→extra_summaries→chart_csv,
   then render_all→build_static_deck→build_frozen_excel→(refresh linked wb via add_phase4)→build_deck→
   check_consistency. Key present at `_tools/.entsoe_key`. Gating via completeness.py.
ALL scripts run on `_tools/.venv` (now has python-pptx+openpyxl+pyarrow+matplotlib).

### Phase 5 — ✅ COMPLETE (2026-07-18)
Shared-spec consistency architecture built, wired, and enforced. `deck_spec.py` is the SINGLE
SOURCE OF TRUTH (ordered SLIDES; per-exhibit id/caption/box/linked-chart#/png/render-recipe). All
builders consume it:
- `render_all.py` (spec-driven dispatch) → 15 gated house-style PNGs.
- `build_static_deck.py` → self-contained deck (reads deck_spec).
- `build_deck.py` → linked deck (reads deck_spec; local SLIDES/STATIC_SLIDES deleted).
- `build_frozen_excel.py` → hardcoded workbook (inherits workbook charts).
Fig6/Fig7 repointed 2024→2025 (latest complete year) in `add_phase4_charts.py` (fig6 col-shift +1,
fig7 +20/yr, numCache rebuilt from cells); g2 monthly now uses LCY; profile charts label the partial
year "<yr> YTD" in BOTH paths (annual charts already stop at last complete year).
`check_consistency.py` asserts both decks' titles+kickers+captions == deck_spec (+ workbook charts
1-15); FAILS the build on drift. `generate.py [--fresh] [--deliver]` = ONE command: (fresh ENTSO-E
pull →) render_all → static deck → frozen Excel → linked workbook+deck → check_consistency. All on
`_tools/.venv` (python-pptx+openpyxl+pyarrow+matplotlib).
**Consistency guarantee for the future:** change any exhibit in `deck_spec.py`, run `generate.py`;
`check_consistency.py` fails if the two paths disagree. To ADD a chart: add it to deck_spec (+ a
workbook chart in add_phase4 for the linked path + a render recipe for the static path), rerun generate.
**4 deliverables (all in Downloads, rebuilt by generate --deliver):** HourlyPowerData.xlsx (live/linked,
PQ), HourlyPowerData.pptx (linked deck), HourlyPowerData_frozen.xlsx (hardcoded snapshot),
HourlyPowerData_snapshot.pptx (self-contained deck). Plus Deliverables/updating-the-deck.{html,pdf}.

### Fred's remaining work-machine setup → see `WORK_MACHINE_SETUP.md` (written 2026-07-18)
Verified against delivered files: 12/14 PQ queries already wired; ONLY G1_SolarPeak + G2_MonthDuck
left to wire. Both live files go in the Redburn `…\Sector Presentation\` folder (deck link target).
Frozen/static snapshots need no setup. Recommended: Fred sends the wired workbook back once for a
read-only G1/G2 layout check.

---

## 2026-08-25 — the UK dataset, the hydro reservoir tracker, and generator parity

**The headline finding, before the additions.** The pipeline produced 23 sheets and 19 charts. The
workbook actually in circulation (`HourlyPowerData 3.xlsx`) had 24 and 62. The extra sheet
(`CaptureVsBase`) and the extra 43 charts had been built by hand in Excel and existed in no script
in either vault, so a fresh `generate.py` run returned a workbook missing two thirds of its
exhibits and nothing reported a fault. Parity was rebuilt first; the new work sits on top of it.

**Great Britain is not an ENTSO-E country.** Probed, not recalled: GB publication to the
Transparency Platform stopped on 15 June 2021 under the post-Brexit Trade and Cooperation
Agreement. Day-ahead price ends 2020, generation, capacity and load mid-2021; only cross-border
flows continue, because the counterparty TSO publishes them. The `UK` domain (10Y1001A1001A92E)
still returns data and is a trap: 857 MW mean generation against 24,716 MW in 2019, because it is
Northern Ireland alone.

GB now comes from Elexon (generation AGPT, load INDO), the ECB (daily GBP/EUR) and DESNZ DUKES
5.12.A (installed capacity 2011-2025), via `fetch_uk.py`, which writes the same raw parquet shapes
so nothing downstream needs a GB branch. Coverage: price and load 94-100% per year, generation
87-99.7% with 2022 the weak year (86 days genuinely absent from Elexon).

**The GB price is not a day-ahead auction, and that is Fred's recorded choice.** N2EX is not
obtainable free: Elexon returns N2EXMIDP rows with price 0 and volume 0 in every year tested, Nord
Pool's portal answers 401, energy-charts has no GB zone, neither NESO nor Ofgem publishes a
wholesale series, and EPEX's GB auction exists only as rendered web pages. The workbook uses the
Elexon market index (APX) and says so on the Status tab.

**Hydro.** ENTSO-E's weekly A72 water-reservoir series, 2015 onward, for FR, ES, PT, IT, NO plus
NO1-NO5, SE, FI, AT and CH. Germany and Great Britain publish no reservoir series under any domain
code, so both get a pumped-storage chart instead, captioned as such. Run-of-river was swapped for
reservoir only where hydro was a single series (Italy); Germany gained a reservoir chart as an
addition, and Portugal and France, which already showed both, were left alone.

**Structural constraint worth knowing.** The twelve inherited figure tabs have Excel tables fixed
at 86 columns, exactly five countries wide, and are not rebuilt from their CSVs. A sixth market's
columns land outside the table where no chart or refresh reaches them. Those CSVs are therefore
frozen at five countries (`config.LEGACY_CSV_COUNTRIES`); every chart reads a rolling-window tab
instead, and those ARE rebuilt, so they widen on their own.

**Three ordering bugs fixed, all previously silent.** `extra_summaries` ran before `chart_csv`
even though it reads that script's output, so `line_windows` was always a run behind. The built
CSVs were never staged into `published/` before the workbook build locally, though CI has always
done it. And Elexon's demand endpoint caps at seven days, so a monthly loop kept only the one month
short enough to succeed and wrote a 1,392-row year. Each now has a guard that reports rather than
passing quietly.

**State: built and validated locally, NOT pushed.** 26 sheets, 89 charts, `opc_validate` and
`check_chart_quality` both green, every new chart range carrying real prefilled data. Fred's call
was to hold the push until after the 2026-08-26 07:23 UTC scheduled run has proved the existing
code on the new organisation.

**One loose end in the LOCAL raw store, self-healing.** A 2026 re-fetch was attempted on
2026-08-25 and ENTSO-E returned 504 after 504 on the German generation pull (the same platform
fault that broke the 18 August run). It was stopped part-way, so `data/raw/DE_*_2026.parquet` is
now mixed: price and load run to 25 August, generation still to 16 July. Nothing shipped from that
state — the delivered workbook was built beforehand and is internally consistent at 16 July for the
five ENTSO-E markets. Any `--fresh` run re-pulls the whole year with `--force`, and CI always does,
so the next run of either resolves it. GB and the hydro series are unaffected and current.
