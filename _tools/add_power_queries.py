"""Wire the 6 remaining Power Query connections INTO the workbook — no manual Excel work.

Runs after add_phase4_charts.py. For each of the six empty target tabs it creates, by
cloning the patterns the existing 12 queries already use in this same file:

  * an M query in the DataMashup blob   (customXml/item1.xml -> Formulas/Section1.m)
  * a workbook connection               (xl/connections.xml)
  * a queryTable + ListObject table     (xl/queryTables/, xl/tables/ + sheet rels)
  * the hidden ExternalData_1 name      (xl/workbook.xml definedNames)
  * the current CSV data, pre-filled    (so charts draw before the first refresh)

It also sets refresh-on-open (refreshOnLoad="1", background="0") on ALL connections,
which is the manual "Properties -> Refresh data when opening the file" step.

Everything is written by XML surgery on the existing package — no openpyxl round-trip —
so the 12 queries Fred already wired, and every chart/drawing part, survive untouched.
"""
from __future__ import annotations

import csv
import os
import re
import struct
import uuid
import zipfile
import base64
import io
import xml.etree.ElementTree as ET

import config as cfg

ROOT = cfg.ROOT
WB = os.path.join(ROOT, "outputs", "HourlyPowerData.xlsx")
PUB = os.path.join(ROOT, "published", "charts")
BASE_URL = ("https://raw.githubusercontent.com/Power-Utilities-team/power-price-data/"
            "main/published/charts/")

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKGREL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", M)

# tab name -> published CSV stem.  Order = document order of the six target tabs.
TARGETS = [
    ("G1_SolarPeak",     "g1_solar_peakhour"),
    ("G2_MonthDuck",     "g2_price_by_month"),
    ("A_MonthPrice",     "figA_monthly_price"),
    ("B_Penetration",    "figB_penetration"),
    ("C_CaptureErosion", "figC_capture_erosion"),
    ("D_NetloadDuck",    "figD_netload_duck"),
    ("Status",           "status"),
    # Rolling-window tables for the annual bar charts. Data-only tabs (no chart of their
    # own): chart6/12 and chart9 read them, so a new complete year reaches those charts
    # on an ordinary refresh instead of needing the workbook rebuilt. See
    # roll_year_window.py for why the window rolls rather than grows.
    ("Fig5_Window",      "fig5_capture_window"),
    ("Fig9_Window",      "fig9_capacity_window"),
    ("Line_Window",      "line_windows"),
    # Added 2026-08-25 with the UK and the hydro tracker. Both tabs are created by
    # add_extra_charts.py, which runs just before this script for that reason.
    #
    # CaptureMonthlyExtra exists because CaptureMonthly cannot grow: its table is one of
    # the inherited 86-column ones, exactly wide enough for the original five countries,
    # so a sixth market's columns would fall outside it and no chart or refresh would
    # ever reach them. Countries beyond those five load here instead.
    ("CaptureMonthlyExtra", "capture_monthly_extra"),
    ("HydroWindow",         "hydro_window"),
]

_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")   # fixed -> deterministic uids


def guid(*bits) -> str:
    return "{" + str(uuid.uuid5(_NS, "|".join(map(str, bits)))).upper() + "}"


