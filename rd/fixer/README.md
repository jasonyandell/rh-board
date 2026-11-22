# RD: mechanical fixer

**Question:** how many failing modules could a script fix before any model is called?

**Metric:** on held-out merged patches, the share of modules where the script's output equals the merged patched file (exact), matches part of it (partial), or makes a change the patch did not make. Also, how often the rules fire on modules that upstream recorded as building unchanged.

Upstream snapshot: `origin/main` at `990c354d`, with 1,391 merged `.patch` files and 9,601 `"unchanged"` records. All 1,391 patches apply cleanly to hash-verified pinned sources. No compiler was run.

## Results

### 1. What the merged patches contain (all 1,391 patches, 3,043 change blocks)

Each contiguous block of `-`/`+` lines was classified by token-level diff. Equal-length blocks are paired line by line; unequal ones count as multi-line rewrites.

| block class | blocks | patches containing it |
|---|---:|---:|
| identifier rename | 946 | 576 |
| inserted tokens (added args, parens, type ascriptions) | 412 | 229 |
| args changed (inserts/deletes mixed with renames) | 388 | 168 |
| other single-line rewrite | 315 | 216 |
| added namespace qualifier | 208 | 81 |
| multi-line rewrite | 206 | 166 |
| deleted lines | 160 | 56 |
| deleted tokens (dropped explicit args) | 135 | 81 |
| tactic swap | 113 | 98 |
| added lines | 106 | 87 |
| rename + numeric literal (TFAE indices) | 48 | 39 |

- **500 of 1,391 patches (36%) consist only of identifier renames and qualifiers.** That is the ceiling for a token-substitution table. The other 891 need some edit that is not context-free.
- There are 358 distinct identifier substitutions, and 236 of them occur in only one patch. Concentration:

| top-k substitutions | patches touched | ident-only patches fully covered |
|---:|---:|---:|
| 1 (`Finset.prod_le_prod`→`Finset.prod_le_prod₀`) | 90 | 70 |
| 5 | 233 | 176 |
| 10 | 344 | 224 |
| 50 | 584 | 365 |
| all 358 | 810 | 500 |

### 2. Rewrite table and safety

`data/rules_all.tsv` lists one candidate per old identifier: the most frequent target, plus these counts over the patched files:

- `support`: patches that make this substitution.
- `fire`: patched files whose pinned source contains the old token in code.
- `clean`: fire files where the patch made the substitution and no old token survives.
- `survive`: fire files where the old token is still present after the merged patch, so it is valid there unchanged.
- `precision = clean / fire`.
- `occ_seen`, `occ_changed`: the same at the level of single occurrences.

`selected=1` marks rules with support ≥ 2 and precision ≥ 0.9: 56 of 284 rules. Context-dependent renames fall out on their own. For example, `padicValNat`→`multiplicity` has precision 0.17, `map_add`→`RingHom.map_add` 0.00, `coeff`→`P.coeff` 0.20, and `Ideal.isMaximal_comap_of_isIntegral_of_isMaximal` 0.57.

When applied, the rules:

- touch only code (comments and strings are skipped) and whole identifiers (word-boundary safe on dotted names);
- skip any rule whose name the file declares itself. This "local-decl guard" stops `mul_apply`→`Matrix.mul_apply` in files that define their own `mul_apply`.

There is one structural rule. In files that mention TFAE, `.out i j` becomes `.out (i+1) (j+1)`. It was justified from the data: 39 of 39 patched files that contain `.out N M` shift every such index, and no unchanged-OK module contains `.out N M`.

Component-level "infix" rules (such as `finset_sum`→`finsetSum` inside any name) were mined and tested (`data/infix_train.tsv`). Only 2 passed the safety threshold, and they added nothing on the held-out set. Dropped.

### 3. Held-out backtest

Patches were ordered by the earliest commit on `origin/main` that added them.

> **Note:** `origin/main` has a second root commit (a full-tree snapshot dated after most merges) that re-adds about 1,000 patches. Taking the latest add would collapse the order.

