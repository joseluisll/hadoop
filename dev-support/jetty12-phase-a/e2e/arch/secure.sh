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

# secure: Kerberos everywhere. A KDC from hadoop-minikdc; every web server
# HTTPS only (Jetty's TLS connector) with SPNEGO authentication; SASL-
# protected data transfer with block access tokens; KMS and HttpFS with
# Kerberos over HTTPS; delegation tokens for MapReduce, WebHDFS and the
# timeline server. All principals map to the user running the daemons, as
# a single-user test cluster.

ARCH_SCENARIOS='^(00|10|20|30|50|70)-'
ARCH_SERVICES=(kdc)
SECURE=true

KDC_DIR="${RUN}/kdc"
KEYTAB="${KDC_DIR}/hadoop.keytab"
REALM=EXAMPLE.COM
export KRB5_CONFIG="${KDC_DIR}/krb5.conf"
export KRB5CCNAME="FILE:${KDC_DIR}/ccache"
# Every Hadoop JVM, client or daemon, finds the KDC through this.
export HADOOP_OPTS="-Djava.security.krb5.conf=${KRB5_CONFIG} ${HADOOP_OPTS:-}"
export PROBE_CA="${RUN}/tls/ca.pem"
export PROBE_SPNEGO=true

NN_URL="https://${HOST}:${P_NN_HTTPS}"
DN_URL="https://${HOST}:${P_DN_HTTPS}"
RM_URL="https://${HOST}:${P_RM_HTTPS}"
NM_URL="https://${HOST}:${P_NM_HTTPS}"
AHS_URL="https://${HOST}:${P_AHS_HTTPS}"
JHS_URL="https://${HOST}:${P_JHS_HTTPS}"
KMS_URL="https://${HOST}:${P_KMS}"
HTTPFS_URL="https://${HOST}:${P_HTTPFS}"
PROXY_URL="${RM_URL}"
WEBHDFS_FS="swebhdfs://${HOST}:${P_NN_HTTPS}"
HTTPFS_FS="swebhdfs://${HOST}:${P_HTTPFS}"
KMS_PROVIDER="kms://https@${HOST}:${P_KMS}/kms"

C="${HADOOP_CONF_DIR}"
INSTANCES=(
  "namenode hdfs namenode HDFS_NAMENODE ${NN_URL}/jmx ${C}"
  "datanode hdfs datanode HDFS_DATANODE ${DN_URL}/jmx ${C}"
  "kms hadoop kms HADOOP_KMS ${KMS_URL}/jmx ${C}"
  "httpfs hdfs httpfs HDFS_HTTPFS ${HTTPFS_URL}/jmx ${C}"
  "resourcemanager yarn resourcemanager YARN_RESOURCEMANAGER ${RM_URL}/jmx ${C}"
  "nodemanager yarn nodemanager YARN_NODEMANAGER ${NM_URL}/jmx ${C}"
  "timelineserver yarn timelineserver YARN_TIMELINESERVER ${AHS_URL}/jmx ${C}"
  "historyserver mapred historyserver MAPRED_HISTORYSERVER ${JHS_URL}/jmx ${C}"
)

