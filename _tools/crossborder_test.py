"""crossborder_test.py — the concurrent border fetch must equal the library's, exactly.

The flows feed the generation-mix exhibits, so a divergence here does not crash: it
quietly changes what a published chart shows. This drives entsoe-py's REAL
query_physical_crossborder_allborders and our crossborder.all_borders over the same canned
responses, and asserts the two DataFrames are identical - values, column order, index and
dtypes. No network, so it runs anywhere the build runs.

The cases are chosen to be the ways a parallel rewrite actually goes wrong:
  * out-of-order completion (a slow early border, a fast late one) must not reorder columns
  * a border with no data must be skipped, exactly as the library skips it
  * an all-zero border must be dropped, because the library drops it
  * a real error must PROPAGATE, so fetch.py's retry and fallback still see it
  * each worker must get its own client, never a shared session
"""
from __future__ import annotations

import sys
import time
import threading

import pandas as pd
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError
from entsoe.mappings import NEIGHBOURS, lookup_area

import crossborder

_MISSING = object()   # sentinel: a Series must never be compared with ==

START = pd.Timestamp("2026-01-01 00:00", tz="UTC")
END = pd.Timestamp("2026-01-01 06:00", tz="UTC")
COUNTRY = "DE_LU"
FAILS = 0


def check(name, cond, detail=""):
    global FAILS
    print(f"  {'ok ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")
    if not cond:
        FAILS += 1


def series(offset, n=6, zero=False):
    idx = pd.date_range(START, periods=n, freq="h", tz="UTC")
    return pd.Series([0 if zero else offset + i for i in range(n)], index=idx)


class FakeClient(EntsoePandasClient):
    """The real client with ONLY the per-border network call replaced."""

    def __init__(self, plan, delays=None, seen=None):
        super().__init__(api_key="test-key-not-used")
        self.plan, self.delays, self.seen = plan, delays or {}, seen

    def query_crossborder_flows(self, country_code_from, country_code_to, start, end,
                                lookup_bzones=False):
        other = country_code_to if str(country_code_from).startswith("DE") else country_code_from
        key = str(other)
        if self.seen is not None:
            self.seen.append(threading.get_ident())
        if key in self.delays:
            time.sleep(self.delays[key])
        val = self.plan.get(key, _MISSING)
        if val is _MISSING:
            raise NoMatchingDataError(f"no data for {key}")
        if isinstance(val, Exception):
            raise val
        return val


def plans():
    """A response for every DE neighbour, deliberately not all the same."""
    ns = list(NEIGHBOURS[lookup_area(COUNTRY).name])
    return ns, {n: series(10 * (i + 1)) for i, n in enumerate(ns)}


def run_library(plan, delays=None):
    c = FakeClient(plan, delays)
    return c.query_physical_crossborder_allborders(COUNTRY, start=START, end=END, export=False)


def run_concurrent(plan, delays=None, seen=None):
    return crossborder.all_borders(lambda: FakeClient(plan, delays, seen),
                                   COUNTRY, START, END, export=False)


def main():
    ns, plan = plans()
    print(f"crossborder equivalence: {COUNTRY}, {len(ns)} borders\n")

    a, b = run_library(plan), run_concurrent(plan)
    check("identical for the ordinary case", a.equals(b))
    check("same column order", list(a.columns) == list(b.columns),
          f"{list(a.columns)} vs {list(b.columns)}")

    # The failure mode a parallel rewrite is most likely to have: the first border is slow,
    # the last is instant, so completion order is the reverse of neighbour order.
    delays = {ns[0]: 0.25, ns[1]: 0.15}
    a2, b2 = run_library(plan), run_concurrent(plan, delays)
    check("out-of-order completion does not reorder columns", a2.equals(b2),
          f"{list(a2.columns)} vs {list(b2.columns)}")

    # A border with no data at all.
    p3 = dict(plan); p3.pop(ns[2])
    a3, b3 = run_library(p3), run_concurrent(p3)
    check("a border with no data is skipped identically", a3.equals(b3))
    check("  and that border is absent from both", ns[2] not in b3.columns)

    # An all-zero border: the library drops it.
    p4 = dict(plan); p4[ns[1]] = series(0, zero=True)
    a4, b4 = run_library(p4), run_concurrent(p4)
    check("an all-zero border is dropped identically", a4.equals(b4))

    # A real error must NOT be swallowed.
    p5 = dict(plan); p5[ns[3]] = RuntimeError("ENTSO-E 503")
    raised = False
    try:
        run_concurrent(p5)
    except RuntimeError:
        raised = True
    check("a real error propagates to the caller", raised,
          "it was swallowed — fetch.py's retry and fallback would never see it")

    check("the sum column is present and correct",
          "sum" in b.columns and bool((b["sum"] == b.drop(columns="sum").sum(axis=1)).all()))

    # THE WORK MUST ACTUALLY BE PARALLEL, and each worker must hold its own client.
    # Asserted, not assumed: a refactor that quietly serialised this would still pass every
    # equivalence check above while delivering none of the speed it exists for, and a
    # refactor that shared one client would pass them too while sharing a requests.Session
    # across threads.
    seen, clients = [], []
    factory_calls = {"n": 0}

    def counting_factory():
        factory_calls["n"] += 1
        c = FakeClient(plan, {ns[0]: 0.20}, seen)
        # Keep the OBJECT, not its id(). CPython reuses an address once an object is
        # freed, and with a bounded pool only a few clients are alive at once, so a set of
        # ids reported 6 distinct clients for 11 correct calls. The test was wrong, not
        # the code, and an id-based assertion here would have gone on lying either way.
        clients.append(c)
        return c

    out = crossborder.all_borders(counting_factory, COUNTRY, START, END, export=False)
    check("more than one thread did the work", len(set(seen)) > 1,
          f"only {len(set(seen))} thread(s) — it ran serially")
    check("a fresh client per border call", factory_calls["n"] == len(ns)
          and len({id(c) for c in clients}) == len(ns),
          f"{factory_calls['n']} factory calls, {len({id(c) for c in clients})} distinct "
          f"clients, {len(ns)} borders")
    check("parallel result still equals the library's", run_library(plan).equals(out))

    print(f"\n{'CROSSBORDER: PASS' if not FAILS else f'CROSSBORDER: FAIL — {FAILS} problem(s)'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
