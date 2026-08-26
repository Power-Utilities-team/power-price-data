"""chunked_test.py — one request first, month blocks only on a transient failure.

No network and no API key. `fetch.py` refuses to import without a key, and the CI job that
runs the suites does not have one, so the key is stubbed on `config` before the import.

WHAT IS ACTUALLY BEING TESTED, in two halves.

  1. WHEN IT SPLITS. Never on a healthy window, because splitting a two-month window that
     works costs 196s against 76s (measured 2026-08-26, identical data both ways). Always
     on a transient failure, because the whole-window request for eight months of German
     generation returns HTTP 504 after 180s every time it is tried. Never on a malformed
     request, which would fail the same way twelve times over.

  2. THAT THE PIECES REASSEMBLE. Splitting one request into eight is only safe if the eight
     answers rebuild exactly the one answer. The failure modes are losing a block,
     double-counting a boundary row, reordering, and turning one empty month into a dead
     fetch. Each has an assertion, driven through a forced fallback.
"""
from __future__ import annotations

import sys

import pandas as pd

import config as cfg

# Before importing fetch, which exits at import time without one.
if not cfg.API_KEY:
    cfg.API_KEY = "stub-key-for-tests"

import fetch                                                          # noqa: E402
from entsoe.exceptions import NoMatchingDataError                     # noqa: E402

TZ = "Europe/Brussels"
fails = []


def check(ok, name, extra=None):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}"
          + ("" if ok or extra is None else f"   {extra}"), flush=True)
    if not ok:
        fails.append(name)


def series_for(a, b):
    idx = pd.date_range(a.tz_convert("UTC"), b.tz_convert("UTC"), freq="15min",
                        inclusive="left")
    return pd.Series(range(len(idx)), index=idx, dtype=float)


class _Resp:
    def __init__(self, code):
        self.status_code = code


class Gateway504(Exception):
    """Shaped like the HTTPError entsoe-py raises: the code hangs off .response."""
    def __init__(self):
        super().__init__("504 Server Error: Gateway Time-out")
        self.response = _Resp(504)


S = pd.Timestamp("2026-01-01", tz=TZ)
E = pd.Timestamp("2026-08-26", tz=TZ)
WHOLE = pd.date_range(S.tz_convert("UTC"), E.tz_convert("UTC"), freq="15min",
                      inclusive="left")


def whole_first(fail_whole=True, per_block=None, blowup=None):
    """A call that fails the whole window once, then serves blocks. Records every call."""
    calls = []

    def call(a, b):
        calls.append((a, b))
        if (a, b) == (S, E):
            if blowup is not None:
                raise blowup
            if fail_whole:
                raise Gateway504()
            return series_for(a, b)
        if per_block is not None:
            r = per_block(a, b)
            if r is not None:
                return r
        return series_for(a, b)

    return call, calls


# ---- 1. WHEN IT SPLITS -------------------------------------------------------------------
call, calls = whole_first(fail_whole=False)
out = fetch._chunked(call, S, E)
check(len(calls) == 1 and calls[0] == (S, E),
      "a healthy window is ONE request, not eight", len(calls))
check(len(out) == len(WHOLE), "and returns the whole window")

call, calls = whole_first(fail_whole=True)
out = fetch._chunked(call, S, E)
check(len(calls) == 9,
      "a 504 on the whole window falls back to eight month blocks", f"{len(calls)} calls")
check(len(out) == len(WHOLE),
      "and the fallback still covers the whole window", f"{len(out)} vs {len(WHOLE)}")

# A malformed request fails identically however it is sliced, so splitting would waste eight
# more round trips to learn the same thing.
call, calls = whole_first(blowup=ValueError("bad parameter"))
try:
    fetch._chunked(call, S, E)
    check(False, "a non-transient failure propagates rather than triggering a split")
except ValueError:
    check(len(calls) == 1,
          "a non-transient failure propagates rather than triggering a split", len(calls))

# "Nothing published" is not a size problem either.
call, calls = whole_first(blowup=NoMatchingDataError("nothing published"))
try:
    fetch._chunked(call, S, E)
    check(False, "an empty answer for the whole window does not trigger a split")
