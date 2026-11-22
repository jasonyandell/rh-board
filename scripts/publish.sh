#!/bin/bash
# usage: publish.sh P0123 ISSUE  (after ship.sh; notes in ~/code/rh/P0123-notes.json)
set -eo pipefail
P=$1; I=$2; REPO=$HOME/code/rh/alpoge-rh-replay; OUT=$HOME/code/rh/out-$P; TMP=${CLAUDE_JOB_DIR:-/tmp}/tmp
D=$(date -u +%Y%m%d); TAG=port-$P-lean436-$D${TAG_SUFFIX:-}; FORK=jasonyandell/alpoge-rh-replay
BASE=https://github.com/$FORK/releases/download/$TAG
cd $REPO
git checkout -q main
FILES="$P-build.log $P-receipt.json $P-module-logs.tar.gz $P-islattice-audit.log"; [ -f $OUT/$P-reused-audit.log ] && FILES="$FILES $P-reused-audit.log"
(cd $OUT && gh release create $TAG -R $FORK --target main --title "Port $P evidence (Lean 4.36.0, Mathlib v4.36.0)" \
  --notes "Build evidence for rohanarun/alpoge-rh-replay#$I: port of $P ready modules to Lean 4.36.0 / Mathlib fc4f59e." $FILES >/dev/null)
mkdir -p $TMP/dl-$P; for f in $FILES; do curl -sfL -o $TMP/dl-$P/$f $BASE/$f; cmp -s $TMP/dl-$P/$f $OUT/$f || { echo "ASSET MISMATCH $f"; exit 1; }; done; echo "assets verified"
# records accepts notes only for patched modules: keep those, save the rest (audit explanations for unchanged modules) for the PR body
python3 - $P $HOME/code/rh/$P-notes.json $TMP/notes-patched-$P.json $TMP/notes-unpatched-$P.json <<'PY'
import json,os,sys
P,src,keep,rest=sys.argv[1:]
d=json.load(open(src)); k={m:v for m,v in d.items() if os.path.exists(f'port/patches/{m}.patch')}
json.dump(k,open(keep,'w'),indent=2); json.dump({m:v for m,v in d.items() if m not in k},open(rest,'w'),indent=2)
PY
python3 tracker/port_build.py records $P ${WORK:-$HOME/code/rh/work} --ready-only --evidence $BASE/$P-receipt.json --notes $TMP/notes-patched-$P.json | head -1
python3 tracker/validate_ports.py | tail -1 > $TMP/validate-$P.txt; cat $TMP/validate-$P.txt
python3 - $P $HOME/code/rh/$P-notes.json > $TMP/summary-$P.md <<'PY'
import gzip,json,os,sys,subprocess
P=sys.argv[1]; notes=json.load(open(sys.argv[2]))
rows=[json.loads(l) for l in gzip.open('tracker/modules.jsonl.gz','rt')]
done_main=set(subprocess.check_output(['git','ls-tree','--name-only','origin/main','port/patches/'],text=True).split())
done_main={os.path.basename(x)[:-5] for x in done_main if x.endswith('.json')}
mine={x[:-5] for x in subprocess.check_output(['git','ls-files','--others','--exclude-standard','port/patches/'],text=True).split() for x in [os.path.basename(x)] if x.endswith('.json')}
pr=set(open('port/pruned.txt').read().split())
done=done_main|mine
pk=[r for r in rows if r['packet']==P]
sub=sorted(mine); patched=[m for m in sub if os.path.exists(f'port/patches/{m}.patch')]
rem=[(r['id'],[i for i in r['imports'] if i not in done]) for r in pk if r['id'] not in done and r['id'] not in pr]
pruned=[r['id'] for r in pk if r['id'] in pr]
full=not rem
print(f"SUB={len(sub)} PATCHED={len(patched)} UNCH={len(sub)-len(patched)} REM={len(rem)} FULL={int(full)}")
print("Submitted IDs: "+", ".join(f"`{m}`" for m in sub)+".\n")
if rem:
  print("Remaining live modules and their missing imports:\n")
  for m,miss in rem: print(f"- `{m}`: missing imports "+", ".join(f"`{x}`" for x in miss))
  print()
print("Excluded upstream-pruned IDs: "+(", ".join(f"`{x}`" for x in pruned) or "none")+".\n")
print("### Equivalence notes\n")
for m in patched: print(f"- `{m}`: {notes.get(m,'(missing note)')}")
PY
head -1 $TMP/summary-$P.md
echo "TAG=$TAG"