- **Train:** the oldest 980 patches (70%; depth 0: 739, depth 1: 240, depth 2: 1).
- **Test:** the newest 411 patches (depth 0: 28, depth 1: 285, depth 2: 97, depth 3: 1).
- Rules are mined from the train set only.

Outcome categories on the 411 held-out modules:

- **exact**: output equals the merged patched file.
- **partial**: every line the script changed equals the merged line, but some hunks are missing.
- **partial-consistent**: the script's new identifiers all appear in the patch's new lines for that block, but the line text differs.
- **alt fix on changed line**: the patch changed that line too, but differently. Often a different valid fix, for example `continuous_const_mul x` versus `continuous_const.mul continuous_id`.
- **touched kept line**: the script changed a line the patch left alone. This is the real false-fix risk.

| variant | rules | exact | partial (+consistent) | alt fix on changed line | touched kept line | no fire | fires on unchanged-OK |
|---|---:|---:|---:|---:|---:|---:|---:|
| **strict + guard + TFAE (recommended)** | 49+1 | **95 (23.1%, CI 19.3–27.4)** | 37 (9.0%, CI 6.6–12.2) | 5 (1.2%) | 2 (0.5%) | 272 (66%) | 4 / 9,601 (0.04%) |
| strict + guard | 49 | 85 (20.7%) | 34 | 5 | 2 | 285 | 4 / 9,601 |
| strict, no guard | 49 | 85 | 34 | 5 | 3 (14 lines) | 284 | 4 / 9,601 |
| + unchanged-module filter | 46 | 74 (18.0%) | 34 | 5 | 2 | 296 | 0 / 9,601 |
| support ≥ 1, precision ≥ 0.9 | 124 | 89 (21.7%) | 34 | 6 | 3 | 279 | 12 / 9,601 |
| support ≥ 2, precision ≥ 0.5 | 65 | 95 (23.1%) | 39 | 10 | 11 | 256 | 27 / 9,601 |
| every mined pair, no safety filter | 241 | 0 | 0 | 0 | 411 | 0 | 9,543 / 9,601 |

Variant definitions:

- **strict:** support ≥ 2 and precision ≥ 0.9.
- **guard:** the local-decl guard described in section 2.
- **unchanged-module filter:** drops any rule that fires on an unchanged-OK module recorded before the test window.

Other measurements:

- **Partial modules:** the script did about 32% of the patch's changed lines.
- **By depth (recommended variant):**

| depth | exact | partial | differs |
|---|---|---|---|
| 0 | 9/28 | 3 | 0 |
| 1 | 65/285 (22.8%) | 27 | 5 |
| 2 | 21/97 (21.6%) | 7 | 2 |

  There is no visible trend over depths 0–2.
- **Ceiling:** 129 of 411 held-out patches are rename/qualify only. 111 of those use only substitutions seen in training, and the script gets 95 exact (with TFAE).
- **Learning curve** (strict + guard, same test set):

| training patches | rules | exact |
|---:|---:|---:|
| 98 | 13 | 14.8% |
| 245 | 30 | 19.2% |
| 490 | 38 | 18.5% |
| 735 | 46 | 20.2% |
| 980 | 49 | 20.7% |

  The table saturates fast. The gain comes from roughly 20 high-frequency Mathlib renames, not from the long tail.
- **The 4 unchanged-OK hits:**
  - One is a real context error: bare `prod_le_prod` under `open Cardinal`.
  - Two are `continuous_finset_sum`, which still builds unchanged there. It is likely still accepted (a deprecated alias), so the rewrite is probably harmless but unproven.
  - One is `Abelianization`→`Group.Abelianization`, in a file where the bare name still resolves.

### 4. Payoff estimate

If about 20,000 modules still need a patch and they resemble the held-out set:

