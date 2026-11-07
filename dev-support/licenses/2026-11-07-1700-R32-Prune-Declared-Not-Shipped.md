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
# R32 prune: declared-but-not-shipped entries, 2026-11-07 ~17:00

Final Stage-2 convergence pass. With BOTH distributed archives gated
(run 42413534907 on ab8af7d7d5d, green: main 302 + cloud 129
third-party GAs, 0 partial/unmapped), the declared-but-not-shipped set
is exactly: LICENSE-binary g:a entries absent from BOTH archives'
enumerations and absent from the shaded-jars embedded set.

Method: union of both archive TSVs (with archive-jar-mappings promotion
applied) diffed against the manifest's g:a pairs, minus the
shaded-jars embedded coordinates.

## Pruned (10 entries)

- **org.apache.kerby 8**: kerb-admin, kerb-client, kerb-common,
  kerb-identity, kerb-server, kerb-simplekdc, kerby-xdr,
  token-provider — declared via the KDC/minikdc support path but
  neither shipped standalone nor embedded. The seven kerby jars that
  ARE embedded unrelocated in hadoop-client-runtime (kerb-core,
  kerb-crypto, kerb-util, kerby-asn1, kerby-config, kerby-pkix,
  kerby-util) stay listed — their classes ship inside that jar.
- **javax.ws.rs:jsr311-api:1.1.1** — added in the cloud pass on the
  assumption it ships via the cloud jersey stack; the enumeration
  says it does not.
- **org.glassfish.jersey.containers:jersey-container-jdk-http:2.46** —
  in the graph, absent from both archives (the other jersey containers
  do ship).

## Verified remaining

After the prune, every manifest g:a is either enumerated in an archive
or recorded as embedded (protobuf-java/-util) — the manual manifest is
now exact against the two distributed archives. The parity gate is
unaffected (pruned entries were inventory-covered or absent; verified
green against run 42413534907's inventory).

Manifest: 302 g:a pairs (was 312).
