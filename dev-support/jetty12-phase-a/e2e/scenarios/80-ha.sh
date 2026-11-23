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

# High availability (architectures ha and mixed): how active and standby
# web servers answer (IsActiveServlet, StandbyException over WebHDFS, the
# RM's redirect to the active RM), and failover: the active namenode and
# resource manager are killed, the standby takes over through ZooKeeper,
# data and applications survive, the killed daemon comes back as standby,
# and a graceful failover returns to the first one.

CLUSTER="${E2E_DIR}/cluster.sh"
NN_URLS=("http://${HOST}:${HA_NN_HTTP[0]}" "http://${HOST}:${HA_NN_HTTP[1]}")
RM_URLS=("${RM_URL}" "${RM2_URL}")
DSHELL_JAR=$(ls "${DIST}"/share/hadoop/yarn/hadoop-yarn-applications-distributedshell-*.jar | head -1)
D=/e2e/ha
U="user.name=${USER_NAME}"

nn_state() {
  hdfs haadmin -ns "${HA_NS}" -getServiceState "$1" 2>/dev/null | tr -d '[:space:]'
}

# wait_nn_active <nn id> <seconds>
wait_nn_active() {
  local deadline=$((SECONDS + $2))
  while (( SECONDS < deadline )); do
    [[ "$(nn_state "$1")" == active ]] && return 0
    sleep 2
  done
  return 1
}

rm_state() {
  yarn rmadmin -getServiceState "$1" 2>/dev/null | tr -d '[:space:]'
}

wait_rm_active() {
  local deadline=$((SECONDS + $2))
  while (( SECONDS < deadline )); do
    [[ "$(rm_state "$1")" == active ]] && return 0
    sleep 2
  done
  return 1
}

dshell() {
  yarn jar "${DSHELL_JAR}" -jar "${DSHELL_JAR}" -shell_command echo -shell_args "$1" \
    -num_containers 1 -container_memory 256 -master_memory 256 -appname "$1"
}

# ------------------------------------------------------------- namenodes
COMPONENT=ha-hdfs
cli states-initial --expect-regex '(?m)^\S+:\d+\s+(active)' -- \
  hdfs haadmin -ns "${HA_NS}" -getAllServiceState
cli nn1-state --expect-regex '^(active)' -- hdfs haadmin -ns "${HA_NS}" -getServiceState nn1
cli nn2-state --expect-regex '^(standby)' -- hdfs haadmin -ns "${HA_NS}" -getServiceState nn2
cli check-health -- hdfs haadmin -ns "${HA_NS}" -checkHealth nn1
http active-isactive "${NN_URLS[0]}/isActive" --expect-status 200
http standby-isactive "${NN_URLS[1]}/isActive" --expect-status 405
http active-status "${NN_URLS[0]}/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus" \
  --expect-regex '"State" : "active"'
http standby-status "${NN_URLS[1]}/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus" \
  --expect-regex '"State" : "standby"'
http standby-webhdfs "${NN_URLS[1]}/webhdfs/v1/?op=LISTSTATUS&${U}" --expect-status any \
  --expect-regex 'StandbyException'
http standby-dfshealth "${NN_URLS[1]}/dfshealth.html"
http standby-fsstate "${NN_URLS[1]}/jmx?qry=Hadoop:service=NameNode,name=FSNamesystemState"
seq 1 10000 > "${RUN}/tmp/ha-before.txt"
hadoop fs -mkdir -p "${D}"
cli put-before -- hadoop fs -put -f "${RUN}/tmp/ha-before.txt" "${D}/before.txt"
cli webhdfs-logical --shape sha256 -- hadoop fs -cat "webhdfs://${HA_NS}${D}/before.txt"

"${CLUSTER}" "${SIDE}" "${ARCH}" kill nn1 >/dev/null 2>&1
start=${SECONDS}
if wait_nn_active nn2 90; then
  check failover-nn2-active true "took $((SECONDS - start))s"
else
  check failover-nn2-active false "nn2 is $(nn_state nn2) after 90s"
