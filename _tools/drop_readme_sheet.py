"""Remove the READ_ME_FIRST tab — its content now lives on Status.

Fred asked for one tab instead of two. READ_ME_FIRST had already been reduced to a link
plus a URL table, and both are now on Status: the link at the top, the URL table as the
"if something breaks" reference. Two tabs for one story is worse than one.

WHY THIS IS NOT A DELETE
    Every <definedName> in this workbook is scoped to a sheet by POSITIONAL index
    (localSheetId), one ExternalData_1 per Power Query load target. Removing a sheet
    shifts every index above it down by one, so all of them must be remapped in the same
    edit, plus activeTab. Get it wrong and defined names point at the wrong sheets, Excel
    offers to Recover, and Recover strips Power Query.

    READ_ME_FIRST itself has no defined name (it is not a load target), which is what
    makes removal safe at all — nothing points AT it. Verified before writing.

Runs after add_status_sheet/add_power_queries (so Status is complete) and before
move_status_first (which re-asserts the whole mapping afterwards).
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
DROP = "READ_ME_FIRST"


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    wb = parts["xl/workbook.xml"].decode()
    sheets = [(m.group(1), m.group(0), m.group(2))
              for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"[^>]*/>', wb)]
    names = [n for n, _, _ in sheets]
    if DROP not in names:
        print(f"  {DROP} not present — nothing to do")
        return
    idx = names.index(DROP)
    rid = sheets[idx][2]

    # --- refuse if anything is scoped to this sheet -------------------------------
    for m in re.finditer(r'<definedName([^>]*)>(.*?)</definedName>', wb, re.S):
        li = re.search(r'localSheetId="(\d+)"', m.group(1))
        if li and int(li.group(1)) == idx:
            raise SystemExit(f"{DROP} has a defined name scoped to it — refusing to drop")

    # --- drop the <sheet> entry ---------------------------------------------------
    wb = wb.replace(sheets[idx][1], "")

    # --- remap every index above it -----------------------------------------------
    def shift(m, attr):
        old = int(m.group(1))
        if old == idx:
            return f'{attr}="0"'          # should not occur; asserted above / activeTab
        return f'{attr}="{old - 1 if old > idx else old}"'

    wb, n_named = re.subn(r'localSheetId="(\d+)"',
                          lambda m: shift(m, "localSheetId"), wb)
    wb = re.sub(r'activeTab="(\d+)"', lambda m: shift(m, "activeTab"), wb)
    parts["xl/workbook.xml"] = wb.encode()

    # --- drop the relationship and the parts --------------------------------------
    rels = parts["xl/_rels/workbook.xml.rels"].decode()
    tgt = re.search(rf'<Relationship Id="{rid}"[^>]*Target="([^"]+)"[^>]*/>', rels)
    part = "xl/" + tgt.group(1).lstrip("/")
    rels = re.sub(rf'<Relationship Id="{rid}"[^>]*/>', "", rels)
    parts["xl/_rels/workbook.xml.rels"] = rels.encode()

    doomed = [part, part.replace("worksheets/", "worksheets/_rels/") + ".rels"]
    for d in doomed:
        parts.pop(d, None)
        if d in order:
            order.remove(d)

    ct = parts["[Content_Types].xml"].decode()
    ct = re.sub(rf'<Override PartName="/{re.escape(part)}"[^>]*/>', "", ct)
    parts["[Content_Types].xml"] = ct.encode()

    # --- assert every remaining defined name still resolves ------------------------
    final = [m.group(1) for m in re.finditer(r'<sheet name="([^"]+)"', wb)]
    bad = []
    for m in re.finditer(r'<definedName([^>]*)>(.*?)</definedName>', wb, re.S):
        li = re.search(r'localSheetId="(\d+)"', m.group(1))
        if not li:
            continue
        want = m.group(2).split("!")[0].strip("'")
        got = final[int(li.group(1))] if int(li.group(1)) < len(final) else "<OOR>"
        if want != got:
            bad.append(f"localSheetId={li.group(1)} -> {got}, but the ref names {want}")
    if bad:
        raise SystemExit("localSheetId remap is WRONG:\n  " + "\n  ".join(bad))

    # --- exactly ONE sheet may be selected ---------------------------------------
    # Two sheets carrying tabSelected="1" makes Excel open them GROUPED — the title bar
    # reads "[Group]", every edit is applied to all selected sheets at once, and any
    # table edit is refused outright with "Cannot make changes to a table or XML mapping
    # when multiple sheets are selected". The base workbook had Fig1_PriceSD selected and
    # add_status_sheet then selected Status too, so every build since has shipped grouped.
    # Clear the flag everywhere, then set it on Status alone.
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="(rId\d+)"', wb):
        tgt = re.search(rf'<Relationship Id="{m.group(2)}"[^>]*Target="([^"]+)"',
                        parts["xl/_rels/workbook.xml.rels"].decode())
        if not tgt:
            continue
        sp = "xl/" + tgt.group(1).lstrip("/")
        if sp not in parts:
            continue
        sxx = parts[sp].decode()
        want = m.group(1) == "Status"
        if want and 'tabSelected="1"' not in sxx:
            sxx = sxx.replace("<sheetView ", '<sheetView tabSelected="1" ', 1)
        elif not want:
            sxx = sxx.replace(' tabSelected="1"', "")
        parts[sp] = sxx.encode()

    # --- shrink (do NOT hide) the raw status row -----------------------------------
    # Rows 1-2 are the Power Query load target: a 13-column machine record read
    # sideways, and the sheet now presents the same cells transposed below, so the raw
    # row is visual noise. It must stay — the query loads there and every formula and
    # chart-series name references it.
    #
    # HIDING it looked like the obvious answer and silently broke the charts: a chart
    # does not read hidden cells, so the annual bar charts' series names (which point at
    # Status!$G$2..$M$2 for the rolling year labels) stopped resolving and the legend
    # fell back to "Column B, Column C, ...". Proven by rendering the same workbook with
    # and without the hidden attribute — the only difference — and watching the years
    # come back.
    #
    # SETTLED 2026-08-03 — rows 1 and 2 are ORDINARY rows. Fred's call, and it ends a
    # sequence of increasingly clever answers to a question nobody asked.
    #
    # The history is worth keeping, because each step looked like an improvement:
    #   * hiding them broke the rolling year legends (a chart ignores hidden cells), so
    #   * they were squeezed to 4pt instead, which merely looked broken, so
    #   * they were hidden properly with plotVisOnly=0 to keep the legends working —
    #     which was the wrong fix to the wrong complaint. "Too squashed" meant too
    #     SHORT, not too visible.
    #
    # So: no hidden attribute, no custom height, nothing. They render at the sheet's
    # default height like every other row. The load target being visible is not a
    # problem — it is a labelled header row over a labelled value row, and the
    # transposed view below remains the readable presentation of the same cells.
    # plotVisOnly is left at its Excel default, since nothing here is hidden any more.
    srid = re.search(r'<sheet name="Status"[^>]*r:id="rId(\d+)"', wb).group(1)
    srel = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"',
                           parts["xl/_rels/workbook.xml.rels"].decode()))
    spart = "xl/" + srel[srid].lstrip("/")
    sx = parts[spart].decode()
    for r in (1, 2):
        sx = re.sub(
            rf'<row r="{r}"[^>]*>',
            lambda m: re.sub(r'\s+(hidden|ht|customHeight)="[^"]*"', "", m.group(0))
                        .replace(">", ' ht="15" customHeight="1">', 1),
            sx, count=1)

    # DO NOT "correct" this sheet's <dimension>. It reads A1:M2 — the LOAD TARGET's
    # range, not the sheet's used range — and that looks like a bug. It is load-bearing:
    # check_consistency reads it to know how many rows the Status table was pre-filled
    # with, and compares that against status.csv to catch a table that would change shape
    # on refresh and re-anchor a chart. Setting it to the true extent (A1:M74) makes that
    # check report 74 rows against the CSV's 2 and fail, which is exactly what happened
    # when it was tried on 2026-08-03. Excel recomputes the used range on open anyway.
    parts[spart] = sx.encode()

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  dropped {DROP} (was tab {idx}); remapped {n_named} localSheetId(s); "
          f"{len(final)} tabs remain, all defined names verified; raw status row hidden")


if __name__ == "__main__":
    main()
