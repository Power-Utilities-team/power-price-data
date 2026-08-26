"""widen_sheets.py — give the linked workbook's sheets the columns a newer build added.

WHY THIS EXISTS, and it is the fault that shipped on 2026-08-26. The first version of the
merger left every sheet the base already had exactly as it found it, on the reasoning that
these are Power Query outputs and Excel widens them itself on the refresh-on-open every
connection in this workbook carries. That is true of most of them and false of the one that
mattered most. `CaptureVsBase` is not a query output at all: it is 30,420 formulas reading
CaptureMonthly, A_MonthPrice and Status, it has no connection and no ExternalData_1 range,
and nothing refreshes it, ever. The delivered file therefore carried 376 of the 502 columns
the build produces, and the seven new capture charts pointed at columns that did not exist,
so they drew nothing at all. Three more charts were blank for the softer version of the same
reason: their sheets do widen on refresh, but not until one succeeds, so the file was wrong
in the hand of anyone who opened it before that.

WHAT IT DOES. For every sheet present in both files whose header row has grown, the donor's
extra columns are APPENDED to the base sheet.

APPENDED, NEVER MERGED IN PLACE, and this is the whole design. `CaptureVsBase` is read by 30
charts that are already linked into the deck, and the donor's own build inserts a new
technology at column 30 and shifts 346 columns sideways behind it. Adopting the donor's
layout would silently repoint all 30 of those charts at the wrong technology, which is the
worst outcome available here: every chart still draws, and every one of them is wrong. So the
base's column ORDER is authoritative and only the tail grows. Columns the donor has dropped
(eight Italian run-of-river series) keep their existing cells, so the charts plotting them
carry on unchanged.

The charts that come from the donor are then remapped from the donor's column letters to the
letters those same headers ended up at. That remap is by HEADER TEXT, so it cannot quietly
land on the wrong column the way position matching would.

WHAT IS CHECKED BEFORE ANY OF IT IS TRUSTED. A donor formula that reaches into another sheet
by column letter is only safe if that sheet's own columns did not move. `identity_only`
asserts exactly that, and the merger refuses to write if it does not hold.
"""
from __future__ import annotations

import re

CELL = re.compile(r"<c\b[^>]*?(?:/>|>.*?</c>)", re.S)
ROW = re.compile(r"<row\b[^>]*?(?:/>|>.*?</row>)", re.S)
REF = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)!(\$?)([A-Z]{1,3})(\$?)(\d+)")

# A RANGE, not a cell, and that distinction is the bug this file shipped on 2026-08-26.
# `remap_refs` used the cell pattern above, so `CaptureVsBase!$QM$2:$QM$13` had its START
# rewritten to the column that header moved to and its END left at the donor's column. The
# result was `$QV$2:$QM$13`: two columns wide, running backwards, and Excel refuses to draw
# it with "the reference is not valid ... must be a single cell, row, or column". Every
# structural check passed, because the file is perfectly well-formed. It just means
# something different.
CELL_PART = r"(\$?)([A-Z]{1,3})(\$?)(\d+)"
RANGE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)!" + CELL_PART
                   + r"(?::" + CELL_PART + r")?")
SELF_RANGE = re.compile(r"(?<![A-Za-z0-9_$!])" + CELL_PART
                        + r"(?::" + CELL_PART + r")?(?![A-Za-z0-9_(])")


def col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_rows(sheet_xml: str):
    """([(row number, row xml)], the sheetData match) without a real XML parse.

    These parts carry namespaces the project edits as bytes elsewhere, and a round trip
    through a parser would rewrite prefixes it has no business touching.
    """
    m = re.search(r"<sheetData\b[^>]*>(.*?)</sheetData>", sheet_xml, re.S)
    if not m:
        return [], None
    rows = []
    for r in ROW.findall(m.group(1)):
        n = re.search(r'\br="(\d+)"', r)
        if n:
            rows.append((int(n.group(1)), r))
    return rows, m


def row_cells(row_xml: str):
    """{column number: cell xml} for one row."""
    out = {}
    for c in CELL.findall(row_xml):
        r = re.search(r'\br="([A-Z]+)\d+"', c)
        if r:
            out[col_num(r.group(1))] = c
    return out


