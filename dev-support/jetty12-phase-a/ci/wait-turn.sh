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
# "Jetty 12 phase A: *" is still active (any status but completed). GitHub's
# own concurrency groups keep at most one run pending and cancel the others,
# so they cannot queue several runs. Run ids grow with creation time, so
# "earlier" is a smaller id. --once prints the blocking runs and exits (1 if
# any).
#
# Each poll is one API request (plus one per further page of runs created in
# the last LOOKBACK_DAYS, default 2: a run cannot stay active longer, its jobs
# stop after 6 hours). The GITHUB_TOKEN of a run may make 1000 requests an
# hour for the whole repository, so a poll a minute leaves room for several
# waiting runs. A failed request is retried at the next poll; after
# MAX_ERRORS (default 10) failures in a row the wait gives up.
#
# GH_TOKEN, when set, authenticates the API calls (actions: read).
# WAIT_INTERVAL (seconds, default 60) is the polling period; GITHUB_API_URL
# (default https://api.github.com) the API.

set -euo pipefail
repo=$1
run_id=$2
once=${3:-}
interval=${WAIT_INTERVAL:-60}
max_errors=${MAX_ERRORS:-10}
api=${GITHUB_API_URL:-https://api.github.com}
since=$(date -u -d "-${LOOKBACK_DAYS:-2} days" +%Y-%m-%dT%H:%M:%SZ)

auth=()
[[ -n "${GH_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer ${GH_TOKEN}")

# Earlier active harness runs, one "<id> <name> [<branch>] (<status>)" per
# line; returns non-zero when the API cannot be read.
blocking() {
  local page=1 body n
  while true; do
    body=$(curl -fsS --max-time 30 "${auth[@]}" -H "Accept: application/vnd.github+json" \
      "${api}/repos/${repo}/actions/runs?created=%3E%3D${since}&per_page=100&page=${page}") \
      || return 1
    jq -r --argjson me "${run_id}" '.workflow_runs[]
        | select(.id < $me and .status != "completed"
                 and (.name | startswith("Jetty 12 phase A: ")))
        | "\(.id) \(.name) [\(.head_branch)] (\(.status))"' <<< "${body}" || return 1
    n=$(jq '.workflow_runs | length' <<< "${body}") || return 1
    (( n == 100 )) || return 0
    page=$((page + 1))
  done
}

errors=0
while true; do
  if ! ahead=$(blocking); then
    errors=$((errors + 1))
    echo "$(date -u +%H:%M:%S) cannot list the workflow runs (${errors}/${max_errors})" >&2
    (( errors < max_errors )) || { echo "giving up: the Actions API cannot be read" >&2; exit 2; }
    [[ "${once}" == --once ]] && exit 2
    sleep "${interval}"
    continue
  fi
  errors=0
  ahead=$(sort -u <<< "${ahead}" | sed '/^$/d')
  if [[ -z "${ahead}" ]]; then
    echo "no earlier harness run is active; starting"
    exit 0
  fi
  echo "$(date -u +%H:%M:%S) waiting for $(wc -l <<< "${ahead}") earlier harness run(s):"
  sed 's/^/  /' <<< "${ahead}"
  [[ "${once}" == --once ]] && exit 1
  sleep "${interval}"
done
