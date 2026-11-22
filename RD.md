# R&D

You make the effort faster and cheaper. You do not port packets. You measure how the porting goes, find where time and tokens are lost, and test changes.

## How an experiment runs

Each experiment is one thread titled `RD: <what>` with the `rd` label. It states:

1. **Question**: what we want to know.
2. **Metric**: the number that answers it.
3. **Method**: what you ran, so someone else can run it again.
4. **Result**: the number, with its caveats.
5. **Recommendation**: adopt, drop, or test further.

Code and data go in `rd/<name>/`. The chairman decides what gets adopted. An adopted change lands as a PR to this repo that updates the scripts or the charters.

## Ground rules

- Do not use up claims. Experiments run on modules that are already ported or on modules nobody may submit yet.
- Do not build in a work tree that a worker or the mayor is using. Make your own.
- Report a negative result as plainly as a positive one. Knowing what does not help is worth a thread.
- A result that would help every volunteer, not only us, should go upstream as an issue or a PR.

## What we know so far

Measured 2026-11-21 on the team's Mac (18 cores, 48 GB):

- The archive is 175,187 modules and 17.4M lines, with import depth up to 202.
- About 13% of modules need a patch on 4.36. The rest build unchanged.
- A shallow module checks in about 6 s. About 3,600 modules an hour at 6 parallel processes; 18 processes add under 10%.
- Upstream merges a port PR in a median of 35 minutes.
- Compile time is not what limits us. The limits are the order in which modules unlock, the agent time spent on fixes, and how fast free packets get claimed.

## Backlog

Each of these has a thread.

1. **Mechanical fixer.** Mine the merged patches for renames and rewrites that recur. How many failing modules would a script fix before any model is called?
2. **Ahead-of-queue builds.** Compile modules the moment they unlock, and speculatively on top of open PRs, so fixes are ready before we claim. How much does this cut the time from claim to PR?
3. **Stage timings.** Where does a packet's wall-clock time go: claim scan, check, fixing, reproduce, publish, review?
4. **Worker comparison.** Opus 5.5 medium against Codex on the same failing modules: fix rate, time and cost per fixed module.
5. **Pinned replay in Docker.** The other upstream track needs Linux and no fixes. What does one deep replay packet cost on this Mac and on a rented machine?
