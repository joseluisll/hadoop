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

# Shared settings and helpers for the Jetty 12 phase A harness.
# Sourced by every script in this directory; not meant to be run.

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "${HARNESS_DIR}/../.." && pwd)"

# Everything the harness produces (worktrees, builds, cluster data, results)
# goes under WORKDIR, never into the source tree.
WORKDIR="${WORKDIR:-${HOME}/jetty12-phase-a-work}"

# The two trees being compared. BASELINE is the PR base without the patch,
# CANDIDATE is the phase A patch.
BASELINE_REF="${BASELINE_REF:-origin/PREPARATION}"
CANDIDATE_REF="${CANDIDATE_REF:-origin/HADOOP-99999}"

# Extra arguments for every Maven invocation, e.g. "-o" or "-Dmaven.repo.local=...".
MVN_EXTRA_ARGS="${MVN_EXTRA_ARGS:-}"

log() {
  printf '%s [%s] %s\n' "$(date -u +%H:%M:%S)" "${LOG_TAG:-harness}" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

# side_dir <baseline|candidate>
side_dir() {
  echo "${WORKDIR}/$1"
}

# src_dir <side>: the git worktree of that side. BUILD_SRC_DIR replaces it
# where only one side is built (a CI build job): the native libraries embed
# their source paths, so both sides must be built at the same path to come
# out identical.
src_dir() {
  echo "${BUILD_SRC_DIR:-${WORKDIR}/$1/src}"
}

# dist_dir <side>: the unpacked hadoop-<version> distribution of that side,
# from its build, or unpacked under <side>/dist (CI jobs that only download
# the tarball).
dist_dir() {
  local d where=()
  # Only existing directories: find fails on a missing one, which set -e
  # with pipefail turns into a silent exit (CI unpacks the distribution
  # where there is no build tree).
  for d in "$(side_dir "$1")/dist" "$(src_dir "$1")/hadoop-dist/target"; do
    [[ -d "${d}" ]] && where+=("${d}")
  done
  d=""
  if [[ ${#where[@]} -gt 0 ]]; then
    d=$(find "${where[@]}" -maxdepth 1 -type d -name 'hadoop-[0-9]*' | head -1) || true
  fi
  [[ -n "${d}" ]] || die "no hadoop distribution built for $1; run build.sh $1 first"
  echo "${d}"
}

# results_dir <side>: where that side's phase results are written.
results_dir() {
  echo "${WORKDIR}/results/$1"
}

check_side() {
  case "$1" in
    baseline|candidate) ;;
    *) die "side must be 'baseline' or 'candidate', got '$1'" ;;
  esac
}

ref_for_side() {
  if [[ "$1" == baseline ]]; then echo "${BASELINE_REF}"; else echo "${CANDIDATE_REF}"; fi
}

# Optional mirror of Maven Central, e.g.
# https://maven-central.storage-download.googleapis.com/maven2
# when repo.maven.apache.org rate-limits the build host.
MAVEN_MIRROR_URL="${MAVEN_MIRROR_URL:-}"

# mvn_side <side> <args...>: the side's Maven wrapper, run in its worktree.
#
# Both sides share one Maven repository for downloads but install their own
# artifacts under separate prefixes, so a "-pl <module>" run on one side never
# resolves the other side's SNAPSHOT jars.
mvn_side() {
  local side=$1
  shift
  local settings=()
  if [[ -n "${MAVEN_MIRROR_URL}" ]]; then
    local f="${WORKDIR}/maven-settings.xml"
    cat > "${f}" <<EOF
<settings>
  <mirrors>
    <mirror>
      <id>central-mirror</id>
      <mirrorOf>central</mirrorOf>
      <url>${MAVEN_MIRROR_URL}</url>
    </mirror>
  </mirrors>
</settings>
EOF
    settings=(-s "${f}")
    export MVNW_REPOURL="${MAVEN_MIRROR_URL}"
    # mvnw downloads its own jar from the wrapperUrl pinned in
    # maven-wrapper.properties, ignoring MVNW_REPOURL. Fetch it from the
    # mirror instead; mvnw still checks it against wrapperSha256Sum.
    local jar
    jar="$(src_dir "${side}")/.mvn/wrapper/maven-wrapper.jar"
    if [[ ! -s "${jar}" ]]; then
      local url
      url=$(sed -n 's/^wrapperUrl=//p' "$(src_dir "${side}")/.mvn/wrapper/maven-wrapper.properties")
      curl -sSfL -o "${jar}" "${MAVEN_MIRROR_URL}/${url#*/maven2/}" \
        || die "cannot download the Maven wrapper jar from ${MAVEN_MIRROR_URL}"
    fi
  fi
  # The resolver's HTTP retries (Maven Resolver 1.9 property names) cover
  # failed connections and 429/5xx answers; mvn_logged below covers what they
  # do not, such as a download cut off part way.
  # shellcheck disable=SC2086
  (cd "$(src_dir "${side}")" && ./mvnw -B -ntp "${settings[@]}" \
      -Dmaven.repo.local="${M2_REPO:-${WORKDIR}/m2}" \
      -Daether.enhancedLocalRepository.split=true \
      -Daether.enhancedLocalRepository.localPrefix="installed-${side}" \
      -Daether.connector.http.retryHandler.count=5 \
      -Daether.connector.http.retryHandler.interval=5000 \
      -Daether.connector.http.retryHandler.intervalMax=60000 \
      -Daether.connector.http.retryHandler.serviceUnavailable=429,502,503,504 \
      ${MVN_EXTRA_ARGS} "$@")
}

# Lines of a Maven log that blame the network, not the build.
MVN_TRANSFER_ERROR='^\[ERROR\].*(Could not transfer|Premature end of Content-Length|Connection reset|Connection refused|timed out|status code: (429|5[0-9][0-9])|Remote host terminated)'

# mvn_logged <side> <log> <args...>: mvn_side with its output in <log>. When
# Maven fails on a download (MVN_TRANSFER_ERROR), runs it again, up to
# MVN_ATTEMPTS times in all, resuming from the module that failed; earlier
# attempts are kept as <log>.attempt-N.
mvn_logged() {
  local side=$1 logf=$2
  shift 2
  local attempt=1 max=${MVN_ATTEMPTS:-3} rc resume=()
  while true; do
    rc=0
    mvn_side "${side}" "$@" "${resume[@]}" > "${logf}" 2>&1 || rc=$?
    (( rc == 0 )) && return 0
    if (( attempt >= max )) || ! grep -Eq "${MVN_TRANSFER_ERROR}" "${logf}"; then
      return "${rc}"
    fi
    local module
    module=$(grep -oE -- '-rf :[A-Za-z0-9._-]+' "${logf}" | tail -1 | cut -c6-) || true
    resume=()
    [[ -n "${module}" ]] && resume=(-rf ":${module}")
    log "maven attempt ${attempt} failed on a download ($(grep -Em1 "${MVN_TRANSFER_ERROR}" "${logf}" | cut -c1-160)); retrying${module:+ from ${module}} in $((attempt * 30))s"
    mv "${logf}" "${logf}.attempt-${attempt}"
    sleep $((attempt * 30))
    attempt=$((attempt + 1))
  done
}

require_cmd() {
  local c
  for c in "$@"; do
    command -v "${c}" >/dev/null 2>&1 || die "required command not found: ${c}"
  done
}
