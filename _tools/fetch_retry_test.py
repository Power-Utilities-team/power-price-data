"""Offline guard: a transient ENTSO-E 5xx must not cost a whole series, and a fetch that
did not fetch must fail its own step.

WHY THIS EXISTS. On 2026-08-18 the DE generation pull returned HTTP 504 twice. fetch.py
logged FAIL and exited 0. Every run re-pulls the whole year with no raw cache, so nothing
was stored for DE generation 2026; net load (demand - wind - solar) was therefore empty for
that year; add_phase4_charts.py emits one series per year column that HAS data, so chart19
was built with 7 series; and roll_line_windows.py, which requires exactly 8 to match the
shared rolling window, aborted the build. The pipeline published nothing for eight days and
the only visible symptom was a message about chart geometry.

    ~/.claude/pyenv/bin/python3 _tools/fetch_retry_test.py

No network, and no entsoe package needed: the client is stubbed at import, because none of
the behaviour under test goes near it.
"""
import os
import sys
import tempfile
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_entsoe = types.ModuleType("entsoe")
_entsoe.EntsoePandasClient = type("EntsoePandasClient", (), {"__init__": lambda s, **k: None})
_exc = types.ModuleType("entsoe.exceptions")
_exc.NoMatchingDataError = type("NoMatchingDataError", (Exception,), {})
_entsoe.exceptions = _exc
sys.modules.setdefault("entsoe", _entsoe)
sys.modules.setdefault("entsoe.exceptions", _exc)
os.environ.setdefault("ENTSOE_API_KEY", "stub-for-import-only")

import pandas as pd                                                        # noqa: E402
import fetch                                                               # noqa: E402

