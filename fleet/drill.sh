#!/usr/bin/env bash
# Five writers, twenty transactions each. Does busy_timeout matter?
#
# Usage: ./fleet/drill.sh [busy_timeout_ms]   (default 0, meaning no waiting)
#
# Rows landed can move run to run at low timeouts, and your machine will differ
# from anyone else's, so run it several times and write down the range you get.
TIMEOUT="${1:-0}"

command -v sqlite3 >/dev/null || { echo "this drill needs the sqlite3 CLI on PATH" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"

: > errors.txt
sqlite3 drill.db "PRAGMA journal_mode=WAL; CREATE TABLE t (id INTEGER PRIMARY KEY, who TEXT);" >/dev/null

# One statement per line, because -bail does not stop within a single argument:
# after a failed BEGIN the CLI would still run the INSERT, outside a transaction.
worker() {
  for i in $(seq 1 20); do
    printf "PRAGMA busy_timeout=$TIMEOUT;\nBEGIN IMMEDIATE;\nINSERT INTO t (who) VALUES ('w$1');\nCOMMIT;\n" \
      | sqlite3 -bail drill.db >/dev/null 2>>errors.txt
  done
}

start=$(python3 -c 'import time;print(time.time())')
for w in 1 2 3 4 5; do worker "$w" & done
wait
end=$(python3 -c 'import time;print(time.time())')

rows=$(sqlite3 drill.db "SELECT COUNT(*) FROM t;")
errs=$(grep -c . errors.txt || true)
printf "busy_timeout=%-5s  rows=%3s/100  errors=%-3s  wall=%.3fs\n" \
  "$TIMEOUT" "$rows" "$errs" "$(python3 -c "print($end-$start)")"
[ "$errs" -gt 0 ] && echo "  first error: $(head -1 errors.txt)"
exit 0