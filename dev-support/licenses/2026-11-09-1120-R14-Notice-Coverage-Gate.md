<!--
  Licensed to the Apache Software Foundation (ASF) under one or more
  contributor license agreements.  See the NOTICE file distributed with
  this work for additional information regarding copyright ownership.
  The ASF licenses this file to You under the Apache License, Version 2.0
  (the "License"); you may not use this file except in compliance with
  the License.  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->
# R14 — NOTICE-coverage gate: attribution-required components are enforced per push (2026-11-09 11:20 CET)

Requirement: R14 (NOTICE accuracy for attribution-required licenses).
Work item T00006. Owner-scoped design, chosen after a feasibility probe
made the original pick impossible to land honestly.

## Why the coverage gate, not a strict mention gate

A strict gate (every attribution-required component must be *mentioned*
in NOTICE-binary) was probed first: 71 of 75 attribution-required
components have no NOTICE-binary mention and no component text — curing
it literally means authoring ~70 attribution entries of legal prose by
hand, exactly the corpus the project earlier decided cannot be derived
from metadata. The owner re-scoped: coverage over the shipped corpus.

## The gate (in `check-asset-manifest.py`, per push, gate 4)

Every component line (`g:a:v`) of a titled, attribution-required
LICENSE-binary section — all but Public Domain — is covered when:

1. **NOTICE mention** — the artifactId (or a `notice-aliases` phrase)
   appears in NOTICE-binary as a whole word, case-insensitive;
2. **Copyright-carrying text** — a shipped component text whose R13
   reference token (slug or component-kind alias token) matches the
   component's manifest line contains a copyright line (the text ships
   with the tarball and carries the component's attribution);
3. **Exception row** — `notice-exceptions` records the artifactId with
   a justification (requirement 52: the justification is mandatory).

Fail-closed both directions: an uncovered component without a row
fails, and an exception row whose component gained NOTICE mention or a
copyright-carrying text is stale and fails too — new components are
enforced immediately and the legacy rows burn down. The empty-files
case is a failure (no vacuous pass): both curation files must exist,
the parse is strict (tab-separated, no duplicate tokens, non-empty
justifications).

## Curation

- `notice-aliases` — starts empty (probed: NOTICE-binary's javax.*
  entries are different coordinates, not aliases for the jakarta.*
  components); rows are added only when a component is genuinely
  mentioned under another surface form.
- `notice-exceptions` — 36 rows, one per legacy gap, grouped by
  section: the jersey/hk2 combined family (attribution carried by the
  combined LICENSE-binary statement per R28), and the EDL/EPL-2.0/
  CDDL/BSD/MIT components whose section's generic text ships without a
  per-component copyright line. Every row's burn-down path is a
  component text carrying the component's own copyright line (or a
  NOTICE-binary entry).

## Validation

- Real tree: 75 attribution-required components — 39 covered by NOTICE
  mention or copyright-carrying text, 36 by exception rows; all four
  per-push gates exit 0.
- Synthetic probes (on a copy in /tmp, never the working tree): the
  baseline synthetic tree reports 39+36; dropping one exception row
  fails that component; a bogus exception row fails as stale; an empty
  notice-exceptions file fails all 36. A probe that stripping the
  copyright line from LICENSE-protobuf.txt uncovers its components
  returned no failure — correctly: protobuf-java is covered by NOTICE
  mention, not by the text (mention-coverage verified, not a gate bug).
- An earlier probe-session anomaly ("baseline fails") was the other
  gates (R7 stage B / R48) failing on the stripped synthetic tree,
  which has no source tree — not an R14 issue.
- Independent review (fresh context, 2026-11-09) found one fail-open
  hole, fixed before landing: an empty token/phrase field in
  `licenses-binary-aliases`, `notice-aliases` or `notice-exceptions`
  built a vacuous whole-word pattern that matches anything, silently
  defeating the R53 and R14 gates (both exploits verified, then
  verified fixed). All curation parsers now fail closed on empty
  fields; a regression test covers the emitter path (22 tests); the
  review's minor findings (dead empty-file check order, hoisted
  alias-parser call, notice-alias staleness implemented as the header
  promised, comment/code alignment) are also in.

## Deliberately out of scope

- NOTICE-binary itself stays curated prose (no generation — its
  attribution corpus is not derivable from metadata); the gate enforces
  coverage, it does not write attributions.
- Asset (npm/native) lines of the manifest sections are not gated:
  their attribution rides the components' and the section texts; the
  gate scope is the component corpus. Revisit if a curation pass adds
  attribution-bearing asset entries.
- Synthetic-input self-tests for this gate (and the other gates) are
  the R49 work item (T00010).
