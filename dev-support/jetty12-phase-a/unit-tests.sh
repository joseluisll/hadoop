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

# Usage: unit-tests.sh <baseline|candidate> <suite> [quick|full] [module-pattern]
#        unit-tests.sh --shards <suite> [quick|full]
#
# Tiers: "quick" runs the tests listed for each module (for "changed", the
# web and Jersey tests); "full" runs every test of each module of the suite
# (modules with Hadoop's parallel-tests profile in parallel), except the
# server modules of "changed", which keep their listed tests.
#
# Runs existing Hadoop tests on the side's tree and keeps the surefire /
# failsafe XML reports in results/<side>/unit/<suite>__<module>/. Suites:
#
#   changed    every module whose build phase A changes, plus the HTTP
#              tests of the modules running those servers. "quick" runs the
#              tests that start a web server or use the Jersey test
#              container; "full" runs every test of those modules.
#   secure     Hadoop's own MiniKdc-based tests: SPNEGO, TLS, SASL data
#              transfer, delegation tokens, secure router, KMS, timeline
#              authentication.
#   ha         namenode HA (QJM, ZKFC, WebHDFS over HA, standby
#              checkpoints) and RM HA (failover, web redirects, election).
#   federated  HDFS federation and ViewFS, RBF (RPC, admin, mount table,
#              WebHDFS) and YARN federation (router interceptors, REST
#              against real daemons, GPG, AMRMProxy, ZooKeeper state store).
#   mixed      the combinations: secure HA, the router in front of HA
#              namenodes, observer reads through the router, fault
#              tolerance of multi-destination mounts.
#   client     the shaded client jars: invariant checks and
#              hadoop-client-integration-tests (the minicluster jar used
#              from a downstream point of view).
#   all        every suite above.
#   <suite>-<n> one shard of a suite, so that "full", which runs for hours,
#              fits CI jobs of 6 hours: for "changed" the n-th of the
#              CHANGED_SHARDS below, for the others its n-th module.
#              Reports are named as for the whole suite. --shards prints the
#              jobs a suite needs in a tier (just the suite in "quick").
#
# Each failing test is re-run once (surefire.rerunFailingTestsCount) so a
# flaky test shows up as flaky, not failed. compare.sh lines up the two
# sides test by test.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
if [[ "${1:-}" == --shards ]]; then
  SHARDS_ONLY=true SIDE="" SUITE="${2:-changed}" TIER="${3:-quick}" PATTERN=""
else
  SHARDS_ONLY=false SIDE="${1:-}" SUITE="${2:-changed}" TIER="${3:-quick}" PATTERN="${4:-}"
  check_side "${SIDE}"
fi
[[ "${TIER}" =~ ^(quick|full)$ ]] || die "tier must be quick or full, got '${TIER}'"
LOG_TAG="unit:${SIDE:-shards}"

HDFS=hadoop-hdfs-project/hadoop-hdfs
RBF=hadoop-hdfs-project/hadoop-hdfs-rbf
COMMON=hadoop-common-project/hadoop-common
YS=hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server
RM=${YS}/hadoop-yarn-server-resourcemanager
ROUTER=${YS}/hadoop-yarn-server-router

