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

# Building blocks the architecture files use: configuration writing, the
# properties every architecture shares, and the non-Hadoop services some
# architectures need (ZooKeeper from the distribution's own jars, a KDC from
# hadoop-minikdc, TLS keystores from keytool). Sourced by e2e/cluster.sh.

DATA="${RUN}/data"

# site <file> <name=value>...: set properties in a configuration file.
site() {
  python3 -I "${E2E_DIR}/lib/confset.py" "$@"
}

# new_conf: the client configuration directory, from the distribution's
# etc/hadoop with every *-site.xml emptied.
new_conf() {
  rm -rf "${HADOOP_CONF_DIR}"
  cp -r "${DIST}/etc/hadoop" "${HADOOP_CONF_DIR}"
  local f
  for f in core hdfs yarn mapred kms httpfs hdfs-rbf; do
    printf '<?xml version="1.0"?>\n<configuration>\n</configuration>\n' \
      > "${HADOOP_CONF_DIR}/${f}-site.xml"
  done
  mkdir -p "${DATA}" "${RUN}/tmp" "${HADOOP_LOG_DIR}" "${HADOOP_PID_DIR}"
}

# instance_conf <instance>: a copy of the client configuration for one
# daemon instance, printed; callers then override properties in it.
instance_conf() {
  local dir="${RUN}/conf-$1"
  rm -rf "${dir}"
  cp -r "${HADOOP_CONF_DIR}" "${dir}"
  echo "${dir}"
}

# Properties every architecture starts from.
base_core() {
  site "${HADOOP_CONF_DIR}/core-site.xml" \
    "hadoop.tmp.dir=${RUN}/tmp" \
    "hadoop.http.staticuser.user=${USER_NAME}" \
    "hadoop.proxyuser.${USER_NAME}.hosts=*" \
    "hadoop.proxyuser.${USER_NAME}.groups=*" \
    "hadoop.prometheus.endpoint.enabled=true" \
    "ipc.client.connect.max.retries=10" \
    "ipc.client.connect.retry.interval=500" \
    "$@"
}

base_hdfs() {
  site "${HADOOP_CONF_DIR}/hdfs-site.xml" \
    "dfs.replication=1" \
    "dfs.datanode.data.dir=${DATA}/dn" \
    "dfs.namenode.acls.enabled=true" \
    "dfs.namenode.safemode.extension=0" \
    "dfs.namenode.safemode.min.datanodes=0" \
    "dfs.namenode.fs-limits.min-block-size=1024" \
    "dfs.datanode.hostname=${HOST}" \
    "dfs.datanode.address=${HOST}:${P_DN_DATA}" \
    "dfs.datanode.http.address=${HOST}:${P_DN_HTTP}" \
    "dfs.datanode.ipc.address=${HOST}:${P_DN_IPC}" \
    "dfs.client.retry.policy.enabled=false" \
    "$@"
}

# base_yarn: node manager, log aggregation and resources; RM addresses are
# the architecture's business.
base_yarn() {
  site "${HADOOP_CONF_DIR}/yarn-site.xml" \
    "yarn.nodemanager.address=${HOST}:45454" \
    "yarn.nodemanager.webapp.address=${HOST}:${P_NM_HTTP}" \
    "yarn.nodemanager.localizer.address=${HOST}:${P_NM_LOCALIZER}" \
    "yarn.nodemanager.aux-services=mapreduce_shuffle" \
    "yarn.nodemanager.aux-services.mapreduce_shuffle.class=org.apache.hadoop.mapred.ShuffleHandler" \
    "yarn.nodemanager.resource.memory-mb=${E2E_NM_MEMORY_MB:-6144}" \
    "yarn.nodemanager.resource.cpu-vcores=8" \
    "yarn.scheduler.minimum-allocation-mb=256" \
    "yarn.scheduler.maximum-allocation-mb=2048" \
    "yarn.nodemanager.vmem-check-enabled=false" \
    "yarn.nodemanager.pmem-check-enabled=false" \
    "yarn.nodemanager.disk-health-checker.max-disk-utilization-per-disk-percentage=99.5" \
    "yarn.nodemanager.local-dirs=${DATA}/nm-local" \
    "yarn.nodemanager.log-dirs=${HADOOP_LOG_DIR}/userlogs" \
    "yarn.nodemanager.delete.debug-delay-sec=3600" \
    "yarn.log-aggregation-enable=true" \
    "yarn.nodemanager.remote-app-log-dir=/tmp/logs" \
    "yarn.log.server.url=${JHS_URL}/jobhistory/logs" \
    "yarn.resourcemanager.connect.retry-interval.ms=1000" \
    "$@"
}

