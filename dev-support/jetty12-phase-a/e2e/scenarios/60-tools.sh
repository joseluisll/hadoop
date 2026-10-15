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

# hadoop-tools: DistCp (over HDFS and WebHDFS), archives, streaming, rumen,
# gridmix, the scheduler load simulator with its Jetty web UI (HADOOP-20016
# declares jetty-http in it), the resource estimator REST service
# (HADOOP-20014 changes its test container), and loading of the cloud
# connector file systems.

TOOLS="${DIST}/share/hadoop/tools"
LOCAL="${RUN}/tmp/tools"
mkdir -p "${LOCAL}"
D=/e2e/tools
seq 1 3000 > "${LOCAL}/a.txt"
seq 3000 9000 > "${LOCAL}/b.txt"
hadoop fs -mkdir -p "${D}/src/sub"
hadoop fs -put -f "${LOCAL}/a.txt" "${D}/src/"
hadoop fs -put -f "${LOCAL}/b.txt" "${D}/src/sub/"

COMPONENT=tools-distcp
cli hdfs-to-hdfs -- hadoop distcp "${D}/src" "${D}/copy1"
same_checksum hdfs-to-hdfs-a "${D}/src/a.txt" "${D}/copy1/a.txt"
same_checksum hdfs-to-hdfs-b "${D}/src/sub/b.txt" "${D}/copy1/sub/b.txt"
cli webhdfs-to-hdfs -- hadoop distcp "${WEBHDFS_FS}${D}/src" "${D}/copy2"
same_checksum webhdfs-to-hdfs-content "${D}/src/sub/b.txt" "${D}/copy2/sub/b.txt"
cli httpfs-to-hdfs -- hadoop distcp "${HTTPFS_FS}${D}/src" "${D}/copy3"
same_checksum httpfs-to-hdfs-content "${D}/src/a.txt" "${D}/copy3/a.txt"
cli update -- hadoop distcp -update -delete "${D}/src" "${D}/copy1"
cli listing --shape lines -- sh -c "hadoop fs -ls -R ${D}/copy1 | awk '{print \$1, \$5, \$8}'"

COMPONENT=tools-archives
cli create -- hadoop archive -archiveName e2e.har -p "${D}" src "${D}/har"
cli ls --shape lines -- sh -c "hadoop fs -ls -R har://${D}/har/e2e.har | awk '{print \$1, \$5, \$8}'"
same_checksum har-content "${D}/src/sub/b.txt" "har://${D}/har/e2e.har/src/sub/b.txt"

COMPONENT=tools-streaming
cli job -- mapred streaming -input "${D}/src/a.txt" -output "${D}/streaming-out" \
  -mapper 'awk /7/' -reducer 'wc -l' -numReduceTasks 1
cli output --expect-regex '^\s*(\d+)' -- hadoop fs -cat "${D}/streaming-out/part-00000"

COMPONENT=tools-rumen
DONE_DIR=$(hdfs getconf -confKey mapreduce.jobhistory.done-dir 2>/dev/null)
DONE_DIR=${DONE_DIR:-/tmp/hadoop-yarn/staging/history/done}
# The history server moves finished jobs to the done directory every three
# minutes; when this scenario runs alone, wait for the streaming job above.
for _ in $(seq 1 60); do
  hadoop fs -ls -R "${DONE_DIR}" 2>/dev/null | grep -q '\.jhist$' && break
  sleep 5
done
cli tracebuilder -- hadoop rumentrace -recursive \
  "file://${LOCAL}/trace.json" "file://${LOCAL}/topology.json" "${FS}${DONE_DIR}"
check trace-written "$([[ -s "${LOCAL}/trace.json" ]] && echo true || echo false)"
cli folder --expect-rc 0,1 -- hadoop rumenfolder \
  -input-cycle 1m -output-duration 10m "file://${LOCAL}/trace.json" "file://${LOCAL}/folded.json"

if [[ "${E2E_GRIDMIX:-true}" == true && -s "${LOCAL}/trace.json" ]]; then
  COMPONENT=tools-gridmix
  # Gridmix wants input even for sleep jobs: -generate a small one, and
  # accept its small files (gridmix.min.file.size defaults to 128 MB).
  cli sleep-jobs --merge-stderr -- timeout 900 hadoop gridmix \
    -Dgridmix.job.type=SLEEPJOB -Dgridmix.job-submission.policy=SERIAL \
    -Dgridmix.sleep.max-map-time=200 -Dgridmix.sleep.max-reduce-time=200 \
    -Dgridmix.output.directory="${D}/gridmix-out" -Dgridmix.min.file.size=1048576 \
    -generate 10m "${D}/gridmix" "file://${LOCAL}/trace.json"
fi

