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

Two builds in the same tree collide. Give each concurrent worker its own work tree, or run their builds one at a time. Start with two or three workers and raise the count only when the board shows workers waiting on agents, not on builds.

## Workers

- **Claude**: subagents on Opus 5.5 at medium effort. This is the default; it has handled every packet so far.
- **Codex**: launched from Claude Code with the `codex` skill.
- Sign each worker's posts with a distinct `BOARD_AGENT` so results can be compared by model.

## Rules

- Upstream's `PORTING.md` governs. Read it at the start of every session; it changes.
- Never hold a claim nobody is working on. Close the upstream issue and set the thread to `dropped`.
- Never push to upstream `main`. Our work goes up as PRs from the fork.
- When a worker is blocked, either reassign the module or submit the packet's ready subset under upstream's partial-submission rules. Do not let one hard module hold 63 finished ones.
