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
# Dist CI triage: GHCR denies the first build-env cache push, 2026-11-08 ~21:00

Triage of the two runs the 2026-11-08 resilience commit (58c5d43e092) was
waiting for. Neither failure is gate logic or curation; one is a new
external failure class, the other its designed knock-on.

## Archive run 42511445584 — GHCR denies the manifest PUT

The resilience work itself validated: the build-env image built cleanly
in ~11 minutes on the retry-hardened scripts — no `curl: (22)` anywhere,
no protobuf/abseil/isa-l download failures. The failure moved to the NEW
cache-push step: `docker push -q
ghcr.io/joseluisll/hadoop-build-ubuntu_24:cache-d864fc...` exited with
`error from registry: denied` at 18:56 UTC, ~75 s after the image
finished exporting.

Registry forensics (anonymous token probes against ghcr.io):

- Every blob of the image IS in the registry — the image config blob
  returns HTTP 307 (present, redirect to storage). The push got past
  all layer uploads.
- The package entity `joseluisll/hadoop-build-ubuntu_24` exists with
  ZERO tags (`tags/list` → 200, `tags: null`); the pushed tag returns
  404 MANIFEST_UNKNOWN. So: blobs accepted, package shell created,
  manifest PUT denied.
- The same digest in the Build workflow's `gha-build-ubuntu_24` package
  returns 404 BLOB_UNKNOWN — the blob exists only in the new package,
  i.e. it was uploaded by THIS run, not leaked from elsewhere.

Ruled out:

- Not credentials: docker/login-action logged in successfully
  (username joseluisll, GITHUB_TOKEN), and the workflow declares
  `packages: write` (workflow-level).
- Not package linkage: the owner checked
  `users/joseluisll/packages/container/hadoop-build-ubuntu_24/settings`
  — the package was created recently (i.e. by this run's push) and
  lists the `hadoop` repository in its access grants.
- Not the underscore in the image name: `gha-build-ubuntu_24` has been
  pushed successfully with the same token mechanics for months.

This matches a GitHub community bug report from 2026-10-31 (discussion
orgs/community#211735): blobs upload, manifest PUT denied, tag 404,
empty package shell — unresolved on GitHub's side; the reporter's
manifest-only retry later succeeded with HTTP 201. The suggested
diagnostic there if it recurs: push with `skopeo --debug` (or without
`-q`) to see WHICH PUT (image manifest, attestation manifest, or index)
is rejected — `docker push -q` condenses everything to one line.

Also a plausible suspect worth one variable change if the retry fails:
the image was built by modern buildx, which attaches provenance
attestation manifests by default (`exporting attestation manifest` in
the build log). `BUILDX_NO_DEFAULT_ATTESTATIONS=1` on the build (or
`--provenance=false`) would remove the attestation manifest from the
pushed index as an isolation test.

## Collect run 42511445672 — designed knock-on

Failed only at the R10 drift-gate step, which found the same-SHA
archive run failed and failed itself with the "triage that run"
message — exactly the commit-aware gate behavior added 2026-11-08
(after run 42461135530 raced its archive run). Nothing else in the
collect run broke. Once the archive run for this commit succeeds, the
R10 gate passes on the next collect (or on rerun).

## Action taken

`gh run rerun 42511445584 --failed` dispatched 2026-11-08 ~20:58 CET.
The rerun re-pulls (miss — no manifest was ever published), rebuilds
the image (~20 min), and retries the push against the now-existing
package shell.

## What to watch

- Rerun push step: success ⇒ the denial was transient (community-bug
  class); the run proceeds to the dist build with
  `HADOOP_BUILD_ENV_PREBUILT=1`.
- The NEXT push-triggered dist run must show "Cache hit" and skip the
  ~20-minute build — that is the real-image validation the 19:40
  record deferred to these runs.
- If the rerun denies again at the manifest PUT: rerun the push step
  verbosely (`docker push` without `-q`, or skopeo --debug) to capture
  the rejected request, and try the build without default attestations
  as the isolation test. A persistent denial against a package shell
  that the repo has access to would be GitHub-side; the fallback lever
  is publishing under a different package name.
- Build run 42511446037 (same push) is still in progress; its
  Docker-pull fallout class from 404fe3abbee should be gone.
