# RD: build-gated fixer on the frontier

**Question:** on modules nobody has ported yet, how many build unchanged on Lean 4.36.0 / Mathlib v4.36.0? Of those that fail, how many does a mechanical fixer make build, measured by a real build?

**Population:** every module on upstream `origin/main` (`d920dca2`) that has no port record, is not pruned, and whose imports all have records. That is 4,007 modules:

| depth | modules |
|---:|---:|
| 0 | 60 |
| 1 | 221 |
| 2 | 3,155 |
| 3 | 570 |
| 4 | 1 |

All were built; nothing was sampled. Their import closure is 3,943 recorded modules, of which 539 carry a merged patch. All 3,943 were built first from pinned sources plus merged patches, and every one built, so nothing was blocked.

## Results

### Baseline: unchanged build

| | modules | share |
|---|---:|---:|
| builds unchanged | 3,425 | 85.5% |
| of which the source mentions `IsLattice` (flagged, not counted as done) | 15 | |
| fails | 582 | 14.5% |

Failures by depth:

| depth | failing | share of depth |
|---:|---:|---:|
| 0 | 60 of 60 | 100% |
| 1 | 39 of 221 | 18% |
| 2 | 407 of 3,155 | 13% |
| 3 | 76 of 570 | 13% |

All 60 depth-0 modules fail because they are the leftover triage failures.

First error of the 582 failures:

| first error | modules |
|---|---:|
| unknown identifier or constant | 207 (36%) |
| application type mismatch | 107 |
| function expected | 63 |
| rewrite failed | 42 |
| failed to synthesize | 25 |
| invalid alternative name | 21 |
| type mismatch | 21 |
| unsolved goals | 18 |
| other | 78 |

### Arms on the 582 failures, each scored by a build

| arm | what it does | fired | builds | still failing: fewer errors / first error changed / no change / more errors |
|---|---|---:|---:|---|
| **A** | rule table from `rd/fixer` (56 renames + TFAE index rule) | 180 | **127 (21.8%)** | 45 / 1 / 5 / 2 |
| **B** | Lean's deprecation hints from the failing build, applied verbatim | 316 | **0** | 1 / 7 / 269 / 39 |
| **C** | A, then hints harvested from A's build | 268 | **127** (same as A) | 47 / 7 / 182 / 32 |
| **D** (added) | for modules still failing after A, apply any mined rename, with no precision threshold, but only for names the compiler reports as `Unknown identifier/constant`; up to 3 build rounds | 127 | **39** | 28 / 56 / 2 / 2 |

- **A+D:** 166 of 582 failures (28.5%) now build. 121 + 36 = 157 pass the rule check as proof-only.
- **B never fixes anything** and makes 39 modules worse. Deprecation replacements are not drop-in. For example, `TensorProduct.induction_on`→`inductionOn` renames the induction cases, which produces `Invalid alternative name`. And `if_neg`→`ite_eq_right` has a different statement. The deprecations are only warnings: they are not what breaks these builds.
- **D works because the compiler gate makes low-precision renames safe.** The old name is gone everywhere, so the rename cannot clobber a valid use. Examples: `continuous_mul_left`→`continuous_const_mul` (precision 0.7 in the backtest), `Polynomial.coeff`, `coeff_add`→`MvPolynomial.coeff_add`, `AlgEquiv.toAlgHom_eq_coe`.

### Rule check of the 166 modules that build

- **Forbidden tokens:** no added line contains `sorry`, `admit`, `axiom`, `native_decide`, `unsafe` or `implemented_by`.
- **`sorry` warnings:** no fixed or unchanged-OK build log contains `declaration uses sorry`.
- **Proof-only:** 157 modules change only lines inside theorem/lemma/example proofs.
- **Builds, needs a note:** 9 modules. The check is conservative: it counts any edit inside a `def`/`instance` body, including tactic lines there. Two are genuine statement renames:
  - `M053946`: `DistribMulAction.toAddMonoidHom`→`DistribSMul.toAddMonoidHom`
  - `M067529`: `Polynomial.coeff`→`AddMonoidAlgebra.coeff`

  Two more rename `DistribMulAction.toAddMonoidHom` inside a definition (`M157203`, `M157578`).
- **IsLattice:** no fixed module mentions `IsLattice`. The 15 unchanged-OK modules that do are flagged in `modules.tsv` (outcome `unchanged-ok-islattice`). This is a text flag, not upstream's environment audit.

### Net

| status | modules |
|---|---:|
| machine-done: builds unchanged, no IsLattice | 3,410 |
| machine-done: fixed by A or D, proof-only | 157 |
| **total machine-done** | **3,567 of 4,007 (89%)** |
| left for an LLM or a person: still failing | 416 |
| left for an LLM or a person: builds, needs a note | 9 |
| IsLattice audit | 15 |