- **Exact match:** about 23%, so **about 4,600 modules (95% CI about 3,900–5,500)** would get a script output identical to what a person or an LLM would have written. Only the binomial sampling error is in that interval.
- **Partial:** about 9%, so **about 1,800 (about 1,300–2,400)** would get a partial head start, with about a third of the patch lines already done. That is a smaller problem for the LLM, not a solved one.
- **Differs:** about 1.7%, so about 350, where the script changes something the reference patch did not. Most of these are plausible alternative fixes, but they are unverified.
- **No fire:** about 66% get no help at all.

### What this does not show

- **No module is shown to be fixed.** An exact match reproduces a file that already built upstream, so it would build again on the same dependency records. For future modules, this textual rate is a proxy.
- **The match is a lower bound in one direction.** Valid fixes that differ from the merged patch count as misses or "differs". For non-matching output it proves nothing either way.
- **The held-out set is shallow** (import depth 0–3) and comes from a short time window, about 1.5 hours of merges right after the training window. Deep modules may fail more often for reasons no Mathlib rename table covers, such as statements changed by upstream project patches. They may also use a different mix of Mathlib API.
- **The reference patches may already be partly script-made.** If volunteers used their own rename scripts, exact-match rates are inflated relative to an independent fixer.
- **The error excerpts were not used as a gate.** Triage excerpts cover only 34 of the held-out modules. In the 684 triage failures, the first error is never "unknown identifier" (0 of the 550 excerpts that have an error line). Renamed lemmas usually still exist with a different type (`Application type mismatch`, `Function expected`). So an "unknown identifier" gate would not work; a gate on "first-error line contains a rule's old token" is untested.
- **Compiler deprecation hints were not used.** 329 of 684 failing excerpts carry Lean's `Replace the deprecated name` hints, a free machine-readable rename source. They were not used because deprecations are warnings, not failures.

## Recommendation

**Adopt as a pre-pass, gated by a build. Test further before trusting it without one.**

1. Run `fix.py` on every module that fails unchanged, then rebuild.
2. If the module builds, ship it without an LLM call.
3. If it still fails, give the LLM the rewritten file and the remaining error.

Builds take about 6 s per shallow module, so the gate is cheap. The table should be re-mined from merged patches as they land; the safety counts update automatically.

The next experiment is to run this on a few hundred not-yet-ported failing modules with real builds. That measures build-verified fix rate rather than textual match, including the 1.7% "differs" bucket.

## Files

| file | what |
|---|---|
| `prepare.sh` | snapshots upstream `port/`, `tracker/` and the patch add-log into `cache/` (gitignored) |
| `common.py` | loaders, pinned-source hash check, strict patch applier, Lean-ish tokenizer |
| `mine.py` | classifies change blocks and mines and scores the full rule table |
| `backtest.py` | time-split held-out backtest, variants, ceilings, learning curve, unchanged-module fire rate |
| `fix.py` | applies the selected table and TFAE rule to files; prints a diff and never writes in place |
| `data/blocks.tsv` | every change block with its class and token edits |
| `data/classes.json` | class distribution, concentration, top edits |
| `data/rules_all.tsv/.json` | rule table mined from all patches, with support and safety counts (`selected` column) |
| `data/rules_train.tsv/.json` | the same, mined from the train split only |
| `data/infix_train.tsv` | component-infix candidates (dropped) |
| `data/backtest.json` | all backtest numbers |
| `data/backtest_modules.tsv` | per held-out module outcome (recommended variant) |

## Re-run

```sh
REPLAY=/path/to/alpoge-rh-replay ./prepare.sh
export FIXER_SRC=/path/to/pinned/lean/src          # files are used only if their SHA-256 matches
python3 -I mine.py                                  # ~15 s
python3 -I backtest.py [--train-frac 0.7]           # ~4 min
python3 -I fix.py --check-unchanged
python3 -I fix.py path/to/Module.lean               # candidate diff
```

`FIXER_SRC` may list several trees separated by `:`. Each module is taken from the first tree whose copy matches the pinned hash.
