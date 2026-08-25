"""opc_validate_fixtures.py — prove the package checks still catch what they claim to.

WHY THIS EXISTS. A guard cannot notice that it has stopped guarding. That is not a
maxim here, it is the measured history of this repo: on 2026-08-25 the reference-stability
guard was widened and silently disconnected from its own fixtures, and only the fixtures
caught it; the same day, check_chart_captions reported PASS while skipping the only four
charts it was ever written for. Both read green. Both were inert.

opc_validate gained two schema checks after a CI run died at the Windows validate leg on
14 errors that every local check had passed. Those checks are worth exactly as much as the
evidence that they fire, so this injects each fault into a real built workbook and asserts
the guard reports it. A check that stops firing fails here instead of in CI, half an hour
and a six-market fetch later.

Exit 0 = every fault is still detected.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

import config as cfg
import opc_validate as ov

WB = os.path.join(cfg.OUTPUT_DIR, "HourlyPowerData.xlsx")
TMP = os.path.join(cfg.OUTPUT_DIR, "_fixture_broken.xlsx")


def _write(parts, order, path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for n in order:
            out.writestr(n, parts[n])


def _load():
    z = zipfile.ZipFile(WB)
    parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    order = [i.filename for i in z.infolist()]
    z.close()
    return parts, order


def _charts(parts):
    return [n for n in parts if re.match(r"xl/charts/chart\d+\.xml$", n)]


def case_extlst_before_f(parts):
    """The exact fault that failed run 32876752424: extLst ahead of <c:f> in a Ref."""
    for n in _charts(parts):
        x = parts[n].decode()
        m = re.search(r"(<c:numRef>)(<c:f>.*?</c:f>)(.*?)(</c:numRef>)", x, re.S)
        if m:
            parts[n] = x.replace(
                m.group(0),
                m.group(1) + '<c:extLst><c:ext uri="{TEST}"/></c:extLst>'
                + m.group(2) + m.group(3) + m.group(4), 1).encode()
            return n
    return None


def case_legend_before_plotarea(parts):
    """A child-order violation inside <c:chart>, which Excel renders and the schema bans."""
    for n in _charts(parts):
        x = parts[n].decode()
        m = re.search(r"<c:legend>.*?</c:legend>", x, re.S)
        if m and "<c:plotArea>" in x:
            parts[n] = (x.replace(m.group(0), "", 1)
                         .replace("<c:plotArea>", m.group(0) + "<c:plotArea>", 1)).encode()
            return n
    return None


CASES = [
    ("extLst before <c:f> in a chart reference", case_extlst_before_f),
    ("legend before plotArea inside <c:chart>", case_legend_before_plotarea),
]


def main():
    if not os.path.exists(WB):
        raise SystemExit(f"{WB} not found — build the workbook first")

    # The control: the real workbook must be CLEAN. Without this, a checker that returned
    # an error for everything would pass every case below and look rigorous.
    if ov.validate(WB):
        print("OPC FIXTURES: FAIL — the real workbook already has problems, so the "
              "injected cases below prove nothing", flush=True)
        for e in ov.validate(WB)[:5]:
            print("  ✗", e, flush=True)
        sys.exit(1)
    print("  ok control                     real workbook is clean", flush=True)

    failed = []
    for label, inject in CASES:
        parts, order = _load()
        where = inject(parts)
        if where is None:
            failed.append(f"{label}: could not inject (no chart has the shape) — this "
                          f"case is no longer testing anything")
            print(f"  ✗  {label:<44} NOT INJECTABLE", flush=True)
            continue
        _write(parts, order, TMP)
        try:
            errs = ov.validate(TMP)
        finally:
            if os.path.exists(TMP):
                os.remove(TMP)
        if errs:
            print(f"  ok {label:<44} caught in {os.path.basename(where)}", flush=True)
        else:
            failed.append(f"{label}: injected into {where} and opc_validate reported "
                          f"NOTHING — that check is inert")
            print(f"  ✗  {label:<44} NOT CAUGHT", flush=True)

    if failed:
        print("OPC FIXTURES: FAIL", flush=True)
        for f in failed:
            print("  ✗", f, flush=True)
        print("\nopc_validate is reporting green because it has stopped looking, not\n"
              "because the workbook is sound. Fix the check, not this file.", flush=True)
        sys.exit(1)
    print(f"OPC FIXTURES: PASS — all {len(CASES)} injected fault(s) still detected",
          flush=True)


if __name__ == "__main__":
    main()
