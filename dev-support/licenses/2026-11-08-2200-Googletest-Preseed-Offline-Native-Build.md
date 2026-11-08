<!--
   Licensed to the Apache Software Foundation (ASF) under one or more
   contributor license agreements.  See the NOTICE file distributed with
   this work for additional information regarding copyright ownership.
   The ASF licenses this file to you under the Apache License, Version 2.0
   (the "License"); you may not use this file except in compliance with
   the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.-->
# Googletest preseed: offline native build, 2026-11-08 ~22:00

Closes the residual exposure left open by
`2026-11-08-1940-Dist-CI-Resilience-Retry-And-Image-Cache.md`: the
googletest FetchContent download inside the dist build
(hadoop-hdfs-native-client) is a build-time cmake fetch that neither the
curlrc hardening nor the image cache covers. It already fired once
(HTTP 503, archive run 42474966167). With the build-env image now
content-address-cached, this was the dist run's last single-point CDN
failure.

## Mechanics of the FetchContent download

`libhdfspp/CMakeLists.txt` declares googletest release-1.10.0 (commit
`703bd9caab50b139428cea1aaff9974ebee5742e`) as a GitHub zip URL and
downloads it at configure time. There is no hook to inject a CMake
variable from the Maven side: the Linux native build goes through
`hadoop-maven-plugins:cmake-compile`, whose `<vars>` are fixed in the
pom, and CMake 3.28's FetchContent has no built-in retry. The chosen
remedy (owner-approved) is pre-seeding: the image ships the exact pinned
source tree, and the CMakeLists uses it when present.

## Changes

### 1. `pkg-resolver/download-with-retry.sh` (new, shared)

`download_with_retry` moves out of `install-protobuf.sh` into a sourced
lib so both install scripts share one implementation. Behavior is
unchanged from the 1940 record's validated version (5 attempts × 60 s
sleep, overridable via `DOWNLOAD_RETRY_ATTEMPTS`/`DOWNLOAD_RETRY_DELAY`,
`curl --fail --connect-timeout 30 --max-time 600`, output removed before
every attempt and on final failure).

### 2. `pkg-resolver/install-googletest-preseed.sh` (new)

Downloads the pinned zip with the shared retry helper and unpacks it to
`/opt/googletest-<commit>`. Extraction uses python3's zipfile (the image
has no unzip). Fail-closed throughout: download failure propagates; the
archive must contain exactly one top-level directory; the extracted tree
must contain `CMakeLists.txt` and `googlemock/CMakeLists.txt` or the
destination is removed and the script exits nonzero. Idempotent — a
second run exits 0 without downloading when the tree is already present.
The preseed root is overridable via `GTEST_PRESEED_ROOT` (test-only knob,
default `/opt`). The script's own commit pin and the CMakeLists pin must
stay in sync by review: if the CMakeLists bumps its pin, the build falls
back to the URL download (never a stale tree) and the next image-input
change re-caches the image, prompting the sync fix.

### 3. `Dockerfile_ubuntu_24`

One `RUN pkg-resolver/install-googletest-preseed.sh ubuntu:noble` line
after the protobuf install. The image build is therefore a new
content-addressed tag (the cache hash covers `pkg-resolver/**`): the
first dist run after this commit is a one-time ~20-min cache miss +
push, the next must show `Cache hit`.

### 4. `libhdfspp/CMakeLists.txt` (guarded override)

The pin moves into a `GOOGLETEST_COMMIT` variable (same SHA) that feeds
both the FetchContent URL and a derived preseed path:

```cmake
set(GOOGLETEST_COMMIT 703bd9caab50b139428cea1aaff9974ebee5742e)
set(HADOOP_GOOGLETEST_PRESEED "/opt/googletest-${GOOGLETEST_COMMIT}" CACHE PATH ...)
if(EXISTS "${HADOOP_GOOGLETEST_PRESEED}/CMakeLists.txt")
  set(FETCHCONTENT_SOURCE_DIR_GOOGLETEST "${HADOOP_GOOGLETEST_PRESEED}")
endif()
```

Deriving the preseed path from the commit makes silent version drift
impossible: bumping `GOOGLETEST_COMMIT` moves the expected preseed path
to a directory the image does not have, so the build downloads the new
commit — never uses the old tree. Without the preseed (developer
machines, other platforms) behavior is byte-for-byte the old download.

### 5. Fail-open platform-check fix (both install scripts)

The new script initially copied `install-protobuf.sh`'s platform check
(`check_platform.py "$1"; if [ $? -eq 1 ]`), and the functional tests
exposed it: any nonzero exit other than 1 (126 permission denied, 2
usage error) fell through and the platform check was silently skipped.
Fixed to `if ! pkg-resolver/check_platform.py "$1"` in BOTH scripts —
same latent bug, same class.

## Validation (all offline, /tmp)

- `bash -n` on all three scripts.
- Preseed script, 6 cases: tree created with expected content;
  idempotent re-run; multi-top-level archive rejected with no
  destination left; download failure propagates; post-download failure
  leaves no destination; platform-check exit code 2 (not 1) now fails
  hard (the fail-open fix).
- Retry lib, 3 cases: success first attempt (`file://` URL); exhaustion
  exits 1 with no residue; success after 2 failures via a failing curl
  shim.
- CMake override, real cmake 4.4 wheel, synthetic project replicating
  the patched block: with the preseed present,
  `FETCHCONTENT_SOURCE_DIR_GOOGLETEST` is honored and the source is used
  IN PLACE (`googletest_SOURCE_DIR` = the preseed path, no `_deps`
  population, no download — verified by content probe); with the preseed
  absent, FetchContent falls back to the URL download (exercised against
  both a `file://` zip and the real GitHub URL).
- One harness lesson recorded: a first CMake probe "passed" while the
  preseed tree it was supposed to exercise did not exist (the failure
  tests had deleted it) and cmake silently downloaded from GitHub. The
  override case is only proven when the probe verifies the populated
  source IS the preseed — content probe required, presence of output is
  not evidence.

Real-image validation rides the next dist run: first run after this
commit = expected one-time cache miss (build + push of the new image
tag); the run after must show `Cache hit`, and the archive gate log
should no longer show a googletest download inside the cmake-compile
step.

## Independent review

Fresh-context reviewer with terminal access ran empirical probes on the
diff: PASS, no security concerns, no logic errors. Its probes confirmed
the three behaviors this design depends on — preseed present →
FetchContent uses the local tree offline; pin bumped with only a stale
preseed → cmake hard-fails on the URL download rather than silently
using the stale tree; every shell failure path (bad archive shape,
corrupt zip, downloader failure, invalid tree) exits 1 with cleanup and
no residue.

Non-blocking suggestions, recorded as trade-offs:
- URL_HASH (SHA512) on the FetchContent URL so the network fallback is
  integrity-checked too — not taken; the fallback is the old upstream
  behavior kept byte-identical on purpose, and the preseed path is the
  integrity-checked one. Worth doing if the fallback ever becomes
  default.
- Non-empty check on the downloaded file after curl success (curl
  --fail can succeed with a 0-byte body) — not taken for now; the
  archive-shape validation downstream catches the empty-file case
  before anything is installed.
- Wire the preseed into the other Linux Dockerfiles — not taken; the
  dist build uses only ubuntu_24, other images keep the (now legacy)
  download fallback.
- CI smoke test for the new scripts using the stubbed-downloader
  pattern — deferred; the probes are documented here for reproduction.
