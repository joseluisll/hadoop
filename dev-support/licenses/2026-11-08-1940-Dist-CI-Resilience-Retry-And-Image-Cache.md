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
# Dist CI resilience: protobuf download retry + content-addressed build-env image cache, 2026-11-08 ~19:40

Follow-up to the 2026-11-08 curlrc hardening (see the R35–38 row of
`License-Management.md`). The curlrc window did not survive contact with
a real outage: on commit 404fe3abbee the archive run 42474966167 and
Build run 42474966726 both died on `curl: (22)` from
`pkg-resolver/install-protobuf.sh` (protobuf v3.25.5 GitHub archive) —
the log shows the curlrc retries firing (504 ×3, then 503 ×3, spaced
~5 s) inside a multi-minute CDN outage window, then giving up. A same-day
rerun of both workflows failed the same way, and the archive run died on
a *different* download (googletest FetchContent, HTTP 503 inside the
hadoop-hdfs-native-client cmake-compile). Reruns are not a remedy: the
outage window outlives them.

Two changes, both riding one new commit (an image fix can never land via
rerun — reruns replay the old image):

## 1. Script-level retry in install-protobuf.sh

The two tarball downloads (protobuf, abseil) go through a new
`download_with_retry`: up to 5 attempts with a 60 s sleep between them
(overridable via `DOWNLOAD_RETRY_ATTEMPTS` / `DOWNLOAD_RETRY_DELAY` for
testing), `curl --fail` so an HTTP error code fails the download instead
of saving the error page as the tarball, and the output file removed
before every attempt so no partial or HTML residue can reach `tar xzf`.
Local functional tests (in /tmp, synthetic URLs): success first attempt,
failure-exhaustion (exit 1 after N attempts with sleeps), success on a
later attempt via a failing curl shim, and no residue after failed
attempts — all pass.

## 2. Content-addressed build-env image cache in licenses-dist.yml

The dist workflow rebuilt the ~20-minute build-env image from scratch on
every run, and those pkg-resolver downloads were the branch's main
transient-failure point. The Build workflow's GHCR base images could not
be reused directly: they are tagged per-run
(`gha-build-<os>:<branch>-<run_id>-base`, no stable tag) and are built
from trunk's Dockerfile, not this branch's. Instead the dist workflow now
publishes its OWN cache image:

- Tag `ghcr.io/<owner>/hadoop-build-ubuntu_24:cache-<sha256>` where the
  hash covers every file the image build consumes:
  `Dockerfile_ubuntu_24`, the whole `pkg-resolver/` directory and
  `hadoop_env_checks.sh`. A cache hit therefore guarantees the image was
  built from the exact inputs of THIS commit; any input change produces
  a new tag, so a stale image can never mask a Dockerfile or
  download-script change.
- On a miss (first run, or any input change) the workflow builds the
  image and pushes the tag; every subsequent run pulls instead of
  building — the ~20 minutes and the CDN-flake failure class both leave
  the per-run path.
- `start-build-env.sh` gains an env-gated skip: with
  `HADOOP_BUILD_ENV_PREBUILT=1` it uses the existing `hadoop-build`
  image instead of rebuilding it. Default behavior is unchanged.
- The job gains `packages: write` (GITHUB_TOKEN-scoped, package stays
  private to the repository); a pull failure — genuine miss or auth
  error — falls through to the build path, and a push failure fails the
  step visibly.
- The push `paths:` filter widens from `Dockerfile_ubuntu_24` to
  `dev-support/docker/**` plus `start-build-env.sh` (the image's build
  inputs are gate inputs); `LICENSE-binary` and `pom.xml` remain in the
  filter.

Known residual exposure: the googletest FetchContent download inside the
Maven build (hadoop-hdfs-native-client) is NOT covered by either change
— it is a build-time cmake download, not an image-build download. With
the image cached, the dist run's exposure to CDN outages shrinks to that
single FetchContent fetch plus Maven artifact resolution.

## Validation

- `bash -n` on both shell scripts; YAML parse of the workflow.
- Functional retry tests as listed above (4/4 pass).
- Static security scan of the added lines: clean.
- Independent fresh-context review (empirical probes on synthetic
  inputs, incl. a live HTTP server and a curl-shim residue test):
  PASS — no security concerns, no logic errors. Three of its
  non-blocking suggestions were applied before commit (curl
  `--connect-timeout 30 --max-time 600`, final-failure `rm -f` of the
  output file, retry WARN suppressed on the last attempt); the delta was
  re-verified empirically (4/4 paths pass) and re-reviewed fresh-context:
  PASS, no findings.
  Not taken (trade-offs recorded here): tolerating a failed cache push so
  the dist gate survives registry-write outages (cache repopulation
  would then depend on a later run), and digest-pinning the
  `FROM ubuntu:noble` base (the content hash covers repo inputs only).
- Real-image validation happens on the next dist run: first run after
  this commit is a cache miss (build + push, expected slow once);
  the run after that must show "Cache hit" and skip the ~20-minute build.
