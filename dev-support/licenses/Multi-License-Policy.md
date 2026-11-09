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
# Multi-license policy (requirement 28)

Artifacts that ship under several alternative licenses are listed in
LICENSE-binary under ONE of them, chosen by the rules below. The rules
are applied in order; the first that matches decides the section. Every
deviation from a rule needs a recorded justification (dated record in
this directory).

1. **Prefer Apache-2.0** when the artifact is dual-licensed Apache-2.0 +
   X. Rationale: the ASF already distributes Apache-2.0 text in every
   archive's top-level LICENSE, so no extra section or text is needed.
   Applies to the jetty family (EPL-1.0 + Apache-2.0), jna (LGPL-2.1 +
   Apache-2.0), javassist (LGPL-2.1 + MPL-1.1 + Apache-2.0).
2. **Prefer EDL 1.0** for Eclipse dual-licensed artifacts (EDL + EPL).
   Rationale: EDL is the Eclipse Foundation's standard BSD-3-style
   license for these projects and the text already ships in the
   licenses-binary store. Applies to eclipse-collections (EDL + EPL-1.0)
   and EclipseLink asm/core/moxy (EDL + EPL-2.0).
3. **Prefer EPL 2.0** for Jakarta/glassfish duals (CDDL+GPLv2-CE + EPL-2.0).
   Rationale: EPL-2.0 is the modern designation for the jakarta family.
   Applies to jakarta.annotation-api, jakarta.json-api, jakarta.ws.rs-api,
   jakarta.servlet-api, jakarta.servlet.jsp-api.
   - Exception: the jersey family and its hk2 runtime stay in the
     combined "EPL 2.0 with some parts being GPLv2-CPE / Apache-2.0 /
     Public Domain" section — jersey's NOTICE.md requires the mixed
     statement, and the hk2 jars are part of that runtime.
4. **Prefer the more permissive single text** for triples with no Apache
   option (none currently; recorded for completeness).
5. **Single-license artifacts** are always listed under their true
   license regardless of the section they historically sat in:
   - checker-qual is MIT (moved out of BSD 3-Clause, 2026-11-07)
   - jakarta.activation-api is EDL 1.0 (moved out of BSD 3-Clause,
     2026-11-07 — the EDL text is BSD-3-clause-shaped with an Oracle
     copyright; the EDL section is its precise home)
   - jsr311-api is plain CDDL 1.0 and stays in the CDDL+GPLv2-CE
     section, which by policy covers the CDDL family (1.0/1.1, with or
     without the GPLv2-CE companion)

The R40 archive-derived manifest generator (Stage 3) applies this
same table when it assigns sections (`NAME_TO_SECTION` +
`section_for` in `generate-archive-manifest.py`, fail-closed on
unknown license names). Both branch manifests — trunk's and the
`feat/LICENSES-3.5` port — were produced by it, so the generated
output and this policy cannot drift.
