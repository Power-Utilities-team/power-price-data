"""
bake_frozen_values.py — make the frozen workbook genuinely self-contained.

WHAT WENT WRONG. `HourlyPowerData_frozen.xlsx` exists so that a reader with no network
and no data connections still sees every exhibit: GENERATE.md defines it as "data
hardcoded and all Power Query stripped (charts recalc from static cells)". After the
2026-08-25 change it held 52 of 84 charts with no cached points and a CaptureVsBase sheet
of 45,372 formulas and zero cached values. The numbers for those charts existed nowhere in
the file. Anything that does not run a full recalculation showed blank charts: Excel on
the web, SharePoint and Teams previews, Quick Look, LibreOffice, and any Excel set to
manual calculation. `fullCalcOnLoad="1"` covers desktop Excel and nothing else.

WHY THIS IS PYTHON AND NOT EXCEL. Driving Excel to recalculate and save was the obvious
fix and cannot work: CI builds the workbook that people actually download, CI runs on
Linux, and there is no Excel there. An Excel step would have fixed the copy on one Mac and
left the published one exactly as hollow. This runs wherever the build runs.

WHAT IT DOES, in two passes:

  1. CaptureVsBase's formulas are evaluated here, from the same tabs Excel would read,
     and written back as cached values beside the formulas they came from. The formulas
     stay, so a refresh still recomputes them; the cache means a reader who never
     recalculates still sees numbers.
  2. Every chart cache is filled from the resulting cell values. A chart cache is what
     Excel draws before it recalculates, so this is the part that makes the exhibits
     appear at all in a viewer that does not calculate.

It is deliberately a SEPARATE step from build_frozen_excel.py, which hardcodes the query
tabs. That script's job is to remove the queries; this one's is to remove the dependence
on a calculating reader, and they fail differently.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import zipfile

import config as cfg
import capture_vs_base as cvb

FROZEN = os.path.join(cfg.OUTPUT_DIR, "HourlyPowerData_frozen.xlsx")
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_map(parts):
    wb = parts["xl/workbook.xml"].decode()
    rel = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"',
                          parts["xl/_rels/workbook.xml.rels"].decode()))
    out = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*?r:id="(rId\d+)"', wb):
        out[name] = "xl/" + rel[rid].lstrip("/")
    return out


def _read_values(xml):
    """{(row, col): float or str} for one worksheet part, values only."""
    vals = {}
    for m in re.finditer(r'<c r="([A-Z]+)(\d+)"([^>]*)>(.*?)</c>', xml, re.S):
        col, row, attrs, body = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        v = re.search(r"<v>([^<]*)</v>", body)
        if v is not None:
            try:
                vals[(row, _col_index(col))] = float(v.group(1))
            except ValueError:
                vals[(row, _col_index(col))] = v.group(1)
            continue
        t = re.search(r"<is><t[^>]*>(.*?)</t></is>", body, re.S)
        if t is not None:
            vals[(row, _col_index(col))] = t.group(1)
    return vals


def bake_capture_vs_base(parts, sheets):
    """Evaluate CaptureVsBase in Python and cache the results beside the formulas."""
    if cvb.PRICE_SHEET not in sheets or "CaptureVsBase" not in sheets:
        return 0
    price = _read_values(parts[sheets[cvb.PRICE_SHEET]].decode())
    src = {n: _read_values(parts[sheets[n]].decode())
           for n in (cvb.CAPTURE_SHEET, cvb.CAPTURE_SHEET_EXTRA) if n in sheets}
    status = _read_values(parts[sheets["Status"]].decode()) if "Status" in sheets else {}

    hdr, index = cvb.layout()
    n_rows = len(cvb.MONTHS) + 1
    computed = {}

    for country, tech, diff_h, pct_h in cvb.pair_columns():
        sheet = cvb.source_sheet(country)
        if sheet not in src:
            continue
        sc = cvb.source_col_index(country, tech)
        pc = cvb.price_col_index(country)
        for r in range(2, n_rows + 1):
            a = src[sheet].get((r, sc))
            b = price.get((r, pc))
            if not isinstance(a, float) or not isinstance(b, float) or b == 0:
                continue                       # stays NA(), which draws a gap
            computed[(r, index[diff_h])] = round(a - b, 2)
            computed[(r, index[pct_h])] = round(a / b * 100, 1)

    # The window blocks INDEX into a percentage column at the offset the Status year
    # implies. Same arithmetic here, so the cache cannot disagree with the formula.
    for country, tech, wh in cvb.window_columns():
        pct_col = index[f"{country}_{tech} {cvb.PCT}"]
        for i, h in enumerate(wh):
            year = status.get((2, 7 + i))
            if not isinstance(year, float):
                continue
            for r in range(2, 2 + 12):
                offset = int((year - cfg.START_YEAR) * 12 + r - 1)
                v = computed.get((offset + 1, pct_col))
                if v is not None:
                    computed[(r, index[h])] = v

    part = sheets["CaptureVsBase"]
    xml = parts[part].decode()

    def add_value(m):
        col, row, attrs, body = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if "<f>" not in body or "<v>" in body:
            return m.group(0)
        v = computed.get((row, _col_index(col)))
        if v is None:
            return m.group(0)
        return f'<c r="{col}{row}"{attrs}>{body}<v>{v}</v></c>'

    xml, n = re.subn(r'<c r="([A-Z]+)(\d+)"([^>]*)>(.*?)</c>', add_value, xml, flags=re.S)
    parts[part] = xml.encode()
    return len(computed)


def fill_chart_caches(parts, sheets):
    """Fill every empty chart cache from the workbook's own cell values."""
    values = {}
    for name, part in sheets.items():
        values[name] = _read_values(parts[part].decode())

    filled = 0
    for part in [p for p in parts if re.match(r"xl/charts/chart\d+\.xml$", p)]:
        xml = parts[part].decode()
        if "<c:pt " in xml or "<c:pt>" in xml:
            continue                                   # already cached

        def cache(m):
            kind, ref, tail = m.group(1), m.group(2), m.group(3)
            # A curated chart's reference is MULTI-AREA — "(Sheet!$A$2:$A$3,Sheet!$A$5)" —
            # because curate_tech_charts removes technologies by punching holes in the
            # range rather than moving anything. Excel numbers the points across the areas
            # in order, so the cache has to be built the same way. Handling only the
            # contiguous case left the curated capacity charts uncached, which is the one
            # kind of chart most likely to be read closely.
            areas = re.findall(r"'?([^'!(),]+)'?!\$([A-Z]+)\$(\d+)(?::\$[A-Z]+\$(\d+))?",
                               ref)
            if not areas:
                return m.group(0)
            pts, idx = [], 0
            for sheet, c0, r0, r1 in areas:
                if sheet not in values:
                    return m.group(0)
                col = _col_index(c0)
                lo, hi = int(r0), int(r1 or r0)
                for r in range(lo, hi + 1):
                    v = values[sheet].get((r, col))
                    if v is not None and v != "":
                        pts.append(f'<c:pt idx="{idx}"><c:v>{v}</c:v></c:pt>')
                    idx += 1
            if not pts:
                return m.group(0)
            n = idx
            body = (f'<c:formatCode>General</c:formatCode>' if kind == "num" else "")
            return (f'<c:{kind}Ref><c:f>{ref}</c:f><c:{kind}Cache>{body}'
                    f'<c:ptCount val="{n}"/>{"".join(pts)}</c:{kind}Cache></c:{kind}Ref>'
                    + tail)

        new = re.sub(
            r"<c:(num|str)Ref><c:f>([^<]+)</c:f><c:\1Cache>.*?</c:\1Cache></c:\1Ref>()",
            cache, xml, flags=re.S)
        if new != xml:
            parts[part] = new.encode()
            filled += 1
    return filled


