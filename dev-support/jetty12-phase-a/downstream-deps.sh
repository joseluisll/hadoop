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

# Usage: downstream-deps.sh <baseline|candidate>
#
# Resolves the side's installed Hadoop artifacts the way a downstream Maven
# project sees them, and writes what it gets to
# results/<side>/downstream/dependencies.tsv (lib/compare_downstream.py
# compares the two sides). Each Hadoop module's own resolved dependencies are
# compared by artifact-diff.sh, but a downstream project mediates them with
# its own: declaring a jar directly in a Hadoop pom moves it nearer to the
# downstream project, and Maven's nearest-wins rule can then pick another
# version there although nothing changes inside Hadoop. Two scenarios, one
# small project per Hadoop artifact and scenario:
#   plain        the Hadoop artifact alone;
#   older-jetty  the Hadoop artifact, then a Jetty client of another
#                version (DOWNSTREAM_JETTY_CLIENT), which brings its own
#                jetty-http and jetty-io one level down.
# Needs the side's artifacts installed (build.sh <side> install, or restored
# from a saved build) and Maven Central for the third-party ones.

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
SIDE=${1:-}
check_side "${SIDE}"
LOG_TAG="downstream:${SIDE}"
require_cmd python3

SRC=$(src_dir "${SIDE}")
OUT=$(results_dir "${SIDE}")/downstream
PROJ=$(side_dir "${SIDE}")/downstream-project
COMPETITOR=${DOWNSTREAM_JETTY_CLIENT:-org.eclipse.jetty:jetty-client:9.4.40.v20210413}
# <artifactId>[:<scope>], the Hadoop artifacts downstream projects use.
ARTIFACTS=(
  hadoop-common hadoop-hdfs-client hadoop-hdfs
  hadoop-mapreduce-client-core hadoop-mapreduce-client-jobclient hadoop-mapreduce-client-shuffle
  hadoop-yarn-api hadoop-yarn-common hadoop-yarn-client
  hadoop-client hadoop-client-api hadoop-client-runtime
  hadoop-minicluster:test hadoop-client-minicluster:test
)

[[ -f "${SRC}/pom.xml" ]] || die "no source tree at ${SRC}; run build.sh ${SIDE} first"
version=$(python3 -I - "${SRC}/pom.xml" <<'EOF'
import sys
import xml.etree.ElementTree as ET
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
print(ET.parse(sys.argv[1]).getroot().find("m:version", ns).text)
EOF
)

dep() {
  local g=$1 a=$2 v=$3 scope=$4
  printf '    <dependency><groupId>%s</groupId><artifactId>%s</artifactId><version>%s</version><scope>%s</scope></dependency>\n' \
    "${g}" "${a}" "${v}" "${scope}"
}

pom() {
  local id=$1 packaging=$2 body=$3
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>jetty12.phasea.downstream</groupId>
  <artifactId>${id}</artifactId>
  <version>1</version>
  <packaging>${packaging}</packaging>
${body}
</project>
EOF
}

rm -rf "${PROJ}" "${OUT}"
mkdir -p "${PROJ}" "${OUT}"
IFS=: read -r cg ca cv <<< "${COMPETITOR}"
modules=""
for scenario in plain older-jetty; do
  for entry in "${ARTIFACTS[@]}"; do
    artifact=${entry%%:*} scope=compile
    [[ "${entry}" == *:* ]] && scope=${entry#*:}
    deps=$(dep org.apache.hadoop "${artifact}" "${version}" "${scope}")
    [[ "${scenario}" == older-jetty ]] && deps+=$'\n'$(dep "${cg}" "${ca}" "${cv}" compile)
    mkdir -p "${PROJ}/${scenario}/${artifact}"
    pom "${scenario}-${artifact}" pom "  <dependencies>
${deps}
  </dependencies>" > "${PROJ}/${scenario}/${artifact}/pom.xml"
    modules+="    <module>${scenario}/${artifact}</module>"$'\n'
  done
done
pom aggregator pom "  <modules>
${modules}  </modules>" > "${PROJ}/pom.xml"
{
  echo "hadoop ${version}"
  echo "older-jetty competitor ${COMPETITOR}"
  printf 'artifact %s\n' "${ARTIFACTS[@]}"
} > "${OUT}/scenarios.txt"

log "resolving ${#ARTIFACTS[@]} Hadoop ${version} artifacts in 2 scenarios; log: ${OUT}/mvn-dependency-list.log"
# -nsu: the side's installed SNAPSHOT jars, never remote ones.
mvn_logged "${SIDE}" "${OUT}/mvn-dependency-list.log" -nsu -f "${PROJ}/pom.xml" \
  "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:list" \
  -Dmdep.outputScope=true -DoutputFile=target/jetty12-deps.txt -Dsort=true \
  || die "dependency:list failed; see ${OUT}/mvn-dependency-list.log"
python3 -I "${HARNESS_DIR}/lib/collect_deps.py" "${PROJ}" > "${OUT}/dependencies.tsv"
log "$(wc -l < "${OUT}/dependencies.tsv") resolved dependencies in ${OUT}/dependencies.tsv"
