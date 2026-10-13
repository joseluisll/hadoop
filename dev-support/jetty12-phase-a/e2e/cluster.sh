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

# Usage: e2e/cluster.sh <baseline|candidate> start|stop|status
#
# A single-host cluster running every Hadoop daemon from the side's binary
# distribution: HDFS (namenode, datanode, secondary namenode, journalnode),
# HDFS router (RBF), HttpFS, KMS, NFS gateway (root only), YARN
# (resourcemanager, nodemanager, timeline server, web proxy, router, global
# policy generator, shared cache manager, timeline reader) and the MapReduce
# job history server.
#
# "start" wipes the side's previous cluster state. Each daemon's JVM logs
# every class it loads to results/<side>/e2e/classload/<daemon>.log.

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
ACTION="${2:-}"
LOG_TAG="cluster:${SIDE}"
source "${HARNESS_DIR}/e2e/lib/env.sh"

DAEMON_HEAP="${DAEMON_HEAP:-384m}"

# site <file> <name=value>...: write a Hadoop configuration file.
site() {
  local file=$1
  shift
  {
    echo '<?xml version="1.0"?>'
    echo '<configuration>'
    local kv
    for kv in "$@"; do
      printf '  <property><name>%s</name><value>%s</value></property>\n' \
        "${kv%%=*}" "${kv#*=}"
    done
    echo '</configuration>'
  } > "${file}"
}