except NoMatchingDataError:
    check(len(calls) == 1,
          "an empty answer for the whole window does not trigger a split", len(calls))

# A window inside one month has nothing to fall back to, so it is passed straight through.
calls2 = []
short = pd.Timestamp("2026-03-05", tz=TZ), pd.Timestamp("2026-03-20", tz=TZ)
fetch._chunked(lambda a, b: (calls2.append((a, b)), series_for(a, b))[1], *short)
check(len(calls2) == 1 and calls2[0] == short,
      "a window inside one month is one call, untouched", calls2)

# ---- 2. THAT THE PIECES REASSEMBLE (driven through a forced fallback) ---------------------
call, _ = whole_first(fail_whole=True)
out = fetch._chunked(call, S, E)
check(out.index.is_monotonic_increasing, "the stitched result is in time order")
check(not out.index.has_duplicates, "with no duplicated timestamps")

# ENTSO-E returns rows just outside a requested window; the library's own year_limited says
# so. Two blocks can carry the same timestamp, and the later one must win.
def overlap(a, b):
    idx = pd.date_range((a - pd.Timedelta(minutes=15)).tz_convert("UTC"),
                        b.tz_convert("UTC"), freq="15min", inclusive="left")
    return pd.Series([1.0] * len(idx), index=idx)


call, _ = whole_first(fail_whole=True, per_block=overlap)
out = fetch._chunked(call, S, E)
check(not out.index.has_duplicates,
      "a row returned by two adjacent blocks is kept once",
      int(out.index.duplicated().sum()))

MARCH = pd.date_range(pd.Timestamp("2026-03-01", tz=TZ).tz_convert("UTC"),
                      pd.Timestamp("2026-04-01", tz=TZ).tz_convert("UTC"),
                      freq="15min", inclusive="left")


def march_raises(a, b):
    if a.month == 3:
        raise NoMatchingDataError("nothing published")
    return None


call, _ = whole_first(fail_whole=True, per_block=march_raises)
out = fetch._chunked(call, S, E)
check(len(out) == len(WHOLE) - len(MARCH),
      "a month with nothing published is skipped, the others survive",
      f"{len(out)} vs {len(WHOLE) - len(MARCH)}")


def march_blank(a, b):
    return series_for(a, b).iloc[:0] if a.month == 3 else None


call, _ = whole_first(fail_whole=True, per_block=march_blank)
out = fetch._chunked(call, S, E)
check(len(out) == len(WHOLE) - len(MARCH),
      "and an empty answer is treated the same as no answer")


def all_raise(a, b):
    raise NoMatchingDataError("nothing published")


call, _ = whole_first(fail_whole=True, per_block=all_raise)
try:
    fetch._chunked(call, S, E)
    check(False, "a window with nothing in any block raises rather than returning nothing")
except NoMatchingDataError:
    check(True, "a window with nothing in any block raises rather than returning nothing")


# THE WORST OUTCOME this must avoid: seven months of eight, returned as if complete. Every
# downstream check would treat that short series as real data.
def may_504(a, b):
    if a.month == 5:
        raise Gateway504()
    return None


call, _ = whole_first(fail_whole=True, per_block=may_504)
try:
    fetch._chunked(call, S, E)
    check(False, "a block that fails is NOT swallowed into a silently short series")
except Exception as ex:                                               # noqa: BLE001
    check(isinstance(ex, Gateway504),
          "a block that fails is NOT swallowed into a silently short series", type(ex))


def frame_block(a, b):
    idx = pd.date_range(a.tz_convert("UTC"), b.tz_convert("UTC"), freq="15min",
                        inclusive="left")
    return pd.DataFrame({"Solar": 1.0, "Wind": 2.0}, index=idx)


call, _ = whole_first(fail_whole=True, per_block=frame_block)
out = fetch._chunked(call, S, E)
check(isinstance(out, pd.DataFrame) and list(out.columns) == ["Solar", "Wind"],
      "a multi-column result keeps its columns and their order", list(out.columns))
check(len(out) == len(WHOLE), "and its full row count")

print("CHUNKED: " + ("FAIL " + ", ".join(fails) if fails else "PASS"), flush=True)
sys.exit(1 if fails else 0)