# Suite entries: "module|tests" (surefire -Dtest syntax). For "changed" an
# empty test list means the whole module in both tiers; the other suites
# always run exactly the listed tests.
SUITE_changed=(
  "${COMMON}|org/apache/hadoop/http/**/Test*,org/apache/hadoop/jmx/**/Test*,org/apache/hadoop/conf/TestConfServlet*,org/apache/hadoop/log/**/Test*,org/apache/hadoop/security/http/**/Test*,org/apache/hadoop/security/authentication/server/**/Test*"
  "hadoop-hdfs-project/hadoop-hdfs-httpfs|org/apache/hadoop/fs/http/server/**/Test*,org/apache/hadoop/fs/http/client/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-common|org/apache/hadoop/yarn/webapp/**/Test*,org/apache/hadoop/yarn/client/api/impl/**/Test*"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-client|org/apache/hadoop/yarn/client/api/impl/TestTimelineClient*,org/apache/hadoop/yarn/client/api/impl/TestAHSv2ClientImpl*,org/apache/hadoop/yarn/client/cli/TestLogsCLI*"
  "${YS}/hadoop-yarn-server-applicationhistoryservice|"
  "${YS}/hadoop-yarn-server-globalpolicygenerator|"
  "${YS}/hadoop-yarn-server-nodemanager|org/apache/hadoop/yarn/server/nodemanager/webapp/**/Test*"
  "${RM}|org/apache/hadoop/yarn/server/resourcemanager/webapp/**/Test*"
  "${ROUTER}|org/apache/hadoop/yarn/server/router/webapp/**/Test*"
  "${YS}/hadoop-yarn-server-web-proxy|"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-applications/hadoop-yarn-applications-catalog/hadoop-yarn-applications-catalog-webapp|"
  # HADOOP-20012 and HADOOP-20014 change its test dependencies. Its tests
  # start an HBase minicluster; "quick" runs the one that also starts the
  # timeline reader's web server on HBase storage.
  "${YS}/hadoop-yarn-server-timelineservice-hbase-tests|org/apache/hadoop/yarn/server/timelineservice/reader/TestTimelineReaderWebServicesHBaseStorage*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-app|org/apache/hadoop/mapreduce/v2/app/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-hs|org/apache/hadoop/mapreduce/v2/hs/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-shuffle|"
  "hadoop-mapreduce-project/hadoop-mapreduce-examples|"
  "hadoop-tools/hadoop-resourceestimator|"
  "hadoop-tools/hadoop-sls|org/apache/hadoop/yarn/sls/web/**/Test*,org/apache/hadoop/yarn/sls/TestSLSRunner*"
)
# Part of "changed" too: not changed by phase A, but they run the servers
# whose classpath it changes. Only the listed tests, in both tiers.
SUITE_changed_servers=(
  "hadoop-common-project/hadoop-kms|org/apache/hadoop/crypto/key/kms/server/TestKMS.java"
  "${HDFS}|org/apache/hadoop/hdfs/web/TestWebHDFS.java,org/apache/hadoop/hdfs/server/namenode/TestNameNodeHttpServer*,org/apache/hadoop/hdfs/server/datanode/web/**/Test*,org/apache/hadoop/hdfs/server/namenode/TestStartupProgressServlet*"
  "${RBF}|org/apache/hadoop/hdfs/server/federation/router/TestRouterHttpServerXFrame*,org/apache/hadoop/hdfs/server/federation/router/web/**/Test*"
  "${YS}/hadoop-yarn-server-timelineservice|org/apache/hadoop/yarn/server/timelineservice/reader/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-jobclient|org/apache/hadoop/mapreduce/v2/TestMRJobsWithHistoryService*"
)
SUITE_secure=(
  "${COMMON}|TestHttpServerWithSpnego,TestSSLHttpServer,TestSSLHttpServerConfigs*,TestKDiag*"
  "${HDFS}|TestSecureNameNode,TestSaslDataTransfer,TestWebHdfsTokens,TestDelegationToken,TestBlockTokenWithDFS*"
  "hadoop-common-project/hadoop-kms|TestKMS"
  "hadoop-hdfs-project/hadoop-hdfs-httpfs|TestHttpFSWithKerberos,TestHttpFSServerWebServer"
  "${RBF}|TestRouterWithSecureStartup,TestRouterHttpDelegationToken,TestRouterSecurityManager"
  "${RM}|TestRMWebappAuthentication,TestRMWebServicesDelegationTokenAuthentication,TestRMWebServicesHttpStaticUserPermissions"
  "${YS}/hadoop-yarn-server-applicationhistoryservice|TestTimelineAuthenticationFilterForV1"
  "${ROUTER}|TestSecureLogins"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-jobclient|TestJHSSecurity"
)
SUITE_ha=(
  "${COMMON}|TestZKFailoverController,TestNodeFencer"
  "${HDFS}|TestWebHDFSForHA,TestFailoverWithBlockTokensEnabled,TestHAStateTransitions,TestDFSZKFailoverController,TestStandbyCheckpoints,TestDelegationTokensWithHA,TestQuorumJournalManager"
  "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-client|TestRMFailover,TestApplicationClientProtocolOnHA,TestResourceTrackerOnHA"
  "${RM}|TestRMHA,TestRMEmbeddedElector"
)
SUITE_federated=(
  "${HDFS}|TestViewFileSystemHdfs,TestViewFsHdfs,TestRefreshNamenodes,TestWebHdfsWithMultipleNameNodes,TestMultipleNNPortQOP"
  "${RBF}|TestRouterRpc,TestRouterAdminCLI,TestRouterMountTable,TestRouterWebHdfsMethods,TestRouterWebHDFSContract*"
  "${ROUTER}|TestFederationClientInterceptor,TestFederationInterceptorREST,TestRouterWebServicesREST"
  "${YS}/hadoop-yarn-server-globalpolicygenerator|TestGlobalPolicyGenerator"
  "${YS}/hadoop-yarn-server-nodemanager|TestFederationInterceptor"
  "${YS}/hadoop-yarn-server-common|TestZookeeperFederationStateStore"
)
SUITE_mixed=(
  "${HDFS}|TestSecureNNWithQJM"
  "${RBF}|TestRouterNamenodeHeartbeat,TestRouterNamenodeMonitoring,TestRouterFaultTolerant,TestObserverWithRouter,TestRouterRPCClientRetries"
)
# The shaded client jars and the minicluster.
SUITE_client=(
  "hadoop-client-modules/hadoop-client-check-invariants|"
  "hadoop-client-modules/hadoop-client-check-test-invariants|"
  "hadoop-client-modules/hadoop-client-integration-tests|"
)
ALL_SUITES=(changed secure ha federated mixed client)

