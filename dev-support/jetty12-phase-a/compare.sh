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

# Usage: compare.sh
#
# Compares whatever both sides have produced (build, e2e, unit) and writes
# results/compare/report.md. Exits 0 only when every check passed.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="compare"
OUT="${WORKDIR}/results/compare"
mkdir -p "${OUT}"
B=$(results_dir baseline)
C=$(results_dir candidate)

if [[ -f "${B}/build/dist-path.txt" && -f "${C}/build/dist-path.txt" ]]; then
  "${HARNESS_DIR}/artifact-diff.sh" baseline candidate || true
else
  log "skipping artifact diff: both sides must be built"
fi

compared=0
for arch_dir in "${B}"/e2e/*/; do
  arch=$(basename "${arch_dir}")
  if [[ -f "${B}/e2e/${arch}/observations.jsonl" && -f "${C}/e2e/${arch}/observations.jsonl" ]]; then
    python3 -I "${HARNESS_DIR}/lib/compare_e2e.py" \
      --expected "${HARNESS_DIR}/e2e/expected-e2e-differences.txt" --out "${OUT}" \
      --arch "${arch}" "${B}/e2e/${arch}" "${C}/e2e/${arch}" || true
    compared=$((compared + 1))
  else
    log "skipping e2e comparison of ${arch}: both sides must have run it"
  fi
done
(( compared > 0 )) || log "no architecture ran end to end on both sides"

if [[ -d "${B}/unit" && -d "${C}/unit" ]]; then
  python3 -I "${HARNESS_DIR}/lib/compare_unit.py" --out "${OUT}" "${B}/unit" "${C}/unit" || true
else
  log "skipping unit test comparison: both sides must have run unit-tests.sh"
fi

python3 -I "${HARNESS_DIR}/lib/report.py" "${WORKDIR}/results"
