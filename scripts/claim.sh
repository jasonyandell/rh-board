#!/bin/bash
# claims the free packet with the most ready modules (port.py claim enforces reservations and the 8-claim cap)
cd $HOME/code/rh/alpoge-rh-replay && git checkout -q main && git pull -q --ff-only
C=$(python3 - <<'PY'
import gzip,json,os,collections
done={f[:-5] for f in os.listdir('port/patches') if f.endswith('.json')}
pr=set(open('port/pruned.txt').read().split())
ready=collections.Counter()
for l in gzip.open('tracker/modules.jsonl.gz','rt'):
    r=json.loads(l)
    if r['id'] in done or r['id'] in pr: continue
    if all(i in done for i in r['imports']): ready[r['packet']]+=1
print(' '.join(p for p,n in ready.most_common(40) if n>=5))
PY
)
for p in $C; do out=$(python3 tracker/port.py claim $p 2>&1 | tail -1); echo "$p: $out"; echo "$out" | grep -q "github.com/.*/issues/" && exit 0; echo "$out" | grep -qi "at most\|cap\|limit" && { echo CAP_REACHED; exit 2; }; done
echo NO_CLAIM; exit 1
