"""status.csv's health columns, and the one invariant that silently breaks the workbook.

WHY THIS EXISTS. Fred, 2026-08-23: "make sure that a refresh within the excel, following a
partially failed or fully failed GitHub run, works fine". A FULLY failed run publishes
nothing, so the workbook's staleness banner fires on age and that path already worked. A
PARTIAL one is the gap: with the bounded fallback a run can publish having taken one series
from stored data, so generated_utc moves, the banner goes green, and one feed is quietly up
to three days behind.

status.csv now carries `health_state` and `health_note`, and the Status sheet reads them
from $O$2 and $P$2 — BY COLUMN LETTER. That is the fragile part and the reason for the last
test here: insert a column anywhere before them and the sheet silently reads the wrong
field, showing nothing, or worse, showing a rolling-window year as a health note.

    ~/.claude/pyenv/bin/python3 _tools/status_health_test.py     (no network)
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

FAILS = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("  " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


def col_letter(i):
    s = ""
    while True:
        s = chr(ord("A") + i % 26) + s
        i = i // 26 - 1
        if i < 0:
            return s


def main():
    import build_status as bs

    tmp = tempfile.mkdtemp()
    bs.GAPS_GLOB = os.path.join(tmp, "fetch-gaps*.json")

    check("no gap records means a clean bill", bs.health() == ("ok", ""), str(bs.health()))

    # A FATAL gap never reaches a published status row: fetch.py exits non-zero and nothing
    # publishes. So a record carrying only `fatal` must still read as ok here.
    json.dump({"fatal": [{"series": "generation", "why": "nothing stored"}], "stale": []},
              open(os.path.join(tmp, "fetch-gaps-DE.json"), "w"))
    check("a fatal-only record is not a published-health problem",
          bs.health() == ("ok", ""), str(bs.health()))

    json.dump({"fatal": [], "stale": [
        {"series": "generation", "covers_to": "2026-08-21T07:00", "days_old": 2}]},
        open(os.path.join(tmp, "fetch-gaps-ES.json"), "w"))
    state, note = bs.health()
    check("a stale series is declared", state == "stale-series", state)
    check("and the note names the series, how far behind, and how old",
          "generation" in note and "2026-08-21" in note and "2d" in note, note)

    # Two countries losing the SAME series is one fact, not two.
    json.dump({"fatal": [], "stale": [
        {"series": "generation", "covers_to": "2026-08-21T07:00", "days_old": 2}]},
        open(os.path.join(tmp, "fetch-gaps-FR.json"), "w"))
    check("the same series across countries is reported once",
          bs.health()[1].count("generation") == 1, bs.health()[1])

    # A malformed record must not take the publish down with it.
    open(os.path.join(tmp, "fetch-gaps-IT.json"), "w").write("{ not json")
    check("an unreadable gap record is skipped, not fatal",
          bs.health()[0] == "stale-series", str(bs.health()))

    # ---- THE COLUMN-LETTER INVARIANT -------------------------------------------------
    # add_status_sheet.py addresses these by letter. Compose the row exactly as main()
    # does and confirm the letters still line up.
    import config as cfg
    row = dict.fromkeys(["generated_utc", "coverage_end", "last_complete_year",
                         "frozen_history_end", "charts_built_for_year",
                         "expected_refresh_days"])
    for i, _ in enumerate(cfg.window_years(2025), start=1):
        row[f"w{i}"] = None
    row[f"w{cfg.WINDOW_YEARS + 1}"] = None
    row["health_state"], row["health_note"] = bs.health()
    cols = list(row)
    state_col = col_letter(cols.index("health_state"))
    note_col = col_letter(cols.index("health_note"))
    check("health_state is the column the Status sheet reads ($O$2)", state_col == "O",
          f"it is {state_col}")
    check("health_note is $P$2", note_col == "P", f"it is {note_col}")

    src = open(os.path.join(_HERE, "add_status_sheet.py")).read()
    check("and the sheet really does read those two cells",
          '$O$2="stale-series"' in src and "$P$2" in src)
    check("the green OK line cannot show over a stale series",
          "STALE_SERIES" in src and "OR(" in src and "STALE_SERIES}" in src.replace(" ", ""),
          "STALE_SERIES is part of ANY_ALARM")

    print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