write_conf() {
  local c="${HADOOP_CONF_DIR}" d="${RUN}/data"
  rm -rf "${c}"
  cp -r "${DIST}/etc/hadoop" "${c}"
  mkdir -p "${d}" "${RUN}/tmp" "${HADOOP_LOG_DIR}" "${HADOOP_PID_DIR}" \
    "${HTTPFS_TEMP}" "${KMS_TEMP}"

  site "${c}/core-site.xml" \
    "fs.defaultFS=${FS}" \
    "hadoop.tmp.dir=${RUN}/tmp" \
    "hadoop.http.staticuser.user=${USER_NAME}" \
    "hadoop.proxyuser.${USER_NAME}.hosts=*" \
    "hadoop.proxyuser.${USER_NAME}.groups=*" \
    "hadoop.security.key.provider.path=kms://http@${HOST}:${P_KMS}/kms" \
    "hadoop.prometheus.endpoint.enabled=true" \
    "nfs.exports.allowed.hosts=* rw"

  site "${c}/hdfs-site.xml" \
    "dfs.replication=1" \
    "dfs.namenode.name.dir=${d}/nn" \
    "dfs.datanode.data.dir=${d}/dn" \
    "dfs.namenode.checkpoint.dir=${d}/snn" \
    "dfs.journalnode.edits.dir=${d}/jn" \
    "dfs.namenode.http-address=${HOST}:${P_NN_HTTP}" \
    "dfs.namenode.secondary.http-address=${HOST}:${P_SNN_HTTP}" \
    "dfs.datanode.address=${HOST}:${P_DN_DATA}" \
    "dfs.datanode.http.address=${HOST}:${P_DN_HTTP}" \
    "dfs.datanode.ipc.address=${HOST}:${P_DN_IPC}" \
    "dfs.journalnode.rpc-address=${HOST}:${P_JN_RPC}" \
    "dfs.journalnode.http-address=${HOST}:${P_JN_HTTP}" \
    "dfs.namenode.acls.enabled=true" \
    "dfs.namenode.safemode.extension=0" \
    "dfs.namenode.safemode.min.datanodes=0" \
    "dfs.namenode.fs-limits.min-block-size=1024" \
    "nfs.dump.dir=${RUN}/tmp/nfs" \
    "nfs.server.port=${P_NFS3}" \
    "nfs.mountd.port=${P_MOUNTD}" \
    "nfs.http.address=${HOST}:${P_NFS_HTTP}"

  site "${c}/hdfs-rbf-site.xml" \
    "dfs.nameservices=ns0" \
    "dfs.namenode.rpc-address.ns0=${HOST}:${P_NN_RPC}" \
    "dfs.namenode.http-address.ns0=${HOST}:${P_NN_HTTP}" \
    "dfs.federation.router.default.nameserviceId=ns0" \
    "dfs.federation.router.rpc-address=${HOST}:${P_ROUTER_RPC}" \
    "dfs.federation.router.http-address=${HOST}:${P_ROUTER_HTTP}" \
    "dfs.federation.router.admin-address=${HOST}:${P_ROUTER_ADMIN}" \
    "dfs.federation.router.monitor.namenode=ns0" \
    "dfs.federation.router.store.driver.class=org.apache.hadoop.hdfs.server.federation.store.driver.impl.StateStoreFileImpl" \
    "dfs.federation.router.store.driver.file.directory=${d}/router-store"

  local yarn_common=(
    "yarn.resourcemanager.hostname=${HOST}"
    "yarn.resourcemanager.address=${HOST}:${P_RM}"
    "yarn.resourcemanager.scheduler.address=${HOST}:${P_RM_SCHED}"
    "yarn.resourcemanager.resource-tracker.address=${HOST}:${P_RM_TRACKER}"
    "yarn.resourcemanager.admin.address=${HOST}:${P_RM_ADMIN}"
    "yarn.resourcemanager.webapp.address=${HOST}:${P_RM_HTTP}"
    "yarn.nodemanager.address=${HOST}:45454"
    "yarn.nodemanager.webapp.address=${HOST}:${P_NM_HTTP}"
    "yarn.nodemanager.localizer.address=${HOST}:${P_NM_LOCALIZER}"
    "yarn.nodemanager.aux-services=mapreduce_shuffle"
    "yarn.nodemanager.aux-services.mapreduce_shuffle.class=org.apache.hadoop.mapred.ShuffleHandler"
    "yarn.nodemanager.resource.memory-mb=${E2E_NM_MEMORY_MB:-6144}"
    "yarn.nodemanager.resource.cpu-vcores=8"
    "yarn.scheduler.minimum-allocation-mb=256"
    "yarn.scheduler.maximum-allocation-mb=2048"
    "yarn.nodemanager.vmem-check-enabled=false"
    "yarn.nodemanager.pmem-check-enabled=false"
    "yarn.nodemanager.disk-health-checker.max-disk-utilization-per-disk-percentage=99.5"
    "yarn.nodemanager.local-dirs=${d}/nm-local"
    "yarn.nodemanager.log-dirs=${HADOOP_LOG_DIR}/userlogs"
    "yarn.nodemanager.delete.debug-delay-sec=3600"
    "yarn.log-aggregation-enable=true"
    "yarn.nodemanager.remote-app-log-dir=/tmp/logs"
    "yarn.log.server.url=${JHS_URL}/jobhistory/logs"
    "yarn.web-proxy.address=${HOST}:${P_PROXY}"
    "yarn.timeline-service.hostname=${HOST}"
    "yarn.timeline-service.address=${HOST}:${P_AHS_RPC}"
    "yarn.timeline-service.webapp.address=${HOST}:${P_AHS_HTTP}"
    "yarn.timeline-service.leveldb-timeline-store.path=${d}/timeline"
    "yarn.timeline-service.leveldb-state-store.path=${d}/timeline-state"
    "yarn.timeline-service.generic-application-history.enabled=true"
    "yarn.router.webapp.address=${HOST}:${P_YROUTER_HTTP}"
    "yarn.router.clientrm.address=${HOST}:${P_YROUTER_CLIENT}"
    "yarn.router.rmadmin.address=${HOST}:${P_YROUTER_ADMIN}"
    "yarn.federation.gpg.webapp.address=${HOST}:${P_GPG_HTTP}"
    "yarn.sharedcache.webapp.address=${HOST}:${P_SCM_HTTP}"
    "yarn.sharedcache.admin.address=${HOST}:${P_SCM_ADMIN}"
    "yarn.sharedcache.client-server.address=${HOST}:${P_SCM_CLIENT}"
    "yarn.sharedcache.uploader.server.address=${HOST}:${P_SCM_UPLOADER}"
    "yarn.webapp.api-service.enable=true"
    "yarn.timeline-service.reader.webapp.address=${HOST}:${P_TLREADER_HTTP}"
    "yarn.timeline-service.reader.class=org.apache.hadoop.yarn.server.timelineservice.storage.FileSystemTimelineReaderImpl"
    "yarn.timeline-service.fs-writer.root-dir=${d}/atsv2"
  )
  site "${c}/yarn-site.xml" "${yarn_common[@]}" \
    "yarn.timeline-service.enabled=true" \
    "yarn.system-metrics-publisher.enabled=true" \
    "yarn.resourcemanager.system-metrics-publisher.enabled=true"

  site "${c}/mapred-site.xml" \
    "mapreduce.framework.name=yarn" \
    "yarn.app.mapreduce.am.env=HADOOP_MAPRED_HOME=${DIST}" \
    "mapreduce.map.env=HADOOP_MAPRED_HOME=${DIST}" \
    "mapreduce.reduce.env=HADOOP_MAPRED_HOME=${DIST}" \
    "mapreduce.application.classpath=${DIST}/share/hadoop/mapreduce/*:${DIST}/share/hadoop/mapreduce/lib/*" \
    "mapreduce.jobhistory.address=${HOST}:${P_JHS_RPC}" \
    "mapreduce.jobhistory.webapp.address=${HOST}:${P_JHS_HTTP}" \
    "mapreduce.jobhistory.admin.address=${HOST}:${P_JHS_ADMIN}" \
    "yarn.app.mapreduce.am.resource.mb=512" \
    "yarn.app.mapreduce.am.command-opts=-Xmx384m" \
    "mapreduce.map.memory.mb=256" \
    "mapreduce.reduce.memory.mb=256" \
    "mapreduce.map.java.opts=-Xmx200m" \
    "mapreduce.reduce.java.opts=-Xmx200m"

  site "${c}/kms-site.xml" \
    "hadoop.kms.key.provider.uri=jceks://file@${d}/kms.keystore" \
    "hadoop.kms.http.port=${P_KMS}"

  site "${c}/httpfs-site.xml" \
    "httpfs.http.port=${P_HTTPFS}" \
    "httpfs.proxyuser.${USER_NAME}.hosts=*" \
    "httpfs.proxyuser.${USER_NAME}.groups=*"

  # The timeline reader only starts when timeline service v2 is enabled, which
  # would change how the RM and NM publish. It gets its own configuration.
  rm -rf "${RUN}/conf-atsv2"
  cp -r "${c}" "${RUN}/conf-atsv2"
  site "${RUN}/conf-atsv2/yarn-site.xml" "${yarn_common[@]}" \
    "yarn.timeline-service.enabled=true" \
    "yarn.timeline-service.version=2.0f"
}

