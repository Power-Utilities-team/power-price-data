"""chart_layout.py — size the charts so that what UpSlide exports is the size Fred wants.

UPSLIDE EXPORTS 1:1. A chart's size on the Excel sheet IS its size in the deck. Measured
2026-08-27 across all 52 linked charts in the deck, after Fred's team resized 32 of them in
Excel and refreshed:

    32 charts   ratio 1.000 across and down, exactly
    20 charts   ratios 0.704, 0.705, 0.717, 0.718, 0.726

Five different ratios in the second group is hand-dragging, not a scale. Those 20 pictures
were sized by hand in PowerPoint and have not been re-exported since, which is also why a
refresh appears to change their size: it does not change it, it restores it.

⚠ THIS CORRECTS THE 2026-08-26 READING OF 0.70535, WHICH WAS WRONG. That figure came from
three pictures believed untouched, and all three turned out to be hand-resized. The error was
invisible while every measurement came from the same contaminated set; it only showed up once
32 charts had been resized in Excel and re-exported, giving a clean control group. Anything
that still quotes 0.70535 as an export scale is repeating the mistake.

WHAT THIS MODULE DOES. Sets each chart to the size its family uses in the deck, taken from the
charts ACTUALLY LINKED into the deck rather than from the whole sheet (Fred, 2026-08-27: "anchor
to whatever size is used in the charts that are actually used in the powerpoint, not the size of
the charts that are *not* used"). Unlinked charts are no evidence: they have never been exported,
so their size says nothing about what the slide wants.

THE FAMILY IS DECIDED BY WHAT A CHART PLOTS, NOT BY ITS NAME OR ITS POSITION. A capture chart
plots windowed columns on `CaptureVsBase` named `<country>_<tech> w1` to `w8`, and each of
those is an INDEX into a source column that is either `... % of base` or `... diff`. Following
that INDEX is what separates the two capture families, and it cannot go wrong the way matching
on a title or a chart number can. The remaining families are read off the caption above the
chart, which is the same text the deck's readers see.

A FAMILY WITH NO LINKED CHART IS LEFT ALONE, and named in the report. Six charts fall in that
gap as of 2026-08-27 (volatility, the duck belly, negative hours, duration curves and two
uncaptioned ones). Guessing a size for them would be inventing a target Fred has never seen.
"""
from __future__ import annotations

import re

import widen_sheets as W

EMU_PER_CM = 360000

# Measured 2026-08-27 across 52 linked charts. See the module docstring; this replaced 0.70535,
# which was read off three hand-resized pictures.
EXPORT_SCALE = 1.0

TARGET_CM = (12.0, 5.4)              # the default family size
TARGET_PCT_CM = (5.9, 4.0)           # capture as a % of base price

# Every family that has at least one chart LINKED into the deck, with the size those linked
# charts unanimously use. Read from `Utilities_Monthly_Product.pptx` on 2026-08-27; the count
# after each is how many linked charts agreed.
SIZE_CM = {
    "capture_pct":       (5.9, 4.0),    # 4 of 4  (the other 20 in the family are hand-sized)
    "capture_baseload":  (12.0, 6.29),  # 5 of 5
    "fig9_capacity":     (12.0, 6.29),  # 6 of 6
    "intraday_shape":    (12.0, 5.4),   # 6 of 6
    "cum_near_neg":      (12.0, 5.4),   # 6 of 6
    "hydro_weekly":      (12.0, 5.4),   # slide 31's TOP row: France, Spain
    "hydro_weekly_tall": (12.0, 6.29),  # slide 31's BOTTOM row: Portugal, Italy
}

# Fred chose on 2026-08-27 to KEEP slide 31's two rows at different heights rather than make
# the four weekly-hydro charts uniform. So the family splits by country, and the seven
# countries that are not on that slide follow the top row.
HYDRO_TALL = ("Portugal", "Italy")


