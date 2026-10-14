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

# Usage: run-all.sh [quick|full|none] [architectures]
#
# The whole comparison on one machine: build both sides, run every
# architecture end to end on both (or the comma-separated list given), run
# all unit test suites on both (the "changed" suite in tier quick by
# default; "none" skips unit tests), and write results/compare/report.md.
# Exits 0 only when every check passed. See README.md for the environment
# variables; CI runs the same steps in parallel jobs.

set -uo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="run-all"
TIER="${1:-quick}"
ARCHS="${2:-all}"
H="${HARNESS_DIR}"

for side in baseline candidate; do
  "${H}/build.sh" "${side}" || die "build of ${side} failed"
done
for side in baseline candidate; do
  "${H}/e2e/run.sh" "${side}" "${ARCHS}" || log "e2e run of ${side} did not complete; the comparison will show it"
done
if [[ "${TIER}" != none ]]; then
  for side in baseline candidate; do
    "${H}/unit-tests.sh" "${side}" all "${TIER}"
  done
fi
for side in baseline candidate; do
  "${H}/downstream-deps.sh" "${side}" || log "downstream projects of ${side} did not resolve; the comparison will show it"
done
all_archs=(simple secure ha federated mixed)
[[ "${ARCHS}" == all ]] && ARCHS=$(IFS=,; echo "${all_archs[*]}")
"${H}/compare.sh" "${ARCHS}"
rc=$?
log "report: ${WORKDIR}/results/compare/report.md"
exit "${rc}"
