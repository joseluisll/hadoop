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

# ha: high availability. ZooKeeper; three journalnodes; two namenodes of
# nameservice "hacluster" with ZKFC automatic failover over the quorum
# journal; two resource managers with embedded leader election and the
# ZooKeeper state store; a datanode, a node manager and the job history
# server. 80-ha.sh kills the active namenode and resource manager and checks
# that the standby takes over, that standby web servers behave (redirects,
# StandbyException, /isActive) and that work continues.

ARCH_SCENARIOS='^(00|10|20|50|80)-'
ARCH_SERVICES=(zookeeper)

HA_NS=hacluster
FS="hdfs://${HA_NS}"
# Namenode and RM instances, their ids and web addresses (80-ha.sh).
HA_NN=(nn1 nn2)
HA_NN_RPC=(9000 9001)
HA_NN_HTTP=(9870 9880)
# Each ZKFC serves RPC on its own port (default 8019 for all of them).
HA_ZKFC_PORT=(8019 8029)
HA_RM=(rm1 rm2)
HA_RM_OFFSET=(0 10000)
NN_URL="http://${HOST}:${HA_NN_HTTP[0]}"
NN2_URL="http://${HOST}:${HA_NN_HTTP[1]}"
RM_URL="http://${HOST}:${P_RM_HTTP}"
RM2_URL="http://${HOST}:$((P_RM_HTTP + HA_RM_OFFSET[1]))"
PROXY_URL="${RM_URL}"
WEBHDFS_FS="webhdfs://${HA_NS}"
JN_RPC=(8485 8486 8487)
JN_HTTP=(8480 8481 8482)

INSTANCES=()
for i in 0 1 2; do
  INSTANCES+=("jn$((i + 1)) hdfs journalnode HDFS_JOURNALNODE http://${HOST}:${JN_HTTP[i]}/jmx ${RUN}/conf-jn$((i + 1))")
done
INSTANCES+=(
  "nn1 hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx ${RUN}/conf-nn1"
  "zkfc1 hdfs zkfc HDFS_ZKFC - ${RUN}/conf-nn1"
  "nn2 hdfs namenode HDFS_NAMENODE ${NN2_URL}/jmx ${RUN}/conf-nn2"
  "zkfc2 hdfs zkfc HDFS_ZKFC - ${RUN}/conf-nn2"
  "datanode hdfs datanode HDFS_DATANODE ${DN_URL}/jmx ${HADOOP_CONF_DIR}"
  "rm1 yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx ${RUN}/conf-rm1"
  "rm2 yarn resourcemanager YARN_RESOURCEMANAGER ${RM2_URL}/jmx ${RUN}/conf-rm2"
  "nodemanager yarn nodemanager YARN_NODEMANAGER ${NM_URL}/jmx ${HADOOP_CONF_DIR}"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx ${HADOOP_CONF_DIR}"
)

# ha_hdfs_props <nameservice> <nn ids> <rpc ports> <http ports> <journal>:
# the HA configuration of one nameservice.
ha_hdfs_props() {
  local ns=$1 journal=$5 i
  local -a ids rpc web
  read -ra ids <<< "$2"
  read -ra rpc <<< "$3"
  read -ra web <<< "$4"
  echo "dfs.ha.namenodes.${ns}=$(IFS=,; echo "${ids[*]}")"
  for i in "${!ids[@]}"; do
    echo "dfs.namenode.rpc-address.${ns}.${ids[i]}=${HOST}:${rpc[i]}"
    echo "dfs.namenode.http-address.${ns}.${ids[i]}=${HOST}:${web[i]}"
  done
  echo "dfs.namenode.shared.edits.dir=${journal}"
  echo "dfs.ha.automatic-failover.enabled.${ns}=true"
  echo "dfs.client.failover.proxy.provider.${ns}=org.apache.hadoop.hdfs.server.namenode.ha.ConfiguredFailoverProxyProvider"
}

ha_journal() {
  local i list=()
  for i in 0 1 2; do list+=("${HOST}:${JN_RPC[i]}"); done
  echo "qjournal://$(IFS=';'; echo "${list[*]}")/$1"
}

