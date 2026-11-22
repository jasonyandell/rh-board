#!/usr/bin/env python3
"""Mine merged port patches: classify every change block, and extract candidate rewrite rules.

Usage: python3 -I mine.py            (env: FIXER_UP, FIXER_ADDLOG, FIXER_SRC; see common.py)
Writes data/blocks.tsv, data/classes.json, data/rules_all.tsv, data/rules_all.json
"""
import collections, difflib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa

TACTICS = set("""simp simp_all simpa dsimp norm_num linarith nlinarith positivity omega ring ring_nf
field_simp gcongr exact apply refine rw rwa nth_rw rintro intro intros obtain rcases cases induction
aesop decide tauto push_cast norm_cast exact_mod_cast assumption_mod_cast fun_prop continuity
measurability bound polyrith linear_combination constructor use exists refine' convert convert_to
congr ext funext calc unfold delta change show trivial rfl first try all_goals any_goals
filter_upwards split_ifs by_cases by_contra contrapose push_neg specialize have let set suffices
exfalso absurd left right subst symm trans grind lia order zify qify lift interval_cases fin_cases
abel group module noncomm_ring nlinarith! simp? exact? apply? infer_instance inferInstance
haveI letI""".split())


def token_edits(a, b):
    """Token-level edits turning line a into line b: list of (old_tokens, new_tokens)."""
    ta, tb = tokens(a), tokens(b)
    sm = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            out.append((ta[i1:i2], tb[j1:j2]))
    return out


def nonws(ts):
    return [t for t in ts if not t.isspace()]


def classify_edit(old, new):
    o, n = nonws(old), nonws(new)
    if not o and not n:
        return "whitespace"
    if len(o) == 1 and len(n) == 1 and is_ident(o[0]) and is_ident(n[0]):
        if n[0].endswith("." + o[0]):
            return "qualify"
        if o[0].endswith("." + n[0]):
            return "unqualify"
        if o[0] in TACTICS or n[0] in TACTICS:
            return "tactic_swap"
        return "rename"
    if len(o) == 1 and len(n) == 1 and o[0].isdigit() and n[0].isdigit():
        return "literal"
    if any(t in TACTICS for t in o + n):
        return "tactic_swap"
    if not o:
        return "insert_tokens"
    if not n:
        return "delete_tokens"
    return "other_edit"


def classify_block(rem, add):
    if not add:
        return "delete_lines", []
    if not rem:
        return "add_lines", []
    if len(rem) != len(add):
        return "multiline_rewrite", []
    kinds, edits = set(), []
    for a, b in zip(rem, add):
        for old, new in token_edits(a, b):
            k = classify_edit(old, new)
            kinds.add(k)
            edits.append((k, "".join(old).strip(), "".join(new).strip()))
    kinds.discard("whitespace")
    if not kinds:
        return "whitespace", edits
    if kinds <= {"rename"}:
        return "rename", edits
    if kinds <= {"qualify", "unqualify"}:
        return "qualify", edits
    if kinds <= {"rename", "qualify", "unqualify"}:
        return "rename+qualify", edits
    if kinds <= {"rename", "qualify", "unqualify", "literal"}:
        return "rename+literal", edits
    if "tactic_swap" in kinds:
        return "tactic_swap", edits
    if kinds <= {"insert_tokens"}:
        return "insert_tokens", edits
    if kinds <= {"delete_tokens"}:
        return "delete_tokens", edits
    if kinds <= {"insert_tokens", "delete_tokens", "rename", "qualify", "unqualify", "literal"}:
        return "args_changed", edits
    return "line_rewrite", edits


IDENT_KINDS = {"rename", "qualify", "unqualify"}


def patch_edits(mid):
    """Return (blocks, ident_pairs) for a patch. ident_pairs: Counter of (old,new) ident substitutions."""
    hunks = parse_patch(read_patch(mid))
    blocks, pairs = [], collections.Counter()
    for start, rem, add in change_blocks(hunks):
        cls, edits = classify_block(rem, add)
        blocks.append((start, len(rem), len(add), cls, edits))
        if len(rem) == len(add):
            for a, b in zip(rem, add):
                for old, new in token_edits(a, b):
                    if classify_edit(old, new) in IDENT_KINDS | {"tactic_swap"}:
                        o, n = nonws(old), nonws(new)
                        if len(o) == 1 and len(n) == 1 and is_ident(o[0]) and is_ident(n[0]):
                            pairs[(o[0], n[0])] += 1
    return blocks, pairs


