# Pending updates — Power Price Data

## 🔴 OPEN COMMITMENTS

Cross-session commitments that outlive a session. Read by the `open-commitments.sh` SessionStart hook
and the cross-session task view.

**Format is load-bearing:** exactly four columns, no `|` inside a cell, and a status cell that starts
with `done` / `recorded` / `accepted` / `closed` to drop off the list.

| # | Item | Status | Blocked on |
|---|---|---|---|
| 1 | Wire the 6 PowerQuery queries on the Windows work machine | done 2026-07-30 — was already complete; verified in the shipped workbook: 19 connections incl. `g1_solar_peakhour` + `g2_price_by_month`, each with queryTable + table + load-target tab (`G1_SolarPeak`, `G2_MonthDuck` present). `WORK_MACHINE_SETUP.md` no longer documents wiring at all (commit `b981ee5`) | Nothing |
| 2 | Push the deliberately-local follow-up commit — `config.py` DISPLAY_END_YEAR 2035→2030 plus untracked deck-builder scripts | closed 2026-07-30 — premise false on all three counts. `HEAD == origin/main` so nothing was unpushed; DISPLAY_END_YEAR is 2035 and was never 2030 in any commit; all six scripts are tracked. The change was recorded as made but never made | Nothing |
| 3 | Capture-price-vs-baseload-by-technology chart renders with transparent or empty white bars | done 2026-07-30 — two causes. The six leftover technologies were fixed 2026-07-22 (`289a352`). The residual German Nuclear gap is fixed today: Nuclear moved to the TAIL of the DE block so Fig 5 takes a 10-row prefix and Fig 9 keeps all 11 | Nothing |
| 4 | Decide DISPLAY_END_YEAR 2035 vs 2030 — a real open question, previously mis-recorded as settled. Changing it reshapes the trailing blank columns in the 12 already-wired CSVs, so it is not a tidy-up. NOTE the reserved columns are load-bearing — READ_ME_FIRST tells the reader "charts are pre-wired and pre-allocated to 2035, so future years fill in automatically on refresh" — so shortening the runway to 2030 buys tidier CSVs at the cost of a 2031 cliff. Leaning KEEP 2035 | OPEN | Fred's call |
| 5 | Confirm the monthly refresh actually fires unattended. Every run to date (6) was a manual `workflow_dispatch`; cron `0 6 2 * *` has never once triggered. First scheduled firing 2026-08-02 06:00 UTC | OPEN | Time — check the Actions tab on 2 Aug |
| 6 | The workbook's `READ_ME_FIRST` tab is STALE and actively misleading — it still walks the reader through "add ONE Power Query … Get Data > From Web …" for queries that are all already wired. Same false premise as row 1, but baked into the file Fred actually opens. It comes from the rebuild base `archive/phase4_2026-07-17/HourlyPowerData_pre-phase4.xlsx`, so fixing it means editing that base or adding a generate.py step | OPEN | Nothing — but it is workbook surgery, so do it deliberately |

<!-- append entries below -->

2026-07-30 · **Queue created; orphaned session `9f9ca682` (quiet since 17 Jul) retired into it.**
⚠ **A first version of this file, written earlier the same day, was WRONG** — it recorded the
"REMAINING (a)(b)(c)" block from `current-status.md` (country-variant charts, deck slides, validate)
as open. Those three were completed the same evening (2026-07-17), by a **DONE block sitting a few
lines further down the same file**, and the project has since moved through Phase 6 to charts 1–19.
Reading the "REMAINING" heading without reading past it is precisely the stale-status trap this
vault has been bitten by before. Rows 1–3 above are the genuine state as of the 2026-07-21 update.

2026-07-30 (later) · **Rows 1 and 2 were ALSO wrong, and are now closed.** The correction above fixed
which items were listed but not whether they were real — both had already been overtaken, and row 2's
premise never existed. Verified directly against the workbook and the repo, not against a status file:
row 1's 19 queries are all wired; row 2's unpushed commit, config change and untracked scripts are all
absent. Rows 4–6 replace them with what is genuinely outstanding.

**The pattern worth naming:** three successive queues for this project were each built by reading a
status document rather than the artefact it described. `current-status.md` claimed the
DISPLAY_END_YEAR change was made (twice), and that Fred still had queries to wire; neither was true.
A status file is a claim. Check the workbook, the CSV, or `git log` before putting an item on a list —
and before taking one off.