def shared_strings(parts):
    if "xl/sharedStrings.xml" not in parts:
        return []
    return ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", s)) for s in
            re.findall(r"<si>(.*?)</si>", parts["xl/sharedStrings.xml"].decode(), re.S)]


def headers(sheet_xml: str, sst):
    """{column number: header text} from row 1, resolving shared strings."""
    rows, _ = sheet_rows(sheet_xml)
    first = next((r for n, r in rows if n == 1), None)
    if first is None:
        return {}
    out = {}
    for col, c in row_cells(first).items():
        t = re.search(r't="(\w+)"', c)
        t = t.group(1) if t else "n"
        if t == "inlineStr":
            out[col] = "".join(re.findall(r"<t[^>]*>([^<]*)</t>", c))
        elif t == "s":
            i = re.search(r"<v>(\d+)</v>", c)
            out[col] = sst[int(i.group(1))] if i and int(i.group(1)) < len(sst) else ""
        else:
            v = re.search(r"<v>([^<]*)</v>", c)
            out[col] = v.group(1) if v else ""
    return out


def _restyle(cell: str, col: int, row: int, style, maps=None, own=None):
    """A donor cell, moved to (col, row), wearing one of the base sheet's own styles.

    THE STYLE INDEX HAS TO BE THE BASE'S. It points into the base's styles.xml and the two
    files number their formats differently, so carrying the donor's index across shows dates
    as five-digit numbers and percentages as raw fractions. The base's own last cell in that
    same row is the right template: it is how this sheet already formats a header, or a data
    value, depending on which row we are on.

    THE FORMULA HAS TO MOVE WITH IT. A cell that says `INDEX($EO$2:$EO$205,...)` names one
    specific column of its own sheet, and that column is somewhere else in the merged
    workbook; a cell that says `A_MonthPrice!$B2` names a column of another sheet, which may
    also have moved. Both go through the same single pass.
    """
    cell = re.sub(r'\br="[A-Z]+\d+"', f'r="{col_letters(col)}{row}"', cell, count=1)
    cell = re.sub(r'\s+s="\d+"', "", cell, count=1)
    if style is not None:
        cell = re.sub(r'(<c\b\s+r="[A-Z]+\d+")', rf'\1 s="{style}"', cell, count=1)
    if maps and "<f" in cell:
        cell = re.sub(r"(<f[^>]*>)([^<]*)(</f>)",
                      lambda m: m.group(1) + remap_formula(m.group(2), maps, own) + m.group(3),
                      cell)
    return cell


SELF_REF = re.compile(r"(?<![A-Za-z0-9_$!])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])")


def relative_local_refs(cells):
    """Formulas that reach a cell on their own sheet WITHOUT pinning the column.

    `CaptureVsBase` is built out of things like `INDEX($EO$2:$EO$205,...)`, which reach along
    the sheet the formula lives on. Those are remappable, because the column is pinned and
    therefore names one specific column that this tool knows the new home of. A reference
    written `EO$2` would not be: its meaning depends on where the cell itself sits, and every
    appended cell has been moved. Nothing this project generates is written that way, so the
    honest response to one turning up is to stop rather than to guess.
    """
    out = []
    for c in cells:
        for f in re.findall(r"<f[^>]*>([^<]*)</f>", c):
            for m in SELF_REF.finditer(REF.sub("", f)):
                if not m.group(1):
                    out.append(f[:120])
    return out


