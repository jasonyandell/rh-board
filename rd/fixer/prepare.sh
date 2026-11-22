#!/bin/bash
# Snapshot upstream inputs into rd/fixer/cache/ (gitignored). Read-only on the upstream checkout.
#   REPLAY=/path/to/alpoge-rh-replay ./prepare.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
: "${REPLAY:?set REPLAY to an alpoge-rh-replay checkout}"
mkdir -p "$here/cache/up"
git -C "$REPLAY" fetch -q origin
git -C "$REPLAY" rev-parse origin/main > "$here/cache/upstream-commit.txt"
git -C "$REPLAY" archive origin/main port tracker -o "$here/cache/up.tar"
tar -xf "$here/cache/up.tar" -C "$here/cache/up"
git -C "$REPLAY" log origin/main --diff-filter=A --name-only --format=COMMIT_%H_%ct -- port/patches/ \
  > "$here/cache/addlog.txt"
echo "snapshot of $(cat "$here/cache/upstream-commit.txt") in $here/cache"
