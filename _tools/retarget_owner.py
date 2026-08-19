#!/usr/bin/env python3
"""Point this project at a new GitHub owner, after the repo is transferred to an organisation.

Prepared 2026-08-17 while Fred created the org, so applying it is one command rather than a hunt
through nine files. Dry run by default: it prints every line it would change and writes nothing.

    ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/retarget_owner.py" <new-owner>
    ~/.claude/pyenv/bin/python3 "Power Price Data/_tools/retarget_owner.py" <new-owner> --apply

AFTER --apply, three things that are NOT this script's job:

  1. `cd _tools/refresh-page && npx wrangler deploy`, or the live page keeps asking GitHub about the
     old owner and its status line goes blank.
  2. Mint a NEW fine-grained PAT with the ORG as resource owner (Actions: write, that repo only) and
     `npx wrangler secret put GH_TOKEN`. The old one is scoped to the old owner and stops covering
     the repo the moment the transfer completes. Until it is replaced, the status line, all three
     downloads and the Refresh button degrade.
  3. The WORKBOOK's own Power Query connections still hold the old URL, inside the xlsx. GitHub
     redirects transferred repo URLs and raw follows, but a live model should not rest on a
     redirect. That file is Fred's and hand-edited, so it is his to change.

Deliberately narrow: it rewrites `<old>/power-price-data` and the Worker's OWNER constant, and
nothing else. The bare username is NOT search-and-replaced, because it also appears in
`fredhill123/flat-hunt` and in the vault's own git remote, neither of which is moving.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "power-price-data"


def current_owner() -> str:
    """Read the owner the project currently points at, rather than hardcoding it.

    Hardcoded, this script worked exactly once: after the 2026-08-17 move to
    `Power-Utilities-team` its own constant still said `fredhill123`, so a second move would have
    found nothing to change and reported success. The Worker's OWNER is the single place the live
    system reads, so it is the right source.
    """
    w = (ROOT / "_tools" / "refresh-page" / "worker.js").read_text(encoding="utf-8")
    m = re.search(r'const OWNER = "([^"]+)"', w)
    if not m:
        raise SystemExit("could not read OWNER from _tools/refresh-page/worker.js")
    return m.group(1)


OLD = current_owner()

# Every file that names the owner, found by grep on 2026-08-17. The script re-scans rather than
# trusting this list, and warns if it finds a file that is not on it: a new reference added since
# then is exactly the thing a hardcoded list would miss.
EXPECTED = {
    "ROLLOVER.md", "CLAUDE.md", "current-status.md", "WORK_MACHINE_SETUP.md", "EXCEL_SETUP.md",
    "GITHUB.md",
    "_tools/add_power_queries.py", "_tools/build_linked.py", "_tools/add_status_sheet.py",
    "_tools/refresh-page/wrangler.toml", "_tools/refresh-page/worker.js",
}
SCAN = ("*.md", "*.py", "*.js", "*.toml", "*.yml", "*.yaml")
SKIP = (".venv", "/.git/", "/archive/", "/.extracted/", "node_modules")


def edits(new: str):
    """(pattern, replacement) pairs. Narrow by construction: each one names the repo or the const."""
    return [
        (re.compile(rf"\b{re.escape(OLD)}/{re.escape(REPO)}\b"), f"{new}/{REPO}"),
        (re.compile(rf'(const OWNER = ")({re.escape(OLD)})(")'), rf"\g<1>{new}\g<3>"),
        # The wrangler.toml comment describes the token's scope in prose, not as a URL.
        (re.compile(rf"(Actions:write on ){re.escape(OLD)}( only)"), rf"\g<1>{new}\g<2>"),
        # current-status.md states the owner in prose beside the URL. Caught by the dry run: the URL
        # rule alone left "github.com/<new>/power-price-data (owner fredhill123)", which reads as a
        # contradiction and is exactly the kind of half-migration that outlives a rename.
        (re.compile(rf"(\(owner ){re.escape(OLD)}(\))"), rf"\g<1>{new}\g<2>"),
    ]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print(f"\nusage: {Path(__file__).name} <new-owner> [--apply]", file=sys.stderr)
        return 2
    new = args[0]
    if new == OLD:
        print(f"that is already the owner ({OLD})", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", new):
        print(f"{new!r} is not a valid GitHub account name", file=sys.stderr)
        return 2

    rules = edits(new)
    files, total, seen = 0, 0, set()
    for pat in SCAN:
        for f in sorted(ROOT.rglob(pat)):
            rel = str(f.relative_to(ROOT))
            if any(s in f"/{rel}" for s in SKIP):
                continue
            # Not itself: OLD appears here as the constant being migrated away from, and rewriting
            # that would leave the script unable to find anything on a second run.
            if f.resolve() == Path(__file__).resolve():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if OLD not in text:
                continue
            out, n = text, 0
            for rx, rep in rules:
                out, k = rx.subn(rep, out)
                n += k
            if not n:
                continue
            seen.add(rel)
            files += 1
            total += n
            print(f"\n{rel}  ({n} change{'s' if n != 1 else ''})")
            for i, (a, b) in enumerate(zip(text.splitlines(), out.splitlines()), 1):
                if a != b:
                    print(f"  {i}: - {a.strip()[:110]}")
                    print(f"  {i}: + {b.strip()[:110]}")
            if apply:
                f.write_text(out, encoding="utf-8")

    print(f"\n{total} change(s) across {files} file(s){' — WRITTEN' if apply else ' — dry run'}")

    # A reference that appeared since the list was written is worth naming, and one that has gone is
    # worth knowing about too: both mean the list and the project have drifted.
    for extra in sorted(seen - EXPECTED):
        print(f"  note: {extra} was not on the expected list, so check that change by eye")
    for gone in sorted(EXPECTED - seen):
        print(f"  note: {gone} no longer names the owner")

    if apply:
        print("\nNext, in order:")
        print("  1. cd \"Power Price Data/_tools/refresh-page\" && npx wrangler deploy")
        print("  2. mint a fine-grained PAT with the ORG as resource owner, then")
        print("     npx wrangler secret put GH_TOKEN")
        print("  3. update BASE in the workbook's Power Query connections (Fred's file)")
        print("  4. check the page's status line reads a date, not "
              "\"Could not read the status record\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
