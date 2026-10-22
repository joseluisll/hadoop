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

# YARN: command line, a distributed shell application, the resource manager
# REST API (JSON and XML, application submission and kill through REST), the
# node manager, timeline server / application history (timeline entity
# round trip), web proxy, router, timeline reader v2 and the YARN services
# API. HADOOP-20015 changes how jetty-webapp reaches the RM, AHS and router.

U="user.name=${USER_NAME}"
NODE_ID="${HOST}:45454"
DSHELL_JAR=$(ls "${DIST}"/share/hadoop/yarn/hadoop-yarn-applications-distributedshell-*.jar | head -1)

COMPONENT=yarn-cli
cli version --expect-regex '^Hadoop (\S+)' -- yarn version
cli node-list --expect-regex 'Total Nodes:(\d+)' -- yarn node -list -all
cli node-status --expect-regex 'Node-State : (\w+)' -- yarn node -status "${NODE_ID}"
cli queue-status --expect-regex 'State : (\w+)' -- yarn queue -status default
cli refresh-queues -- yarn rmadmin -refreshQueues
cli refresh-nodes -- yarn rmadmin -refreshNodes
cli service-state --expect-rc 0,255 -- yarn rmadmin -getAllServiceState
cli node-labels --shape none -- yarn cluster --list-node-labels
cli dshell --merge-stderr --expect-regex '(Application completed successfully)' -- \
  yarn jar "${DSHELL_JAR}" -jar "${DSHELL_JAR}" -shell_command echo \
  -shell_args jetty12-dshell-output -num_containers 2 -container_memory 256 \
  -master_memory 256 -appname jetty12-dshell
DSHELL_APP=$(latest_app '^jetty12-dshell$')
cli app-list --shape none -- yarn application -list -appStates ALL
cli app-status --expect-regex 'Final-State : (\w+)' -- yarn application -status "${DSHELL_APP}"
cli app-attempts --expect-regex 'Total number of application attempts :(\d+)' -- \
  yarn applicationattempt -list "${DSHELL_APP}"
# Log aggregation is asynchronous; give it a moment.
for _ in $(seq 1 30); do
  yarn logs -applicationId "${DSHELL_APP}" 2>/dev/null | grep -q jetty12-dshell-output && break
  sleep 2
done
cli logs --expect-regex '(jetty12-dshell-output)' -- yarn logs -applicationId "${DSHELL_APP}"

COMPONENT=yarn-rm-rest
C="${RM_URL}/ws/v1/cluster"
http cluster "${C}" --expect-regex '"clusterInfo"'
http info "${C}/info" --expect-regex '"resourceManagerVersion"'
http info-xml "${C}/info" --header 'Accept: application/xml' --expect-regex '<clusterInfo>'
http metrics "${C}/metrics" --expect-regex '"clusterMetrics"'
http metrics-xml "${C}/metrics" --header 'Accept: application/xml'
http scheduler "${C}/scheduler" --expect-regex '"schedulerInfo"'
http scheduler-xml "${C}/scheduler" --header 'Accept: application/xml'
http apps "${C}/apps" --expect-regex '"apps"'
http apps-finished "${C}/apps?states=FINISHED&applicationTypes=YARN"
http apps-xml "${C}/apps" --header 'Accept: application/xml'
http app "${C}/apps/${DSHELL_APP}" --expect-regex '"finalStatus":"SUCCEEDED"'
http app-xml "${C}/apps/${DSHELL_APP}" --header 'Accept: application/xml'
http app-state "${C}/apps/${DSHELL_APP}/state" --expect-regex '"state":"FINISHED"'
http app-attempts "${C}/apps/${DSHELL_APP}/appattempts"
http app-priority "${C}/apps/${DSHELL_APP}/priority"
http app-queue "${C}/apps/${DSHELL_APP}/queue"
http app-timeouts "${C}/apps/${DSHELL_APP}/timeouts"
http appstatistics "${C}/appstatistics"
http nodes "${C}/nodes" --expect-regex '"nodes"'
http node "${C}/nodes/${NODE_ID}" --expect-regex '"state":"RUNNING"'
http node-xml "${C}/nodes/${NODE_ID}" --header 'Accept: application/xml'
http node-labels "${C}/get-node-labels"
http node-to-labels "${C}/get-node-to-labels"
http label-mappings "${C}/label-mappings"
http activities "${C}/scheduler/activities" --expect-status any
http app-activities "${C}/scheduler/app-activities/${DSHELL_APP}" --expect-status any
http scheduler-conf "${C}/scheduler-conf" --expect-status any
http reservation-list "${C}/reservation/list?queue=default" --expect-status any
http err-no-app "${C}/apps/application_1_0001" --expect-status 404
http err-bad-app-id "${C}/apps/not_an_app" --expect-status any
http err-bad-state "${C}/apps?states=NOSUCHSTATE" --expect-status any
http err-no-node "${C}/nodes/nosuchhost:1" --expect-status 404
http err-unsupported-type "${C}/info" --header 'Accept: image/png' --expect-status any
# Submit an application through REST: JSON request bodies are parsed by the
# Jersey providers phase A touches. The AM command never registers, so the
# attempt fails; with one attempt allowed the application ends FAILED.
http new-app "${C}/apps/new-application?${U}" --method POST --data '' \
  --expect-regex '"application-id"' --out "${RES}/new-app.json"
