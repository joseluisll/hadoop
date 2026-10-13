#!/usr/bin/env bash
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

# Usage: e2e/run.sh <baseline|candidate> [scenario-name-pattern]
#
# Starts the side's cluster, runs every scenario in e2e/scenarios (or those
# whose file name matches the pattern), scans all daemon and container logs
# for class loading and linkage errors, summarizes the classes each daemon
# loaded, and stops the cluster.
#
# Results: results/<side>/e2e/{observations.jsonl,summary.json,logscan.json,
# classload-summary.json,scenarios/*.log}

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
PATTERN="${2:-}"
LOG_TAG="e2e:${SIDE}"
require_cmd java python3 curl
source "${HARNESS_DIR}/e2e/lib/env.sh"

CLUSTER="${HARNESS_DIR}/e2e/cluster.sh"
trap '"${CLUSTER}" "${SIDE}" stop >/dev/null 2>&1 || true' EXIT

"${CLUSTER}" "${SIDE}" start
mkdir -p "${RES}/scenarios"
: > "${OBS}"

for scenario in "${E2E_DIR}"/scenarios/*.sh; do
  name=$(basename "${scenario}" .sh)
  [[ -z "${PATTERN}" || "${name}" =~ ${PATTERN} ]] || continue
  log "scenario ${name}"
  start=${SECONDS}
  # Each scenario runs in its own shell so one failing command cannot stop
  # the others; a hung scenario is cut off.
  set +e
  timeout "${E2E_SCENARIO_TIMEOUT:-3600}" bash -c '
    set -u
    source "$1/lib/common.sh"
    SIDE=$2
    source "$1/e2e/lib/env.sh"
    source "$3"
  ' _ "${HARNESS_DIR}" "${SIDE}" "${scenario}" > "${RES}/scenarios/${name}.log" 2>&1
  rc=$?
  set -e
  if [[ ${rc} -eq 124 ]]; then
    log "scenario ${name} timed out"
    COMPONENT="scenario" check "${name}.timeout" false "timed out" 2>/dev/null || true
  fi
  log "scenario ${name} done in $((SECONDS - start))s: $(grep -c '\[PASS\]' "${RES}/scenarios/${name}.log") pass, $(grep -c '\[FAIL\]' "${RES}/scenarios/${name}.log") fail"
done

# Give the daemons a moment to flush aggregated logs, then look at them.
sleep 5
python3 -I "${E2E_DIR}/lib/logscan.py" "${HADOOP_LOG_DIR}" "${RES}" > "${RES}/logscan.json"
python3 -I "${E2E_DIR}/lib/classload.py" summarize "${RES}/classload" "${DIST}" \
  > "${RES}/classload-summary.json"
"${CLUSTER}" "${SIDE}" stop
trap - EXIT

python3 -I - "${OBS}" "${RES}/daemons.txt" > "${RES}/summary.json" <<'EOF'
import json, sys, collections
recs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
by = collections.Counter((r["component"], r["ok"]) for r in recs)
comps = sorted({r["component"] for r in recs})
daemons = dict(l.split() for l in open(sys.argv[2]) if l.strip())
print(json.dumps({
    "observations": len(recs),
    "passed": sum(r["ok"] for r in recs),
    "failed": sum(not r["ok"] for r in recs),
    "daemons": daemons,
    "components": {c: {"pass": by[(c, True)], "fail": by[(c, False)]} for c in comps},
}, indent=1))
EOF
log "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(f"{d[\"observations\"]} observations, {d[\"passed\"]} pass, {d[\"failed\"]} fail")' "${RES}/summary.json")"
log "results in ${RES}"
