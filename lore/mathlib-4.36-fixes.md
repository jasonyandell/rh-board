# Mathlib v4.36.0 fix patterns

Fixes that have recurred while porting from Lean 4.33.1 to 4.36.0. Search this file for the failing identifier before reasoning about an error. New patterns arrive on the board's Lore thread and get folded in here.

Also search upstream's merged patches: `/usr/bin/grep -l IDENT port/patches/*.patch`.

## Renames

| Pinned name | Name on v4.36.0 |
|---|---|
| `finset_sum_coeff` | `finsetSum_coeff` |
| `continuous_mul_left` | `continuous_const_mul` |
| `comap_map_of_isPrime_disjoint` | `under_map_of_isPrime_disjoint` |
| `map_comap` (ideals lying over) | `map_under` |

## Changed behavior

- `TFAE.out` is now 1-indexed.
- `Matrix.mul_apply`, `Matrix.one_apply` and `Polynomial.coeff_smul` are now protected. Write the full name.
- `MultilinearMap` needs the ring homomorphism made explicit: `(RingHom.id R)`.
- `PowerSeries.derivative` needs the ring made explicit: `(R := k)`.
- `pow_padicValNat_dvd` is gone. Use `padicValNat_def` with `pow_multiplicity_dvd`.
- `intValuation_liesOver` is now stated with `ramificationIdx`.

## Meaning changes that still compile

- `Submodule.IsLattice` now names a weaker notion (no `span_eq_top`). A statement or definition that uses it must become `Submodule.IsFullLattice`, with an equivalence note. Upstream's `port/islattice_audit.lean` finds these; text search does not.

## Tooling gotchas

- On macOS the receipt's `peak_child_rss_kib` is in bytes, not KiB.
- The upstream claim scan takes over two minutes. Run it in the background.
- If `show --ready-only` lists members whose imports are other members of the same packet, remove the local record JSONs and re-run, so one receipt covers the whole packet.
