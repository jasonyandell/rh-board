#!/bin/bash
# usage: audit.sh P0123 WORK   -> reused-name environment audit (IsLattice, multiplicity, eLpNorm, Measure.map/prod, NoAtoms, ...) over every ready module
P=$1; W=$2; REPO=$HOME/code/rh/alpoge-rh-replay
export ELAN_HOME=$W/elan XDG_CACHE_HOME=$W/cache PATH=$W/elan/bin:$PATH
cd $REPO && python3 - $P > $W/audit-mods-$P.txt <<'PY'
import gzip,json,subprocess,sys
ids={l.split()[0] for l in subprocess.check_output(['python3','tracker/port.py','show',sys.argv[1],'--ready-only'],text=True).splitlines() if l.strip()}
for l in gzip.open('tracker/modules.jsonl.gz','rt'):
    r=json.loads(l)
    if r['id'] in ids: print(r['module'])
PY
cd $W/lean && xargs lake env lean --run $REPO/port/reused_audit.lean < $W/audit-mods-$P.txt
