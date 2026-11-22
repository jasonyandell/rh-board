#!/usr/bin/env python3
"""Summarise a run.py output directory into rd/frontier/data/.

  python3 -I analyze.py --out OUT --src PINNED_SRC
Writes data/modules.tsv (one row per target), data/summary.json, data/timing.json.
"""
import argparse, collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fixer"))
sys.path.insert(0, HERE)
os.environ.setdefault("FIXER_UP", os.path.join(HERE, "..", "fixer", "cache", "up"))
from common import load_modules  # noqa
ERR_RE = re.compile(r"^[^\n]*?:\d+:\d+: error(?:\([^)]*\))?: ?(.*)$", re.M)

DECL_RE = re.compile(r"^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|partial|unsafe|scoped|local)\s+)*"
                     r"(theorem|lemma|def|abbrev|instance|structure|class|inductive|example|opaque|axiom)\b")
FORBIDDEN = re.compile(r"\b(sorry|admit|axiom|native_decide|unsafe|implemented_by)\b")
PROOFY = {"theorem", "lemma", "example"}


def error_class(msg):
    m = msg or ""
    for key, name in (("timeout", "timeout"), ("Application type mismatch", "application type mismatch"),
                      ("ype mismatch", "type mismatch"), ("unsolved goals", "unsolved goals"),
                      ("Function expected", "function expected"), ("Unknown identifier", "unknown identifier"),
                      ("Unknown constant", "unknown constant"), ("unknown identifier", "unknown identifier"),
                      ("rewrite` failed", "rewrite failed"), ("failed to synthesize", "failed to synthesize"),
                      ("No goals", "no goals"), ("Invalid field", "invalid field"),
                      ("simp` made no progress", "simp no progress"), ("linarith failed", "linarith failed"),
                      ("Invalid alternative name", "invalid alternative name"),
                      ("could not synthesize default value", "default value"),
                      ("deterministic) timeout", "heartbeat timeout"), ("Unknown", "unknown name (other)")):
        if key in m:
            return name
    return "other" if m else ""


