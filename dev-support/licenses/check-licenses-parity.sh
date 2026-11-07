#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied.  See the License for the specific
# language governing permissions and limitations under the License.

# Parity gate between the generated THIRD-PARTY inventory and the
# hand-maintained LICENSE-binary manifest (requirement 25 of
# dev-support/licenses/License-Management.md).
#
# The generated inventory is the future baseline of record; until it is a
# proven superset of the manual one, every dependency the manual manifest
# tracks must appear in the generated inventory — a manual entry missing
# from the generated output is a regression of the collection.
#
# Both directions are reported; only manual-but-not-generated fails,
# because the generated inventory is expected to surface dependencies the
# manual process misses (that is the point of the module).
#
# Known inventory noise (hadoop's own reactor artifacts, test libraries)
# is expected in the generated direction and listed only for information.
#
# Usage: check-licenses-parity.sh <THIRD-PARTY.txt> <LICENSE-binary>
#                               [assembly-includes]
#   exit 1 when any manual g:a is absent from the generated inventory,
#          unless it is listed (with a justification) in the optional
#          assembly-includes file: jars that ship via assembly includes
#          and are legitimately outside the compile/runtime graph.
#   exit 1 when an assembly-includes entry IS in the generated inventory
#          (the exception is stale and must be pruned).
set -euo pipefail

report="$1"
manifest="$2"
includes="${3:-}"

# g:a pairs from the generated inventory: the LAST parenthesized group of
# each report line is the g:a:v coordinate (an artifact name always sits
# between the license groups and it, and names may carry their own parens)
generated="$(mktemp)"
manifest_gas="$(mktemp)"
cleanup() { rm -f "$generated" "$manifest_gas"; }
trap cleanup EXIT
LC_ALL=C awk '
  {
    line = $0
    n = length(line)
    depth = 0
    group = ""
    last = ""
    i = 1
    while (i <= n) {
      c = substr(line, i, 1)
      if (depth == 0) {
        if (c == "(") { depth = 1; group = ""; i++; continue }
        i++
        continue
      }
      if (c == ")") {
        depth--
        if (depth == 0) { last = group; group = "" }
        else { group = group c }
        i++
        continue
      }
      if (c == "(") depth++
      group = group c
      i++
    }
    split(last, parts, ":")
    if (parts[1] != "" && parts[2] != "") print tolower(parts[1]) ":" parts[2]
  }
' "$report" | LC_ALL=C sort -u > "$generated"

# g:a pairs from the manual manifest: lines that look like g:a[:v];
# tolerate the known malformed entries by taking the first two fields
# (an empty match set must not kill the script under pipefail)
grep -E '^[a-z][a-zA-Z0-9._-]*(:[a-zA-Z0-9._=-]+)+' "$manifest" \
  | sed 's/\.jar$//' | LC_ALL=C awk -F: '{print tolower($1) ":" $2}' | LC_ALL=C sort -u > "$manifest_gas" || true

missing=$(comm -23 "$manifest_gas" "$generated")
extra=$(comm -13 "$manifest_gas" "$generated")

# a manifest that parsed to zero g:a entries is a broken input, not a
# vacuous pass — every manual entry cannot be "covered" by nothing
if [[ ! -s "$manifest_gas" ]]; then
  echo "PARITY FAILURE: no g:a entries parsed from $manifest" >&2
  exit 1
fi

# jars that ship via assembly includes and are legitimately off-graph
expected=""
if [[ -n "$includes" ]]; then
  includes_gas="$(mktemp)"
  cleanup() { rm -f "$generated" "$manifest_gas" "$includes_gas"; }
  grep -vE '^[[:space:]]*(#|$)' "$includes" \
    | awk '{print tolower($1)}' | LC_ALL=C sort -u > "$includes_gas"
  # an exception that is already covered by the inventory is stale
  stale=$(comm -12 "$includes_gas" "$generated")
  if [[ -n "$stale" ]]; then
    echo "STALE assembly-includes entries (already in the generated inventory, prune them from $includes):" >&2
    printf '%s\n' "$stale" >&2
    exit 1
  fi
  if [[ -n "$missing" ]]; then
    expected=$(comm -12 "$includes_gas" <(printf '%s\n' "$missing"))
    missing=$(comm -23 <(printf '%s\n' "$missing") "$includes_gas")
  fi
fi

if [[ -n "$missing" ]]; then
  echo "PARITY FAILURE: manual LICENSE-binary entries absent from the generated inventory:" >&2
  printf '%s\n' "$missing" >&2
fi
if [[ -n "$extra" ]]; then
  {
    echo "INFO: generated inventory entries not in the manual manifest"
    echo "(expected: the automated collection surfaces what the manual process misses):"
    printf '%s\n' "$extra"
  } >&2
fi

if [[ -n "$expected" ]]; then
  {
    echo "expected: manual entries shipped via assembly includes (see dev-support/licenses/assembly-includes):"
    printf '%s\n' "$expected"
  } >&2
fi

echo "manual manifest: $(wc -l < "$manifest_gas") g:a pairs; generated inventory: $(wc -l < "$generated") g:a pairs"

if [[ -n "$missing" ]]; then
  exit 1
fi
echo "Parity gate passed: every manual entry is covered by the generated inventory."