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
# F1/R42 dependency-change coverage + F2/R43 baseline freshness, 2026-11-09 ~01:20

Implements the first two items of the 2026-11-08 requirements review's
recommended order (record:
`2026-11-08-2336-License-Management-Requirements-Review.md`). Also
carries the 2026-11-08 reconciliation edits: the googletest record's
real-image-validation section and the R35–38 row's new-tag sentence.

## F1 / R42 — every dependency or assembly change gets an archive run

The dist workflow's push `paths:` filter covered only the ROOT pom.xml,
while dependency versions live in `hadoop-project/pom.xml` and the
module poms, and the shipped set is declared by the assembly
descriptors (all ten under `hadoop-assemblies/src/main/resources/
assemblies/`). A commit changing only those skipped the archive run,
and the per-push R10 gate compared the committed LICENSE-binary against
the PREVIOUS commit's baseline — which matched, so a new shipped
dependency passed CI unchecked (review F1's effect statement).

Fix (the review's stopgap, chosen over the per-push generator
comparison): the filter gains `**/pom.xml` and `hadoop-assemblies/**`
(root `pom.xml` kept explicit; GitHub's `**` matches zero or more path
segments, so the glob is belt-and-braces). Cost: one ~38-minute archive
run per dependency-changing push — acceptable on this branch, and the
ee8afe9cb overlap fix keeps concurrent runs from double-building the
build-env image. The cheaper per-push generator-vs-last-enumeration
comparison remains the documented upstream option if that cost matters
at apache/hadoop scale (revisit under R41/F3, which redesigns the
triggers anyway; pull-request coverage also waits for R41). The R10
gate's assumption comment was updated to match the widened filter.

## F2 / R43 — baseline freshness and a printed recovery path

Three changes:

1. `archive-ground-truth` sets `retention-days: 90`. The first draft
   used 365 and the fresh-context review REJECTED it: GitHub caps
   artifact retention at 1–90 days for PUBLIC repositories (the
   upload-artifact contract: "the retention period must be between 1
   and 90 inclusive"; the 2020-10-08 changelog reserves >1-year
   retention for private/internal/enterprise). 90 is the maximum
   expressible here; the owner chose the cap + fail-closed expiry over
   the retention-proof alternative (committing the baseline to a git
   branch, which would need a commit step, `contents: write`, and an
   R10 baseline-lookup rewrite — recorded as an option if artifact
   expiry ever bites in practice). Upstream, the org's retention
   setting plus the weekly cron make the cap a non-issue.
2. The R10 gate builds an exact recovery command AFTER `wf_id` and
   `branch` are defined — `gh workflow run <id> --repo <repo> --ref
   feat/LICENSES` plus the raw `gh api .../dispatches` form — and every
   failure site prints it: no successful archive run on the branch
   (missing or expired baseline), baseline artifact download failure
   (now explicitly fail-checked instead of relying on bare `set -e`,
   with the same message), missing/empty generated manifest, and the
   R10 DRIFT message. The workflow is registered (id 410303109, state
   active — it runs via push), and workflow_dispatch is declared, so
   the command targets a real dispatch target. Remaining verification:
   dispatch the workflow once by that exact command to prove the
   recovery path end-to-end (a dispatch is a side effect — owner
   gate).
3. The schedule comment states the cron is INERT while the workflow is
   branch-only (GitHub runs schedules from the default branch only;
   the workflow is not on trunk) — on the fork the baseline refreshes
   by push and dispatch only.

## Validation

- YAML parse of both workflows; `bash -n` on every extracted run block
  (GitHub expressions substituted with dummies).
- Static scan of added lines: clean.
- Independent fresh-context review with empirical probes: the glob
  semantics, recovery-command usability, fail-closed paths and
  before-definition ordering all verified PASS; the one substantive
  finding (retention 365 vs the public-repo cap) is fixed as above and
  the fix re-verified by a focused second review: PASS (90 confirmed
  the maximum valid value; YAML parses; nothing else in the step
  changed).
- Real-CI validation rides the next push: this commit touches
  `dev-support/licenses/**` and both workflow files, so the archive run
  revalidates the gates; a pom-touching push after it demonstrates the
  F1 trigger.
