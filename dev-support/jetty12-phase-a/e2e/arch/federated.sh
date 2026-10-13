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

# federated: HDFS federation and YARN federation.
#   HDFS: two namenodes with independent namespaces (ns1, ns2), one datanode
#   serving both block pools, an RBF router with the ZooKeeper state store,
#   and a ViewFS mount table for clients.
#   YARN: two sub-clusters (sc1, sc2), each a resource manager and a node
#   manager, registered in the ZooKeeper federation state store; the YARN
#   router with the federation interceptors (client RPC, REST, admin) and
#   the global policy generator.
# 85-federation.sh drives both.

ARCH_SCENARIOS='^(00|10|85)-'
ARCH_SERVICES=(zookeeper)

FED_NS=(ns1 ns2)
FED_NN=(nnns1 nnns2)
FED_RPC=(9000 9001)
FED_HTTP=(9870 9880)
FED_FS=("hdfs://${HOST}:9000" "hdfs://${HOST}:9001")
NN_URL="http://${HOST}:${FED_HTTP[0]}"
NN2_URL="http://${HOST}:${FED_HTTP[1]}"
ROUTER_FS="hdfs://${HOST}:${P_ROUTER_RPC}"
ROUTER_URL="http://${HOST}:${P_ROUTER_HTTP}"
VIEWFS="viewfs://cluster"
# YARN sub-clusters: RM port offset, NM RPC/web/localizer/shuffle ports.
SC=(sc1 sc2)
SC_RM_OFFSET=(0 10000)
SC_NM_RPC=(45454 45455)
SC_NM_HTTP=(8042 8043)
SC_NM_LOC=(8040 8041)
SC_SHUFFLE=(13562 13563)
RM_URL="http://${HOST}:${P_RM_HTTP}"
RM2_URL="http://${HOST}:$((P_RM_HTTP + SC_RM_OFFSET[1]))"
YROUTER_URL="http://${HOST}:${P_YROUTER_HTTP}"
YROUTER_RPC="${HOST}:${P_YROUTER_CLIENT}"
GPG_URL="http://${HOST}:${P_GPG_HTTP}"
PROXY_URL="${RM_URL}"
FS="${FED_FS[0]}"
WEBHDFS_FS="webhdfs://${HOST}:${FED_HTTP[0]}"

INSTANCES=(
  "nnns1 hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx ${RUN}/conf-nnns1"
  "nnns2 hdfs namenode HDFS_NAMENODE ${NN2_URL}/jmx ${RUN}/conf-nnns2"
  "datanode hdfs datanode HDFS_DATANODE ${DN_URL}/jmx ${HADOOP_CONF_DIR}"
  "dfsrouter hdfs dfsrouter HDFS_DFSROUTER ${ROUTER_URL}/jmx ${HADOOP_CONF_DIR}"
  "rmsc1 yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx ${RUN}/conf-rmsc1"
  "rmsc2 yarn resourcemanager YARN_RESOURCEMANAGER ${RM2_URL}/jmx ${RUN}/conf-rmsc2"
  "nmsc1 yarn nodemanager YARN_NODEMANAGER http://${HOST}:${SC_NM_HTTP[0]}/jmx ${RUN}/conf-nmsc1"
  "nmsc2 yarn nodemanager YARN_NODEMANAGER http://${HOST}:${SC_NM_HTTP[1]}/jmx ${RUN}/conf-nmsc2"
  "yrouter yarn router YARN_ROUTER ${YROUTER_URL}/jmx ${HADOOP_CONF_DIR}"
  "gpg yarn globalpolicygenerator YARN_GLOBALPOLICYGENERATOR ${GPG_URL}/jmx ${HADOOP_CONF_DIR}"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx ${HADOOP_CONF_DIR}"
)

# federation_yarn_props: what every YARN process of the federation shares.
federation_yarn_props() {
  echo "yarn.federation.enabled=true"
  echo "yarn.federation.state-store.class=org.apache.hadoop.yarn.server.federation.store.impl.ZookeeperFederationStateStore"
  echo "hadoop.zk.address=${HOST}:${P_ZK}"
  echo "yarn.router.webapp.address=${HOST}:${P_YROUTER_HTTP}"
  echo "yarn.router.clientrm.address=${YROUTER_RPC}"
  echo "yarn.router.rmadmin.address=${HOST}:${P_YROUTER_ADMIN}"
  echo "yarn.router.clientrm.interceptor-class.pipeline=org.apache.hadoop.yarn.server.router.clientrm.FederationClientInterceptor"
  echo "yarn.router.webapp.interceptor-class.pipeline=org.apache.hadoop.yarn.server.router.webapp.FederationInterceptorREST"
  echo "yarn.router.rmadmin.interceptor-class.pipeline=org.apache.hadoop.yarn.server.router.rmadmin.FederationRMAdminInterceptor"
  echo "yarn.federation.gpg.webapp.address=${GPG_URL#http://}"
  echo "yarn.federation.cache-ttl.secs=0"
}