run_module() {
  local suite=$1 module=$2 tests=$3 exact=${4:-false}
  local dest="${OUT}/${suite}__${module//\//__}"
  rm -rf "${dest}"
  mkdir -p "${dest}"
  local goal=test
  [[ "${suite}" == client ]] && goal=verify
  # -nsu: never replace this side's installed SNAPSHOT jars with remote ones.
  local args=(-nsu "${goal}" -pl "${module}" -Dmaven.test.failure.ignore=true
              -Dsurefire.rerunFailingTestsCount="${UNIT_RERUNS:-1}"
              -Dfailsafe.rerunFailingTestsCount="${UNIT_RERUNS:-1}"
              -Dmaven.javadoc.skip=true -Dspotbugs.skip=true -Dcheckstyle.skip=true)
  if [[ -n "${tests}" && ( "${TIER}" == quick || "${exact}" == true ) ]]; then
    args+=("-Dtest=${tests}" -Dsurefire.failIfNoSpecifiedTests=false)
  elif [[ "${TIER}" == full ]] && grep -qs '<id>parallel-tests</id>' "$(src_dir "${SIDE}")/${module}/pom.xml"; then
    # Every test of a big module (HDFS, common, RBF): in parallel, as
    # Hadoop's own CI runs them, to fit a 6-hour CI job.
    args+=(-Pparallel-tests -DtestsThreadCount="${UNIT_TEST_THREADS:-4}")
  fi
  log "${suite}: ${module}${tests:+ ($(tr ',' '\n' <<< "${tests}" | wc -l) test patterns)}"
  local start=${SECONDS} rc=0
  mvn_logged "${SIDE}" "${dest}/mvn.log" "${args[@]}" || rc=$?
  local src
  src="$(src_dir "${SIDE}")/${module}/target"
  cp "${src}"/surefire-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  cp "${src}"/failsafe-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  rm -rf "${src}/surefire-reports" "${src}/failsafe-reports"
  echo "${rc} $((SECONDS - start))" > "${dest}/status"
  log "${suite}: ${module}: maven exit ${rc}, $(ls "${dest}"/TEST-*.xml 2>/dev/null | wc -l) report files, $((SECONDS - start))s"
}

