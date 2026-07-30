"""Move the Status sheet to the LEFTMOST tab position.

The workbook already *opens* on Status (activeTab), but it was the 21st tab, so anyone
navigating rather than re-opening had to hunt for it. Leftmost makes the health banner
the first thing in the tab strip as well as the first thing on screen.

WHY THIS NEEDS A SCRIPT, NOT A DRAG IN EXCEL
--------------------------------------------
Every `<definedName>` in this workbook is scoped to a sheet by **positional index**
(`localSheetId`), not by name — 19 of them, one `ExternalData_1` per Power Query load
target. Sheet order IS that index. Moving a sheet from position 20 to position 0 shifts
every other sheet right by one, so all 19 indices must be remapped in the same edit, plus
`activeTab` in bookViews. Get it wrong and the defined names point at the wrong sheets:
Excel then offers to Recover, and Recover strips Power Query — the one failure this
project treats as unacceptable.

This is why Phase 4 deliberately APPENDED its new tabs at the end (see current-status.md:
"New tabs APPENDED at end -> every existing localSheetId index untouched"). Reordering is
the case that rule was avoiding, so it is done here in the build, deterministically, and
asserted afterwards — never by hand.

Runs AFTER add_power_queries.py (which creates the Status defined name) and before the
frozen/deck builds, which reference sheets by NAME and are therefore order-independent.
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
SHEET = "Status"


def sheet_order(wb_xml: str):
    """[(name, full <sheet .../> tag)] in document (tab) order."""
    return [(m.group(1), m.group(0))
            for m in re.finditer(r'<sheet name="([^"]+)"[^>]*/>', wb_xml)]


def main():
    with zipfile.ZipFile(WB) as z:
        order = z.namelist()
        parts = {n: z.read(n) for n in order}

    wb = parts["xl/workbook.xml"].decode()
    sheets = sheet_order(wb)
    names = [n for n, _ in sheets]
    if SHEET not in names:
        raise SystemExit(f"{SHEET} sheet not found")
    old_idx = names.index(SHEET)
    if old_idx == 0:
        print(f"  {SHEET} already leftmost — nothing to do")
        return

    # --- 1. move the <sheet> element to the front ---------------------------------
    tag = dict(sheets)[SHEET]
    block = re.search(r"<sheets>.*?</sheets>", wb, re.S).group(0)
    new_block = block.replace(tag, "")                       # remove from old slot
    new_block = new_block.replace("<sheets>", "<sheets>" + tag, 1)   # reinsert first
    wb = wb.replace(block, new_block)

    # --- 2. remap every localSheetId ----------------------------------------------
    # Everything that sat before Status shifts right by one; Status itself becomes 0.
    def remap(m):
        old = int(m.group(1))
        new = 0 if old == old_idx else (old + 1 if old < old_idx else old)
        return f'localSheetId="{new}"'

    wb, n_remapped = re.subn(r'localSheetId="(\d+)"', remap, wb)

    # --- 3. activeTab follows the same rule ---------------------------------------
    def remap_active(m):
        old = int(m.group(1))
        new = 0 if old == old_idx else (old + 1 if old < old_idx else old)
        return f'activeTab="{new}"'

    wb = re.sub(r'activeTab="(\d+)"', remap_active, wb)
    parts["xl/workbook.xml"] = wb.encode()

    # --- 4. assert before writing --------------------------------------------------
    check = sheet_order(wb)
    assert check[0][0] == SHEET, f"reorder failed: first tab is {check[0][0]}"
    assert len(check) == len(sheets), "sheet lost during reorder"
    assert sorted(n for n, _ in check) == sorted(names), "sheet set changed"

    # every defined name must still name the sheet its index points at
    idx_to_name = {i: n for i, (n, _) in enumerate(check)}
    bad = []
    for m in re.finditer(r'<definedName([^>]*)>(.*?)</definedName>', wb, re.S):
        li = re.search(r'localSheetId="(\d+)"', m.group(1))
        if not li:
            continue
        target = idx_to_name.get(int(li.group(1)))
        ref_sheet = m.group(2).split("!")[0].strip("'")
        if target != ref_sheet:
            bad.append(f"localSheetId={li.group(1)} -> {target}, but ref is {ref_sheet}")
    if bad:
        raise SystemExit("localSheetId remap is WRONG:\n  " + "\n  ".join(bad))

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  moved {SHEET} {old_idx} -> 0; remapped {n_remapped} localSheetId(s); "
          f"all defined names verified against sheet order")
    print(f"  tab order now: {', '.join(n for n, _ in check[:4])}, …")


if __name__ == "__main__":
    main()