REST_APP=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["application-id"])' \
  "${RES}/new-app.json" 2>/dev/null || echo none)
http submit-app "${C}/apps?${U}" --method POST --header 'Content-Type: application/json' \
  --expect-status 202 --data "{\"application-id\":\"${REST_APP}\",
  \"application-name\":\"jetty12-rest-app\",\"application-type\":\"YARN\",
  \"queue\":\"default\",\"max-app-attempts\":1,
  \"resource\":{\"memory\":256,\"vCores\":1},
  \"am-container-spec\":{\"commands\":{\"command\":\"sleep 1\"},
    \"environment\":{\"entry\":[{\"key\":\"JETTY12\",\"value\":\"phase-a\"}]}}}"
state=$(wait_app_state "${REST_APP}" 'FAILED|FINISHED|KILLED' 120 || true)
check rest-app-final-state "$([[ "${state}" == FAILED ]] && echo true || echo false)" "state ${state}"
http rest-app "${C}/apps/${REST_APP}" --expect-regex '"name":"jetty12-rest-app"'
# Submit through XML, then kill it through REST.
http new-app-2 "${C}/apps/new-application?${U}" --method POST --data '' \
  --header 'Accept: application/xml' --out "${RES}/new-app-2.xml"
KILL_APP=$(sed -n 's:.*<application-id>\(.*\)</application-id>.*:\1:p' "${RES}/new-app-2.xml")
http submit-app-xml "${C}/apps?${U}" --method POST --header 'Content-Type: application/xml' \
  --expect-status 202 --data "<application-submission-context>
  <application-id>${KILL_APP}</application-id><application-name>jetty12-kill-app</application-name>
  <queue>default</queue><max-app-attempts>1</max-app-attempts>
  <am-container-spec><commands><command>sleep 600</command></commands></am-container-spec>
  <resource><memory>256</memory><vCores>1</vCores></resource>
  </application-submission-context>"
wait_app_state "${KILL_APP}" 'ACCEPTED|RUNNING' 60 >/dev/null || true
http kill-app "${C}/apps/${KILL_APP}/state?${U}" --method PUT \
  --header 'Content-Type: application/json' --data '{"state":"KILLED"}' --expect-status 200,202
state=$(wait_app_state "${KILL_APP}" 'KILLED' 60 || true)
check kill-app-final-state "$([[ "${state}" == KILLED ]] && echo true || echo false)" "state ${state}"

