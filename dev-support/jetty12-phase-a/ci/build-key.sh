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

# Usage: ci/build-key.sh <side> <dist|install>
#
# Prints the CI cache key of a side's build, so a run reuses a build of the
# same code instead of compiling it again: most runs change only the harness,
# and the baseline is the same commit every time. The key covers
#   - every file of the side's tree except the harness and .github, by blob id;
#   - the harness files that shape what the build produces;
#   - the JDK.
# Anything else that changes the build output must be added here, or a run
# would test a stale build.

set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
side=$1
kind=$2
check_side "${side}"
case "${kind}" in
  dist) shaping=(build.sh lib/common.sh lib/collect_deps.py ci/artifacts.sh ci/build-key.sh) ;;
  install) shaping=(build.sh lib/common.sh ci/build-key.sh) ;;
  *) die "kind must be dist or install, got '${kind}'" ;;
esac

ref=$(ref_for_side "${side}")
tree=$(git -C "${REPO_DIR}" ls-tree -r "${ref}" \
  | grep -vE $'\t(dev-support/jetty12-phase-a/|\\.github/)' | sha256sum | cut -c1-16)
harness=$(cd "${HARNESS_DIR}" && cat "${shaping[@]}" | sha256sum | cut -c1-8)
jdk=$(java -version 2>&1 | head -1 | sha256sum | cut -c1-6)
echo "jetty12-phase-a-${kind}-${side}-${tree}-${harness}-${jdk}"
