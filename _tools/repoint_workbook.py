#!/usr/bin/env python3
"""Repoint a workbook's Power Query sources at a new GitHub owner.

Written 2026-08-17, after the repo moved to `Power-Utilities-team`. The live workbook still named the
old personal account, and worked only because GitHub redirects a transferred repo. That redirect is
the risk: delete the old account and its username is freed, so anyone who registers it and creates a
repo of the same name would have this workbook quietly pulling THEIR data. No error, just different
numbers.

TWO PLACES HOLD URLS, and the second one is the one that matters:

  * the Status sheet's documentation table, in `xl/sharedStrings.xml` and a worksheet part. Plain
    text, cosmetic, tells a reader which CSV feeds which tab.
  * `Formulas/Section1.m`, the actual Power Query code, DEFLATE-compressed inside a base64 blob
    inside a UTF-16 XML part (`customXml/item1.xml`, the [MS-QDEFF] DataMashup layout). This is
    where `Web.Contents("...")` actually points.

The first version of this script patched only the first and reported "0 stale references remaining",
which was worse than useless: it would have left every live query on the old owner while saying the
job was done. If a search of the raw parts finds nothing, that is not evidence of nothing.

Deliberately NOT openpyxl, which drops charts and metadata and leaves Excel refusing the file. Parts
are edited as bytes and `xlsx_surgery.part_parity_check` proves nothing was lost.

    ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/repoint_workbook.py" <file.xlsx>
    ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/repoint_workbook.py" <file.xlsx> --apply

Dry run by default. With --apply it writes `<name>.repointed.xlsx` beside the original and leaves the
file you gave it untouched, because a live model is not something to overwrite in place.
"""
from __future__ import annotations
import base64
import io
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "tools"))
import xlsx_surgery  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = "power-price-data"
HOST = "raw.githubusercontent.com"
MASHUP_PART = "customXml/item1.xml"

PAT_B = re.compile(rf"{re.escape(HOST)}/([A-Za-z0-9-]+)/{re.escape(REPO)}".encode())
PAT_S = re.compile(rf"{re.escape(HOST)}/([A-Za-z0-9-]+)/{re.escape(REPO)}")


def current_owner() -> str:
    """The owner the project points at now, read from the Worker rather than hardcoded."""
    w = (ROOT / "_tools" / "refresh-page" / "worker.js").read_text(encoding="utf-8")
    m = re.search(r'const OWNER = "([^"]+)"', w)
    if not m:
        raise SystemExit("could not read OWNER from _tools/refresh-page/worker.js")
    return m.group(1)


def read_mashup(item1: bytes):
    """-> (version, package_zip_bytes, trailer, section1_text). Raises if the layout is unexpected."""
    text = item1.decode("utf-16" if item1[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf8")
    blob = base64.b64decode(ET.fromstring(text).text)
    version, = struct.unpack_from("<I", blob, 0)
    pkg_len, = struct.unpack_from("<I", blob, 4)
    pkg = blob[8:8 + pkg_len]
    trailer = blob[8 + pkg_len:]          # permissions, metadata, bindings: carried through verbatim
    zin = zipfile.ZipFile(io.BytesIO(pkg))
    if "Formulas/Section1.m" not in zin.namelist():
        raise SystemExit(f"{MASHUP_PART}: no Formulas/Section1.m, so the query code cannot be read")
    return version, pkg, trailer, zin.read("Formulas/Section1.m").decode("utf8")


def write_mashup(version, pkg, trailer, new_section: str) -> bytes:
    """Rebuild item1.xml with Section1.m replaced. Same layout the project's own writer uses."""
    zin = zipfile.ZipFile(io.BytesIO(pkg))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zin.namelist():
            data = new_section.encode("utf8") if n == "Formulas/Section1.m" else zin.read(n)
            zo.writestr(n, data)
    newpkg = buf.getvalue()
    out = struct.pack("<I", version) + struct.pack("<I", len(newpkg)) + newpkg + trailer
    xml = ('<DataMashup xmlns="http://schemas.microsoft.com/DataMashup" sqmid="0">'
           + base64.b64encode(out).decode() + "</DataMashup>")
    return ('<?xml version="1.0" encoding="utf-16"?>' + xml).encode("utf-16")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if len(args) != 1:
        print(f"usage: {Path(__file__).name} <file.xlsx> [--apply]", file=sys.stderr)
        return 2
    src = Path(args[0]).expanduser()
    if not src.is_file():
        print(f"no such file: {src}", file=sys.stderr)
        return 2

    new = current_owner()
    good_b, good_s = f"{HOST}/{new}/{REPO}".encode(), f"{HOST}/{new}/{REPO}"

    zin = zipfile.ZipFile(src)
    if MASHUP_PART not in zin.namelist():
        raise SystemExit(f"{src.name} has no {MASHUP_PART}: this is not one of the linked workbooks")

    # 1. the live query code
    version, pkg, trailer, section = read_mashup(zin.read(MASHUP_PART))
    q_stale = [o for o in PAT_S.findall(section) if o != new]
    print(f"  Formulas/Section1.m (the live queries): {len(PAT_S.findall(section))} URL(s), "
          f"{len(q_stale)} stale, owners {sorted(set(q_stale)) or 'none'}")

    # 2. the visible documentation table
    visible = {}
    for info in zin.infolist():
        if info.filename == MASHUP_PART:
            continue
        b = zin.read(info.filename)
        stale = [o for o in (m.group(1).decode() for m in PAT_B.finditer(b)) if o != new]
        if stale:
            visible[info.filename] = len(stale)
            print(f"  {info.filename} (documentation): {len(stale)} stale URL(s)")

    total = len(q_stale) + sum(visible.values())
    if not total:
        print(f"\nnothing to do: everything already names {new}")
        return 0
    print(f"\n{total} stale reference(s) -> {new}{'  — WRITING' if apply else '  — dry run'}")
    if not apply:
        return 0

    dst = src.with_suffix(".repointed.xlsx")
    new_section = PAT_S.sub(good_s, section)
    new_item1 = write_mashup(version, pkg, trailer, new_section)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename == MASHUP_PART:
                zout.writestr(info, new_item1)
            elif info.filename in visible:
                zout.writestr(info, PAT_B.sub(good_b, zin.read(info.filename)))
            else:
                zout.writestr(info, zin.read(info.filename))
    zin.close()

    xlsx_surgery.part_parity_check(src, dst, allow_drop=())

    # Verify by RE-READING the result, including re-decoding the mashup. Checking the bytes we just
    # wrote against the substitution we just made would prove nothing.
    zchk = zipfile.ZipFile(dst)
    _, _, _, chk_section = read_mashup(zchk.read(MASHUP_PART))
    left_q = [o for o in PAT_S.findall(chk_section) if o != new]
    left_v = sum(len([o for o in (m.group(1).decode() for m in PAT_B.finditer(zchk.read(n)))
                      if o != new])
                 for n in zchk.namelist() if n != MASHUP_PART)
    print(f"wrote {dst}")
    print(f"  part parity: OK (every part preserved)")
    print(f"  stale left in the live queries: {len(left_q)}")
    print(f"  stale left in the documentation: {left_v}")
    print(f"  queries now pointing at {new}: {len([o for o in PAT_S.findall(chk_section) if o == new])}")
    return 0 if not left_q and not left_v else 1


if __name__ == "__main__":
    sys.exit(main())
