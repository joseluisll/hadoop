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

# Mixed architecture: MapReduce with RBF as the default file system over an
# HA and a non-HA namespace, the two routers as one HA nameservice for
# clients (one is killed and clients carry on through the other), and both
# routers' web servers.

CLUSTER="${E2E_DIR}/cluster.sh"
EXAMPLES=$(ls "${DIST}"/share/hadoop/mapreduce/hadoop-mapreduce-examples-*.jar | head -1)
LOCAL="${RUN}/tmp/mixed"
mkdir -p "${LOCAL}"
D=/data2/mixed
U="user.name=${USER_NAME}"
for i in $(seq 1 300); do echo "router based federation ${i} high availability $((i % 5))"; done \
  > "${LOCAL}/words.txt"

COMPONENT=mixed-mapreduce
cli default-fs --expect-regex '^(\S+)' -- hdfs getconf -confKey fs.defaultFS
hadoop fs -mkdir -p "${D}/in"
cli put-input -- hadoop fs -put -f "${LOCAL}/words.txt" "${D}/in/"
cli pi --merge-stderr --expect-regex 'Estimated value of Pi is (\S+)' -- yarn jar "${EXAMPLES}" pi 2 500
# Input and output on ns2 (non-HA), staging on ns1 (HA), all through RBF.
cli wordcount -- yarn jar "${EXAMPLES}" wordcount "${D}/in" "${D}/wc-out"
cli wordcount-output --shape sha256 -- hadoop fs -cat "${D}/wc-out/part-r-00000"
cli output-in-ns2 -- hadoop fs -fs "${FED_FS[1]}" -test -e /data2/mixed/wc-out/_SUCCESS

COMPONENT=mixed-routers
for i in 0 1; do
  u="http://${HOST}:${ROUTER_HTTP[i]}"
  http "${ROUTERS[i]}-federationhealth" "${u}/federationhealth.html"
  http "${ROUTERS[i]}-state" "${u}/jmx?qry=Hadoop:service=Router,name=FederationState" \
    --expect-regex '"NumNamenodes" : [1-9]'
  http "${ROUTERS[i]}-webhdfs" "${u}/webhdfs/v1/data2/mixed/in?op=LISTSTATUS&${U}" \
    --expect-regex '"FileStatuses"'
done
# Both routers see the same mount table (shared state store).
cli mounts-router1 --shape lines -- sh -c "hdfs dfsrouteradmin -ls | awk 'NR>1 {print \$1, \$2, \$3}' | sort"
cli mounts-router2 --shape lines -- sh -c "hdfs dfsrouteradmin -Ddfs.federation.router.admin-address=${HOST}:${ROUTER_ADMIN[1]} -ls | awk 'NR>1 {print \$1, \$2, \$3}' | sort"

"${CLUSTER}" "${SIDE}" "${ARCH}" kill router1 >/dev/null 2>&1
cli read-with-router1-down --shape sha256 -- hadoop fs -cat "${D}/in/words.txt"
cli write-with-router1-down -- hadoop fs -put -f "${LOCAL}/words.txt" "${D}/after-router-kill.txt"
cli job-with-router1-down --merge-stderr --expect-regex 'Estimated value of Pi is (\S+)' -- \
  yarn jar "${EXAMPLES}" pi 1 200
"${CLUSTER}" "${SIDE}" "${ARCH}" restart router1 >/dev/null 2>&1
http router1-back "http://${HOST}:${ROUTER_HTTP[0]}/jmx?qry=Hadoop:service=Router,name=Router" \
  --expect-status 200
same_checksum data-consistent "${D}/in/words.txt" "${D}/after-router-kill.txt"
