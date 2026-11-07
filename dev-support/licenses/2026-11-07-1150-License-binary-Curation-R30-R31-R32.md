<!-- Licensed to the Apache Software Foundation (ASF) under one or more
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
# LICENSE-binary curation record (R30, R31, R32), 2026-11-07 ~11:50

One-time cleanup of the hand-maintained `LICENSE-binary` manifest, performed
against the generated inventory of CI run 42362507643 (commit `cf7d915c854`,
`feat/LICENSES`; artifact `collected-licenses`, `THIRD-PARTY.txt` with 331
dependencies / 313 g:a pairs). Before the pass the parity gate
(`check-licenses-parity.sh`, requirement 25) failed with 39 manual g:a
entries absent from the generated inventory; after the pass it exits 0
(250 manual g:a pairs, one expected exception via
`dev-support/licenses/assembly-includes`).

Evidence per entry is from the repository poms, the assembly descriptors,
and the run's `THIRD-PARTY.txt` (paths refer to this commit). No build was
run (AGENTS.md policy); the inventory of record is the CI artifact.

## 1. Pruned entries (R32 — stale, 30 artifacts)

### Test-scoped dependencies (never shipped)

| Entry | Evidence | Action |
|---|---|---|
| `org.apache.sshd:sshd-common/core/sftp:2.11.0` (3) | test scope in `hadoop-common-project/hadoop-common/pom.xml:271-277` (sshd-common is their transitive) | pruned |
| `com.github.stephenc.jcip:jcip-annotations:1.0-1` | test scope in `hadoop-yarn-server-router/pom.xml:178` and `hadoop-yarn-server-resourcemanager/pom.xml:362` | pruned |
| `junit:junit:4.13.2`, `org.hamcrest:hamcrest-core:1.3`, `org.objenesis:objenesis:2.6` | test libraries; objenesis/hamcrest also curated out of the inventory via `excludedArtifacts` (`pom.xml`) | pruned |

### Test tooling that leaks into the compile-scope graph (R39 class)