def changed_lines_kind(src, new):
    """Classify each changed line: 'proof' (inside a theorem/lemma/example body), 'statement'
    (theorem header before its first `:=`), 'definition' (inside def/instance/structure/...),
    'other' (outside any declaration). Edits here never change the line count."""
    a, b = src.split("\n"), new.split("\n")
    if len(a) != len(b):
        return {"unaligned": 1}, []
    decl_kind, header_open = None, False
    kinds = collections.Counter()
    added = []
    for i, (x, y) in enumerate(zip(a, b)):
        m = DECL_RE.match(x)
        if m:
            decl_kind, header_open = m.group(1), True
        elif x and not x[0].isspace() and not x.startswith(("--", "/-", "·", "|", ")", "]")):
            # a column-0 line that is not a declaration ends the previous declaration
            if not x.startswith(("@[", "attribute")):
                decl_kind, header_open = None, False
        if x != y:
            added.append(y)
            if decl_kind is None:
                kinds["other"] += 1
            elif decl_kind in PROOFY:
                if header_open:
                    pos = x.find(":=")
                    # changed text before := on the header line is a statement change
                    first_diff = next((k for k, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
                    kinds["statement" if pos < 0 or first_diff < pos else "proof"] += 1
                else:
                    kinds["proof"] += 1
            else:
                kinds["definition"] += 1
        if header_open and ":=" in x:
            header_open = False
    return dict(kinds), added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", required=True)
    a = ap.parse_args()
    mods = load_modules()
    res = os.path.join(a.out, "results")
    load = lambda s: ({r["id"]: r for r in map(json.loads, open(os.path.join(res, s + ".jsonl")))}
                      if os.path.exists(os.path.join(res, s + ".jsonl")) else {})
    sel = json.load(open(os.path.join(res, "selection.json")))
    closure, base, A, B, C, D = (load(s) for s in ("closure", "base", "A", "B", "C", "D"))
    # recount errors from the logs (early runs used a pattern that missed `error(lean.xxx):`)
    for stage, R in (("base", base), ("A", A), ("B", B), ("C", C), ("D", D)):
        for m, r in R.items():
            lp = os.path.join(a.out, "logs", stage, m + ".log")
            if "secs" in r and os.path.exists(lp):
                errs = ERR_RE.findall(open(lp, encoding="utf-8", errors="replace").read())
                r["errors"] = len(errs)
                r["first_error"] = errs[0][:200] if errs else r.get("first_error", "")
    rows = []
    summ = collections.Counter()
    first_err = collections.Counter()
    arm = {k: collections.Counter() for k in "ABCD"}
    rule = collections.Counter()
    for m in sel["targets"]:
        mod = mods[m]
        src = open(os.path.join(a.src, mod["module"].replace(".", "/") + ".lean"), encoding="utf-8").read()
        islat = "IsLattice" in src
        b = base.get(m)
        row = {"id": m, "module": mod["module"], "depth": mod["depth"], "packet": mod["packet"],
               "islattice": int(islat)}
        if b is None:
            row["outcome"] = "not-built"
            rows.append(row); summ["not-built"] += 1
            continue
        row["base_errors"] = b["errors"]
        row["first_error_class"] = error_class(b["first_error"]) if not b["ok"] else ""
        row["first_error"] = b["first_error"][:120] if not b["ok"] else ""
        if b["ok"]:
            row["outcome"] = "unchanged-ok-islattice" if islat else "unchanged-ok"
        else:
            first_err[row["first_error_class"]] += 1
            fixed_by = []
            for k, R in (("A", A), ("B", B), ("C", C), ("D", D)):
                r = R.get(m)
                if r is None:
                    row[k] = "not-run"; arm[k]["not-run"] += 1
                    continue
                if r.get("skip"):
                    row[k] = r["skip"]; arm[k][r["skip"]] += 1
                    continue
                if not r.get("fired"):
                    row[k] = "no-change"; arm[k]["no-change"] += 1
                    continue
                if r.get("ok"):
                    row[k] = "builds"; arm[k]["builds"] += 1
                    if k == "D":
                        row["D_rules"] = " ".join(r.get("rules", []))
                    fixed_by.append(k)
                    ed = os.path.join(a.out, "edits", r.get("from", k)[:1] if k == "C" else k, m + ".lean")
                    if os.path.exists(ed):
                        kinds, added = changed_lines_kind(src, open(ed, encoding="utf-8").read())
                        bad = any(FORBIDDEN.search(x) for x in added)
                        needs_note = any(kinds.get(x) for x in ("statement", "definition", "unaligned"))
                        verdict = "forbidden-token" if bad else ("builds-needs-note" if needs_note else "proof-only")
                        if islat:
                            verdict += "+islattice"
                        row[k + "_check"] = verdict
                        row[k + "_lines"] = kinds
                        rule[(k, verdict)] += 1
                else:
                    ne = r.get("errors", 0)
                    if ne < b["errors"]:
                        ch = "fewer-errors"
                    elif ne > b["errors"]:
                        ch = "more-errors"
                    elif r.get("first_error") != b["first_error"]:
                        ch = "same-count-first-error-changed"
                    else:
                        ch = "no-change-in-errors"
                    row[k] = "fails:" + ch; arm[k]["fails:" + ch] += 1
                    row[k + "_errors"] = ne
            if fixed_by:
                first = fixed_by[0]
                row["outcome"] = f"fixed-by-{first}" + ("-islattice" if islat else "")
            else:
                row["outcome"] = "still-failing"
        summ[row["outcome"]] += 1
        rows.append(row)
    blocked = sum(1 for r in rows if r["outcome"] == "not-built")
    by_depth = collections.defaultdict(collections.Counter)
    for r in rows:
        by_depth[r["depth"]][r["outcome"]] += 1
    out = {
        "targets": len(sel["targets"]), "closure": len(sel["closure"]),
        "closure_failed": sorted(m for m, r in closure.items() if not r["ok"]),
        "outcomes": dict(summ.most_common()),
        "by_depth": {d: dict(c) for d, c in sorted(by_depth.items())},
        "first_error_classes": dict(first_err.most_common()),
        "arms": {k: dict(v.most_common()) for k, v in arm.items()},
        "rule_check": {f"{k}:{v}": n for (k, v), n in sorted(rule.items())},
        "blocked": blocked,
    }
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "data", "summary.json"), "w"), indent=1, ensure_ascii=False)
    cols = ["id", "depth", "packet", "module", "outcome", "first_error_class", "base_errors",
            "A", "A_check", "B", "B_check", "C", "C_check", "D", "D_check", "D_rules", "islattice", "first_error"]
    with open(os.path.join(HERE, "data", "modules.tsv"), "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in cols) + "\n")
    tim = [json.loads(l) for l in open(os.path.join(res, "timing.jsonl"))]
    secs = collections.defaultdict(list)
    for s, R in (("closure", closure), ("base", base), ("A", A), ("B", B), ("C", C), ("D", D)):
        secs[s] = sorted(r["secs"] for r in R.values() if "secs" in r)
    pct = lambda xs, q: xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None
    json.dump({"stages": tim,
               "per_module_secs": {s: {"n": len(x), "median": pct(x, .5), "p90": pct(x, .9),
                                       "max": x[-1] if x else None, "sum": round(sum(x))}
                                   for s, x in secs.items()}},
              open(os.path.join(HERE, "data", "timing.json"), "w"), indent=1)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
