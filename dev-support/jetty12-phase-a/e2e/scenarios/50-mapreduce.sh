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

# MapReduce: example jobs with deterministic results (shuffle through the
# node manager's ShuffleHandler, HADOOP-20016 declares jetty-http in it), the
# MR application master's web UI and REST API reached through the YARN web
# proxy while a job runs, and the job history server.

EXAMPLES=$(ls "${DIST}"/share/hadoop/mapreduce/hadoop-mapreduce-examples-*.jar | head -1)
JOBCLIENT_TESTS=$(ls "${DIST}"/share/hadoop/mapreduce/hadoop-mapreduce-client-jobclient-*-tests.jar | head -1)
LOCAL="${RUN}/tmp/mr"
mkdir -p "${LOCAL}"
D=/e2e/mr
U="user.name=${USER_NAME}"

# A fixed text, so word counts are the same on both sides.
for i in $(seq 1 200); do
  echo "the quick brown fox ${i} jumps over the lazy dog $((i % 7)) jetty twelve phase a"
done > "${LOCAL}/words.txt"
hadoop fs -mkdir -p "${D}/in"
hadoop fs -put -f "${LOCAL}/words.txt" "${D}/in/"

COMPONENT=mapreduce-jobs
cli pi --merge-stderr --expect-regex 'Estimated value of Pi is (\S+)' -- \
  yarn jar "${EXAMPLES}" pi 2 1000
PI_JOB=$(mapred job -list all 2>/dev/null | awk '/^ *job_/ {print $1}' | sort | tail -1)
cli wordcount -- yarn jar "${EXAMPLES}" wordcount "${D}/in" "${D}/wc-out"
cli wordcount-output --shape sha256 -- hadoop fs -cat "${D}/wc-out/part-r-00000"
cli grep -- yarn jar "${EXAMPLES}" grep "${D}/in" "${D}/grep-out" 'jump[a-z]*'
cli grep-output --shape lines -- hadoop fs -cat "${D}/grep-out/part-r-00000"
cli teragen -- yarn jar "${EXAMPLES}" teragen -Dmapreduce.job.maps=2 20000 "${D}/teragen"
cli terasort -- yarn jar "${EXAMPLES}" terasort -Dmapreduce.job.reduces=2 "${D}/teragen" "${D}/terasort"
cli teravalidate -- yarn jar "${EXAMPLES}" teravalidate "${D}/terasort" "${D}/teravalidate"
cli teravalidate-checksum --expect-regex 'checksum\s+(\S+)' -- \
  hadoop fs -cat "${D}/teravalidate/part-r-00000"
cli job-list --shape none -- mapred job -list all
cli job-status --expect-regex 'Job state: (\w+)' -- mapred job -status "${PI_JOB}"
cli job-counter --expect-regex '^(\d+)' -- \
  mapred job -counter "${PI_JOB}" org.apache.hadoop.mapreduce.TaskCounter MAP_INPUT_RECORDS
cli queue-list --shape none -- mapred queue -list
cli hsadmin-refresh -- mapred hsadmin -refreshLoadedJobCache
cli classpath -- mapred classpath

# A job that stays running long enough to look at its application master.
COMPONENT=mapreduce-am
yarn jar "${JOBCLIENT_TESTS}" sleep -m 1 -r 1 -mt 120000 -rt 1000 \
  > "${RES}/sleep-job.log" 2>&1 &
SLEEP_PID=$!
SLEEP_APP=""
for _ in $(seq 1 60); do
  SLEEP_APP=$(latest_app '^Sleep job$')
  [[ -n "${SLEEP_APP}" ]] && wait_app_state "${SLEEP_APP}" RUNNING 2 >/dev/null && break
  sleep 2
done
# The AM web app answers only after it registered its tracking URL.
for _ in $(seq 1 30); do
  curl -s --noproxy '*' -o /dev/null -w '%{http_code}' \
    "http://${HOST}:${P_PROXY}/proxy/${SLEEP_APP}/ws/v1/mapreduce/info" | grep -q 200 && break
  sleep 2
