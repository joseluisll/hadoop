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
# R13 — Text bundling: the store becomes the single home, the tarball's `licenses-binary/` is generated (2026-11-09 11:10 CET)

Requirement: R13 (text bundling into `hadoop-dist`/`hadoop-assemblies`),
closing the R53 direction the 2026-11-08 gate left open. Work item
T00005; owner-approved design (option A, full store migration).

## What changed

- **Store migration.** The 66 hand-kept texts of the repo-root
  `licenses-binary/` moved into the versioned store
  `dev-support/licenses/texts/` (`git mv`), and the repo-root directory
  is gone (now generated, `.gitignore`d):
  - 62 texts moved verbatim;
  - 3 were byte-identical to store texts already present
    (`bouncycastle`, `cddl-gplv2-ce`, `jquery` — `cmp`-verified) and
    their copies were dropped;
  - `LICENSE-go.txt` (the RE2-derived component text for
    `com.google.re2j:re2j`) was renamed `LICENSE-re2j.txt` — the store's
    own `LICENSE-go.txt` is Google's plain Go license and stays the
    name-resolution target for "The Go license"; the re2j component
    ships the RE2-derived text.
- **The emitter** (`generate-archive-manifest.py`): a store text ships
  iff LICENSE-binary references it — its slug or its
  `licenses-binary-aliases` token appears as a whole word
  (case-insensitive). New modes: `--emit-licenses-dir-only --manifest
  <file> --licenses-dir <dir>` (derive-and-copy, no archive inputs) and
  `--licenses-dir` in full generation mode. Fail-closed: empty store or
  manifest, alias/generic row without its text, a slug both aliased and
  exempted, populated output directory, missing/empty store text, and —
  the R53 coverage direction — a manifest section no shipped text
  covers.
- **Curation files.**
  - `licenses-binary-aliases` gained a kind column
    (`slug<TAB>component|section<TAB>token`; two-field rows read as
    component). `component` rows must match today (staleness);
    `section` rows tie a section's generic text to its manifest title
    and ship whenever the section is present without being
    staleness-checked (a section may legitimately vanish with the
    dependency set and reappear). Section rows added: `bsd-2-clause`,
    `bsd-3-clause`, `edl-1.0`, `epl-1.0`, `epl-2.0`, `gplv2-ce`,
    `public-domain`. The `go` alias row is gone (the text is renamed
    `re2j`, whose slug matches `com.google.re2j:re2j` directly).
  - New `texts-generic` lists the resolve-store texts that never ship:
    `apache-2.0` (the manifest template carries the Apache text), `go`,
    `json` (the bare word inside the `javax.json` coordinate would
    falsely match the JSON.org text), `lgpl-2.1`, `mpl-1.1`, `w3c`.
- **R53 per-push gate** (`check-asset-manifest.py`): rewritten against
  the store — every component-specific text must still be referenced by
  LICENSE-binary (a stale text would ship, via the emitter, for a
  component that is gone); alias/text, texts-generic/text and
  alias/generic-overlap mismatches fail.
- **Dist wiring.**
  - `dev-support/bin/dist-layout-stitching` regenerates the directory
    from the committed LICENSE-binary into
    `target/licenses-binary-staged` and copies that into the layout
    (the main dist; `python3` is in the build-env image,
    `Dockerfile_ubuntu_24:55`).
  - `licenses-dist.yml` gained a pre-build step generating the
    directory at the repo root (the `hadoop-cloud-storage.xml` assembly
    copies `../../licenses-binary` during the reactor, before
    stitching runs).
  - The R40 drift step now also re-emits from the freshly generated
    manifest and diffs each tarball's shipped `licenses-binary/`
    against it (R53, dist side) — the shipped set must equal the
    referenced set on the archives of record, not only in the tree.

## Derived ship set vs the hand-kept directory

Emitting from the committed LICENSE-binary yields 73 texts: the
hand-kept 66, minus `go` (renamed `re2j`, which ships), plus 8 section
texts (`bsd-2-clause`, `bsd-3-clause`, `cddl`, `edl-1.0`, `epl-2.0`,
`gplv2-ce`, `mit`, `public-domain`) — each a section present in the
manifest whose components previously shipped with no generic license
text at all. `json` was investigated and excluded (false positive via
the `javax.json` coordinate); `epl-1.0` does not ship because the
manifest currently has no EPL-1.0 section, and its section row exists
so it ships again if one appears.

## Validation

- Synthetic: `test-generate-archive-manifest.py` extended to 22 tests —
  emitter happy path (slug, alias-token, section-alias, generic
  exemption), every fail-closed path (empty store, populated output
  dir, alias without text, texts-generic without text, alias/generic
  overlap, bad kind, section without text), and full-mode `--licenses-dir`
  emission (covered and uncovered sections). All pass.
- Real data: regenerating the manifest from the latest green dist run's
  artifact (run 42586639595, commit 292610f1445: inventory + both
  archives' TSVs) is byte-identical to the committed LICENSE-binary
  (R40 unchanged: 303 g:a, 317 version lines), and the emitter derives
  the 73-text set from it.
- Per-push gates green on the tree: `check-asset-manifest.py` (80
  texts: 67 checked, 6 exempted, 7 section rows) — including the R7
  stage B and R48 gates it shares the script with.
- `bash -n` on the stitching script; YAML parse on both workflows.
- Not yet exercised: a real dist run (Docker + approval). The next
  `dev-support/licenses/**` push triggers one; its new pre-build step,
  the stitching call and the R53 dist diff validate the wiring on real
  archives (the owner reports run completion; triage on that signal).

## Deliberately out of scope

- `NOTICE-binary` stays curated prose (R14): its attribution corpus is
  not derivable from metadata. R14's enforcement approach is a separate
  owner decision; a strict mention-gate probe on 2026-11-09 found 71 of
  75 attribution-required components with no NOTICE mention and no
  component text — recorded in the doc's status row pending that
  decision.
- `resolve-licenses.sh` is untouched: it resolves by license-NAME slug
  (`license-slugs.sh`), which the migration preserves; the moved
  component texts use slugs no license name maps to.