# ---------------------------------------------------------------- code/comment segmentation

def code_mask(s):
    """Return list of (is_code, text) segments: skips comments (nested /- -/, --) and strings."""
    out, i, n, buf, start = [], 0, len(s), [], 0
    segs = []
    code_start = 0
    while i < n:
        c = s[i]
        if s.startswith("--", i):
            j = s.find("\n", i)
            j = n if j < 0 else j
            segs.append((True, s[code_start:i])); segs.append((False, s[i:j])); i = code_start = j
        elif s.startswith("/-", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if s.startswith("/-", j):
                    depth += 1; j += 2
                elif s.startswith("-/", j):
                    depth -= 1; j += 2
                else:
                    j += 1
            segs.append((True, s[code_start:i])); segs.append((False, s[i:j])); i = code_start = j
        elif c == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            j = min(j + 1, n)
            segs.append((True, s[code_start:i])); segs.append((False, s[i:j])); i = code_start = j
        else:
            i += 1
    segs.append((True, s[code_start:]))
    return [x for x in segs if x[1]]


def code_only(s):
    return "".join(t if c else re.sub(r"[^\n]", " ", t) for c, t in code_mask(s))


_re_cache = {}


def rx(tok):
    r = _re_cache.get(tok)
    if r is None:
        r = _re_cache[tok] = ident_re(tok)
    return r


def count_code(tok, code):
    return len(rx(tok).findall(code))


def apply_rules(src, rules):
    """Apply ident rules (dict old->new) to code segments only, simultaneously (no chaining)."""
    if not rules:
        return src
    big = re.compile(r"(?<![" + CONT + r"])(" + "|".join(re.escape(k) for k in sorted(rules, key=len, reverse=True)) + r")(?![" + CONT + r"])")
    out = []
    for is_code, t in code_mask(src):
        out.append(big.sub(lambda m: rules[m.group(1)], t) if is_code else t)
    return "".join(out)


# ---------------------------------------------------------------- rule scoring

def score_rules(ids, sources, patched):
    """Mine ident rules from `ids` and score each against the same files.

    For rule old->new:
      support   = files whose patch performs old->new
      fire      = files whose pinned source contains old in code
      survive   = files whose merged (patched) file still contains old in code
      clean     = fire files where the patch did old->new and no old survives
      precision = clean / fire       (file level)
      occ_changed / occ_seen = token-level share of old's code occurrences that the patches rewrote
    Conflicts: the same old with several different new values are kept as separate candidates;
    only the most frequent is applied.
    """
    pair_files = collections.defaultdict(set)
    for mid in ids:
        _, pairs = patch_edits(mid)
        for k in pairs:
            pair_files[k].add(mid)
    olds = collections.defaultdict(dict)
    for (o, n), fs in pair_files.items():
        olds[o][n] = fs
    code_src = {m: code_only(sources[m]) for m in ids}
    code_new = {m: code_only(patched[m]) for m in ids}
    # cheap prefilter by substring
    rows = []
    for o, news in olds.items():
        fire, survive, occ_seen, occ_left = set(), set(), 0, 0
        for m in ids:
            if o not in code_src[m]:
                continue
            c = count_code(o, code_src[m])
            if c:
                fire.add(m)
                occ_seen += c
                cl = count_code(o, code_new[m])
                occ_left += cl
                if cl:
                    survive.add(m)
        ranked = sorted(news.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        best_new, best_fs = ranked[0]
        clean = len((best_fs & fire) - survive)
        rows.append({
            "old": o, "new": best_new,
            "kind": classify_edit([o], [best_new]),
            "support": len(best_fs),
            "alt_targets": len(ranked) - 1,
            "alt_support": sum(len(v) for _, v in ranked[1:]),
            "fire": len(fire), "survive": len(survive), "clean": clean,
            "precision": round(clean / len(fire), 3) if fire else 0.0,
            "occ_seen": occ_seen, "occ_changed": occ_seen - occ_left,
        })
    rows.sort(key=lambda r: (-r["support"], r["old"]))
    return rows


def select(rows, min_support=2, min_precision=0.9):
    return {r["old"]: r["new"] for r in rows
            if r["support"] >= min_support and r["precision"] >= min_precision}


def load_all(ids, mods):
    sources, patched = {}, {}
    for m in ids:
        s = pinned_source(mods[m])
        if s is None:
            continue
        p = apply_patch(s, parse_patch(read_patch(m)))
        if p is None:
            continue
        sources[m], patched[m] = s, p
    return sources, patched


def write_rules(rows, path):
    for r in rows:
        r["selected"] = int(r["support"] >= 2 and r["precision"] >= 0.9)
    cols = ["selected", "old", "new", "kind", "support", "fire", "clean", "survive", "precision",
            "occ_seen", "occ_changed", "alt_targets", "alt_support"]
    with open(path + ".tsv", "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    with open(path + ".json", "w") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)


def main():
    mods = load_modules()
    ids = patch_ids()
    sources, patched = load_all(ids, mods)
    ids = [m for m in ids if m in sources]
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)

    # ---- classification
    block_cls = collections.Counter()
    patch_sets = collections.Counter()
    patch_has = collections.Counter()
    lines_by_cls = collections.Counter()
    edit_strs = collections.Counter()
    with open(os.path.join(HERE, "data", "blocks.tsv"), "w") as f:
        f.write("id\tline\tremoved\tadded\tclass\tedits\n")
        for m in ids:
            blocks, _ = patch_edits(m)
            cs = set()
            for start, nr, na, cls, edits in blocks:
                block_cls[cls] += 1
                lines_by_cls[cls] += nr + na
                cs.add(cls)
                es = "; ".join(f"{k}:{o!r}->{n!r}" for k, o, n in edits if k != "whitespace")
                for k, o, n in edits:
                    if k != "whitespace":
                        edit_strs[(k, o, n)] += 1
                f.write(f"{m}\t{start}\t{nr}\t{na}\t{cls}\t{es}\n")
            for c in cs:
                patch_has[c] += 1
            mech = cs <= {"rename", "qualify", "rename+qualify", "whitespace"}
            patch_sets["ident-only (rename/qualify)" if mech else "needs other edits"] += 1
    # concentration of ident substitutions: per distinct pair, number of patches
    pair_files = collections.defaultdict(set)
    ident_only = set()
    patch_pairs = {}
    for m in ids:
        blocks, pairs = patch_edits(m)
        patch_pairs[m] = set(pairs)
        for k in pairs:
            pair_files[k].add(m)
        if {b[3] for b in blocks} <= {"rename", "qualify", "rename+qualify", "whitespace"}:
            ident_only.add(m)
    ranked = sorted(pair_files.items(), key=lambda kv: -len(kv[1]))
    conc = []
    covered_any, covered_full = set(), set()
    chosen = set()
    for i, (k, fs) in enumerate(ranked, 1):
        chosen.add(k)
        covered_any |= fs
        if i in (1, 5, 10, 20, 50, 100, 200, len(ranked)):
            full = [m for m in ident_only if patch_pairs[m] <= chosen]
            conc.append({"top_k": i, "patches_touched": len(covered_any),
                         "ident_only_patches_fully_covered": len(full)})
    summary = {
        "patches": len(ids),
        "blocks": sum(block_cls.values()),
        "block_classes": block_cls.most_common(),
        "changed_lines_by_class": lines_by_cls.most_common(),
        "patches_containing_class": patch_has.most_common(),
        "patch_split": patch_sets.most_common(),
        "distinct_ident_pairs": len(pair_files),
        "ident_pairs_in_one_patch_only": sum(1 for v in pair_files.values() if len(v) == 1),
        "concentration": conc,
        "top_ident_pairs": [(o, n, len(fs)) for (o, n), fs in ranked[:60]],
        "top_edits_any_kind": [(k, o, n, c) for (k, o, n), c in edit_strs.most_common(80)],
    }
    with open(os.path.join(HERE, "data", "classes.json"), "w") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    rows = score_rules(ids, sources, patched)
    write_rules(rows, os.path.join(HERE, "data", "rules_all"))
    print(json.dumps({k: summary[k] for k in ("patches", "blocks", "block_classes", "patches_containing_class",
                                              "patch_split", "distinct_ident_pairs",
                                              "ident_pairs_in_one_patch_only", "concentration")}, ensure_ascii=False))
    print("rules:", len(rows), "support>=2:", sum(r["support"] >= 2 for r in rows),
          "support>=2&prec>=0.9:", len(select(rows)))


if __name__ == "__main__":
    main()
