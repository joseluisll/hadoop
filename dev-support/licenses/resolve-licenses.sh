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
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Offline-first license text resolution.
#
# Reads the distinct licenses from a THIRD-PARTY.txt report and resolves
# each one against the versioned texts in dev-support/licenses/texts/.
# Nothing is downloaded: network access is only used by the optional
# aggregate-download-licenses goal (see .github/workflows/licenses.yml).
#
# Usage: resolve-licenses.sh <THIRD-PARTY.txt> <texts-dir> <output-dir> [--strict]
#   --strict  exit 1 if any license has no local text
set -euo pipefail

report="$1"
texts_dir="$2"
out_dir="$3"
strict="${4:-}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=license-slugs.sh
source "$script_dir/license-slugs.sh"

mkdir -p "$out_dir"
missing=()

# distinct license names from lines like "     (MIT License) foo (...)"
while IFS= read -r license_name; do
  slug="$(license_slug "$license_name")"
  src="$texts_dir/LICENSE-$slug.txt"
  if [[ -f "$src" ]]; then
    cp "$src" "$out_dir/"
  else
    missing+=("$license_name (LICENSE-$slug.txt)")
  fi
done < <(grep -oE '^\s+\([^()]+\)' "$report" | sed 's/^\s*(//;s/)$//' | sort -u)

resolved=$(find "$out_dir" -name 'LICENSE-*.txt' | wc -l)
echo "Resolved $resolved license text(s) from $texts_dir into $out_dir"

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "MISSING local license texts:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  if [[ "$strict" == "--strict" ]]; then
    exit 1
  fi
fi