def _plan(base, donor, bs, ds):
    """{sheet: (base worksheet path, {donor col: merged col}, [(donor col, header)])}.

    Worked out for EVERY shared sheet before a single cell is moved. A donor formula names
    other sheets by column letter, so translating one sheet's cells needs the finished map of
    the sheets it reaches into; building the maps as you go would translate against whichever
    ones happened to be done first.
    """
    b_sst, d_sst = shared_strings(base), shared_strings(donor)
    plan = {}
    for name in bs:
        if name not in ds:
            continue
        bws, dws = bs[name][0], ds[name][0]
        if bws not in base or dws not in donor:
            continue
        b_hdr = headers(base[bws].decode(), b_sst)
        d_hdr = headers(donor[dws].decode(), d_sst)
        if not b_hdr or not d_hdr:
            continue
        # A blank header would match every other blank header, so two unrelated columns would
        # be treated as the same one. Nothing generated here has a blank header; a sheet that
        # does is left alone rather than guessed at.
        if any(not t.strip() for t in d_hdr.values()) or any(not t.strip() for t in b_hdr.values()):
            continue
        if len(set(d_hdr.values())) != len(d_hdr) or len(set(b_hdr.values())) != len(b_hdr):
            continue
        b_by_text = {text: col for col, text in sorted(b_hdr.items(), reverse=True)}
        new = [(col, text) for col, text in sorted(d_hdr.items()) if text not in b_by_text]
        cmap = {col: b_by_text[text] for col, text in d_hdr.items() if text in b_by_text}
        # THE WIDTH OF THE SHEET, NOT THE WIDTH OF ITS HEADER ROW. `Status` labels 14
        # columns and carries content out to P on rows further down, where the warnings that
        # tell a reader the file has not refreshed live. Appending after the last HEADER put
        # a second cell at O2 beside the one already there, and Excel answered with "we
        # found a problem with some content", whose Yes button strips Power Query out of
        # this workbook. Duplicate cell references are invisible to every structural check:
        # the XML parses, the relationships resolve, and the file is still refused.
        b_max = max(b_hdr)
        for _, rxml in sheet_rows(base[bws].decode())[0]:
            cells = row_cells(rxml)
            if cells:
                b_max = max(b_max, max(cells))
        dim = re.search(r'<dimension ref="[A-Z]+\d+:([A-Z]+)\d+"', base[bws].decode())
        if dim:
            b_max = max(b_max, col_num(dim.group(1)))
        for i, (dcol, _) in enumerate(new, start=1):
            cmap[dcol] = b_max + i
        plan[name] = (bws, cmap, new, b_max)
    return plan


def widen(base, donor, bs, ds, report, only=None):
    """Append the donor's new columns to every shared sheet.

    Returns ({sheet: {donor column: merged column}}, [problems], [sheets actually widened]).
    The maps are what every piece of donor XML that follows has to be rewritten through.
    """
    plan = _plan(base, donor, bs, ds)
    maps = {n: cmap for n, (_, cmap, _, _) in plan.items()}
    problems, widened = [], []

    for name, (bws, cmap, new, b_max) in plan.items():
        if not new or (only is not None and name not in only):
            continue
        b_xml = base[bws].decode()
        b_rows, span = sheet_rows(b_xml)
        if not b_rows:
            continue
        d_rows = dict(sheet_rows(donor[ds[name][0]].decode())[0])
        width = b_max + len(new)

        moved = []
        for rnum, _ in b_rows:
            drow = d_rows.get(rnum)
            if drow is None:
                continue
            dc = row_cells(drow)
            moved.extend(c for col, _ in new if dc.get(col) is not None
                         for c in [dc[col]])
        loose = relative_local_refs(moved)
        if loose:
            problems.append(f"{name}: a formula reaches its own sheet without pinning the "
                            f"column ({loose[0]}), so moving it would change what it means")
            continue

        out, added = [], 0
        for rnum, rxml in b_rows:
            drow = d_rows.get(rnum)
            if drow is None or not rxml.endswith("</row>"):
                out.append(rxml)
                continue
            bcells = row_cells(rxml)
            style = None
            if bcells:
                s = re.search(r'\bs="(\d+)"', bcells[max(bcells)])
                style = s.group(1) if s else None
            dcells = row_cells(drow)
            extra = []
            for dcol, _ in new:
                c = dcells.get(dcol)
                if c is None:
                    continue
                extra.append(_restyle(c, cmap[dcol], rnum, style, maps, name))
                added += 1
            if not extra:
                out.append(rxml)
                continue
            rxml = re.sub(r'\bspans="\d+:\d+"', f'spans="1:{width}"', rxml, count=1)
            out.append(rxml[:rxml.rfind("</row>")] + "".join(extra) + "</row>")

        last_row = max(n for n, _ in b_rows)
        b_xml = b_xml[:span.start(1)] + "".join(out) + b_xml[span.end(1):]
        b_xml = re.sub(r'<dimension ref="[^"]*"/>',
                       f'<dimension ref="A1:{col_letters(width)}{last_row}"/>', b_xml, count=1)
        base[bws] = b_xml.encode()
        report.append(f"  {name}: +{len(new)} column(s) appended from "
                      f"{col_letters(b_max + 1)}, {added} cells written, "
                      f"{b_max} existing column(s) left exactly where they were")
        widened.append(name)
    return maps, problems, widened



