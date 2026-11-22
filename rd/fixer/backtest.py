#!/usr/bin/env python3
"""Held-out backtest of the mechanical fixer.

Patches are ordered by the time upstream merged them (latest commit that added the .patch).
Rules are mined from the oldest TRAIN_FRAC of patches only, applied to the pinned sources of the
newest patches, and the output is compared with the merged patched file. No compiler is run.

Usage: python3 -I backtest.py [--train-frac 0.7]
Writes data/backtest.json, data/backtest_modules.tsv, data/rules_train.tsv/.json,
data/infix_train.tsv
"""
import argparse, collections, json, math, os, random, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa
from mine import (score_rules, select, load_all, apply_rules, code_only, code_mask, patch_edits,
                  write_rules, count_code)

QIDENT_RE = re.compile(r"(?<![" + CONT + r"])" + QIDENT)
SPLIT = re.compile(r"([._])")


def comps(name):
    return SPLIT.split(name)  # keeps separators at odd indices


def infix_of(o, n):
    """Component-level middle edit between two identifiers, or None."""
    a, b = comps(o), comps(n)
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    ma, mb = a[i:len(a) - j], b[i:len(b) - j]
    if not ma or not mb:
        return None
    sa, sb = "".join(ma), "".join(mb)
    if sa.startswith(("_", ".")) or sa.endswith(("_", ".")):
        return None
    # require the edit to be a multi-character word change, not a single letter
    if len(sa) < 4:
        return None
    return sa, sb


def infix_apply_ident(tok, rules):
    """Rewrite one identifier with component infix rules; returns tok unchanged if none apply."""
    for oa, nb in rules:
        pat = r"(?:^|(?<=[._]))" + re.escape(oa) + r"(?=$|[._])"
        tok2 = re.sub(pat, nb, tok)
        if tok2 != tok:
            return tok2
    return tok


def mine_infix(ids, sources, patched, exact):
    """Mine component infix rules from rename pairs and score them like exact rules.

    fire  = train files containing an identifier the infix rule would rewrite (excluding
            identifiers already handled by an exact rule)
    clean = fire files where every such identifier is gone from the merged file and its
            rewritten form is present
    """
    files = collections.defaultdict(set)
    for m in ids:
        _, pairs = patch_edits(m)
        for o, n in pairs:
            ix = infix_of(o, n)
            if ix:
                files[ix].add(m)
    rows = []
    code_src = {m: code_only(sources[m]) for m in ids}
    code_new = {m: code_only(patched[m]) for m in ids}
    for (oa, nb), sup in files.items():
        fire = clean = 0
        pat = re.compile(r"(?:^|(?<=[._]))" + re.escape(oa) + r"(?=$|[._])")
        for m in ids:
            if oa not in code_src[m]:
                continue
            hits = {t for t in QIDENT_RE.findall(code_src[m]) if t not in exact and pat.search(t)}
            if not hits:
                continue
            fire += 1
            newset = set(QIDENT_RE.findall(code_new[m]))
            if all(t not in newset and infix_apply_ident(t, [(oa, nb)]) in newset for t in hits):
                clean += 1
        rows.append({"old": oa, "new": nb, "support": len(sup), "fire": fire, "clean": clean,
                     "precision": round(clean / fire, 3) if fire else 0.0})
    rows.sort(key=lambda r: (-r["support"], r["old"]))
    return rows


DECL_RE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|partial|unsafe)\s+)*"
                     r"(?:theorem|lemma|def|abbrev|instance|structure|class|inductive|opaque|axiom)\s+(" + QIDENT + ")",
                     re.M)


def local_names(src):
    """Last components of names the file itself declares."""
    return {n.split(".")[-1] for n in DECL_RE.findall(src)}


TFAE_FILE = re.compile(r"(?i)tfae")
TFAE_OUT = re.compile(r"\.out (\d+) (\d+)(?![\d.])")


