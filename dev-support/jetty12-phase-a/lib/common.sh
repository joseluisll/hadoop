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

# src_dir <side>: the git worktree of that side.
src_dir() {
  echo "${WORKDIR}/$1/src"
}

# dist_dir <side>: the unpacked hadoop-<version> distribution of that side.
dist_dir() {
  local d
  d=$(find "$(src_dir "$1")/hadoop-dist/target" -maxdepth 1 -type d \
      -name 'hadoop-[0-9]*' 2>/dev/null | head -1)
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
  # shellcheck disable=SC2086
  (cd "$(src_dir "${side}")" && ./mvnw -B -ntp "${settings[@]}" \
      -Dmaven.repo.local="${M2_REPO:-${WORKDIR}/m2}" \
      -Daether.enhancedLocalRepository.split=true \
      -Daether.enhancedLocalRepository.localPrefix="installed-${side}" \
      ${MVN_EXTRA_ARGS} "$@")
}

require_cmd() {
  local c
  for c in "$@"; do
    command -v "${c}" >/dev/null 2>&1 || die "required command not found: ${c}"
  done
}
