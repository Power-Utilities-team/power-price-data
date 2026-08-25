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
import argparse, glob, json, os, re, sys, time, traceback
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

# WHAT EACH SERIES ACTUALLY DID, so a failure can be reported where it happened.
# On 2026-08-18 the DE generation pull returned HTTP 504 twice, this script exited 0
# anyway, and the run died 25 minutes later in roll_line_windows.py with "chart19: 7
# series, expected 8" — a message about chart geometry, for a fault that was an upstream
# gateway timeout. Eight days of no publication followed, because every run re-pulls the
# whole year and there is no raw cache to fall back on, so each subsequent run met the
# same wall. A fetch that did not fetch has to say so, in its own step.
OUTCOMES = {}        # raw_path -> (label, "ok"|"skip"|"none"|"empty"|"fail")

# Series the rest of the pipeline cannot do without. `generation` is on the list because
# net load (demand - wind - solar) is derived from it, and a missing year there removes a
# chart series, which is a hard error downstream rather than a gap.
REQUIRED = ("load", "generation")

# ENTSO-E's gateway returns 502/503/504 under load. entsoe-py's own retry_count covers
# CONNECTION errors only: a 5xx comes back through raise_for_status() as an HTTPError and
# was never retried, so one bad minute cost a whole series for a whole year.
TRANSIENT_STATUS = (500, 502, 503, 504, 408, 429)
RETRIES = 4
RETRY_WAIT = 20      # seconds, doubling

# HOW STALE A FALLBACK MAY BE (Fred's call, 2026-08-23). When a required series cannot be
# fetched, the run may use what is already stored rather than publishing nothing — but only
# for a bounded time, and only saying so.
#
# WHY THIS DOES NOT UNDO THE 2026-08-03 DECISION. That decision removed the raw cache so
# every run re-pulls the whole year and any stored file that has gone bad is replaced. That
# still holds: a series that fetches SUCCESSFULLY overwrites, exactly as before. Only a
# series that FAILED leans on storage, and the bound caps how long it may.
#
# THE COVERAGE GUARD IS THE TIGHTER BOUND, AND IT DECIDES (measured 2026-08-23).
# This was 8, on the reasoning that one whole slot gap is the natural limit. That number was
# never reachable. check_coverage.py refuses to publish a column that lost more than BOTH 3
# cells AND 2% of what it had, and on a daily-resolution column in late August 2% is about
# 4.7 cells — so a 5-day-old fallback is REFUSED at publish and an 8-day one never had a
# chance. Documenting 8 as the bound would have sent someone hunting through the fetch logs
# for a failure that was actually a publish-time coverage refusal.
#
# Three is chosen because it is provably inside the guard at every time of year, which no
# larger number is: a 3-day-behind daily column loses exactly 3 cells, and the guard needs
# a drop STRICTLY GREATER than 3 before the percentage is even consulted. That floor is what
# saves January, when 2% of a year barely started is a single cell. On the long hourly feeds
# 3 days is ~72 rows of 6,200, which is under the 2% as well.
FALLBACK_DAYS = 3

# Read by the repair workflow and published to the status page. Its PRESENCE is the
# signal; there is no "all clear" file to go stale.
GAPS_FILE = "fetch-gaps.json"

