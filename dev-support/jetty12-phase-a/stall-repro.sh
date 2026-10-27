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

# Usage: stall-repro.sh <baseline|candidate>
#
# Tries to reproduce the loopback HDFS read stall seen once in Hadoop's CI:
# TestMRIntermediateDataEncryption's last case, normally 9 s, took 1857 s
# because one 32 MB block crawled from the datanode to the map task at about
# 18 KB/s, both ends waiting on the socket (MAPREDUCE-7099 is the same
# symptom). Not about phase A: any side will do.
#
# Runs that test class again and again for STALL_REPRO_MINUTES (default
# 270), or until STALL_REPRO_STOP_AFTER stalls (default 2). A run whose
# slowest test case takes more than STALL_REPRO_SLOW_CASE seconds (default
# 60) is a stall. lib/stall-watch.sh watches every run from 150 s on, every
# 30 s, with loopback packet captures (STALL_TCPDUMP), so a stall leaves the
# kernel's view of its sockets behind.
#
# STALL_REPRO_VARIANT picks how the test runs:
#   plain          as in Hadoop's CI without native libraries (default)
#   short-circuit  with HDFS short-circuit local reads: the datanode hands
#                  the map task the block files through a UNIX domain socket,
#                  so input reads never cross TCP. Builds hadoop-common's
#                  native library (libhadoop, which surefire finds in that
#                  module's target directory) and adds
#                  dfs.client.read.shortcircuit and dfs.domain.socket.path to
#                  jobclient's test hdfs-site.xml in the side's worktree. Each
#                  run counts the datanode's "REQUEST_SHORT_CIRCUIT_FDS ...
#                  success: true" log lines, and the script stops if the first
#                  run has none: a fallback to TCP must not pass as a result.
#
# Writes results/<side>/stall-repro/:
#   iterations.tsv  one line per run: seconds, maven exit, slowest case,
#                   short-circuit reads
#   summary.md      runs, stalls, slowest times
#   iter-<n>/       for a stall only: maven log, surefire reports and test
#                   output, and the watcher's snapshots (stalls/)

set -euo pipefail
source "$(dirname "$0")/lib/common.sh"
SIDE=${1:-}
check_side "${SIDE}"
LOG_TAG="stall-repro:${SIDE}"
require_cmd python3

MODULE=hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-jobclient
TEST=org/apache/hadoop/mapreduce/TestMRIntermediateDataEncryption.java
MINUTES=${STALL_REPRO_MINUTES:-270}
STOP_AFTER=${STALL_REPRO_STOP_AFTER:-2}
SLOW=${STALL_REPRO_SLOW_CASE:-60}
VARIANT=${STALL_REPRO_VARIANT:-plain}
[[ "${VARIANT}" =~ ^(plain|short-circuit)$ ]] || die "STALL_REPRO_VARIANT must be plain or short-circuit"
export STALL_AFTER=${STALL_AFTER:-150} STALL_REPEAT=${STALL_REPEAT:-30}
export STALL_SNAPSHOTS=${STALL_SNAPSHOTS:-30} STALL_TCPDUMP=${STALL_TCPDUMP:-1}

SRC=$(src_dir "${SIDE}")
[[ -d "${SRC}" ]] || die "run build.sh ${SIDE} first"
TARGET="${SRC}/${MODULE}/target"
OUT=$(results_dir "${SIDE}")/stall-repro
rm -rf "${OUT}"
mkdir -p "${OUT}"
printf 'iteration\tstarted\tseconds\tmaven_exit\tslowest_case_s\tslowest_case\tstall\tscr_reads\n' > "${OUT}/iterations.tsv"

if [[ "${VARIANT}" == short-circuit ]]; then
  log "building hadoop-common's native library; log: ${OUT}/mvn-native.log"
  mvn_logged "${SIDE}" "${OUT}/mvn-native.log" -nsu compile -pl hadoop-common-project/hadoop-common \
    -Pnative -Dmaven.javadoc.skip=true -Dspotbugs.skip=true -Dcheckstyle.skip=true \
    || die "native build failed; see ${OUT}/mvn-native.log"
  lib="${SRC}/hadoop-common-project/hadoop-common/target/native/target/usr/local/lib/libhadoop.so"
  [[ -e "${lib}" ]] || die "no ${lib} after the native build"
  # A UNIX socket path must stay short (108 bytes), and DomainSocket refuses
  # one whose directories others can write to.
  sockdir="${WORKDIR}/scr"
  mkdir -p "${sockdir}"
  chmod 755 "${sockdir}"
  site="${SRC}/${MODULE}/src/test/resources/hdfs-site.xml"
  python3 -I - "${site}" "${sockdir}/dn._PORT.sock" <<'EOF'
import sys
path, sock = sys.argv[1], sys.argv[2]
text = open(path).read()
props = (f"  <property><name>dfs.client.read.shortcircuit</name><value>true</value></property>\n"
         f"  <property><name>dfs.domain.socket.path</name><value>{sock}</value></property>\n")
open(path, "w").write(text.replace("</configuration>", props + "</configuration>"))
EOF
  log "short-circuit reads on: ${lib}, socket ${sockdir}/dn._PORT.sock"
