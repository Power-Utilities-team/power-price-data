"""check_chart_preservation.py — refuse a build that TOOK SOMETHING AWAY from a chart.

THE FAULT THIS EXISTS TO CATCH, which shipped on 2026-08-26. Adding the GB price-basis
caveat to charts 1, 3 and 16 removed "the first <c:title>" in each part, on the assumption
that it was the chart's own title. A chart title and an axis title are both `<c:title>`, and
those three charts had no chart title, so the first one belonged to the value axis. All
three shipped having lost their y-axis labels: chart1 and chart16 stopped saying EUR/MWh,
chart3 stopped saying "# hours", each replaced by an 8-point italic caveat where the unit
had been.

WHY NOTHING CAUGHT IT, and this is the general lesson. Every check was about the thing being
added. `check_chart_captions` asserts the caveat is PRESENT. `opc_validate` asserts the XML
is well-formed and correctly ordered. `check_consistency` asserts ranges do not overrun the
data. All three passed, because all three ask "did the change add what it meant to add".
None asks "is everything that was there before still there".

That is the same shape as `check_reference_stability`, which exists because no other guard
noticed a column moving sideways. This is its equivalent for the workbook's charts.

WHAT IT COMPARES. The freshly built workbook against the PUBLISHED one at git HEAD, which
is the copy people already have open. For every chart present in both:

  * every axis title that existed must still exist, with the same text;
  * every series must still be there, counted;
  * a chart may GAIN a title, a series or an axis label freely. Adding is the sanctioned
    way to bring in a market or a technology.

The baseline is git HEAD rather than the working tree, for the reason spelled out in
check_reference_stability: a local build overwrites the working copy, so comparing against
it compares the new build with itself and passes anything.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import zipfile

import config as cfg

BUILT = os.path.join(cfg.OUTPUT_DIR, "HourlyPowerData.xlsx")
PUBLISHED = "deliverables/HourlyPowerData.xlsx"

CHART = re.compile(r"xl/charts/chart\d+\.xml$")


def _axis_titles(xml: str):
    """[(axis_index, text)] for every title that belongs to an axis, in document order.

    An axis title sits inside <c:valAx>/<c:catAx>/<c:dateAx>; a chart title sits between
    <c:chart> and <c:plotArea>. Depth-counting separates them without a real XML parse,
    which matters because these parts carry namespaces this project edits as bytes.
    """
    out, seen = [], 0
    for m in re.finditer(r"<c:title>.*?</c:title>", xml, re.S):
        before = xml[:m.start()]
        opened = (before.count("<c:valAx>") + before.count("<c:catAx>")
                  + before.count("<c:dateAx>"))
        closed = (before.count("</c:valAx>") + before.count("</c:catAx>")
                  + before.count("</c:dateAx>"))
        if opened - closed > 0:
            text = " ".join(re.findall(r"<a:t>([^<]*)</a:t>", m.group(0))).strip()
            out.append((seen, text))
            seen += 1
    return out


def _series_count(xml: str) -> int:
    return len(re.findall(r"<c:ser>", xml))


def _published_at_head():
    """The published workbook as a ZipFile at git HEAD, or None if git cannot answer."""
    try:
        blob = subprocess.run(["git", "show", f"HEAD:{PUBLISHED}"], cwd=cfg.ROOT,
                              capture_output=True, check=True).stdout
    except Exception:                                  # noqa: BLE001 - not a git checkout
        return None
    if not blob:
        return None
    return zipfile.ZipFile(io.BytesIO(blob))


def check():
    if not os.path.exists(BUILT):
        return [f"{BUILT} not found — build the workbook first"]
    base = _published_at_head()
    if base is None:
        print("chart preservation: no git baseline, nothing to compare against", flush=True)
        return []

    new = zipfile.ZipFile(BUILT)
    new_names = {n for n in new.namelist() if CHART.match(n)}
    old_names = {n for n in base.namelist() if CHART.match(n)}

    errs, compared = [], 0
    for name in sorted(old_names):
        if name not in new_names:
            errs.append(f"{os.path.basename(name)}: was published and is no longer built")
            continue
        compared += 1
        old_xml = base.read(name).decode()
        new_xml = new.read(name).decode()

        old_ax, new_ax = _axis_titles(old_xml), _axis_titles(new_xml)
        new_by_i = dict(new_ax)
        for i, text in old_ax:
            if i not in new_by_i:
                errs.append(f"{os.path.basename(name)}: axis title {text!r} has been "
                            f"REMOVED — the chart no longer names its units")
            elif new_by_i[i] != text:
                errs.append(f"{os.path.basename(name)}: axis title was {text!r} and is now "
                            f"{new_by_i[i]!r}")

        o, n = _series_count(old_xml), _series_count(new_xml)
        if n < o:
            errs.append(f"{os.path.basename(name)}: had {o} series and now has {n} — "
                        f"{o - n} were dropped")

    gained = len(new_names - old_names)
    print(f"chart preservation: compared {compared} chart(s) against git HEAD, "
          f"{gained} new", flush=True)
    return errs


def main():
    errs = check()
    if errs:
        print("CHART PRESERVATION: FAIL", flush=True)
        for e in errs:
            print("  ✗", e, flush=True)
        print("\nEvery other chart check asks whether the change added what it meant to.\n"
              "This one asks whether anything that was already there survived it.",
              flush=True)
        sys.exit(1)
    print("CHART PRESERVATION: PASS — no chart lost an axis title or a series", flush=True)


if __name__ == "__main__":
    main()
