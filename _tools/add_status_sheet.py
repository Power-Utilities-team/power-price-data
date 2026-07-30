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
ANY_ALARM = f'OR({NOT_REFRESHED},{STALE},{ROLLOVER_DUE})'

BANNER = [
    (3, f'=IF({NOT_REFRESHED},"!! NOT REFRESHED - this file is showing built-in preview '
        f'data, not live data. Close it, re-open, and choose Enable when Excel asks about '
        f'data connections. If that does not fix it, the network is blocking GitHub.","")',
     "red"),
    (4, f'=IF({STALE},"!! STALE DATA - the refresh has not run for "&'
        f'TEXT({DAYS},"0")&" days. Figures may be out of date.","")',
     "red"),
    (5, f'=IF({ROLLOVER_DUE},"!! ANNUAL ROLLOVER OVERDUE - charts were built for "&$E$2&'
        f'", but "&(YEAR(TODAY())-1)&" is now complete. The charts CANNOT show it on '
        f'refresh - a new year is a new chart series. Replace this file (and the .pptx) '
        f'with the newest pair from deliverables/ in the repo.","")', "red"),
    (6, f'=IF({ANY_ALARM},"ACTION: see WORK_MACHINE_SETUP.md in the repo.","")', "red"),
    # The last-refreshed line is now ALWAYS on, not just when healthy: the single most
    # asked question of this file is "how current is this?", and hiding the answer behind
    # a green-only branch meant the alarm state showed a problem without showing the date.
    (7, f'=IF({NOT_REFRESHED},"Last refreshed: UNKNOWN - not refreshed yet this session.",'
        f'"Last refreshed "&LEFT($A$2,10)&" ("&TEXT({DAYS},"0")&" days ago). '
        f'Data through "&$B$2&".")', "plain"),
    (8, f'=IF({ANY_ALARM},"","OK - data is current and the charts are up to date.")',
     "green"),
    (10, '="Charts show one series per year up to "&$E$2&'
        '". A newly completed year appears only after a rebuild, not on refresh."', "plain"),
    (11, '="Frozen history ends "&$D$2&"; last complete year in the data is "&$C$2&"."',
     "plain"),
]


def add_styles(styles: str) -> tuple[str, dict]:
    """Append a red-20pt-bold, a green-14pt-bold and a plain font + their cellXfs."""
    def count_of(tag, xml):
        m = re.search(rf"<{tag} count=\"(\d+)\"", xml)
        return int(m.group(1)) if m else 0

    nfonts = count_of("fonts", styles)
    new_fonts = (
        '<font><b/><sz val="20"/><color rgb="FFC00000"/><name val="Calibri"/></font>'
        '<font><b/><sz val="14"/><color rgb="FF006100"/><name val="Calibri"/></font>'
        '<font><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/></font>'
    )
    styles = re.sub(r"(<fonts count=\")(\d+)(\"[^>]*>)",
                    lambda m: f"{m.group(1)}{nfonts+3}{m.group(3)}", styles, count=1)
    styles = styles.replace("</fonts>", new_fonts + "</fonts>")

    nxf = count_of("cellXfs", styles)
    new_xfs = "".join(
        f'<xf numFmtId="0" fontId="{nfonts+i}" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        for i in range(3))
    styles = re.sub(r"(<cellXfs count=\")(\d+)(\")",
                    lambda m: f"{m.group(1)}{nxf+3}{m.group(3)}", styles, count=1)
    styles = styles.replace("</cellXfs>", new_xfs + "</cellXfs>")
    return styles, {"red": nxf, "green": nxf + 1, "plain": nxf + 2}


def sheet_xml(styleids: dict) -> str:
    rows = []
    for r, formula, style in BANNER:
        s = f' s="{styleids[style]}"' if style in styleids else ""
        f = formula[1:].replace("&", "&amp;").replace("<", "&lt;")   # XML-escape the formula
        rows.append(f'<row r="{r}" ht="26" customHeight="1">'
                    f'<c r="A{r}"{s} t="str"><f>{f}</f></c></row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{M}" xmlns:r="{RNS}">'
        '<dimension ref="A1:F10"/>'
        '<sheetViews><sheetView showGridLines="0" tabSelected="1" workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols><col min="1" max="1" width="140" customWidth="1"/></cols>'
        f'<sheetData>{"".join(rows)}</sheetData>'
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

    ws_part = f"xl/worksheets/sheet{next_ws}.xml"
    parts[ws_part] = sheet_xml(styleids).encode()
    order.append(ws_part)

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
