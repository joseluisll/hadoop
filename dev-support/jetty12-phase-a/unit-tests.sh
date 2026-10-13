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
#
# Each failing test is re-run once (surefire.rerunFailingTestsCount) so a
# flaky test shows up as flaky, not failed. compare.sh lines up the two
# sides test by test.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
SUITE="${2:-changed}"
TIER="${3:-quick}"
PATTERN="${4:-}"
LOG_TAG="unit:${SIDE}"
OUT="$(results_dir "${SIDE}")/unit"
mkdir -p "${OUT}"

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
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-app|org/apache/hadoop/mapreduce/v2/app/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-hs|org/apache/hadoop/mapreduce/v2/hs/webapp/**/Test*"
  "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-shuffle|"
  "hadoop-mapreduce-project/hadoop-mapreduce-examples|"
  "hadoop-tools/hadoop-resourceestimator|"
  "hadoop-tools/hadoop-sls|org/apache/hadoop/yarn/sls/web/**/Test*,org/apache/hadoop/yarn/sls/TestSLSRunner*"
  # Not changed by phase A, but they run the servers whose classpath it
  # changes.
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

[[ -d "$(src_dir "${SIDE}")" ]] || die "run build.sh ${SIDE} first"

run_module() {
  local suite=$1 module=$2 tests=$3
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
  if [[ -n "${tests}" && ( "${suite}" != changed || "${TIER}" == quick ) ]]; then
    args+=("-Dtest=${tests}" -Dsurefire.failIfNoSpecifiedTests=false)
  fi
  log "${suite}: ${module}${tests:+ ($(tr ',' '\n' <<< "${tests}" | wc -l) test patterns)}"
  local start=${SECONDS} rc=0
  mvn_side "${SIDE}" "${args[@]}" > "${dest}/mvn.log" 2>&1 || rc=$?
  local src
  src="$(src_dir "${SIDE}")/${module}/target"
  cp "${src}"/surefire-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  cp "${src}"/failsafe-reports/TEST-*.xml "${dest}/" 2>/dev/null || true
  rm -rf "${src}/surefire-reports" "${src}/failsafe-reports"
  echo "${rc} $((SECONDS - start))" > "${dest}/status"
  log "${suite}: ${module}: maven exit ${rc}, $(ls "${dest}"/TEST-*.xml 2>/dev/null | wc -l) report files, $((SECONDS - start))s"
}

suites=("${SUITE}")
[[ "${SUITE}" == all ]] && suites=("${ALL_SUITES[@]}")
for suite in "${suites[@]}"; do
  [[ " ${ALL_SUITES[*]} " == *" ${suite} "* ]] || die "unknown suite ${suite}"
  declare -n entries="SUITE_${suite}"
  for entry in "${entries[@]}"; do
    module=${entry%%|*} tests=${entry#*|}
    [[ -z "${PATTERN}" || "${module}" =~ ${PATTERN} ]] || continue
    run_module "${suite}" "${module}" "${tests}"
  done
  unset -n entries
done
log "reports in ${OUT}"
