#!/usr/bin/env bash
# Rung 6: compile Ozone's hdds-server-framework against each Hadoop ref.
# That module holds BaseHttpServer, which wraps Hadoop's HttpServer2 and is
# where Ozone's org.eclipse.jetty.servlet imports live. -am pulls its own
# dependency chain so the reactor resolves without a full Ozone build.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"
SRC="$W/downstream-ozone"

for ref in trunk phase-c; do
  cd "$SRC" || exit 1
  echo "=== ozone hdds-server-framework against $ref ==="
  date -u +"START %H:%M:%SZ"
  "$MVN" -B install -DskipTests -DskipRecon -Dmaven.javadoc.skip=true \
      -Dhadoop.version=3.6.0-SNAPSHOT \
      -pl hadoop-hdds/framework -am \
      -Dmaven.repo.local="$W/refs/$ref/repo" \
      -Dmaven.repo.local.tail="$W/m2-tail" \
      > "$W/logs/rung6-ozone-$ref.log" 2>&1
  rc=$?
  date -u +"END %H:%M:%SZ"
  echo "exit=$rc"
  if [ $rc -ne 0 ]; then
    echo "--- compilation errors ---"
    grep -E '^\[ERROR\].*\.java:\[' "$W/logs/rung6-ozone-$ref.log" | head -10
    echo "--- goal that failed ---"
    grep -E '^\[ERROR\] Failed to execute goal' "$W/logs/rung6-ozone-$ref.log" | head -2
  fi
  echo "--- jetty artifacts actually resolved ---"
  grep -oE 'org/eclipse/jetty/[a-z0-9/.-]+/[0-9][^/]*/' "$W/logs/rung6-ozone-$ref.log" \
    | sed 's|/$||' | awk -F/ '{print $(NF-1)":"$NF}' | sort -u | head -12
  echo
done
echo "RUNG6 OZONE DONE"
