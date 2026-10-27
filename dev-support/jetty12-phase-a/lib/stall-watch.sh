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

# Usage: stall-watch.sh <dir> <parent pid>
#
# Runs in the background while unit-tests.sh runs one module's tests, and
# exits with the parent. Surefire runs each test class in its own JVM and
# Hadoop gives that JVM 900 s (surefire.fork.timeout). When one has run for
# STALL_AFTER seconds (default 600), this records, into
# <dir>/<pid>-<n>.txt, what the TCP stack and the JVM are doing:
#   ss -tinmoep   every TCP socket with its kernel state: send and receive
#                 queues, windows, cwnd, rtt, retransmits, timers (a
#                 "persist" timer means the peer advertised a zero window),
#                 socket memory;
#   nstat         the kernel's TCP counters (zero-window, retransmit, drops);
#   jstack        the JVM's threads.
# Then again every STALL_REPEAT seconds (default 120), at most STALL_SNAPSHOTS
# times (default 8), so successive snapshots show whether bytes still move.
# With STALL_TCPDUMP=1, the first and every tenth snapshot also capture 20 s
# of loopback packet headers into <dir>/<pid>-<n>.pcap (needs tcpdump and the
# right to capture, e.g. root in a container).
# Written for a test whose HDFS read over loopback slowed to a trickle for
# half an hour (TestMRIntermediateDataEncryption in Hadoop's CI): the thread
# dump showed both ends waiting on the socket, and only the kernel's view
# of that socket can say why.
#
# Nothing is written when no test JVM runs that long. Missing tools are
# skipped.

set -uo pipefail
DIR=$1
PARENT=$2
AFTER=${STALL_AFTER:-600}
REPEAT=${STALL_REPEAT:-120}
MAX=${STALL_SNAPSHOTS:-8}
POLL=${STALL_POLL:-30}
JSTACK=jstack
[[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/jstack" ]] && JSTACK="${JAVA_HOME}/bin/jstack"

declare -A taken last

section() {
  echo
  echo "===== $1"
  shift
  if command -v "$1" >/dev/null 2>&1; then
    "$@" 2>&1
  else
    echo "($1 not available)"
  fi
}

snapshot() {
  local pid=$1 age=$2 n=$3
  mkdir -p "${DIR}"
  if [[ "${STALL_TCPDUMP:-}" == 1 ]] && (( n == 1 || n % 10 == 0 )) && command -v tcpdump >/dev/null 2>&1; then
    # Headers only (-s 96), at most 200000 packets; in the background so the
    # snapshot below is taken at the same time.
    timeout 20 tcpdump -i lo -p -nn -s 96 -c 200000 -w "${DIR}/${pid}-${n}.pcap" \
      > "${DIR}/${pid}-${n}.tcpdump.log" 2>&1 &
  fi
  {
    echo "test JVM ${pid}, running for ${age}s, snapshot ${n} at $(date -u +%FT%TZ)"
    section "ps" ps -o pid,etimes,pcpu,rss,args -p "${pid}"
    section "loadavg" cat /proc/loadavg
    section "ss -tinmoep" ss -tinmoep
    section "nstat -asz" nstat -asz
    if (( n == 1 )); then
      section "sysctl" sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max \
        net.core.wmem_max net.ipv4.tcp_moderate_rcvbuf net.ipv4.tcp_window_scaling
      section "ip link show lo" ip link show lo
      section "uname" uname -a
    fi
    section "jstack" "${JSTACK}" -l "${pid}"
  } > "${DIR}/${pid}-${n}.txt"
}

while kill -0 "${PARENT}" 2>/dev/null; do
  now=${SECONDS}
  # Surefire's test JVMs: java -jar .../surefirebooter-<id>.jar ...
  for pid in $(pgrep -f 'surefirebooter[^ ]*\.jar' 2>/dev/null); do
    [[ "$(ps -o comm= -p "${pid}" 2>/dev/null)" == java ]] || continue
    age=$(ps -o etimes= -p "${pid}" 2>/dev/null | tr -d ' ')
    [[ -n "${age}" ]] && (( age >= AFTER )) || continue
    n=${taken[${pid}]:-0}
    (( n < MAX )) || continue
    (( n == 0 || now - ${last[${pid}]:-0} >= REPEAT )) || continue
    taken[${pid}]=$((n + 1))
    last[${pid}]=${now}
    snapshot "${pid}" "${age}" $((n + 1))
  done
  sleep "${POLL}"
done
