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

# Usage: compare.sh [architectures]
#
# Compares what both sides have produced (build, e2e, unit) and writes
# results/compare/report.md. Exits 0 only when every check passed.
#
# First it checks that the two trees are what they claim to be, and stops
# before comparing when they are not (R78 to R80):
#   - the candidate contains the baseline's commits (lib/ancestry.py);
#   - the candidate is the baseline plus the PR branches (lib/compare_plan.py),
#     when PR_BRANCHES names them.
# Either failure writes its section of the report and exits 1 without running
# a comparison: differences from an older trunk or a hand-made change are not
# differences the patch causes. Set ANCESTRY_CHECK or PLAN_CHECK to false to
# compare anyway. Both are skipped when the two sides are the same commit (a
# self-comparison run, R68), which has no patch for them to check.
#
# architectures: comma-separated list that should have run end to end; each
# one missing on a side is reported NOT RUN. Default: every architecture
# either side has results for.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="compare"
OUT="${WORKDIR}/results/compare"
mkdir -p "${OUT}"
# report.py lists what it finds here, so nothing may be left from an earlier
# run: remove only what this script writes. A directory holding downloaded
# report-<arch> artifacts (what replay.sh reads) must survive a compare run.
for f in ancestry.json ancestry.md compare-plan.json compare-plan.md \
         artifact-diff.json artifact-diff.md api-compat.json api-compat.md \
         e2e-compare-*.json e2e-compare-*.md classload-compare-*.json \
         unit-compare.json unit-compare.md downstream-compare.json \
         downstream-compare.md impact.json impact.md report.md; do
  rm -f "${OUT}/${f}"
done
B=$(results_dir baseline)
C=$(results_dir candidate)

# A broken comparator would cost a whole run to find out.
python3 -I "${HARNESS_DIR}/lib/test_comparators.py" || die "the comparators' self-check failed"

stop=0
if ! checks_supported; then
  log "skipping the ancestry and plan checks: both sides are ${BASELINE_REF} (a self-comparison)"
elif [[ "${ANCESTRY_CHECK:-true}" == true ]]; then
  python3 -I "${HARNESS_DIR}/lib/ancestry.py" --out "${OUT}" \
    --baseline "${BASELINE_REF}" --candidate "${CANDIDATE_REF}" || stop=1
fi
if checks_supported && [[ -n "${PR_BRANCHES:-}" && "${PLAN_CHECK:-true}" == true ]]; then
  # PR_BRANCHES: the branches merged into trunk, in merge order, comma-separated.
  plan_args=()
  for b in ${PR_BRANCHES//,/ }; do plan_args+=(--branch "${b}"); done
  python3 -I "${HARNESS_DIR}/lib/compare_plan.py" --out "${OUT}" \
    --baseline "${BASELINE_REF}" --candidate "${CANDIDATE_REF}" "${plan_args[@]}" || stop=1
fi
if (( stop )); then
  # || true: report.py exits 1 when the overall verdict is not PASS, which
  # set -e would turn into an exit before the reason below is logged.
  python3 -I "${HARNESS_DIR}/lib/report.py" "${WORKDIR}/results" || true
  # Exit 1 without die's "ERROR": the report already says which check failed,
  # and a caller may want to tell this stop from a comparison that failed.
  log "stopped before comparing: the candidate is not the tree to test; see ${OUT}/report.md"
  exit 1
fi

if [[ -f "${B}/build/dist-path.txt" && -f "${C}/build/dist-path.txt" ]]; then
  "${HARNESS_DIR}/artifact-diff.sh" baseline candidate || true
else
  log "skipping artifact diff: both sides must be built"
fi

if [[ -n "${1:-}" ]]; then
  archs="${1//,/ }"
else
  archs=$(find "${B}/e2e" "${C}/e2e" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null \
    | sort -u | tr '\n' ' ') || true
fi
# compare_e2e.py writes a NOT RUN result for an architecture a side has no
# observations for, so it shows in the report instead of being skipped.
for arch in ${archs}; do
  python3 -I "${HARNESS_DIR}/lib/compare_e2e.py" \
    --expected "${HARNESS_DIR}/e2e/expected-e2e-differences.txt" --out "${OUT}" \
    --arch "${arch}" "${B}/e2e/${arch}" "${C}/e2e/${arch}" || true
done
[[ -n "${archs// /}" ]] || log "no architecture ran end to end"

if [[ -d "${B}/unit" && -d "${C}/unit" ]]; then
  python3 -I "${HARNESS_DIR}/lib/compare_unit.py" --out "${OUT}" "${B}/unit" "${C}/unit" || true
else
  log "skipping unit test comparison: both sides must have run unit-tests.sh"
fi
python3 -I "${HARNESS_DIR}/lib/compare_downstream.py" \
  --expected "${HARNESS_DIR}/expected-downstream-differences.txt" --out "${OUT}" \
  "${B}/downstream" "${C}/downstream" || true

# Who the accepted and unexpected differences affect (no verdict of its own).
python3 -I "${HARNESS_DIR}/lib/impact.py" "${OUT}" || true
python3 -I "${HARNESS_DIR}/lib/report.py" "${WORKDIR}/results"
