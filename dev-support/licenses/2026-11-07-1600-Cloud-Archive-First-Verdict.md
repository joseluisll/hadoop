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
# Cloud-archive first verdict and its curation, 2026-11-07 ~16:00

Triage of the first cloud-gated ground-truth run (42405080846, commit
1ada6a4bf9f — first run with the eight -Dhadoop-*-package flags; the
opentelemetry DependencyConvergence conflict it initially hit was fixed
in hadoop-cloud-storage-dist/pom.xml by excluding io.opentelemetry:* from
the hadoop-aliyun profile dependency, google-cloud's 1.47.0 winning).
The Docker build then succeeded and the gates ran on both archives:

- main hadoop-3.6.0-SNAPSHOT: 271 third-party g:a, 80 own, 31 partial,
  0 unmapped (was 221/78/129 — the SDK trees stitched into the main
  archive through the cloud dist)
- cloud hadoop-cloud-storage-3.6.0-SNAPSHOT: 98 third-party g:a, 9 own,
  31 partial, 0 unmapped

## R39 verdicts (both flip on real evidence)

- **org.jacoco.agent ships** — `share/hadoop/common/lib/org.jacoco
  .agent-0.8.5-runtime.jar` in BOTH archives (aliyun SDK's compile-scope
  agent, classifier-form filename). The first run never verified this
  (the R39 check was dead then). **Action:** un-excluded from
  excludedArtifacts, listed under a re-created EPL 1.0 section.
- **org.ini4j:ini4j ships** — in both archives via the tencent COS
  module's compile tree once the package flags are on (it was
  test-tooling only without them). **Action:** un-excluded, listed in
  the Apache section (Apache-2.0 per its pom).

## LICENSE-binary corrections and additions

- **com.qcloud:cos_api-bundle:5.6.19** — the manual carried it as the
  malformed name-line `cos_api-bundle-5.6.19.jar` under MIT; the
  inventory resolves it Apache-2.0. Replaced with a proper g:a:v line in
  the Apache section (both 5.6.19 and 5.6.69 exist in the inventory;
  5.6.19 is the confirmed shipped version).
- **com.google.cloud:google-cloud-storage:2.52.0** — new entry: it ships
  in both archives now and was never listed (first-run worklist entry).
- Version additions: com.aliyun.oss:aliyun-sdk-oss 3.18.1 (the branch
  bumped it from 3.13.2 — both kept pending a run confirming 3.13.2
  does not ship), httpclient5 5.6.3 (manifest had only 6.3),
  grpc-protobuf-lite 1.70.0, opentelemetry-api/context 1.47.0.

## archive-jar-mappings: +31 entries

The SDK trees ship the same metadata-less jars the first run saw in
isolation (Gradle-built google/opentelemetry/cloud-opentelemetry family,
grpc gcp-stack copies without META-INF/maven, checker-qual, conscrypt,
dom4j, jdom2, reactive-streams, protobuf-java-util, the jacoco agent's
classifier-form filename, api-common, google-api-services-storage with
its -rev suffix). All curated; the mappings are version-independent.

## Remaining after this pass

- The kerby artifacts not embedded in hadoop-client-runtime (kerb-admin,
  kerb-client, kerb-common, kerb-identity, kerb-server,
  kerb-simplekdc, kerby-xdr, token-provider), jmh-core and
  jmh-generator-annprocess, and any other entry absent from BOTH
  tarballs are declared-but-not-shipped — R32 prune candidates pending
  the next run's confirmation.
- The cloud dist still needs a NOTICE review of its own (it now carries
  NOTICE-binary, which was authored for the main archive) — fold into
  the R28/R14 pass.
