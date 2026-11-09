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
# Cloud-tarball gating and shaded-jars curation, 2026-11-07 ~15:00

Stage-2 convergence pass after the first green archive run
(42380708044; see 2026-11-07-1430-Archive-Ground-Truth-First-Run.md).
The 93-entry worklist split into three evidence-based categories, and
the second distributed archive is now built and gated.

## 1. The cloud-storage archive is now built and gated

- The `licenses-dist` workflow's Docker build adds the eight
  `-Dhadoop-*-package` flags (aliyun, aws, azure-datalake, bos, cos,
  gcp, huaweicloud, tos). The package profiles add the cloud modules at
  compile scope without the transitive exclusions the always-on
  dependencies carry, so the cloud-storage dist ships the SDK trees
  (aliyun-oss, aws-sdk-bundle, azure-data-lake, cos_api-bundle,
  esdk-obs-java, ve-tos, bce-java-sdk, google-cloud family).
- The cloud dist produces a DIRECTORY (dir-format assembly), not a
  tarball — the workflow tars it before gating so the archive gate
  treats it as the distributed archive it is.
- **R38 finding fixed in the assembly**: hadoop-cloud-storage.xml
  shipped no license file at all. The assembly now copies
  LICENSE-binary, NOTICE-binary and licenses-binary/ into the archive
  root, exactly as dist-layout-stitching does for the main dist.

## 2. The "shaded into hadoop-gcp" premise was wrong

Package listing of the real hadoop-gcp jar: only its own
com/google/cloud/hadoop and org/apache/hadoop/fs classes — no relocated
google-cloud/grpc/opencensus. The v2.1 analysis ("hadoop-gcp shading
opencensus and google-cloud classes into itself") was incorrect; those
coordinates are hadoop-gcp's Maven dependencies and ship in the
cloud-storage dist. The google family was already fully listed in
LICENSE-binary, so no entries were needed for it.

## 3. hadoop-client-runtime is the real shading site

Its jar embeds hadoop-shaded-protobuf_3_25 (protobuf relocated to
org.apache.hadoop.thirdparty.protobuf — embedded pom.properties
evidence) and a large set of unrelocated runtime deps (kerby x7, jline
x11, jetty, avro, jackson, gson, nimbus, dnsjava, jsch, ...) whose
standalone jars then do not ship. Curated into
`dev-support/licenses/shaded-jars`: protobuf-java and protobuf-java-util
→ embedded in hadoop-client-runtime.

## 4. LICENSE-binary additions

- org.apache.httpcomponents.core5:httpcore5-h2:5.4.3 (Apache-2.0;
  ships with the httpclient5/httpcore5 set)
- javax.ws.rs:jsr311-api:1.1.1 (CDDL; ships via the cloud dist's
  jersey/azure stack) — placed in the CDDL+GPLv2-CE section following
  the javax.json precedent; section choice provisional pending R28.

The rest of the worklist's cloud-side entries (aliyun, aws, azure,
baidu, cos, huawei, tos, volcengine, google family, okhttp/okio,
opentracing, threetenbp, joda-time, java-xmlbuilder, dom4j, jdom2,
httpasyncclient, reactive-streams) were already listed in
LICENSE-binary.

## Verdict after curation (re-gated against run 42405080846's own data)

Both archives: **R36/R38/R39 = 0** — every shipped jar in both tarballs
is licensed and no curated exclusion ships. Remaining:

- **R26 (transient, self-resolving):** org.ini4j:ini4i and
  org.jacoco:org.jacoco.agent are absent from that run's inventory
  because the exclusions were still active in its pom; this commit
  removes them, so the next per-push inventory carries both and the
  parity/archive gates go green.
- **R31 (benign version-string mismatches):**
  google-api-services-storage 2.0.0 (filename form) vs
  v1-rev20250420-2.0.0 (POM form); the EclipseLink OSGi build stamps;
  org.jacoco.agent 0.8.5-runtime (classifier form) vs 0.8.5.
- **Parity:** fails only on the same two transient entries.
- **WORKLIST:** 93 → the cloud-SDK entries now ship in the gated cloud
  archive; the remaining non-shippers (kerby non-embedded set, jmh,
  checker-qual, conscrypt, kfs, ...) are the R32 prune worklist for the
  next pass.

## Backlog for the next convergence pass

After the cloud run gates, whatever remains in the worklist on BOTH
archives is declared-but-not-shipped and becomes the R32 prune
worklist — expected candidates: the kerby set not embedded in
hadoop-client-runtime (kerb-admin, kerb-client, kerb-common,
kerb-identity, kerb-server, kerb-simplekdc, kerby-xdr,
token-provider), jmh-core/jmh-generator-annprocess, checker-qual,
conscrypt-openjdk-uber, net.sf.kosmosfs:kfs, and any other entry
absent from both tarballs. Prune only after the cloud run confirms
absence.
