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

# Federation (architectures federated and mixed): the namespaces behind it,
# the RBF router mount table over them (single and multi-destination
# mounts, quotas, WebHDFS, the federation UI and JMX), ViewFS where the
# architecture configures it, and YARN federation through the YARN router
# (aggregated REST, client RPC, an application placed on a sub-cluster,
# the global policy generator) where it runs.

D=/e2e/fed
LOCAL="${RUN}/tmp/fed"
mkdir -p "${LOCAL}"
seq 1 4000 > "${LOCAL}/a.txt"
seq 4000 8000 > "${LOCAL}/b.txt"
U="user.name=${USER_NAME}"

# ---------------------------------------------------- the namespaces
COMPONENT=fed-hdfs
for i in 0 1; do
  ns=${FED_NS[i]} fs=${FED_FS[i]}
  cli "${ns}-report" --expect-regex 'Live datanodes \((\d+)\)' -- hdfs dfsadmin -fs "${fs}" -report
  cli "${ns}-mkdir" -- hadoop fs -fs "${fs}" -mkdir -p "/data$((i + 1))/fed"
  cli "${ns}-put" -- hadoop fs -fs "${fs}" -put -f "${LOCAL}/a.txt" "/data$((i + 1))/fed/a.txt"
  cli "${ns}-cat" --shape sha256 -- hadoop fs -fs "${fs}" -cat "/data$((i + 1))/fed/a.txt"
done
# Separate namespaces: a file written to one is not in the other.
cli ns2-does-not-see-ns1 --expect-rc 1 -- hadoop fs -fs "${FED_FS[1]}" -test -e /data1/fed/a.txt
# One datanode, one block pool per namespace.
cli block-pools --expect-regex '^\s*(\d+)' -- sh -c "ls -d ${RUN}/data/dn/current/BP-* | wc -l"
cli cross-ns-distcp -- hadoop distcp "${FED_FS[0]}/data1/fed" "${FED_FS[1]}/data2/copied"
same_checksum cross-ns-copy "${FED_FS[0]}/data1/fed/a.txt" "${FED_FS[1]}/data2/copied/a.txt"

# ------------------------------------------------------------ the router
COMPONENT=fed-rbf
cli mount-ns1 -- hdfs dfsrouteradmin -add /r1 ns1 /data1/fed
cli mount-ns2 -- hdfs dfsrouteradmin -add /r2 ns2 /data2/fed
cli mount-multi -- hdfs dfsrouteradmin -add /rboth ns1,ns2 /data1/multi -order HASH_ALL
cli mount-refresh -- hdfs dfsrouteradmin -refresh
# With several routers, every one of them must see the new mounts.
for port in "${ROUTER_ADMIN[@]:1}"; do
  hdfs dfsrouteradmin -Ddfs.federation.router.admin-address="${HOST}:${port}" -refresh >/dev/null 2>&1 || true
done
cli mount-list --shape lines -- sh -c "hdfs dfsrouteradmin -ls | awk 'NR>1 {print \$1, \$2, \$3}' | sort"
cli quota -- hdfs dfsrouteradmin -setQuota /r2 -nsQuota 1000
cli safemode --expect-regex 'Safe Mode: (\w+)' -- hdfs dfsrouteradmin -safemode get
cli ls-r1 --shape lines -- sh -c "hadoop fs -ls ${ROUTER_FS}/r1 | awk '{print \$1, \$5, \$8}'"
cli cat-r2 --shape sha256 -- hadoop fs -cat "${ROUTER_FS}/r2/a.txt"
cli put-r2 -- hadoop fs -put -f "${LOCAL}/b.txt" "${ROUTER_FS}/r2/b.txt"
same_checksum put-r2-landed-in-ns2 "${ROUTER_FS}/r2/b.txt" "${FED_FS[1]}/data2/fed/b.txt"
cli mkdir-multi -- hadoop fs -mkdir -p "${ROUTER_FS}/rboth/sub"
cli put-multi -- hadoop fs -put -f "${LOCAL}/a.txt" "${ROUTER_FS}/rboth/sub/a.txt"
cli cat-multi --shape sha256 -- hadoop fs -cat "${ROUTER_FS}/rboth/sub/a.txt"
cli count-r2 --shape lines -- hadoop fs -count -q "${ROUTER_FS}/r2"
cli rename-across-mounts --expect-rc 1 -- hadoop fs -mv "${ROUTER_FS}/r1/a.txt" "${ROUTER_FS}/r2/moved.txt"
http webhdfs-liststatus "${ROUTER_URL}/webhdfs/v1/r1?op=LISTSTATUS&${U}" --expect-regex '"FileStatuses"'
http webhdfs-open-r2 "${ROUTER_URL}/webhdfs/v1/r2/b.txt?op=OPEN&${U}" --follow --shape sha256
http webhdfs-mounts "${ROUTER_URL}/webhdfs/v1/?op=LISTSTATUS&${U}"
http federationhealth "${ROUTER_URL}/federationhealth.html"
http federation-state "${ROUTER_URL}/jmx?qry=Hadoop:service=Router,name=FederationState" \
  --expect-regex '"NumNamenodes" : [1-9]'
