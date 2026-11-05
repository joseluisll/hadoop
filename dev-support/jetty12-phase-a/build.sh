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

# Usage: build.sh <baseline|candidate> [dist|install|worktree]
#
# Checks out the side's ref in its own git worktree and builds it.
#   dist     (default) the binary distribution, every module's resolved
#            dependencies, and the Hadoop test code the end-to-end runs reuse
#   install  only "mvn install" without tests, enough for unit-tests.sh
#   worktree only the checkout, when CI restored the side's installed
#            artifacts from its cache (ci/build-key.sh)
#
# BUILD_NATIVE=true adds the native libraries to the distribution (-Pnative,
# failing when OpenSSL or Snappy support cannot be built). It needs the
# native toolchain of Hadoop's build image (dev-support/docker), which the CI
# build jobs run in.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

SIDE="${1:-}"
check_side "${SIDE}"
MODE="${2:-dist}"
[[ "${MODE}" =~ ^(dist|install|worktree)$ ]] || die "mode must be dist, install or worktree"
LOG_TAG="build:${SIDE}"
require_cmd git java

REF=$(ref_for_side "${SIDE}")
SRC=$(src_dir "${SIDE}")
OUT=$(results_dir "${SIDE}")/build
mkdir -p "${OUT}" "$(side_dir "${SIDE}")"

if [[ ! -d "${SRC}/.git" && ! -f "${SRC}/.git" ]]; then
  log "creating worktree for ${REF} at ${SRC}"
  git -C "${REPO_DIR}" worktree add --detach "${SRC}" "${REF}"
else
  # A reused worktree must still build ${REF}: the branch may have moved.
  log "reusing worktree ${SRC}, checking out ${REF}"
  git -C "${SRC}" checkout -q --detach "${REF}" || die "cannot check out ${REF} in ${SRC}"
fi
git -C "${SRC}" rev-parse HEAD > "${OUT}/commit.txt"
git -C "${SRC}" log -1 --format='%H %s' > "${OUT}/commit-subject.txt"
if [[ "${MODE}" == worktree ]]; then
  log "checked out $(cat "${OUT}/commit-subject.txt"); not building"
  exit 0
fi
log "building $(cat "${OUT}/commit-subject.txt")"

if [[ "${MODE}" == install ]]; then
  log "mvn install (no tests); log: ${OUT}/mvn-install.log"
  mvn_logged "${SIDE}" "${OUT}/mvn-install.log" install -DskipTests -Dmaven.javadoc.skip=true \
    || die "build failed; see ${OUT}/mvn-install.log"
  exit 0
fi

native=()
[[ "${BUILD_NATIVE:-false}" == true ]] && native=(-Pnative -Drequire.openssl -Drequire.snappy)
log "mvn install -Pdist ${native[*]} (no tests); log: ${OUT}/mvn-install.log"
mvn_logged "${SIDE}" "${OUT}/mvn-install.log" install -Pdist "${native[@]}" -Dtar -DskipTests -Dmaven.javadoc.skip=true \
  || die "build failed; see ${OUT}/mvn-install.log"

# Resolved dependencies of every module, all scopes.
log "recording resolved dependencies; log: ${OUT}/mvn-dependency-list.log"
find "${SRC}" -name jetty12-deps.txt -path '*/target/*' -delete
mvn_logged "${SIDE}" "${OUT}/mvn-dependency-list.log" -nsu dependency:list -Dmdep.outputScope=true \
  -Dmdep.includeParents=false -DoutputFile=target/jetty12-deps.txt -Dsort=true \
  || die "dependency:list failed; see ${OUT}/mvn-dependency-list.log"

# One file, one line per "module<TAB>group:artifact:type[:classifier]:version:scope".
python3 -I "${HARNESS_DIR}/lib/collect_deps.py" "${SRC}" > "${OUT}/dependencies.tsv"
log "dependencies of $(cut -f1 "${OUT}/dependencies.tsv" | sort -u | wc -l) modules recorded"

dist=$(dist_dir "${SIDE}")
echo "${dist}" > "${OUT}/dist-path.txt"
log "distribution: ${dist}"

# Test code of Hadoop the end-to-end runs reuse, next to the distribution:
# hadoop-minikdc (the KDC of the secure architecture) with its runtime
# dependencies, and the timeline service test jar (file system storage for
# the timeline reader).
TOOLS="$(side_dir "${SIDE}")/tools"
rm -rf "${TOOLS}"
mkdir -p "${TOOLS}/minikdc" "${TOOLS}/timelineservice-tests"
mvn_logged "${SIDE}" "${OUT}/mvn-tools.log" -nsu dependency:copy-dependencies \
  -pl hadoop-common-project/hadoop-minikdc -DincludeScope=runtime -DoutputDirectory="${TOOLS}/minikdc" \
  || die "cannot stage MiniKdc; see ${OUT}/mvn-tools.log"
cp "${SRC}"/hadoop-common-project/hadoop-minikdc/target/hadoop-minikdc-*[0-9T].jar "${TOOLS}/minikdc/"
cp "${SRC}"/hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice/target/hadoop-yarn-server-timelineservice-*-tests.jar \
  "${TOOLS}/timelineservice-tests/"
log "tools staged in ${TOOLS}: $(ls "${TOOLS}/minikdc" | wc -l) MiniKdc jars"