def tfae_shift(src):
    """Structural rule: in files that mention TFAE, `.out i j` -> `.out (i+1) (j+1)` (List.TFAE.out
    became 1-indexed). Code segments only."""
    if not TFAE_FILE.search(src):
        return src
    return "".join(TFAE_OUT.sub(lambda m: f".out {int(m.group(1)) + 1} {int(m.group(2)) + 1}", t)
                   if c else t for c, t in code_mask(src))


def tfae_stats(ids, sources, patched):
    """files where tfae_shift fires, and where every shifted line appears in the merged file."""
    fire = clean = 0
    for m in ids:
        out = tfae_shift(sources[m])
        if out == sources[m]:
            continue
        fire += 1
        pl = set(patched[m].split("\n"))
        if all(b in pl for a, b in zip(sources[m].split("\n"), out.split("\n")) if a != b):
            clean += 1
    return {"fire": fire, "clean": clean}


def apply_all(src, exact, infix, guard=True, tfae=False):
    if tfae:
        src = tfae_shift(src)
    """Apply exact ident rules, then infix rules. With guard, skip any rule whose old name's last
    component is declared in this file (a local lemma shadows the Mathlib name)."""
    if guard and exact:
        loc = local_names(src)
        exact = {o: n for o, n in exact.items() if o.split(".")[-1] not in loc}
    out = apply_rules(src, exact)
    if not infix:
        return out
    res = []
    for is_code, t in code_mask(out):
        if is_code:
            t = QIDENT_RE.sub(lambda mm: mm.group(0) if mm.group(0) in exact.values()
                              else infix_apply_ident(mm.group(0), infix), t)
        res.append(t)
    return "".join(res)


def line_map(hunks):
    """Source line (1-based) -> ('kept') | ('paired', new_text) | ('block', set_of_new_lines)."""
    changed = {}
    for start, rem, add in change_blocks(hunks):
        if len(rem) == len(add):
            for k, (a, b) in enumerate(zip(rem, add)):
                changed[start + k] = ("paired", b, set(add))
        else:
            for k in range(len(rem)):
                changed[start + k] = ("block", None, set(add))
    return changed


