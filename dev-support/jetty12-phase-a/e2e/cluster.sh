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

# Usage: e2e/cluster.sh <baseline|candidate> <architecture> start|stop|status
#        e2e/cluster.sh <side> <architecture> kill|restart <instance>
#
# Runs one architecture (e2e/arch/<architecture>.sh) on this host from the
# side's binary distribution. Every daemon instance gets its own
# configuration directory, pid file and log file (HADOOP_IDENT_STRING is
# the instance name), so an architecture can run two namenodes, three
# journalnodes, two resource managers or two routers side by side.
#
# "start" wipes the architecture's previous state. Each daemon's JVM logs
# every class it loads to results/<side>/e2e/<arch>/classload/<instance>.log.

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
ARCH="${2:-}"
ACTION="${3:-}"
LOG_TAG="cluster:${SIDE}:${ARCH}"
source "${HARNESS_DIR}/e2e/lib/env.sh"
source "${E2E_DIR}/lib/conf.sh"

DAEMON_HEAP="${DAEMON_HEAP:-384m}"

# instance_line <instance>: its INSTANCES line.
instance_line() {
  local line
  for line in "${INSTANCES[@]}"; do
    [[ "${line%% *}" == "$1" ]] && { echo "${line}"; return 0; }
  done
  die "no instance '$1' in architecture ${ARCH}"
}

