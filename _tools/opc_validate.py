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

    # EVERY r:id INSIDE A PART MUST RESOLVE IN THAT PART'S OWN .rels.
    #
    # Added 2026-08-25, after a build shipped 65 charts each carrying
    # <c:userShapes r:id="rId1"/> with no chart .rels file at all. Excel answered with
    # "We found a problem with some content ... recover?", and recovering strips Power
    # Query. Every check in this file passed: the XML was well-formed, every part was
    # declared in [Content_Types].xml, and the package-level joins were consistent —
    # because nothing looked INSIDE a part for a relationship id and asked whether the
    # part it points at exists. A reference to a part that is not there is invisible from
    # the outside and fatal from the inside.
    for n in sorted(names):
        if not n.endswith((".xml", ".rels")) or n.endswith(".rels"):
            continue
        try:
            body = z.read(n).decode("utf-8", "replace")
        except KeyError:
            continue
        used = set(re.findall(r'r:(?:id|embed|link|pict)="(rId\d+)"', body))
        if not used:
            continue
        d, base = os.path.split(n)
        relpath = f"{d}/_rels/{base}.rels"
        have = set()
        if relpath in names:
            have = set(re.findall(r'Id="(rId\d+)"', z.read(relpath).decode("utf-8", "replace")))
        missing = sorted(used - have)
        if missing:
            errs.append(f"{n}: relationship id(s) {', '.join(missing)} do not resolve"
                        f"{' (no .rels file at all)' if relpath not in names else ''}"
                        f" — Excel will offer Recover")

    # CHILD ORDER INSIDE A CHART REFERENCE. CT_NumRef, CT_StrRef and CT_MultiLvlStrRef are
    # a schema SEQUENCE: <c:f>, then the optional cache, then the optional <c:extLst>.
    # Excel accepts any order, so a file that gets this wrong opens, draws correctly, and
    # looks completely healthy on a Mac. The strict Open XML validator rejects it, and
    # that validator runs on the Windows CI leg AFTER a full six-market fetch and build
    # have already been paid for. On 2026-08-25 that cost a whole run: 14 errors, every
    # one of them an <c:extLst> ahead of its <c:f>, inherited from a hand-built source
    # workbook through an extracted chart template. Checking it here means the answer
    # arrives in seconds on the machine doing the work.
    for n in names:
        if not re.match(r"xl/charts/chart\d+\.xml$", n):
            continue
        body = z.read(n).decode("utf-8", "replace")
        bad = len(re.findall(r"<c:(?:num|str|multiLvlStr)Ref><c:extLst>", body))
        if bad:
            errs.append(f"{n}: {bad} chart reference(s) put <c:extLst> before <c:f> — "
                        f"Excel tolerates it but the Open XML schema does not, so this "
                        f"passes every check here and fails the Windows validate leg")

    # THE SAME CLASS, GENERALISED. The extLst fault above is one instance of a rule that
    # holds throughout DrawingML: these elements are schema SEQUENCES, so their children
    # must appear in a fixed order. Excel reads them in any order and renders correctly,
    # which is exactly why this survives every local check and every human looking at the
    # file. restyle_charts already carries the authoritative orders, because it has to
    # INSERT into these elements correctly; reusing them here means the checker and the
    # writer cannot disagree about what the order is.
    #
    # Deliberately conservative: an element is only flagged when TWO of its children are
    # both known to the order list and appear the wrong way round. An unrecognised child
    # is skipped rather than guessed at, so this reports faults instead of noise.
    try:
        import restyle_charts as _rs
        ORDERS = {"chartSpace": _rs.ORDER_SPACE, "chart": _rs.ORDER_CHART,
                  "legend": _rs.ORDER_LEGEND, "valAx": _rs.ORDER_AXIS,
                  "catAx": _rs.ORDER_AXIS, "dateAx": _rs.ORDER_AXIS,
                  "serAx": _rs.ORDER_AXIS}
        from lxml import etree as _et
    except Exception:                                  # noqa: BLE001
        ORDERS = None
    if ORDERS:
        for n in names:
            if not re.match(r"xl/charts/chart\d+\.xml$", n):
                continue
            try:
                root = _et.fromstring(z.read(n))
            except Exception:                          # noqa: BLE001
                continue
            for el in root.iter():
                ln = _et.QName(el).localname
                order = ORDERS.get(ln)
                if not order:
                    continue
                seen = [(_et.QName(c).localname, i) for i, c in enumerate(el)
                        if _et.QName(c).localname in order]
                for (a, _), (b, _) in zip(seen, seen[1:]):
                    if order.index(a) > order.index(b):
                        errs.append(f"{n}: inside <c:{ln}>, <c:{a}> precedes <c:{b}> but "
                                    f"the schema orders them the other way — Excel "
                                    f"renders it, the Open XML validator rejects it")
                        break
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
