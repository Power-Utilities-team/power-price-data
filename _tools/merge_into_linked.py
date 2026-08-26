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

IT ALSO WIDENS THE SHEETS THAT GAINED COLUMNS, which the first version did not, and that
omission is what shipped broken on 2026-08-26. The reasoning then was that these sheets are
Power Query outputs and Excel widens them itself on the refresh-on-open every connection
here carries. It is true of most of them and false of the one that mattered: `CaptureVsBase`
has no connection and no load range, it is 30,420 formulas over CaptureMonthly and
A_MonthPrice, and nothing refreshes it ever. It shipped 126 columns short and the seven new
capture charts drew nothing. See widen_sheets.py, which appends rather than merging in place
precisely so the 30 already-linked charts on that sheet keep pointing at what they pointed
at before.

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

import chart_layout
import widen_sheets

# Base charts that may be updated from the donor, each checked by hand first. Both gained a
# sixth (GB) series and the GB price-basis caveat, and their axes are identical to the
# donor's apart from parenthesis escaping in the number format.
UPDATE = {"xl/charts/chart1.xml": "xl/charts/chart1.xml",
          "xl/charts/chart3.xml": "xl/charts/chart3.xml"}

# The Italian capture chart that plots hydro. Named by part, not found by similarity, for
# the reason UPDATE gives above: this workbook has charts that look alike and are not.
IT_HYDRO_CHART = "xl/charts/chart50.xml"

# Its caption has to move with its data, or the sheet labels the exhibit as the series it no
# longer plots. Matched on the full existing text so it cannot catch France's or Portugal's.
CAPTION_RENAMES = {
    "Italy — Hydro run-of-river: capture as % of base price, by month (one line per year)":
    "Italy — Hydro reservoir: capture as % of base price, by month (one line per year)",
}

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


def _table_of(parts, ws_path):
    """The table part a worksheet loads its query into, or None if it has no table."""
    rel = ws_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
    if rel not in parts:
        return None
    m = re.search(r'Target="\.\./(tables/table\d+\.xml)"', parts[rel].decode())
    return "xl/" + m.group(1) if m else None


