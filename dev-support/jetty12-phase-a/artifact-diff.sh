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

# Usage: artifact-diff.sh [baseline-side] [candidate-side]
#
# Compares the two built distributions and dependency lists (see
# lib/artifact_diff.py), then the API of every class that changes between
# them (lib/api_compat.py). Both sides must have been built with build.sh.
# The sides default to baseline and candidate; passing "candidate candidate"
# self-compares one build, which must report no differences.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
LOG_TAG="artifact-diff"
require_cmd java python3

B_SIDE="${1:-baseline}"
C_SIDE="${2:-candidate}"
check_side "${B_SIDE}"
check_side "${C_SIDE}"

# record_classpaths <side>: the expanded classpath of every launcher command.
record_classpaths() {
  local side=$1 dist out
  dist=$(dist_dir "${side}")
  out="$(results_dir "${side}")/classpath"
  mkdir -p "${out}"
  export JAVA_HOME="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}"
  (
    unset HADOOP_HOME HADOOP_CONF_DIR HADOOP_CLASSPATH HADOOP_OPTIONAL_TOOLS
    "${dist}/bin/hadoop" classpath --glob > "${out}/hadoop.txt"
    "${dist}/bin/hdfs" classpath --glob > "${out}/hdfs.txt"
    "${dist}/bin/yarn" classpath --glob > "${out}/yarn.txt"
    "${dist}/bin/mapred" classpath --glob > "${out}/mapred.txt"
    # Tools (distcp, streaming, archives, sls, ...) run with share/hadoop/tools
    # added to the mapred classpath.
    { cat "${out}/mapred.txt"
      find "${dist}/share/hadoop/tools" -name '*.jar' | sort | sed 's/^/:/' | tr -d '\n'
    } > "${out}/tools.txt"
    # The timeline reader adds share/hadoop/yarn/timelineservice.
    { cat "${out}/yarn.txt"
      find "${dist}/share/hadoop/yarn/timelineservice" -name '*.jar' | sort | sed 's/^/:/' | tr -d '\n'
    } > "${out}/yarn-timelinereader.txt"
    # Downstream applications use the shaded client jars instead.
    find "${dist}/share/hadoop/client" -name 'hadoop-client-api-*.jar' \
      -o -name 'hadoop-client-runtime-*.jar' | sort | paste -sd: > "${out}/client.txt"
    find "${dist}/share/hadoop/client" -name 'hadoop-client-*.jar' | sort \
      | paste -sd: > "${out}/client-minicluster.txt"
  )
  log "${side}: classpaths recorded in ${out}"
}

record_classpaths "${B_SIDE}"
[[ "${C_SIDE}" == "${B_SIDE}" ]] || record_classpaths "${C_SIDE}"

OUT="${WORKDIR}/results/compare"
mkdir -p "${OUT}"
set +e
python3 -I "${HARNESS_DIR}/lib/artifact_diff.py" \
  --expected "${HARNESS_DIR}/expected-differences.txt" --out "${OUT}" \
  "$(results_dir "${B_SIDE}")" "$(results_dir "${C_SIDE}")"
rc=$?
# What the changed classes mean for code built against the old ones.
python3 -I "${HARNESS_DIR}/lib/api_compat.py" \
  --expected "${HARNESS_DIR}/expected-api-differences.txt" --out "${OUT}" \
  "$(results_dir "${B_SIDE}")" "$(results_dir "${C_SIDE}")" || rc=1
set -e
log "report: ${OUT}/artifact-diff.md, ${OUT}/api-compat.md"
exit "${rc}"