arch_conf() {
  local d="${DATA}" i
  base_core "fs.defaultFS=${FS}" \
    "fs.viewfs.mounttable.cluster.link./ns1=${FED_FS[0]}/fed1" \
    "fs.viewfs.mounttable.cluster.link./ns2=${FED_FS[1]}/fed2" \
    "fs.viewfs.mounttable.cluster.link./tmp=${FED_FS[0]}/tmp" \
    "fs.viewfs.mounttable.cluster.link./user=${FED_FS[0]}/user"
  base_hdfs "dfs.nameservices=ns1,ns2" \
    "dfs.namenode.rpc-address.ns1=${HOST}:${FED_RPC[0]}" \
    "dfs.namenode.http-address.ns1=${HOST}:${FED_HTTP[0]}" \
    "dfs.namenode.rpc-address.ns2=${HOST}:${FED_RPC[1]}" \
    "dfs.namenode.http-address.ns2=${HOST}:${FED_HTTP[1]}"
  site "${HADOOP_CONF_DIR}/hdfs-rbf-site.xml" \
    "dfs.federation.router.rpc-address=${HOST}:${P_ROUTER_RPC}" \
    "dfs.federation.router.http-address=${HOST}:${P_ROUTER_HTTP}" \
    "dfs.federation.router.admin-address=${HOST}:${P_ROUTER_ADMIN}" \
    "dfs.federation.router.default.nameserviceId=ns1" \
    "dfs.federation.router.monitor.namenode=ns1,ns2" \
    "dfs.federation.router.store.driver.class=org.apache.hadoop.hdfs.server.federation.store.driver.impl.StateStoreZooKeeperImpl" \
    "hadoop.zk.address=${HOST}:${P_ZK}"
  # The client talks to sub-cluster sc1 directly; scenarios go through the
  # YARN router explicitly.
  # shellcheck disable=SC2046
  base_yarn $(yarn_rm_addresses "" 0) $(federation_yarn_props)
  base_mapred
  for i in 0 1; do
    site "$(instance_conf "${FED_NN[i]}")/hdfs-site.xml" \
      "dfs.nameservice.id=${FED_NS[i]}" \
      "dfs.namenode.name.dir=${d}/${FED_NN[i]}"
    # shellcheck disable=SC2046
    site "$(instance_conf "rm${SC[i]}")/yarn-site.xml" \
      $(yarn_rm_addresses "" "${SC_RM_OFFSET[i]}") \
      "yarn.resourcemanager.cluster-id=${SC[i]}" \
      "yarn.resourcemanager.epoch=$((i * 1000))"
    # shellcheck disable=SC2046
    site "$(instance_conf "nm${SC[i]}")/yarn-site.xml" \
      $(yarn_rm_addresses "" "${SC_RM_OFFSET[i]}") \
      "yarn.resourcemanager.cluster-id=${SC[i]}" \
      "yarn.nodemanager.address=${HOST}:${SC_NM_RPC[i]}" \
      "yarn.nodemanager.webapp.address=${HOST}:${SC_NM_HTTP[i]}" \
      "yarn.nodemanager.localizer.address=${HOST}:${SC_NM_LOC[i]}" \
      "yarn.nodemanager.local-dirs=${d}/nm-local-${SC[i]}" \
      "yarn.nodemanager.log-dirs=${HADOOP_LOG_DIR}/userlogs-${SC[i]}" \
      "yarn.nodemanager.resource.memory-mb=$(( ${E2E_NM_MEMORY_MB:-6144} / 2 ))" \
      "mapreduce.shuffle.port=${SC_SHUFFLE[i]}"
  done
}

arch_prepare() {
  log "formatting both namenodes into one cluster id"
  hdfs --config "${RUN}/conf-nnns1" namenode -format -force -nonInteractive -clusterid CID-jetty12 \
    > "${RES}/namenode-format.log" 2>&1 || die "nnns1 format failed; see ${RES}/namenode-format.log"
  hdfs --config "${RUN}/conf-nnns2" namenode -format -force -nonInteractive -clusterid CID-jetty12 \
    >> "${RES}/namenode-format.log" 2>&1 || die "nnns2 format failed; see ${RES}/namenode-format.log"
}

arch_after_start() {
  hadoop fs -fs "${FED_FS[1]}" -mkdir -p /fed2 /tmp >/dev/null 2>&1 || true
  hadoop fs -fs "${FED_FS[0]}" -mkdir -p /fed1 >/dev/null 2>&1 || true
  # Sub-clusters register with the state store on their first heartbeat.
  sleep 10
}