def family_of(caption, pct):
    """Which size family a chart belongs to, or None to leave it alone.

    Matched case-insensitively throughout. The captions are written by hand and the same
    exhibit appears both as "Fig 5 - Capture price vs baseload..." and as
    "Portugal - capture price vs baseload...", so a case-sensitive test silently drops the
    figure-numbered member of a family. That is exactly what it did to Germany's Fig 5 on the
    first run of this rule, 2026-08-27.
    """
    if pct:
        return "capture_pct"
    c = (caption or "").lower()
    if "capture price vs baseload" in c:
        return "capture_baseload"
    if c.startswith("fig 9") or "installed generation capacity" in c:
        return "fig9_capacity"
    if "intraday price shape" in c:
        return "intraday_shape"
    if "near-negative-price hours" in c:
        return "cum_near_neg"
    if "reservoir fill by week" in c or "pumped-storage generation by week" in c:
        return ("hydro_weekly_tall"
                if any(c.startswith(x.lower()) for x in HYDRO_TALL) else "hydro_weekly")
    return None                      # no linked chart in this family: no evidence, no change


def _excel_emu(target_cm):
    """The Excel size whose export lands on `target_cm`."""
    return tuple(round(cm / EXPORT_SCALE * EMU_PER_CM) for cm in target_cm)


def capture_vs_base_map(parts, sheets):
    """{column on CaptureVsBase: the source column its INDEX reads}, by header text.

    The charts plot `w1` to `w8`, which are windows, and a window says nothing about whether
    it holds a percentage or a difference. Its formula does.
    """
    if "CaptureVsBase" not in sheets:
        return {}, {}
    xml = parts[sheets["CaptureVsBase"][0]].decode()
    heads = W.headers(xml, W.shared_strings(parts))
    rows = dict(W.sheet_rows(xml)[0])
    src = {}
    if 2 in rows:
        for col, cell in W.row_cells(rows[2]).items():
            m = re.search(r"INDEX\(\$([A-Z]+)\$", cell)
            if m:
                src[col] = heads.get(W.col_num(m.group(1)), "")
    return heads, src


def is_percent_of_base(chart_xml, src) -> bool:
    """True when every series this chart plots is a percentage of the base price."""
    kinds = set()
    for m in re.finditer(r"<c:val>.*?</c:val>", chart_xml, re.S):
        for f in re.findall(r"<c:f>([^<]+)</c:f>", m.group(0)):
            for r in W.RANGE.finditer(f):
                if r.group(1) == "CaptureVsBase":
                    s = src.get(W.col_num(r.group(3)), "")
                    kinds.add("pct" if "% of base" in s else "other")
    return kinds == {"pct"}


def caption_matches_data(parts, sheets):
    """Capture charts whose data does not match the country and technology they are captioned.

    The one check that would have caught the 2026-08-26 selection bug on its own: a second copy
    of Italy's biomass chart carried a caption naming a different exhibit. Reading the caption
    and reading the columns are two independent facts, and they have to agree.
    """
    heads, _ = capture_vs_base_map(parts, sheets)
    country = {"Germany": "DE", "Spain": "ES", "Portugal": "PT",
               "France": "FR", "Italy": "IT", "Great Britain": "GB"}
    bad = []
    for part, cap in captions_by_chart(parts, sheets).items():
        m = re.match(r"^(.+?) — (.+?): capture as % of base price", cap)
        if not m or m.group(1) not in country:
            continue
        want = f"{country[m.group(1)]}_{m.group(2)} "
        plotted = set()
        for v in re.finditer(r"<c:val>.*?</c:val>", parts[part].decode(), re.S):
            for f in re.findall(r"<c:f>([^<]+)</c:f>", v.group(0)):
                for r in W.RANGE.finditer(f):
                    if r.group(1) == "CaptureVsBase":
                        plotted.add(heads.get(W.col_num(r.group(3)), ""))
        if not plotted or not all(h.startswith(want) for h in plotted):
            bad.append(f"{part.split('/')[-1]} is captioned {cap[:44]!r} and plots "
                       f"{sorted(plotted)[:1]}")
    return bad