def col_letter(n: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# read the CSVs and work out each column's type
# ---------------------------------------------------------------------------
def load_csv(stem):
    with open(os.path.join(PUB, stem + ".csv"), newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    kinds = []
    for i, name in enumerate(header):
        vals = [r[i] for r in body if i < len(r) and r[i] != ""]
        if not vals:
            kinds.append("text")            # all-blank future column
        elif name == "date" or any(re.match(r"\d{4}-\d{2}-\d{2}", v) for v in vals):
            kinds.append("date_text")       # keep as text: charts cache these as strRef
        elif all(re.fullmatch(r"-?\d+", v) for v in vals):
            kinds.append("int")
        elif all(re.fullmatch(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", v) for v in vals):
            kinds.append("number")
        else:
            # Genuine text (fig5_capture_pct's 'technology' column). Until 2026-07-22 this
            # fell through to "number", which wrote the label into a numeric <v> unescaped —
            # "Oil & other fossil" then made the whole sheet malformed XML and Excel offered
            # to Recover the workbook. Only ever surfaced once a text column was resynced.
            kinds.append("text")
    return header, body, kinds


# ---------------------------------------------------------------------------
# worksheet cells
# ---------------------------------------------------------------------------
_NUMERIC = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def sheet_data_xml(header, body, kinds):
    out = ["<sheetData>"]
    cells = "".join(
        f'<c r="{col_letter(i+1)}1" t="inlineStr"><is><t>{esc(h)}</t></is></c>'
        for i, h in enumerate(header))
    out.append(f'<row r="1" spans="1:{len(header)}">{cells}</row>')
    for ri, row in enumerate(body, start=2):
        cs = []
        for i, kind in enumerate(kinds):
            v = row[i] if i < len(row) else ""
            if v == "":
                continue                                   # leave the cell empty
            ref = f"{col_letter(i+1)}{ri}"
            # belt-and-braces: a value that is not actually numeric must never reach a bare
            # <v>, whatever the column was classified as — that is what corrupts the part.
            if kind in ("int", "number") and _NUMERIC.fullmatch(v):
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cs.append(f'<c r="{ref}" t="inlineStr"><is><t>{esc(v)}</t></is></c>')
        if cs:
            out.append(f'<row r="{ri}" spans="1:{len(header)}">{"".join(cs)}</row>')
    out.append("</sheetData>")
    return "".join(out)


def patch_sheet(xml: str, header, body, kinds, table_rid: str) -> str:
    ref = f"A1:{col_letter(len(header))}{len(body)+1}"
    xml = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="{ref}"/>', xml)
    new = sheet_data_xml(header, body, kinds)
    if "<sheetData/>" in xml:
        xml = xml.replace("<sheetData/>", new)
    else:
        # sheet already has rows (the Status banner): merge, keeping ascending row order
        existing = re.search(r"<sheetData>(.*?)</sheetData>", xml, re.S).group(1)
        merged = new[len("<sheetData>"):-len("</sheetData>")] + existing
        xml = re.sub(r"<sheetData>.*?</sheetData>", f"<sheetData>{merged}</sheetData>",
                     xml, flags=re.S)
    # tableParts is the LAST child of CT_Worksheet (after <drawing/>) - order matters
    xml = xml.replace("</worksheet>",
                      f'<tableParts count="1"><tablePart r:id="{table_rid}"/></tableParts>'
                      "</worksheet>")
    return xml


# Text deliberately chosen NOT to parse as a date: the Status banner keys off
# ISERROR(DATEVALUE(...)) to tell "never refreshed" from "refreshed and stale".
SENTINEL = "NOT REFRESHED"


def sentinel_status_row(header, body):
    """Blank the Status row's timestamps in the SHIPPED prefill.

    Every query target ships with a preview of its CSV so the workbook is readable
    before its first refresh. For the Status tab that preview is actively harmful: it
    would bake the BUILD time into `generated_utc`, so a workbook whose refresh had
    silently failed (data connections declined, a proxy blocking raw.githubusercontent,
    refresh-on-open not honoured) would show its own build date as the last refresh —
    and show GREEN. A staleness banner that reports freshness it cannot verify fails
    OPEN, which is the one behaviour it must never have.

    Replacing the two timestamp columns with a non-date sentinel makes the un-refreshed
    state impossible to mistake for a healthy one. Row COUNT and column count are
    untouched, so the refresh-stability invariant check_consistency asserts still holds.
    """
    if not body:
        return body
    out = [list(r) for r in body]
    for col in ("generated_utc", "coverage_end"):
        if col in header:
            out[0][header.index(col)] = SENTINEL
    return out


def next_rid(rels_xml: str) -> str:
    used = {int(n) for n in re.findall(r'Id="rId(\d+)"', rels_xml)}
    return f"rId{max(used) + 1 if used else 1}"


# ---------------------------------------------------------------------------
# table / queryTable / connection parts
# ---------------------------------------------------------------------------
def table_xml(tid, name, header, nrows):
    ref = f"A1:{col_letter(len(header))}{nrows+1}"
    cols = "".join(
        f'<tableColumn id="{i}" xr3:uid="{guid(name,"col",i)}" uniqueName="{i}" '
        f'name="{esc(h)}" queryTableFieldId="{i}"/>'
        for i, h in enumerate(header, start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<table xmlns="{M}" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'mc:Ignorable="xr xr3" '
        'xmlns:xr="http://schemas.microsoft.com/office/spreadsheetml/2014/revision" '
        'xmlns:xr3="http://schemas.microsoft.com/office/spreadsheetml/2016/revision3" '
        f'id="{tid}" xr:uid="{guid(name,"tbl")}" name="{name}" displayName="{name}" '
        f'ref="{ref}" tableType="queryTable" totalsRowShown="0">'
        f'<autoFilter ref="{ref}" xr:uid="{guid(name,"af")}"/>'
        f'<tableColumns count="{len(header)}">{cols}</tableColumns>'
        '<tableStyleInfo name="TableStyleMedium7" showFirstColumn="0" showLastColumn="0" '
        'showRowStripes="1" showColumnStripes="0"/></table>')


def query_table_xml(name, conn_id, header):
    fields = "".join(
        f'<queryTableField id="{i}" name="{esc(h)}" tableColumnId="{i}"/>'
        for i, h in enumerate(header, start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<queryTable xmlns="{M}" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'mc:Ignorable="xr16" '
        'xmlns:xr16="http://schemas.microsoft.com/office/spreadsheetml/2017/revision16" '
        f'name="ExternalData_1" connectionId="{conn_id}" xr16:uid="{guid(name,"qt")}" '
        'autoFormatId="16" applyNumberFormats="0" applyBorderFormats="0" '
        'applyFontFormats="0" applyPatternFormats="0" applyAlignmentFormats="0" '
        'applyWidthHeightFormats="0">'
        f'<queryTableRefresh nextId="{len(header)+1}">'
        f'<queryTableFields count="{len(header)}">{fields}</queryTableFields>'
        '</queryTableRefresh></queryTable>')


def connection_xml(cid, name):
    return (
        f'<connection id="{cid}" xr16:uid="{guid(name,"conn")}" keepAlive="1" '
        f'name="Query - {name}" '
        f'description="Connection to the &apos;{name}&apos; query in the workbook." '
        'type="5" refreshedVersion="8" refreshOnLoad="1" background="0" saveData="1">'
        '<dbPr connection="Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;'
        f'Location={name};Extended Properties=&quot;&quot;" '
        f'command="SELECT * FROM [{name}]"/></connection>')


# ---------------------------------------------------------------------------
# the M query text
# ---------------------------------------------------------------------------
M_TYPE = {"int": "Int64.Type", "number": "type number",
          "text": "type text", "date_text": "type text"}


def m_section(name, stem, header, kinds):
    types = ", ".join(f'{{"{h}", {M_TYPE[k]}}}' for h, k in zip(header, kinds))
    return (
        f"shared {name} = let\n"
        f'    Source = Csv.Document(Web.Contents("{BASE_URL}{stem}.csv"),'
        f'[Delimiter=",", Columns={len(header)}, Encoding=65001, '
        "QuoteStyle=QuoteStyle.None]),\n"
        '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n'
        '    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers",'
        f"{{{types}}})\n"
        "in\n"
        '    #"Changed Type";\n')


# ---------------------------------------------------------------------------
# DataMashup: decode -> replace Section1.m -> re-encode  ([MS-QDEFF] layout)
# ---------------------------------------------------------------------------
def rewrite_mashup(item1: bytes, new_sections: str) -> bytes:
    text = item1.decode("utf-16" if item1[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf8")
    root = ET.fromstring(text)
    blob = base64.b64decode(root.text)

    off = 0
    version, = struct.unpack_from("<I", blob, off); off += 4
    pkg_len, = struct.unpack_from("<I", blob, off); off += 4
    pkg = blob[off:off + pkg_len]; off += pkg_len
    trailer = blob[off:]                      # permissions + metadata + bindings, verbatim

    zin = zipfile.ZipFile(io.BytesIO(pkg))
    names = zin.namelist()
    if "Formulas/Section1.m" not in names:
        raise SystemExit("DataMashup has no Formulas/Section1.m")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            data = zin.read(n)
            if n == "Formulas/Section1.m":
                m = data.decode("utf8")
                if not m.endswith("\n"):
                    m += "\n"
                data = (m + "\n" + new_sections).encode("utf8")
            zo.writestr(n, data)
    newpkg = buf.getvalue()

    out = struct.pack("<I", version) + struct.pack("<I", len(newpkg)) + newpkg + trailer
    b64 = base64.b64encode(out).decode()
    xml = ('<DataMashup xmlns="http://schemas.microsoft.com/DataMashup" '
           'sqmid="0">' + b64 + "</DataMashup>")
    return ('<?xml version="1.0" encoding="utf-16"?>' + xml).encode("utf-16")


# ---------------------------------------------------------------------------
def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    wb_xml = parts["xl/workbook.xml"].decode()
    wb_rels = parts["xl/_rels/workbook.xml.rels"].decode()

    # sheet name -> worksheet part
    relmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', wb_rels))
    sheets = re.findall(r'<sheet name="([^"]+)" sheetId="\d+" r:id="([^"]+)"/>', wb_xml)
    if not sheets:
        sheets = [(m.group(1), m.group(2)) for m in
                  re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wb_xml)]
    sheet_part = {nm: "xl/" + relmap[rid] for nm, rid in sheets}
    doc_index = {nm: i for i, (nm, _) in enumerate(sheets)}

    # next free ids
    existing_tables = [int(m) for m in
                       re.findall(r"xl/tables/table(\d+)\.xml$", "\n".join(order), re.M)]
    tno = max(existing_tables) + 1
    conn_xml = parts["xl/connections.xml"].decode()
    cid = max(int(m) for m in re.findall(r'<connection id="(\d+)"', conn_xml)) + 1

    new_names, m_sections, new_defined = [], [], []

    for tab, stem in TARGETS:
        header, body, kinds = load_csv(stem)
        if tab == "Status":
            body = sentinel_status_row(header, body)
        spart = sheet_part[tab]
        srels_path = spart.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if srels_path not in parts:          # e.g. the Status sheet: no drawing, no rels yet
            parts[srels_path] = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<Relationships xmlns="{PKGREL}"></Relationships>').encode()
            order.append(srels_path)
        srels = parts[srels_path].decode()
        rid = next_rid(srels)

        # 1. worksheet: data + tableParts
        parts[spart] = patch_sheet(parts[spart].decode(), header, body, kinds,
                                   rid).encode()
        # 2. sheet rels -> table
        parts[srels_path] = srels.replace(
            "</Relationships>",
            f'<Relationship Id="{rid}" Type="{RNS}/table" '
            f'Target="../tables/table{tno}.xml"/></Relationships>').encode()
        # 3. table part + its rels -> queryTable
        parts[f"xl/tables/table{tno}.xml"] = table_xml(tno, stem, header,
                                                       len(body)).encode()
        parts[f"xl/tables/_rels/table{tno}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{PKGREL}">'
            f'<Relationship Id="rId1" Type="{RNS}/queryTable" '
            f'Target="../queryTables/queryTable{tno}.xml"/></Relationships>').encode()
        # 4. queryTable
        parts[f"xl/queryTables/queryTable{tno}.xml"] = query_table_xml(
            stem, cid, header).encode()
        # 5. connection + M + defined name
        new_names.append(connection_xml(cid, stem))
        m_sections.append(m_section(stem, stem, header, kinds))
        ref = f"{tab}!$A$1:${col_letter(len(header))}${len(body)+1}"
        new_defined.append(
            f'<definedName name="ExternalData_1" localSheetId="{doc_index[tab]}" '
            f'hidden="1">{ref}</definedName>')

        order += [f"xl/tables/table{tno}.xml",
                  f"xl/tables/_rels/table{tno}.xml.rels",
                  f"xl/queryTables/queryTable{tno}.xml"]
        print(f"  {tab:18s} table{tno:<3d} queryTable{tno:<3d} conn={cid:<3d} "
              f"{len(header):4d} cols x {len(body):4d} rows")
        tno += 1
        cid += 1

    # ---- connections: append new + set refresh-on-open for ALL ----------------
    conn_xml = conn_xml.replace("</connections>", "".join(new_names) + "</connections>")
    conn_xml = conn_xml.replace(' background="1"', ' refreshOnLoad="1" background="0"')
    parts["xl/connections.xml"] = conn_xml.encode()

    # ---- workbook definedNames ----------------------------------------------
    if "<definedNames>" in wb_xml:
        wb_xml = wb_xml.replace("</definedNames>", "".join(new_defined) + "</definedNames>")
    else:
        wb_xml = wb_xml.replace("<calcPr", "<definedNames>" + "".join(new_defined) +
                                "</definedNames><calcPr")
    parts["xl/workbook.xml"] = wb_xml.encode()

    # ---- DataMashup ----------------------------------------------------------
    parts["customXml/item1.xml"] = rewrite_mashup(parts["customXml/item1.xml"],
                                                  "\n".join(m_sections))

    # ---- content types -------------------------------------------------------
    ct = parts["[Content_Types].xml"].decode()
    adds = ""
    for n in range(tno - len(TARGETS), tno):
        adds += (f'<Override PartName="/xl/tables/table{n}.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>')
        adds += (f'<Override PartName="/xl/queryTables/queryTable{n}.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.spreadsheetml.queryTable+xml"/>')
    parts["[Content_Types].xml"] = ct.replace("</Types>", adds + "</Types>").encode()

    # ---- write ---------------------------------------------------------------
    seen, final = set(), []
    for n in order:
        if n not in seen:
            seen.add(n); final.append(n)
    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in final:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"wrote {WB}  ({len(final)} parts, {cid-1} connections)")


if __name__ == "__main__":
    main()
