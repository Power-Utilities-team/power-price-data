"""Rewrite the workbook's VISIBLE references to a GitHub owner that has moved.

The EXCEL_SETUP tab prints the raw URL each query reads, and one cell hyperlinks to the status
record. When a repository is transferred, GitHub's owner-rename redirect keeps the old spelling
working, so nothing breaks and nothing warns: the tab quietly goes on displaying an owner that
no longer holds the repository. The redirect is also not a guarantee, because it stops the
moment anyone creates a new repository at the old path.

This touches only what the tab SHOWS. It does NOT rewrite the Power Query connections, whose M
code is compressed inside `customXml/item1.xml`. Fred's call, 2026-08-27: fix the visible text,
and leave the connections alone while refresh demonstrably works.

Surgical, on the zip parts, because openpyxl silently drops charts, comments and metadata and
Excel then refuses to open the file.

    python3 repoint_owner.py IN.xlsx OUT.xlsx old-owner/repo new-owner/repo
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# The only parts that carry displayed text or a hyperlink target. Deliberately NOT a scan of
# every part: a blanket search-and-replace across a workbook is how chart caches and query
# definitions get rewritten by accident.
TOUCH = ("xl/sharedStrings.xml", "xl/worksheets/_rels/sheet1.xml.rels")


def repoint(src: Path, dst: Path, old: str, new: str):
    """Returns ({part: references rewritten}, references to `old` still left anywhere)."""
    with zipfile.ZipFile(src) as z:
        order = z.namelist()
        parts = {n: z.read(n) for n in order}

    counts = {}
    for name in TOUCH:
        if name not in parts:
            continue
        text = parts[name].decode("utf-8")
        n = text.count(old)
        if n:
            parts[name] = text.replace(old, new).encode("utf-8")
            counts[name] = n

    left = sum(v.decode("utf-8", "ignore").count(old)
               for k, v in parts.items() if k.endswith((".xml", ".rels")))

    # Fixed 1980 timestamp so two builds of the same input are byte-identical and comparable
    # by checksum, the same rule merge_into_linked.py writes under.
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
        for name in order:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            out.writestr(info, parts[name])
    return counts, left


def parse_gate(path: Path):
    """Every XML part must still parse. Cheap, and it is what Excel checks first."""
    bad = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                try:
                    ET.fromstring(z.read(n))
                except Exception as e:
                    bad.append((n, str(e)[:60]))
    return bad


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    src, dst, old, new = Path(argv[1]), Path(argv[2]), argv[3], argv[4]
    counts, left = repoint(src, dst, old, new)
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v} reference(s) repointed")
    if not counts:
        print(f"  nothing to do: no visible reference to {old}")
    print(f"  references to the old owner left in any text part: {left}")
    bad = parse_gate(dst)
    print(f"  parse gate: {'PASS' if not bad else 'FAIL ' + str(bad[:3])}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
