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

# Usage: replay.sh [compare dir ...]
#
# Replays every rule file against the comparisons already written (lib/replay.py,
# R66): each rule is matched the way its comparison matches it, so a new or
# edited rule can be tried against the latest report of every architecture
# without a build or a run. With no argument it uses this machine's
# results/compare. Exits 1 when a rule matches nothing in any directory, which
# is the rule a run would report as unused (R59).
#
# A directory is what a comparison leaves behind: results/compare here, or a
# downloaded report-<arch> artifact. In CI, download every architecture's
# report artifact and replay against all of them:
#
#   gh run download <run id> -p 'report-*' -D /tmp/reports
#   dev-support/jetty12-phase-a/replay.sh /tmp/reports/report-*

set -uo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="replay"
require_cmd python3

dirs=("$@")
if [[ ${#dirs[@]} -eq 0 ]]; then
  dirs=("${WORKDIR}/results/compare")
fi
for d in "${dirs[@]}"; do
  [[ -d "${d}" ]] || die "no such compare directory: ${d}"
done
python3 -I "${HARNESS_DIR}/lib/replay.py" "${dirs[@]}"
