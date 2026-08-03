"""Add the Status sheet — a staleness banner you cannot miss.

The workbook opens ON this sheet. It reads status.csv (published by the monthly CI run,
loaded by Power Query into A1:F2) and compares it against TODAY() on the reader's own
machine, so it fires whether or not anyone here notices something has gone wrong.

Two independent alarms:
  * the monthly GitHub refresh has not run within `expected_refresh_days`
  * a calendar year has completed but the charts were built for an earlier year
    (i.e. the annual rollover in ROLLOVER.md is overdue)

Styling is deliberately simple — a red 20pt font and a green one, with the text driven
by formulas, so a healthy workbook shows nothing red. No conditional formatting / dxf
surgery, which is the fragile part of the format.

Runs after curate_tech_charts.py and BEFORE add_power_queries.py (which wires the query).
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
SHEET_NAME = "Status"
RAW_BASE = ("https://raw.githubusercontent.com/fredhill123/power-price-data/"
            "main/published/charts")

# tab -> published CSV stem, for the recovery-reference table at the bottom of the sheet.
URL_TABS = [
    ("Fig1_PriceSD", "fig1_price_sd"), ("Fig2_Intraday", "fig2_intraday_indexed"),
    ("Fig3_NegHours", "fig3_neg_hours_annual"), ("Fig3_CumNeg", "fig3_cum_near_neg"),
    ("Fig4_Duration", "fig4_duration_curve"), ("Fig5_Capture", "fig5_capture_pct"),
    ("Fig6_MinMax", "fig6_daily_minmax"), ("Fig7_GenMix", "fig7_gen_mix"),
    ("Fig9_Capacity", "fig9_capacity"), ("Fig2_Intraday_avg", "fig2_intraday_avg"),
    ("Fig5_Capture_abs", "fig5_capture_abs"), ("CaptureMonthly", "capture_monthly"),
    ("G1_SolarPeak", "g1_solar_peakhour"), ("G2_MonthDuck", "g2_price_by_month"),
    ("A_MonthPrice", "figA_monthly_price"), ("B_Penetration", "figB_penetration"),
    ("C_CaptureErosion", "figC_capture_erosion"), ("D_NetloadDuck", "figD_netload_duck"),
    ("Fig5_Window", "fig5_capture_window"), ("Fig9_Window", "fig9_capacity_window"),
    ("Status", "status"),
]

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# --- the alarm conditions, as Excel formulas over the loaded status row -------------
# B2 = coverage_end, C2 = last_complete_year, D2 = frozen_history_end,
# E2 = charts_built_for_year, F2 = expected_refresh_days, A2 = generated_utc
#
# A2 ships pre-filled with a SENTINEL, not a date (see add_power_queries.SENTINEL).
# That is deliberate and load-bearing. The workbook has to carry a preview of the query
# target, and if that preview were a real timestamp then a workbook whose refresh had
# silently failed — data connections declined at the prompt, a proxy blocking
# raw.githubusercontent.com, refresh-on-open not honoured — would display its own BUILD
# date as though it were the last refresh, and show green while doing it. The banner
# would then be asserting freshness precisely when it could not know it: failing open,
# which is the one thing a staleness warning must never do. A non-date sentinel makes
# the un-refreshed state unrepresentable as "fine".
NOT_REFRESHED = 'ISERROR(DATEVALUE(LEFT($A$2,10)))'
DAYS = 'TODAY()-DATEVALUE(LEFT($A$2,10))'
# AND()/OR() do NOT short-circuit — every argument is evaluated even once the result is
# decided — so guarding DATEVALUE with a NOT(ISERROR(...)) term inside AND() does not
# stop it erroring on the sentinel; the #VALUE! propagates out and the cell shows an
# error instead of a banner. (Caught by rendering the sheet: rows 4/6/8 came back
# Err:502.) IFERROR wraps the whole comparison instead: un-refreshed simply is not
# "stale", which is correct — row 3 already reports that state, and more loudly.
STALE = f'IFERROR(AND(ISNUMBER($F$2),({DAYS})>$F$2),FALSE)'
ROLLOVER_DUE = 'IFERROR(AND(ISNUMBER($E$2),YEAR(TODAY())-1>$E$2),FALSE)'
# ROLLOVER_DUE is deliberately NOT in here any more (2026-08-03). Every one of the
# nineteen charts now advances on an ordinary refresh, so there is no annual action to
# raise — see roll_single_year_charts.py for the last three. It stays defined above
# because the Status row still publishes charts_built_for_year, which is worth keeping
# visible as a diagnostic even though it no longer drives an alarm.
ANY_ALARM = f'OR({NOT_REFRESHED},{STALE})'

STATUS_URL = "https://power-price-data.fredhill.workers.dev"

# The whole sheet, as (row, column, formula-or-text, style).
#
# Rows 1-2 stay the Power Query load target and are HIDDEN: that row is a machine
# record with 13 wide columns, and reading it sideways is exactly what Fred asked to
# stop doing. Everything below is a transposed, labelled view of the same cells, so
# there is still only one source of truth — the loaded row — and no risk of the display
# drifting from it.
#
# READ_ME_FIRST is merged in here (bottom section). It used to be a separate tab telling
# the reader to wire queries that have been wired for weeks; the genuinely useful part
# was the tab->URL map, kept below as recovery reference and clearly labelled as such.
LAYOUT = [
    (4, "A", "Power Price Data", "title"),
    (5, "A", "European hourly power prices — Germany, Spain, Portugal, France, Italy. "
             "Source: ENTSO-E Transparency Platform.", "plain"),

    # --- alarms ---------------------------------------------------------------
    (7, "A", f'=IF({NOT_REFRESHED},"!! NOT REFRESHED - this file is showing built-in preview '
             f'data, not live data. Close it, re-open, and choose Enable Content when Excel '
             f'asks about data connections. If that does not fix it, the network is blocking '
             f'GitHub.","")', "red"),
    (8, "A", f'=IF({STALE},"!! STALE DATA - the refresh has not run for "&'
             f'TEXT({DAYS},"0")&" days. Figures may be out of date.","")', "red"),
    (10, "A", f'=IF({ANY_ALARM},"ACTION: see \'What you need to do\' below.","")', "red"),
    (11, "A", f'=IF({NOT_REFRESHED},"Last refreshed: UNKNOWN - not refreshed yet this session.",'
              f'"Last refreshed "&LEFT($A$2,10)&" ("&TEXT({DAYS},"0")&" days ago). '
              f'Data through "&$B$2&".")', "plain"),
    (12, "A", f'=IF({ANY_ALARM},"","OK - data is current and the charts are up to date.")',
     "green"),

    # --- the status row, transposed into label/value pairs ---------------------
    (14, "A", "STATUS", "head"),
    (15, "A", "Last refreshed", "label"),      (15, "B", "=$A$2", "val"),
    (16, "A", "Data through", "label"),        (16, "B", "=$B$2", "val"),
    (17, "A", "Last complete year", "label"),  (17, "B", "=$C$2", "val"),
    (18, "A", "Frozen history ends", "label"), (18, "B", "=$D$2", "val"),
    (19, "A", "Charts built for year", "label"), (19, "B", "=$E$2", "val"),
    (20, "A", "Chart year window", "label"),   (20, "B", '=$G$2&" to "&$M$2', "val"),
    (21, "A", "Refresh tolerance", "label"),   (21, "B", '=$F$2&" days"', "val"),

    # --- what the reader actually has to do ------------------------------------
    # One short line per row. Long paragraphs either wrap into very tall rows or get
    # cut off at the column edge; short lines overflow cleanly across the empty cells
    # to the right and stay readable at any column width.
    (23, "A", "WHAT YOU NEED TO DO", "head"),

    (24, "A", "NOTHING — not monthly, not yearly, not ever.", "sub"),
    (25, "A", "The data refreshes itself every time you open this file.", "plain"),
    (26, "A", "A job re-publishes it on the 2nd, 10th, 18th and 26th.", "plain"),
    (27, "A", "You never need to download a replacement for this workbook.", "plain"),

    (29, "A", "WHEN A NEW CALENDAR YEAR STARTS — still nothing.", "sub"),
    (30, "A", "Every chart here rolls forward on its own. In January the newly", "plain"),
    (31, "A", "completed year appears by itself, and the oldest drops off, so each", "plain"),
    (32, "A", "exhibit always shows the same span of recent years.", "plain"),
    (33, "A", "This is the one thing that used to need a person, and no longer does.", "plain"),

    (35, "A", "Check that the data is current, or look at the source figures:", "plain"),
    (36, "A", STATUS_URL, "link"),

    # --- reference: the plumbing, already done ---------------------------------
    (41, "A", "IF SOMETHING BREAKS — reference only, nothing to set up", "head"),
    (42, "A", "Every connection below is ALREADY configured here and refreshes on open.", "plain"),
    (43, "A", "This map exists only so one can be rebuilt by hand if it is ever lost.", "plain"),
    (44, "A", "Do not type into the data tabs — they are load targets, and anything", "plain"),
    (45, "A", "typed there is overwritten on the next refresh.", "plain"),
    (47, "A", "Tab", "label"),  (47, "B", "Loads from", "label"),
]


def add_styles(styles: str) -> tuple[str, dict]:
    """Append the fonts this sheet needs and return {name: cellXf index}."""
    def count_of(tag, xml):
        m = re.search(rf"<{tag} count=\"(\d+)\"", xml)
        return int(m.group(1)) if m else 0

    FONTS = [
        ("red",   '<b/><sz val="16"/><color rgb="FFC00000"/><name val="Calibri"/>'),
        ("green", '<b/><sz val="13"/><color rgb="FF006100"/><name val="Calibri"/>'),
        ("plain", '<sz val="11"/><color rgb="FF3F3F3F"/><name val="Calibri"/>'),
        ("title", '<b/><sz val="20"/><color rgb="FF2E3E80"/><name val="Calibri"/>'),
        ("head",  '<b/><sz val="12"/><color rgb="FF2E3E80"/><name val="Calibri"/>'),
        ("sub",   '<b/><sz val="11"/><color rgb="FF1F1F1F"/><name val="Calibri"/>'),
        ("label", '<sz val="11"/><color rgb="FF7F7F7F"/><name val="Calibri"/>'),
        ("val",   '<b/><sz val="11"/><color rgb="FF1F1F1F"/><name val="Calibri"/>'),
        ("link",  '<u/><sz val="11"/><color rgb="FF2E3E80"/><name val="Calibri"/>'),
    ]
    nfonts = count_of("fonts", styles)
    styles = re.sub(r"(<fonts count=\")(\d+)(\"[^>]*>)",
                    lambda m: f"{m.group(1)}{nfonts+len(FONTS)}{m.group(3)}", styles, count=1)
    styles = styles.replace("</fonts>",
                            "".join(f"<font>{f}</font>" for _, f in FONTS) + "</fonts>")

    nxf = count_of("cellXfs", styles)
    styles = re.sub(r"(<cellXfs count=\")(\d+)(\")",
                    lambda m: f"{m.group(1)}{nxf+len(FONTS)}{m.group(3)}", styles, count=1)
    styles = styles.replace("</cellXfs>", "".join(
        f'<xf numFmtId="0" fontId="{nfonts+i}" fillId="0" borderId="0" xfId="0" '
        f'applyFont="1" applyAlignment="1">'
        f'<alignment horizontal="left" vertical="center"/></xf>'
        for i in range(len(FONTS))) + "</cellXfs>")
    return styles, {name: nxf + i for i, (name, _) in enumerate(FONTS)}


def sheet_xml(styleids: dict, urlmap) -> str:
    """The whole Status sheet: hidden load row, alarms, transposed status, instructions."""
    cells = {}

    def put(r, col, text, style):
        esc = (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        sid = f' s="{styleids[style]}"' if style in styleids else ""
        if str(text).startswith("="):
            cells.setdefault(r, []).append(
                f'<c r="{col}{r}"{sid} t="str"><f>{esc[1:]}</f></c>')
        else:
            cells.setdefault(r, []).append(
                f'<c r="{col}{r}"{sid} t="inlineStr"><is><t>{esc}</t></is></c>')

    for r, col, text, style in LAYOUT:
        put(r, col, text, style)

    # the tab -> URL reference map, appended under the header row of the last section
    row = max(r for r, *_ in LAYOUT) + 1
    for tab, url in urlmap:
        put(row, "A", tab, "plain")
        put(row, "B", url, "plain")
        row += 1

    body = ""
    for r in sorted(cells):
        # rows 1-2 are the Power Query load target: keep them, hide them
        hidden = ' hidden="1"' if r <= 2 else ""
        ht = ' ht="30" customHeight="1"' if r in (4,) else ""
        body += f'<row r="{r}"{hidden}{ht}>{"".join(cells[r])}</row>'

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{M}" xmlns:r="{RNS}">'
        f'<dimension ref="A1:M{row}"/>'
        '<sheetViews><sheetView showGridLines="0" tabSelected="1" workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols><col min="1" max="1" width="30" customWidth="1"/>'
        '<col min="2" max="2" width="26" customWidth="1"/></cols>'
        f'<sheetData>{body}</sheetData>'
        '</worksheet>')


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    wb = parts["xl/workbook.xml"].decode()
    if f'<sheet name="{SHEET_NAME}"' in wb:
        print(f"{SHEET_NAME} sheet already present")
        return

    rels = parts["xl/_rels/workbook.xml.rels"].decode()
    sheets = re.findall(r'<sheet name="[^"]+" sheetId="(\d+)" r:id="rId(\d+)"/>', wb)
    next_sheet_id = max(int(s) for s, _ in sheets) + 1
    next_rid = max(int(n) for n in re.findall(r'Id="rId(\d+)"', rels)) + 1
    ws_nums = [int(n) for n in re.findall(r"xl/worksheets/sheet(\d+)\.xml$",
                                          "\n".join(order), re.M)]
    next_ws = max(ws_nums) + 1

    parts["xl/styles.xml"], styleids = add_styles(parts["xl/styles.xml"].decode())
    parts["xl/styles.xml"] = parts["xl/styles.xml"].encode()

    # The tab -> URL map is derived from the published CSVs the queries actually load,
    # so the reference section cannot drift from the wiring the way the old
    # READ_ME_FIRST tab did (it still described work that had been done for weeks).
    urlmap = [(tab, f"{RAW_BASE}/{stem}.csv") for tab, stem in URL_TABS]

    ws_part = f"xl/worksheets/sheet{next_ws}.xml"
    parts[ws_part] = sheet_xml(styleids, urlmap).encode()
    order.append(ws_part)

    # the status page, as a real clickable hyperlink on the URL cell
    parts[ws_part.replace("worksheets/", "worksheets/_rels/") + ".rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{RNS}/hyperlink" Target="{STATUS_URL}" '
        f'TargetMode="External"/></Relationships>').encode()
    order.append(ws_part.replace("worksheets/", "worksheets/_rels/") + ".rels")
    parts[ws_part] = parts[ws_part].decode().replace(
        "</sheetData>",
        '</sheetData><hyperlinks><hyperlink ref="A39" r:id="rId1"/></hyperlinks>').encode()

    # append LAST so every existing ExternalData_1 localSheetId stays valid
    wb = wb.replace("</sheets>",
                    f'<sheet name="{SHEET_NAME}" sheetId="{next_sheet_id}" '
                    f'r:id="rId{next_rid}"/></sheets>')
    # open on this sheet, and make Excel evaluate the banner formulas on load
    idx = len(sheets)

    def _set_active(m):
        attrs = re.sub(r'\s*activeTab="\d+"', "", m.group(1))
        return f'<workbookView{attrs} activeTab="{idx}"/>'
    wb = re.sub(r'<workbookView([^>]*?)/>', _set_active, wb, count=1)
    wb = wb.replace('<calcPr calcId="191029"/>',
                    '<calcPr calcId="191029" fullCalcOnLoad="1"/>')
    parts["xl/workbook.xml"] = wb.encode()

    parts["xl/_rels/workbook.xml.rels"] = rels.replace(
        "</Relationships>",
        f'<Relationship Id="rId{next_rid}" Type="{RNS}/worksheet" '
        f'Target="worksheets/sheet{next_ws}.xml"/></Relationships>').encode()

    ct = parts["[Content_Types].xml"].decode()
    parts["[Content_Types].xml"] = ct.replace(
        "</Types>",
        f'<Override PartName="/xl/worksheets/sheet{next_ws}.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>").encode()

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"added {SHEET_NAME} sheet (sheet{next_ws}, tab index {idx}, opens on it)")


if __name__ == "__main__":
    main()