def main():
    if not os.path.exists(FROZEN):
        raise SystemExit(f"{FROZEN} not found — build the frozen workbook first")
    z = zipfile.ZipFile(FROZEN)
    parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    order = [i.filename for i in z.infolist()]
    z.close()

    sheets = _sheet_map(parts)
    n_cells = bake_capture_vs_base(parts, sheets)
    n_charts = fill_chart_caches(parts, sheets)

    tmp = FROZEN + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for name in order:
            out.writestr(name, parts[name])
    shutil.move(tmp, FROZEN)
    # VERIFY, do not assume. The whole point of this file is that a reader who never
    # recalculates still sees every exhibit, and a chart left without a cache is exactly
    # the reader seeing nothing. Fail here rather than shipping a hollow deliverable that
    # looks fine to every other check.
    z = zipfile.ZipFile(FROZEN)
    empty = [n for n in z.namelist()
             if re.match(r"xl/charts/chart\d+\.xml$", n)
             and "<c:pt " not in z.read(n).decode()
             and "<c:pt>" not in z.read(n).decode()]
    print(f"baked {n_cells} CaptureVsBase values and filled {n_charts} chart cache(s) "
          f"-> {os.path.basename(FROZEN)}", flush=True)
    if empty:
        print(f"FROZEN WORKBOOK: FAIL — {len(empty)} chart(s) still have no cached data, "
              f"so they render blank for any reader who does not recalculate:", flush=True)
        for n in empty[:8]:
            print("  ✗", os.path.basename(n), flush=True)
        sys.exit(1)
    print("FROZEN WORKBOOK: PASS — every chart carries its own data", flush=True)


if __name__ == "__main__":
    sys.exit(main())
