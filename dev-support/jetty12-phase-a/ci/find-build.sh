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

# Usage: ci/find-build.sh <owner/repo> <artifact name>
#
# Prints the run id of the newest unexpired artifact of that name (a build
# saved under its ci/build-key.sh key), or nothing. Artifacts, unlike the
# actions cache, can be read from any branch of the repository, and every
# harness run is on a branch of its own. A failed lookup prints nothing too:
# the job then builds as if nothing was saved.
#
# GH_TOKEN, when set, authenticates the call (actions: read); GITHUB_API_URL
# (default https://api.github.com) is the API.

set -uo pipefail
repo=$1
name=$2
auth=()
[[ -n "${GH_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer ${GH_TOKEN}")
curl -fsS --max-time 30 --retry 3 "${auth[@]}" -H "Accept: application/vnd.github+json" \
  "${GITHUB_API_URL:-https://api.github.com}/repos/${repo}/actions/artifacts?name=${name}&per_page=10" \
  | jq -r '[.artifacts[] | select(.expired | not)] | sort_by(.created_at) | last | .workflow_run.id // empty' \
  || true
