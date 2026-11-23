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
# version there although nothing changes inside Hadoop. One small project per
# Hadoop artifact and scenario:
#   plain                the Hadoop artifact alone;
#   older-jetty          the Hadoop artifact, then a Jetty client of another
#                        version (DOWNSTREAM_JETTY_CLIENT), which brings its
#                        own jetty-http and jetty-io one level down;
#   own-javax-servlet    the Hadoop artifact, then its own servlet API under
#                        the javax.servlet coordinate (DOWNSTREAM_JAVAX_SERVLET,
#                        as HBase declares it);
#   own-jakarta-servlet  the same under the jakarta.servlet coordinate
#                        (DOWNSTREAM_JAKARTA_SERVLET, as Spark and Hive).
# Maven mediates versions of one coordinate only: when Hadoop brings the same
# classes under another coordinate, both jars end up on the classpath. So each
# project also records its classpath, and lib/downstream_classes.py writes the
# classes more than one jar provides to results/<side>/downstream/duplicates.tsv.
# It then compiles lib/DownstreamSmoke.java and runs, per project, the steps
# its classpath supports (an HttpServer2, a MiniDFSCluster and MiniYARNCluster,
# a JerseyTest), writing results/<side>/downstream/smoke.tsv (T26).
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
# The extra dependency each scenario declares after the Hadoop artifact.
declare -A EXTRA=(
  [plain]=""
  [older-jetty]="${COMPETITOR}"
  [own-javax-servlet]="${DOWNSTREAM_JAVAX_SERVLET:-javax.servlet:javax.servlet-api:3.1.0}"
  [own-jakarta-servlet]="${DOWNSTREAM_JAKARTA_SERVLET:-jakarta.servlet:jakarta.servlet-api:4.0.4}"
)
SCENARIOS=(plain older-jetty own-javax-servlet own-jakarta-servlet)
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
modules=""
for scenario in "${SCENARIOS[@]}"; do
  for entry in "${ARTIFACTS[@]}"; do
    artifact=${entry%%:*} scope=compile
    [[ "${entry}" == *:* ]] && scope=${entry#*:}
    deps=$(dep org.apache.hadoop "${artifact}" "${version}" "${scope}")
    if [[ -n "${EXTRA[${scenario}]}" ]]; then
      IFS=: read -r eg ea ev <<< "${EXTRA[${scenario}]}"
      deps+=$'\n'$(dep "${eg}" "${ea}" "${ev}" compile)
    fi
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
  for scenario in "${SCENARIOS[@]}"; do
    echo "scenario ${scenario} ${EXTRA[${scenario}]:-(none)}"
  done
  printf 'artifact %s\n' "${ARTIFACTS[@]}"
} > "${OUT}/scenarios.txt"

log "resolving ${#ARTIFACTS[@]} Hadoop ${version} artifacts in ${#SCENARIOS[@]} scenarios; log: ${OUT}/mvn-dependency-list.log"
# -nsu: the side's installed SNAPSHOT jars, never remote ones.
mvn_logged "${SIDE}" "${OUT}/mvn-dependency-list.log" -nsu -f "${PROJ}/pom.xml" \
  "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:list" \
  "org.apache.maven.plugins:maven-dependency-plugin:3.8.1:build-classpath" \
  -Dmdep.outputScope=true -DoutputFile=target/jetty12-deps.txt -Dsort=true \
  -Dmdep.outputFile=target/jetty12-cp.txt \
  || die "dependency:list failed; see ${OUT}/mvn-dependency-list.log"
python3 -I "${HARNESS_DIR}/lib/collect_deps.py" "${PROJ}" > "${OUT}/dependencies.tsv"
log "$(wc -l < "${OUT}/dependencies.tsv") resolved dependencies in ${OUT}/dependencies.tsv"
python3 -I "${HARNESS_DIR}/lib/downstream_classes.py" "${PROJ}" "${M2_REPO:-${WORKDIR}/m2}" \
  > "${OUT}/duplicates.tsv"
log "$(wc -l < "${OUT}/duplicates.tsv") packages with classes from more than one jar in ${OUT}/duplicates.tsv"

# T26: compile and run one small program against each project's classpath.
# The one source names every step, so it is compiled against the union of the
# projects' classpaths (which has all of them) and run against each project's
# own; a step whose classes are absent is not started.
SMOKE="${OUT}/smoke.tsv"
: > "${SMOKE}"
SMOKE_CLASSES="${OUT}/smoke-classes"
rm -rf "${SMOKE_CLASSES}"
mkdir -p "${SMOKE_CLASSES}"
ALL_CP=""
while IFS= read -r cpfile; do
  ALL_CP+=$(cat "${cpfile}")":"
done < <(find "${PROJ}" -name jetty12-cp.txt | sort)
if [[ -n "${ALL_CP}" ]]; then
  javac -d "${SMOKE_CLASSES}" -cp "${ALL_CP}" "${HARNESS_DIR}/lib/DownstreamSmoke.java" \
    > "${OUT}/smoke-javac.log" 2>&1 \
    || log "smoke: javac failed; see ${OUT}/smoke-javac.log"
fi

smoke() {
  local project=$1 cp=$2 scenario=${1%%/*} artifact=${1#*/}
  local webapps="${OUT}/smoke-webapps"
  mkdir -p "${webapps}/webapps/smoke"
  local steps step out ok version jar detail
  steps=$(python3 -I - "${cp}" <<'EOF'
import sys
import zipfile
cp = sys.argv[1]
want = {
    "httpserver2": ["org/apache/hadoop/http/HttpServer2.class"],
    "minicluster": ["org/apache/hadoop/hdfs/MiniDFSCluster.class",
                    "org/apache/hadoop/yarn/server/MiniYARNCluster.class"],
    "jerseytest": ["org/apache/hadoop/shaded/org/glassfish/jersey/test/JerseyTest.class",
                   "org/apache/hadoop/shaded/javax/ws/rs/GET.class"],
}
names = set()
for jar in cp.split(":"):
    try:
        with zipfile.ZipFile(jar) as z:
            names |= set(z.namelist())
    except (OSError, zipfile.BadZipFile):
        continue
found = [step for step, entries in want.items() if all(e in names for e in entries)]
print(" ".join(s for s in ("httpserver2", "minicluster", "jerseytest") if s in found))
EOF
)
  for step in ${steps}; do
    out=$(timeout 300 java -cp "${SMOKE_CLASSES}:${webapps}:${cp}" DownstreamSmoke "${step}" \
      2>> "${OUT}/smoke-${scenario}-${artifact}-${step}.log") || true
    IFS=$'\t' read -r ok version jar detail <<< "${out}"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${scenario}" "${artifact}" "${step}" \
      "${ok:-fail}" "${version:-}" "${jar:-}" "${detail:-no output}" >> "${SMOKE}"
  done
}

if [[ -f "${SMOKE_CLASSES}/DownstreamSmoke.class" ]]; then
  while IFS= read -r cpfile; do
    project=$(dirname "$(dirname "${cpfile}")")
    project=${project#"${PROJ}/"}
    smoke "${project}" "$(cat "${cpfile}")"
  done < <(find "${PROJ}" -name jetty12-cp.txt | sort)
fi
log "$(wc -l < "${SMOKE}") smoke steps in ${SMOKE}"
