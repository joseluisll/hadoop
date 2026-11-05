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

# Usage: ci/history.sh <owner/repo> <workflow file name> <arch> <dest dir>
#
# Downloads the report-<arch> artifact of up to five earlier completed runs of
# the workflow, other than the current one, into <dest dir>/<run id>. Only
# normal runs (branch jetty12-phase-a-<arch>-run-<N>) count, not aa or broken
# ones. It
# reads them with lib/compare_unit.py --history (R85). A run without the
# artifact is skipped; the script always exits 0, so a missing history never
# stops a comparison.
#
# GH_TOKEN, when set, authenticates the gh calls (actions: read).

set -uo pipefail
repo=$1
workflow=$2
arch=$3
dest=$4

runs=$(gh run list -R "${repo}" --workflow "${workflow}" --status completed --limit 30 \
       --json databaseId,headBranch 2>/dev/null \
       | python3 -I -c '
import json, re, sys, os
me = os.environ.get("GITHUB_RUN_ID", "")
# Normal runs only: an aa or broken run fails tests on purpose.
normal = re.compile(r"jetty12-phase-a-" + re.escape(sys.argv[1]) + r"-run-[0-9]+$")
for r in json.load(sys.stdin):
    if str(r["databaseId"]) != me and normal.match(r["headBranch"] or ""):
        print(r["databaseId"])
' "${arch}" 2>/dev/null | head -5)

for id in ${runs}; do
  dir="${dest}/${id}"
  if gh run download "${id}" -R "${repo}" -n "report-${arch}" -D "${dir}" 2>/dev/null; then
    echo "history: downloaded ${id} into ${dir}"
  else
    echo "history: run ${id} has no report-${arch} artifact; skipped"
  fi
done
exit 0
