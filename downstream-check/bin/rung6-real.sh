#!/usr/bin/env bash
# Real builds for Knox and Hive, then the linkage probe on the classpath their
# own reactor produces. Modules chosen because each declares both Hadoop and
# Jetty, so the combination that broke Ozone is actually present.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"

probe() {
  local proj="$1" src="$2" module="$3"
  echo "################ $proj / $module ################"
  for ref in trunk phase-c; do
    cd "$src" || return
    local log="$W/logs/real-$proj-$ref.log"
    date -u +"  $ref START %H:%M:%SZ"
    "$MVN" -B install -DskipTests -Dmaven.javadoc.skip=true -Drat.skip=true \
        -Dhadoop.version=3.6.0-SNAPSHOT -Dspotbugs.skip=true -Dforbiddenapis.skip=true -Dmdep.analyze.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true -Dmaven.test.skip=true -pl "$module" -am \
        -Dmaven.repo.local="$W/refs/$ref/repo" \
        -Dmaven.repo.local.tail="$W/m2-tail" > "$log" 2>&1
    local brc=$?
    date -u +"  $ref END   %H:%M:%SZ"
    echo "  build exit=$brc"
    if [ $brc -ne 0 ]; then
      grep -E '^\[ERROR\].*\.java:\[' "$log" | head -4 | sed 's/^/    /'
      grep -E '^\[ERROR\] Failed to execute goal' "$log" | head -1 | sed 's/^/    /'
    fi
    local cp="/tmp/real-$proj-$ref.txt"; rm -f "$cp"
    "$MVN" -B -q dependency:build-classpath -Dhadoop.version=3.6.0-SNAPSHOT \
        -pl "$module" -Dmdep.outputFile="$cp" \
        -Dmaven.repo.local="$W/refs/$ref/repo" \
        -Dmaven.repo.local.tail="$W/m2-tail" >> "$log" 2>&1
    if [ -s "$cp" ]; then
      echo -n "  linkage: "
      java -cp "/tmp:$(cat "$cp")" RtProbe 2>&1 | grep -E '^RESULT:' | head -1
      echo -n "  jetty:   "
      grep -oE 'org/eclipse/jetty[a-z0-9/.-]*/[0-9][^/]*/' "$cp" \
        | awk -F/ '{print $(NF-1)}' | sort -u | tr '\n' ' '; echo
    else
      echo "  linkage: classpath unavailable"
    fi
  done
  echo
}

probe knox "$W/downstream/knox" gateway-server

echo "REAL BUILDS DONE"
