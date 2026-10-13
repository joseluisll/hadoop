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

# Usage: run-all.sh [quick|full|none]
#
# The whole comparison: build both sides, run the end-to-end cluster on
# both, run the unit tests on both (tier quick by default, "none" to skip),
# and write results/compare/report.md. Exits 0 only when every check passed.
# See README.md for the environment variables.

set -uo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="run-all"
TIER="${1:-quick}"
H="${HARNESS_DIR}"

for side in baseline candidate; do
  "${H}/build.sh" "${side}" || die "build of ${side} failed"
done
for side in baseline candidate; do
  "${H}/e2e/run.sh" "${side}" || log "e2e run of ${side} did not complete; the comparison will show it"
done
if [[ "${TIER}" != none ]]; then
  for side in baseline candidate; do
    "${H}/unit-tests.sh" "${side}" "${TIER}"
  done
fi
"${H}/compare.sh"
rc=$?
log "report: ${WORKDIR}/results/compare/report.md"
exit "${rc}"
