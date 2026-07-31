"""
fetch.py — pull all raw ENTSO-E series and cache to Parquet.

Series per country / year (UTC-year boundaries):
  price_<zone>   day-ahead prices (one file per price zone; IT has several)
  load           actual total load (national)
  load_<zone>    actual load per price zone  (IT only, for PUN weighting)
  generation     actual aggregated generation per production type (national)
  flow_import    physical cross-border flows INTO the country (all borders, +sum)
  flow_export    physical cross-border flows OUT of the country (all borders, +sum)
  capacity       annual installed generation capacity per type

Everything is stored with a tz-aware UTC DatetimeIndex. Resampling to the hourly
canonical timeline happens later in build_hourly.py.

Resumable: an existing, non-empty parquet for (country, series, year) is skipped
unless --force. For incremental updates, re-run with --years <latest> --force.

Usage:
  python fetch.py                       # everything, all countries, all years
  python fetch.py --country DE          # one country
  python fetch.py --country DE --years 2024   # one country-year (smoke test)
  python fetch.py --force               # re-fetch even if cached
"""
from __future__ import annotations
import argparse, glob, os, sys, time, traceback
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

import config as cfg

if not cfg.API_KEY:
    raise SystemExit("No ENTSO-E API key: set ENTSOE_API_KEY env var or create _tools/.entsoe_key")
client = EntsoePandasClient(api_key=cfg.API_KEY, retry_count=4, retry_delay=8)

SLEEP = 0.7          # politeness pause between calls (well under 400/min limit)
LOG = []

def log(msg):
    line = f"[{pd.Timestamp.now(tz='UTC').strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)

def year_bounds(year: int):
    """UTC-year boundaries. 2026 (current) capped at 'now' floored to the hour."""
    start = pd.Timestamp(f"{year}-01-01", tz="UTC")
    now = pd.Timestamp.now(tz="UTC").floor("h")
    end = pd.Timestamp(f"{year+1}-01-01", tz="UTC")
    if end > now:
        end = now
    return start, end

def raw_path(country, series, year):
    return os.path.join(cfg.RAW_DIR, f"{country}_{series}_{year}.parquet")

def _to_utc(obj):
    """Return obj with a tz-aware UTC index; DataFrame or Series."""
    idx = obj.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    obj = obj.copy()
    obj.index = idx.tz_convert("UTC")
    obj.index.name = "ts_utc"
    return obj

def _save(obj, path):
    if obj is None or len(obj) == 0:
        return False
    if isinstance(obj, pd.Series):
        obj = obj.to_frame(name="value")
    # flatten MultiIndex columns (generation) to "a|b" strings for parquet
    if isinstance(obj.columns, pd.MultiIndex):
        obj = obj.copy()
        obj.columns = ["|".join(str(x) for x in c) for c in obj.columns]
    else:
        obj = obj.copy()
        obj.columns = [str(c) for c in obj.columns]
    obj.to_parquet(path)
    return True

def _need(path, force):
    if force:
        return True
    return not (os.path.exists(path) and os.path.getsize(path) > 0)

