#!/usr/bin/env bash
# Expand each candidate's sparse checkout to its Java sources, then find every
# import of an org.eclipse.jetty package. Tez broke on exactly this: a Jetty
# import satisfied by a jar borrowed from Hadoop's transitive closure.
set -u
D=/home/user/dcheck-work/downstream
OUT=/home/user/dcheck-work/logs/jetty-imports.txt
: > "$OUT"

for p in hbase knox hive ranger atlas oozie spark ozone tez; do
  [ -d "$D/$p" ] || continue
  if [ -f "$D/$p/.git/info/sparse-checkout" ] || \
     git -C "$D/$p" config --get core.sparseCheckout >/dev/null 2>&1; then
    git -C "$D/$p" sparse-checkout set --no-cone '/*' >/dev/null 2>&1 || true
  fi
  n=$(find "$D/$p" -name '*.java' 2>/dev/null | wc -l)
  echo "### $p ($n java files)" >> "$OUT"
  grep -rhoE '^import (static )?org\.eclipse\.jetty\.[A-Za-z0-9_.]+' \
      "$D/$p" --include='*.java' 2>/dev/null \
    | sed -E 's/^import (static )?//; s/\.[A-Z][A-Za-z0-9_]*$//; s/\.[a-z0-9_]+$//' \
    | sort | uniq -c | sort -rn >> "$OUT" 2>/dev/null
  echo >> "$OUT"
done
echo "IMPORT SCAN DONE" >> "$OUT"
cat "$OUT"
