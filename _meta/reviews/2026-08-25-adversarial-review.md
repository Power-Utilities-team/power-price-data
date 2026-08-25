# Adversarial review, 2026-08-25

Three independently-briefed structural reviewers, run after the UK dataset, the hydro
reservoir tracker and the 43 parity charts landed on `main` (commits `0c58211`, `296fe27`).
The brief was open-ended by design: navigation notes rather than a read order, no question
list, and the builder's decisions held in an appendix behind "do not read until you have
formed your own view".

Kept because the findings' evidence is worth more than the fixes' commit messages: several
of these are properties of the design rather than bugs, and the next person to add a
country will meet them again.

## What the review cost and returned

Two defects were already live on `main` and neither was visible to any check in the repo.
All three reviewers independently found the second one.

## Verdicts, verbatim

**Reviewer 1.** "Right shape, one confirmed defect that invalidates the change's headline
claim: four charts captioned 'United Kingdom' in the built workbook plot Spain's and
France's data, because the repointing function in `_tools/add_extra_charts.py` silently
substitutes nothing, and every validator including today's new guard passes it."

**Reviewer 2.** "Right shape, wrong state: the pipeline's architecture (append-only
columns, publish-before-build, CI as the only writer) is sound and unusually well-reasoned,
but this change has never once been built end-to-end by CI, its new guard sits where the
shrink guard is missing, and the working tree right now contains a published-data
regression that every automated check passes."

**Reviewer 3.** "Right shape, with structural gaps: the pipeline, its guards and the GB
sourcing are genuinely well-built, but today's change silently converted the one
deliverable designed to be self-contained into one that renders blank without a
recalculating Excel, and it moved 65 of 84 charts outside every spec and consistency
guarantee the project relies on."

## Findings, and their state

### Fixed the same day

1. **65 charts carried `<c:userShapes r:id="rId1"/>` with no chart `.rels` file**, so every
   reference dangled and Excel answered with "We found a problem with some content ...
   recover?". Recovering strips Power Query. Found by opening the file in Excel, which no
   check had ever done. The overlays were empty, so they are stripped.
   `opc_validate.py` now resolves every `r:id` inside every part against that part's own
   `.rels`, which is the check whose absence let it through.

2. **`build_country_variant` repointed nothing.** Its pattern was written `r'\\$([A-Z]{1,3})\\$'`,
   which in a raw string is a literal backslash then a dollar, a sequence that never occurs
   in an Excel reference. Four charts captioned "United Kingdom" shipped plotting
   `Fig5_Window!I:O` and `Fig9_Window!I:O` (Spain) and `Line_Window` `i_FR_*` / `c_FR_*`
   (France). The letter map was correct, which is why testing the map looked like testing
   the function. It now verifies its own output and raises rather than emitting a chart it
   failed to repoint, and `check_chart_captions.py` compares the country named in a
   caption against the country in the column headers it plots.

### Confirmed, fixed in the follow-up

3. **The frozen workbook stopped being self-contained.** 52 of 84 chart parts hold zero
   cached points and `CaptureVsBase` holds 45,372 formulas and zero cached values,
   confirmed by two independent parses. It renders blank anywhere that does not run a full
   recalculation: Excel on the web, SharePoint and Teams previews, Quick Look, LibreOffice,
   and any Excel set to manual calculation. `fullCalcOnLoad="1"` covers desktop Excel only.

4. **GB is absent from more exhibits than was declared.** `figA_monthly_price.csv` and
   `figB_penetration.csv` carry a GB column that their charts do not plot; `fig2_intraday_avg`,
   `fig4_duration_curve`, `fig6_daily_minmax`, `fig7_gen_mix` have no GB column at all; and
   `line_windows`' `f1_*` and `f3_*` blocks are five-country. So the claim that "every chart
   reads a rolling-window tab, and those widen on their own" is false for several exhibits.
   The `_extra` parallel-file design does not make a sixth country propagate; it makes it
   arrive wherever someone remembered to add it.

5. **`generate.py` never runs the coverage guard.** It calls `check_reference_stability`
   then publishes. `check_coverage` runs only in CI. A local `--fresh` run therefore
   overwrote the tracked baseline with a month-shorter series and every check passed;
   the working tree was in exactly that state when the review ran.

6. **The commit message contradicted its commit.** `0c58211` says published data is
   deliberately excluded, and adds five files under `published/charts/` from the same build
   the coverage guard had refused.

7. **`fetch_uk.fetch_capacity` fails silently on a content-hashed gov.uk URL.** It logs and
   returns on any non-200, with no retry and no gaps record. DESNZ re-issues DUKES annually
   and the media hash changes, so GB capacity would quietly freeze.

8. **CI and `generate.py` are two specifications of one pipeline, already drifted.** CI runs
   `build_hourly --absorb-prior-year` and `export_csv.py`; `generate.py` runs neither, so a
   local run loses the completed year at the January rollover.

9. **"United Kingdom" is the label, Great Britain is the data.** DUKES 5.12.A, and Elexon's
   price, load and generation, all exclude Northern Ireland. The same trap `fetch_uk.py`'s
   header warns about, re-entering through the label.

10. **A cancelled run raises nothing.** The notify job is gated on `if: failure()`, and
    GitHub's `failure()` is false for a cancelled run, so no issue is opened and no health
    record is written.

11. **`check_reference_stability` has holes in its own terms**: `ROW_ADDRESSED` omits six
    files with positional first columns, and the baseline covers `published/charts` only,
    leaving ten CSVs at `published/` root unguarded.

12. **Nothing checks cross-file period parity.** `capture_monthly.csv` ended 2026-07 while
    `capture_monthly_extra.csv` ended 2026-08, because the two halves come from independent
    sources with independent failure modes.

### Raised, not treated as defects

- **Intraday exhibits use a UTC hour axis**, so GB's local solar peak sits an hour left of
  the CET markets on shared axes. Pre-existing for Portugal; adding GB doubles it.
- **The build depends on two hand-made workbooks in `archive/`** (4.4 MB), which is by
  convention where finished things go, not build inputs.
- **The GB price basis caveat reaches three worksheets and no chart title or deck slide.**
  Latent while GB appears on no shared-axis price exhibit; live the moment finding 4 is fixed.
- **GB load and generation exclude distribution-connected plant** where ENTSO-E's German
  figures do not, which may distort the penetration exhibit. Unresolved: settling it needs
  to know what the exhibit is used to argue, and no document in the project says.

## The one structural lesson

Every guard in the repo was positional: is the package valid, did anything move, did a
series shorten, does the deck match its spec. Not one asked what a chart MEANS. Wrong data
under a right title is invisible to all of them and obvious to any reader, and it took
opening the file and reading a caption to find. Both new guards this review produced
(`opc_validate`'s relationship resolution, and `check_chart_captions`) close semantic gaps,
not positional ones.

A reviewer also noted, fairly, that the appendix sat in the same file as the brief, so the
"do not read until you have formed your own view" sequencing was unenforceable. Two of the
three said they read it in one pass and compensated by verifying rather than absorbing.
Next time the appendix belongs in a separate file the brief names.