COMPONENT=yarn-rm-web
http cluster "${RM_URL}/cluster" --expect-regex 'About the Cluster'
http cluster-about "${RM_URL}/cluster/cluster"
http apps "${RM_URL}/cluster/apps"
http apps-finished "${RM_URL}/cluster/apps/FINISHED"
http app "${RM_URL}/cluster/app/${DSHELL_APP}"
http nodes "${RM_URL}/cluster/nodes"
http scheduler "${RM_URL}/cluster/scheduler"
http nodelabels "${RM_URL}/cluster/nodelabels"
http logs-page "${RM_URL}/logs/" --expect-status any
http root-redirect "${RM_URL}/" --expect-status any
http yarn-css "${RM_URL}/static/yarn.css" --shape sha256
http yarn-dt-js "${RM_URL}/static/yarn.dt.plugins.js" --shape sha256 --expect-status any
http ui2 "${RM_URL}/ui2/" --expect-status any
http ws-root "${RM_URL}/ws/v1/" --expect-status any
http err-no-page "${RM_URL}/cluster/nosuchpage" --expect-status any
http err-no-app "${RM_URL}/cluster/app/application_1_0001" --expect-status any

COMPONENT=yarn-nm
N="${NM_URL}/ws/v1/node"
http node "${N}" --expect-regex '"nodeInfo"'
http info "${N}/info" --expect-regex '"nodeManagerVersion"'
http info-xml "${N}/info" --header 'Accept: application/xml'
# Which applications a node manager still tracks depends on log aggregation
# timing, so only the response itself is compared.
http apps "${N}/apps" --shape none
http containers "${N}/containers" --shape none
http resources "${N}/resources" --expect-status any
http aux-services "${N}/auxiliaryservices" --expect-status any
http err-no-app "${N}/apps/application_1_0001" --expect-status 404
http ui-node "${NM_URL}/node"
http ui-apps "${NM_URL}/node/allApplications"
http ui-containers "${NM_URL}/node/allContainers"
http ui-node-info "${NM_URL}/node/node"

if daemon_up timelineserver; then
  COMPONENT=yarn-timeline
  T="${AHS_URL}/ws/v1/timeline"
  http about "${T}" --expect-regex '"About"'
  http put-entity "${T}?${U}" --method POST --header 'Content-Type: application/json' \
    --data '{"entities":[{"entityType":"JETTY12_PHASE_A","entityId":"entity_1",
    "startTime":1700000000000,"events":[{"timestamp":1700000000001,"eventType":"START",
    "eventInfo":{"k":"v"}}],"primaryFilters":{"probe":["jetty12"]},
    "otherInfo":{"answer":42,"nested":{"a":[1,2]}},
    "relatedEntities":{"OTHER":["other_1"]}}]}' \
    --expect-regex '^\{("errors":\[\]|"response":"")\}$' \
    --out "${RES}/timeline-put-entity.json"
  http get-entity "${T}/JETTY12_PHASE_A/entity_1" --expect-regex '"entityId":"entity_1"'
  http get-entities "${T}/JETTY12_PHASE_A?primaryFilter=probe:jetty12" \
    --expect-regex '"entity_1"'
  http get-events "${T}/JETTY12_PHASE_A/events?entityId=entity_1" --expect-regex '"START"'
  http yarn-app-entities "${T}/YARN_APPLICATION?limit=10"
  http domain "${T}/domain?owner=${USER_NAME}" --expect-status any
  http err-no-entity "${T}/JETTY12_PHASE_A/no_such_entity" --expect-status 404
  http err-bad-json "${T}?${U}" --method POST --header 'Content-Type: application/json' \
    --data '{"entities":[{' --expect-status any
  H="${AHS_URL}/ws/v1/applicationhistory"
  http ahs-about "${H}" --expect-status any
  http ahs-apps "${H}/apps"
  http ahs-app "${H}/apps/${DSHELL_APP}" --expect-status 200,404
  http ahs-attempts "${H}/apps/${DSHELL_APP}/appattempts" --expect-status 200,404
  http ahs-ui "${AHS_URL}/applicationhistory"
  http ahs-ui-app "${AHS_URL}/applicationhistory/app/${DSHELL_APP}" --expect-status any
fi

