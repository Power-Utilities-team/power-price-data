"""
check_chart_captions.py — does the chart captioned "X" actually plot X's data?

THE FAULT THIS EXISTS TO CATCH, and it is not hypothetical: on 2026-08-25 four charts
captioned "United Kingdom" shipped plotting Spain's and France's columns. A repointing
function had a dead regex, so it returned every reference unchanged, and the charts were
emitted as faithful copies of the country they were cloned from, under a UK title.

EVERY OTHER CHECK PASSED. The package was valid, every part was declared, the chart count
was exactly what was expected, no range ran past its data, no column had moved, and both
decks matched their spec. They are all POSITIONAL checks: they ask whether the file is
well-formed and whether anything shifted. Not one of them asks what a chart MEANS. Wrong
data under a right title is the one defect that is invisible from the outside and obvious
to any reader, which makes it the worst kind to ship.

HOW IT WORKS. Every chart on the Charts tab has a caption cell immediately above it.
Every chart's series resolve to a sheet and a column letter, and every one of those
sheets is loaded from a published CSV whose header names the country. So the country in
the caption and the country in the column header can simply be compared. Where they
disagree, the chart is wrong.

WHAT IT DELIBERATELY DOES NOT DO. It says nothing about a caption naming no country (the
cross-market exhibits, which legitimately plot everyone), and nothing about a chart whose
sheet it cannot resolve to a CSV. Silence on those is stated in the output rather than
implied, so a check that has quietly stopped covering anything is visible.

Exit 0 = every country-specific caption matches the data beneath it.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import zipfile

import config as cfg

ROOT = cfg.ROOT
WB = os.path.join(ROOT, "outputs", "HourlyPowerData.xlsx")
PUB = os.path.join(ROOT, "published", "charts")
BUILT = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
CNS = "http://schemas.openxmlformats.org/drawingml/2006/chart"

# Which published CSV backs each tab, so a column letter can be turned into a header.
SHEET_CSV = {
    "Fig5_Window": "fig5_capture_window", "Fig9_Window": "fig9_capacity_window",
    "Line_Window": "line_windows",
    "HydroWindow": "hydro_window", "CaptureMonthlyExtra": "capture_monthly_extra",
    "CaptureMonthly": "capture_monthly", "Fig5_Capture": "fig5_capture_pct",
    "Fig9_Capacity": "fig9_capacity", "Fig2_Intraday": "fig2_intraday_indexed",
    "Fig2_Intraday_avg": "fig2_intraday_avg", "Fig3_CumNeg": "fig3_cum_near_neg",
    "Fig4_Duration": "fig4_duration_curve", "Fig6_MinMax": "fig6_daily_minmax",
    "Fig7_GenMix": "fig7_gen_mix", "A_MonthPrice": "figA_monthly_price",
    "B_Penetration": "figB_penetration", "G1_SolarPeak": "g1_solar_peakhour",
    "G2_MonthDuck": "g2_price_by_month", "D_NetloadDuck": "figD_netload_duck",
}

# Caption wording -> the country code whose columns the chart must read. Longest first,
# so "United Kingdom" is matched before any substring of it could be.
CAPTION_COUNTRY = sorted(
    ((meta["name"], code) for code, meta in cfg.COUNTRIES.items()),
    key=lambda t: -len(t[0]))

# The hydro tab is keyed by zone, not by the country codes above.
HYDRO_ZONE = {name: key for key, _area, name in cfg.HYDRO_RESERVOIR_ZONES}


def _col_to_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _capture_vs_base_header():
    """CaptureVsBase has no CSV behind it — it is generated — but its layout is declared.

    Without this the 37 monthly capture charts, the largest single family in the
    workbook, were skipped by this check entirely. A guard that silently covers only half
    of what it appears to is worse than one that covers none, because it reads as green.
    """
    import capture_vs_base as _cvb
    return _cvb.headers()


def _header(stem):
    for base in (BUILT, PUB):
        p = os.path.join(base, f"{stem}.csv")
        if os.path.exists(p):
            with open(p, newline="", encoding="utf-8") as f:
                return next(csv.reader(f))
    return []


def _caption_country(text):
    """The country a caption commits to, or None if it names none."""
    for name, code in CAPTION_COUNTRY:
        if name in text:
            return code, name
    return None, None


def _charts_with_captions(path):
    """[(chart part, caption, [(sheet, column letter), ...])] for the Charts tab."""
    z = zipfile.ZipFile(path)
    parts = {n: z.read(n) for n in z.namelist()}
    wbx = parts["xl/workbook.xml"].decode()
    relmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"',
                             parts["xl/_rels/workbook.xml.rels"].decode()))
    charts_part = None
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*?r:id="(rId\d+)"', wbx):
        if name == "Charts":
            charts_part = "xl/" + relmap[rid].lstrip("/")
    if not charts_part:
        return []

    srels = parts[charts_part.replace("worksheets/", "worksheets/_rels/") + ".rels"].decode()
    m = re.search(r'Target="\.\./(drawings/drawing\d+\.xml)"', srels)
    drawing = "xl/" + m.group(1)
    drels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                            parts[drawing.replace("drawings/", "drawings/_rels/") + ".rels"].decode()))

    # caption text by (row, col) on the Charts sheet
    caps = {}
    sheet = parts[charts_part].decode()
    for cell in re.findall(r'<c r="([A-Z]+)(\d+)"[^>]*>(.*?)</c>', sheet, re.S):
        col, row, body = cell
        t = re.search(r"<t[^>]*>(.*?)</t>", body, re.S)
        if t:
            caps[(int(row), _col_to_index(col))] = re.sub(r"<[^>]+>", "", t.group(1))

    out = []
    dx = parts[drawing].decode()
    for anchor in re.findall(r"<xdr:(?:one|two)CellAnchor.*?</xdr:(?:one|two)CellAnchor>", dx, re.S):
        f = re.search(r"<xdr:from>.*?<xdr:col>(\d+)</xdr:col>.*?<xdr:row>(\d+)</xdr:row>",
                      anchor, re.S)
        rid = re.search(r'<c:chart[^>]*r:id="(rId\d+)"', anchor)
        if not (f and rid):
            continue
        col, row = int(f.group(1)), int(f.group(2))
        cpart = "xl/" + drels[rid.group(1)].replace("../", "")
        caption = caps.get((row, col + 1), "")
        refs = []
        cx = parts[cpart].decode()
        for ref in re.findall(r"<c:val><c:numRef><c:f>([^<]+)</c:f>", cx):
            for one in re.findall(r"([A-Za-z0-9_]+)!\$([A-Z]{1,3})\$", ref):
                refs.append(one)
        out.append((os.path.basename(cpart), caption, refs))
    return out


def main():
    if not os.path.exists(WB):
        raise SystemExit(f"{WB} not found — build the workbook first")

    errs, checked, skipped_nocountry, skipped_nosheet = [], 0, 0, 0
    headers = {}
    for part, caption, refs in _charts_with_captions(WB):
        if not caption:
            continue
        code, name = _caption_country(caption)
        hydro_key = None
        for zname, zkey in HYDRO_ZONE.items():
            if caption.startswith(zname + " "):
                hydro_key = zkey
        if code is None and hydro_key is None:
            skipped_nocountry += 1
            continue

        want = hydro_key or code
        # Germany and Great Britain have no reservoir series, so their hydro exhibit is
        # pumped storage, whose columns are labelled "<CC>pump". Same country, different
        # token: without this the two correct charts read as failures, and a check that
        # cries wolf gets ignored, which is how a real one goes unread.
        accept = {want, f"{want}pump"}
        seen, unresolved = set(), 0
        for sheet, letters in refs:
            if sheet == "CaptureVsBase":
                if "CaptureVsBase" not in headers:
                    headers["CaptureVsBase"] = _capture_vs_base_header()
                h = headers["CaptureVsBase"]
                i = _col_to_index(letters) - 1
                if 0 <= i < len(h):
                    seen.add(h[i])
                continue
            stem = SHEET_CSV.get(sheet)
            if stem is None:
                unresolved += 1
                continue
            if stem not in headers:
                headers[stem] = _header(stem)
            h = headers[stem]
            i = _col_to_index(letters) - 1
            if 0 <= i < len(h):
                seen.add(h[i])
        if not seen:
            skipped_nosheet += 1 if unresolved else 0
            continue

        checked += 1
        # A column belongs to this chart's country if its header carries that token.
        wrong = [c for c in sorted(seen)
                 if not any(re.search(rf"(^|_){re.escape(w)}(_|$| )", c) for w in accept)]
        if wrong:
            errs.append(f"{part}: caption says {name or want!r} but plots "
                        f"{', '.join(wrong[:4])}"
                        f"{f' (+{len(wrong)-4} more)' if len(wrong) > 4 else ''}")

    print(f"chart captions: {checked} country-specific chart(s) checked; "
          f"{skipped_nocountry} name no country; {skipped_nosheet} read a sheet with no "
          f"CSV behind it", flush=True)
    if errs:
        print("CHART CAPTIONS: FAIL", flush=True)
        for e in errs:
            print("  ✗", e, flush=True)
        print("\nA chart plotting the wrong country is valid XML, the right size and in\n"
              "bounds, so no other check can see it. Fix the reference, not this check.",
              flush=True)
        sys.exit(1)
    print("CHART CAPTIONS: PASS — every country-specific caption matches its data",
          flush=True)


if __name__ == "__main__":
    main()