def _merge_into(path, fresh):
    """Merge a freshly-fetched trailing window into the stored series.

    Rows are keyed on the UTC timestamp and the FRESH copy wins on overlap, which is what
    makes revisions propagate: ENTSO-E restates published values, so a re-fetched day must
    replace the stored one rather than be discarded as a duplicate. Anything outside the
    window is untouched, so the stored history is preserved without re-downloading it.
    """
    if fresh is None or len(fresh) == 0:
        return None
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return fresh                       # nothing stored yet — this IS the whole series
    old = pd.read_parquet(path)
    if isinstance(fresh, pd.Series):
        fresh = fresh.to_frame(name="value")
    if isinstance(fresh.columns, pd.MultiIndex):
        fresh = fresh.copy()
        fresh.columns = ["|".join(str(x) for x in c) for c in fresh.columns]
    else:
        fresh = fresh.copy()
        fresh.columns = [str(c) for c in fresh.columns]
    # A column set that differs is NORMAL for a trailing window and must not be treated
    # as a schema change. ENTSO-E returns a column per generation type that actually
    # reported, so a technology that produced nothing in the last 30 days simply is not
    # in the fresh frame — which says nothing about the rest of the year.
    #
    # This branch used to `return fresh`, discarding the stored series. On 2026-07-31 that
    # took FR generation from 20,213 rows to 2,880 and IT with it, deleting January to
    # June from capture_monthly for both countries. Every validator passed: the remaining
    # data was entirely valid, just six months short. Take the UNION of the columns
    # instead, so an absent technology reads as "did not generate in this window" rather
    # than "this year did not happen".
    if list(old.columns) != list(fresh.columns):
        cols = list(dict.fromkeys(list(old.columns) + list(fresh.columns)))
        added = [c for c in fresh.columns if c not in old.columns]
        gone = [c for c in old.columns if c not in fresh.columns]
        log(f"  note  {os.path.basename(path)}: column set differs "
            f"(+{len(added)} / -{len(gone)}) — taking the union, history kept")
        old = old.reindex(columns=cols)
        fresh = fresh.reindex(columns=cols)
    keep = old[~old.index.isin(fresh.index)]
    merged = pd.concat([keep, fresh]).sort_index()
    # A merge exists to ADD to the stored series. If it ever returns less than it was
    # given, something has gone wrong upstream and the stored copy is the better one —
    # this is the same "coverage may not shrink" rule the publish gate applies, asserted
    # at the point the data is written rather than eight steps later.
    if len(merged) < len(old):
        log(f"  WARN  {os.path.basename(path)}: merge would shrink {len(old)} -> "
            f"{len(merged)} rows; keeping the stored series")
        return old
    return merged


def _attempt(label, fn, path, force, merge=False, full_start=None):
    """Fetch one series. `fn` takes (start, end).

    The incremental decision is made HERE, per series, not once per country-year. The
    country-level check asks only whether SOME series is stored, so a country whose
    generation fetch had failed on an earlier run — while its prices cached fine — would
    still take the 30-day path for generation and end up with a 30-day year. That is the
    same fault that cost FR and IT six months on 2026-07-31, one step upstream: a window
    is only safe to merge when there is something to merge INTO, and that is a property
    of the individual file.
    """
    if merge and full_start is not None and not (os.path.exists(path)
                                                 and os.path.getsize(path) > 0):
        log(f"  widen {label}: nothing stored — fetching the full period, not the window")
        merge = False
        _start = full_start
    else:
        _start = None
    if not merge and not _need(path, force):
        log(f"  skip  {label} (cached)")
        return
    try:
        obj = fn(_start)
        obj = _to_utc(obj) if obj is not None and len(obj) else obj
        if merge:
            before = 0
            if os.path.exists(path) and os.path.getsize(path) > 0:
                before = len(pd.read_parquet(path))
            obj = _merge_into(path, obj)
            if _save(obj, path):
                log(f"  ok    {label}  ({before} -> {len(obj)} rows)")
            else:
                log(f"  EMPTY {label}")
        elif _save(obj, path):
            log(f"  ok    {label}  ({len(obj)} rows)")
        else:
            log(f"  EMPTY {label}")
    except NoMatchingDataError:
        log(f"  none  {label} (no data published)")
    except Exception as ex:
        log(f"  FAIL  {label}: {type(ex).__name__}: {str(ex)[:90]}")
    time.sleep(SLEEP)

