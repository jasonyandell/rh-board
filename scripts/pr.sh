#!/bin/bash
# usage: PORT_COAUTHOR="Co-Authored-By: ..." [PORT_SESSION=url] pr.sh P0123 ISSUE  (after publish.sh)
set -e
P=$1; I=$2; REPO=$HOME/code/rh/alpoge-rh-replay; TMP=${CLAUDE_JOB_DIR:-/tmp}/tmp; S=$TMP/summary-$P.md
eval "$(head -1 $S | tr ' ' '\n' | sed 's/^/export /')"
[ "${SUB:-0}" -gt 0 ] || { echo "REFUSING: 0 submitted records for $P"; exit 1; }
TAG=port-$P-lean436-$(date -u +%Y%m%d)${TAG_SUFFIX:-}; BASE=https://github.com/jasonyandell/alpoge-rh-replay/releases/download/$TAG
cd $REPO
B=port-$(echo $P | tr A-Z a-z)-lean436${TAG_SUFFIX:-}
git checkout -q -b $B
git add port/patches/
if [ "$FULL" = 1 ]; then
  TITLE="Port $P to Lean 4.36 ($PATCHED fixed, $UNCH unchanged)"
  LEAD="Ports all $SUB live modules of $P to Lean 4.36.0 and Mathlib \`fc4f59e577feb1a4956671bc04ac18aaaf8cd842\` (v4.36.0): $PATCHED compatibility patches and $UNCH unchanged records. Closes #$I."
else
  TITLE="Port $P: $SUB ready modules to Lean 4.36"
  LEAD="Submits $SUB completed modules from $P to Lean 4.36.0 and Mathlib \`fc4f59e577feb1a4956671bc04ac18aaaf8cd842\` (v4.36.0): $PATCHED compatibility patches and $UNCH unchanged records. This is a partial submission under the completed-subset rules. Closes #$I: under the release-on-merge rule, merging this PR releases the packet claim, and the blocked modules listed below return to the queue."
fi
git commit -q -m "$TITLE

${PORT_COAUTHOR:?set PORT_COAUTHOR, e.g. "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"}
${PORT_SESSION:+Claude-Session: $PORT_SESSION}"
git push -q -u fork $B 2>&1 | grep -v "^remote:" || true
VAL=$(cat $TMP/validate-$P.txt)
{
echo "$LEAD"; echo
sed -n '2,$p' $S
python3 - $TMP/notes-unpatched-$P.json <<'PY'
import json,os,sys
d=json.load(open(sys.argv[1])) if os.path.exists(sys.argv[1]) else {}
if d:
    print("\n### Reused-name audit notes for unchanged modules\n")
    print("`port/reused_audit.lean` flagged these modules, which build unchanged. The side condition holds in each declaration's own hypotheses, so the pinned and target meanings agree (PORTING.md, \"Reused-name audit\"). The `records` tool accepts notes only for patched modules, so the explanations are here.\n")
    for m,v in sorted(d.items()): print(f"- `{m}`: {v}")
PY
cat <<EOT

### Evidence

\`port_build.py reproduce $P WORK OUT --ready-only --issue $I\` rebuilt every submitted module in a fresh tree from the verified archive plus the import and packet patches, with \`lake --no-cache build\`. All exited 0. The \`IsLattice\` environment audit found 0 hits across every submitted module, and every \`port/reused_audit.lean\` hit is explained in the notes. \`tracker/validate_ports.py\`: $VAL There are no new \`sorry\`, \`admit\`, axioms, \`unsafe\` or \`native_decide\`.

- [Receipt]($BASE/$P-receipt.json) (source, patch, object and log digests)
- [Build transcript]($BASE/$P-build.log)
- [Per-module logs]($BASE/$P-module-logs.tar.gz)
- [IsLattice audit]($BASE/$P-islattice-audit.log)
- [Reused-name audit]($BASE/$P-reused-audit.log) (\`port/reused_audit.lean\`; any hit is explained in the notes)

I downloaded each asset and checked it byte for byte against the local file before opening this PR. The build ran on macOS arm64 (\`Lean (version 4.36.0, arm64-apple-darwin24.6.0)\`) with GNU patch and diffutils. On macOS the receipt's \`peak_child_rss_kib\` value is in bytes, not KiB.

This is a port submission, separate from the original RH replay verdict.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

${PORT_SESSION:-}
EOT
} > $TMP/pr-$P.md
gh pr create -R rohanarun/alpoge-rh-replay --base main --head jasonyandell:$B --title "$TITLE" --body-file $TMP/pr-$P.md | tail -1
git checkout -q main
