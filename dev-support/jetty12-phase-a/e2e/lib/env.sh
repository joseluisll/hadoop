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

# Environment of one end-to-end run: where the distribution, configuration,
# data and results live, which ports every daemon uses, and helpers for the
# scenarios. Sourced after lib/common.sh with SIDE set.

E2E_DIR="${HARNESS_DIR}/e2e"
DIST=$(dist_dir "${SIDE}")
RUN="$(side_dir "${SIDE}")/e2e"            # cluster state, wiped on each run
RES="$(results_dir "${SIDE}")/e2e"         # what the comparison reads
OBS="${RES}/observations.jsonl"
PROBE="${E2E_DIR}/lib/probe.py"

export HADOOP_HOME="${DIST}"
export HADOOP_CONF_DIR="${RUN}/conf"
export HADOOP_LOG_DIR="${RUN}/logs"
export HADOOP_PID_DIR="${RUN}/pids"
export YARN_LOG_DIR="${HADOOP_LOG_DIR}"
export HADOOP_MAPRED_LOG_DIR="${HADOOP_LOG_DIR}"
export HTTPFS_TEMP="${RUN}/tmp/httpfs"
export KMS_TEMP="${RUN}/tmp/kms"
export JAVA_HOME="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}"
export PATH="${DIST}/bin:${DIST}/sbin:${PATH}"
# Optional tools some scenarios need on the client classpath.
export HADOOP_OPTIONAL_TOOLS="hadoop-distcp,hadoop-archives,hadoop-streaming,hadoop-rumen,hadoop-gridmix,hadoop-extras,hadoop-datajoin"
unset HADOOP_CLASSPATH

HOST=localhost
USER_NAME=$(id -un)

# Ports. Defaults where Hadoop has them, explicit everywhere so a stray
# daemon from another run makes start-up fail loudly instead of mixing runs.
P_NN_RPC=9000
P_NN_HTTP=9870
P_DN_HTTP=9864
P_DN_DATA=9866
P_DN_IPC=9867
P_SNN_HTTP=9868
P_JN_RPC=8485
P_JN_HTTP=8480
P_ROUTER_RPC=8888
P_ROUTER_HTTP=50071
P_ROUTER_ADMIN=8111
P_HTTPFS=14000
P_KMS=9600
P_NFS3=2049
P_MOUNTD=4242
P_NFS_HTTP=50079
P_RM=8032
P_RM_SCHED=8030
P_RM_TRACKER=8031
P_RM_ADMIN=8033
P_RM_HTTP=8088
P_NM_HTTP=8042
P_NM_LOCALIZER=8040
P_AHS_RPC=10200
P_AHS_HTTP=8188
P_PROXY=9046
P_YROUTER_HTTP=8089
P_YROUTER_CLIENT=8050
P_YROUTER_ADMIN=8052
P_GPG_HTTP=8069
P_SCM_HTTP=8788
P_SCM_ADMIN=8047
P_SCM_CLIENT=8045
P_SCM_UPLOADER=8046
P_TLREADER_HTTP=8198
P_JHS_RPC=10020
P_JHS_HTTP=19888
P_JHS_ADMIN=10033
P_SLS_HTTP=10001

NN_URL="http://${HOST}:${P_NN_HTTP}"
RM_URL="http://${HOST}:${P_RM_HTTP}"
NM_URL="http://${HOST}:${P_NM_HTTP}"
AHS_URL="http://${HOST}:${P_AHS_HTTP}"
JHS_URL="http://${HOST}:${P_JHS_HTTP}"
HTTPFS_URL="http://${HOST}:${P_HTTPFS}"
KMS_URL="http://${HOST}:${P_KMS}"
FS="hdfs://${HOST}:${P_NN_RPC}"

# Daemons: name, launcher, subcommand, the *_OPTS variable the launcher reads,
# the web address checked for readiness ("-" for none).
DAEMONS=(
  "namenode hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx"
  "datanode hdfs datanode HDFS_DATANODE http://${HOST}:${P_DN_HTTP}/jmx"
  "secondarynamenode hdfs secondarynamenode HDFS_SECONDARYNAMENODE http://${HOST}:${P_SNN_HTTP}/jmx"
  "journalnode hdfs journalnode HDFS_JOURNALNODE http://${HOST}:${P_JN_HTTP}/jmx"
  "kms hadoop kms HADOOP_KMS ${KMS_URL}/jmx"
  "httpfs hdfs httpfs HDFS_HTTPFS ${HTTPFS_URL}/jmx"
  "dfsrouter hdfs dfsrouter HDFS_DFSROUTER http://${HOST}:${P_ROUTER_HTTP}/jmx"
  "resourcemanager yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx"
  "nodemanager yarn nodemanager YARN_NODEMANAGER ${NM_URL}/jmx"
  "timelineserver yarn timelineserver YARN_TIMELINESERVER ${AHS_URL}/jmx"
  "proxyserver yarn proxyserver YARN_PROXYSERVER http://${HOST}:${P_PROXY}/jmx"
  "router yarn router YARN_ROUTER http://${HOST}:${P_YROUTER_HTTP}/jmx"
  "globalpolicygenerator yarn globalpolicygenerator YARN_GLOBALPOLICYGENERATOR http://${HOST}:${P_GPG_HTTP}/jmx"
  "sharedcachemanager yarn sharedcachemanager YARN_SHAREDCACHEMANAGER http://${HOST}:${P_SCM_HTTP}/jmx"
  "timelinereader yarn timelinereader YARN_TIMELINEREADER http://${HOST}:${P_TLREADER_HTTP}/jmx"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx"
)
# The NFS gateway needs the privileged portmap port; only started as root.
NFS_DAEMONS=(
  "portmap hdfs portmap HDFS_PORTMAP -"
  "nfs3 hdfs nfs3 HDFS_NFS3 http://${HOST}:${P_NFS_HTTP}/jmx"
)