def fetch_country_year(country, year, force=False, since_days=None):
    """Fetch one country-year. With since_days=N, fetch only the trailing N days and
    MERGE into what is stored, instead of re-pulling the whole year.

    Why a trailing WINDOW rather than "everything since the last timestamp": ENTSO-E
    revises data it has already published, so a strict watermark would never revisit a
    restated day. Re-fetching a window catches revisions and any hour a 503 left empty,
    which is what the full re-pull was really insuring against. Measured 2026-07-31: zero
    gaps inside the covered span across 2024, 2025 and 2026, so the in-run second pass
    already handles transient failures and the window handles the rest.
    """
    meta = cfg.COUNTRIES[country]
    code = meta["code"]
    s, e = year_bounds(year)
    s_full = s                      # kept so a series with nothing stored can widen back
    merge = False
    if since_days:
        # An incremental window is only safe if there is something to merge INTO.
        # Without this guard the first run on a cold cache fetched 30 days, merged them
        # into nothing, and published a 31-day "year" — destroying seven months of
        # history in the deliverables. The fallback was designed and then not written.
        stored = glob.glob(os.path.join(cfg.RAW_DIR, f"{country}_*_{year}.parquet"))
        stored = [f for f in stored if os.path.getsize(f) > 0]
        w = e - pd.Timedelta(days=int(since_days))
        if not stored:
            log(f"   no stored data for {country} {year} — FULL fetch (incremental needs "
                f"an existing series to merge into)")
        elif w <= s:
            log(f"   incremental window covers the whole year — full fetch")
        else:
            s, merge = w, True
            log(f"   incremental: last {since_days} days, merging into "
                f"{len(stored)} stored series")
    if s >= e:
        log(f"{country} {year}: future/empty window, skip")
        return
    log(f"== {country} ({code}) {year}  [{s.date()}..{e.date()}] ==")

    # `ov` is the per-series widen-to-full-year override: _attempt passes the full start
    # when THIS series has nothing stored to merge into, and None otherwise.
    full = s_full if merge else None

    # ---- prices (per zone) ----
    for zone in meta["price_zones"]:
        _attempt(f"price {zone}",
                 lambda ov=None, z=zone: client.query_day_ahead_prices(z, start=ov or s, end=e),
                 raw_path(country, f"price_{zone}", year), force, merge, full)

    # ---- load (national) ----
    _attempt("load",
             lambda ov=None: client.query_load(code, start=ov or s, end=e),
             raw_path(country, "load", year), force, merge, full)

    # ---- per-zone load for IT PUN weighting ----
    if len(meta["price_zones"]) > 1:
        for zone in meta["price_zones"]:
            _attempt(f"load {zone}",
                     lambda ov=None, z=zone: client.query_load(z, start=ov or s, end=e),
                     raw_path(country, f"load_{zone}", year), force, merge, full)

    # ---- generation per type (national) ----
    _attempt("generation",
             lambda ov=None: client.query_generation(code, start=ov or s, end=e, psr_type=None),
             raw_path(country, "generation", year), force, merge, full)

    # ---- cross-border physical flows (all borders) ----
    _attempt("flow_import",
             lambda ov=None: client.query_physical_crossborder_allborders(
                 code, start=ov or s, end=e, export=False),
             raw_path(country, "flow_import", year), force, merge, full)
    _attempt("flow_export",
             lambda ov=None: client.query_physical_crossborder_allborders(
                 code, start=ov or s, end=e, export=True),
             raw_path(country, "flow_export", year), force, merge, full)

    # ---- installed capacity (annual) ----
    cs = pd.Timestamp(f"{year}-01-01", tz="UTC")
    ce = pd.Timestamp(f"{year}-12-31", tz="UTC")
    # NOT merged: capacity is an annual snapshot keyed by technology, not a time series.
    # Merging a 30-day window into it would keep only the technologies present in that
    # window and silently drop the rest.
    _attempt("capacity",
             lambda ov=None: client.query_installed_generation_capacity(code, start=cs, end=ce),
             raw_path(country, "capacity", year), force or merge)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default=None, help="DE/FR/ES/PT/IT (default all)")
    ap.add_argument("--years", default=None, help="comma list, e.g. 2024 or 2019,2020")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--since-days", type=int, default=None,
                    help="fetch only the trailing N days and merge into stored data "
                         "(falls back to a full year fetch if nothing is stored)")
    a = ap.parse_args()

    countries = [a.country] if a.country else cfg.COUNTRY_ORDER
    years = [int(y) for y in a.years.split(",")] if a.years else cfg.YEARS

    t0 = time.time()
    for country in countries:
        for year in years:
            try:
                fetch_country_year(country, year, force=a.force,
                                   since_days=a.since_days)
            except Exception:
                log(f"UNCAUGHT {country} {year}\n{traceback.format_exc()}")
    log(f"DONE in {(time.time()-t0)/60:.1f} min")
    with open(os.path.join(cfg.META_DIR, "fetch_log.txt"), "a") as f:
        f.write("\n".join(LOG) + "\n")

if __name__ == "__main__":
    main()
