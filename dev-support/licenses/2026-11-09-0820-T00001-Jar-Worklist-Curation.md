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
# T00001: jar worklist curation (14 entries), 2026-11-09 ~08:20

Closes the work-state item "Curate the 15-entry jar worklist from the
-Pyarn-ui dist shape" (T00001). Source of truth: archive run 42543652715
on 5dce2dabd53 — the first `-Pdist,native,yarn-ui` ground truth (its
asset-gate failure was fixed in round 2, record
`2026-11-09-0300-R7-Stage-C-Round-2-Lock-Evidence-And-UI-Wars.md`; the
jar-side enumeration and both jar gates passed in that run).

## The worklist, verified

Recomputed with the gate's own algorithm (`check-archive-licenses.sh`
graph-only `comm`, `archive-jar-mappings` promotion applied, own
`org.apache.hadoop*` excluded) against the UNION of both archive TSVs:
inventory 316 g:a, union of shipped g:a 302, worklist **14** entries —
not 15 as recorded in work state. The 15th line was
`com.google.protobuf:protobuf-java-util`, which the enumeration carries
as a partial row (3.25.5, `filename` source) promoted by
`archive-jar-mappings`: it ships (inside hadoop-client-runtime's shade
set, listed in `shaded-jars`), so it was never worklist material.

All 14 fall into two classes:

### Class 1 — embedded in a shipping uber jar (1 entry)

- `io.opentelemetry:opentelemetry-common:1.59.0` — shaded and relocated
  to `com.google.cloud.hadoop.repackaged.ossgcs.io.opentelemetry` inside
  `org.apache.hadoop:hadoop-gcp` (ships in
  `share/hadoop/common/lib/hadoop-gcp-3.6.0-SNAPSHOT.jar`). Evidence:
  hadoop-gcp's pom imports `opentelemetry-bom:1.59.0` (exactly the
  inventory's resolved version — the whole 1.59.0 opentelemetry set in
  the inventory exists only through hadoop-gcp's graph) and shades
  `io.opentelemetry.**` with that relocation. Disposition: new
  `shaded-jars` entry (the protobuf precedent).

### Class 2 — compile(+optional)/test scope of modules the dist never ships (13 entries)

None of these exists anywhere in either archive, standalone or embedded:

- `org.apache.kerby`: `kerb-admin`, `kerb-client`, `kerb-common`,
  `kerb-identity`, `kerb-server`, `kerb-simplekdc`, `kerby-xdr`,
  `token-provider` (2.0.3) — pulled only by hadoop-minikdc and
  hadoop-client-minicluster (compile+optional). The auth-chain kerby
  jars (`kerb-core`, `kerb-util`, `kerb-crypto`, `kerby-asn1`,
  `kerby-pkix`) DO ship standalone (2.0.3, pom.properties evidence) and
  are NOT touched. This corrects the `shaded-jars` prose claiming kerby
  is embedded in hadoop-client-runtime: the runtime shade set never
  reaches these eight (its dependencies cannot; only minikdc/minicluster
  declare them), and the shipped kerby jars prove the runtime auth chain
  is served standalone.
- `org.openjdk.jmh`: `jmh-core`, `jmh-generator-annprocess` (1.20,
  GPL2+classpath-exception) — compile scope of hadoop-benchmark, which
  the dist assembly does not ship (0 rows in either TSV).
- `javax.ws.rs:jsr311-api` (1.1.1) — compile scope of the
  hadoop-yarn-server-timelineservice-hbase-tests test-support module;
  the jersey 1.x stack it belongs to ships nowhere (only jersey-server
  2.46 ships, via the jakarta chain).
- `net.sf.kosmosfs:kfs` (0.3) — compile+optional in
  hadoop-client-minicluster.
- `org.glassfish.jersey.containers:jersey-container-jdk-http` (2.46) —
  transitive of `jersey-test-framework-provider-jdk-http`, whose parent
  is already in `excludedArtifacts` (`jersey-test-framework-.*`); the
  per-entry filter dropped the parent but not this transitive.

Owner decision (presented 2026-11-09, options A/B/C): **Option A** —
extend the root pom's `excludedArtifacts` (the canonical, already
R39/R47-gate-enforced inventory filter) rather than a fork-side
inventory-exception file. Consequence accepted: the 13 leave
THIRD-PARTY.txt, so the per-release third-party report no longer claims
dependencies that ship nowhere; the fork-carried line in the
upstream-vendored pom.xml grows.

## Changes

1. `pom.xml` — `excludedArtifacts` gains 13 anchored alternatives:
   `jmh-.*|jsr311-api|kfs|jersey-container-jdk-http|kerb-admin|
   kerb-client|kerb-common|kerb-identity|kerb-server|kerb-simplekdc|
   kerby-xdr|token-provider`; comment documents the class and why the
   auth-chain kerby jars stay out.
2. `dev-support/licenses/shaded-jars` — new entry:
   `io.opentelemetry:opentelemetry-common # embedded in hadoop-gcp`;
   kerby prose in the header comment corrected (kerby only partly
   embedded; the eight minikdc/minicluster-only artifacts are curated
   out of the inventory instead).
3. This record.

## Validation (offline, run 42543652715 data)

- Gate with the edited pom and the REAL run inventory: R47 anchoring
  check passes, R39 passes (no curated exclusion ships — verified
  against both TSVs), main-archive worklist = one line,
  `opentelemetry-common [mapped: ...]`. Exit 0.
- Gate with a simulated post-curation inventory (13 entries removed,
  316→303 g:a, the exact effect the license plugin will produce):
  main archive gate passes, worklist = the single mapped line; cloud
  archive gate passes; the 13 no longer appear in either worklist.
- No LICENSE-binary change: the generator derives from archive TSVs and
  none of the 14 ships; the R10 drift gate compares LICENSE-binary only.

## Follow-ups

- Push triggers dist + collect runs (pom.xml and `dev-support/licenses/**`
  are in the dist `paths:` filter) — the first real inventory with the 13
  removed is the like-for-like validation of this curation; watch item
  recorded in work state.
- `io.opentelemetry:opentelemetry-api:1.38.0` and other version-form
  mismatches (inventory claims 1.38.0/1.59.0 where the archive ships
  1.47.0/1.49.0) are the R31 warning class — informational, untouched
  here.
