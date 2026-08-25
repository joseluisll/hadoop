#!/usr/bin/env bash
# Full module test suites for the modules the Jetty relocation touches, on both
# the baseline (phase-c) and the relocated build. Not all of Hadoop: that is
# many hours per ref and needs clusters this container does not have.
set -u
W=/home/user/dcheck-work
MVN="$W/tools/apache-maven-3.9.15/bin/mvn"

# hadoop-auth is HADOOP-19971's surface; hadoop-common holds HttpServer2;
# yarn-common holds WebApps, which the inline attempt broke.
MODULES="hadoop-common-project/hadoop-auth,hadoop-common-project/hadoop-common,hadoop-yarn-project/hadoop-yarn/hadoop-yarn-common"

for pair in "baseline:$W/refs/phase-c/src:phase-c" "relocated:$W/refs/shaded/src:shaded"; do
  label=${pair%%:*}; rest=${pair#*:}; src=${rest%%:*}; repo=${rest##*:}
  cd "$src" || continue
  echo "################ $label ################"
  date -u +"START %H:%M:%SZ"
  timeout 14400 "$MVN" -B test -pl "$MODULES" -fae \
      -Dmaven.repo.local="$W/refs/$repo/repo" \
      -Dmaven.repo.local.tail="$W/m2-tail" \
      -Dsurefire.rerunFailingTestsCount=0 \
      > "$W/logs/full-$label.log" 2>&1
  echo "exit=$?"
  date -u +"END %H:%M:%SZ"
  # per-module totals
  grep -E '^\[INFO\] Tests run:.*Skipped: [0-9]+$|^\[ERROR\] Tests run:.*Skipped: [0-9]+$' \
    "$W/logs/full-$label.log" | tail -5
  echo "  failed tests:"
  grep -E '^\[ERROR\]   [A-Za-z0-9_]+\.' "$W/logs/full-$label.log" | sed 's/^/    /' | head -25
  echo
done
echo "FULL SUITE DONE"