# Scheduler load simulator: an in-process RM driven by a trace, with its own
# Jetty web UI. It gets its own configuration and ports.
COMPONENT=tools-sls
SLS_CONF="${RUN}/conf-sls"
rm -rf "${SLS_CONF}"
cp -r "${DIST}/etc/hadoop" "${SLS_CONF}"
cp "${TOOLS}"/sls/sample-conf/* "${SLS_CONF}/"
# SLSRunner builds the simulated RM's configuration from sls-runner.xml
# alone (new Configuration(false)), so yarn-site.xml is not read: the
# scheduler and the RM's ports go there.
for f in yarn-site.xml sls-runner.xml; do
  python3 -I "${E2E_DIR}/lib/confset.py" "${SLS_CONF}/${f}" \
    yarn.resourcemanager.scheduler.class=org.apache.hadoop.yarn.server.resourcemanager.scheduler.capacity.CapacityScheduler \
    yarn.resourcemanager.address=localhost:18032 \
    yarn.resourcemanager.scheduler.address=localhost:18030 \
    yarn.resourcemanager.resource-tracker.address=localhost:18031 \
    yarn.resourcemanager.admin.address=localhost:18033 \
    yarn.resourcemanager.webapp.address=localhost:18088 \
    yarn.timeline-service.enabled=false
done
SLS_OUT="${LOCAL}/sls-out"
rm -rf "${SLS_OUT}"
( cd "${TOOLS}/sls" && HADOOP_CONF_DIR="${SLS_CONF}" timeout 900 bin/slsrun.sh \
    --tracetype=RUMEN --tracelocation="${TOOLS}/sls/sample-data/2jobs2min-rumen-jh.json" \
    --output-dir="${SLS_OUT}" --print-simulation ) > "${RES}/sls.log" 2>&1 &
SLS_PID=$!
if wait_http "http://${HOST}:${P_SLS_HTTP}/simulate" 180; then
  sleep 10
  http simulate "http://${HOST}:${P_SLS_HTTP}/simulate" --expect-status 200
  http track "http://${HOST}:${P_SLS_HTTP}/track" --expect-status 200
  http realtime-track "http://${HOST}:${P_SLS_HTTP}/simulateMetrics" --expect-status any
  http static-js "http://${HOST}:${P_SLS_HTTP}/js/showchart.js" --expect-status any --shape sha256
  http not-found "http://${HOST}:${P_SLS_HTTP}/no/such/page" --expect-status any
  http rm-webapp "http://${HOST}:18088/ws/v1/cluster/info?user.name=${USER_NAME}" --expect-status 200
else
  check web-up false "SLS web UI did not come up; see sls.log"
fi
sls_rc=0
wait "${SLS_PID}" || sls_rc=$?
check simulation-finished "$([[ ${sls_rc} -eq 0 ]] && echo true || echo false)" "exit ${sls_rc}"
check metrics-written "$(ls "${SLS_OUT}"/*.csv >/dev/null 2>&1 && echo true || echo false)"

# Resource estimator REST service (HttpServer2 + Jersey).
COMPONENT=tools-resourceestimator
cp "${TOOLS}/resourceestimator/conf/"*.xml "${HADOOP_CONF_DIR}/"
cp "${TOOLS}/resourceestimator/data/resourceEstimatorService.txt" "${LOCAL}/"
EST="http://${HOST}:9998/resourceestimator"
( cd "${LOCAL}" && "${TOOLS}/resourceestimator/bin/estimator.sh" --daemon start resourceestimator ) \
  > "${RES}/estimator-start.log" 2>&1
if wait_http "http://${HOST}:9998/jmx" 90; then
  http translate "${EST}/translator/resourceEstimatorService.txt" --method POST --data '' \
    --expect-status 200,204
  http history "${EST}/skylinestore/history/tpch_q12/*" --expect-regex 'tpch_q12'
  http estimate "${EST}/estimator/tpch_q12" --expect-status 200
  http estimation "${EST}/skylinestore/estimation/tpch_q12" --expect-status 200
  http delete-history "${EST}/skylinestore/history/tpch_q12/tpch_q12_1" --method DELETE \
    --expect-status 200,204
  http err-unknown "${EST}/skylinestore/estimation/nosuchpipeline" --expect-status any
  http jmx "http://${HOST}:9998/jmx" --shape none --expect-status any
else
  check server-up false "resource estimator did not start; see estimator-start.log"
fi
"${TOOLS}/resourceestimator/bin/estimator.sh" --daemon stop resourceestimator >/dev/null 2>&1 || true

# Cloud connectors and other tools: no credentials here, so only check that
# their entry points load from the tools classpath the same way.
COMPONENT=tools-classload
for spec in \
  hadoop-aws:org.apache.hadoop.fs.s3a.S3AFileSystem \
  hadoop-azure:org.apache.hadoop.fs.azurebfs.AzureBlobFileSystem \
  hadoop-azure:org.apache.hadoop.fs.azure.NativeAzureFileSystem \
  hadoop-azure-datalake:org.apache.hadoop.fs.adl.AdlFileSystem \
  hadoop-aliyun:org.apache.hadoop.fs.aliyun.oss.AliyunOSSFileSystem \
  hadoop-cos:org.apache.hadoop.fs.cosn.CosNFileSystem \
  hadoop-huaweicloud:org.apache.hadoop.fs.obs.OBSFileSystem \
  hadoop-gcp:org.apache.hadoop.fs.gs.GoogleHadoopFileSystem \
  hadoop-tos:org.apache.hadoop.fs.tosfs.TosFileSystem \
  hadoop-kafka:org.apache.hadoop.metrics2.sink.KafkaSink \
  hadoop-dynamometer-infra:org.apache.hadoop.tools.dynamometer.Client \
  hadoop-dynamometer-workload:org.apache.hadoop.tools.dynamometer.workloadgenerator.WorkloadDriver \
  hadoop-fs2img:org.apache.hadoop.hdfs.server.namenode.FileSystemImage \
  hadoop-federation-balance:org.apache.hadoop.tools.fedbalance.FedBalance \
  hadoop-extras:org.apache.hadoop.tools.DistCh \
  hadoop-datajoin:org.apache.hadoop.contrib.utils.join.DataJoinJob; do
  tool=${spec%%:*} cls=${spec#*:}
  cli "load.${tool}.${cls##*.}" --expect-rc 0,3,4 \
    --expect-regex "(?m)^${cls//./\\.}: file:\\S*/([^/\\s]+)\\.jar\$|()(?:Class not found|Error while loading|Exception while loading)" \
    -- sh -c 'HADOOP_OPTIONAL_TOOLS="$0" hadoop org.apache.hadoop.util.FindClass load "$1" 2>&1' \
    "${tool}" "${cls}"
done