def resize(parts, sheets, report, sheet="Charts", target=None, target_pct=None, scale=None):
    """Set every chart on one sheet to the size its FAMILY uses in the deck.

    A chart whose family has no linked counterpart is left exactly as it is, and named in the
    report. `target` and `target_pct` override the 12 x 5.4 and the capture-percentage families
    respectively, so the old flags still steer the two sizes anyone actually changes.
    """
    global TARGET_CM, TARGET_PCT_CM, EXPORT_SCALE, SIZE_CM
    TARGET_CM = target or TARGET_CM
    TARGET_PCT_CM = target_pct or TARGET_PCT_CM
    EXPORT_SCALE = scale or EXPORT_SCALE
    sizes = dict(SIZE_CM)
    if target:
        for k in ("intraday_shape", "cum_near_neg", "hydro_weekly"):
            sizes[k] = TARGET_CM
    if target_pct:
        sizes["capture_pct"] = TARGET_PCT_CM
    if sheet not in sheets:
        return {}
    ws, drawing = sheets[sheet]
    if not drawing:
        return {}
    rels = drawing.replace("drawings/", "drawings/_rels/") + ".rels"
    chart_of = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="\.\./(charts/chart\d+\.xml)"',
                               parts[rels].decode()))
    _, src = capture_vs_base_map(parts, sheets)
    caps = captions_by_chart(parts, sheets, sheet)

    counts, scaled, skipped = {}, {}, []
    def one(m):
        anchor = m.group(0)
        rid = re.search(r'r:id="(rId\d+)"', anchor)
        if not rid or rid.group(1) not in chart_of:
            return anchor
        part = "xl/" + chart_of[rid.group(1)]
        if part not in parts:
            return anchor
        pct = is_percent_of_base(parts[part].decode(), src)
        fam = family_of(caps.get(part, ""), pct)
        if fam is None:
            skipped.append(caps.get(part, "(uncaptioned)")[:60])
            return anchor                     # no linked evidence: do not invent a size
        cx, cy = _excel_emu(sizes[fam])
        counts[fam] = counts.get(fam, 0) + 1
        # BY WIDTH, deliberately, and NOT by whichever dimension shrank most. Scaling on the
        # height would have brought the large family from 9pt to 7.5pt to make room for its
        # rotated category labels, and Fred ruled that out on 2026-08-26: the type is already
        # hard to read on the slide, so it is a floor rather than a lever. Where the labels
        # still do not fit, the answer has to be more room, not smaller words.
        was = re.search(r'<xdr:ext cx="(\d+)" cy="(\d+)"', anchor)
        if was:
            scaled[part] = cx / int(was.group(1))
        return re.sub(r'<xdr:ext cx="\d+" cy="\d+"/>',
                      f'<xdr:ext cx="{cx}" cy="{cy}"/>', anchor, count=1)

    parts[drawing] = re.sub(r"<xdr:(?:one|two)CellAnchor\b[^>]*>.*?</xdr:(?:one|two)CellAnchor>",
                            one, parts[drawing].decode(), flags=re.S).encode()
    for fam in sorted(counts):
        w, h = sizes[fam]
        report.append(f"  {sheet}: {counts[fam]:2d} chart(s) in '{fam}' set to {w} x {h} cm")
    if skipped:
        report.append(f"  {sheet}: {len(skipped)} chart(s) LEFT ALONE, no linked chart in "
                      f"their family to anchor a size: {'; '.join(sorted(set(skipped)))}")
    return scaled


