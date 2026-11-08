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

# Pre-seed the googletest source that libhdfspp's CMakeLists.txt consumes
# via FetchContent (release-1.10.0, pinned by commit SHA). At configure
# time the CMakeLists picks this tree up from /opt/googletest-<commit> and
# skips the network download — the last build-time fetch in the dist build
# that a CDN outage could kill (observed: HTTP 503, archive run
# 42474966167, 2026-11-08). The commit here and the GOOGLETEST_COMMIT
# variable in libhdfspp's CMakeLists.txt must stay in sync: if the
# CMakeLists bumps its pin, the preseed path changes there too and the
# build falls back to the URL download rather than using a stale tree.

if [ $# -lt 1 ]; then
  echo "ERROR: Need at least 1 argument, $# were provided"
  exit 1
fi

if ! pkg-resolver/check_platform.py "$1"; then
  echo "ERROR: Unsupported platform $1"
  exit 1
fi

default_commit="703bd9caab50b139428cea1aaff9974ebee5742e"
commit=$default_commit
if [ -n "$2" ]; then
  commit="$2"
fi

dest="${GTEST_PRESEED_ROOT:-/opt}/googletest-${commit}"
if [ -f "${dest}/CMakeLists.txt" ] && [ -f "${dest}/googlemock/CMakeLists.txt" ]; then
  echo "googletest ${commit} already preseeded at ${dest}"
  exit 0
fi

source "$(dirname "$0")/download-with-retry.sh"

# GitHub archive zips contain a single top-level directory
# googletest-<commit>/. The image has no unzip; python3 (installed for the
# package resolver) handles extraction.
zip="/tmp/googletest-${commit}.zip"
tmp=$(mktemp -d)
if ! download_with_retry \
    "https://github.com/google/googletest/archive/${commit}.zip" "$zip"; then
  rm -rf "$tmp"
  exit 1
fi

python3 - "$zip" "$tmp" <<'PYEOF'
import sys, zipfile
zip_path, extract_to = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(extract_to)
PYEOF
if [ $? -ne 0 ]; then
  echo "ERROR: failed to extract ${zip}" >&2
  rm -rf "$tmp" "$zip"
  exit 1
fi

# Exactly one top-level directory is expected; anything else means the
# archive shape changed and the tree cannot be trusted as a preseed.
entries=$(find "$tmp" -mindepth 1 -maxdepth 1 || true)
top=$(echo "$entries" | wc -l)
if [ "$top" -ne 1 ] || [ ! -d "$(echo "$entries" | head -1)" ]; then
  echo "ERROR: ${zip} does not contain exactly one top-level directory" >&2
  rm -rf "$tmp" "$zip"
  exit 1
fi

rm -rf "$dest"
mv "$(echo "$entries" | head -1)" "$dest"
rm -rf "$tmp" "$zip"

if [ ! -f "${dest}/CMakeLists.txt" ] || [ ! -f "${dest}/googlemock/CMakeLists.txt" ]; then
  echo "ERROR: extracted tree at ${dest} is not a googletest source tree" >&2
  rm -rf "$dest"
  exit 1
fi

echo "Preseeded googletest ${commit} at ${dest}"
