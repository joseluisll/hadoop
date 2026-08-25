#!/usr/bin/env bash
# Rung 6 + linkage, generalised from the Ozone finding.
#
# For each candidate: find a module that depends on hadoop-common, build just
# that module's chain against each Hadoop ref, then load Hadoop's HttpServer2
# on the module's resolved classpath. Compiling proves source compatibility;
# loading the class proves the Jetty stack underneath it is coherent. Ozone
# passed the first and failed the second.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"
PROBE=/tmp

run_project() {
  local proj="$1" src="$2" module="$3"
  echo "################ $proj ($module) ################"
  for ref in trunk phase-c; do
    cd "$src" || return 1
    local log="$W/logs/linkage-$proj-$ref.log"
    "$MVN" -B install -DskipTests -Dmaven.javadoc.skip=true -Drat.skip=true \
        -Dhadoop.version=3.6.0-SNAPSHOT \
        -pl "$module" -am \
        -Dmaven.repo.local="$W/refs/$ref/repo" \
        -Dmaven.repo.local.tail="$W/m2-tail" > "$log" 2>&1
    local brc=$?
    local cp="/tmp/cp-$proj-$ref.txt"
    rm -f "$cp"
    "$MVN" -B -q dependency:build-classpath -Dhadoop.version=3.6.0-SNAPSHOT \
        -pl "$module" -Dmdep.outputFile="$cp" \
        -Dmaven.repo.local="$W/refs/$ref/repo" \
        -Dmaven.repo.local.tail="$W/m2-tail" >> "$log" 2>&1
    local link="classpath unavailable"
    if [ -s "$cp" ]; then
      link=$(java -cp "$PROBE:$(cat "$cp")" RtProbe 2>&1 \
             | grep -E '^RESULT:' | head -1)
      [ -z "$link" ] && link="probe produced no RESULT line"
    fi
    local jetty
    jetty=$(grep -oE 'org/eclipse/jetty[a-z0-9/.-]*/[0-9][^/]*/' "$cp" 2>/dev/null \
            | awk -F/ '{print $(NF-1)}' | sort -u | tr '\n' ' ')
    printf '  %-8s build=%-3s  %s\n' "$ref" \
      "$([ $brc -eq 0 ] && echo ok || echo FAIL)" "$link"
    printf '           jetty versions: %s\n' "${jetty:-none}"
    if [ $brc -ne 0 ]; then
      grep -E '^\[ERROR\].*\.java:\[' "$log" | head -3 | sed 's/^/           /'
    fi
  done
  echo
}

# module chosen as one that depends on hadoop-common
run_project knox   "$W/downstream/knox"   gateway-server
run_project hive   "$W/downstream/hive"   common
run_project atlas  "$W/downstream/atlas"  common
run_project hbase  "$W/downstream/hbase"  hbase-common
echo "LINKAGE SWEEP DONE"