# Set by --only. A REPAIR run re-fetches exactly the series that failed and nothing else,
# which is the difference between a two-minute repair and a thirty-minute re-pull. It has to
# override the cache check as well as select: after a bounded fallback the failed series HAS
# a stored file, so a plain incremental pass would skip the very thing it was sent to fix.
ONLY_SERIES = None

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
    if ONLY_SERIES is not None and not any(label.startswith(s) for s in ONLY_SERIES):
        return                                  # not part of this repair; leave it alone
    if ONLY_SERIES is not None:
        force = True                            # named series are re-fetched, cache or not
    if not merge and not _need(path, force):
        log(f"  skip  {label} (cached)")
        OUTCOMES[path] = (label, "skip")
        return
    def _transient(ex):
        st = getattr(getattr(ex, "response", None), "status_code", None)
        if st in TRANSIENT_STATUS:
            return True
        return type(ex).__name__ in ("ConnectionError", "Timeout", "ReadTimeout",
                                     "ConnectTimeout", "ChunkedEncodingError")

    def _call():
        wait = RETRY_WAIT
        for attempt in range(1, RETRIES + 1):
            try:
                return fn(_start)
            except NoMatchingDataError:
                raise
            except Exception as ex:
                if attempt == RETRIES or not _transient(ex):
                    raise
                log(f"  retry {label}: {type(ex).__name__} "
                    f"{getattr(getattr(ex,'response',None),'status_code','')} "
                    f"— attempt {attempt} of {RETRIES}, waiting {wait}s")
                time.sleep(wait)
                wait *= 2

    try:
        obj = _call()
        obj = _to_utc(obj) if obj is not None and len(obj) else obj
        if merge:
            before = 0
            if os.path.exists(path) and os.path.getsize(path) > 0:
                before = len(pd.read_parquet(path))
            obj = _merge_into(path, obj)
            if _save(obj, path):
                log(f"  ok    {label}  ({before} -> {len(obj)} rows)")
                OUTCOMES[path] = (label, "ok")
            else:
                log(f"  EMPTY {label}")
                OUTCOMES[path] = (label, "empty")
        elif _save(obj, path):
            log(f"  ok    {label}  ({len(obj)} rows)")
            OUTCOMES[path] = (label, "ok")
        else:
            log(f"  EMPTY {label}")
            OUTCOMES[path] = (label, "empty")
    except NoMatchingDataError:
        # NOT a failure: the publisher has nothing for this period. Distinguished from a
        # fetch that broke, so the exit check below does not fail a legitimately empty one.
        log(f"  none  {label} (no data published)")
        OUTCOMES[path] = (label, "none")
    except Exception as ex:
        log(f"  FAIL  {label}: {type(ex).__name__}: {str(ex)[:90]}")
        OUTCOMES[path] = (label, "fail")
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
    ap.add_argument("--only", default=None,
                    help="comma list of series labels to re-fetch and nothing else, e.g. "
                         "'generation,load'. Ignores what is stored for those, skips the "
                         "rest. Used by the repair run after a partial failure.")
    ap.add_argument("--since-days", type=int, default=None,
                    help="fetch only the trailing N days and merge into stored data "
                         "(falls back to a full year fetch if nothing is stored)")
    a = ap.parse_args()

    global ONLY_SERIES
    if a.only:
        ONLY_SERIES = [s.strip() for s in a.only.split(",") if s.strip()]
        log(f"REPAIR: re-fetching only {', '.join(ONLY_SERIES)}")

    # GB is on this list because everything downstream treats it as an ordinary market,
    # but its raw series come from Elexon/ECB/DUKES via fetch_uk.py — ENTSO-E stopped
    # publishing GB on 15 June 2021. Asking ENTSO-E for it would log five NoMatchingData
    # failures a year and, worse, trip the required-series gap check into declaring the
    # run broken. Named explicitly (--country GB) it still skips, with a reason.
    countries = [a.country] if a.country else cfg.COUNTRY_ORDER
    skipped = [c for c in countries if c in cfg.NON_ENTSOE]
    countries = [c for c in countries if c not in cfg.NON_ENTSOE]
    for c in skipped:
        log(f"{c}: not an ENTSO-E source ({cfg.COUNTRIES[c]['source']}) — see fetch_uk.py")
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

    # A FETCH THAT DID NOT FETCH FAILS HERE, not 25 minutes downstream. See the OUTCOMES
    # note at the top: on 2026-08-18 this exited 0 with DE generation missing, and the run
    # died later in a chart-geometry check that said nothing about ENTSO-E.
    hard, stale = classify_gaps()

    # THE GAPS RECORD. One file, written whenever anything required did not come back
    # fresh, whether the run survives it or not. It is the single input to both things that
    # happen next: the targeted repair run reads `series` to know what to re-fetch, and the
    # public status page reads it to say WHICH series is behind and why, instead of only
    # going stale on age and leaving the reason in a log nobody opens.
    if hard or stale:
        rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "countries": sorted({c for c in countries}),
               "years": sorted(years),
               "fatal": hard, "stale": stale,
               "series": sorted({g["series"] for g in hard + stale})}
        try:
            os.makedirs(cfg.META_DIR, exist_ok=True)
            with open(os.path.join(cfg.META_DIR, GAPS_FILE), "w") as fh:
                json.dump(rec, fh, indent=1)
            log(f"  wrote {GAPS_FILE}: {len(hard)} fatal, {len(stale)} running on stored data")
        except Exception as ex:
            log(f"  could not write {GAPS_FILE}: {ex}")

    for g in stale:
        log(f"  STALE {g['series']}: fetch failed, continuing on stored data to "
            f"{g['covers_to']} ({g['days_old']}d old, bound is {FALLBACK_DAYS}d)")

    if hard:
        for g in hard:
            log(f"  MISSING {g['series']}: {g['why']}")
        raise SystemExit(
            f"fetch: {len(hard)} required series could not be retrieved and no stored copy "
            f"is fresh enough to stand in ({FALLBACK_DAYS}-day bound). The build downstream "
            f"would fail on a missing chart series instead of on this, which is how eight "
            f"days went unpublished in August. ENTSO-E 5xx timeouts are transient and are "
            f"retried {RETRIES} times with backoff; a repair run re-fetches only these "
            f"series later the same day.")


