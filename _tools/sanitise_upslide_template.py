"""sanitise_upslide_template.py — remove the personal destinations from a linked workbook.

WHY. The linked workbook has to be kept somewhere so a rebuild can be merged into it, and
the obvious place is beside the tool. That repository is PUBLIC, and the workbook carries a
colleague's personal SharePoint URL 37 times over, plus an internal H: drive path.

WHAT IS SAFE TO CHANGE. Each UpSlide marker is a hidden shape whose `descr` reads

    _EXPORT31_2_<id>_<id>_json{"DestinationType":"Powerpoint",
                              "PowerPointDestination":{"FilePath":"...","SlideId":...}}

The identity UpSlide matches on is the `_EXPORT31_2_<id>_<id>` prefix; the JSON is metadata
about where the chart was last exported TO. Rewriting FilePath leaves the prefix, the
DestinationType and the SlideId untouched, so the PowerPoint side still finds its
counterpart by id.

⚠ UNVERIFIED, AND ONLY THE TEAM CAN VERIFY IT. UpSlide runs on Windows and is not available
here, so the claim above is read off the file's own structure rather than tested. What IS
tested is that the sanitised workbook opens in Excel with no repair prompt and that nothing
outside the FilePath strings changed. If a re-export from the sanitised copy turns out to
need the real path, the answer is to keep the template out of the public repository instead,
which costs nothing.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile

MARKER = re.compile(r'(name="UpSlideExportSave"\s+descr=")([^"]*)(")')


def rewrite(descr_escaped: str, to: str) -> tuple[str, bool]:
    d = html.unescape(descr_escaped)
    m = re.search(r'("FilePath":")([^"]*)(")', d)
    if not m:
        return descr_escaped, False
    new = d[:m.start(2)] + to.replace("\\", "\\\\") + d[m.end(2):]
    return html.escape(new, quote=True), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--to", default="Utilities_Monthly_Product.pptx",
                    help="what every FilePath becomes (default: the bare file name)")
    a = ap.parse_args()

    z = zipfile.ZipFile(a.src)
    parts = {n: z.read(n) for n in z.namelist()}
    order = list(parts)
    z.close()

    changed = touched = 0
    for n in list(parts):
        if not (n.startswith("xl/drawings/drawing") and n.endswith(".xml")):
            continue
        x = parts[n].decode()
        if "UpSlideExportSave" not in x:
            continue
        out, hits = [], 0
        pos = 0
        for m in MARKER.finditer(x):
            new_descr, did = rewrite(m.group(2), a.to)
            out.append(x[pos:m.start()] + m.group(1) + new_descr + m.group(3))
            pos = m.end()
            hits += did
        if hits:
            parts[n] = ("".join(out) + x[pos:]).encode()
            changed += hits
            touched += 1

    # WHERE THE FILE WAS LAST SAVED, which is not only in the markers. Excel records the
    # containing folder in workbook.xml as <x15ac:absPath url="..."/>, and on this workbook
    # that is a UNC path naming an internal file server and the whole directory tree beneath
    # it. It is informational - Excel uses it to resolve relative links and rewrites it on
    # the next save - so removing it costs nothing and it would otherwise have been published
    # alongside everything the markers gave up.
    wbx = parts["xl/workbook.xml"].decode()
    n_abs = len(re.findall(r"<x15ac:absPath\b[^>]*/>", wbx))
    if n_abs:
        wbx = re.sub(r"<x15ac:absPath\b[^>]*/>", "", wbx)
        parts["xl/workbook.xml"] = wbx.encode()

    import xml.etree.ElementTree as ET
    for n, blob in parts.items():
        if n.endswith((".xml", ".rels")):
            try:
                ET.fromstring(blob)
            except Exception as ex:                        # noqa: BLE001
                print(f"REFUSING TO WRITE - {n} would not parse: {ex}", file=sys.stderr)
                return 1

    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])

    # Nothing outside the FilePath strings may have moved.
    src = zipfile.ZipFile(a.src)
    dst = zipfile.ZipFile(a.out)
    moved = [n for n in src.namelist()
             if src.read(n) != dst.read(n) and not n.startswith("xl/drawings/drawing")
             and n != "xl/workbook.xml"]
    print(f"rewrote {changed} destination path(s) across {touched} marker drawing(s) -> {a.to!r}")
    print(f"removed {n_abs} absPath record(s) of where the file was last saved")
    print(f"parts changed outside the marker drawings: {len(moved)}"
          + (f"  {moved[:4]}" if moved else "  (none, as intended)"))
    LEAKS = (b"sharepoint.com", b"personal/", b"lon01fs01", b"Oils", b"H:\\\\")
    left = [n for n in dst.namelist() if any(k in dst.read(n) for k in LEAKS)]
    print(f"parts still naming a person, a server or an internal path: {len(left)}"
          + (f"  {left[:3]}" if left else "  (none)"))
    return 1 if left or moved else 0


if __name__ == "__main__":
    sys.exit(main())