# run_daemon <start|stop> <instance> <launcher> <sub> <prefix> <url> <conf>
run_daemon() {
  local action=$1 name=$2 launcher=$3 sub=$4 prefix=$5 conf=$7
  mkdir -p "${RES}/classload"
  # The launcher reads <PREFIX>_OPTS for this daemon's JVM.
  local opts="-Xmx${DAEMON_HEAP} -Xlog:class+load=info:file=${RES}/classload/${name}.log::filecount=0"
  [[ -n "${KRB5_JVM_OPTS:-}" ]] && opts+=" ${KRB5_JVM_OPTS}"
  local extra_cp=""
  # The timeline reader's file system storage lives in Hadoop's test jar.
  if [[ "${sub}" == timelinereader ]]; then
    extra_cp=$(ls "${TOOLS_DIR}"/timelineservice-tests/*.jar 2>/dev/null | paste -sd: || true)
  fi
  env "${prefix}_OPTS=${opts}" \
      "${prefix}_USER=$( [[ ${EUID} -eq 0 ]] && echo root || id -un)" \
      HADOOP_IDENT_STRING="${name}" \
      HADOOP_CLASSPATH="${extra_cp}" \
      "${launcher}" --config "${conf}" --daemon "${action}" "${sub}"
}

# wait_ready <instance> <daemon> <url> <seconds>: prints "up", "exited" or
# "timeout". A daemon that will not come up stops the wait at once instead of
# running out the timeout: its process is gone, or its main thread died (KMS
# and HttpFS keep the JVM alive when their web application fails to start;
# the launcher rotates the .out file at each start, so the line is new).
wait_ready() {
  local pidf="${HADOOP_PID_DIR}/hadoop-$1-$2.pid" deadline=$((SECONDS + $4)) pid
  while (( SECONDS < deadline )); do
    if wait_http "$3" 2; then echo up; return 0; fi
    pid=$(cat "${pidf}" 2>/dev/null || true)
    if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then echo exited; return 0; fi
    if grep -qs '^Exception in thread "main"' "${HADOOP_LOG_DIR}/hadoop-$1-$2-"*.out; then
      echo exited
      return 0
    fi
  done
  echo timeout
}

start_instance() {
  local name=$1 url=$5
  log "starting ${name}"
  if ! run_daemon start "$@" >> "${RES}/daemon-start.log" 2>&1; then
    log "WARNING: ${name} did not start (see ${RES}/daemon-start.log)"
    echo "${name} start-failed" >> "${RES}/daemons.txt"
    return 0
  fi
  if [[ "${url}" != "-" ]]; then
    case $(wait_ready "${name}" "$3" "${url}" "${E2E_START_TIMEOUT:-180}") in
      up) ;;
      exited)
        log "WARNING: ${name} exited before its web endpoint ${url} was up"
        echo "${name} start-failed" >> "${RES}/daemons.txt"
        return 0 ;;
      *)
        log "WARNING: ${name} web endpoint ${url} not up"
        echo "${name} not-ready" >> "${RES}/daemons.txt"
        return 0 ;;
    esac
  fi
  # Daemons without a web endpoint: give them a moment, then check the pid.
  if [[ "${url}" == "-" ]]; then
    sleep 3
    local pid
    pid=$(cat "${HADOOP_PID_DIR}/hadoop-${name}-$3.pid" 2>/dev/null || true)
    if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
      log "WARNING: ${name} exited"
      echo "${name} start-failed" >> "${RES}/daemons.txt"
      return 0
    fi
  fi
  # A router serves nothing until its namenode heartbeats register; clients
  # started right after it (job history server) would fail.
  if [[ "$3" == dfsrouter ]]; then
    local deadline=$((SECONDS + 120))
    until curl -s --noproxy '*' "${url%/jmx}/jmx?qry=Hadoop:service=Router,name=FederationState" \
        | grep -Eq '"NumNamenodes" : [1-9]'; do
      if (( SECONDS > deadline )); then
        log "WARNING: ${name} has no registered namenode after 120s"
        break
      fi
      sleep 2
    done
  fi
  echo "${name} up" >> "${RES}/daemons.txt"
}

start() {
  stop_all quiet
  rm -rf "${RUN}" "${RES}"
  mkdir -p "${RUN}" "${RES}"
  : > "${RES}/daemons.txt"
  new_conf
  local svc
  for svc in "${ARCH_SERVICES[@]}"; do
    case "${svc}" in
      kdc) start_kdc ;;
      zookeeper) start_zk ;;
      *) die "unknown service ${svc}" ;;
    esac
  done
  arch_conf
  # arch_prepare may start some instances itself (e.g. journalnodes before
  # a namenode can be formatted) and list them in SKIP_INSTANCES.
  SKIP_INSTANCES=""
  arch_prepare
  local line
  for line in "${INSTANCES[@]}"; do
    [[ " ${SKIP_INSTANCES} " == *" ${line%% *} "* ]] && continue
    # shellcheck disable=SC2086
    start_instance ${line}
    if [[ "${line%% *}" =~ ^datanode ]]; then
      after_datanode
    fi
  done
  arch_after_start
  log "daemons: $(grep -c ' up$' "${RES}/daemons.txt") up, $(grep -vc ' up$' "${RES}/daemons.txt") not"
}

# The first datanode is up: wait for HDFS and create the shared directories,
# in FS_DIRECT when the default file system is not up yet (RBF in front).
after_datanode() {
  local fs="${FS_DIRECT:-${FS}}"
  hdfs dfsadmin -fs "${fs}" -safemode wait >/dev/null 2>&1 || true
  hadoop fs -fs "${fs}" -mkdir -p /tmp /user/"${USER_NAME}" /tmp/logs /sharedcache \
    && hadoop fs -fs "${fs}" -chmod 1777 /tmp /tmp/logs \
    || log "WARNING: cannot create the base HDFS directories"
}

stop_all() {
  local quiet=${1:-} line i
  if [[ -d "${RUN}" ]]; then
    for (( i=${#INSTANCES[@]}-1; i>=0; i-- )); do
      line=${INSTANCES[i]}
      # shellcheck disable=SC2086
      set -- ${line}
      [[ -d "$6" ]] || continue
      [[ -n "${quiet}" ]] || log "stopping $1"
      run_daemon stop "$@" >/dev/null 2>&1 || true
    done
  fi
  stop_services
  # Anything that ignored the stop request.
  local pid
  for pid in $(cat "${HADOOP_PID_DIR}"/*.pid 2>/dev/null); do
    kill -9 "${pid}" 2>/dev/null || true
  done
}

status() {
  local line code
  for line in "${INSTANCES[@]}"; do
    # shellcheck disable=SC2086
    set -- ${line}
    if [[ "$5" == "-" ]]; then code="-"
    else code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 5 \
                  ${PROBE_CA:+--cacert "${PROBE_CA}"} "$5" || true)
    fi
    printf '%-24s %s\n' "$1" "${code}"
  done
}

# kill_instance <instance>: kill -9, as a crash would (failover tests).
kill_instance() {
  # shellcheck disable=SC2046
  set -- $(instance_line "$1")
  local pid
  pid=$(cat "${HADOOP_PID_DIR}/hadoop-$1-$3.pid" 2>/dev/null || true)
  [[ -n "${pid}" ]] && kill -9 "${pid}" 2>/dev/null || true
  rm -f "${HADOOP_PID_DIR}/hadoop-$1-$3.pid"
  log "killed $1 (${pid:-no pid})"
}

restart_instance() {
  # shellcheck disable=SC2046
  set -- $(instance_line "$1")
  sed -i "/^$1 /d" "${RES}/daemons.txt"
  start_instance "$@"
}

case "${ACTION}" in
  start) start ;;
  stop) stop_all ;;
  status) status ;;
  kill) kill_instance "${4:?instance}" ;;
  restart) restart_instance "${4:?instance}" ;;
  *) die "usage: $0 <baseline|candidate> <architecture> start|stop|status|kill|restart [instance]" ;;
esac
