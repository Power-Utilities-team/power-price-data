"""Point the three SINGLE-YEAR charts at the rolling window, so they survive the year turn.

THE LAST THREE
    roll_year_window.py and roll_line_windows.py between them freed twelve charts from
    the year they were built in. Three were left: chart 7 (daily min/max scatter, DE),
    chart 8 (intraday generation mix, PORTUGAL) and chart 15 (price-by-month duck curve,
    DE). Each plots ONE year rather than a span of them, so neither of those scripts
    applied, and each stayed pinned to whichever year the workbook was built in.

    That was the entire remaining reason the workbook told its reader to download a
    replacement every January. Sixteen of nineteen charts already advanced on an ordinary
    refresh; these three would have gone on showing 2025 for ever while the rest moved,
    which is worse than an obviously stale file — the workbook would have looked healthy
    and been quietly wrong in three places.

HOW
    Identical in principle to the other two scripts, and simpler in practice because
    there is no window to walk: each series moves from a hardcoded {country}_{year}_x
    column on its own Fig sheet to a fixed column on the shared Line_Window tab, which
    extra_summaries.SINGLE_YEAR_BLOCKS fills from the latest complete year. The column
    POSITION never changes, so the reference stays valid for ever; its MEANING advances
    every January because `last_complete_year` does.

    Series names are left alone. Unlike the year-series charts, none of these names is a
    year: chart 8's are technologies and chart 15's are month names, both constant. Only
    chart 7's carried a year ("DE 2025"), and it is a single-series scatter whose legend
    is suppressed, so it takes the rolling year label from the Status row for correctness
    rather than for display.

Runs after add_power_queries.py (which creates the Line_Window table this reads) and
after resync_prefill.py, so the table is already at its full width. Before
move_status_first / drop_readme_sheet, which re-assert the sheet mapping.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg
from completeness import cutoffs

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
WINDOW_TAB = "Line_Window"
STATUS_SHEET = "Status"

# chart -> list of Line_Window column names, IN SERIES ORDER. The order is load-bearing:
# series i is re-pointed at column i, so a wrong order would relabel real data rather
# than fail, which is the one failure mode worth being paranoid about here.
CHARTS = {
    8: ["gm_Gas", "gm_Biomass", "gm_HydroROR", "gm_HydroRes", "gm_HydroPump",
        "gm_Onshore", "gm_Solar", "gm_Other", "gm_Price"],
    15: [f"md_M{m:02d}" for m in range(1, 13)],
}

# chart 7 is a scatter: x and y come from two different columns of the same year.
SCATTER = {7: ("mm_DE_max", "mm_DE_min")}

# The Charts-tab captions for these two exhibits spell the year out in words, as rich
# text with the year baked in. Rolling the DATA without rolling the CAPTION would be
# worse than leaving both alone: the exhibit would show the new year under last year's
# heading, and a confidently wrong label is harder to catch than an obviously old one.
# add_phase4_charts.py rewrites these at BUILD time; that is no longer enough for a
# workbook that is never rebuilt, so they become formulas over the Status row instead.
CAPTIONS = [
    "Fig 6 — Daily minimum vs maximum price (Germany, ",
    "Fig 7 — Intraday generation mix and price (Portugal, ",
]
CHARTS_SHEET = "Charts"
# Status!$C$2 is last_complete_year, republished on every refresh.
YEAR_CELL = "Status!$C$2"


def header_of(parts, part):
    x = parts[part].decode()
    row1 = re.search(r'<row r="1"[^>]*>(.*?)</row>', x, re.S)
    if not row1:
        return {}
    return {m.group(1): m.group(2) for m in
            re.finditer(r'<c r="([A-Z]+)1"[^>]*><is><t>([^<]*)</t></is></c>', row1.group(1))}


def sheet_parts(parts):
    wb = parts["xl/workbook.xml"].decode()
    rm = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"',
                         parts["xl/_rels/workbook.xml.rels"].decode()))
    return {m.group(1): "xl/" + rm[m.group(2)].lstrip("/")
            for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="rId(\d+)"', wb)}


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    sp = sheet_parts(parts)
    if WINDOW_TAB not in sp:
        raise SystemExit(f"{WINDOW_TAB} tab missing — add_power_queries must run first")

    whdr = header_of(parts, sp[WINDOW_TAB])
    col_of = {v: k for k, v in whdr.items()}
    wx = parts[sp[WINDOW_TAB]].decode()
    last_row = max(int(m) for m in re.findall(r'<row r="(\d+)"', wx))

    lcy = cutoffs()["last_complete_year"]

    def need(name):
        col = col_of.get(name)
        if not col:
            raise SystemExit(
                f"{WINDOW_TAB}: no column {name!r}. extra_summaries.SINGLE_YEAR_BLOCKS "
                f"must run before this and publish it.")
        return col

    done = []

    # --- the two multi-series charts -------------------------------------------
    for num, cols in sorted(CHARTS.items()):
        p = f"xl/charts/chart{num}.xml"
        xml = parts[p].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
        if len(sers) != len(cols):
            raise SystemExit(
                f"chart{num}: {len(sers)} series but {len(cols)} columns configured. "
                f"These are matched BY POSITION, so a mismatch would silently plot the "
                f"wrong series under the right name.")

        # keep the chart's own row span — 24 hours here, not the tab's full 366
        rng = re.search(r"<c:val>.*?\$[A-Z]+\$(\d+):\$[A-Z]+\$(\d+)", sers[0], re.S)
        r0, r1 = int(rng.group(1)), min(int(rng.group(2)), last_row)

        for s, name in zip(sers, cols):
            col = need(name)
            new = re.sub(r"(<c:val>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{WINDOW_TAB}!${col}${r0}:${col}${r1}\g<2>",
                         s, count=1, flags=re.S)
            xml = xml.replace(s, new, 1)
        parts[p] = xml.encode()
        done.append(f"chart{num}({len(cols)} series)")

    # --- the scatter -----------------------------------------------------------
    # xVal and yVal are separate elements, so the generic <c:val> rewrite above does not
    # reach them; they are handled explicitly rather than by a looser regex that might
    # match one and miss the other.
    for num, (xcol_name, ycol_name) in sorted(SCATTER.items()):
        p = f"xl/charts/chart{num}.xml"
        xml = parts[p].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
        if len(sers) != 1:
            raise SystemExit(f"chart{num}: {len(sers)} series, expected 1 (scatter)")
        s = sers[0]
        rng = re.search(r"<c:xVal>.*?\$[A-Z]+\$(\d+):\$[A-Z]+\$(\d+)", s, re.S)
        r0, r1 = int(rng.group(1)), min(int(rng.group(2)), last_row)
        xcol, ycol = need(xcol_name), need(ycol_name)
        new = s
        for tag, col in (("xVal", xcol), ("yVal", ycol)):
            before = new
            new = re.sub(rf"(<c:{tag}>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{WINDOW_TAB}!${col}${r0}:${col}${r1}\g<2>",
                         new, count=1, flags=re.S)
            if new == before:
                raise SystemExit(f"chart{num}: could not rewrite <c:{tag}> — chart shape changed")
        # the name carries a year, so point it at the Status row's latest-complete label
        shdr = header_of(parts, sp[STATUS_SHEET])
        wlab = {int(m.group(1)): letter for letter, nm in shdr.items()
                for m in [re.fullmatch(r"w(\d+)", str(nm or ""))] if m}
        if wlab:
            letter = wlab[max(wlab)]            # highest slot = latest complete year
            new = re.sub(
                r"<c:tx>.*?</c:tx>",
                f'<c:tx><c:strRef><c:f>{STATUS_SHEET}!${letter}$2</c:f>'
                f'<c:strCache><c:ptCount val="1"/>'
                f'<c:pt idx="0"><c:v>{lcy}</c:v></c:pt>'
                f'</c:strCache></c:strRef></c:tx>',
                new, count=1, flags=re.S)
        xml = xml.replace(s, new, 1)
        parts[p] = xml.encode()
        done.append(f"chart{num}(scatter)")

    # --- the captions ----------------------------------------------------------
    # Each is one rich-text run, so the run's own <rPr> carries the bold/12pt/navy/Arial
    # look. A formula cell cannot hold a run, so the styling has to move to a cellXf; the
    # font is appended to styles.xml and referenced by index, which is the same approach
    # add_status_sheet.py uses for its own text.
    cs = parts[sp[CHARTS_SHEET]].decode()
    styles = parts["xl/styles.xml"].decode()

    nfonts = int(re.search(r'<fonts count="(\d+)"', styles).group(1))
    styles = re.sub(r'(<fonts count=")(\d+)(")', lambda m: f"{m.group(1)}{nfonts+1}{m.group(3)}",
                    styles, count=1)
    styles = styles.replace(
        "</fonts>",
        '<font><b/><sz val="12"/><color rgb="FF2E3E80"/><name val="Arial"/></font></fonts>', 1)
    nxf = int(re.search(r'<cellXfs count="(\d+)"', styles).group(1))
    styles = re.sub(r'(<cellXfs count=")(\d+)(")', lambda m: f"{m.group(1)}{nxf+1}{m.group(3)}",
                    styles, count=1)
    styles = styles.replace(
        "</cellXfs>",
        f'<xf numFmtId="0" fontId="{nfonts}" fillId="0" borderId="0" xfId="0" '
        f'applyFont="1"/></cellXfs>', 1)
    parts["xl/styles.xml"] = styles.encode()

    patched = 0
    for cap in CAPTIONS:
        # Match the ONE <c> element holding this caption. The `(?:(?!</c>).)*` guards are
        # load-bearing: a plain `.*?` spans cell boundaries, so the first attempt at this
        # matched from cell A1 all the way to the caption and would have replaced every
        # cell in between with a single one. Tempering the wildcard so it can never cross
        # a </c> makes that impossible rather than merely unlikely.
        pat = re.compile(
            r'<c r="([A-Z]+\d+)"(?:(?!</c>).)*?t="inlineStr"(?:(?!</c>).)*?'
            + re.escape(cap) + r'(\d{4})\)</t>(?:(?!</c>).)*?</c>', re.S)
        m = pat.search(cs)
        if not m:
            raise SystemExit(
                f"Charts tab: caption {cap!r} not found. It is rewritten here so it can "
                f"never contradict the rolled data — fix the mapping rather than shipping "
                f"a caption whose year is frozen.")
        ref, yr = m.group(1), m.group(2)
        text = f"{cap}{lcy})"
        formula = f'"{cap}"&amp;{YEAR_CELL}&amp;")"'
        cs = cs[:m.start()] + (
            f'<c r="{ref}" s="{nxf}" t="str"><f>{formula}</f><v>{text}</v></c>'
        ) + cs[m.end():]
        patched += 1
        done.append(f"caption {ref} (was {yr})")
    parts[sp[CHARTS_SHEET]] = cs.encode()
    if patched != len(CAPTIONS):
        raise SystemExit("caption patch count mismatch")

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  rolled onto {WINDOW_TAB} (latest complete year {lcy}): {', '.join(done)}")


if __name__ == "__main__":
    main()
