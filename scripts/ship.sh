#!/bin/bash
# usage: ship.sh P0123 ISSUE   -> check, IsLattice audit, diff, clean reproduce (ready-only)
set -e
P=$1; I=$2; W=$HOME/code/rh/work; REPO=$HOME/code/rh/alpoge-rh-replay; OUT=$HOME/code/rh/out-$P
export PATH="/opt/homebrew/opt/gpatch/libexec/gnubin:/opt/homebrew/opt/diffutils/bin:$PATH"
cd $REPO
python3 tracker/port_build.py check $P $W --ready-only > $HOME/code/rh/check-$P.log 2>&1 || { grep -v "^Skipping" $HOME/code/rh/check-$P.log | tail -20; echo CHECK_FAILED; exit 1; }
tail -1 $HOME/code/rh/check-$P.log
grep -i "reused\|REUSED" $HOME/code/rh/check-$P.log || true
python3 - $P <<'PY' > $HOME/code/rh/mods-$P.txt
import gzip,json,subprocess,sys
ids=set(l.split()[0] for l in subprocess.check_output(['python3','tracker/port.py','show',sys.argv[1],'--ready-only'],text=True).splitlines() if l.strip())
for l in gzip.open('tracker/modules.jsonl.gz','rt'):
    r=json.loads(l)
    if r['id'] in ids: print(r['module'])
PY
(export ELAN_HOME=$W/elan XDG_CACHE_HOME=$W/cache PATH=$W/elan/bin:$PATH; cd $W/lean && xargs lake env lean --run $REPO/port/islattice_audit.lean < $HOME/code/rh/mods-$P.txt) > $HOME/code/rh/audit-$P.log 2>&1 || { cat $HOME/code/rh/audit-$P.log; echo AUDIT_FAILED; exit 1; }
cat $HOME/code/rh/audit-$P.log | tail -3
python3 tracker/port_build.py diff $P $W
rm -rf $OUT
python3 tracker/port_build.py reproduce $P $W $OUT --ready-only --issue $I > $HOME/code/rh/reproduce-$P.log 2>&1 || { tail -30 $HOME/code/rh/reproduce-$P.log; echo REPRO_FAILED; exit 1; }
grep "== done\|exit=[^0]" $HOME/code/rh/reproduce-$P.log
cp $HOME/code/rh/audit-$P.log $OUT/$P-islattice-audit.log
echo SHIP_OK