fetch.SLEEP = 0
fetch.RETRY_WAIT = 0
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("  " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


class _Resp:
    def __init__(self, code):
        self.status_code = code


_HTTPError = type("HTTPError", (Exception,), {})


def http_error(code):
    e = _HTTPError(f"{code} Server Error")
    e.response = _Resp(code)
    return e


def series(days_old=0):
    """A stored series whose data ENDS `days_old` days ago.

    Relative, never a literal: the fallback bound is measured against the data's own last
    timestamp, so a fixed date would drift past the bound and fail the suite for a calendar
    reason rather than a code one.
    """
    end = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(days=days_old)
    return pd.Series([1.0, 2.0], index=pd.date_range(end=end, periods=2, freq="h", tz="UTC"))


def main():
    tmp = tempfile.mkdtemp()

    # a 504 that clears on the third attempt: exactly the 18 Aug shape, survivable
    calls = {"n": 0}

    def flaky(_start=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise http_error(504)
        return series(0)

    good = os.path.join(tmp, "DE_generation_2026.parquet")
    fetch.OUTCOMES.clear()
    fetch._attempt("generation", flaky, good, force=True)
    check("a 504 is retried rather than abandoned", calls["n"] == 3, f"{calls['n']} attempts")
    check("the retried fetch is recorded ok", fetch.OUTCOMES.get(good, (0, 0))[1] == "ok")
    check("and the file was actually written", os.path.getsize(good) > 0)

    # a 504 that never clears: give up, but say so loudly enough to fail the step
    hard = {"n": 0}

    def dead(_start=None):
        hard["n"] += 1
        raise http_error(504)

    gone = os.path.join(tmp, "DE_generation_2025.parquet")
    fetch.OUTCOMES.clear()
    fetch._attempt("generation", dead, gone, force=True)
    check("it gives up after RETRIES attempts", hard["n"] == fetch.RETRIES, f"{hard['n']}")
    check("a dead required series is recorded as fail",
          fetch.OUTCOMES.get(gone, (0, 0))[1] == "fail")
    check("unmet_requirements catches it", len(fetch.unmet_requirements()) == 1)

    # a 400 is the caller's fault and retrying it just wastes the runner
    bad = {"n": 0}

    def bad_request(_start=None):
        bad["n"] += 1
        raise http_error(400)

    fetch.OUTCOMES.clear()
    fetch._attempt("load", bad_request, os.path.join(tmp, "DE_load_2025.parquet"), force=True)
    check("a 400 is NOT retried", bad["n"] == 1, f"{bad['n']} attempts")

    # "nothing published for this period" is DATA, not a fault
    def nodata(_start=None):
        raise fetch.NoMatchingDataError("nothing there")

    none_p = os.path.join(tmp, "DE_generation_2019.parquet")
    fetch.OUTCOMES.clear()
    fetch._attempt("generation", nodata, none_p, force=True)
    check("NoMatchingData is 'none', not 'fail'", fetch.OUTCOMES.get(none_p, (0, 0))[1] == "none")
    check("and it does not fail the step", fetch.unmet_requirements() == [])

    # only the series the pipeline cannot do without stop the run
    fetch.OUTCOMES.clear()
    fetch._attempt("flow_import", dead, os.path.join(tmp, "DE_flow_import_2026.parquet"), force=True)
    check("a failed non-required series does not fail the step", fetch.unmet_requirements() == [])

    fetch.OUTCOMES.clear()
    fetch._attempt("price DE_LU", dead, os.path.join(tmp, "DE_price_DE_LU_2026.parquet"), force=True)
    check("a dead price series DOES fail the step", len(fetch.unmet_requirements()) == 1)

    # ---- the bounded fallback ------------------------------------------------------------
    # A failed fetch over data that is still FRESH is survivable, and must be declared
    # rather than swallowed. `good` was written above with data ending now.
    fetch.OUTCOMES.clear()
    fetch.OUTCOMES[good] = ("generation", "fail")
    hard, stale = fetch.classify_gaps()
    check("a failure over fresh stored data is not fatal", hard == [], str(hard))
    check("it is recorded as stale instead", len(stale) == 1 and stale[0]["days_old"] == 0,
          str(stale))
    check("and the record says how far the stored copy runs",
          bool(stale and stale[0].get("covers_to")), str(stale))

    # Past the bound it is fatal again: stale is a bridge over one missed cycle, not a way
    # to keep publishing month-old numbers as current.
    year = pd.Timestamp.now(tz="UTC").year
    aged = os.path.join(tmp, f"DE_generation_{year}.parquet")
    series(fetch.FALLBACK_DAYS + 3).to_frame("v").to_parquet(aged)
    fetch.OUTCOMES.clear()
    fetch.OUTCOMES[aged] = ("generation", "fail")
    hard, stale = fetch.classify_gaps()
    check("stored data past the bound is fatal again", len(hard) == 1, str(hard))
    check("and the reason names the age", bool(hard and "days old" in hard[0]["why"]),
          str(hard))

    # A COMPLETED year is complete: its file cannot be "stale" in any useful sense, so the
    # bound must not apply or every run would fail on 2019.
    done = os.path.join(tmp, f"DE_generation_{year - 2}.parquet")
    series(400).to_frame("v").to_parquet(done)
    fetch.OUTCOMES.clear()
    fetch.OUTCOMES[done] = ("generation", "fail")
    hard, stale = fetch.classify_gaps()
    check("a completed past year is never judged stale", hard == [] and stale == [],
          f"hard={hard} stale={stale}")

    # An unreadable file is not a fallback.
    broken = os.path.join(tmp, f"DE_generation_{year}.parquet.bad")
    broken = os.path.join(tmp, f"DE_load_{year}.parquet")
    open(broken, "w").write("not a parquet file")
    fetch.OUTCOMES.clear()
    fetch.OUTCOMES[broken] = ("load", "fail")
    hard, _ = fetch.classify_gaps()
    check("an unreadable stored file is fatal, not a fallback", len(hard) == 1, str(hard))

    # ---- --only, the repair selector ------------------------------------------------------
    # After a bounded fallback the failed series HAS a file, so a plain incremental pass
    # would skip the one thing the repair exists to re-fetch. --only must override that.
    fetch.OUTCOMES.clear()
    seen = {"generation": 0, "load": 0}

    def counted(name):
        def fn(_start=None):
            seen[name] += 1
            return series(0)
        return fn

    fetch.ONLY_SERIES = ["generation"]
    try:
        fetch._attempt("generation", counted("generation"), good, force=False)
        fetch._attempt("load", counted("load"), good, force=False)
    finally:
        fetch.ONLY_SERIES = None
    check("--only re-fetches the named series even though a file is stored",
          seen["generation"] == 1, f"{seen['generation']} call(s)")
    check("--only leaves every other series alone", seen["load"] == 0,
          f"{seen['load']} call(s)")

    # and with no --only, a stored file is still skipped, which is what makes a normal
    # incremental pass cheap
    fetch.OUTCOMES.clear()
    seen["generation"] = 0
    fetch._attempt("generation", counted("generation"), good, force=False)
    check("without --only a stored series is still skipped", seen["generation"] == 0,
          f"{seen['generation']} call(s)")

    print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