http router-status "${ROUTER_URL}/jmx?qry=Hadoop:service=Router,name=Router" --expect-status any

# --------------------------------------------------------------- ViewFS
if [[ -n "${VIEWFS:-}" ]]; then
  COMPONENT=fed-viewfs
  cli ls-root --shape lines -- sh -c "hadoop fs -ls ${VIEWFS}/ | awk '{print \$1, \$8}'"
  cli put-ns2 -- hadoop fs -put -f "${LOCAL}/b.txt" "${VIEWFS}/ns2/viewfs-b.txt"
  same_checksum put-ns2-landed "${VIEWFS}/ns2/viewfs-b.txt" "${FED_FS[1]}/fed2/viewfs-b.txt"
  cli mv-within-mount -- hadoop fs -mv "${VIEWFS}/ns2/viewfs-b.txt" "${VIEWFS}/ns2/viewfs-moved.txt"
  cli mv-across-mounts --expect-rc 1 -- hadoop fs -mv "${VIEWFS}/ns2/viewfs-moved.txt" "${VIEWFS}/ns1/x.txt"
  cli df --shape none -- hadoop fs -df "${VIEWFS}/"
fi

# ------------------------------------------------------- YARN federation
if daemon_up yrouter; then
  COMPONENT=fed-yarn
  DSHELL_JAR=$(ls "${DIST}"/share/hadoop/yarn/hadoop-yarn-applications-distributedshell-*.jar | head -1)
  Y="${YROUTER_URL}/ws/v1/cluster"
  http router-info "${Y}/info" --expect-status 200
  http router-metrics "${Y}/metrics" --expect-regex '"activeNodes":2'
  http router-nodes "${Y}/nodes" --expect-regex '"nodes"'
  http router-scheduler "${Y}/scheduler" --expect-status any
  http router-apps "${Y}/apps" --expect-status 200
  http router-ui "${YROUTER_URL}/cluster" --expect-status any
  http router-ui-federation "${YROUTER_URL}/cluster/federation" --expect-status any
  http router-ui-nodes "${YROUTER_URL}/cluster/nodes" --expect-status any
  http rm-sc1-info "${RM_URL}/ws/v1/cluster/info" --expect-regex '"clusterInfo"'
  http rm-sc2-info "${RM2_URL}/ws/v1/cluster/info" --expect-regex '"clusterInfo"'
  cli router-node-list --expect-regex 'Total Nodes:(\d+)' -- \
    yarn node -Dyarn.resourcemanager.address="${YROUTER_RPC}" -list -all
  # The distributed shell client takes no -D options: a client configuration
  # whose RM address is the YARN router.
  cli dshell-via-router --merge-stderr --expect-regex '(Application completed successfully)' -- \
    env HADOOP_CONF_DIR="${RUN}/conf-viarouter" \
    yarn jar "${DSHELL_JAR}" -jar "${DSHELL_JAR}" -shell_command echo \
    -shell_args jetty12-federated -num_containers 1 -container_memory 256 \
    -master_memory 256 -appname jetty12-federated
  APP=$(rest "${Y}/apps" | python3 -c '
import json, sys
apps = ((json.load(sys.stdin).get("apps") or {}).get("app")) or []
apps = [a for a in apps if a.get("name") == "jetty12-federated"]
print(apps[0]["id"] if apps else "")' 2>/dev/null || true)
  http router-app "${Y}/apps/${APP}" --expect-regex '"finalStatus":"SUCCEEDED"'
  http router-app-state "${Y}/apps/${APP}/state" --expect-status any
  cli router-app-status --expect-regex 'Final-State : (\w+)' -- \
    yarn application -Dyarn.resourcemanager.address="${YROUTER_RPC}" -status "${APP}"
  # It ran on exactly one of the sub-clusters.
  on1=$(rest "${RM_URL}/ws/v1/cluster/apps/${APP}" | grep -c '"id"' || true)
  on2=$(rest "${RM2_URL}/ws/v1/cluster/apps/${APP}" | grep -c '"id"' || true)
  check app-on-one-subcluster "$([[ $((on1 + on2)) -eq 1 ]] && echo true || echo false)" "sc1 ${on1}, sc2 ${on2}"
  if daemon_up gpg; then
    http gpg-ui "${GPG_URL}/gpg" --expect-status any
    http gpg-overview "${GPG_URL}/gpg/overview" --expect-status any
    http gpg-policies "${GPG_URL}/gpg/policies" --expect-status any
  fi
fi