Of the 416 still failing, unknown names remain the biggest group. The `MvPolynomial.coeff`/`coeff`/`coeff_add` API change alone appears in about 50 modules and has no safe one-token rewrite.

### Timing (6 Lean processes, this Mac; load from Spotlight indexing reached about 30 at times)

| stage | modules | wall clock | modules/hour |
|---|---:|---:|---:|
| prepare sources (hash-verified) | 7,950 | 4 s | |
| import closure | 3,943 | 54.8 min | about 4,300 |
| baseline build | 4,007 | 60.6 min | 3,965 |
| arm A | 180 builds | 2.8 min | |
| arm B | 316 builds | 7.8 min | |
| arm C | 268 builds | 6.6 min | |
| arm D | 127 builds | 2.4 min | |

- **Per-module time:** median 4.4 s, p90 5.7 s, max 489 s (one closure module). There were no timeouts at 900 s.
- **Total:** about 2 h 15 min of wall clock for everything.
- **Disk:** build outputs grew by 3.1 GB; logs are 72 MB.
- **Ahead-of-queue cost:** about 1 s of wall clock per ready module at 6 processes. The fixer adds about 3% on top (arms A and D are about 5 minutes per 4,000 modules).

## What this does not show

- **Upstream's acceptance gates were not run.** The patches were not reproduced with `port_build.py reproduce` (`lake --no-cache build`), and upstream's `islattice_audit.lean` environment audit was not run.
- **Lean was invoked directly, not through Lake.** The command line and `--setup` options copy what Lake passes in this tree. All 3,943 recorded closure modules built this way, which suggests the invocation is faithful.
- **"Proof-only" is a line-level heuristic.** It sorts changed lines into declaration headers before `:=`, definition bodies, and proofs. On the 1,391 merged patches it flags only 5 of the 299 whose notes say proof-only, and all 5 are proof edits inside `def` bodies.
- **Some of these modules sit in other volunteers' claims and open PRs,** whose own fixes may differ. Agreement with those fixes was not measured.
- **The LLM time and tokens saved were not measured.**

## Recommendation

1. **Adopt A+D as a build-gated pre-pass.** It is cheap and makes 28.5% of real failures build, 27% of them proof-only. D is the bigger finding: gating the long tail of renames on the compiler's `Unknown identifier/constant` makes renames safe that the textual safety filter had to reject.
2. **Drop B,** and C with it. Lean's deprecation hints fix nothing and break 7% of the modules they touch.
3. **Next steps:**
   - Grow D's table from the still-failing unknown names. The biggest cluster is the MvPolynomial `coeff` API, which needs a context rule or an LLM, not a rename.
   - Run D after every merged batch.
4. **Offer the asset to claim holders.** `data/modules.tsv` (outcomes per module) and `data/fixed/*.patch` (166 build-verified candidate patches, with the 9 needing a note marked) cover 123 packets held by other volunteers. Offer them to those claimants through our own channels, not upstream. Each claimant must still reproduce the result and run the IsLattice audit before submitting.

## Files

| file | what |
|---|---|
| `run.py` | stages: `prepare`, `closure`, `base`, `A`, `B`, `C`, `D`, `restore`; resumable; fixed pool of N Lean processes; backs off when load is high |
| `hints.py` | harvests and applies Lean deprecation hints (decodes the strike-through hint diff) |
| `analyze.py` | outcome table, rule check, IsLattice flag, timing |
| `env.sh` | toolchain and path variables for this Mac (read-only use of the shared elan) |
| `data/modules.tsv` | one row per module: id, depth, packet, module, outcome (`unchanged-ok`, `unchanged-ok-islattice`, `fixed-by-A`, `fixed-by-D`, `still-failing`), first error class, base error count, per-arm result and rule check, D's rules, first error text |
| `data/summary.json` | all counts |
| `data/timing.json` | stage timing and per-module seconds |
| `data/fixed/<ID>.patch` | unified diff against the pinned source for every module that builds after A or D |

Outcome precedence in `modules.tsv`: `fixed-by-A` wins over `fixed-by-D`. No module was fixed by B or C alone.

## Re-run

```sh
# 1. upstream snapshot (also used by rd/fixer)
REPLAY=/path/to/alpoge-rh-replay ../fixer/prepare.sh
# 2. a private copy-on-write tree with Mathlib built for 4.36
cp -cRp /path/to/idle-4.36-tree/lean /path/to/rd-trees/frontier/lean
# 3. edit env.sh (TREE, OUT, PINNED), then
source env.sh
python3 -I run.py --tree $TREE --out $OUT --src $PINNED --jobs 6 prepare closure base A B C D restore
python3 -I analyze.py --out $OUT --src $PINNED
```

Every stage is resumable: it skips modules already in `OUT/results/<stage>.jsonl`. `--sample N` builds a depth-stratified random sample instead of every module.
