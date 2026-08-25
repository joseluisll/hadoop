#!/usr/bin/env bash
# Rung 6: compile Tez against each Hadoop ref. -pl tez-dag -am covers the core
# chain (hadoop-shim, tez-api, tez-common, runtime, mapreduce, dag) and skips
# tez-ui, docs and tez-dist, which need node and are not on the HTTP path.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"
SRC="$W/downstream/tez"

for ref in trunk phase-c; do
  cd "$SRC" || exit 1
  "$MVN" -B clean >/dev/null 2>&1
  echo "=== tez against $ref ==="
  date -u +"START %H:%M:%SZ"
  "$MVN" -B install -DskipTests \
      -Dhadoop.version=3.6.0-SNAPSHOT \
      -pl tez-dag -am \
      -Dmaven.repo.local="$W/refs/$ref/repo" \
      -Dmaven.repo.local.tail="$W/m2-tail" \
      > "$W/logs/rung6-tez-$ref.log" 2>&1
  rc=$?
  date -u +"END %H:%M:%SZ"
  echo "exit=$rc"
  if [ $rc -ne 0 ]; then
    echo "--- first compilation errors ---"
    grep -E '^\[ERROR\].*\.java:|^\[ERROR\] Failed to execute' \
      "$W/logs/rung6-tez-$ref.log" | head -8
    echo "--- distinct error symbols ---"
    grep -oE 'cannot find symbol|package [a-z.]+ does not exist|incompatible types|method .* not found' \
      "$W/logs/rung6-tez-$ref.log" | sort | uniq -c | sort -rn | head -6
  fi
done
echo "RUNG6 TEZ DONE"
