"""fetch_uk_gaps_test.py — Great Britain must be able to FAIL, and must say why.

WHAT THIS EXISTS TO CATCH, found by fault injection on 2026-08-26. `fetch_uk.py` caught
every exception and returned None from `main`, so the process exited 0 no matter what
happened. Patching both fetch functions to raise produced: exit code 0, no gaps record,
a green job, and a publish from stored data of unbounded age.

That mattered three times over. The workflow's `if ! python fetch_uk.py ...; then --force`
fallback can only fire on a non-zero exit. `fetch-gaps.json` is the only route by which a
fetch problem reaches health.json, the status page and the Excel banner. And nothing
downstream compensates: check_coverage looks for data that SHRANK, and a frozen GB column
loses nothing while the other five markets keep the file's last row advancing.

The assertions below are the three outcomes, driven through a stubbed fetcher: nothing
stored is FATAL, recent stored data is a declared fallback, and stored data past the bound
is fatal again. No network and no API key.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

import pandas as pd

import config as cfg
import fetch_uk as u

fails = []


def check(ok, name, extra=None):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok or extra is None else f"   {extra}"),
          flush=True)
    if not ok:
        fails.append(name)


TMP = tempfile.mkdtemp(prefix="gbgaps-")
cfg.RAW_DIR, cfg.META_DIR = os.path.join(TMP, "raw"), os.path.join(TMP, "meta")
os.makedirs(cfg.RAW_DIR); os.makedirs(cfg.META_DIR)
YEAR = cfg.CURRENT_YEAR
GAPS = os.path.join(cfg.META_DIR, u.GAPS_FILE)


def store(series, year, ends_days_ago):
    """A stored parquet whose DATA ends N days ago. Age is read from the data, not mtime."""
    end = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(days=ends_days_ago)
    idx = pd.date_range(end - pd.Timedelta(days=2), end, freq="30min", name="ts_utc")
    pd.DataFrame({"value": 1.0}, index=idx).to_parquet(u.raw_path(series, year))


def run(fail=("price", "load", "generation"), years=(YEAR,)):
    """One fetch where the named series raise and the rest succeed. Returns (rc, record)."""
    for p in os.listdir(cfg.META_DIR):
        os.remove(os.path.join(cfg.META_DIR, p))
    u.OUTCOMES.clear(); u.LOG.clear()
    def maker(label, key):
        def fn(year, force):
            if label in fail:
                raise RuntimeError(f"{label} endpoint is down")
            u._mark(u.raw_path(key, year), label, "ok")
        return fn
    u.fetch_price = maker("price", f"price_{u.UK}")
    u.fetch_load = maker("load", "load")
    u.fetch_generation = maker("generation", "generation")
    u.fetch_flows = lambda year, force: None
    u.fetch_capacity = lambda years_, force: None
    sys.argv = ["fetch_uk.py", "--years", ",".join(str(y) for y in years)]
    rc = u.main()
    rec = json.load(open(GAPS)) if os.path.exists(GAPS) else None
    return rc, rec


# 1. NOTHING STORED. There is no fallback to lean on, so the run must not report success.
rc, rec = run()
check(rc == 1, "every required series down with nothing stored EXITS NON-ZERO", f"rc={rc}")
check(rec is not None, "and writes a gaps record")
if rec:
    check(sorted(rec["series"]) == ["generation", "load", "price"],
          "naming every series that failed", rec.get("series"))
    check(len(rec["fatal"]) == 3 and not rec["stale"],
          "as FATAL, not as a tolerable fallback", (len(rec["fatal"]), len(rec["stale"])))
    check(all(g["why"] == "nothing stored" for g in rec["fatal"]),
          "and saying why", [g["why"] for g in rec["fatal"]])
    check(set(rec) == {"at", "countries", "years", "fatal", "stale", "series"},
          "with the same fields fetch.py writes, so no consumer needs a GB special case",
          sorted(rec))
    check(rec["countries"] == ["GB"], "attributed to GB", rec["countries"])

# 2. STORED AND RECENT. A bounded fallback: publish, and declare it.
for s in (f"price_{u.UK}", "load", "generation"):
    store(s, YEAR, ends_days_ago=1)
rc, rec = run()
check(rc == 0, "a one-day-old stored copy is a fallback the run SURVIVES", f"rc={rc}")
check(rec and len(rec["stale"]) == 3 and not rec["fatal"],
      "recorded as stale rather than fatal",
      rec and (len(rec["stale"]), len(rec["fatal"])))
check(rec and all(g["days_old"] <= 1 and g["covers_to"] for g in rec["stale"]),
      "carrying how old it is and how far it covers")

# 3. STORED AND TOO OLD. Past the bound it stops being a fallback and becomes a lie.
for s in (f"price_{u.UK}", "load", "generation"):
    store(s, YEAR, ends_days_ago=u.FALLBACK_DAYS + 7)
rc, rec = run()
check(rc == 1, f"a copy older than the {u.FALLBACK_DAYS}-day bound FAILS the run", f"rc={rc}")
check(rec and len(rec["fatal"]) == 3, "as fatal", rec and len(rec["fatal"]))

# 4. A COMPLETED PAST YEAR is complete by definition; its age says nothing.
past = YEAR - 1
for s in (f"price_{u.UK}", "load", "generation"):
    store(s, past, ends_days_ago=400)
rc, rec = run(years=(past,))
check(rc == 0, "a stored PAST year that failed to re-fetch is not a gap", f"rc={rc}")
check(rec is None, "and writes no record at all")

# 5. NOTHING FAILED. The record's PRESENCE is the signal, so a clean run must not write one.
rc, rec = run(fail=())
check(rc == 0 and rec is None, "a clean fetch writes no gaps record", (rc, rec is not None))

# 6. FLOWS ARE NOT REQUIRED. A border gap must not fail the run or the publish.
u.OUTCOMES.clear()
u.OUTCOMES[u.raw_path("flow_import", YEAR)] = ("flow_import", "fail")
hard, stale = u.classify_gaps()
check(not hard and not stale, "a failed border flow is not a gap", (hard, stale))

shutil.rmtree(TMP, ignore_errors=True)
print("GB GAPS: " + ("FAIL " + ", ".join(fails) if fails else "PASS"), flush=True)
sys.exit(1 if fails else 0)