done
PX="http://${HOST}:${P_PROXY}/proxy/${SLEEP_APP}"
SLEEP_JOB=${SLEEP_APP/application_/job_}
http am-info "${PX}/ws/v1/mapreduce/info" --expect-regex '"appId"'
http am-info-xml "${PX}/ws/v1/mapreduce/info" --header 'Accept: application/xml'
http am-jobs "${PX}/ws/v1/mapreduce/jobs" --expect-regex '"jobs"'
http am-job "${PX}/ws/v1/mapreduce/jobs/${SLEEP_JOB}" --expect-regex '"state"'
http am-job-counters "${PX}/ws/v1/mapreduce/jobs/${SLEEP_JOB}/counters"
http am-job-conf "${PX}/ws/v1/mapreduce/jobs/${SLEEP_JOB}/conf" --expect-regex '"property"'
http am-job-tasks "${PX}/ws/v1/mapreduce/jobs/${SLEEP_JOB}/tasks"
http am-job-attempts "${PX}/ws/v1/mapreduce/jobs/${SLEEP_JOB}/jobattempts"
http am-err-no-job "${PX}/ws/v1/mapreduce/jobs/job_1_0001" --expect-status 404
http am-ui "${PX}/mapreduce" --expect-status any
http am-ui-job "${PX}/mapreduce/job/${SLEEP_JOB}" --expect-status any
http am-ui-conf "${PX}/mapreduce/conf/${SLEEP_JOB}" --expect-status any
http am-root-redirect "${PX}/" --expect-status any
http rm-tracking "${RM_URL}/cluster/app/${SLEEP_APP}"
cli kill --merge-stderr --expect-regex '(Killed job \S+)' -- mapred job -kill "${SLEEP_JOB}"
wait "${SLEEP_PID}" 2>/dev/null || true
state=$(wait_app_state "${SLEEP_APP}" 'KILLED|FINISHED|FAILED' 60 || true)
check sleep-job-killed "$([[ "${state}" == KILLED ]] && echo true || echo false)" "state ${state}"

COMPONENT=mapreduce-jhs
J="${JHS_URL}/ws/v1/history"
# The history server picks up finished jobs asynchronously.
for _ in $(seq 1 30); do
  curl -s --noproxy '*' "${J}/mapreduce/jobs/${PI_JOB}" | grep -q '"state":"SUCCEEDED"' && break
  sleep 2
done
http history "${J}" --expect-regex '"historyInfo"'
http info "${J}/info" --expect-regex '"hadoopVersion"'
http info-xml "${J}/info" --header 'Accept: application/xml'
http jobs "${J}/mapreduce/jobs" --expect-regex '"jobs"'
http jobs-xml "${J}/mapreduce/jobs" --header 'Accept: application/xml'
http job "${J}/mapreduce/jobs/${PI_JOB}" --expect-regex '"state":"SUCCEEDED"'
http job-counters "${J}/mapreduce/jobs/${PI_JOB}/counters" --expect-regex '"counterGroup"'
http job-conf "${J}/mapreduce/jobs/${PI_JOB}/conf" --expect-regex '"property"'
http job-tasks "${J}/mapreduce/jobs/${PI_JOB}/tasks" --expect-regex '"task"'
http job-attempts "${J}/mapreduce/jobs/${PI_JOB}/jobattempts"
TASK=${PI_JOB/job_/task_}_m_000000
http task "${J}/mapreduce/jobs/${PI_JOB}/tasks/${TASK}" --expect-regex '"state":"SUCCEEDED"'
http task-attempts "${J}/mapreduce/jobs/${PI_JOB}/tasks/${TASK}/attempts"
http task-counters "${J}/mapreduce/jobs/${PI_JOB}/tasks/${TASK}/counters"
http err-no-job "${J}/mapreduce/jobs/job_1_0001" --expect-status 404
http err-bad-job "${J}/mapreduce/jobs/not_a_job" --expect-status 400
http ui "${JHS_URL}/jobhistory"
http ui-job "${JHS_URL}/jobhistory/job/${PI_JOB}"
http ui-conf "${JHS_URL}/jobhistory/conf/${PI_JOB}"
http ui-tasks "${JHS_URL}/jobhistory/tasks/${PI_JOB}/m"
http ui-about "${JHS_URL}/jobhistory/about"
http ui-logs-redirect "${JHS_URL}/jobhistory/logs/${HOST}:45454/container_0/container_0/${USER_NAME}" \
  --expect-status any
