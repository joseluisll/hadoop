#!/usr/bin/env bash
# The 25 relocation-touched modules not covered by the first full-suite run.
#
# Ordered by how much the module has to say about the relocation, not by size:
# the modules that embed HttpServer2 or serve HTTP go first, so a partial run
# is still worth reading. The giants (hdfs, resourcemanager, nodemanager,
# jobclient, minicluster) sit at the end where their cost buys the least
# marginal signal.
#
# Both refs run the same module back to back, so a module's two results are
# always comparable even if the run is cut short later.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"
OUT=$W/logs/remaining
mkdir -p "$OUT"
PER_MODULE_TIMEOUT=5400   # 90 min; a module that needs longer is reported, not waited on

MODULES="
hadoop-hdfs-project/hadoop-hdfs-httpfs
hadoop-common-project/hadoop-kms
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-web-proxy
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-applications/hadoop-yarn-services/hadoop-yarn-services-api
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-applicationhistoryservice
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-router
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-globalpolicygenerator
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-common
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-client
hadoop-common-project/hadoop-nfs
hadoop-hdfs-project/hadoop-hdfs-nfs
hadoop-common-project/hadoop-auth-examples
hadoop-tools/hadoop-sls
hadoop-tools/hadoop-resourceestimator
hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-app
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-applications/hadoop-yarn-applications-catalog/hadoop-yarn-applications-catalog-webapp
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice-hbase-tests
hadoop-client-modules/hadoop-client-runtime
hadoop-client-modules/hadoop-client-minicluster
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-nodemanager
hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-resourcemanager
hadoop-hdfs-project/hadoop-hdfs
hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-jobclient
"

run_one() {
  local label=$1 src=$2 repo=$3 module=$4 tag=$5
  local log="$OUT/$tag-$label.log"
  cd "$src" || return 1
  # Maven recompiles on changed SOURCES, not on changed dependencies. A test
  # class compiled against an earlier build of hadoop-common survives a
  # dependency swap and then throws NoSuchMethodError against the new jars,
  # which reads exactly like a regression and is not one. Force the compile.
  rm -rf "$module/target/classes" "$module/target/test-classes"
  timeout $PER_MODULE_TIMEOUT "$MVN" -B test -pl "$module" -fae \
      -Dmaven.repo.local="$W/refs/$repo/repo" \
      -Dmaven.repo.local.tail="$W/m2-tail" \
      -Dsurefire.rerunFailingTestsCount=0 \
      > "$log" 2>&1
  echo $?
}

for module in $MODULES; do
  tag=$(basename "$module")
  echo "################ $tag ################"
  date -u +"  start %H:%M:%SZ"
  for pair in "baseline:$W/refs/phase-c/src:phase-c" "relocated:$W/refs/shaded/src:shaded"; do
    label=${pair%%:*}; rest=${pair#*:}; src=${rest%%:*}; repo=${rest##*:}
    rc=$(run_one "$label" "$src" "$repo" "$module" "$tag")
    tot=$(grep -hoE 'Tests run: [0-9]+, Failures: [0-9]+, Errors: [0-9]+, Skipped: [0-9]+' \
            "$OUT/$tag-$label.log" 2>/dev/null | tail -1)
    printf "  %-10s exit=%-3s %s\n" "$label" "$rc" "${tot:-<no surefire summary>}"
    # Failing test names, for the by-name diff that matters more than totals.
    grep -oE '^\[ERROR\]   [A-Za-z0-9_.]+' "$OUT/$tag-$label.log" 2>/dev/null \
      | sed 's/^\[ERROR\]   //' | sort -u > "$OUT/$tag-$label.names"
  done
  only_reloc=$(comm -13 "$OUT/$tag-baseline.names" "$OUT/$tag-relocated.names" 2>/dev/null | tr '\n' ' ')
  only_base=$(comm -23 "$OUT/$tag-baseline.names" "$OUT/$tag-relocated.names" 2>/dev/null | tr '\n' ' ')
  echo "  REGRESSIONS (only relocated): ${only_reloc:-none}"
  echo "  only baseline               : ${only_base:-none}"
  date -u +"  end   %H:%M:%SZ"
  # HDFS and YARN tests leave large trees behind; the box has ~16G.
  find "$W/refs" -maxdepth 6 -type d \( -name 'test-dir' -o -name 'tmp' \) -path '*/target/*' \
       -exec rm -rf {} + 2>/dev/null
  echo
done
echo "REMAINING SUITES DONE"
