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

# Moves the harness's outputs between CI jobs.
#
#   ci/artifacts.sh pack-build <side> <dir>    distribution tarball, staged
#                                              test tools, build results
#   ci/artifacts.sh unpack-build <side> <dir>  the reverse, into WORKDIR;
#                                              for the candidate, breaks it
#                                              when asked (BREAK_CANDIDATE,
#                                              BREAK_REF; see below)
#   ci/artifacts.sh reuse-build <side> <dir>   a packed build restored from the
#                                              CI cache (ci/build-key.sh) now
#                                              stands for the current commit
#   ci/artifacts.sh pack-e2e <side> <arch> <dir>
#   ci/artifacts.sh pack-unit <side> <dir>
#   ci/artifacts.sh unpack-results <dir>...    e2e/unit results into WORKDIR
#
# Raw class-load logs stay behind: the per-daemon class tables
# (<daemon>.classes.tsv) are what the comparison reads.

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
LOG_TAG="ci"

pack_build() {
  local side=$1 dir=$2
  mkdir -p "${dir}"
  cp "$(src_dir "${side}")"/hadoop-dist/target/hadoop-*.tar.gz "${dir}/"
  tar -C "$(side_dir "${side}")" -cf "${dir}/tools.tar" tools
  tar -C "$(results_dir "${side}")" -cf "${dir}/build-results.tar" build
  log "packed ${side}: $(du -sh "${dir}" | cut -f1)"
}

unpack_build() {
  local side=$1 dir=$2
  mkdir -p "$(side_dir "${side}")/dist" "$(results_dir "${side}")"
  tar -C "$(side_dir "${side}")/dist" -xzf "${dir}"/hadoop-*.tar.gz
  tar -C "$(side_dir "${side}")" -xf "${dir}/tools.tar"
  tar -C "$(results_dir "${side}")" -xf "${dir}/build-results.tar"
  # The distribution now lives here, not in the build's worktree.
  dist_dir "${side}" > "$(results_dir "${side}")/build/dist-path.txt"
  log "unpacked ${side} into $(dist_dir "${side}")"
  [[ "${side}" == candidate ]] && break_candidate
  return 0
}

# Checks the harness itself by breaking the candidate's distribution, which
# every comparison must then fail on (ci/break_candidate.py; the report says
# what was changed). BREAK_CANDIDATE holds specs for it (e.g.
# "rm:share/*/jetty-http-*.jar"); otherwise BREAK_REF, the name of a branch
# jetty12-phase-a-<arch>-run-broken-<case>-<n>, names a case (no case:
# "annotation").
break_candidate() {
  local args=() case
  if [[ -n "${BREAK_CANDIDATE:-}" ]]; then
    # shellcheck disable=SC2206
    args=(${BREAK_CANDIDATE})
  elif [[ "${BREAK_REF:-}" == *-run-broken-* ]]; then
    case=${BREAK_REF##*-run-broken-}
    case=$(sed -E 's/-?[0-9]+$//' <<< "${case}")
    args=(--case "${case:-annotation}")
  else
    return 0
  fi
  python3 -I "${HARNESS_DIR}/ci/break_candidate.py" "$(dist_dir candidate)" \
    "$(results_dir candidate)/build/broken.txt" "${args[@]}" \
    || die "could not break the candidate as asked (${args[*]})"
  log "candidate deliberately broken: $(tr '\n' ';' < "$(results_dir candidate)/build/broken.txt")"
}

# The cache key covers everything that shapes the build, but the build results
# name the commit that built them, which can be an earlier harness commit:
# name the current one, and keep the original in build/reused-from.txt.
reuse_build() {
  local side=$1 dir=$2 tmp ref
  tmp=$(mktemp -d)
  tar -C "${tmp}" -xf "${dir}/build-results.tar"
  ref=$(ref_for_side "${side}")
  [[ -f "${tmp}/build/reused-from.txt" ]] || cp "${tmp}/build/commit-subject.txt" "${tmp}/build/reused-from.txt"
  git -C "${REPO_DIR}" rev-parse "${ref}" > "${tmp}/build/commit.txt"
  git -C "${REPO_DIR}" log -1 --format='%H %s' "${ref}" > "${tmp}/build/commit-subject.txt"
  log "reusing the cached build of ${side}: built from $(cut -c1-8 "${tmp}/build/reused-from.txt"), now $(cut -c1-8 "${tmp}/build/commit.txt")"
  tar -C "${tmp}" -cf "${dir}/build-results.tar" build
  rm -rf "${tmp}"
}

pack_e2e() {
  local side=$1 arch=$2 dir=$3
  local res
  res="$(results_dir "${side}")/e2e/${arch}"
  mkdir -p "${dir}"
  [[ -d "${res}" ]] || { log "no e2e results for ${side}/${arch}"; return 0; }
  tar -C "$(results_dir "${side}")" --exclude='classload/*.log' \
    -czf "${dir}/e2e-${side}-${arch}.tar.gz" "e2e/${arch}"
  # Daemon logs help when something differs; they are not compared.
  local logs
  logs="$(side_dir "${side}")/e2e/${arch}/logs"
  [[ -d "${logs}" ]] && tar -C "$(dirname "${logs}")" -czf "${dir}/logs-${side}-${arch}.tar.gz" logs || true
}

pack_unit() {
  local side=$1 dir=$2
  mkdir -p "${dir}"
  local parts=(unit)
  [[ -d "$(results_dir "${side}")/downstream" ]] && parts+=(downstream)
  tar -C "$(results_dir "${side}")" -czf "${dir}/unit-${side}.tar.gz" "${parts[@]}"
}

unpack_results() {
  local dir f side
  for dir in "$@"; do
    for f in "${dir}"/e2e-*.tar.gz "${dir}"/unit-*.tar.gz; do
      [[ -f "${f}" ]] || continue
      # e2e-<side>-<arch>.tar.gz or unit-<side>.tar.gz
      side=$(basename "${f}" .tar.gz | cut -d- -f2)
      check_side "${side}"
      mkdir -p "$(results_dir "${side}")"
      tar -C "$(results_dir "${side}")" -xzf "${f}"
    done
  done
}

cmd=${1:-}
shift || true
case "${cmd}" in
  pack-build) pack_build "$@" ;;
  unpack-build) unpack_build "$@" ;;
  reuse-build) reuse_build "$@" ;;
  pack-e2e) pack_e2e "$@" ;;
  pack-unit) pack_unit "$@" ;;
  unpack-results) unpack_results "$@" ;;
  *) die "usage: $0 pack-build|unpack-build|reuse-build|pack-e2e|pack-unit|unpack-results ..." ;;
esac
