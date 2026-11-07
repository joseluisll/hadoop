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
# First archive ground-truth run: triage and curation, 2026-11-07 ~14:30

Triage of the first `Archive license ground truth` run (42374519973,
commit d7919446fe3; Docker dist build + inventory succeeded, gates ran
on the real `hadoop-dist/target/hadoop-3.6.0-SNAPSHOT.tar.gz`):
264 jars enumerated — 186 third-party g:a, 78 own `org.apache.hadoop`
jars, 129 partial (no Maven metadata), 0 unmapped. This record covers
every change made in response, per the curation-record rule.

## What the run found

- **R39 confirmed, with one violation.** None of the curated
  `excludedArtifacts` (mockito, junit, hamcrest, jersey-test-framework,
  jacoco agent, ini4j, jopt-simple) ships in the archive — except
  **objenesis**, which ships in `share/hadoop/yarn/lib/objenesis-2.6.jar`
  (it reaches the graph through the hadoop-client-minicluster compile-
  scope support path and the yarn dist assembly; guice's POM does not
  declare it). The 2026-11-07 LICENSE-binary curation had pruned
  objenesis as test tooling; the archive says otherwise. **Action:** the
  exclusion is removed from the root pom (`pom.xml` excludedArtifacts)
  and `org.objenesis:objenesis:2.6`
  (Apache-2.0, verified from the jar's own META-INF/LICENSE) is listed
  in LICENSE-binary again. The archive's word wins — this is R39/R26
  working as designed.
- **R38: 48 jars shipped whose license LICENSE-binary did not state.**
  47 were genuine coverage gaps of the manual manifest (the
  bundled-but-unlisted class from pjfanning/hadoop#116, now measured
  exactly); 1 (HikariCP) was a gate bug (see below). All 47 + the
  mapped-partial set below are now listed in LICENSE-binary with the
  licenses the THIRD-PARTY inventory resolved.
- **R36: 129 partial jars.** Two systematic causes: (a) the dist ships
  ~44 modules' `-sources`/`-test-sources` jars, which carry no
  META-INF/maven; (b) a set of third-party jars is published without
  Maven metadata at all — Gradle-built artifacts (guice, caffeine,
  okhttp, kafka-clients, jna, objenesis) and bouncycastle/OSGi bundles
  never carry pom.properties, and hadoop-client-runtime's 71 embedded
  pom.properties are all embedded artifacts' (none its own). All are
  now curated in `dev-support/licenses/archive-jar-mappings`
  (identity-only entries; versions come from the jars, so bumps do not
  rot them).
- **R31: version drift.** Genuine: commons-beanutils 1.9.2 ships
  (manifest had only 1.9.4), audience-annotations 0.12.0 ships (manifest
  had only 0.5.0), error_prone_annotations 2.30.0 ships, both
  zookeeper-jute 3.6.2 and 3.8.6 ship, opentelemetry-api/context 1.49.0
  ship (next to 1.59.0), jackson-datatype-jsr310 2.16.0 ships. All
  added; the older manifest versions are kept until a later run
  confirms they do not ship. The remaining ~60 R31 lines were case
  noise (see gate fixes).
- **R26: 2 off-graph jars** — both were the case bug (HikariCP,
  HdrHistogram are in the inventory under mixed-case artifactIds).
  After the case fix: zero genuine off-graph jars beyond the curated
  hsqldb assembly include.

## Gate bugs found by the run and fixed

1. **R39 silently dead in real runs.** The `sed -n 's/.../p;q'`
   extraction for `excludedArtifacts` quits after line 1 of pom.xml
   (`q` is unconditional), yielding an empty pattern — the R39 check
   was skipped entirely in the dist run. Fixed with an awk extraction
   (print-and-exit). This is how objenesis slipped through.
2. **Case-inconsistent g:a comparison.** The enumeration lowercases
   g:a; the manifest/inventory parsing preserved the artifactId's case,
   so mixed-case artifacts (HikariCP, HdrHistogram, netty `Final`
   versions) mismatched — producing the two phantom R26 failures, one
   phantom R38, and most of the R31 noise. Both gates now compare
   case-insensitively on both sides.
3. **Hyphenated versions mis-split.** `zstd-jni-1.5.7-8.jar` parsed as
   artifact `zstd-jni-1.5.7`, version `8`. The filename parser now
   extends left while the preceding segment also starts with a digit.
4. **Artifact bloat.** The workflow uploaded the extracted tarballs
   (~1 GB) because the untarred dirs lived under the upload path.
   Uploads are now restricted to the TSVs, gate logs and inventory.

## Entries added to LICENSE-binary (R38/R31/R39 response)

Apache-2.0: jackson-datatype-jsr310 2.16.0, com.google.android:annotations
4.1.1.4, jsr305 3.0.2, error_prone_annotations 2.30.0, flatbuffers-java
23.5.26, commons-beanutils 1.9.2, commons-lang 2.6, commons-logging 1.3.0,
metrics-core 3.2.4, netty-handler-ssl-ocsp, jakarta.validation-api 2.0.2,
arrow-format/memory-core/memory-netty/vector 15.0.2,
hbase-shaded-client-byo-hadoop 2.6.3-hadoop3, httpmime 4.5.13,
audience-annotations 0.12.0, zookeeper-jute 3.6.2 + 3.8.6,
jsonschema2pojo-core 1.0.2, jspecify 1.0.0, objenesis 2.6,
jcl-over-slf4j 1.7.36, javassist 3.30.2-GA (LGPL/MPL/Apache triple —
listed under the Apache option pending the R28 multi-license policy),
jetty alpn-client/alpn-java-client/client, jetty.http2 x4, jetty.websocket
x5 (EPL-1.0/Apache dual, following the existing jetty precedent),
opentelemetry-api/context 1.49.0, perfmark-api 0.27.0.
CDDL+GPLv2-CE: codemodel 2.6, javax.websocket-client-api 1.0,
org.glassfish:javax.json 1.1.4. EDL 1.0: jakarta.activation 1.2.2,
istack-commons-runtime 3.0.12, eclipse-collections(+api) 11.1.0,
org.eclipse.persistence asm/core/moxy, txw2 2.3.9. EPL 2.0:
jakarta.annotation-api 1.3.5, jakarta.json-api 1.1.6. Jersey section:
hk2 x6 (api/locator/utils/osgi-resource-locator + external
aopalliance-repackaged/jakarta.inject). BSD 2-Clause: HdrHistogram 2.1.12.

Section placement for dual/triple-licensed entries is first-license or
existing-precedent and is provisional until the R28 multi-license
policy is curated.

## Backlog (not failing, tracked)

- **Known-benign R31 warnings after this pass:** the EclipseLink
  core/moxy jars report OSGi build-stamp versions
  (`2.7.14.v20231208-d05cebc9b0`) from their manifests where the
  manifest lists `2.7.14` — advisory only. grpc-util 1.69.0 (csi/lib)
  is now listed alongside 1.70.0.
- **WORKLIST (~127 inventory GAs without a standalone jar in this
  archive):** cloud-store SDKs (aliyun, baidu, huawei, cos, volcengine,
  azure-data-lake) ship only in the cloud-storage tarball, not in this
  one; google-cloud/opencensus/gax coordinates are shaded into
  hadoop-gcp (R37 mapping to curate in `shaded-jars`); grpc 1.70
  resolves via the csi 1.69 jars and worklist-side entries. This is the
  Stage-2 convergence worklist for the next runs.
- jakarta.activation-api sits in the BSD 3-Clause section of
  LICENSE-binary though its license is Apache-2.0 (pre-existing
  misplacement) — fix with the R28 section pass.
- commons-beanutils 1.9.4 / audience-annotations 0.5.0 may not ship;
  drop when a run confirms.
