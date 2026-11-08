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

if [ $# -lt 1 ]; then
  echo "ERROR: Need at least 1 argument, $# were provided"
  exit 1
fi

pkg-resolver/check_platform.py "$1"
if [ $? -eq 1 ]; then
  echo "ERROR: Unsupported platform $1"
  exit 1
fi

default_version="3.25.5"
version_to_install=$default_version
if [ -n "$2" ]; then
  version_to_install="$2"
fi

if [ "$version_to_install" != "3.25.5" ]; then
  echo "WARN: Don't know how to install version $version_to_install, installing the default version $default_version instead"
  version_to_install=$default_version
fi

# Retry a download: transient CDN outages (HTTP 503/504, mid-transfer
# drops) have killed unattended image builds — the short curl --retry
# window written into /root/.curlrc does not cover multi-minute outage
# windows (observed: protobuf's GitHub archive, 2026-11-08). --fail makes
# HTTP error codes fail the download instead of saving the error page as
# the tarball. Attempts and delay are overridable for testing.
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

if [ "$version_to_install" == "3.25.5" ]; then
  # hadolint ignore=DL3003
  mkdir -p /opt/protobuf-src &&
    download_with_retry \
      https://github.com/protocolbuffers/protobuf/archive/refs/tags/v3.25.5.tar.gz \
      /opt/protobuf.tar.gz &&
    tar xzf /opt/protobuf.tar.gz --strip-components 1 -C /opt/protobuf-src &&
    download_with_retry \
      https://github.com/abseil/abseil-cpp/archive/refs/tags/20230802.1.tar.gz \
      /opt/abseil-cpp.tar.gz &&
    tar xzf /opt/abseil-cpp.tar.gz --strip-components 1 -C /opt/protobuf-src/third_party/abseil-cpp &&
    cd /opt/protobuf-src &&
    cmake -S . -B build -DCMAKE_POSITION_INDEPENDENT_CODE=ON -Dprotobuf_BUILD_TESTS=OFF &&
    cmake --build build --parallel $(nproc) &&
    cmake --install build --prefix /opt/protobuf &&
    cd /root &&
    rm -rf /opt/protobuf-src
else
  echo "ERROR: Don't know how to install version $version_to_install"
  exit 1
fi
