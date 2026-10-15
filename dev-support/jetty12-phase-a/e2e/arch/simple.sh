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

# simple: one of every daemon, simple authentication over HTTP. The widest
# coverage of components: HDFS with secondary namenode and a standalone
# journalnode, the HDFS router, HttpFS, KMS, the NFS gateway (as root), the
# resource manager, node manager, timeline server, standalone web proxy,
# YARN router, shared cache manager, timeline reader v2, and the job
# history server.

ARCH_SCENARIOS='^(00|10|20|30|40|50|60)-'
# The YARN service registry (and so service destroy) needs ZooKeeper.
ARCH_SERVICES=(zookeeper)
C="${HADOOP_CONF_DIR}"
INSTANCES=(
  "namenode hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx ${C}"
  "datanode hdfs datanode HDFS_DATANODE ${DN_URL}/jmx ${C}"
  "secondarynamenode hdfs secondarynamenode HDFS_SECONDARYNAMENODE ${SNN_URL}/jmx ${C}"
  "journalnode hdfs journalnode HDFS_JOURNALNODE ${JN_URL}/jmx ${C}"
  "kms hadoop kms HADOOP_KMS ${KMS_URL}/jmx ${C}"
  "httpfs hdfs httpfs HDFS_HTTPFS ${HTTPFS_URL}/jmx ${C}"
  "dfsrouter hdfs dfsrouter HDFS_DFSROUTER http://${HOST}:${P_ROUTER_HTTP}/jmx ${C}"
  "resourcemanager yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx ${C}"
  "nodemanager yarn nodemanager YARN_NODEMANAGER ${NM_URL}/jmx ${C}"
  "timelineserver yarn timelineserver YARN_TIMELINESERVER ${AHS_URL}/jmx ${C}"
  "proxyserver yarn proxyserver YARN_PROXYSERVER ${PROXY_URL}/jmx ${C}"
  "router yarn router YARN_ROUTER http://${HOST}:${P_YROUTER_HTTP}/jmx ${C}"
  "sharedcachemanager yarn sharedcachemanager YARN_SHAREDCACHEMANAGER http://${HOST}:${P_SCM_HTTP}/jmx ${C}"
  "timelinereader yarn timelinereader YARN_TIMELINEREADER http://${HOST}:${P_TLREADER_HTTP}/jmx ${RUN}/conf-atsv2"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx ${C}"
)
# The NFS gateway needs the privileged portmap port.
if [[ "${E2E_NFS:-auto}" == true || ( "${E2E_NFS:-auto}" == auto && ${EUID} -eq 0 ) ]]; then
  INSTANCES+=(
    "portmap hdfs portmap HDFS_PORTMAP - ${C}"
    "nfs3 hdfs nfs3 HDFS_NFS3 http://${HOST}:${P_NFS_HTTP}/jmx ${C}"
  )
fi

