"""undefined_names_test.py — refuse a tool that uses a name it never bound.

THE FAULT THIS EXISTS TO CATCH, found 2026-08-26 in a German fetch log. `fetch.py` used
`datetime.now(timezone.utc)` to stamp its gaps record and imported neither name. The line
sits inside `if hard or stale:`, so it ran ONLY when a fetch came back partial, which is
the one moment the record matters. Every time that happened it raised NameError instead.

The record is not decorative. Its own comment calls it "the single input to both things
that happen next: the targeted repair run reads `series` to know what to re-fetch, and the
public status page reads it to say WHICH series is behind and why". Both had therefore
never worked, and the failure was invisible: the fetch had already written its data, so the
run looked fine and the page simply went on saying nothing was wrong.

WHY NOTHING CAUGHT IT.
  * `python -c "import fetch"` cannot: the name resolves at call time, not import time.
  * `ast.parse` cannot: it is syntactically perfect.
  * status_health_test.py cannot, and this is the instructive part. It tests the CONSUMER
    of the record against hand-written fixture files. It passed throughout, because it
    never asked the producer to write one. A test that supplies its own input can only
    check the half downstream of it.
  * A linter would, but requirements.txt is exact-pinned on purpose ("a VERIFIED
    combination, not a guess at a good one"), so adding one to make a fetch job lint is a
    worse trade than thirty lines of stdlib.

HOW IT WORKS. `symtable` resolves scopes the way the interpreter does. For each module it
takes every GLOBAL name that is used but never bound anywhere in the module, and subtracts
the builtins. What remains is a name that cannot resolve at runtime, wherever it is used.

This is deliberately narrower than pyflakes: it says nothing about unused imports, shadowed
names or local-before-assignment. It answers one question, the one that cost a mechanism a
month of silence: can every name this module reads actually be found?
"""
from __future__ import annotations

import builtins
import io
import os
import symtable
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Checked in full. Anything importable that the pipeline runs belongs here; the list is the
# directory rather than a hand-kept set, so a new tool is covered the day it is added.
SKIP_DIRS = {".venv", "__pycache__", "chart_templates", "refresh-page", ".wrangler"}

# Names a module may legitimately read without binding: the interpreter provides them.
PROVIDED = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
    "__builtins__", "__debug__", "__annotations__", "WindowsError",
}


def _bound_anywhere(table, out):
    """Every name bound in this scope or any nested one.

    Nested scopes matter: a helper defined inside a function, or a name bound in a
    comprehension, is still a binding as far as "did anyone ever define this" goes. Being
    generous here is deliberate. This check is a floor on obvious breakage, and a false
    alarm in a build is far more expensive than a missed one, because a suite people learn
    to distrust stops being read at all.
    """
    for name in table.get_identifiers():
        sym = table.lookup(name)
        if sym.is_assigned() or sym.is_imported() or sym.is_parameter():
            out.add(name)
        # A name bound by `global x; x = ...` inside a function reads as assigned there.
    for child in table.get_children():
        _bound_anywhere(child, out)
    return out


def _used_globals(table, out):
    for name in table.get_identifiers():
        sym = table.lookup(name)
        if sym.is_global() and sym.is_referenced():
            out.add(name)
    for child in table.get_children():
        _used_globals(child, out)
    return out


def check_file(path):
    """-> sorted list of names this module reads and never binds."""
    with io.open(path, encoding="utf-8") as fh:
        src = fh.read()
    try:
        top = symtable.symtable(src, os.path.basename(path), "exec")
    except SyntaxError as ex:
        return [f"<syntax error: {ex}>"]
    bound = _bound_anywhere(top, set())
    used = _used_globals(top, set())
    return sorted(n for n in used - bound - PROVIDED if not n.startswith("__"))


def tool_files():
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".py") or name in SKIP_DIRS:
            continue
        yield os.path.join(HERE, name)


def main():
    fails = {}
    n = 0
    for path in tool_files():
        n += 1
        missing = check_file(path)
        if missing:
            fails[os.path.basename(path)] = missing

    print(f"undefined names: checked {n} module(s)", flush=True)
    if fails:
        print("UNDEFINED NAMES: FAIL", flush=True)
        for mod, names in sorted(fails.items()):
            print(f"  ✗ {mod}: uses {', '.join(names)} and binds them nowhere", flush=True)
        print("\nA name used inside a rarely-taken branch resolves only when that branch\n"
              "runs, which is why this survives import, ast.parse and every test that\n"
              "supplies its own input.", flush=True)
        return 1
    print("UNDEFINED NAMES: PASS — every module can resolve every name it reads",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