def _required(label):
    return any(label.startswith(r) for r in REQUIRED) or label.startswith("price")


def _stored_coverage_end(path):
    """How far the STORED copy of a series actually runs, as a UTC timestamp.

    File mtime would be the easy answer and the wrong one: a cache restore rewrites it, so
    a file whose data stops in June can look like it was written this morning. The data's
    own last timestamp cannot lie about that.
    """
    try:
        df = pd.read_parquet(path)
        if not len(df.index):
            return None
        return pd.Timestamp(df.index.max()).tz_convert("UTC")
    except Exception:
        return None


def classify_gaps():
    """Required series that failed, split into what the run can survive and what it cannot.

    Three outcomes, and the middle one is the whole point of the bound:

      hard   nothing stored, or stored data older than FALLBACK_DAYS. The run must fail:
             publishing here means either a chart short a series or numbers presented as
             current that are not.
      stale  stored data inside the bound. The run continues on it and DECLARES it, which
             is the difference between a fallback and a silent lie.
      (kept) a completed past year. Its stored file is complete by definition, so its age
             says nothing about health and the bound does not apply.
    """
    hard, stale = [], []
    now = pd.Timestamp.now(tz="UTC")
    for path, (label, state) in OUTCOMES.items():
        if state != "fail" or not _required(label):
            continue
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            hard.append({"series": label, "file": os.path.basename(path),
                         "why": "nothing stored"})
            continue
        m = re.search(r"_(\d{4})\.parquet$", path)
        year = int(m.group(1)) if m else None
        if year is not None and year < now.year:
            continue
        end = _stored_coverage_end(path)
        if end is None:
            hard.append({"series": label, "file": os.path.basename(path),
                         "why": "stored file unreadable"})
            continue
        age = (now - end).days
        if age > FALLBACK_DAYS:
            hard.append({"series": label, "file": os.path.basename(path),
                         "why": f"stored data ends {end.date()}, {age} days old, "
                                f"past the {FALLBACK_DAYS}-day bound"})
        else:
            stale.append({"series": label, "file": os.path.basename(path),
                          "covers_to": end.isoformat(timespec="minutes"), "days_old": age})
    return hard, stale


def unmet_requirements():
    """The hard half of classify_gaps(): what no stored copy can cover for."""
    return classify_gaps()[0]

if __name__ == "__main__":
    main()
