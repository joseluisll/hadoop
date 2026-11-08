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

# Shared download helper for the pkg-resolver install scripts. Source this
# file, then call download_with_retry <url> <output-file>.

# Retry a download: transient CDN outages (HTTP 503/504, mid-transfer
# drops) have killed unattended image builds — the short curl --retry
# window written into /root/.curlrc does not cover multi-minute outage
# windows (observed: protobuf's GitHub archive, 2026-11-08). --fail makes
# HTTP error codes fail the download instead of saving the error page as
# the tarball. The output file is removed before every attempt so no
# partial or HTML residue can reach a later tar/unzip. Attempts and delay
# are overridable for testing.
download_with_retry() {
  local url="$1" out="$2"
  local attempts="${DOWNLOAD_RETRY_ATTEMPTS:-5}"
  local delay="${DOWNLOAD_RETRY_DELAY:-60}"
  local i
  for i in $(seq 1 "$attempts"); do
    rm -f "$out"
    if curl -L -s -S --fail --connect-timeout 30 --max-time 600 "$url" -o "$out"; then
      return 0
    fi
    if [ "$i" -lt "$attempts" ]; then
      echo "WARN: download of $url failed (attempt $i/$attempts), retrying in ${delay}s" >&2
      sleep "$delay"
    fi
  done
  rm -f "$out"
  echo "ERROR: download of $url failed after $attempts attempts" >&2
  return 1
}