def compare(src, out, patched, hunks):
    if out == src:
        return "no_fire", {}
    if out == patched:
        return "exact", {}
    sl, ol = src.split("\n"), out.split("\n")
    assert len(sl) == len(ol)
    cmap = line_map(hunks)
    right = wrong_kept = wrong_diff = consistent = 0
    for i, (a, b) in enumerate(zip(sl, ol), 1):
        if a == b:
            continue
        st = cmap.get(i)
        if st is None:
            wrong_kept += 1
        elif st[0] == "paired" and st[1] == b:
            right += 1
        else:
            # script touched a line the patch also changed, differently. Consistent if every
            # identifier the script introduced on this line appears in the patch's new lines.
            new_ids = set(QIDENT_RE.findall(b)) - set(QIDENT_RE.findall(a))
            added_ids = set(QIDENT_RE.findall("\n".join(st[2])))
            if new_ids and new_ids <= added_ids:
                consistent += 1
            else:
                wrong_diff += 1
    patch_lines = len(cmap)
    info = {"right": right, "consistent": consistent, "wrong_kept": wrong_kept,
            "wrong_diff": wrong_diff, "patch_changed_lines": patch_lines}
    if wrong_kept:
        return "false_fix_kept_line", info
    if wrong_diff:
        return "alt_fix_changed_line", info
    if consistent:
        return "partial_consistent", info
    return "partial", info


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 4), round(min(1, c + h), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-frac", type=float, default=0.7)
    args = ap.parse_args()
    mods = load_modules()
    times = load_merge_times(".patch")
    ids = patch_ids()
    sources, patched = load_all(ids, mods)
    ids = sorted((m for m in ids if m in sources), key=lambda m: (times[m][0], m))
    cut = int(len(ids) * args.train_frac)
    # do not split a merge commit across train and test
    while 0 < cut < len(ids) and times[ids[cut]][1] == times[ids[cut - 1]][1]:
        cut += 1
    train, test = ids[:cut], ids[cut:]
    depth = lambda xs: dict(sorted(collections.Counter(mods[m]["depth"] for m in xs).items()))

    rows = score_rules(train, sources, patched)
    write_rules(rows, os.path.join(HERE, "data", "rules_train"))
    strict = select(rows, 2, 0.9)
    infix_rows = mine_infix(train, sources, patched, strict)
    with open(os.path.join(HERE, "data", "infix_train.tsv"), "w") as f:
        f.write("old\tnew\tsupport\tfire\tclean\tprecision\n")
        for r in infix_rows:
            f.write(f"{r['old']}\t{r['new']}\t{r['support']}\t{r['fire']}\t{r['clean']}\t{r['precision']}\n")
    infix_sel = [(r["old"], r["new"]) for r in infix_rows if r["support"] >= 2 and r["precision"] >= 0.9]

    # unchanged-OK modules: split by merge time of their .json record
    jtimes = load_merge_times(".json")
    unch = [m for m in unchanged_ids() if m in jtimes]
    unch_src = {}
    for m in unch:
        s = pinned_source(mods[m])
        if s is not None:
            unch_src[m] = s
    unch = sorted(unch_src, key=lambda m: (jtimes[m][0], m))
    tcut = times[test[0]][0]
    unch_train = [m for m in unch if jtimes[m][0] < tcut]
    unch_test = [m for m in unch if jtimes[m][0] >= tcut]

    def neg_filter(table):
        """Drop rules that fire on any unchanged-OK module recorded before the test window."""
        bad = set()
        codes = {m: code_only(unch_src[m]) for m in unch_train}
        for o in table:
            for m in unch_train:
                if o in codes[m] and count_code(o, codes[m]):
                    bad.add(o)
                    break
        return {o: n for o, n in table.items() if o not in bad}, sorted(bad)

    strict_neg, dropped = neg_filter(strict)
    MAIN = "strict + local-decl guard"
    REC = "strict + guard + TFAE index rule (recommended)"
    variants = {
        "strict (support>=2, precision>=0.9), no guard": (strict, [], False),
        MAIN: (strict, [], True),
        "strict + guard + unchanged-module filter": (strict_neg, [], True),
        "loose (support>=1, precision>=0.9) + guard": (select(rows, 1, 0.9), [], True),
        "permissive (support>=2, precision>=0.5) + guard": (select(rows, 2, 0.5), [], True),
        "strict + guard + infix rules": (strict, infix_sel, True),
        REC: (strict, [], True, True),
        "all mined pairs (no safety filter)": (select(rows, 1, 0.0), [], True),
    }

    # ceilings for any identifier-substitution table on the held-out set
    ident_only = lambda m: {b[3] for b in patch_edits(m)[0]} <= {"rename", "qualify", "rename+qualify", "whitespace"}
    train_pairs = set()
    train_olds = set()
    for m in train:
        for o, n in patch_edits(m)[1]:
            train_pairs.add((o, n)); train_olds.add(o)
    test_ident_only = [m for m in test if ident_only(m)]
    test_seen = [m for m in test_ident_only if set(patch_edits(m)[1]) <= train_pairs]
    test_touch = [m for m in test if set(patch_edits(m)[1]) & train_pairs]
    ceilings = {
        "test_patches_ident_only": len(test_ident_only),
        "test_ident_only_all_pairs_seen_in_train": len(test_seen),
        "test_patches_with_any_pair_seen_in_train": len(test_touch),
    }

    result = {
        "upstream_commit": open(os.path.join(os.path.dirname(UP), "upstream-commit.txt")).read().strip()
        if os.path.exists(os.path.join(os.path.dirname(UP), "upstream-commit.txt")) else None,
        "train_patches": len(train), "test_patches": len(test),
        "train_window_utc": [times[train[0]][0], times[train[-1]][0]],
        "test_window_utc": [times[test[0]][0], times[test[-1]][0]],
        "train_depths": depth(train), "test_depths": depth(test),
        "unchanged_modules": {"before_test_window": len(unch_train), "in_test_window": len(unch_test)},
        "rules_mined_train": len(rows),
        "infix_rules_selected": infix_sel,
        "dropped_by_unchanged_filter": dropped,
        "ceilings": ceilings,
        "tfae_rule_train": tfae_stats(train, sources, patched),
        "tfae_rule_test": tfae_stats(test, sources, patched),
        "variants": {},
    }
    per_module = []
    n = len(test)
    for name, (table, infix, guard, *tf) in variants.items():
        tf = bool(tf and tf[0])
        cats = collections.Counter()
        right = cons = wrongk = wrongd = pl_partial = right_partial = 0
        for m in test:
            hunks = parse_patch(read_patch(m))
            out = apply_all(sources[m], table, infix, guard, tf)
            cat, info = compare(sources[m], out, patched[m], hunks)
            cats[cat] += 1
            if info:
                right += info["right"]; cons += info["consistent"]
                wrongk += info["wrong_kept"]; wrongd += info["wrong_diff"]
                if cat in ("partial", "partial_consistent"):
                    pl_partial += info["patch_changed_lines"]; right_partial += info["right"]
            if name == REC:
                per_module.append((m, mods[m]["depth"], cat, info))
        fired_unch = [m for m in unch if apply_all(unch_src[m], table, infix, guard, tf) != unch_src[m]]
        result["variants"][name] = {
            "rules": len(table) + len(infix),
            "counts": {k: cats[k] for k in ("exact", "partial", "partial_consistent",
                                            "alt_fix_changed_line", "false_fix_kept_line", "no_fire")},
            "rates": {k: round(cats[k] / n, 4) for k in ("exact", "partial", "partial_consistent",
                                                         "alt_fix_changed_line", "false_fix_kept_line", "no_fire")},
            "exact_ci95": wilson(cats["exact"], n),
            "partial_any_ci95": wilson(cats["partial"] + cats["partial_consistent"], n),
            "differs_from_patch_ci95": wilson(cats["alt_fix_changed_line"] + cats["false_fix_kept_line"], n),
            "lines": {"right": right, "consistent": cons, "wrong_on_kept_line": wrongk,
                      "differs_on_changed_line": wrongd},
            "partial_share_of_patch_lines_done": round(right_partial / pl_partial, 3) if pl_partial else None,
            "fires_on_unchanged": [len(fired_unch), len(unch)],
            "fires_on_unchanged_in_test_window": [sum(1 for m in fired_unch if m in set(unch_test)), len(unch_test)],
            "unchanged_fired_ids": fired_unch[:30],
        }

    bydepth = collections.defaultdict(collections.Counter)
    for m, d, cat, info in per_module:
        bydepth[d][cat] += 1
    result["recommended_by_depth"] = {d: {"n": sum(c.values()), "exact": c["exact"],
                                          "partial": c["partial"] + c["partial_consistent"],
                                          "differs": c["alt_fix_changed_line"] + c["false_fix_kept_line"]}
                                      for d, c in sorted(bydepth.items())}

    # learning curve: grow the training prefix, same held-out set, MAIN settings
    curve = []
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        sub = train[:max(1, int(len(train) * frac))]
        tab = select(score_rules(sub, sources, patched), 2, 0.9)
        ex = sum(1 for m in test if apply_all(sources[m], tab, [], True) == patched[m])
        curve.append({"train_patches": len(sub), "rules": len(tab), "test_exact": ex,
                      "test_exact_rate": round(ex / n, 4)})
    result["learning_curve"] = curve

    with open(os.path.join(HERE, "data", "backtest.json"), "w") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
    with open(os.path.join(HERE, "data", "backtest_modules.tsv"), "w") as f:
        f.write("id\tdepth\tcategory\tlines_right\tlines_consistent\twrong_kept\twrong_changed\tpatch_lines\n")
        for m, d, cat, info in per_module:
            f.write(f"{m}\t{d}\t{cat}\t" + "\t".join(str(info.get(k, "")) for k in
                    ("right", "consistent", "wrong_kept", "wrong_diff", "patch_changed_lines")) + "\n")
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