if daemon_up proxyserver; then
  COMPONENT=yarn-proxy
  P="${PROXY_URL}"
  http finished-app "${P}/proxy/${DSHELL_APP}/" --expect-status any
  http unknown-app "${P}/proxy/application_1_0001/" --expect-status any
  http bad-app-id "${P}/proxy/not_an_app/" --expect-status any
fi

if daemon_up router; then
  COMPONENT=yarn-router
  Y="http://${HOST}:${P_YROUTER_HTTP}"
  http cluster-info "${Y}/ws/v1/cluster/info" --expect-status any
  http cluster-metrics "${Y}/ws/v1/cluster/metrics" --expect-status any
  http apps "${Y}/ws/v1/cluster/apps" --expect-status any
  http nodes "${Y}/ws/v1/cluster/nodes" --expect-status any
  http ui-cluster "${Y}/cluster" --expect-status any
  http ui-federation "${Y}/cluster/federation" --expect-status any
  http ui-apps "${Y}/cluster/apps" --expect-status any
  cli client-app-list --shape none -- yarn application \
    -Dyarn.resourcemanager.address="${HOST}:${P_YROUTER_CLIENT}" -list -appStates ALL
fi

if daemon_up globalpolicygenerator; then
  COMPONENT=yarn-gpg
  G="http://${HOST}:${P_GPG_HTTP}"
  http ui "${G}/gpg" --expect-status any
  http ui-policies "${G}/gpg/policies" --expect-status any
fi

if daemon_up sharedcachemanager; then
  COMPONENT=yarn-scm
  S="http://${HOST}:${P_SCM_HTTP}"
  http ui "${S}/SCMOverview" --expect-status any
  cli scm-admin --shape none --expect-rc 0,255 -- yarn scmadmin -runCleanerTask
fi

if daemon_up timelinereader; then
  COMPONENT=yarn-timelinereader
  TR="http://${HOST}:${P_TLREADER_HTTP}/ws/v2/timeline"
  http about "${TR}/" --expect-regex '"About"'
  http health "${TR}/health" --expect-status any
  http clusters-apps "${TR}/clusters/yarn-cluster/apps/${DSHELL_APP}" --expect-status any
  http flows "${TR}/flows" --expect-status any
  http err-bad-path "${TR}/no/such/path" --expect-status any
fi

COMPONENT=yarn-services
A="${RM_URL}/app/v1/services"
http api-version "${RM_URL}/app/v1/services/version?${U}" --expect-status any
http create "${A}?${U}" --method POST --header 'Content-Type: application/json' \
  --expect-status 202 --data '{"name":"jetty12-sleeper","version":"1.0.0",
  "components":[{"name":"sleeper","number_of_containers":1,"launch_command":"sleep 900",
  "resource":{"cpus":1,"memory":"256"}}]}'
for _ in $(seq 1 60); do
  rest "${A}/jetty12-sleeper?${U}" | grep -Eq '"state" ?: ?"STABLE"' && break
  sleep 3
done
http status "${A}/jetty12-sleeper?${U}" --expect-regex '"state"\s*:\s*"STABLE"'
cli service-status --expect-regex '"state"\s*:\s*"(STABLE)"' -- yarn app -status jetty12-sleeper
http flex "${A}/jetty12-sleeper/components/sleeper?${U}" --method PUT \
  --header 'Content-Type: application/json' --data '{"number_of_containers":2}' \
  --expect-status 200,202
http stop "${A}/jetty12-sleeper?${U}" --method PUT --header 'Content-Type: application/json' \
  --data '{"state":"STOPPED"}' --expect-status 200,202 --timeout 300
for _ in $(seq 1 40); do
  rest "${A}/jetty12-sleeper?${U}" | grep -Eq '"state" ?: ?"STOPPED"' && break
  sleep 3
done
http destroy "${A}/jetty12-sleeper?${U}" --method DELETE --expect-status 200,204 --timeout 300
http err-no-service "${A}/no-such-service?${U}" --expect-status 404
http err-bad-spec "${A}?${U}" --method POST --header 'Content-Type: application/json' \
  --data '{"name":"Bad Name!"}' --expect-status any
