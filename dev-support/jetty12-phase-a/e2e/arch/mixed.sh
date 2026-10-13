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

# mixed: HA and federation together, the way large deployments run.
#   HDFS: nameservice ns1 is HA (two namenodes, three journalnodes, ZKFC),
#   ns2 is a single namenode; one datanode serves both. Two RBF routers share
#   the ZooKeeper state store, and clients see them as one HA nameservice
#   ("routerfed"), which is the default file system: every client, including
#   YARN and MapReduce, goes through RBF.
#   YARN: two resource managers in HA, a node manager, the job history
#   server.
# 80-ha.sh fails over ns1 and the RMs underneath the routers; 85-federation.sh
# covers the router mount table across HA and non-HA namespaces; 90-mixed.sh
# kills a router, and runs MapReduce on RBF.

ARCH_SERVICES=(zookeeper)
ARCH_SCENARIOS='^(00|10|80|85|90)-'

# Shared with ha.sh's helpers.
source "${E2E_DIR}/arch/ha.sh"
ARCH_SCENARIOS='^(00|10|80|85|90)-'

HA_NS=ns1
FED_NS=(ns1 ns2)
FED_FS=("hdfs://ns1" "hdfs://${HOST}:9002")
NN2_URL="http://${HOST}:${HA_NN_HTTP[1]}"
NS2_URL="http://${HOST}:9882"
ROUTERS=(router1 router2)
ROUTER_RPC=(8888 8889)
ROUTER_HTTP=(50071 50072)
ROUTER_ADMIN=(8111 8112)
ROUTER_FS="hdfs://routerfed"
ROUTER_URL="http://${HOST}:${ROUTER_HTTP[0]}"
FS="${ROUTER_FS}"
# The routers start after the datanode; shared directories go straight to
# ns1, the routers' default namespace.
FS_DIRECT="hdfs://ns1"
WEBHDFS_FS="webhdfs://${HOST}:${ROUTER_HTTP[0]}"

INSTANCES=()
for i in 0 1 2; do
  INSTANCES+=("jn$((i + 1)) hdfs journalnode HDFS_JOURNALNODE http://${HOST}:${JN_HTTP[i]}/jmx ${RUN}/conf-jn$((i + 1))")
done
INSTANCES+=(
  "nn1 hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx ${RUN}/conf-nn1"
  "zkfc1 hdfs zkfc HDFS_ZKFC - ${RUN}/conf-nn1"
  "nn2 hdfs namenode HDFS_NAMENODE ${NN2_URL}/jmx ${RUN}/conf-nn2"
  "zkfc2 hdfs zkfc HDFS_ZKFC - ${RUN}/conf-nn2"
  "nnns2 hdfs namenode HDFS_NAMENODE ${NS2_URL}/jmx ${RUN}/conf-nnns2"
  "datanode hdfs datanode HDFS_DATANODE ${DN_URL}/jmx ${RUN}/conf-datanode"
  "router1 hdfs dfsrouter HDFS_DFSROUTER http://${HOST}:${ROUTER_HTTP[0]}/jmx ${RUN}/conf-router1"
  "router2 hdfs dfsrouter HDFS_DFSROUTER http://${HOST}:${ROUTER_HTTP[1]}/jmx ${RUN}/conf-router2"
  "rm1 yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx ${RUN}/conf-rm1"
  "rm2 yarn resourcemanager YARN_RESOURCEMANAGER ${RM2_URL}/jmx ${RUN}/conf-rm2"
  "nodemanager yarn nodemanager YARN_NODEMANAGER ${NM_URL}/jmx ${HADOOP_CONF_DIR}"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx ${HADOOP_CONF_DIR}"
)