# daemon_env <name> <OPTS prefix>: JVM options for one daemon.
daemon_env() {
  local name=$1 prefix=$2
  mkdir -p "${RES}/classload"
  export "${prefix}_OPTS=-Xmx${DAEMON_HEAP} -Xlog:class+load=info:file=${RES}/classload/${name}.log::filecount=0"
  # As root the launcher wants to know which user each daemon runs as.
  if [[ ${EUID} -eq 0 ]]; then
    export "${prefix}_USER=root"
  fi
}

start_daemon() {
  local name=$1 launcher=$2 sub=$3 prefix=$4 url=$5
  daemon_env "${name}" "${prefix}"
  local conf_args=()
  [[ "${name}" == timelinereader ]] && conf_args=(--config "${RUN}/conf-atsv2")
  log "starting ${name}"
  if ! "${launcher}" "${conf_args[@]}" --daemon start "${sub}" >> "${RES}/daemon-start.log" 2>&1; then
    log "WARNING: ${name} did not start (see ${RES}/daemon-start.log)"
    echo "${name} start-failed" >> "${RES}/daemons.txt"
    return 0
  fi
  if [[ "${url}" != "-" ]] && ! wait_http "${url}" "${E2E_START_TIMEOUT:-180}"; then
    log "WARNING: ${name} web endpoint ${url} not up"
    echo "${name} not-ready" >> "${RES}/daemons.txt"
    return 0
  fi
  echo "${name} up" >> "${RES}/daemons.txt"
}

start() {
  stop_all quiet
  rm -rf "${RUN}" "${RES}"
  mkdir -p "${RUN}" "${RES}"
  write_conf
  : > "${RES}/daemons.txt"

  log "formatting the namenode"
  hdfs namenode -format -force -nonInteractive > "${RES}/namenode-format.log" 2>&1 \
    || die "namenode format failed; see ${RES}/namenode-format.log"

  local line
  while read -r line; do
    # shellcheck disable=SC2086
    set -- ${line}
    start_daemon "$@"
    if [[ "$1" == datanode ]]; then
      hdfs dfsadmin -safemode wait >/dev/null 2>&1 || true
      # Shared directories every scenario expects.
      hadoop fs -mkdir -p /tmp /user/"${USER_NAME}" /tmp/logs /sharedcache \
        && hadoop fs -chmod 1777 /tmp /tmp/logs \
        || log "WARNING: cannot create the base HDFS directories"
    fi
  done < <(all_daemons)
  log "daemons: $(grep -c ' up$' "${RES}/daemons.txt") up, $(grep -vc ' up$' "${RES}/daemons.txt") not"
}

stop_all() {
  local quiet=${1:-} line
  # Reverse order of start.
  mapfile -t lines < <(all_daemons | tac)
  for line in "${lines[@]}"; do
    # shellcheck disable=SC2086
    set -- ${line}
    local conf_args=()
    [[ "$1" == timelinereader ]] && conf_args=(--config "${RUN}/conf-atsv2")
    if [[ -d "${HADOOP_CONF_DIR}" ]]; then
      [[ -n "${quiet}" ]] || log "stopping $1"
      if [[ ${EUID} -eq 0 ]]; then export "$4_USER=root"; fi
      "$2" "${conf_args[@]}" --daemon stop "$3" >/dev/null 2>&1 || true
    fi
  done
  # Anything that ignored the stop request.
  local pid
  for pid in $(cat "${HADOOP_PID_DIR}"/*.pid 2>/dev/null); do
    kill -9 "${pid}" 2>/dev/null || true
  done
}

status() {
  local line code
  while read -r line; do
    # shellcheck disable=SC2086
    set -- ${line}
    if [[ "$5" == "-" ]]; then code="-"
    else code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 5 "$5" || true)
    fi
    printf '%-24s %s\n' "$1" "${code}"
  done < <(all_daemons)
}

case "${ACTION}" in
  start) start ;;
  stop) stop_all ;;
  status) status ;;
  *) die "usage: $0 <baseline|candidate> start|stop|status" ;;
esac