Curated out of the inventory by `excludedArtifacts` in the root `pom.xml`
(mockito/junit/objenesis/hamcrest/jersey-test-framework/jacoco agent);
they enter the graph only through `hadoop-client-minicluster`'s
compile+optional test-jar support deps or through upstream SDK POMs
declaring test tooling at compile scope (tencent's ini4j). These prunes
remove the manual-baseline side of that curation; per R39, absence from the
assembled archive must still be confirmed by the first Stage-2 ground-truth
run (R26) — an exclusion that turns out to ship SHALL fail the archive gate.

| Entry | Origin | Action |
|---|---|---|
| `org.glassfish.jersey.test-framework:jersey-test-framework-core:2.46` | minicluster test support | pruned |
| `org.glassfish.jersey.test-framework.providers:jersey-test-framework-provider-jdk-http:2.46` | minicluster test support | pruned |
| `org.jacoco:org.jacoco.agent:0.8.5` | aliyun SDK POM, compile scope | pruned |
| `org.ini4j:ini4j:0.5.4` | tencent COS SDK POM, compile scope | pruned |

The EPL 1.0 section contained only `junit` and `org.jacoco.agent`; with both
pruned the empty section was dropped (R32).

### Build tooling

| Entry | Evidence | Action |
|---|---|---|
| `ro.isdc.wro4j:wro4j-maven-plugin:1.8.0` | build-time resource optimizer of `hadoop-yarn-project/hadoop-yarn/hadoop-yarn-ui/pom.xml:274-275` | pruned |

### Removed or superseded upstream dependencies

| Entry | Evidence | Action |
|---|---|---|
| `com.aliyun:aliyun-java-sdk-sts:3.0.0` | no pom in the reactor declares it; the inventory carries core/kms/ram/oss via `hadoop-tools/hadoop-aliyun` | pruned |
| `com.cedarsoftware:java-util:1.9.0` | explicitly POM-excluded from `fst` in `hadoop-yarn-server-applicationhistoryservice/pom.xml:216` | pruned |
| `com.cedarsoftware:json-io:2.5.1` | not a resolved dependency of `fst:2.50`; absent from the inventory | pruned |
| `com.microsoft.azure:azure-storage:7.0.1` | no pom reference remains; `hadoop-azure` moved to azure-cosmosdb / azure-data-lake-store-sdk (both in the inventory) | pruned |
| `com.microsoft.azure:azure-keyvault-core:1.0.0` | transitive of the retired azure-storage; absent from the inventory | pruned |
| `com.sun.xml.bind:jaxb-impl:2.2.3-1` | old coordinate of the JAXB runtime; superseded by `org.glassfish.jaxb:jaxb-runtime:2.3.9` (in the inventory, listed in the EDL section) | pruned |
| `com.thoughtworks.paranamer:paranamer:2.3` | historic avro transitive; only a `paranamer-ant` exclusion remains in `hadoop-mapreduce-client/pom.xml:68-70`; absent from the inventory | pruned |
| `io.opencensus:opencensus-contrib-grpc-metrics:0.12.3` | transitive of the old grpc stack; the current grpc 1.69/1.70 graph does not carry it (opencensus-api/http-util 0.31.1 remain in the inventory) | pruned |
| `javax.servlet.jsp:jsp-api:2.1` | POM-excluded from jetty in `hadoop-common-project/hadoop-kms/pom.xml:103-119` | pruned |
| `org.apache.hbase:hbase-{annotations,client,common,protocol}:2.5.8` (4) | unshaded coordinates no longer in the graph; the timeline service now uses `hbase-shaded-client-byo-hadoop:2.6.3-hadoop3` (in the inventory). The shaded jar embeds the unshaded artifacts — per R37 the archive's view (one jar) wins once R26 runs | pruned |
| `org.apache.htrace:htrace-core:3.1.0-incubating`, `htrace-core4:4.1.0-incubating` | no reference anywhere in the reactor | pruned |
| `org.jruby.joni:joni:2.1.2` | absent from the inventory; jcodings 1.0.13 remains (carried by the hbase shaded client) | pruned |
| `org.ow2.asm:asm:5.0.4` | absent from the inventory; hadoop actively excludes `org.ow2.asm:asm` from its mapreduce/jetty dependencies (`hadoop-project/pom.xml:933-940`); asm-commons/asm-tree 9.7.1 remain (jersey/hk2) | pruned |
| `net.minidev:accessors-smart:1.21` | json-smart transitive of an older nimbus-jose-jwt; nimbus 10.4 (in the inventory) no longer depends on json-smart; absent from the inventory | pruned |

## 2. Fixed malformed entries (R30)

| Old entry | Fixed to | Why |
|---|---|---|
| `com.google.code.gson:2.9.0` | `com.google.code.gson:gson:2.9.0` | groupId:version — no artifactId |
| `com.google:guice:5.1.0` | `com.google.inject:guice:5.1.0` | wrong groupId (in inventory under the real one) |
| `com.google:guice-servlet:5.1.0` | `com.google.inject.extensions:guice-servlet:5.1.0` | wrong groupId |
| `com.google.json-simple:json-simple:1.1.1` | `com.googlecode.json-simple:json-simple:1.1.1` | wrong groupId |
| `com.jamesmurty.utils:java-xmlbuilder-1.2.jar` | `com.jamesmurty.utils:java-xmlbuilder:1.2` | version glued to the artifactId, trailing `.jar` |
| `jakarta.ws.rs-api:jakarta.ws.rs-api:2.1.6` | `jakarta.ws.rs:jakarta.ws.rs-api:2.1.6` | wrong groupId |
| `org.apache.commons:commons-digester:1.8.1` | `commons-digester:commons-digester:1.8.1` | the shipping artifact uses the old-style coordinates (that is what the inventory resolves) |
| `org.apache.commons:commons-validator:1.6` | `commons-validator:commons-validator:1.6` | same |
| `:jar:` / trailing `.jar` noise | `com.squareup.okhttp3:okhttp:3.14.2`, `com.squareup.okio:okio:1.17.2`, `com.volcengine:ve-tos-java-sdk-hadoop:2.8.9`, `io.opentracing:*:0.33.0`, `org.reactivestreams:reactive-streams:1.0.3`, `org.dom4j:dom4j:2.1.4` | classifier fragments and `.jar` suffixes removed so every entry is a clean `g:a:v` |

## 3. Version alignment (R31)

Aligned to the versions the generated inventory actually resolves (full
per-entry version audit stays open until R26 compares against the tarball):

| Entry | Change |
|---|---|
| `com.google.api.grpc:proto-google-common-protos` | `1.0.0` → `2.48.0` (inventory has 2.48.0 + 2.55.2) |
| `com.google.guava:failureaccess` | `1.0, 1.0.2` → `1.0.1, 1.0.2, 1.0.3` |
| `com.google.guava:guava` | added `33.4.0-jre` next to `33.4.8-jre` (both resolve in the reactor) |
| `com.google.j2objc:j2objc-annotations` | dropped the duplicate stale `1.3` line (inventory has only 3.0.0) |
| `org.checkerframework:checker-qual` | dropped stale `3.8.0` (inventory has only 3.49.0) |
| `org.ow2.asm:asm-commons` / `asm-tree` | `6.0` → `9.7.1` |

## 4. Kept with a parity-gate exception

| Entry | Why it stays |
|---|---|
| `org.hsqldb:hsqldb:2.7.1` | test (jobclient) / provided (mapreduce-examples) scope in the poms, but shipped by explicit assembly includes: `hadoop-assemblies/.../hadoop-mapreduce-dist.xml:191` and `hadoop-yarn-dist.xml:328`. This is the known "assembly-included jar off the compile/runtime graph" case (R2 scope-policy gap). |

Mechanism: new file `dev-support/licenses/assembly-includes` lists such
jars (g:a + `#` justification). `check-licenses-parity.sh` takes it as an
optional third argument: entries there are reported as expected absences
and do not fail the gate; an entry that shows up in the generated inventory
is a stale exception and fails the gate; the gate still fails without the
argument. CI (`licenses.yml`) passes the file.

## Verification

- `bash dev-support/licenses/check-licenses-parity.sh <run-42362507643 THIRD-PARTY.txt> LICENSE-binary dev-support/licenses/assembly-includes`
  → "Parity gate passed", exit 0 (manual manifest: 250 g:a pairs; generated: 313).
- Same invocation without the third argument → fails on `org.hsqldb:hsqldb` only (backwards-compatible strict mode).
- Stale-exception self-test (bogus `com.google.code.gson:gson` entry) → "STALE assembly-includes entries", exit 1.
- `bash -n` on the modified script passes.

## Follow-ups

- R39/R26: the Stage-2 dist run must confirm the four `excludedArtifacts`
  prunes (junit, hamcrest, objenesis, jersey-test-framework, jacoco agent,
  ini4j) and hsqldb's presence actually match the assembled archive; any
  divergence reopens these rows.
- `org.checkerframework:checker-qual:3.49.0` sits in the BSD 3-Clause
  section, but its POM and the inventory say MIT License — reclassify the
  section when the multi-license policy work (R28) touches sections.
- `licenses-binary/` may now hold texts orphaned by the prunes (e.g. the
  EPL 1.0 text); handle via R10 drift detection or when the manual files
  retire (Stage 3), not by hand.
- Only disputed/multi-version entries were version-audited; a systematic
  manifest-vs-inventory version diff belongs to the R26/R31 archive run.
- The 63 inventory entries not in the manual manifest (the INFO direction)
  are expected: the automated collection surfaces what the manual process
  missed; they fold into the R40 generated manifest.
