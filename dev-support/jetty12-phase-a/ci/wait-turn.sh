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

# Usage: ci/wait-turn.sh <owner/repo> <run id> [--once]
#
# Runs of the harness workflows (any architecture) go one at a time, oldest
# first: this waits until no earlier run of a workflow named
# "Jetty 12 phase A: *" is queued, waiting or in progress. GitHub's own
# concurrency groups keep at most one run pending and cancel the others, so
# they cannot queue several runs. Run ids grow with creation time, so "earlier"
# is a smaller id. --once prints the blocking runs and exits (1 if any).
#
# GH_TOKEN, when set, authenticates the API calls (actions: read).
# WAIT_INTERVAL (seconds, default 60) is the polling period.

set -euo pipefail
repo=$1
run_id=$2
once=${3:-}
interval=${WAIT_INTERVAL:-60}

auth=()
[[ -n "${GH_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer ${GH_TOKEN}")

# Earlier active harness runs, one "<id> <name> (<status>)" per line.
blocking() {
  local status
  for status in queued waiting requested pending in_progress; do
    curl -fsS --retry 3 --retry-delay 5 "${auth[@]}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${repo}/actions/runs?status=${status}&per_page=100" \
      | jq -r --argjson me "${run_id}" '.workflow_runs[]
          | select(.id < $me and (.name | startswith("Jetty 12 phase A: ")))
          | "\(.id) \(.name) [\(.head_branch)] (\(.status))"'
  done | sort -u
}

while true; do
  ahead=$(blocking)
  if [[ -z "${ahead}" ]]; then
    echo "no earlier harness run is active; starting"
    exit 0
  fi
  echo "$(date -u +%H:%M:%S) waiting for $(wc -l <<< "${ahead}") earlier harness run(s):"
  sed 's/^/  /' <<< "${ahead}"
  [[ "${once}" == --once ]] && exit 1
  sleep "${interval}"
done
