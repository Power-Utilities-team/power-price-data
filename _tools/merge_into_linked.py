"""merge_into_linked.py — add a fresh build's NEW content to the UpSlide-linked workbook.

WHY THIS EXISTS. The workbook Power & Utilities send out is linked into PowerPoint with
UpSlide, and UpSlide does not match its links by file path. It stamps a hidden, zero-size
shape named `UpSlideExportSave` into each chart's own userShapes drawing, carrying an export
id and the destination slide. Replace the workbook with a freshly generated one and those
shapes are gone, so every link in the deck is orphaned no matter what the new file is called
or where it sits. There is no relink-by-path dialog, because paths are not the mechanism.

So the delivered file is built by ADDING to the linked workbook rather than by generating a
new one. The linked copy is the template; a fresh build is only a donor of new parts.

WHAT IS NEVER TOUCHED (Fred, 2026-08-26: "don't mess up any of the charts' widths or
heights", and "change as few as possible"):
  * every existing chart part and its rels, bar the two named below
  * every chartUserShapes drawing, which is where the UpSlide markers live
  * every existing anchor, so the five hand-resized charts keep their sizes
  * the theme and styles, so the house palette survives
  * every existing worksheet

WHAT IT ADDS. Sheets present in the donor and not the base, the donor's whole Power Query
section (which brings the new queries and widens the existing ones), and the donor charts
that have no counterpart in the base.

WHAT IT DELIBERATELY DOES NOT DO. It does not hand-widen the eight sheets that gained
columns. They are Power Query outputs and Excel widens them itself on the refresh-on-open
that every connection in this workbook already carries, which is how the monthly roll has
always worked. Hand-editing their extents would risk the very chart references the whole
exercise exists to protect.

MATCHING IS BY EXACT PART IDENTITY, NOT BY SIMILARITY. An earlier attempt aligned charts by
a content signature and paired the base's `chart35` with the donor's `chart44`. They are
different exhibits: the base plots one technology across four fixed year-windows, the donor
plots eight rolling ones driven by the Status sheet. Similarity matching is not safe enough
to drive edits into a linked chart, so a base chart is only ever updated when it is named in
UPDATE below and its axes have been compared by hand.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile

# Base charts that may be updated from the donor, each checked by hand first. Both gained a
# sixth (GB) series and the GB price-basis caveat, and their axes are identical to the
# donor's apart from parenthesis escaping in the number format.
UPDATE = {"xl/charts/chart1.xml": "xl/charts/chart1.xml",
          "xl/charts/chart3.xml": "xl/charts/chart3.xml"}

CT = "[Content_Types].xml"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read(path):
    z = zipfile.ZipFile(path)
    parts = {n: z.read(n) for n in z.namelist()}
    z.close()
    return parts


def sheet_map(parts):
    """{sheet name: (worksheet part, drawing part or None)} in workbook order."""
    wb = parts["xl/workbook.xml"].decode()
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                           parts["xl/_rels/workbook.xml.rels"].decode()))
    out = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        ws = "xl/" + rels[rid].lstrip("/")
        srel = ws.replace("worksheets/", "worksheets/_rels/") + ".rels"
        dr = None
        if srel in parts:
            m = re.search(r'Target="\.\./(drawings/drawing\d+\.xml)"', parts[srel].decode())
            if m:
                dr = "xl/" + m.group(1)
        out[name] = (ws, dr)
    return out


def chart_parts(parts):
    return sorted((n for n in parts if re.match(r"xl/charts/chart\d+\.xml$", n)),
                  key=lambda n: int(re.search(r"(\d+)", n).group(1)))


def anchored_charts(parts, drawing):
    """[(anchor xml, chart part)] in document order for one sheet drawing."""
    d = parts[drawing].decode()
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                           parts[drawing.replace("drawings/", "drawings/_rels/") + ".rels"].decode()))
    out = []
    for m in re.finditer(r"<xdr:(oneCellAnchor|twoCellAnchor|absoluteAnchor)\b.*?</xdr:\1>", d, re.S):
        rid = re.search(r'r:id="(rId\d+)"', m.group(0))
        if not rid:
            continue
        t = rels.get(rid.group(1), "")
        if "charts/chart" in t:
            out.append((m.group(0), "xl/" + t.replace("../", "")))
    return out


def next_free(parts, pattern):
    hi = 0
    for n in parts:
        m = re.match(pattern, n)
        if m:
            hi = max(hi, int(m.group(1)))
    return hi + 1


def theme_accents(parts):
    t = parts["xl/theme/theme1.xml"].decode()
    scheme = t.split("<a:clrScheme")[1].split("</a:clrScheme>")[0]
    out = {}
    for m in re.finditer(r'<a:(accent\d)>\s*<a:srgbClr val="([0-9A-Fa-f]{6})"', scheme):
        out[m.group(1)] = m.group(2)
    return out


# The hydro band charts were the only ones in this workbook that took their colours from
# the theme, which is why they needed resolving here at all. chart_templates/hydro_band.xml
# now states them explicitly and check_house_palette.py keeps it that way, so this mapping
# is a fallback for a donor built before that fix. It deliberately MATCHES the template
# rather than resolving against whatever theme the base happens to carry: resolving against
# the base put the current year's line on ACBFB7, the same colour as the band it sits inside.
HYDRO_LINE_COLOURS = {"accent2": "CC9F53",   # oldest complete year   GOLD
                      "accent6": "3D664A",   #                        FOREST
                      "accent5": "5FA1AD",   #                        TEAL
                      "accent4": "8A1E41",   #                        WINE
                      "accent3": "2E3E80"}   # the current year       NAVY


def resolve_accents(xml: str, accents: dict) -> str:
    """Turn any theme-colour reference into the explicit house colour it should be."""
    def sub(m):
        slot = m.group(1)
        return (f'<a:srgbClr val="{HYDRO_LINE_COLOURS[slot]}"'
                if slot in HYDRO_LINE_COLOURS else m.group(0))
    return re.sub(r'<a:schemeClr val="(accent\d)"', sub, xml)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="the UpSlide-linked workbook")
    ap.add_argument("--donor", required=True, help="a fresh build to take new content from")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip", default="", help="comma list of stages to omit: "
                    "update,queries,sheets,charts,calcchain")
    ap.add_argument("--chart-size", default=None,
                    help="cx,cy in EMU for added charts; default is the base's commonest")
    a = ap.parse_args()

    base, donor = read(a.base), read(a.donor)
    skip = {x.strip() for x in a.skip.split(',') if x.strip()}
    report = []

    # ---- 1. which donor charts are new -------------------------------------------------
    bs, ds = sheet_map(base), sheet_map(donor)
    base_by_sheet, donor_by_sheet = {}, {}
    for name, (_, dr) in bs.items():
        if dr:
            base_by_sheet[name] = anchored_charts(base, dr)
    for name, (_, dr) in ds.items():
        if dr:
            donor_by_sheet[name] = anchored_charts(donor, dr)

    # A donor chart is NEW when its sheet has more charts than the base's copy of that sheet.
    # Position, not similarity: the generator appends, and appending is the only way this
    # project is allowed to add anything (see check_reference_stability).
    new_charts = []          # (sheet, anchor xml, donor chart part)
    for name, dl in donor_by_sheet.items():
        keep = len(base_by_sheet.get(name, []))
        for anchor, part in dl[keep:]:
            new_charts.append((name, anchor, part))
    report.append(f"new charts to add: {len(new_charts)}"
                  + (f" (all on {sorted({s for s, _, _ in new_charts})})" if new_charts else ""))

    # ---- 2. update the hand-checked charts ---------------------------------------------
    for bp, dp in ({} if 'update' in skip else UPDATE).items():
        if bp not in base or dp not in donor:
            report.append(f"  SKIP update {bp}: not in both files")
            continue
        old = base[bp].decode()
        don = donor[dp].decode()
        # ADDITIVE ONLY. Taking the donor's chart wholesale would also import its axis XML,
        # and Fred's instruction on 2026-08-26 was to change as few axes as possible and to
        # cut no data off. The two files' axes already agree apart from parenthesis escaping
        # in the number format, so importing them would be a diff for no gain. Instead the
        # base chart keeps every one of its own elements and gains exactly two things: the
        # series it is missing, and the caveat title.
        def sers(x):
            return {(re.search(r"<c:val>.*?<c:f>([^<]+)</c:f>", m, re.S) or [None, m])[1]: m
                    for m in re.findall(r"<c:ser>.*?</c:ser>", x, re.S)}
        have, want = sers(old), sers(don)
        extra = [m for k, m in want.items() if k not in have]
        if extra:
            last = list(re.finditer(r"<c:ser>.*?</c:ser>", old, re.S))[-1]
            old = old[:last.end()] + "".join(extra) + old[last.end():]
        title = re.search(r"<c:title>.*?</c:title>", don.split("<c:plotArea>")[0], re.S)
        added_title = False
        if title and "<c:title>" not in old.split("<c:plotArea>")[0]:
            old = old.replace("<c:chart>", "<c:chart>" + title.group(0), 1)
            old = re.sub(r'<c:autoTitleDeleted val="1"/>',
                         '<c:autoTitleDeleted val="0"/>', old, count=1)
            added_title = True
        base[bp] = old.encode()
        report.append(f"  {os.path.basename(bp)}: +{len(extra)} series"
                      + (", + caveat title" if added_title else "")
                      + ", axes and every other element left as they were")

    # ---- 3. the query section, which brings the new queries and widens the old ones -----
    if "customXml/item1.xml" in donor and "queries" not in skip:
        base["customXml/item1.xml"] = donor["customXml/item1.xml"]
        report.append("query code replaced with the donor's (all queries)")

    # ---- 3b. sheets the base does not have ----------------------------------------------
    # THE WHOLE CHAIN, OR NONE OF IT. A Power Query load target is five parts, not one:
    #
    #     worksheet  -rels->  table  -rels->  queryTable  -connectionId->  connection
    #
    # The first version of this copied the worksheet and the table and stopped. Every static
    # check passed - relationships resolved, ids were unique, every part parsed - because
    # nothing was dangling: the table simply declared `tableType="queryTable"` with a
    # queryTableFieldId on all 18 columns and no queryTable behind it. Excel answered with
    # "we found a problem with some content", which is the prompt whose Yes button strips
    # Power Query out of this workbook. Found by bisection on 2026-08-26: an empty sheet was
    # accepted, the donor's sheet data was accepted, and adding the table was what broke it.
    added_sheets = [] if 'sheets' in skip else [n for n in ds if n not in bs]
    if added_sheets:
        wb = base["xl/workbook.xml"].decode()
        wrel = base["xl/_rels/workbook.xml.rels"].decode()
        conns = base["xl/connections.xml"].decode()
        new_ct = []
        n_ws = next_free(base, r"xl/worksheets/sheet(\d+)\.xml$")
        n_tbl = next_free(base, r"xl/tables/table(\d+)\.xml$")
        n_qt = next_free(base, r"xl/queryTables/queryTable(\d+)\.xml$")
        n_rid = max(int(x) for x in re.findall(r'Id="rId(\d+)"', wrel))
        n_sid = max(int(x) for x in re.findall(r'sheetId="(\d+)"', wb))
        n_cid = max(int(x) for x in re.findall(r'<connection id="(\d+)"', conns))
        n_tid = max([int(x) for x in re.findall(r'<table [^>]*\bid="(\d+)"',
                     "".join(base[n].decode() for n in base if n.startswith("xl/tables/")))] or [0])
        n_idx = len(re.findall(r"<sheet ", wb))

        # Connections first, so a queryTable can be pointed at the id it will actually have.
        dconn = donor["xl/connections.xml"].decode()
        have = set(re.findall(r'<connection[^>]*\bname="([^"]+)"', conns))
        cid_map = {}                       # donor connection id -> id in the merged workbook
        for m in re.finditer(r"<connection\b.*?</connection>", dconn, re.S):
            blk = m.group(0)
            nm = re.search(r'\bname="([^"]+)"', blk).group(1)
            old_id = re.search(r'<connection id="(\d+)"', blk).group(1)
            if nm in have:
                continue
            n_cid += 1
            cid_map[old_id] = n_cid
            conns = conns.replace("</connections>",
                re.sub(r'(<connection id=")\d+(")', rf'\g<1>{n_cid}\g<2>', blk, count=1)
                + "</connections>")
            report.append(f"  added connection {nm!r} as id {n_cid}")

        def ct_override(part, kind):
            new_ct.append(f'<Override PartName="/{part}" ContentType="application/vnd.'
                          f'openxmlformats-officedocument.spreadsheetml.{kind}+xml"/>')

        for name in added_sheets:
            dws, _ = ds[name]
            drel = dws.replace("worksheets/", "worksheets/_rels/") + ".rels"
            ws_new = f"xl/worksheets/sheet{n_ws}.xml"
            base[ws_new] = donor[dws]
            ct_override(ws_new, "worksheet")
            rel_xml = donor[drel].decode() if drel in donor else (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
                'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
            for tgt in re.findall(r'Target="\.\./(tables/table\d+\.xml)"', rel_xml):
                src_tbl = "xl/" + tgt
                dst_tbl = f"xl/tables/table{n_tbl}.xml"
                n_tid += 1
                base[dst_tbl] = re.sub(r'(<table [^>]*\bid=")\d+(")', rf'\g<1>{n_tid}\g<2>',
                                       donor[src_tbl].decode(), count=1).encode()
                ct_override(dst_tbl, "table")
                # the table's OWN rels, and the queryTable they point at
                src_trel = src_tbl.replace("tables/", "tables/_rels/") + ".rels"
                if src_trel in donor:
                    trel = donor[src_trel].decode()
                    for qt in re.findall(r'Target="\.\./(queryTables/queryTable\d+\.xml)"', trel):
                        src_qt = "xl/" + qt
                        dst_qt = f"xl/queryTables/queryTable{n_qt}.xml"
                        qx = donor[src_qt].decode()
                        old_cid = re.search(r'connectionId="(\d+)"', qx)
                        if old_cid and old_cid.group(1) in cid_map:
                            qx = re.sub(r'(connectionId=")\d+(")',
                                        rf'\g<1>{cid_map[old_cid.group(1)]}\g<2>', qx, count=1)
                        base[dst_qt] = qx.encode()
                        ct_override(dst_qt, "queryTable")
                        trel = trel.replace(f'Target="../{qt}"',
                                            f'Target="../queryTables/queryTable{n_qt}.xml"')
                        n_qt += 1
                    base[dst_tbl.replace("tables/", "tables/_rels/") + ".rels"] = trel.encode()
                rel_xml = rel_xml.replace(f'Target="../{tgt}"',
                                          f'Target="../tables/table{n_tbl}.xml"')
                n_tbl += 1
            base[ws_new.replace("worksheets/", "worksheets/_rels/") + ".rels"] = rel_xml.encode()
            n_rid += 1
            n_sid += 1
            wrel = wrel.replace("</Relationships>",
                f'<Relationship Id="rId{n_rid}" Type="{NS_R}/worksheet" '
                f'Target="worksheets/sheet{n_ws}.xml"/></Relationships>')
            wb = wb.replace("</sheets>",
                            f'<sheet name="{name}" sheetId="{n_sid}" r:id="rId{n_rid}"/></sheets>')
            dn = re.search(rf"<definedName[^>]*>{re.escape(name)}!\$[^<]*</definedName>",
                           donor["xl/workbook.xml"].decode())
            if dn:
                entry = re.sub(r'localSheetId="\d+"', f'localSheetId="{n_idx}"', dn.group(0))
                wb = (wb.replace("</definedNames>", entry + "</definedNames>")
                      if "<definedNames>" in wb else
                      wb.replace("<calcPr", f"<definedNames>{entry}</definedNames><calcPr"))
            n_idx += 1
            n_ws += 1

        base["xl/workbook.xml"] = wb.encode()
        base["xl/_rels/workbook.xml.rels"] = wrel.encode()
        base["xl/connections.xml"] = conns.encode()
        base[CT] = base[CT].decode().replace("</Types>", "".join(new_ct) + "</Types>").encode()
        report.append(f"added sheets: {', '.join(added_sheets)}"
                      f" (worksheet + table + queryTable + connection for each)")

    # ---- 4. add the new charts ----------------------------------------------------------
    if new_charts and 'charts' not in skip:
        accents = theme_accents(base)
        # the size the base actually standardises on
        import collections
        sizes = collections.Counter()
        for lst in base_by_sheet.values():
            for anchor, _ in lst:
                m = re.search(r'<xdr:ext cx="(\d+)" cy="(\d+)"', anchor)
                if m:
                    sizes[(m.group(1), m.group(2))] += 1
        cx, cy = a.chart_size.split(",") if a.chart_size else sizes.most_common(1)[0][0]
        report.append(f"added charts sized {cx} x {cy} "
                      f"(used by {sizes[(cx, cy)]} of {sum(sizes.values())} existing charts)")

        n_chart = next_free(base, r"xl/charts/chart(\d+)\.xml$")
        by_sheet = {}
        for sheet, anchor, part in new_charts:
            by_sheet.setdefault(sheet, []).append((anchor, part))

        for sheet, items in by_sheet.items():
            drawing = bs[sheet][1]
            drel = drawing.replace("drawings/", "drawings/_rels/") + ".rels"
            d_xml = base[drawing].decode()
            r_xml = base[drel].decode()
            existing = anchored_charts(base, drawing)
            rows = [int(x) for anc, _ in existing
                    for x in re.findall(r"<xdr:row>(\d+)</xdr:row>", anc)]
            step = 0
            if len(rows) > 1:
                step = max(1, round((max(rows) - min(rows)) / (len(rows) - 1)))
            row = max(rows) if rows else 0
            n_rid = max([int(x) for x in re.findall(r'Id="rId(\d+)"', r_xml)] or [0])
            n_shape = max([int(x) for x in re.findall(r'<xdr:cNvPr id="(\d+)"', d_xml)] or [0])
            # The NAME is numbered separately from the id: this drawing has id 57 carrying
            # "Chart 65". Deriving the name from the id put "Chart 58" through "Chart 65" on
            # top of names already in the drawing, and duplicate shape names are one of the
            # things Excel offers to "recover" a workbook over.
            n_name = max([int(x) for x in
                          re.findall(r'<xdr:cNvPr id="\d+" name="Chart (\d+)"', d_xml)] or [0])

            add_anchor, add_rel, add_ct = [], [], []
            for anchor, part in items:
                cname = f"xl/charts/chart{n_chart}.xml"
                xml = donor[part].decode()
                xml = resolve_accents(xml, accents)
                # a donor chart may carry its own userShapes; it has no marker, drop the ref
                xml = re.sub(r"<c:userShapes[^>]*/>", "", xml)
                base[cname] = xml.encode()
                add_ct.append(f'<Override PartName="/{cname}" ContentType="application/vnd.'
                              f'openxmlformats-officedocument.drawingml.chart+xml"/>')
                n_rid += 1
                n_shape += 1
                n_name += 1
                row += step or 11
                add_rel.append(f'<Relationship Id="rId{n_rid}" Type="{NS_R}/chart" '
                               f'Target="../charts/chart{n_chart}.xml"/>')
                anc = (f'<xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>'
                       f'<xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                       f'<xdr:ext cx="{cx}" cy="{cy}"/>'
                       f'<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
                       f'<xdr:cNvPr id="{n_shape}" name="Chart {n_name}"/>'
                       f'<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>'
                       f'<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
                       f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
                       f'drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.'
                       f'org/drawingml/2006/chart" xmlns:r="{NS_R}" r:id="rId{n_rid}"/>'
                       f'</a:graphicData></a:graphic></xdr:graphicFrame>'
                       f'<xdr:clientData/></xdr:oneCellAnchor>')
                add_anchor.append(anc)
                n_chart += 1
            base[drawing] = d_xml.replace("</xdr:wsDr>", "".join(add_anchor) + "</xdr:wsDr>").encode()
            base[drel] = r_xml.replace("</Relationships>",
                                       "".join(add_rel) + "</Relationships>").encode()
            ct = base[CT].decode()
            base[CT] = ct.replace("</Types>", "".join(add_ct) + "</Types>").encode()
            report.append(f"  {sheet}: appended {len(items)} chart(s) below row {max(rows)}")

    # ---- 4b. drop the calculation chain and force a recalculation -----------------------
    # calcChain.xml caches the order Excel last evaluated formulas in. It is an optimisation
    # and Excel rebuilds it from nothing, but a stale one after hand-edited XML is a known
    # cause of the "we found a problem with some content" recovery prompt, and accepting that
    # prompt is what strips Power Query out of this workbook. Removing it costs one slower
    # first open. fullCalcOnLoad makes Excel evaluate everything on that open rather than
    # trusting cached results that predate the new sheets.
    for dead in ([] if "calcchain" in skip else
                 [n for n in list(base) if n.endswith("calcChain.xml")]):
        del base[dead]
        base[CT] = re.sub(rf'<Override PartName="/{re.escape(dead)}"[^>]*/>', "",
                          base[CT].decode()).encode()
        wr = base["xl/_rels/workbook.xml.rels"].decode()
        base["xl/_rels/workbook.xml.rels"] = re.sub(
            r'<Relationship[^>]*Target="calcChain\.xml"[^>]*/>', "", wr).encode()
        report.append(f"removed {dead}; Excel rebuilds it on open")
    wb = base["xl/workbook.xml"].decode()
    if "<calcPr" in wb:
        wb = re.sub(r"<calcPr\b([^/>]*)/>", r'<calcPr\1 fullCalcOnLoad="1"/>', wb, count=1)
        if 'fullCalcOnLoad' not in wb:
            wb = re.sub(r"(<calcPr\b[^>]*)>", r'\1 fullCalcOnLoad="1">', wb, count=1)
    else:
        wb = wb.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
    base["xl/workbook.xml"] = wb.encode()
    report.append("set fullCalcOnLoad so the first open recalculates everything")

    # ---- 5. write ------------------------------------------------------------------------
    orig = read(a.base)
    order = [n for n in orig if n in base] + [n for n in base if n not in orig]
    # EVERY PART MUST PARSE BEFORE ANYTHING IS WRITTEN. The first build of this tool
    # appended content-type overrides AFTER </Types>, and Excel refused the file outright
    # with "the file format or file extension is not valid". Every semantic check passed:
    # markers intact, anchors untouched, relationships resolving. None of them opened the
    # XML. A malformed package is the one failure that costs the whole exercise, because
    # the recovery prompt it leads to is what strips Power Query out of this workbook.
    import xml.etree.ElementTree as ET
    broken = []
    for n, blob in base.items():
        if n.endswith(".xml") or n.endswith(".rels"):
            try:
                ET.fromstring(blob)
            except Exception as ex:                       # noqa: BLE001
                broken.append(f"{n}: {ex}")
    if broken:
        print("REFUSING TO WRITE - the package would not open:", file=sys.stderr)
        for b in broken:
            print("  x", b, file=sys.stderr)
        return 1
    report.append(f"every one of the {len(base)} parts parses as XML")

    tmp = a.out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            z.writestr(n, base[n])
    shutil.move(tmp, a.out)
    print("\n".join(report))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    sys.exit(main() or 0)
