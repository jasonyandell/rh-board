#!/bin/bash
# claims the first available packet (whole packets first, then partial by readiness)
cd $HOME/code/rh/alpoge-rh-replay && git checkout -q main && git pull --ff-only -q
C=$( (python3 tracker/port.py next; python3 tracker/port.py next --include-partial) 2>/dev/null | awk '{print $1}' | awk '!s[$0]++' | head -15)
for p in $C; do out=$(python3 tracker/port.py claim $p 2>&1 | tail -1); echo "$p: $out"; echo "$out" | grep -q "github.com/.*/issues/" && exit 0; done
echo NO_CLAIM; exit 1
