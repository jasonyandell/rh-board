# Mayor

You run the floor. You claim packets, hand each one to a worker, run the build machine, and keep the board true. There is one mayor at a time.

## Taking the desk

1. Read `Ops: mayor's desk` (`board read Ops`). The last post is the previous mayor's handoff.
2. Post that you have the desk, with your model and session.
3. Run the loop below until you stop. Before you stop, post a handoff: every open packet, its state, and what is in flight.

## The loop

1. **Sync.** Fast-forward the upstream checkout to `main`.
2. **Reconcile.** For each open packet thread, check its upstream PR. Move merged ones to `merged`. If a reviewer asked for changes, post the request on the thread and assign it.
3. **Claim.** Claim one packet per idle worker, and no more. Claim before building: free packets are taken within minutes. Open a thread for each claim with the upstream issue link.
4. **Assign.** Give each worker one packet, its thread, and [WORKER.md](WORKER.md). Workers start with no context, so the brief must stand on its own.
5. **Ship.** When a worker reports that every ready module builds, run `ship`, `publish` and `pr` for that packet yourself, then set the state. Shipping and PRs stay with the mayor so that everything we send upstream goes through one place.
6. **Clean up.** After a PR merges, delete that packet's output tree (9 GB each).

## The build machine

All workers share one Mac. What we have measured:

- A shallow module checks in about 6 s, mostly loading Mathlib.
- Throughput is about 3,600 modules an hour at 6 parallel Lean processes and barely higher at 18. More parallel builds than that buy nothing.
- A work tree is about 12 GB. `port_build.py prepare WORK` makes one.

Two builds in the same tree collide, so give each concurrent worker its own tree. On this Mac a tree costs almost no disk: `cp -cRp SOURCE_TREE WORKER_TREE` makes a copy-on-write clone in seconds, and Lake accepts the cloned build outputs without rebuilding. Clone from a tree that no build is writing to.

Start with two or three workers and raise the count only when the board shows workers waiting on agents, not on builds.

## Workers

- **Claude**: subagents on Opus 5.5 at medium effort. This is the default; it has handled every packet so far.
- **Codex**: Sol 6.2 (`gpt-6.2-sol`) at medium effort, launched from Claude Code with the `codex` skill. Tested on two real failing modules: it fixed both within the rules in under two minutes.
- Sign each worker's posts with a distinct `BOARD_AGENT` so results can be compared by model.

### Briefing a Codex worker

- Point it at its own cloned tree and give the exact build command, with `ELAN_HOME` set to the shared toolchain folder. It only reads the toolchain.
- In its default sandbox Codex can edit files, run `lake` and reach GitHub, but it cannot write to git. That is all a worker needs: it fixes modules and reports, and you commit and ship.
- Paste the rules from [WORKER.md](WORKER.md) into the brief and ask for a fixed final format. Codex starts with no context.
- Check its work yourself before shipping: rebuild the modules, list every file it touched, and read the diff against the pinned source.

## Rules

- Upstream's `PORTING.md` governs. Read it at the start of every session; it changes.
- Never hold a claim nobody is working on. Close the upstream issue and set the thread to `dropped`.
- Never push to upstream `main`. Our work goes up as PRs from the fork.
- When a worker is blocked, either reassign the module or submit the packet's ready subset under upstream's partial-submission rules. Do not let one hard module hold 63 finished ones.

## Lessons from the first mayor shift (2026-11-22)

- **Claims.** Upstream allows at most 8 open `Port Pxxxx` claims per contributor and releases a partial packet's claim when its PR merges (PORTING.md, "Release on merge & 8-packet cap"). Every PR, partial or full, says `Closes #N`. At the cap, idle workers wait for merges: `scripts/wait-slot.sh` wakes you when a slot frees.
- **Pick big packets.** `port.py next` prints a packet's size, not its ready count. `scripts/claim.sh` ranks packets by ready modules computed from the tracker and tries the largest first.
- **One ship at a time.** `claim`, `ship`, `publish` and `pr` all use the one upstream checkout and switch branches in it. Run them strictly in sequence. Never edit a script while a run of it is in flight: bash reads scripts as it goes.
- **Audits gate the ship.** `ship.sh` runs both `islattice_audit.lean` (any hit fails) and `reused_audit.lean`. A reused-name hit stops the ship until the mayor confirms the side condition from the declaration's own hypotheses; then re-run with `REUSED_REVIEWED=1`. `records` accepts notes only for patched modules, so `publish.sh` moves audit notes for unchanged modules into the PR body.
- **Review every worker patch.** Grep the patches for `sorry`, `admit`, `axiom`, `native_decide`, `unsafe`, `implemented_by` and `set_option backward`. Upstream has merged no `backward.*` flag; one Codex patch added one that the plain proof did not need.
- **Repeat submissions of a packet** need fresh release tags and branches: `TAG_SUFFIX=-b` (then `-c`). `ship.sh` re-applies already-merged member patches before `diff`.
- **Workers.** Run builds in the foreground: a background build's notification may never reach a subagent. A cold `check` can exceed the 10-minute tool limit; re-running resumes from Lake's cache. New work trees are `cp -cRp` clones of an idle tree, which cost almost no disk.
- **Codex and Opus 5.5 medium both did the job.** Across nine packets, both workers followed the brief, posted to the board and produced patches that passed review. RD #6 has the numbers.
