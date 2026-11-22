#!/bin/bash
# claims one packet upstream and opens its board thread
export BOARD_AGENT="mayor · opus-5.5"
out=$($HOME/code/rh/claim.sh 2>&1); echo "$out"
line=$(echo "$out" | grep "github.com/.*/issues/" | tail -1) || { echo NO_CLAIM; exit 1; }
P=${line%%:*}; URL=$(echo "$line" | grep -o 'https://[^ ]*')
cd $HOME/code/rh/alpoge-rh-replay; N=$(python3 tracker/port.py show $P --ready-only | wc -l | tr -d ' ')
printf 'Upstream claim: %s\n\n%s ready modules at claim time. Assigned by the mayor; the worker will post here.\n' "$URL" "$N" | $HOME/code/rh/board/bin/board open $P packet state:claimed
echo "CLAIMED $P $URL ready=$N"
