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

# Usage: e2e/run.sh <baseline|candidate> [architectures] [scenario-pattern]
#
#   architectures   comma-separated names from e2e/arch/ (simple, secure,
#                   ha, federated, mixed), or "all" (the default)
#   scenario-pattern  regex on scenario file names, to run a subset
#
# For each architecture: starts its cluster, runs the scenarios it lists
# (ARCH_SCENARIOS), scans all daemon and container logs for class loading
# and linkage errors, summarizes the classes each daemon loaded, and stops
# the cluster. Results: results/<side>/e2e/<arch>/.

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
SIDE="${1:-}"
check_side "${SIDE}"
ARCHS="${2:-all}"
PATTERN="${3:-}"
require_cmd java python3 curl
ALL_ARCHS=(simple secure ha federated mixed)
[[ "${ARCHS}" == all ]] && ARCHS=$(IFS=,; echo "${ALL_ARCHS[*]}")

rc_all=0
for ARCH in ${ARCHS//,/ }; do
  LOG_TAG="e2e:${SIDE}:${ARCH}"
  log "architecture ${ARCH}"
  # Each architecture in its own shell: its environment must not leak.
  ( set -euo pipefail
    export ARCH
    source "${HARNESS_DIR}/e2e/lib/env.sh"
    CLUSTER="${HARNESS_DIR}/e2e/cluster.sh"
    trap '"${CLUSTER}" "${SIDE}" "${ARCH}" stop >/dev/null 2>&1 || true' EXIT

    "${CLUSTER}" "${SIDE}" "${ARCH}" start
    mkdir -p "${RES}/scenarios"
    : > "${OBS}"
    for scenario in "${E2E_DIR}"/scenarios/*.sh; do
      name=$(basename "${scenario}" .sh)
      [[ "${name}" =~ ${ARCH_SCENARIOS} ]] || continue
      [[ -z "${PATTERN}" || "${name}" =~ ${PATTERN} ]] || continue
      log "scenario ${name}"
      start=${SECONDS}
      # Each scenario in its own shell so a failing command cannot stop the
      # others; a hung scenario is cut off.
      set +e
      timeout "${E2E_SCENARIO_TIMEOUT:-3600}" bash -c '
        set -u
        source "$1/lib/common.sh"
        SIDE=$2 ARCH=$3
        source "$1/e2e/lib/env.sh"
        source "$4"
      ' _ "${HARNESS_DIR}" "${SIDE}" "${ARCH}" "${scenario}" > "${RES}/scenarios/${name}.log" 2>&1
      rc=$?
      set -e
      if [[ ${rc} -eq 124 ]]; then
        log "scenario ${name} timed out"
        COMPONENT=scenario check "${name}.timeout" false "timed out" 2>/dev/null || true
      fi
      log "scenario ${name} done in $((SECONDS - start))s: $(grep -c '\[PASS\]' "${RES}/scenarios/${name}.log") pass, $(grep -c '\[FAIL\]' "${RES}/scenarios/${name}.log") fail"
    done

    # Give the daemons a moment to flush aggregated logs, then look at them.
    sleep 5
    python3 -I "${E2E_DIR}/lib/logscan.py" "${HADOOP_LOG_DIR}" "${RES}" > "${RES}/logscan.json"
    python3 -I "${E2E_DIR}/lib/classload.py" summarize "${RES}/classload" "${DIST}" \
      > "${RES}/classload-summary.json"
    "${CLUSTER}" "${SIDE}" "${ARCH}" stop
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
    log "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("%d observations, %d pass, %d fail" % (d["observations"], d["passed"], d["failed"]))' "${RES}/summary.json")"
    log "results in ${RES}"
  ) || { log "architecture ${ARCH} did not complete"; rc_all=1; }
done
exit "${rc_all}"
