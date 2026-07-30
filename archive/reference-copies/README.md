# Reference copies — NOT deliverables, NOT go-forward files

Workbooks kept only as **evidence of a past state**. Never treat one as current, and never
build on one.

## `HourlyPowerData_post-refresh_2026-07-21_REFERENCE-ONLY.xlsx`
Fred's own working copy after he opened the 2026-07-21 build in Excel and let Power Query
refresh it. He put it in the project root so the refresh's effects could be inspected.

**What it was for:** diffing his refreshed copy against the shipped file. That diff found the
three faults fixed in commit `289a352` — most importantly that Excel re-anchors any chart series
running to or past the end of its data, which stretched chart12 from `$A$13:$A$19` to
`$A$13:$A$26` and silently put six leftover technologies back into the Portugal capture chart.

**Why it is here and not in the root:** it is one build BEHIND the fix it helped find, so its
Fig 5 charts still show the empty-bar defect (17 categories where there should be 11 and 7).
Left in the root it reads like a current file — on 2026-07-30 it was mistaken for exactly that.
Archived 2026-07-30.

The current workbook is `Deliverables/HourlyPowerData.xlsx`, rebuilt and committed by the
monthly GitHub Action.