# Shards of the "changed" suite: a module goes to the first one whose regex
# it matches, or to the last. The resource manager's tests alone take hours.
CHANGED_SHARDS=(
  "hadoop-yarn-server-resourcemanager"
  "hadoop-yarn-server-(nodemanager|router|globalpolicygenerator|web-proxy|applicationhistoryservice)"
  "hadoop-common-project|hadoop-hdfs-project|timelineservice"
  ".*"
)
shard_of() {
  local i
  for i in "${!CHANGED_SHARDS[@]}"; do
    [[ "$1" =~ ${CHANGED_SHARDS[$i]} ]] && { echo $((i + 1)); return; }
  done
}

# shards <suite>: the CI jobs that run the suite in this tier, one per line.
shards() {
  local suite=$1 i
  [[ " ${ALL_SUITES[*]} " == *" ${suite} "* ]] || die "unknown suite ${suite}"
  if [[ "${TIER}" == quick || "${suite}" == client ]]; then
    echo "${suite}"
  elif [[ "${suite}" == changed ]]; then
    for i in "${!CHANGED_SHARDS[@]}"; do echo "changed-$((i + 1))"; done
  else
    declare -n e="SUITE_${suite}"
    for i in "${!e[@]}"; do echo "${suite}-$((i + 1))"; done
  fi
}
if [[ "${SHARDS_ONLY}" == true ]]; then
  shards "${SUITE}"
  exit 0
fi

[[ -d "$(src_dir "${SIDE}")" ]] || die "run build.sh ${SIDE} first"
OUT="$(results_dir "${SIDE}")/unit"
mkdir -p "${OUT}"

# in_shard <suite> <index> <module>: whether the selected shard runs it.
in_shard() {
  [[ -z "${shard}" ]] && return 0
  if [[ "$1" == changed ]]; then
    [[ "$(shard_of "$3")" == "${shard}" ]]
  else
    (( $2 + 1 == shard ))
  fi
}

suites=("${SUITE}")
shard=""
[[ "${SUITE}" == all ]] && suites=("${ALL_SUITES[@]}")
if [[ "${SUITE}" =~ ^([a-z]+)-([0-9]+)$ ]]; then
  suites=("${BASH_REMATCH[1]}")
  shard=${BASH_REMATCH[2]}
fi
ran=0
for suite in "${suites[@]}"; do
  [[ " ${ALL_SUITES[*]} " == *" ${suite} "* ]] || die "unknown suite ${suite}"
  declare -n entries="SUITE_${suite}"
  for i in "${!entries[@]}"; do
    module=${entries[$i]%%|*} tests=${entries[$i]#*|}
    [[ -z "${PATTERN}" || "${module}" =~ ${PATTERN} ]] || continue
    in_shard "${suite}" "${i}" "${module}" || continue
    run_module "${suite}" "${module}" "${tests}"
    ran=$((ran + 1))
  done
  unset -n entries
  [[ "${suite}" == changed ]] || continue
  for entry in "${SUITE_changed_servers[@]}"; do
    module=${entry%%|*} tests=${entry#*|}
    [[ -z "${PATTERN}" || "${module}" =~ ${PATTERN} ]] || continue
    in_shard changed 0 "${module}" || continue
    run_module "${suite}" "${module}" "${tests}" true
    ran=$((ran + 1))
  done
done
(( ran > 0 )) || die "suite ${SUITE} selects no module"
log "reports in ${OUT}"