arch_conf() {
  local d="${DATA}" kt="${KEYTAB}" r="@${REALM}"
  # Every principal of the realm is the user running the cluster.
  local rules="RULE:[1:\$1@\$0](.*@EXAMPLE\\.COM)s/.*/${USER_NAME}/ RULE:[2:\$1@\$0](.*@EXAMPLE\\.COM)s/.*/${USER_NAME}/ DEFAULT"
  head -c 64 /dev/urandom | base64 > "${KDC_DIR}/http-signature-secret"
  make_tls
  base_core "fs.defaultFS=${FS}" \
    "hadoop.security.key.provider.path=${KMS_PROVIDER}" \
    "hadoop.security.authentication=kerberos" \
    "hadoop.security.authorization=true" \
    "hadoop.security.auth_to_local=${rules}" \
    "hadoop.rpc.protection=authentication" \
    "hadoop.http.filter.initializers=org.apache.hadoop.security.AuthenticationFilterInitializer" \
    "hadoop.http.authentication.type=kerberos" \
    "hadoop.http.authentication.simple.anonymous.allowed=false" \
    "hadoop.http.authentication.kerberos.principal=HTTP/${HOST}${r}" \
    "hadoop.http.authentication.kerberos.keytab=${kt}" \
    "hadoop.http.authentication.signature.secret.file=${KDC_DIR}/http-signature-secret"
  base_hdfs \
    "dfs.namenode.name.dir=${d}/nn" \
    "dfs.namenode.rpc-address=${HOST}:${P_NN_RPC}" \
    "dfs.http.policy=HTTPS_ONLY" \
    "dfs.namenode.https-address=${HOST}:${P_NN_HTTPS}" \
    "dfs.datanode.https.address=${HOST}:${P_DN_HTTPS}" \
    "dfs.block.access.token.enable=true" \
    "dfs.data.transfer.protection=authentication" \
    "dfs.namenode.kerberos.principal=nn/_HOST${r}" \
    "dfs.namenode.keytab.file=${kt}" \
    "dfs.namenode.kerberos.internal.spnego.principal=HTTP/_HOST${r}" \
    "dfs.datanode.kerberos.principal=dn/_HOST${r}" \
    "dfs.datanode.keytab.file=${kt}" \
    "dfs.web.authentication.kerberos.principal=HTTP/_HOST${r}" \
    "dfs.web.authentication.kerberos.keytab=${kt}" \
    "dfs.cluster.administrators=${USER_NAME}"
  # Log aggregation under Kerberos opens files with SecureIOUtils, which needs
  # the native libhadoop; without it the node manager exits ("Secure IO is
  # not possible without native code extensions"). CI builds the
  # distributions with -Pnative, but a local build.sh does not by default
  # (BUILD_NATIVE), so it stays off and both kinds of runs compare the same.
  # The node manager logs in as nm/<canonical local hostname> when its
  # principal has _HOST (SecurityUtil.login without a bind address); on CI
  # runners that is an FQDN the keytab has no entry for, so name the host.
  # shellcheck disable=SC2046
  base_yarn $(yarn_rm_addresses "" 0) \
    "yarn.log-aggregation-enable=false" \
    "yarn.resourcemanager.hostname=${HOST}" \
    "yarn.http.policy=HTTPS_ONLY" \
    "yarn.nodemanager.webapp.https.address=${HOST}:${P_NM_HTTPS}" \
    "yarn.resourcemanager.principal=rm/_HOST${r}" \
    "yarn.resourcemanager.keytab=${kt}" \
    "yarn.nodemanager.principal=nm/${HOST}${r}" \
    "yarn.nodemanager.keytab=${kt}" \
    "yarn.resourcemanager.webapp.spnego-principal=HTTP/_HOST${r}" \
    "yarn.resourcemanager.webapp.spnego-keytab-file=${kt}" \
    "yarn.nodemanager.webapp.spnego-principal=HTTP/_HOST${r}" \
    "yarn.nodemanager.webapp.spnego-keytab-file=${kt}" \
    "yarn.timeline-service.enabled=true" \
    "yarn.system-metrics-publisher.enabled=true" \
    "yarn.timeline-service.hostname=${HOST}" \
    "yarn.timeline-service.address=${HOST}:${P_AHS_RPC}" \
    "yarn.timeline-service.webapp.https.address=${HOST}:${P_AHS_HTTPS}" \
    "yarn.timeline-service.leveldb-timeline-store.path=${d}/timeline" \
    "yarn.timeline-service.leveldb-state-store.path=${d}/timeline-state" \
    "yarn.timeline-service.generic-application-history.enabled=true" \
    "yarn.timeline-service.principal=tl/_HOST${r}" \
    "yarn.timeline-service.keytab=${kt}" \
    "yarn.timeline-service.http-authentication.type=kerberos" \
    "yarn.timeline-service.http-authentication.kerberos.principal=HTTP/_HOST${r}" \
    "yarn.timeline-service.http-authentication.kerberos.keytab=${kt}" \
    "yarn.log.server.url=${JHS_URL}/jobhistory/logs"
  base_mapred \
    "mapreduce.jobhistory.principal=jhs/_HOST${r}" \
    "mapreduce.jobhistory.keytab=${kt}" \
    "mapreduce.jobhistory.http.policy=HTTPS_ONLY" \
    "mapreduce.jobhistory.webapp.https.address=${HOST}:${P_JHS_HTTPS}" \
    "mapreduce.jobhistory.webapp.spnego-principal=HTTP/_HOST${r}" \
    "mapreduce.jobhistory.webapp.spnego-keytab-file=${kt}" \
    "yarn.app.mapreduce.am.command-opts=-Xmx384m -Djava.security.krb5.conf=${KRB5_CONFIG}" \
    "mapreduce.map.java.opts=-Xmx200m -Djava.security.krb5.conf=${KRB5_CONFIG}" \
    "mapreduce.reduce.java.opts=-Xmx200m -Djava.security.krb5.conf=${KRB5_CONFIG}"
  site "${HADOOP_CONF_DIR}/kms-site.xml" \
    "hadoop.kms.key.provider.uri=jceks://file@${d}/kms.keystore" \
    "hadoop.kms.http.port=${P_KMS}" \
    "hadoop.kms.ssl.enabled=true" \
    "hadoop.kms.authentication.type=kerberos" \
    "hadoop.kms.authentication.kerberos.principal=HTTP/${HOST}${r}" \
    "hadoop.kms.authentication.kerberos.keytab=${kt}" \
    "hadoop.kms.authentication.kerberos.name.rules=${rules}" \
    "hadoop.kms.proxyuser.${USER_NAME}.users=*" \
    "hadoop.kms.proxyuser.${USER_NAME}.groups=*" \
    "hadoop.kms.proxyuser.${USER_NAME}.hosts=*" \
    "hadoop.kms.http.administrators=${USER_NAME}"
  site "${HADOOP_CONF_DIR}/httpfs-site.xml" \
    "httpfs.http.port=${P_HTTPFS}" \
    "httpfs.ssl.enabled=true" \
    "httpfs.authentication.type=kerberos" \
    "httpfs.authentication.kerberos.principal=HTTP/${HOST}${r}" \
    "httpfs.authentication.kerberos.keytab=${kt}" \
    "httpfs.authentication.kerberos.name.rules=${rules}" \
    "httpfs.hadoop.authentication.type=kerberos" \
    "httpfs.hadoop.authentication.kerberos.principal=httpfs/${HOST}${r}" \
    "httpfs.hadoop.authentication.kerberos.keytab=${kt}" \
    "httpfs.proxyuser.${USER_NAME}.hosts=*" \
    "httpfs.proxyuser.${USER_NAME}.groups=*" \
    "httpfs.http.administrators=${USER_NAME}"
}

arch_prepare() {
  log "formatting the namenode"
  hdfs namenode -format -force -nonInteractive > "${RES}/namenode-format.log" 2>&1 \
    || die "namenode format failed; see ${RES}/namenode-format.log"
}
