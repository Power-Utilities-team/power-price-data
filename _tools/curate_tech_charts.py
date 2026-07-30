"""Narrow the LIVE workbook's technology charts to the curated sets.

The PNG path curates via cfg.tech_keep()/cfg.GENMIX_KEEP; this does the same for the
Excel charts so the two update paths keep showing the same exhibit. Runs after
add_phase4_charts.py (which rebuilds charts 1-19 from the pre-phase-4 base).

  chart 6  Fig5_Capture   Germany capture vs base    -> the DE row block (11 techs)
  chart 12 Fig5_Capture   Portugal capture vs base   -> the PT row block (7 techs)
  chart 9  Fig9_Capacity  Germany installed capacity -> the DE row block (11 techs)
  chart 8  Fig7_GenMix    Portugal intraday mix      -> drop the non-curated series

Row ranges come from cfg.tech_block_start()/tech_keep(): each country gets its own
STACKED, CONTIGUOUS block of rows in the capture/capacity CSVs, so every chart can
keep the note's exact technology ordering (an Excel series reads one range).
"""
from __future__ import annotations

import csv
import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
CSVDIR = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"

# chart number -> the country whose row block it plots
ROW_CHARTS = {6: "DE", 12: "PT", 9: "DE"}


def colnum(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def narrow_rows(xml: str, start: int, keep: int) -> str:
    """Point every range at this country's block and truncate the cached points."""
    def fix_ref(m):
        return f"{m.group(1)}${start}:{m.group(2)}${start + keep - 1}"
    xml = re.sub(r"(\$[A-Z]+)\$\d+:(\$[A-Z]+)\$\d+", fix_ref, xml)

    # ptCount + drop cached points beyond the new range
    xml = re.sub(r'<c:ptCount val="\d+"/>', f'<c:ptCount val="{keep}"/>', xml)

    def drop_pts(m):
        block = m.group(0)
        out = []
        for pt in re.finditer(r'<c:pt idx="(\d+)">.*?</c:pt>', block, re.S):
            if int(pt.group(1)) < keep:
                out.append(pt.group(0))
        head = block[:block.index("<c:pt ")] if "<c:pt " in block else block
        tail = "</c:strCache>" if "strCache" in block else "</c:numCache>"
        return head + "".join(out) + tail
    xml = re.sub(r"<c:strCache>.*?</c:strCache>", drop_pts, xml, flags=re.S)
    xml = re.sub(r"<c:numCache>.*?</c:numCache>", drop_pts, xml, flags=re.S)
    return xml


def refresh_caches(xml: str, csv_path: str, start: int, keep: int) -> str:
    """Rewrite the cached categories/values from the CSV.

    The chart caches are what Excel draws BEFORE the first Power Query refresh, so
    after the CSV row order changed they must be rebuilt or the pre-refresh chart
    shows the old technologies against the new bars.
    """
    rows = list(csv.reader(open(csv_path)))
    header, body = rows[0], rows[1:]
    block = body[start - 2:start - 2 + keep]     # start is a 1-based sheet row
    labels = [r[0] for r in block]

    def cat_pts(m):
        pts = "".join(f'<c:pt idx="{i}"><c:v>{l.replace("&", "&amp;")}</c:v></c:pt>'
                      for i, l in enumerate(labels))
        return f'<c:ptCount val="{keep}"/>{pts}'
    xml = re.sub(r'<c:ptCount val="\d+"/>(?:<c:pt idx="\d+"><c:v>[^<]*</c:v></c:pt>)*',
                 lambda m: m.group(0), xml)   # (no-op guard; per-series work below)

    def one_series(ser: str) -> str:
        m = re.search(r"<c:cat>.*?<c:strCache>.*?(<c:ptCount[^>]*/>)", ser, re.S)
        if m:
            ser = re.sub(r"(<c:cat>.*?<c:strCache>).*?(</c:strCache>)",
                         lambda mm: mm.group(1) + cat_pts(mm) + mm.group(2),
                         ser, flags=re.S)
        v = re.search(r"<c:val>.*?<c:f>[^!]+!\$([A-Z]+)\$", ser, re.S)
        if v:
            ci = colnum(v.group(1)) - 1
            vals = []
            for i, r in enumerate(block):
                cell = r[ci] if ci < len(r) else ""
                if cell not in ("", None):
                    vals.append(f'<c:pt idx="{i}"><c:v>{cell}</c:v></c:pt>')
            ser = re.sub(r"(<c:val>.*?<c:numCache>.*?<c:formatCode>[^<]*</c:formatCode>).*?(</c:numCache>)",
                         lambda mm: (mm.group(1) + f'<c:ptCount val="{keep}"/>'
                                     + "".join(vals) + mm.group(2)),
                         ser, flags=re.S)
        return ser

    return re.sub(r"<c:ser>.*?</c:ser>", lambda m: one_series(m.group(0)), xml, flags=re.S)


def genmix_keep_series(xml: str, header: list[str]) -> tuple[str, list[str]]:
    """Delete <c:ser> blocks whose value column is a non-curated technology."""
    kept, dropped = [], []
    out = xml
    for ser in re.findall(r"<c:ser>.*?</c:ser>", xml, re.S):
        m = re.search(r"<c:val>.*?<c:f>Fig7_GenMix!\$([A-Z]+)\$", ser, re.S)
        if not m:                       # price series lives in a lineChart <c:ser>
            kept.append("(price)")
            continue
        col = header[colnum(m.group(1)) - 1]
        tech = col.split("_", 2)[2] if col.count("_") >= 2 else col
        if tech in cfg.GENMIX_KEEP or tech == "price":
            kept.append(tech)
        else:
            dropped.append(tech)
            out = out.replace(ser, "")
    return out, dropped


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    CSV_FOR = {6: "fig5_capture_pct", 12: "fig5_capture_pct", 9: "fig9_capacity"}
    for no, country in ROW_CHARTS.items():
        # The capture charts take a shorter PREFIX of the block than the capacity
        # chart: German nuclear sits at the tail and is excluded from Fig 5 only
        # (closed fleet, part-year 2023 artefact) — see config.TECH_BLOCKS.
        is_capture = CSV_FOR[no] == "fig5_capture_pct"
        keep = len(cfg.tech_keep_capture(country) if is_capture else cfg.tech_keep(country))
        start = cfg.tech_block_start(country)
        p = f"xl/charts/chart{no}.xml"
        xml = narrow_rows(parts[p].decode(), start, keep)
        xml = refresh_caches(xml, os.path.join(CSVDIR, CSV_FOR[no] + ".csv"), start, keep)
        parts[p] = xml.encode()
        print(f"  chart{no:<3d} {country} block -> {keep} technologies "
              f"(rows {start}..{start+keep-1})")

    hdr = next(csv.reader(open(os.path.join(CSVDIR, "fig7_gen_mix.csv"))))
    p = "xl/charts/chart8.xml"
    new, dropped = genmix_keep_series(parts[p].decode(), hdr)
    parts[p] = new.encode()
    print(f"  chart8   -> dropped {len(dropped)} series: {', '.join(dropped)}")

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"wrote {WB}")


if __name__ == "__main__":
    main()
