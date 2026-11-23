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

# Usage: attribution.sh list | <tree> | merge <tree> | compare <tree>
#
# The per-ticket and merge-order runs (R89): the candidate is the baseline
# plus one PR branch (ticket-<n>) or a prefix of the merge order (prefix-<n>).
# The branches and their order come from PR_ORDER in lib/compare_plan.py.
#
#   list          print the tree names, one per line
#   <tree>        create the tree as a detached merge commit in a worktree
#                 under WORKDIR (no branch is created), set CANDIDATE_REF,
#                 and run checks 1, 2 and 5 for it: build both sides,
#                 artifact-diff.sh (which includes the API check) and the
#                 downstream comparison. The comparisons go to
#                 results/attribution/<tree>/.
#   merge <tree>  only create the tree and print its commit; under GitHub
#                 Actions it also sets CANDIDATE_REF for the later steps
#   compare <tree>  only the comparisons, once both sides are built (CI
#                 builds them or reuses saved builds of the same code)
#
# It calls the same scripts a normal run calls; it does not reimplement them.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="attribution"

usage() {
  die "usage: $0 list|<tree>|merge <tree>|compare <tree>"
}

pr_branches() {
  python3 -I - "${HARNESS_DIR}" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1] + "/lib")
from compare_plan import PR_ORDER
print("\n".join(PR_ORDER))
EOF
}

step=all
if [[ "${1:-}" == merge || "${1:-}" == compare ]]; then
  step=$1
  shift
fi
tree=${1:-}
[[ -n "${tree}" ]] || usage

mapfile -t branches < <(pr_branches)
(( ${#branches[@]} > 0 )) || die "PR_ORDER in lib/compare_plan.py is empty"

if [[ "${step}" == all && "${tree}" == list ]]; then
  for i in "${!branches[@]}"; do
    echo "ticket-$((i + 1))"
  done
  for n in 2 3 4 5; do
    (( n <= ${#branches[@]} )) && echo "prefix-${n}"
  done
  exit 0
fi

case "${tree}" in
  ticket-*) n=${tree#ticket-}; kind=ticket ;;
  prefix-*) n=${tree#prefix-}; kind=prefix ;;
  *) usage ;;
esac
[[ "${n}" =~ ^[0-9]+$ ]] || usage

if [[ "${kind}" == ticket ]]; then
  (( n >= 1 && n <= ${#branches[@]} )) || die "no ${tree}: only ${#branches[@]} branches"
  merge=("${branches[$((n - 1))]}")
else
  (( n >= 2 && n <= 5 && n <= ${#branches[@]} )) || die "no ${tree}: prefixes are 2 to 5"
  merge=("${branches[@]:0:n}")
fi

if [[ "${step}" != compare ]]; then
  # The tree is a detached merge commit in its own worktree. The candidate's
  # build worktree (build.sh) is separate; both may check out the same commit.
  tree_dir="${WORKDIR}/attribution/${tree}"
  git -C "${REPO_DIR}" worktree remove --force "${tree_dir}" 2>/dev/null || true
  rm -rf "${tree_dir}"
  mkdir -p "$(dirname "${tree_dir}")"
  git -C "${REPO_DIR}" worktree prune
  git -C "${REPO_DIR}" worktree add --detach "${tree_dir}" "${BASELINE_REF}"
  for branch in "${merge[@]}"; do
    git -C "${tree_dir}" -c user.name=harness -c user.email=harness@invalid \
      merge --no-ff -m "attribution ${tree}: merge ${branch}" "${branch}"
  done
  CANDIDATE_REF=$(git -C "${tree_dir}" rev-parse HEAD)
  export CANDIDATE_REF
  log "${tree}: ${CANDIDATE_REF} (${#merge[@]} branch(es))"
  [[ -n "${GITHUB_ENV:-}" ]] && echo "CANDIDATE_REF=${CANDIDATE_REF}" >> "${GITHUB_ENV}"
  [[ "${step}" == merge ]] && { echo "${CANDIDATE_REF}"; exit 0; }

  # What a normal run runs for checks 1, 2 and 5.
  "${HARNESS_DIR}/build.sh" baseline
  "${HARNESS_DIR}/build.sh" candidate
fi

# A comparison that fails is reported by lib/attribution.py, not here.

out="${WORKDIR}/results/attribution/${tree}"
mkdir -p "${out}"
rm -f "${WORKDIR}/results/compare"/artifact-diff.json \
      "${WORKDIR}/results/compare"/artifact-diff.md \
      "${WORKDIR}/results/compare"/api-compat.json \
      "${WORKDIR}/results/compare"/api-compat.md
"${HARNESS_DIR}/artifact-diff.sh" baseline candidate || true
for f in artifact-diff.json artifact-diff.md api-compat.json api-compat.md; do
  [[ -f "${WORKDIR}/results/compare/${f}" ]] && cp "${WORKDIR}/results/compare/${f}" "${out}/"
done

"${HARNESS_DIR}/downstream-deps.sh" baseline || log "downstream-deps baseline did not complete"
"${HARNESS_DIR}/downstream-deps.sh" candidate || log "downstream-deps candidate did not complete"
python3 -I "${HARNESS_DIR}/lib/compare_downstream.py" \
  --expected "${HARNESS_DIR}/expected-downstream-differences.txt" --out "${out}" \
  "$(results_dir baseline)/downstream" "$(results_dir candidate)/downstream" || true

log "${tree}: comparisons in ${out}"