arch_conf() {
  local d="${DATA}" i
  base_core "fs.defaultFS=${FS}" "ha.zookeeper.quorum=${HOST}:${P_ZK}"
  # Clients know the two routers as an HA nameservice, and ns1/ns2 directly.
  # shellcheck disable=SC2046
  base_hdfs "dfs.nameservices=ns1,ns2,routerfed" \
    $(ha_hdfs_props ns1 "${HA_NN[*]}" "${HA_NN_RPC[*]}" "${HA_NN_HTTP[*]}" "$(ha_journal ns1)" "${HA_ZKFC_PORT[*]}") \
    "dfs.namenode.rpc-address.ns2=${HOST}:9002" \
    "dfs.namenode.http-address.ns2=${HOST}:9882" \
    $(ha_hdfs_props routerfed "r1 r2" "${ROUTER_RPC[*]}" "${ROUTER_HTTP[*]}" "") \
    "dfs.ha.fencing.methods=shell(/bin/true)"
  site "${HADOOP_CONF_DIR}/hdfs-site.xml" "dfs.namenode.shared.edits.dir" \
    "dfs.namenode.shared.edits.dir.ns1=$(ha_journal ns1)" \
    "dfs.ha.automatic-failover.enabled.routerfed"
  site "${HADOOP_CONF_DIR}/hdfs-rbf-site.xml" \
    "dfs.federation.router.default.nameserviceId=ns1" \
    "dfs.federation.router.monitor.namenode=ns1.nn1,ns1.nn2,ns2" \
    "dfs.federation.router.monitor.localnamenode.enable=false" \
    "dfs.federation.router.file.resolver.client.class=org.apache.hadoop.hdfs.server.federation.resolver.MultipleDestinationMountTableResolver" \
    "dfs.federation.router.mount-table.cache.update=true" \
    "dfs.federation.router.store.driver.class=org.apache.hadoop.hdfs.server.federation.store.driver.impl.StateStoreZooKeeperImpl" \
    "hadoop.zk.address=${HOST}:${P_ZK}"
  # shellcheck disable=SC2046
  base_yarn $(ha_yarn_props)
  base_mapred
  # Servers only know the real nameservices.
  local server
  for server in jn1 jn2 jn3 nn1 nn2 nnns2 datanode router1 router2; do
    site "$(instance_conf "${server}")/hdfs-site.xml" "dfs.nameservices=ns1,ns2" \
      "dfs.internal.nameservices=ns1,ns2"
  done
  for i in 0 1 2; do
    site "${RUN}/conf-jn$((i + 1))/hdfs-site.xml" \
      "dfs.journalnode.rpc-address=${HOST}:${JN_RPC[i]}" \
      "dfs.journalnode.http-address=${HOST}:${JN_HTTP[i]}" \
      "dfs.journalnode.edits.dir=${d}/jn$((i + 1))"
  done
  for i in 0 1; do
    site "${RUN}/conf-${HA_NN[i]}/hdfs-site.xml" \
      "dfs.nameservice.id=ns1" \
      "dfs.ha.namenode.id=${HA_NN[i]}" \
      "dfs.namenode.name.dir=${d}/${HA_NN[i]}"
    site "$(instance_conf "${HA_RM[i]}")/yarn-site.xml" "yarn.resourcemanager.ha.id=${HA_RM[i]}"
    site "${RUN}/conf-${ROUTERS[i]}/hdfs-rbf-site.xml" \
      "dfs.federation.router.rpc-address=${HOST}:${ROUTER_RPC[i]}" \
      "dfs.federation.router.http-address=${HOST}:${ROUTER_HTTP[i]}" \
      "dfs.federation.router.admin-address=${HOST}:${ROUTER_ADMIN[i]}"
  done
  site "${RUN}/conf-nnns2/hdfs-site.xml" \
    "dfs.nameservice.id=ns2" \
    "dfs.namenode.name.dir=${d}/nnns2"
}

arch_prepare() {
  local line
  for line in "${INSTANCES[@]:0:3}"; do
    # shellcheck disable=SC2086
    start_instance ${line}
  done
  log "formatting ns1 (HA) and ns2 into one cluster id"
  hdfs --config "${RUN}/conf-nn1" namenode -format -force -nonInteractive -clusterid CID-jetty12 \
    > "${RES}/namenode-format.log" 2>&1 || die "nn1 format failed; see ${RES}/namenode-format.log"
  hdfs --config "${RUN}/conf-nn1" zkfc -formatZK -force -nonInteractive \
    > "${RES}/zkfc-format.log" 2>&1 || die "ZKFC format failed; see ${RES}/zkfc-format.log"
  hdfs --config "${RUN}/conf-nnns2" namenode -format -force -nonInteractive -clusterid CID-jetty12 \
    >> "${RES}/namenode-format.log" 2>&1 || die "nnns2 format failed; see ${RES}/namenode-format.log"
  # shellcheck disable=SC2086
  start_instance ${INSTANCES[3]}
  # shellcheck disable=SC2086
  start_instance ${INSTANCES[4]}
  log "bootstrapping nn2 from nn1"
  hdfs --config "${RUN}/conf-nn2" namenode -bootstrapStandby -force -nonInteractive \
    > "${RES}/bootstrap-standby.log" 2>&1 || die "nn2 bootstrap failed; see ${RES}/bootstrap-standby.log"
  SKIP_INSTANCES="jn1 jn2 jn3 nn1 zkfc1"
}

arch_after_start() {
  local i
  for i in $(seq 1 30); do
    hdfs haadmin -ns ns1 -getServiceState nn1 2>/dev/null | grep -q active && break
    sleep 2
  done
  # Routers learn about the namenodes from their heartbeats.
  sleep 10
  hdfs dfsrouteradmin -add /data2 ns2 /data2 >/dev/null 2>&1 || true
  hdfs dfsrouteradmin -add /data1 ns1 /data1 >/dev/null 2>&1 || true
  hdfs dfsrouteradmin -refresh >/dev/null 2>&1 || true
  log "ns1 states: $(hdfs haadmin -ns ns1 -getAllServiceState 2>/dev/null | tr '\n' ' ')"
  log "resource manager states: $(yarn rmadmin -getAllServiceState 2>/dev/null | tr '\n' ' ')"
}