def identity_only(maps, sheets):
    """The sheets a donor formula reaches into must not have moved. Returns what did.

    A formula copied out of the donor says `CaptureMonthly!B2`. That is only still true in the
    merged workbook if CaptureMonthly's column B holds what it held in the donor. Every sheet
    this project's formulas reach into grows by appending, so the map should be the identity;
    this asserts it rather than trusting it.
    """
    bad = []
    for s in sheets:
        cm = maps.get(s)
        if cm and any(k != v for k, v in cm.items()):
            n = sum(1 for k, v in cm.items() if k != v)
            bad.append(f"{s} ({n} column(s) land somewhere else)")
    return bad


def formula_sheets(parts, sheet_paths):
    """Every sheet name reached by a formula on the given sheets."""
    out = set()
    for p in sheet_paths:
        if p not in parts:
            continue
        for f in re.findall(r"<f[^>]*>([^<]*)</f>", parts[p].decode()):
            out.update(m.group(1) for m in REF.finditer(f))
    return out


def _shift(cm, letters):
    """One column letter through a map, unchanged if the map does not name it."""
    n = cm.get(col_num(letters))
    return letters if n is None else col_letters(n)


def remap_refs(xml: str, maps) -> str:
    """Rewrite donor references onto the columns those headers actually ended up at.

    BOTH ENDS OF A RANGE, always. Moving only the start turns a one-column series into a
    backwards two-column block that Excel will not draw.
    """
    if not maps:
        return xml

    def one(m):
        sheet = m.group(1)
        cm = maps.get(sheet)
        if not cm:
            return m.group(0)
        d1, c1, d2, r1 = m.group(2), m.group(3), m.group(4), m.group(5)
        out = f"{sheet}!{d1}{_shift(cm, c1)}{d2}{r1}"
        if m.group(6) is not None or m.group(7):
            d3, c2, d4, r2 = m.group(6), m.group(7), m.group(8), m.group(9)
            out += f":{d3}{_shift(cm, c2)}{d4}{r2}"
        return out

    return RANGE.sub(one, xml)


def remap_formula(text: str, maps, own: str) -> str:
    """One formula, moved to another column of its own sheet.

    Two kinds of reference need different maps and they overlap in the text, so a single
    left-to-right pass handles both: `Sheet!$B$2:$B$9` goes through that sheet's map, and a
    bare `$EO$2:$EO$205` through the map of the sheet the formula lives on. Two passes would
    let the second rewrite the letters the first had just produced.
    """
    own_map = maps.get(own, {})
    pattern = re.compile(RANGE.pattern + r"|" + SELF_RANGE.pattern)

    def one(m):
        if m.group(1) is not None:
            cm = maps.get(m.group(1))
            if cm is None:
                return m.group(0)
            sheet, g = m.group(1) + "!", m.groups()[1:9]
        else:
            cm, sheet, g = own_map, "", m.groups()[9:17]
        d1, c1, d2, r1, d3, c2, d4, r2 = g
        out = f"{sheet}{d1}{_shift(cm, c1)}{d2}{r1}"
        if c2:
            out += f":{d3}{_shift(cm, c2)}{d4}{r2}"
        return out

    return pattern.sub(one, text)


def block_refs(chart_xml: str):
    """Chart references that are neither a single cell, nor a row, nor a column.

    Excel refuses to draw one, and says so in a dialog rather than in the file. A backwards
    range counts too: `$QV$2:$QM$13` is what a half-finished column remap produces.
    """
    out = []
    for f in re.findall(r"<c:f>([^<]+)</c:f>", chart_xml):
        for m in RANGE.finditer(f):
            if not m.group(7):
                continue
            c1, r1, c2, r2 = m.group(3), int(m.group(5)), m.group(7), int(m.group(9))
            if col_num(c2) < col_num(c1) or r2 < r1:
                out.append(f"{f} runs backwards")
            elif c1 != c2 and r1 != r2:
                out.append(f"{f} spans rows and columns")
    return out
