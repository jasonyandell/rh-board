#!/bin/bash
# exits when we hold fewer than CAP open "Port P" claims upstream (a PR merged and released one)
R=rohanarun/alpoge-rh-replay; CAP=${1:-8}
while true; do
  n=$(gh api "repos/$R/issues?creator=${PORT_USER:-$(gh api user --jq .login)}&state=open&per_page=100" --jq '[.[]|select(.pull_request|not)|select(.title|startswith("Port P"))]|length' 2>/dev/null)
  if [ -n "$n" ] && [ "$n" -lt "$CAP" ]; then echo "SLOTS_FREE open_claims=$n"; exit 0; fi
  echo "$(date -u +%H:%M) open_claims=$n" >> $HOME/code/rh/wait-slot.log
  sleep 300
done
