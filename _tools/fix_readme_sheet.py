"""Rewrite READ_ME_FIRST's header: drop the stale setup steps, add the status-page link.

The tab shipped with the ORIGINAL build instructions — "add ONE Power Query … Data > Get
Data > From Web > … Load To …" — for queries that have all been wired inside the file for
weeks. It contradicted `WORK_MACHINE_SETUP.md`'s opening line ("there is no setup left"),
and it is the first thing a reader sees, so it was the most misleading page in the
workbook: it described work nobody needs to do, in a file where doing it would break
things (typing into a Power Query load target detaches charts on the next refresh).

Replaced with what a reader actually needs: one clickable link to the public status page,
and the one rule that is not obvious — the numbers refresh themselves, the CHARTS do not.

The URL table below row 9 is deliberately kept. It is genuine reference (which tab is fed
by which published CSV) and is what someone would need to rebuild a connection by hand.

Runs after add_power_queries.py; before build_frozen_excel/build_deck, which read by name.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
SHEET = "READ_ME_FIRST"
STATUS_URL = "https://power-price-data.fredhill.workers.dev"

RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# (row, text, style id) — style ids are the ones already in this sheet:
#   1 = title, 3 = bold-ish lead, 2 = plain, 4 = indented step, 5 = note
HEADER = [
    (1, "Power Price Data — live workbook", 1),
    (3, "Everything is already set up. There is nothing to install, wire or run.", 3),
    (4, "The numbers refresh themselves from GitHub every time you open this file.", 2),
    (5, "Status page — last update, next update, downloads, refresh now:", 4),
    (6, STATUS_URL, 4),
    (7, "If a CHART is wrong (a missing year, a technology that should not be there), "
        "download a fresh workbook from that page — refreshing can never change a chart, "
        "only the numbers inside it.", 5),
    (8, "Data freshness is shown on the Status tab (the first tab).", 5),
]


def esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    wb = parts["xl/workbook.xml"].decode()
    rels = parts["xl/_rels/workbook.xml.rels"].decode()
    relmap = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"', rels))
    m = re.search(rf'<sheet name="{SHEET}"[^>]*r:id="rId(\d+)"', wb)
    if not m:
        print(f"  {SHEET} not found — skipping")
        return
    spart = "xl/" + relmap[m.group(1)].lstrip("/")
    x = parts[spart].decode()

    # --- replace rows 1..8 with inline strings (no sharedStrings surgery) ---------
    for r, text, style in HEADER:
        cell = (f'<row r="{r}" spans="1:3">'
                f'<c r="A{r}" s="{style}" t="inlineStr"><is><t>{esc(text)}</t></is></c></row>')
        pat = rf'<row r="{r}"[^>]*>.*?</row>'
        if re.search(pat, x, re.S):
            x = re.sub(pat, cell, x, count=1, flags=re.S)
        else:
            x = x.replace("<sheetData>", "<sheetData>" + cell, 1)

    # --- make A6 a real hyperlink -------------------------------------------------
    srels_path = spart.replace("worksheets/", "worksheets/_rels/") + ".rels"
    srels = parts[srels_path].decode()
    used = {int(n) for n in re.findall(r'Id="rId(\d+)"', srels)}
    rid = f"rId{max(used) + 1 if used else 1}"

    if STATUS_URL not in srels:
        srels = srels.replace(
            "</Relationships>",
            f'<Relationship Id="{rid}" Type="{RNS}/hyperlink" '
            f'Target="{STATUS_URL}" TargetMode="External"/></Relationships>')
        parts[srels_path] = srels.encode()

    # drop any previous A6 link, then add ours
    x = re.sub(r'<hyperlink ref="A6"[^/]*/>', "", x)
    if "<hyperlinks>" in x:
        x = x.replace("<hyperlinks>", f'<hyperlinks><hyperlink ref="A6" r:id="{rid}"/>', 1)
    else:
        # hyperlinks must sit directly after sheetData in CT_Worksheet
        x = x.replace("</sheetData>",
                      f'</sheetData><hyperlinks><hyperlink ref="A6" r:id="{rid}"/></hyperlinks>', 1)

    parts[spart] = x.encode()

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  {SHEET}: replaced the stale setup steps; A6 -> {STATUS_URL}")


if __name__ == "__main__":
    main()