def _querytable_of(parts, table_path):
    """The queryTable behind a table, or None."""
    rel = table_path.replace("tables/", "tables/_rels/") + ".rels"
    if rel not in parts:
        return None
    m = re.search(r'Target="\.\./(queryTables/queryTable\d+\.xml)"', parts[rel].decode())
    return "xl/" + m.group(1) if m else None


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
    ap.add_argument("--out", required=False,
                    help="not needed with --dry-run")
    ap.add_argument("--dry-run", action="store_true",
                    help="report whether the template is behind the donor, and change "
                         "nothing. Exit 1 if a rebuild is due, 0 if it is not.")
    ap.add_argument("--skip", default="", help="comma list of stages to omit: "
                    "update,queries,sheets,charts,calcchain")
    ap.add_argument("--widen-only", default="", help="comma list of sheets to widen, for "
                    "bisecting which one Excel objects to; default is all of them")
    ap.add_argument("--target-cm", default=None, metavar="W,H",
                    help="the size a chart should be in POWERPOINT, in cm; default 12,5.4. "
                         "The Excel size is worked back through --export-scale.")
    ap.add_argument("--target-pct-cm", default=None, metavar="W,H",
                    help="the same for the capture-as-a-%%-of-base charts; default 5.8,3.99")
    ap.add_argument("--export-scale", type=float, default=None,
                    help="the fraction of its Excel size at which UpSlide exports a chart; "
                         "default 0.70535, measured from the deck. Change this if a refreshed "
                         "picture comes out uniformly the wrong size.")
    ap.add_argument("--no-tables", action="store_true",
                    help="widen the cells but leave every table declaration alone")
    ap.add_argument("--chart-size", default=None,
                    help="cx,cy in EMU for added charts; default is the base's commonest")
    a = ap.parse_args()

    if not a.out and not a.dry_run:
        ap.error("--out is required unless --dry-run is given")
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

    # A donor chart is NEW when the base has no chart CAPTIONED THE SAME WAY.
    #
    # This used to be decided by position, on the reasoning that the generator appends. That
    # reasoning was wrong and it shipped on 2026-08-26. The newer build inserts Germany's
    # hydro reservoir chart into the middle of the capture block, which shifts every chart
    # after it by one, so slicing off the last 22 took a SECOND COPY of "Italy - Biomass" and
    # left out Germany's and Italy's hydro reservoir charts entirely.
    #
    # Matching on the caption is not the similarity matching this file warns about elsewhere.
    # It is exact text, written by the generator from the country and the technology, and it
    # is the same string in both files or it is not.
    new_charts = []          # (sheet, anchor xml, donor chart part)
    for name, dl in donor_by_sheet.items():
        have = {v for v, _ in chart_layout.read_captions(base, bs, name).values()} \
            if name in bs and bs[name][1] else set()
        have |= set(CAPTION_RENAMES.values())    # produced by relabelling a chart we keep
        dcaps = chart_layout.captions_by_chart(donor, ds, name)
        if not have or not dcaps:
            keep = len(base_by_sheet.get(name, []))
            new_charts += [(name, a, p) for a, p in dl[keep:]]
            continue
        for anchor, part in dl:
            cap = dcaps.get(part)
            if cap and cap not in have:
                new_charts.append((name, anchor, part))
    report.append(f"new charts to add: {len(new_charts)}"
                  + (f" (all on {sorted({s for s, _, _ in new_charts})})" if new_charts else ""))

    # ---- 1b. is a rebuild due at all? ---------------------------------------------------
    # THE NUMBERS DO NOT NEED ONE. Every query in this workbook refreshes on open, so a
    # month of fresh data reaches the linked copy without anything being rebuilt. Only a
    # change of SHAPE does: a new sheet, a new chart, a column that moved. Fred's call,
    # 2026-08-26, and this is what makes it checkable rather than something to remember.
    if a.dry_run:
        sheets_due = [n for n in ds if n not in bs]
        charts_due = len(new_charts)
        # NOT a byte comparison. The updates this tool applies are surgical - the base
        # chart keeps all its own elements and gains a series and a title - so an updated
        # chart is deliberately not byte-equal to the donor's version of it. Comparing
        # bytes reported a rebuild as due the moment one had just been done. What is
        # actually behind is a chart with fewer series than the donor's, or missing the
        # caveat the donor carries.
        def _shape(x):
            head = x.split("<c:plotArea>")[0]
            m = re.search(r"<c:title>.*?</c:title>", head, re.S)
            return (len(re.findall(r"<c:ser>", x)),
                    " ".join(re.findall(r"<a:t>([^<]*)</a:t>", m.group(0))) if m else "")
        updates_due = []
        for b, d in UPDATE.items():
            if b not in base or d not in donor:
                continue
            bn, bt = _shape(base[b].decode())
            dn, dt = _shape(donor[d].decode())
            if bn < dn or (dt and dt != bt):
                updates_due.append(os.path.basename(b))
        # A column the build added and the template has not got is the fault that shipped on
        # 2026-08-26, and the first version of this check could not see it: it asked only
        # about whole sheets and whole charts, so a template 126 columns short reported UP
        # TO DATE.
        b_sst, d_sst = widen_sheets.shared_strings(base), widen_sheets.shared_strings(donor)
        cols_due = []
        for n in bs:
            if n not in ds:
                continue
            bh = set(widen_sheets.headers(base[bs[n][0]].decode(), b_sst).values())
            dh = set(widen_sheets.headers(donor[ds[n][0]].decode(), d_sst).values())
            if dh - bh:
                cols_due.append(f"{n} (+{len(dh - bh)})")

        due = bool(sheets_due or charts_due or updates_due or cols_due)
        print(f"template : {a.base}")
        print(f"donor    : {a.donor}")
        print(f"  new sheets : {', '.join(sheets_due) if sheets_due else 'none'}")
        print(f"  new charts : {charts_due}")
        print(f"  sheets missing columns the build produces : "
              f"{', '.join(cols_due) if cols_due else 'none'}")
        print(f"  charts whose content moved on : "
              f"{', '.join(updates_due) if updates_due else 'none'}")
        print("\nREBUILD DUE" if due else
              "\nUP TO DATE - the linked workbook only needs its numbers, which it "
              "refreshes on open")
        return 1 if due else 0

    # ---- 1c. widen the sheets whose build gained columns --------------------------------
    # Appends only, so nothing an existing chart points at can move. The returned maps say
    # where each of the donor's columns ended up, and every piece of donor XML that follows
    # is rewritten through them.
    maps = {}
    if "widen" not in skip:
        only = {x.strip() for x in a.widen_only.split(',') if x.strip()}
        maps, problems, widened = widen_sheets.widen(base, donor, bs, ds, report,
                                                     only=only or None)
        if problems:
            print("REFUSING TO WRITE - a sheet could not be widened safely:", file=sys.stderr)
            for p in problems:
                print("  x", p, file=sys.stderr)
            return 1
        # A donor formula that says `Status!O$2` is translated through Status's own map, so a
        # column that moved is handled rather than fatal. What is NOT recoverable is a
        # formula reaching a sheet this tool has no map for, because then there is nothing to
        # translate through and the reference silently keeps a meaning it no longer has.
        touched = [bs[n][0] for n in widened if n in bs]
        reached = widen_sheets.formula_sheets(base, touched)
        unknown = sorted(s for s in reached
                         if s in bs and s not in maps and s not in ds)
        if unknown:
            print("REFUSING TO WRITE - a formula reaches a sheet with no column map:",
                  file=sys.stderr)
            for m in unknown:
                print("  x", m, file=sys.stderr)
            return 1
        remapped = {s: n for s, n in ((s, sum(1 for k, v in maps[s].items() if k != v))
                                      for s in reached if s in maps) if n}
        if remapped:
            report.append("  formulas rewritten for columns that moved: "
                          + ", ".join(f"{s} ({n})" for s, n in sorted(remapped.items())))
        if maps:
            report.append(f"column maps built for {len(maps)} sheet(s); every formula and "
                          f"every donor chart reference translated through them")
        # A widened sheet that loads from a query keeps a table and a queryTable declaring
        # how wide it is. Left stale they disagree with the cells beside them until the next
        # refresh rewrites both. The donor's own declarations are exactly right wherever the
        # merged order matched the donor's, which is every sheet that grew by appending.
        for name in ([] if a.no_tables else widened):
            cmap = maps.get(name, {})
            if any(k != v for k, v in cmap.items()):
                continue                      # not the donor's order; its table would lie
            bt, dt = _table_of(base, bs[name][0]), _table_of(donor, ds[name][0])
            if not bt or not dt:
                continue
            bx, dx = base[bt].decode(), donor[dt].decode()
            # re.search, not re.match: these parts open with an XML declaration, and matching
            # from position 0 silently found nothing at all.
            head = re.search(r"<table\b[^>]*>", bx)
            dhead = re.search(r"<table\b[^>]*>", dx)
            dref = re.search(r'\bref="([^"]+)"', dhead.group(0)) if dhead else None
            if not head or not dref:
                continue
            new_head = re.sub(r'\bref="[^"]*"', f'ref="{dref.group(1)}"', head.group(0))
            base[bt] = (bx[:head.start()] + new_head + dx[dhead.end():]).encode()
            bq, dq = _querytable_of(base, bt), _querytable_of(donor, dt)
            if bq and dq:
                qb, qd = base[bq].decode(), donor[dq].decode()
                keep = re.search(r"<queryTable\b[^>]*>", qb)
                drop = re.search(r"<queryTable\b[^>]*>", qd)
                if keep and drop:
                    base[bq] = (qb[:keep.end()] + qd[drop.end():]).encode()
            # AND THE LOAD RANGE HAS TO AGREE WITH THEM. Power Query marks where it loads
            # with a hidden `ExternalData_1` defined name. Widening the table without it
            # leaves the two saying different things about the same range, and Excel answers
            # with the recovery prompt whose Yes button strips Power Query out of this file.
            wbx = base["xl/workbook.xml"].decode()
            absref = re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", dref.group(1))
            new_wbx = re.sub(
                rf"(<definedName[^>]*>){re.escape(name)}!\$[A-Z]+\$\d+:\$[A-Z]+\$\d+(</definedName>)",
                rf"\g<1>{name}!{absref}\g<2>", wbx, count=1)
            base["xl/workbook.xml"] = new_wbx.encode()
            report.append(f"  {name}: table, queryTable and load range now declare "
                          f"{dref.group(1)}")

    # ---- 2. update the hand-checked charts ---------------------------------------------
    for bp, dp in ({} if 'update' in skip else UPDATE).items():
        if bp not in base or dp not in donor:
            report.append(f"  SKIP update {bp}: not in both files")
            continue
        old = base[bp].decode()
        don = widen_sheets.remap_refs(donor[dp].decode(), maps)
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
            # Its own cells stay where the donor put them, but a formula reaching ANOTHER
            # sheet has to be translated: the columns it names may sit somewhere else here.
            base[ws_new] = widen_sheets.remap_refs(donor[dws].decode(), maps).encode()
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
    made = {}
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
                xml = widen_sheets.remap_refs(donor[part].decode(), maps)
                xml = resolve_accents(xml, accents)
                # a donor chart may carry its own userShapes; it has no marker, drop the ref
                xml = re.sub(r"<c:userShapes[^>]*/>", "", xml)
                base[cname] = xml.encode()
                made[cname] = part
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
    # ONLY IF IT IS NOT ALREADY THERE. Adding it unconditionally made a second pass over an
    # already-built file produce `<calcPr ... fullCalcOnLoad="1" fullCalcOnLoad="1"/>`, a
    # duplicate attribute, which is not well-formed XML at all. Every rebuild after the first
    # runs over a template this tool has already touched, so idempotence is the normal case
    # rather than an edge one.
    wb = base["xl/workbook.xml"].decode()
    if 'fullCalcOnLoad' in wb:
        report.append("fullCalcOnLoad already set; left as it was")
    elif "<calcPr" in wb:
        wb = re.sub(r"<calcPr\b([^/>]*)/>", r'<calcPr\1 fullCalcOnLoad="1"/>', wb, count=1)
        if 'fullCalcOnLoad' not in wb:
            wb = re.sub(r"(<calcPr\b[^>]*)>", r'\1 fullCalcOnLoad="1">', wb, count=1)
        report.append("set fullCalcOnLoad so the first open recalculates everything")
    else:
        wb = wb.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
        report.append("set fullCalcOnLoad so the first open recalculates everything")
    base["xl/workbook.xml"] = wb.encode()

    # ---- 4b2. Italy's hydro exhibit moves to reservoir -----------------------------------
    # Fred, 2026-08-26. Italy plotted run-of-river and nothing plotted Italian reservoir, so
    # this is a straight swap. He looked at Portugal in the same breath and left it alone,
    # because Portugal already carries BOTH: swapping its run-of-river chart would have shown
    # the reservoir series twice.
    if "hydro" not in skip:
        chart_layout.repoint(base, bs, IT_HYDRO_CHART,
                             "IT_Hydro run-of-river", "IT_Hydro reservoir", report)

    # ---- 4b3. size the charts for what UpSlide exports -----------------------------------
    if "sizes" not in skip:
        # A chart REFLOWS rather than scales, so halving its width leaves 9pt labels in half
        # the room. Rendered, the capture charts came back with their y-axis labels collapsed
        # into an illegible smear and the legend sitting on top of them. Bringing the type
        # down by the same factor the chart came down by is what keeps them looking like the
        # ones already in the deck (Fred, 2026-08-26: "without anything looking squashed,
        # stretched, or weird in any other way").
        cm = lambda v: tuple(float(x) for x in v.split(",")) if v else None
        if "unpin" not in skip:
            chart_layout.unpin_plot_area(base, bs, report)
        factors = chart_layout.resize(base, bs, report, target=cm(a.target_cm),
                                      target_pct=cm(a.target_pct_cm), scale=a.export_scale)
        chart_layout.scale_fonts(base, factors, report)

    # ---- 4b4. lay the Charts contact sheet out again -------------------------------------
    # Every chart on that sheet has a caption in the cell above it, and nothing kept the two
    # in step: four charts already sat on top of the next band's caption before any of this
    # work, the resize loosened every band, and the 22 charts appended on a fixed 10-row step
    # overlapped one another because a 7.66 cm chart is 14.5 rows tall. Reflowing from the
    # chart sizes themselves is the version that cannot drift.
    if "layout" not in skip:
        extra = {}
        if made:
            donor_caps = chart_layout.captions_by_chart(donor, ds)
            extra = {new: donor_caps.get(src, "") for new, src in made.items()}
        chart_layout.reflow(base, bs, extra, report, renames=CAPTION_RENAMES)

    # ---- 4c. make every query refresh when the file is opened ---------------------------
    # THE LINKED COPY HAD LOST THIS AND NOBODY KNEW. All 22 of its connections were missing
    # `refreshOnLoad`, so the numbers only moved when somebody remembered to press Refresh
    # All, while the generator sets it on all 24 and the Status tab tells the reader the data
    # was "pulled when you opened this file". It also quietly undermined the rebuild rule,
    # which is only safe if a month of fresh data reaches the linked copy on its own.
    # Fred chose to turn it on across all 24 (2026-08-26), which restores what the build
    # intends rather than preserving an accident.
    if "refresh" not in skip:
        conns = base["xl/connections.xml"].decode()
        before = len(re.findall(r'<connection\b[^>]*\brefreshOnLoad="1"', conns))
        # Appended, not prepended. Putting it first pushes `id=` out of the `<connection id=`
        # position that this tool and its checks both read connections by.
        conns = re.sub(r"<connection\b(?![^>]*\brefreshOnLoad=)([^>]*?)(/?)>",
                       r'<connection\1 refreshOnLoad="1"\2>', conns)
        total = len(re.findall(r"<connection\b", conns))
        base["xl/connections.xml"] = conns.encode()
        report.append(f"refresh-on-open set on all {total} connection(s); "
                      f"{total - before} of them did not have it")

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

    # AND NO CELL MAY BE WRITTEN TWICE. A row holding two cells with the same reference is
    # well-formed XML, resolves every relationship, and is still refused by Excel with "we
    # found a problem with some content" - the prompt whose Yes button strips Power Query out
    # of this workbook. It happened here on 2026-08-26 by appending after the last HEADER on
    # a sheet whose lower rows ran wider than its header row. Nothing above can see it, so it
    # gets its own gate.
    dupes = []
    for n in base:
        if not re.match(r"xl/worksheets/sheet\d+\.xml$", n):
            continue
        for rnum, rxml in widen_sheets.sheet_rows(base[n].decode())[0]:
            refs = re.findall(r'<c\b[^>]*?\br="([A-Z]+\d+)"', rxml)
            if len(refs) != len(set(refs)):
                seen, twice = set(), []
                for r in refs:
                    (twice.append(r) if r in seen else seen.add(r))
                dupes.append(f"{n} row {rnum}: {', '.join(sorted(set(twice))[:6])}")
    if dupes:
        print("REFUSING TO WRITE - a cell is written twice:", file=sys.stderr)
        for d in dupes[:12]:
            print("  x", d, file=sys.stderr)
        return 1
    report.append("no worksheet writes the same cell twice")

    # AND NO CHART MAY POINT AT A BLOCK. A series value, a category axis or a title has to be
    # a single cell, a row or a column; Excel refuses anything else with "the reference is not
    # valid", in a dialog, at open time, and says nothing in the file. That is what a
    # half-finished column remap produces: rewriting only the START of `$QM$2:$QM$13` gives
    # `$QV$2:$QM$13`, two columns wide and running backwards. It parses, it resolves, and it
    # will not draw.
    blocks = []
    for n in sorted(base):
        if re.match(r"xl/charts/chart\d+\.xml$", n):
            for b in widen_sheets.block_refs(base[n].decode()):
                blocks.append(f"{os.path.basename(n)}: {b}")
    if blocks:
        print("REFUSING TO WRITE - a chart points at a block, not a row or column:",
              file=sys.stderr)
        for b in blocks[:12]:
            print("  x", b, file=sys.stderr)
        return 1
    report.append("every chart reference is a single cell, row or column")

    # AND A CAPTURE CHART MUST PLOT WHAT IT SAYS IT PLOTS. Reading the caption and reading the
    # columns are independent, and a mismatch is what the positional chart selection produced:
    # a second copy of Italy's biomass chart under a caption naming something else.
    mismatched = chart_layout.caption_matches_data(base, bs)
    if mismatched:
        print("REFUSING TO WRITE - a chart does not plot what it is captioned:", file=sys.stderr)
        for m in mismatched[:12]:
            print("  x", m, file=sys.stderr)
        return 1
    report.append("every capture chart plots the country and technology it is captioned")

    # A FIXED TIMESTAMP ON EVERY ENTRY, so two builds of the same inputs are byte-identical
    # and can be compared with a checksum. Left to itself zipfile stamps the current time, and
    # then every rebuild differs from the last for no reason anyone can see.
    tmp = a.out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            info = zipfile.ZipInfo(n, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            z.writestr(info, base[n])
    shutil.move(tmp, a.out)
    print("\n".join(report))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    sys.exit(main() or 0)
