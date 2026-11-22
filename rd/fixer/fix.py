#!/usr/bin/env python3
"""Apply the mined rename table to Lean files and print a unified diff (never writes in place).

  python3 -I fix.py FILE.lean [...]                 # diff to stdout
  python3 -I fix.py --out DIR FILE.lean [...]       # also write rewritten copies under DIR
  python3 -I fix.py --check-unchanged               # fire rate on upstream "unchanged" modules

Table: data/rules_all.json (mined from every merged patch), rules with support >= 2 and
file-level precision >= 0.9, skipping any rule whose name the file declares itself,
plus the TFAE rule (`.out i j` -> `.out i+1 j+1` in files that mention TFAE).
A diff from this script is a candidate, not a fix: build it before submitting.
"""
import argparse, difflib, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE, load_modules, unchanged_ids, pinned_source  # noqa
from mine import select  # noqa
from backtest import apply_all  # noqa


def table(path, min_support, min_precision):
    with open(path) as f:
        return select(json.load(f), min_support, min_precision)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--table", default=os.path.join(HERE, "data", "rules_all.json"))
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-precision", type=float, default=0.9)
    ap.add_argument("--out")
    ap.add_argument("--check-unchanged", action="store_true")
    a = ap.parse_args()
    tab = table(a.table, a.min_support, a.min_precision)
    if a.check_unchanged:
        mods = load_modules()
        fired, n = [], 0
        for m in unchanged_ids():
            s = pinned_source(mods[m])
            if s is None:
                continue
            n += 1
            if apply_all(s, tab, [], True, True) != s:
                fired.append(m)
        print(json.dumps({"rules": len(tab), "unchanged_checked": n, "fired": len(fired), "ids": fired}))
        return
    for p in a.files:
        src = open(p, encoding="utf-8").read()
        out = apply_all(src, tab, [], True, True)
        if out == src:
            continue
        sys.stdout.writelines(difflib.unified_diff(src.splitlines(True), out.splitlines(True),
                                                   "a/" + p.lstrip("/"), "b/" + p.lstrip("/")))
        if a.out:
            dst = os.path.join(a.out, p.lstrip("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "w", encoding="utf-8").write(out)


if __name__ == "__main__":
    main()
