"""Fixtures for check_reference_stability — prove it FAILS on what it claims to catch.

A guard that has never been seen to fail is not a guard, it is a line that runs. These
cases pin both halves: the three layout changes that are legitimate (identical, a column
appended, a row appended) must PASS, and the four that silently repoint charts (a column
inserted, rows reordered, a column dropped, a published file no longer built) must FAIL.

Run it directly: python check_reference_stability_fixtures.py
Exits non-zero if any case behaves differently from what it says it should.
"""
import csv, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_reference_stability as g

def write(p, rows):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

BASE = [["technology","DE_w1","ES_w1"],["Solar",1,2],["Onshore wind",3,4]]

cases = {
    "identical":            [["technology","DE_w1","ES_w1"],["Solar",1,2],["Onshore wind",3,4]],
    "appended column":      [["technology","DE_w1","ES_w1","GB_w1"],["Solar",1,2,9],["Onshore wind",3,4,9]],
    "appended row":         [["technology","DE_w1","ES_w1"],["Solar",1,2],["Onshore wind",3,4],["Gas",5,6]],
    "INSERTED column":      [["technology","DE_w1","GB_w1","ES_w1"],["Solar",1,9,2],["Onshore wind",3,9,4]],
    "REORDERED rows":       [["technology","DE_w1","ES_w1"],["Onshore wind",3,4],["Solar",1,2]],
    "DROPPED column":       [["technology","DE_w1"],["Solar",1],["Onshore wind",3]],
    "file no longer built": None,
}

all_ok = True
for label, new_rows in cases.items():
    tmp = tempfile.mkdtemp()
    b, n = os.path.join(tmp,"base"), os.path.join(tmp,"new")
    write(os.path.join(b,"fig5_capture_window.csv"), BASE)
    if new_rows is not None:
        write(os.path.join(n,"fig5_capture_window.csv"), new_rows)
    else:
        os.makedirs(n, exist_ok=True)
    g.BASELINE, g.NEW = b, n
    errs = g.check()
    verdict = "PASS" if not errs else "FAIL"
    expect = "PASS" if label in ("identical","appended column","appended row") else "FAIL"
    all_ok = all_ok and verdict == expect
    mark = "ok " if verdict == expect else "!! "
    print(f"{mark}{label:24s} guard says {verdict:4s} (expected {expect})")
    if errs and verdict == expect:
        print(f"      {errs[0][:110]}")
    shutil.rmtree(tmp)

sys.exit(0 if all_ok else 1)