fi
cli read-after-failover --shape sha256 -- hadoop fs -cat "${D}/before.txt"
cli put-after-failover -- hadoop fs -put -f "${RUN}/tmp/ha-before.txt" "${D}/after.txt"
http new-active-isactive "${NN_URLS[1]}/isActive" --expect-status 200
http killed-nn-down "${NN_URLS[0]}/isActive" --expect-status any --allow-error --shape none
"${CLUSTER}" "${SIDE}" "${ARCH}" restart nn1 >/dev/null 2>&1
for _ in $(seq 1 30); do [[ "$(nn_state nn1)" == standby ]] && break; sleep 2; done
cli restarted-nn1-state --expect-regex '^(standby)' -- hdfs haadmin -ns "${HA_NS}" -getServiceState nn1
http restarted-isactive "${NN_URLS[0]}/isActive" --expect-status 405
cli graceful-failover -- hdfs haadmin -ns "${HA_NS}" -failover nn2 nn1
wait_nn_active nn1 60 || true
cli nn1-active-again --expect-regex '^(active)' -- hdfs haadmin -ns "${HA_NS}" -getServiceState nn1
same_checksum data-survived "${D}/before.txt" "${D}/after.txt"

# ---------------------------------------------------- resource managers
COMPONENT=ha-yarn
cli states-initial --expect-regex '(?m)^\S+:\d+\s+(active)' -- yarn rmadmin -getAllServiceState
cli rm1-state --expect-regex '^(active)' -- yarn rmadmin -getServiceState rm1
cli rm2-state --expect-regex '^(standby)' -- yarn rmadmin -getServiceState rm2
http active-isactive "${RM_URLS[0]}/isActive" --expect-status 200
http standby-isactive "${RM_URLS[1]}/isActive" --expect-status 405
http standby-info "${RM_URLS[1]}/ws/v1/cluster/info" --expect-regex '"haState":"STANDBY"'
http active-info "${RM_URLS[0]}/ws/v1/cluster/info" --expect-regex '"haState":"ACTIVE"'
# A standby RM sends web requests to the active one.
http standby-redirect-ui "${RM_URLS[1]}/cluster" --expect-status 307
http standby-redirect-rest "${RM_URLS[1]}/ws/v1/cluster/apps" --expect-status 307
http standby-about "${RM_URLS[1]}/cluster/cluster" --expect-status any
cli dshell-before --merge-stderr --expect-regex '(Application completed successfully)' -- dshell jetty12-ha-before
APP_BEFORE=$(latest_app '^jetty12-ha-before$')

"${CLUSTER}" "${SIDE}" "${ARCH}" kill rm1 >/dev/null 2>&1
start=${SECONDS}
if wait_rm_active rm2 120; then
  check failover-rm2-active true "took $((SECONDS - start))s"
else
  check failover-rm2-active false "rm2 is $(rm_state rm2) after 120s"
fi
RM_URL="${RM_URLS[1]}"
for _ in $(seq 1 30); do
  rest "${RM_URL}/ws/v1/cluster/nodes" | grep -q '"state":"RUNNING"' && break
  sleep 2
done
http new-active-info "${RM_URL}/ws/v1/cluster/info" --expect-regex '"haState":"ACTIVE"'
http recovered-app "${RM_URL}/ws/v1/cluster/apps/${APP_BEFORE}" --expect-regex '"finalStatus":"SUCCEEDED"'
http node-reregistered "${RM_URL}/ws/v1/cluster/nodes" --expect-regex '"state":"RUNNING"'
cli dshell-after --merge-stderr --expect-regex '(Application completed successfully)' -- dshell jetty12-ha-after
cli app-list --shape none -- yarn application -list -appStates FINISHED
"${CLUSTER}" "${SIDE}" "${ARCH}" restart rm1 >/dev/null 2>&1
for _ in $(seq 1 30); do [[ "$(rm_state rm1)" == standby ]] && break; sleep 2; done
cli restarted-rm1-state --expect-regex '^(standby)' -- yarn rmadmin -getServiceState rm1
http restarted-redirect "${RM_URLS[0]}/cluster" --expect-status 307
