"""
fetch_hydro.py — pull ENTSO-E's WEEKLY water-reservoir and hydro-storage series (A72).

This is the data behind the reservoir-fill-vs-historic-range charts. It is a different
ENTSO-E endpoint from anything the price pipeline used before 2026-08-25: A72 is a
weekly STOCK (energy stored in reservoirs, MWh) rather than an hourly FLOW, so it is
fetched, stored and summarised on its own path and never joins the hourly master.

Coverage, probed 2026-08-25 with a single-year call per zone:
    yes   FR ES PT IT, NO and NO_1..NO_5, SE, FI, AT, CH  (53 weekly points in 2025)
    no    Germany — DE_LU, DE and DE_AT_LU all return NoMatchingData
    no    Great Britain — no domain code returns it
Germany and the UK therefore get a pumped-storage chart instead; see config.PUMPED_ONLY.

Stored one parquet per (zone, year), matching fetch.py's habit of re-pulling a whole
year so a restated week replaces rather than duplicates.

Usage:
  python fetch_hydro.py                  # every zone, HYDRO_START_YEAR..current
  python fetch_hydro.py --zones NO,SE    # a subset, by config key
  python fetch_hydro.py --years 2026     # one year
  python fetch_hydro.py --force
"""
from __future__ import annotations
import argparse, os, sys, time, warnings
warnings.filterwarnings("ignore")
import pandas as pd

import config as cfg

LOG = []


def log(m):
    print(m, flush=True)
    LOG.append(m)


def raw_path(key, year):
    return os.path.join(cfg.RAW_DIR, f"hydro_{key}_{year}.parquet")


def _need(path, force):
    return force or not (os.path.exists(path) and os.path.getsize(path) > 0)


def fetch(zones=None, years=None, force=False):
    from entsoe import EntsoePandasClient
    from entsoe.exceptions import NoMatchingDataError

    if not cfg.API_KEY:
        raise SystemExit("No ENTSO-E API key: set ENTSOE_API_KEY or create _tools/.entsoe_key")
    client = EntsoePandasClient(api_key=cfg.API_KEY, retry_count=4, retry_delay=8)

    wanted = {k for k in (zones or [])} or None
    targets = [z for z in cfg.HYDRO_RESERVOIR_ZONES if wanted is None or z[0] in wanted]
    years = years or list(range(cfg.HYDRO_START_YEAR, cfg.CURRENT_YEAR + 1))

    have, missing = [], []
    for key, area, name in targets:
        got_any = False
        for year in years:
            path = raw_path(key, year)
            if not _need(path, force):
                got_any = True
                continue
            s = pd.Timestamp(f"{year}-01-01", tz="UTC")
            e = min(pd.Timestamp(f"{year + 1}-01-01", tz="UTC"),
                    pd.Timestamp.now(tz="UTC").floor("h"))
            if s >= e:
                continue
            try:
                r = client.query_aggregate_water_reservoirs_and_hydro_storage(
                    area, start=s, end=e)
            except NoMatchingDataError:
                log(f"   {name} {year}: no data")
                continue
            except Exception as ex:               # noqa: BLE001 - one bad year is not fatal
                log(f"   {name} {year}: {type(ex).__name__} — skipped")
                continue
            if r is None or len(r) == 0:
                log(f"   {name} {year}: empty")
                continue
            df = r.to_frame(name="stored_mwh") if isinstance(r, pd.Series) else r
            df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
            df.index.name = "ts_utc"
            df.to_parquet(path)
            log(f"   {name} {year}: {len(df)} weeks")
            got_any = True
            time.sleep(0.7)                       # the politeness pause fetch.py uses
        (have if got_any else missing).append(name)

    log(f"reservoir data present for {len(have)} zone(s): {', '.join(have)}")
    if missing:
        log(f"no reservoir data at all for: {', '.join(missing)}")
    return have, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", default=None, help="comma list of config keys, e.g. NO,SE")
    ap.add_argument("--years", default=None, help="comma list, e.g. 2026")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    zones = [z.strip() for z in a.zones.split(",")] if a.zones else None
    years = [int(y) for y in a.years.split(",")] if a.years else None

    t0 = time.time()
    fetch(zones=zones, years=years, force=a.force)
    log(f"DONE in {(time.time() - t0) / 60:.1f} min")
    with open(os.path.join(cfg.META_DIR, "fetch_hydro.log"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    sys.exit(main())