def scale_fonts(parts, factors, report, floor=350):
    """Bring the type down in step with a chart that has been made smaller.

    An Excel chart REFLOWS rather than scales: halve its width and the 9pt labels stay 9pt in
    half the room. That is not distortion, but it does mean a chart shrunk to a third of its
    area comes back with type three times as prominent as the copy people are used to. Where
    the exported picture has to keep looking like the one already in the deck, the type has to
    come down by the same factor the chart did.
    """
    n, touched, seen = 0, 0, []
    for part, factor in sorted(factors.items()):
        if part not in parts or factor > 0.95:
            continue                       # a chart that barely moved keeps its type
        def shrink(m, f=factor):
            old = int(m.group(1))
            new = max(floor, int(round(old * f / 50.0) * 50))
            return m.group(0).replace(f'sz="{old}"', f'sz="{new}"')
        xml, k = re.subn(r'<a:defRPr[^>]*\bsz="(\d+)"[^>]*>', shrink, parts[part].decode())
        parts[part] = xml.encode()
        n += k
        touched += 1
        seen.append(factor)
    if touched:
        report.append(f"  type scaled with each chart on {touched} chart(s) "
                      f"(factors {min(seen):.2f} to {max(seen):.2f}, floor "
                      f"{floor / 100:.1f}pt), {n} run(s), so nothing crowds")


def repoint(parts, sheets, chart_part, frm, to, report):
    """Move one chart's series from one technology's columns to another's, by header name.

    By NAME, so it cannot land on the wrong column, and only on the chart named. The capture
    charts carry no title of their own (`autoTitleDeleted` is 1 and the technology is labelled
    in the deck), so nothing else in the workbook needs to change with it.
    """
    if chart_part not in parts:
        report.append(f"  SKIP repoint {chart_part}: not in the workbook")
        return
    heads, _ = capture_vs_base_map(parts, sheets)
    by_text = {t: c for c, t in heads.items()}
    move = {}
    for text, col in by_text.items():
        if text.startswith(frm):
            tail = text[len(frm):]
            dest = by_text.get(to + tail)
            if dest:
                move[col] = dest
    if not move:
        report.append(f"  SKIP repoint {chart_part}: no {to!r} column matches {frm!r}")
        return

    def one(m):
        r = m
        if r.group(1) != "CaptureVsBase":
            return r.group(0)
        c1 = W.col_num(r.group(3))
        if c1 not in move:
            return r.group(0)
        out = f"CaptureVsBase!{r.group(2)}{W.col_letters(move[c1])}{r.group(4)}{r.group(5)}"
        if r.group(7):
            c2 = W.col_num(r.group(7))
            out += f":{r.group(6)}{W.col_letters(move.get(c2, c2))}{r.group(8)}{r.group(9)}"
        return out

    # Counted by what CHANGED, not by what the regex looked at: `subn` counts every match it
    # processed, including the references deliberately left alone, and reporting 24 moved
    # when 8 moved is the kind of number someone later checks a build against.
    before = W.RANGE.findall(parts[chart_part].decode())
    xml = W.RANGE.sub(one, parts[chart_part].decode())
    parts[chart_part] = xml.encode()
    moved = sum(1 for a, b in zip(before, W.RANGE.findall(xml)) if a != b)
    report.append(f"  {chart_part.split('/')[-1]}: {moved} series reference(s) moved from "
                  f"{frm!r} to {to!r}")


# ---- laying the Charts sheet out -----------------------------------------------------------
# The sheet is a two-column contact sheet: a caption in column A or column L, and the chart it
# describes anchored on the row beneath it. Nothing enforced that, so it had drifted before any
# of this work began: four charts sat on top of the next band's caption, because those bands
# were given 19 rows where the chart needed 20.
#
# Resizing made it worse rather than better, and appending 22 charts on a fixed 10-row step made
# it worse again: a 7.66 cm chart is 14.5 rows tall, so consecutive charts overlapped each other.
# Reflowing from the chart sizes themselves is the only version of this that cannot drift, because
# the band is computed from what it has to hold.