fi

# Short-circuit reads the datanode granted during the last run.
scr_reads() {
  cat "${TARGET}"/surefire-reports/*-output.txt 2>/dev/null \
    | grep -c 'op: REQUEST_SHORT_CIRCUIT_FDS.*success: true' || true
}

# "<seconds> <name>" of the slowest test case in the surefire reports, or
# "-1 none" without reports.
slowest_case() {
  python3 -I - "${TARGET}/surefire-reports" <<'EOF'
import glob, os, sys
import xml.etree.ElementTree as ET
best = (-1.0, "none")
for f in glob.glob(os.path.join(sys.argv[1], "TEST-*.xml")):
    try:
        cases = list(ET.parse(f).getroot().iter("testcase"))
    except ET.ParseError:
        continue
    for case in cases:
        best = max(best, (float(case.get("time") or 0), case.get("name") or "?"))
print(f"{best[0]:.1f} {best[1].replace(' ', '')}")
EOF
}

deadline=$((SECONDS + MINUTES * 60))
i=0 stalls=0 broken=0 offline=()
log "running ${TEST} for ${MINUTES} min or until ${STOP_AFTER} stalls (a case over ${SLOW}s)"
while (( SECONDS < deadline && stalls < STOP_AFTER )); do
  i=$((i + 1))
  dest="${OUT}/iter-${i}"
  mkdir -p "${dest}"
  rm -rf "${TARGET}/surefire-reports" "${TARGET}/test-dir"
  "${HARNESS_DIR}/lib/stall-watch.sh" "${dest}/stalls" $$ &
  watch=$!
  started=$(date -u +%H:%M:%S) start=${SECONDS} rc=0
  mvn_logged "${SIDE}" "${dest}/mvn.log" "${offline[@]}" -nsu test -pl "${MODULE}" \
    "-Dtest=${TEST}" -Dsurefire.failIfNoSpecifiedTests=false \
    -Dmaven.test.failure.ignore=true -Dsurefire.rerunFailingTestsCount=0 \
    -Dmaven.javadoc.skip=true -Dspotbugs.skip=true -Dcheckstyle.skip=true || rc=$?
  kill "${watch}" 2>/dev/null || true
  wait "${watch}" 2>/dev/null || true
  secs=$((SECONDS - start))
  read -r case_s case_name <<< "$(slowest_case)"
  scr=$(scr_reads)
  if [[ "${VARIANT}" == short-circuit && "${case_s}" != -1.0 && "${scr}" == 0 ]] && (( i == 1 )); then
    cp -r "${TARGET}/surefire-reports" "${dest}/" 2>/dev/null || true
    die "run 1 made no short-circuit read (they fell back to TCP); see ${dest}"
  fi
  stall=no
  if [[ "${case_s}" == -1.0 ]]; then
    broken=$((broken + 1))
    log "run ${i}: no test reports (maven exit ${rc}); see ${dest}/mvn.log"
    (( broken < 3 )) || die "3 runs without test reports in a row"
  else
    broken=0
    # From the second run on Maven has everything it needs locally.
    offline=(-o)
    if python3 -I -c "import sys; sys.exit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)" "${case_s}" "${SLOW}"; then
      stall=yes
      stalls=$((stalls + 1))
    fi
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${i}" "${started}" "${secs}" "${rc}" "${case_s}" "${case_name}" "${stall}" "${scr}" >> "${OUT}/iterations.tsv"
  if [[ "${stall}" == yes || "${case_s}" == -1.0 ]]; then
    cp -r "${TARGET}/surefire-reports" "${dest}/" 2>/dev/null || true
    log "run ${i}: ${secs}s, slowest case ${case_s}s (${case_name}); kept in ${dest}"
  else
    rm -rf "${dest}"
    if (( i % 10 == 0 )); then
      log "run ${i}: ${secs}s, slowest case ${case_s}s; ${stalls} stalls so far"
    fi
  fi
done
rm -rf "${TARGET}/test-dir"

python3 -I - "${OUT}/iterations.tsv" "${SLOW}" "${VARIANT}" > "${OUT}/summary.md" <<'EOF'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1]), delimiter="\t") if float(r["slowest_case_s"]) >= 0]
stalls = [r for r in rows if r["stall"] == "yes"]
cases = sorted(float(r["slowest_case_s"]) for r in rows)
print(f"Variant: {sys.argv[3]}. Runs of TestMRIntermediateDataEncryption: {len(rows)}; "
      f"stalls (a case over {sys.argv[2]} s): **{len(stalls)}**")
if sys.argv[3] == "short-circuit":
    print(f"\nRuns without a short-circuit read: {sum(1 for r in rows if r['scr_reads'] == '0')}")
if cases:
    print(f"\nSlowest case per run: median {cases[len(cases) // 2]:.1f} s, max {cases[-1]:.1f} s")
for r in stalls:
    print(f"- run {r['iteration']} at {r['started']}: {r['slowest_case']} took {r['slowest_case_s']} s")
EOF
cat "${OUT}/summary.md" >&2
log "results in ${OUT}"