arch_conf() {
  local d="${DATA}"
  base_core "fs.defaultFS=${FS}" \
    "hadoop.security.key.provider.path=${KMS_PROVIDER}" \
    "nfs.exports.allowed.hosts=* rw" \
    "hadoop.registry.zk.quorum=${HOST}:${P_ZK}"
  base_hdfs \
    "dfs.namenode.name.dir=${d}/nn" \
    "dfs.namenode.checkpoint.dir=${d}/snn" \
    "dfs.journalnode.edits.dir=${d}/jn" \
    "dfs.namenode.http-address=${HOST}:${P_NN_HTTP}" \
    "dfs.namenode.secondary.http-address=${HOST}:${P_SNN_HTTP}" \
    "dfs.journalnode.rpc-address=${HOST}:${P_JN_RPC}" \
    "dfs.journalnode.http-address=${HOST}:${P_JN_HTTP}" \
    "nfs.dump.dir=${RUN}/tmp/nfs" \
    "nfs.server.port=${P_NFS3}" \
    "nfs.mountd.port=${P_MOUNTD}" \
    "nfs.http.address=${HOST}:${P_NFS_HTTP}"
  # Router WebHDFS redirects name the router by its id, the local hostname
  # plus the RPC port (Router#setRpcServerAddress), whatever its RPC address;
  # the router listens on all interfaces so the datanode reaches it (on CI
  # runners the hostname is not a loopback address).
  site "${HADOOP_CONF_DIR}/hdfs-rbf-site.xml" \
    "dfs.nameservices=ns0" \
    "dfs.namenode.rpc-address.ns0=${HOST}:${P_NN_RPC}" \
    "dfs.namenode.http-address.ns0=${HOST}:${P_NN_HTTP}" \
    "dfs.federation.router.default.nameserviceId=ns0" \
    "dfs.federation.router.rpc-address=${HOST}:${P_ROUTER_RPC}" \
    "dfs.federation.router.rpc-bind-host=0.0.0.0" \
    "dfs.federation.router.http-address=${HOST}:${P_ROUTER_HTTP}" \
    "dfs.federation.router.admin-address=${HOST}:${P_ROUTER_ADMIN}" \
    "dfs.federation.router.monitor.namenode=ns0" \
    "dfs.federation.router.store.driver.class=org.apache.hadoop.hdfs.server.federation.store.driver.impl.StateStoreFileImpl" \
    "dfs.federation.router.store.driver.file.directory=${d}/router-store"
  # shellcheck disable=SC2046
  base_yarn $(yarn_rm_addresses "" 0) \
    "yarn.resourcemanager.hostname=${HOST}" \
    "yarn.web-proxy.address=${HOST}:${P_PROXY}" \
    "yarn.timeline-service.enabled=true" \
    "yarn.system-metrics-publisher.enabled=true" \
    "yarn.timeline-service.hostname=${HOST}" \
    "yarn.timeline-service.address=${HOST}:${P_AHS_RPC}" \
    "yarn.timeline-service.webapp.address=${HOST}:${P_AHS_HTTP}" \
    "yarn.timeline-service.leveldb-timeline-store.path=${d}/timeline" \
    "yarn.timeline-service.leveldb-state-store.path=${d}/timeline-state" \
    "yarn.timeline-service.generic-application-history.enabled=true" \
    "yarn.router.webapp.address=${HOST}:${P_YROUTER_HTTP}" \
    "yarn.router.clientrm.address=${HOST}:${P_YROUTER_CLIENT}" \
    "yarn.router.rmadmin.address=${HOST}:${P_YROUTER_ADMIN}" \
    "yarn.sharedcache.webapp.address=${HOST}:${P_SCM_HTTP}" \
    "yarn.sharedcache.admin.address=${HOST}:${P_SCM_ADMIN}" \
    "yarn.sharedcache.client-server.address=${HOST}:${P_SCM_CLIENT}" \
    "yarn.sharedcache.uploader.server.address=${HOST}:${P_SCM_UPLOADER}" \
    "yarn.webapp.api-service.enable=true"
  base_mapred
  site "${HADOOP_CONF_DIR}/kms-site.xml" \
    "hadoop.kms.key.provider.uri=jceks://file@${d}/kms.keystore" \
    "hadoop.kms.http.port=${P_KMS}" \
    "hadoop.kms.proxyuser.${USER_NAME}.users=*" \
    "hadoop.kms.proxyuser.${USER_NAME}.groups=*" \
    "hadoop.kms.proxyuser.${USER_NAME}.hosts=*"
  site "${HADOOP_CONF_DIR}/httpfs-site.xml" \
    "httpfs.http.port=${P_HTTPFS}" \
    "httpfs.proxyuser.${USER_NAME}.hosts=*" \
    "httpfs.proxyuser.${USER_NAME}.groups=*"

  # The timeline reader only starts with timeline service v2 enabled, which
  # would change how the RM and NM publish; it gets its own configuration,
  # with the file system storage from Hadoop's timelineservice test jar.
  local atsv2
  atsv2=$(instance_conf atsv2)
  site "${atsv2}/yarn-site.xml" \
    "yarn.timeline-service.version=2.0f" \
    "yarn.timeline-service.reader.webapp.address=${HOST}:${P_TLREADER_HTTP}" \
    "yarn.timeline-service.reader.class=org.apache.hadoop.yarn.server.timelineservice.storage.FileSystemTimelineReaderImpl" \
    "yarn.timeline-service.fs-writer.root-dir=${d}/atsv2"
}

arch_prepare() {
  log "formatting the namenode"
  hdfs namenode -format -force -nonInteractive > "${RES}/namenode-format.log" 2>&1 \
    || die "namenode format failed; see ${RES}/namenode-format.log"
}
