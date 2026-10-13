#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Usage: unit-tests.sh <baseline|candidate> [quick|full] [module-pattern]
#
# Runs the Maven tests of every module whose build phase A changes, plus the
# HTTP tests of the modules that use those servers, on the side's tree, and
# keeps the surefire/failsafe XML reports in results/<side>/unit/<module>/.
#
#   quick  tests that start a web server or exercise the Jersey test
#          container (the code phase A can affect), roughly 2-3 hours
#   full   every test of those modules, many hours
#
# Each failing test is re-run once (surefire.rerunFailingTestsCount) so a
# flaky test shows up as flaky, not failed. compare.sh lines up the two
# sides test by test.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
TIER="${2:-quick}"
PATTERN="${3:-}"
LOG_TAG="unit:${SIDE}"
OUT="$(results_dir "${SIDE}")/unit"
mkdir -p "${OUT}"

# module|quick-tier tests (surefire -Dtest syntax; empty = whole module in
# both tiers). Modules whose pom phase A changes come first.
MODULES=(
  "hadoop-common-project/hadoop-common|org/apache/hadoop/http/**/Test*,org/apache/hadoop/jmx/**/Test*,org/apache/hadoop/conf/TestConfServlet*,org/apache/hadoop/log/**/Test*,org/apache/hadoop/security/http/**/Test*,org/apache/hadoop/security/authentication/server/**/Test*"
  "hadoop-hdfs-project/hadoop-hdfs-httpfs|org/apache/hadoop/fs/http/server/**/Test*,org/apache/hadoop/fs/http/client/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-common|org/apache/hadoop/yarn/webapp/**/Test*,org/apache/hadoop/yarn/client/api/impl/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-client|org/apache/hadoop/yarn/client/api/impl/TestTimelineClient*,org/apache/hadoop/yarn/client/api/impl/TestAHSv2ClientImpl*,org/apache/hadoop/yarn/client/cli/TestLogsCLI*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-applicationhistoryservice|"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-globalpolicygenerator|"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-nodemanager|org/apache/hadoop/yarn/server/nodemanager/webapp/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-resourcemanager|org/apache/hadoop/yarn/server/resourcemanager/webapp/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-router|org/apache/hadoop/yarn/server/router/webapp/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-web-proxy|"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-applications/hadoop-yarn-applications-catalog/hadoop-yarn-applications-catalog-webapp|"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-app|org/apache/hadoop/mapreduce/v2/app/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-hs|org/apache/hadoop/mapreduce/v2/hs/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-shuffle|"
  "hadoop-mapreduce-project/hadoop-mapreduce-examples|"
  "hadoop-tools/hadoop-resourceestimator|"
  "hadoop-tools/hadoop-sls|org/apache/hadoop/yarn/sls/web/**/Test*,org/apache/hadoop/yarn/sls/TestSLSRunner*"
  # Not changed by phase A, but they run the servers whose classpath it
  # changes.
  "hadoop-common-project/hadoop-kms|org/apache/hadoop/crypto/key/kms/server/TestKMS.java,org/apache/hadoop/crypto/key/kms/server/TestKMSWithZK*"
  "hadoop-hdfs-project/hadoop-hdfs|org/apache/hadoop/hdfs/web/TestWebHDFS.java,org/apache/hadoop/hdfs/web/TestWebHdfsTokens*,org/apache/hadoop/hdfs/server/namenode/TestNameNodeHttpServer*,org/apache/hadoop/hdfs/server/datanode/web/**/Test*,org/apache/hadoop/hdfs/server/namenode/TestStartupProgressServlet*"
  "hadoop-hdfs-project/hadoop-hdfs-rbf|org/apache/hadoop/hdfs/server/federation/router/TestRouterHttpServerXFrame*,org/apache/hadoop/hdfs/server/federation/router/web/**/Test*,org/apache/hadoop/hdfs/server/federation/router/TestRouterWebHdfsMethods*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice|org/apache/hadoop/yarn/server/timelineservice/reader/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-jobclient|org/apache/hadoop/mapreduce/v2/TestMRJobsWithHistoryService*"
)
# The shaded client jars and the minicluster: invariant checks and the
# integration tests that use them from a downstream point of view.
CLIENT_MODULES=(
  hadoop-client-modules/hadoop-client-check-invariants
  hadoop-client-modules/hadoop-client-check-test-invariants
  hadoop-client-modules/hadoop-client-integration-tests
)

[[ -d "$(src_dir "${SIDE}")" ]] || die "run build.sh ${SIDE} first"

run_module() {
  local module=$1 tests=$2 goal=$3
  local key=${module//\//__}
  local dest="${OUT}/${key}"
  rm -rf "${dest}"
  mkdir -p "${dest}"
  # -nsu: never replace this side's installed SNAPSHOT jars with remote ones.
  local args=(-nsu "${goal}" -pl "${module}" -Dmaven.test.failure.ignore=true
              -Dsurefire.rerunFailingTestsCount="${UNIT_RERUNS:-1}"
              -Dfailsafe.rerunFailingTestsCount="${UNIT_RERUNS:-1}"
              -Dmaven.javadoc.skip=true -Dspotbugs.skip=true -Dcheckstyle.skip=true)
  if [[ "${TIER}" == quick && -n "${tests}" ]]; then
    args+=("-Dtest=${tests}" -Dsurefire.failIfNoSpecifiedTests=false)
  fi
  log "${module} (${TIER}${tests:+, $(tr ',' '\n' <<< "${tests}" | wc -l) patterns})"
  local start=${SECONDS} rc=0
  mvn_side "${SIDE}" "${args[@]}" > "${dest}/mvn.log" 2>&1 || rc=$?
  local src
  src="$(src_dir "${SIDE}")/${module}/target"
  cp "${src}"/surefire-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  cp "${src}"/failsafe-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  echo "${rc} $((SECONDS - start))" > "${dest}/status"
  log "${module}: maven exit ${rc}, $(ls "${dest}"/TEST-*.xml 2>/dev/null | wc -l) report files, $((SECONDS - start))s"
}

for entry in "${MODULES[@]}"; do
  module=${entry%%|*} tests=${entry#*|}
  [[ -z "${PATTERN}" || "${module}" =~ ${PATTERN} ]] || continue
  run_module "${module}" "${tests}" test
done
for module in "${CLIENT_MODULES[@]}"; do
  [[ -z "${PATTERN}" || "${module}" =~ ${PATTERN} ]] || continue
  run_module "${module}" "" verify
done
log "reports in ${OUT}"
