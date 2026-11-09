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
# R28 multi-license policy application, 2026-11-07 ~16:30

Applied the curated multi-license policy
(`dev-support/licenses/Multi-License-Policy.md`, requirement 28) to the
shipped manifest, based on the full multi-license survey of the
inventory (run 42409351098, 314-GA inventory):

- **jakarta.activation:jakarta.activation-api:1.2.1** moved from
  BSD 3-Clause to the EDL 1.0 section — its jar's META-INF/LICENSE.md is
  the Oracle EDL (BSD-3-clause-shaped with Oracle copyright), matching
  com.sun.activation:jakarta.activation:1.2.2 already in EDL. Evidence:
  the artifact's own pom (Eclipse Distribution License) and embedded
  LICENSE.md.
- **org.checkerframework:checker-qual:3.49.0** moved from BSD 3-Clause
  to MIT — its pom declares "The MIT License" and the inventory
  resolves it as MIT. (Its stale 3.8.0 duplicate was already removed in
  the 2026-11-07 curation pass.)
- Everything else already conforms to the policy: jetty family and jna
  under Apache-2.0 (rule 1 duals), eclipse-collections and EclipseLink
  under EDL (rule 2), the jakarta duals under EPL 2.0 (rule 3), the
  jersey+hk2 family in the combined section (rule 3 exception),
  HdrHistogram under BSD 2-Clause, javassist under Apache-2.0 (rule 1
  triple).
- jsr311-api (plain CDDL 1.0) stays in the CDDL+GPLv2-CE section, which
  the policy defines as covering the CDDL family.

No g:a or version changed — the parity and archive gates are unaffected
(verified: parity green against run 42409351098's inventory).
