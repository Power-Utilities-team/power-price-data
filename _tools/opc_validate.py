"""Validate the OPC package the way Excel does, not the way a parser does.

Every check in check_consistency inspects parts INDIVIDUALLY. That is why three separate
faults shipped past it on 2026-07-31, each of which made Excel offer to Recover (which
strips Power Query) while every part was perfectly well-formed XML:

  1. two new worksheets with no [Content_Types] Override — they silently inherited the
     generic `Default xml -> application/xml`, i.e. the WRONG type;
  2. a chart series name whose strCache declared ptCount=1 with zero <c:pt> children;
  3. a data-only worksheet still carrying <drawing r:id="rId1"/> from the template, where
     rId1 was now the TABLE relationship — a reference of the wrong TYPE.

None of those is a parse error. All three are package-level: a part, a declaration or a
relationship that is individually valid and collectively wrong. This checks the joins.

Run standalone (`python opc_validate.py [file]`) or import `validate()`.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
import zipfile

RTYPE = {
    "drawing": "drawing",
    "table": "table",
    "worksheet": "worksheet",
    "chart": "chart",
}


def validate(path: str) -> list[str]:
    errs: list[str] = []
    z = zipfile.ZipFile(path)
    names = set(z.namelist())

    ct = z.read("[Content_Types].xml").decode()
    overrides = dict(re.findall(r'PartName="([^"]+)"\s+ContentType="([^"]+)"', ct))
    defaults = dict(re.findall(r'Extension="([^"]+)"\s+ContentType="([^"]+)"', ct))

    # --- 1. typed parts must carry their own Override -----------------------------
    for n in sorted(names):
        if not n.endswith(".xml"):
            continue
        if n.startswith(("xl/worksheets/", "xl/charts/", "xl/drawings/", "xl/tables/")) \
                and "/_rels/" not in n:
            if ("/" + n) not in overrides:
                errs.append(f"{n}: no Content_Types Override (falls back to "
                            f"'{defaults.get('xml', '?')}' — Excel will offer Recover)")

    # --- 2. every relationship target must exist ----------------------------------
    rel_of: dict[str, dict[str, tuple[str, str]]] = {}
    for n in sorted(names):
        if not n.endswith(".rels"):
            continue
        base = posixpath.dirname(posixpath.dirname(n))          # part's own directory
        owner = posixpath.join(base, posixpath.basename(n)[:-5]) if base else \
            posixpath.basename(n)[:-5]
        rels = {}
        for rid, rtype, tgt, mode in re.findall(
                r'Id="([^"]+)"\s+Type="([^"]+)"\s+Target="([^"]+)"(?:\s+TargetMode="([^"]+)")?',
                z.read(n).decode()):
            rels[rid] = (rtype.rsplit("/", 1)[-1], tgt)
            if mode == "External":
                continue
            resolved = posixpath.normpath(posixpath.join(base, tgt))
            if resolved not in names:
                errs.append(f"{n}: {rid} -> {tgt} does not exist in the package")
        rel_of[owner] = rels

    # --- 3. r:id references inside a part must resolve, with the RIGHT type --------
    for n in sorted(names):
        if not n.startswith("xl/worksheets/") or not n.endswith(".xml") or "/_rels/" in n:
            continue
        x = z.read(n).decode(errors="replace")
        rels = rel_of.get(n, {})
        for elem, rid in re.findall(r'<(drawing|tablePart|legacyDrawing)[^>]*r:id="([^"]+)"', x):
            if rid not in rels:
                errs.append(f"{n}: <{elem}> references {rid}, which has no relationship")
                continue
            want = {"drawing": "drawing", "tablePart": "table",
                    "legacyDrawing": "vmlDrawing"}[elem]
            got = rels[rid][0]
            if got != want:
                errs.append(f"{n}: <{elem}> points at {rid}, but that relationship is a "
                            f"'{got}', not a '{want}' — Excel will offer Recover")

    # --- 4. chart caches must be internally consistent -----------------------------
    for n in sorted(names):
        if not re.match(r"xl/charts/chart\d+\.xml$", n):
            continue
        x = z.read(n).decode()
        for cache in re.findall(r"<c:(?:str|num)Cache>.*?</c:(?:str|num)Cache>", x, re.S):
            m = re.search(r'<c:ptCount val="(\d+)"/>', cache)
            if not m:
                continue
            declared = int(m.group(1))
            actual = len(re.findall(r"<c:pt\s", cache))
            # a cache may legitimately omit blanks, but must never claim points and have none
            if declared > 0 and actual == 0:
                errs.append(f"{n}: a cache declares ptCount={declared} but contains no "
                            f"<c:pt> — Excel will offer Recover")
    return errs


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "outputs")
    # EVERY deliverable, not just the live workbook. Checking only HourlyPowerData.xlsx
    # is how three dangling table relationships shipped in the FROZEN workbook on
    # 2026-07-31 — the PQ strip deleted the tables and left the sheets pointing at them,
    # and Microsoft's SDK rejected the package while every local check passed, because
    # no local check had ever opened that file.
    paths = sys.argv[1:] or [os.path.join(out, f) for f in (
        "HourlyPowerData.xlsx", "HourlyPowerData_frozen.xlsx")]

    total = 0
    for path in paths:
        if not os.path.exists(path):
            print(f"OPC validate: {os.path.basename(path)} — MISSING")
            total += 1
            continue
        errs = validate(path)
        print(f"OPC validate: {os.path.basename(path)}")
        if not errs:
            print("  PASS — package joins are consistent")
            continue
        for e in errs:
            print("  ✗", e)
        print(f"  {len(errs)} problem(s)")
        total += len(errs)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