ROW_EMU = 190500                      # a default 15pt row
COL_EMU = 609600                      # a default 8.43-character column
GAP_CM = 1.63                         # the gap the sheet already used between a pair, measured
BAND_SPARE_ROWS = 2                   # blank rows under a chart before the next caption


def _rows_for(cy_emu):
    return -(-cy_emu // ROW_EMU)      # ceiling


def read_captions(parts, sheets, sheet="Charts"):
    """{(row, column): (text, style)} for every caption cell on the sheet."""
    ws = sheets[sheet][0]
    sst = W.shared_strings(parts)
    out = {}
    for rn, rx in W.sheet_rows(parts[ws].decode())[0]:
        for col, cell in W.row_cells(rx).items():
            t = re.search(r't="(\w+)"', cell)
            t = t.group(1) if t else "n"
            if t == "inlineStr":
                v = "".join(re.findall(r"<t[^>]*>([^<]*)</t>", cell))
            elif t == "s":
                i = re.search(r"<v>(\d+)</v>", cell)
                v = sst[int(i.group(1))] if i and int(i.group(1)) < len(sst) else ""
            else:
                v = ""
            if v.strip():
                s = re.search(r'\bs="(\d+)"', cell)
                out[(rn, col)] = (v, s.group(1) if s else None)
    return out


def _anchors(parts, drawing):
    """[(anchor xml, chart part, row0, col)] in document order."""
    rels = parts[drawing.replace("drawings/", "drawings/_rels/") + ".rels"].decode()
    chart_of = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="\.\./(charts/chart\d+\.xml)"', rels))
    out = []
    for m in re.finditer(r"<xdr:(?:one|two)CellAnchor\b[^>]*>.*?</xdr:(?:one|two)CellAnchor>",
                         parts[drawing].decode(), re.S):
        a = m.group(0)
        rid = re.search(r'r:id="(rId\d+)"', a)
        row = re.search(r"<xdr:row>(\d+)</xdr:row>", a)
        col = re.search(r"<xdr:col>(\d+)</xdr:col>", a)
        if rid and rid.group(1) in chart_of and row and col:
            out.append((a, "xl/" + chart_of[rid.group(1)], int(row.group(1)), int(col.group(1))))
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def caption_for(caps, row0, col, tolerance=3):
    """The caption belonging to a chart at (row0, col), or ("", None).

    NEAREST COLUMN ON THAT ROW, not an exact hit. Five charts on this sheet sit at a column
    offset (`Chart 6` is at column 10 plus 1.68 cm, under a caption in column L), so an exact
    `col + 1` lookup missed them and the reflow dropped three captions that were there all
    along.
    """
    row = [(c, v) for (r, c), v in caps.items() if r == row0]
    if not row:
        return ("", None)
    c, v = min(row, key=lambda kv: abs(kv[0] - (col + 1)))
    return v if abs(c - (col + 1)) <= tolerance else ("", None)


def captions_by_chart(parts, sheets, sheet="Charts"):
    """{chart part: the caption sitting above it}, for lifting them from another build."""
    caps = read_captions(parts, sheets, sheet)
    out = {}
    for _, part, row0, col in _anchors(parts, sheets[sheet][1]):
        text = caption_for(caps, row0, col)[0]
        if text:
            out[part] = text
    return out


def reflow(parts, sheets, extra_captions, report, sheet="Charts", per_row=2,
           renames=None):
    """Lay the contact sheet out again: two per band, a caption over every chart, no overlaps.

    `extra_captions` is {chart part: caption text} for charts the sheet has no caption for,
    which is how the newly added ones get theirs from the build that produced them.
    """
    ws, drawing = sheets[sheet]
    caps = read_captions(parts, sheets, sheet)
    anchors = _anchors(parts, drawing)
    if not anchors:
        return

    # Each chart's own caption, by where it sits now: column A over a chart in column 0, and
    # column L over one in column 11. Keep the words exactly; only the row is ours to move.
    style = next((s for _, s in caps.values() if s), None)
    plan = []
    for a, part, row0, col in anchors:
        text, st = caption_for(caps, row0, col)
        if not text:
            text, st = extra_captions.get(part, ""), None
        if renames and text in renames:
            text = renames[text]
        e = re.search(r'<xdr:ext cx="(\d+)" cy="(\d+)"', a)
        plan.append([a, part, text, st or style, int(e.group(1)), int(e.group(2))])

    # The second column sits so the pair keeps the gap the sheet already used, rounded to a
    # whole column so a caption still lands in a cell of its own.
    # WHERE each chart goes. Worked out first, applied second, and applied by SUBSTITUTING
    # each anchor's <xdr:from> in place rather than by rebuilding the drawing. The shape name
    # in <xdr:cNvPr> is what the deck's UpSlide links key on (`SOURCENAME = "Chart 59"`), and
    # anything on this sheet that is not a chart would be silently dropped by a rebuild.
    # BANDS HOLD ONE SIZE ONLY. The column a pair's second chart sits at is worked out from
    # the wider of the two, so pairing a 17 cm chart with an 8 cm one left a 10.4 cm hole
    # between them. Where the run changes size, the band ends.
    bands, run = [], []
    for entry in plan:
        if run and (len(run) == per_row or (run[0][4], run[0][5]) != (entry[4], entry[5])):
            bands.append(run)
            run = []
        run.append(entry)
    if run:
        bands.append(run)

    new_caps, moves, cursor = {}, {}, 0
    for band in bands:
        height = max(_rows_for(cy) for *_, cy in band)
        widest = max(cx for *_, cx, _ in band)
        step_col = max(1, int(round((widest + GAP_CM * 360000) / COL_EMU)))
        for k, (a, part, text, st, cx, cy) in enumerate(band):
            col = k * step_col
            if text:
                new_caps[(cursor + 1, col + 1)] = (text, st)
            moves[part] = (col, cursor + 1)
        cursor += 1 + height + BAND_SPARE_ROWS

    rels = parts[drawing.replace("drawings/", "drawings/_rels/") + ".rels"].decode()
    chart_of = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="\.\./(charts/chart\d+\.xml)"', rels))

    def place(m):
        a = m.group(0)
        rid = re.search(r'r:id="(rId\d+)"', a)
        if not rid or rid.group(1) not in chart_of:
            return a                                   # not a chart: left exactly as it was
        part = "xl/" + chart_of[rid.group(1)]
        if part not in moves:
            return a
        col, row = moves[part]
        a = re.sub(r"<xdr:col>\d+</xdr:col>", f"<xdr:col>{col}</xdr:col>", a, count=1)
        a = re.sub(r"<xdr:colOff>\d+</xdr:colOff>", "<xdr:colOff>0</xdr:colOff>", a, count=1)
        a = re.sub(r"<xdr:row>\d+</xdr:row>", f"<xdr:row>{row}</xdr:row>", a, count=1)
        a = re.sub(r"<xdr:rowOff>\d+</xdr:rowOff>", "<xdr:rowOff>0</xdr:rowOff>", a, count=1)
        return a

    before = re.findall(r'<xdr:cNvPr id="\d+" name="[^"]*"', parts[drawing].decode())
    d = re.sub(r"<xdr:(?:one|two)CellAnchor\b[^>]*>.*?</xdr:(?:one|two)CellAnchor>",
               place, parts[drawing].decode(), flags=re.S)
    after = re.findall(r'<xdr:cNvPr id="\d+" name="[^"]*"', d)
    if before != after:
        raise SystemExit("reflow would have changed a shape id or name, which is what the "
                         "deck's links are keyed on")
    parts[drawing] = d.encode()

    # The sheet holds nothing but captions, so it is rebuilt rather than patched.
    body = []
    for rn in sorted({r for r, _ in new_caps}):
        cells = "".join(
            f'<c r="{W.col_letters(c)}{rn}"' + (f' s="{new_caps[(rn, c)][1]}"' if new_caps[(rn, c)][1] else "")
            + f'  t="inlineStr"><is><t xml:space="preserve">{_esc(new_caps[(rn, c)][0])}</t></is></c>'
            for c in sorted(c for r, c in new_caps if r == rn))
        body.append(f'<row r="{rn}">{cells}</row>')
    sx = parts[ws].decode()
    m = re.search(r"<sheetData\b[^>]*>.*?</sheetData>", sx, re.S)
    sx = sx[:m.start()] + "<sheetData>" + "".join(body) + "</sheetData>" + sx[m.end():]
    last_col = max(c for _, c in new_caps)
    sx = re.sub(r'<dimension ref="[^"]*"/>',
                f'<dimension ref="A1:{W.col_letters(last_col)}{cursor}"/>', sx, count=1)
    parts[ws] = sx.encode()
    report.append(f"  {sheet}: relaid out, {len(plan)} chart(s) in {-(-len(plan) // per_row)} "
                  f"band(s) over {cursor} rows, {len(new_caps)} caption(s), "
                  f"{sum(1 for p in plan if not p[2])} chart(s) still without one")


def unpin_plot_area(parts, sheets, report, sheet="Charts"):
    """Let Excel decide how much of a chart the plot takes, where the chart says otherwise.

    ELEVEN CHARTS PIN THEIR PLOT AREA by manual layout to 70% of the chart height, which
    leaves a fixed 26% for the category labels and the legend TOGETHER, whatever size the
    chart is. Those are the charts with technology names on the axis, where the longest label
    is "Hydro pumped (production)"; rotated, it needs more than 26%, so it runs into the
    legend and Excel truncates it to "Hydro pumped (pr...".

    That is why neither lever worked. Making the chart taller grows the plot and the label
    band in the same proportion, so 8.5 cm was no better than 7.66. Shrinking the type shrinks
    the labels and the legend together, so 6.5pt was barely better than 9pt, and Fred ruled
    type out anyway on 2026-08-26: it is already hard to read on the slide.

    Removing the pin is what the other 72 charts already do, and Excel then gives the labels
    the room they need at any size. Rendered at 17.01 x 7.66 cm and 9pt, the labels come out
    in full and the legend sits on its own row beneath them.
    """
    if sheet not in sheets or not sheets[sheet][1]:
        return
    rels = parts[sheets[sheet][1].replace("drawings/", "drawings/_rels/") + ".rels"].decode()
    done = []
    for part in {"xl/" + t for t in
                 re.findall(r'Target="\.\./(charts/chart\d+\.xml)"', rels)}:
        if part not in parts:
            continue
        x = parts[part].decode()
        # ONLY WHERE THE LABELS ACTUALLY CROWD. 72 of the 78 charts pin their plot area, and
        # most are perfectly happy: a month name or a day number is short enough that Excel
        # never has to rotate it. Unpinning all of them would restyle exhibits that are fine.
        # The ones that crowd have a handful of categories with long words in them.
        cat = re.search(r"<c:cat>.*?</c:cat>", x, re.S)
        labels = re.findall(r"<c:pt idx=\"\d+\"><c:v>([^<]*)</c:v>", cat.group(0)) if cat else []
        if not labels or len(labels) > 20 or max(len(t) for t in labels) <= 12:
            continue
        new = re.sub(r"(<c:plotArea>)<c:layout>\s*<c:manualLayout>.*?</c:layout>",
                     r"\1<c:layout/>", x, count=1, flags=re.S)
        if new != x:
            parts[part] = new.encode()
            done.append(part.split("/")[-1])
    if done:
        report.append(f"  {sheet}: plot area unpinned on {len(done)} chart(s) so the axis "
                      f"labels get the room they need ({', '.join(sorted(done)[:4])}"
                      f"{', ...' if len(done) > 4 else ''})")
