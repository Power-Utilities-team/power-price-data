"""Point the annual BAR charts at the rolling window, so they survive the year turn.

THE PROBLEM
    A year is a chart SERIES, and the series count is fixed when the workbook is built.
    Power Query writes values into cells; it cannot create a series. So a workbook built
    in 2026 shows 2019-2025 for ever, however often it refreshes — the charts silently
    stop gaining years while the numbers inside them stay current.

WHY NOT JUST RESERVE EMPTY SERIES
    Measured 2026-07-30: on a BAR chart an empty series still claims its slot. Adding
    three took the cluster from 58px to 47px (-19%) and left visible gaps; reserving to
    2030 would cost ~40% of bar width. Naming them from a blank cell hides the legend
    entry but not the slot (51px, -12%). So reserving is out for bar charts.

WHAT THIS DOES INSTEAD
    The window rolls rather than grows. Each chart reads the same {country}_w1..w7
    columns for ever; chart_csv.add_window fills them from the last seven complete years,
    and build_status publishes those years as w1..w7 on the Status row. The series NAMES
    point at those label cells, so the legend rolls with the data.

    Verified: a series name read from a cell renders that cell's text — a probe pointing
    the seven names at cells holding 2013-2019 produced exactly that legend, with no
    "Series N" fallback and bar width unchanged at 58px.

    Net effect: every January the new complete year appears on an ordinary refresh, with
    no rebuild, no compression and correct year labels. The trade is that the exhibit is
    "the last seven complete years", so 2019 drops off in 2027 — Fred's explicit choice.

Runs after add_power_queries.py (which creates the Status table this reads) and before
build_frozen_excel / build_deck, which resolve sheets by name and so are order-agnostic.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")

# chart -> (sheet holding its data, country whose window it plots)
CHARTS = {6: ("Fig5_Window", "DE"), 12: ("Fig5_Window", "PT"), 9: ("Fig9_Window", "DE")}

STATUS_SHEET = "Status"
STATUS_ROW = 2                      # the single data row of the status table


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def header_of(parts, sheet_part) -> list[str]:
    """Row 1 of a worksheet, as a list of column headers."""
    x = parts[sheet_part].decode()
    row1 = re.search(r'<row r="1"[^>]*>(.*?)</row>', x, re.S)
    if not row1:
        return []
    out = {}
    for m in re.finditer(r'<c r="([A-Z]+)1"[^>]*?>(?:<is><t>([^<]*)</t></is>|<v>([^<]*)</v>)',
                         row1.group(1)):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


def sheet_parts(parts):
    wb = parts["xl/workbook.xml"].decode()
    rels = parts["xl/_rels/workbook.xml.rels"].decode()
    rm = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"', rels))
    out = {}
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="rId(\d+)"', wb):
        out[m.group(1)] = "xl/" + rm[m.group(2)].lstrip("/")
    return out


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    sp = sheet_parts(parts)

    # --- where are the w1..wN labels on the Status sheet? ------------------------
    shdr = header_of(parts, sp[STATUS_SHEET])
    label_cell = {}
    for letter, name in shdr.items():
        m = re.fullmatch(r"w(\d+)", str(name or ""))
        if m:
            label_cell[int(m.group(1))] = f"${letter}${STATUS_ROW}"
    missing = [i for i in range(1, cfg.WINDOW_YEARS + 1) if i not in label_cell]
    if missing:
        raise SystemExit(f"status sheet has no w{missing} label columns — "
                         f"run build_status.py and add_power_queries.py first")

    for num, (sheet, country) in CHARTS.items():
        hdr = header_of(parts, sp[sheet])
        # locate this country's window columns by NAME, never by position
        wcols = {}
        for letter, name in hdr.items():
            for i in range(1, cfg.WINDOW_YEARS + 1):
                if name == cfg.wcol(country, i):
                    wcols[i] = letter
        if len(wcols) != cfg.WINDOW_YEARS:
            raise SystemExit(f"{sheet}: found {len(wcols)} of {cfg.WINDOW_YEARS} "
                             f"{country}_w* columns")

        p = f"xl/charts/chart{num}.xml"
        x = parts[p].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", x, re.S)
        if len(sers) != cfg.WINDOW_YEARS:
            raise SystemExit(f"chart{num}: {len(sers)} series, expected {cfg.WINDOW_YEARS} "
                             f"— the window and the chart must match exactly, or the "
                             f"series would silently plot the wrong year")

        # the row range each series already reads (the curated technology block)
        rng = re.search(r"<c:val>.*?<c:f>[^!]+!\$[A-Z]+\$(\d+):\$[A-Z]+\$(\d+)", sers[0], re.S)
        r0, r1 = rng.group(1), rng.group(2)

        for i, s in enumerate(sers, start=1):
            letter = wcols[i]
            new = s
            # name -> the rolling label cell (cache the current year so the pre-refresh
            # preview reads correctly too)
            new = re.sub(
                r"<c:tx>.*?</c:tx>",
                f'<c:tx><c:strRef><c:f>{STATUS_SHEET}!{label_cell[i]}</c:f>'
                f'<c:strCache><c:ptCount val="1"/></c:strCache></c:strRef></c:tx>',
                new, count=1, flags=re.S)
            # values -> this country's window column, same rows as before
            new = re.sub(r"(<c:val>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{sheet}!${letter}${r0}:${letter}${r1}\g<2>",
                         new, count=1, flags=re.S)
            x = x.replace(s, new, 1)

        parts[p] = x.encode()
        cols = ", ".join(wcols[i] for i in sorted(wcols))
        print(f"  chart{num:<3} {country} -> {sheet}!{cols} rows {r0}-{r1}; "
              f"names -> {STATUS_SHEET}!{label_cell[1]}..{label_cell[cfg.WINDOW_YEARS]}")

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  rolling window applied — charts gain a year on refresh, no rebuild")


if __name__ == "__main__":
    main()
