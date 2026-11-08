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
# Stage 3 switch: generated manifest is the artifact of record, 2026-11-08 ~08:00

The transition plan's design decision is resolved: the shipped
`LICENSE-binary` is the COMMITTED, GENERATED file. The R40 generator
derives it from the archives' enumerations; the workflows enforce that
the committed file can never silently diverge from what the archives
contain. The manual-parity scaffolding retires.

## Changes

- `LICENSE-binary` regenerated with `generate-archive-manifest.py`
  against the freshest green ground-truth pair (archive run 42427570912
  + collect run 42427570914, both on the previous commit). g:a set is
  EXACTLY the manual file's 302; the diff is 100% the R40 record's
  documented classes:
  - 15 stale-version drops (versions the archives do not ship:
    aliyun-sdk-oss 3.13.2, error_prone_annotations 2.32.0, guava
    33.4.0-jre, failureaccess 1.0.1, commons-beanutils 1.9.4,
    httpclient5 6.3, opencensus-api 0.12.3, audience-annotations 0.5.0,
    opentelemetry 1.59.0 family x7),
  - 4 enumerated version forms (google-api-services-storage 2.0.0
    plain vs the v1-rev POM form, EclipseLink core/moxy OSGi build
    stamps, org.jacoco.agent 0.8.5-runtime classifier form),
  - the two R28 section corrections (org.jacoco.agent -> EPL 2.0,
    reactive-streams -> Public Domain),
  - cosmetic: exact "The following components are included:" wording,
    hdrhistogram case normalization, asset lines grouped at section
    top, sorted entries.
- `licenses-dist.yml`: new R40 drift-gate step — after the per-archive
  gates, the workflow regenerates the manifest from THIS run's TSVs and
  fails on any diff against the committed file. The generated manifest
  joins the `archive-ground-truth` artifact as
  `generated-LICENSE-binary`.
- `licenses.yml`: the R25 parity gate
  (`check-licenses-parity.sh` vs the hand-maintained manifest) is
  REPLACED by the R10 drift gate: resolve the last successful archive
  ground-truth run on this branch (workflow looked up by name, run by
  head_branch), download its `generated-LICENSE-binary`, diff against
  the committed file. Fail-closed: unregistered workflow, no successful
  run, or missing/empty artifact all fail the gate.
- `dev-support/licenses/check-licenses-parity.sh` deleted (retired with
  R25; the archive gate keeps consuming `assembly-includes` for its
  R26/R39 expected-absences, so that curated file stays).
- README updated: regeneration command, drift-gate description,
  assembly-includes wording, refinement list.

## Why this ordering is safe

The dist workflow gates the tarball it ships (R38) BEFORE the drift
gate, and the drift gate runs against the same enumerations the R38
gate just validated — a green dist run means: what ships in the
tarball, what the committed manifest states, and what the generator
derives are three views of one truth. The per-push gate compares the
committed file against the last such validated manifest, so a manifest
change without an archive run behind it cannot slip through.

The committed-file design reopens a drift window between a dependency
change and the next weekly dist run — the per-push graph inventory
(unchanged) is the early-warning gate in that window, as R40 intended.

## Validation

- 11/11 generator tests pass.
- Regeneration against 42427570912/42427570914: exit 0, 302 g:a /
  316 version lines / 120 assets / 11 sections; diff vs the previous
  manual file fully classified above (no unexplained line).
- The fix-verification review of the generator completed green
  2026-11-08 (see the R40 record) before this switch was built on it.
- Workflow edits are static YAML; the R40 drift-gate command sequence
  was exercised locally against the downloaded artifacts of the same
  run pair. First real validation is the dist run this push triggers
  (the paths filter includes LICENSE-binary and the workflow files).

## Scope note (NOTICE-binary)

Unchanged: NOTICE-binary stays hand-maintained (curated prose
attribution corpus, per the R40 record's scope note); its generation
remains open.