# ha_yarn_props: RM HA with the ZooKeeper state store.
ha_yarn_props() {
  local i
  echo "yarn.resourcemanager.ha.enabled=true"
  echo "yarn.resourcemanager.ha.rm-ids=$(IFS=,; echo "${HA_RM[*]}")"
  echo "yarn.resourcemanager.cluster-id=yarn-ha"
  echo "yarn.resourcemanager.recovery.enabled=true"
  echo "yarn.resourcemanager.store.class=org.apache.hadoop.yarn.server.resourcemanager.recovery.ZKRMStateStore"
  echo "hadoop.zk.address=${HOST}:${P_ZK}"
  echo "yarn.resourcemanager.zk-address=${HOST}:${P_ZK}"
  for i in "${!HA_RM[@]}"; do
    echo "yarn.resourcemanager.hostname.${HA_RM[i]}=${HOST}"
    yarn_rm_addresses "${HA_RM[i]}" "${HA_RM_OFFSET[i]}"
  done
}

arch_conf() {
  local d="${DATA}" i
  base_core "fs.defaultFS=${FS}" "ha.zookeeper.quorum=${HOST}:${P_ZK}"
  # shellcheck disable=SC2046
  base_hdfs "dfs.nameservices=${HA_NS}" \
    $(ha_hdfs_props "${HA_NS}" "${HA_NN[*]}" "${HA_NN_RPC[*]}" "${HA_NN_HTTP[*]}" "$(ha_journal "${HA_NS}")") \
    "dfs.ha.fencing.methods=shell(/bin/true)"
  # shellcheck disable=SC2046
  base_yarn $(ha_yarn_props)
  base_mapred
  for i in 0 1 2; do
    site "$(instance_conf "jn$((i + 1))")/hdfs-site.xml" \
      "dfs.journalnode.rpc-address=${HOST}:${JN_RPC[i]}" \
      "dfs.journalnode.http-address=${HOST}:${JN_HTTP[i]}" \
      "dfs.journalnode.edits.dir=${d}/jn$((i + 1))"
  done
  for i in 0 1; do
    site "$(instance_conf "${HA_NN[i]}")/hdfs-site.xml" \
      "dfs.ha.namenode.id=${HA_NN[i]}" \
      "dfs.ha.zkfc.port=${HA_ZKFC_PORT[i]}" \
      "dfs.namenode.name.dir=${d}/${HA_NN[i]}"
    site "$(instance_conf "${HA_RM[i]}")/yarn-site.xml" \
      "yarn.resourcemanager.ha.id=${HA_RM[i]}"
  done
}

# Journalnodes first, then format nn1 and ZooKeeper; nn2 copies nn1's
# namespace once nn1 runs (arch_prepare runs before the instances start, so
# the journalnodes and nn1 are started here and skipped later).
arch_prepare() {
  local line
  for line in "${INSTANCES[@]:0:3}"; do
    # shellcheck disable=SC2086
    start_instance ${line}
  done
  log "formatting nn1 and the ZKFC znode"
  hdfs --config "${RUN}/conf-nn1" namenode -format -force -nonInteractive \
    > "${RES}/namenode-format.log" 2>&1 || die "nn1 format failed; see ${RES}/namenode-format.log"
  hdfs --config "${RUN}/conf-nn1" zkfc -formatZK -force -nonInteractive \
    > "${RES}/zkfc-format.log" 2>&1 || die "ZKFC format failed; see ${RES}/zkfc-format.log"
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
  # nn1 started first with its ZKFC, so it should be the active one.
  local i
  for i in $(seq 1 30); do
    hdfs haadmin -getServiceState nn1 2>/dev/null | grep -q active && break
    sleep 2
  done
  log "namenode states: $(hdfs haadmin -getAllServiceState 2>/dev/null | tr '\n' ' ')"
  log "resource manager states: $(yarn rmadmin -getAllServiceState 2>/dev/null | tr '\n' ' ')"
}