nfs_enabled() {
  [[ "${E2E_NFS:-auto}" == true ]] || { [[ "${E2E_NFS:-auto}" == auto && ${EUID} -eq 0 ]]; }
}

all_daemons() {
  printf '%s\n' "${DAEMONS[@]}"
  if nfs_enabled; then printf '%s\n' "${NFS_DAEMONS[@]}"; fi
}

# wait_http <url> <seconds>: until the URL answers with any HTTP status < 500.
wait_http() {
  local url=$1 deadline=$((SECONDS + $2)) code
  while (( SECONDS < deadline )); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 5 "${url}" || true)
    if [[ "${code}" =~ ^[1-4][0-9][0-9]$ ]]; then return 0; fi
    sleep 2
  done
  return 1
}

# ---------------------------------------------------------------- scenarios

# Scenario helpers. COMPONENT is set by each scenario file.

# http <id> <url> [probe options]: probe a URL and record the observation.
http() {
  local id=$1 url=$2
  shift 2
  python3 -I "${PROBE}" http --obs "${OBS}" --component "${COMPONENT}" \
    --id "${id}" --url "${url}" "$@"
}

# cli <id> [--merge-stderr] [--expect-rc N] [--shape S] [--expect-regex R]...
#     -- <command...>
# Runs the command, keeps its output in ${RES}/cli/<id>.out, records the
# exit code (and output shape / captured groups, if asked). --merge-stderr
# matches the regexes against stderr too (Hadoop clients log to stderr).
cli() {
  local id=$1
  shift
  local opts=() merge=false
  while [[ $# -gt 0 && "$1" != "--" ]]; do
    if [[ "$1" == --merge-stderr ]]; then merge=true; else opts+=("$1"); fi
    shift
  done
  [[ "${1:-}" == "--" ]] && shift
  local out="${RES}/cli/${COMPONENT}.${id}.out"
  mkdir -p "${RES}/cli"
  local rc=0
  if [[ "${merge}" == true ]]; then
    "$@" > "${out}" 2>&1 || rc=$?
  else
    "$@" > "${out}" 2> "${out}.err" || rc=$?
  fi
  python3 -I "${PROBE}" cli --obs "${OBS}" --component "${COMPONENT}" --id "${id}" \
    --rc "${rc}" --stdout-file "${out}" "${opts[@]}"
}

# check <id> <ok:true|false> [detail]: record a scenario-level assertion.
check() {
  python3 -I "${PROBE}" assert --obs "${OBS}" --component "${COMPONENT}" \
    --id "$1" --ok "$2" --detail "${3:-}"
}

# same_checksum <id> <path1> <path2>: HDFS-compatible paths hold equal data.
same_checksum() {
  local a b
  a=$(hadoop fs -cat "$2" 2>/dev/null | sha256sum | cut -d' ' -f1)
  b=$(hadoop fs -cat "$3" 2>/dev/null | sha256sum | cut -d' ' -f1)
  if [[ -n "${a}" && "${a}" == "${b}" && "${a}" != "$(sha256sum < /dev/null | cut -d' ' -f1)" ]]; then
    check "$1" true
  else
    check "$1" false "content differs: $2 (${a}) vs $3 (${b})"
  fi
}

# wait_app_state <application id> <state regex> <seconds>
wait_app_state() {
  local app=$1 want=$2 deadline=$((SECONDS + $3)) state
  while (( SECONDS < deadline )); do
    state=$(curl -s --noproxy '*' "${RM_URL}/ws/v1/cluster/apps/${app}/state" \
      | python3 -c 'import sys,json; print(json.load(sys.stdin).get("state",""))' 2>/dev/null || true)
    if [[ "${state}" =~ ^(${want})$ ]]; then echo "${state}"; return 0; fi
    sleep 2
  done
  echo "${state:-unknown}"
  return 1
}

# latest_app [name regex]: id of the most recently submitted application.
latest_app() {
  curl -s --noproxy '*' "${RM_URL}/ws/v1/cluster/apps" | python3 -c '
import sys, json, re
apps = (json.load(sys.stdin).get("apps") or {}).get("app") or []
pat = re.compile(sys.argv[1]) if len(sys.argv) > 1 else None
apps = [a for a in apps if not pat or pat.search(a.get("name", ""))]
print(max(apps, key=lambda a: a["startedTime"])["id"] if apps else "")' "$@"
}