base_mapred() {
  site "${HADOOP_CONF_DIR}/mapred-site.xml" \
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
    "mapreduce.reduce.java.opts=-Xmx200m" \
    "$@"
}

# yarn_rm_addresses <rm-id or ""> <offset>: the five RM addresses, ports
# shifted by offset; with an id, as the per-id HA form of the names.
yarn_rm_addresses() {
  local id=${1:+.$1} off=$2
  echo "yarn.resourcemanager.address${id}=${HOST}:$((P_RM + off))"
  echo "yarn.resourcemanager.scheduler.address${id}=${HOST}:$((P_RM_SCHED + off))"
  echo "yarn.resourcemanager.resource-tracker.address${id}=${HOST}:$((P_RM_TRACKER + off))"
  echo "yarn.resourcemanager.admin.address${id}=${HOST}:$((P_RM_ADMIN + off))"
  echo "yarn.resourcemanager.webapp.address${id}=${HOST}:$((P_RM_HTTP + off))"
  echo "yarn.resourcemanager.webapp.https.address${id}=${HOST}:$((P_RM_HTTPS + off))"
}

# ------------------------------------------------------------- ZooKeeper

# ZooKeeper from the jars the distribution already ships for HA and the
# federation state stores.
start_zk() {
  local dir="${RUN}/zk"
  mkdir -p "${dir}/data"
  cat > "${dir}/zoo.cfg" <<EOF
tickTime=2000
dataDir=${dir}/data
clientPort=${P_ZK}
clientPortAddress=${HOST}
admin.enableServer=false
4lw.commands.whitelist=ruok,srvr
maxClientCnxns=200
EOF
  log "starting zookeeper on ${P_ZK}"
  nohup java -Xmx256m -cp "${DIST}/share/hadoop/common/lib/*" \
    -Dzookeeper.log.dir="${HADOOP_LOG_DIR}" \
    org.apache.zookeeper.server.quorum.QuorumPeerMain "${dir}/zoo.cfg" \
    > "${HADOOP_LOG_DIR}/zookeeper.out" 2>&1 &
  echo $! > "${HADOOP_PID_DIR}/zookeeper.pid"
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if [[ "$(python3 -c "import socket; s=socket.create_connection(('${HOST}', ${P_ZK}), 2); s.sendall(b'ruok'); print(s.recv(4).decode())" 2>/dev/null)" == imok ]]; then
      echo "zookeeper up" >> "${RES}/daemons.txt"
      return 0
    fi
    sleep 1
  done
  echo "zookeeper start-failed" >> "${RES}/daemons.txt"
  die "zookeeper did not start; see ${HADOOP_LOG_DIR}/zookeeper.out"
}

# ------------------------------------------------------------------ KDC

KDC_DIR="${RUN}/kdc"
KEYTAB="${KDC_DIR}/hadoop.keytab"
REALM=EXAMPLE.COM
# Every service and the test user share one keytab.
PRINCIPALS=(nn dn jn sn rm nm jhs tl httpfs router HTTP)

