"""crossborder.py — fetch a country's border flows CONCURRENTLY, not one at a time.

WHY. entsoe-py's query_physical_crossborder_allborders loops over NEIGHBOURS and makes one
HTTP request per border, in sequence. That is the single biggest cost in a refresh, and it
scales with a country's border count rather than with its data: Germany has 11 neighbours,
so 22 sequential calls per run (import and export); Portugal has 1, so 2. Measured across
four runs, Germany's fetch took 25, 8, 22 and 1 minutes while Portugal's took 5, 3, 2 and
0. The wait is round-trips, not payload.

WHAT IT IS NOT. This does not fetch less. Every border is still pulled, and the result is
required to be identical to the library's, because the flows feed the generation-mix
exhibits (fig7_gen_mix carries 85 flow columns) and a mix without imports is wrong.

THE THREE THINGS THAT MAKE IT SAFE, each of which would be a real bug if missed:

  1. ORDER IS POSITIONAL, NOT COMPLETION ORDER. The library builds its frame by
     concatenating in NEIGHBOURS order, so column order is part of the output schema.
     Results are placed back into their slot by index, never appended as they arrive.
  2. ONE CLIENT PER WORKER. EntsoePandasClient wraps a requests.Session, which is not
     guaranteed thread-safe. Sharing one across threads is the classic way this kind of
     change corrupts responses under load and looks fine in testing.
  3. THE POST-PROCESSING IS THE LIBRARY'S, REPRODUCED EXACTLY: drop all-zero columns,
     convert to the area timezone, truncate to the window, then add the 'sum' column.
     crossborder_test.py drives the real library method and this function over the same
     canned data and asserts the two frames are equal, so a divergence fails a test
     rather than quietly changing what a chart shows.

A border that has no data raises NoMatchingDataError and is skipped, exactly as the
library does. Any OTHER exception is re-raised: a border failing for a real reason must
reach fetch.py's retry and fallback machinery, not be silently dropped.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

# ENTSO-E IS IMPORTED LAZILY, INSIDE THE FUNCTION. fetch_retry_test.py runs with no entsoe
# package at all, stubbing the module so the retry logic can be exercised offline and in
# CI without a key. A module-level `from entsoe.mappings import ...` here broke that suite
# the moment fetch.py imported this file: the stub is not a package, so the submodule
# import failed at import time and took the whole test down. Deferring it keeps this
# module importable anywhere and costs one dict lookup per call.

# Bounded deliberately. ENTSO-E documents a 400-requests-per-minute ceiling, so even the
# 22 calls Germany needs are far inside it, but an unbounded pool would open one socket
# per border and gains nothing over a handful of workers on a round-trip-bound task.
MAX_WORKERS = 6


def all_borders(client_factory, country_code, start, end, export, max_workers=MAX_WORKERS):
    """The library's query_physical_crossborder_allborders, with the I/O run in parallel.

    client_factory() must return a FRESH EntsoePandasClient each call (see note 2 above).
    """
    from entsoe.exceptions import NoMatchingDataError
    from entsoe.mappings import Area, NEIGHBOURS, lookup_area

    area = lookup_area(country_code) if not isinstance(country_code, Area) else country_code
    neighbours = list(NEIGHBOURS[area.name])

    def one(neighbour):
        client = client_factory()
        try:
            if export:
                s = client.query_crossborder_flows(country_code_from=country_code,
                                                   country_code_to=neighbour,
                                                   start=start, end=end, lookup_bzones=True)
            else:
                s = client.query_crossborder_flows(country_code_from=neighbour,
                                                   country_code_to=country_code,
                                                   start=start, end=end, lookup_bzones=True)
        except NoMatchingDataError:
            return None                      # same as the library: that border is skipped
        s.name = neighbour
        return s

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(neighbours)))) as pool:
        # map() yields in INPUT order regardless of completion order, which is what keeps
        # the column order identical to the library's.
        results = list(pool.map(one, neighbours))

    frames = [f for f in results if f is not None]
    if not frames:
        raise NoMatchingDataError(f"no border data for {area.name}")

    df = pd.concat(frames, axis=1, sort=True)
    df = df.loc[:, (df != 0).any(axis=0)]
    df = df.tz_convert(area.tz)
    df = df.truncate(before=start, after=end)
    df["sum"] = df.sum(axis=1)
    return df