# The KDC is hadoop-minikdc's standalone MiniKdc, from the side's build.
start_kdc() {
  local cp
  cp="$(side_dir "${SIDE}")/tools/minikdc"
  [[ -d "${cp}" ]] || die "no MiniKdc classpath at ${cp}; run build.sh ${SIDE}"
  rm -rf "${KDC_DIR}"
  mkdir -p "${KDC_DIR}"
  cat > "${KDC_DIR}/kdc.properties" <<EOF
kdc.port=${P_KDC}
kdc.bind.address=${HOST}
max.ticket.lifetime=86400000
max.renewable.lifetime=604800000
EOF
  local principals=("${USER_NAME}") p
  for p in "${PRINCIPALS[@]}"; do principals+=("${p}/${HOST}"); done
  log "starting MiniKdc on ${P_KDC}"
  nohup java -Xmx256m -cp "${cp}/*" org.apache.hadoop.minikdc.MiniKdc \
    "${KDC_DIR}" "${KDC_DIR}/kdc.properties" "${KEYTAB}" "${principals[@]}" \
    > "${HADOOP_LOG_DIR}/minikdc.out" 2>&1 &
  echo $! > "${HADOOP_PID_DIR}/minikdc.pid"
  local deadline=$((SECONDS + 60))
  until grep -q 'Standalone MiniKdc Running' "${HADOOP_LOG_DIR}/minikdc.out" 2>/dev/null; do
    (( SECONDS < deadline )) || die "MiniKdc did not start; see ${HADOOP_LOG_DIR}/minikdc.out"
    sleep 1
  done
  echo "minikdc up" >> "${RES}/daemons.txt"
  kinit_user
}

# kinit_user: a ticket cache for the test user. The system kinit when there
# is one, otherwise the Kerby client library MiniKdc itself is built on.
kinit_user() {
  if command -v kinit >/dev/null; then
    kinit -kt "${KEYTAB}" "${USER_NAME}@${REALM}" \
      || die "kinit failed"
  else
    java -cp "$(side_dir "${SIDE}")/tools/minikdc/*" "${E2E_DIR}/lib/KerbyKinit.java" \
      "${KDC_DIR}" "${KEYTAB}" "${USER_NAME}@${REALM}" "${KRB5CCNAME#FILE:}" \
      > "${RES}/kinit.log" 2>&1 || die "Kerby kinit failed; see ${RES}/kinit.log"
  fi
}

# ------------------------------------------------------------------ TLS

TLS_DIR="${RUN}/tls"
TLS_PASS=jetty12pass

# make_tls: a self-signed certificate for localhost, its keystore, a
# truststore, the PEM for curl and Python, and ssl-server/ssl-client.xml.
make_tls() {
  rm -rf "${TLS_DIR}"
  mkdir -p "${TLS_DIR}"
  keytool -genkeypair -noprompt -alias localhost -keyalg RSA -keysize 2048 \
    -validity 30 -dname "CN=${HOST}" -ext "SAN=dns:${HOST},ip:127.0.0.1" \
    -keystore "${TLS_DIR}/server.jks" -storetype JKS \
    -storepass "${TLS_PASS}" -keypass "${TLS_PASS}" > /dev/null 2>&1 \
    || die "keytool could not create the keystore"
  keytool -exportcert -rfc -alias localhost -keystore "${TLS_DIR}/server.jks" \
    -storepass "${TLS_PASS}" > "${TLS_DIR}/ca.pem" 2>/dev/null
  keytool -importcert -noprompt -alias localhost -file "${TLS_DIR}/ca.pem" \
    -keystore "${TLS_DIR}/truststore.jks" -storetype JKS \
    -storepass "${TLS_PASS}" > /dev/null 2>&1
  site "${HADOOP_CONF_DIR}/ssl-server.xml" \
    "ssl.server.keystore.location=${TLS_DIR}/server.jks" \
    "ssl.server.keystore.password=${TLS_PASS}" \
    "ssl.server.keystore.keypassword=${TLS_PASS}" \
    "ssl.server.keystore.type=jks" \
    "ssl.server.truststore.location=${TLS_DIR}/truststore.jks" \
    "ssl.server.truststore.password=${TLS_PASS}" \
    "ssl.server.truststore.type=jks"
  site "${HADOOP_CONF_DIR}/ssl-client.xml" \
    "ssl.client.truststore.location=${TLS_DIR}/truststore.jks" \
    "ssl.client.truststore.password=${TLS_PASS}" \
    "ssl.client.truststore.type=jks"
}

stop_services() {
  local svc pid
  for svc in zookeeper minikdc; do
    pid=$(cat "${HADOOP_PID_DIR}/${svc}.pid" 2>/dev/null || true)
    [[ -n "${pid}" ]] && kill "${pid}" 2>/dev/null || true
  done
}
