# Automated license collection

Prototype for automating the collection and distribution of third-party
dependency licenses, complementing the hand-maintained `licenses/` and
`licenses-binary/` directories and the Apache RAT header checks.

## How it works

The root `pom.xml` defines a `licenses` profile that wires in
`org.codehaus.mojo:license-maven-plugin`:

- `aggregate-add-third-party` — builds the `THIRD-PARTY` inventory listing
  every (transitive) compile/runtime dependency with its resolved license.
- `aggregate-download-licenses` — *optional, opt-in only*: downloads
  license texts from the network. Used to update the local store, never
  part of the default flow.

**Offline-first:** license texts are project data. They live in
`texts/` (`LICENSE-<name>.txt`) and are resolved by
`resolve-licenses.sh`, which fails (with `--strict`) when a detected
license has no local text. License names are normalized via
`licenseMerges`; the canonical-name → file-slug mapping lives in
`license-slugs.sh`, shared by both scripts. Store provenance:
`bouncycastle` and `cddl-gplv2-ce` are copies of the repo's own
`licenses-binary/` texts, `edl-1.0` is the canonical eclipse.org plain
text, and `gplv2-ce` is the JMH project's COPYING (GPLv2 plus the
Classpath Exception); the rest were seeded from SPDX and upstream
sources.

## Usage

```bash
# the aggregate goals resolve artifacts from the local repository,
# so the modules must be installed first (full reactor for full coverage)
mvn install -DskipTests -Dmaven.javadoc.skip=true
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-add-third-party
dev-support/licenses/resolve-licenses.sh \
  target/third-party/THIRD-PARTY.txt \
  dev-support/licenses/texts \
  target/licenses-resolved --strict
```

For a quick local iteration over a single module:

```bash
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-add-third-party \
  -pl hadoop-common-project/hadoop-common -am
```

To refresh the local store from the network (rare, reviewed in a PR):

```bash
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-download-licenses
dev-support/licenses/normalize-licenses.sh target/licenses /tmp/downloaded
# review /tmp/downloaded, then copy vetted texts into texts/
```

## CI

`.github/workflows/licenses.yml` installs the full reactor (no skipped
modules), builds the `THIRD-PARTY` inventory, resolves texts from the
local store (`--strict`), fails when the committed `LICENSE-binary`
(the archive-derived artifact of record, requirement 40) drifts from
the last ground-truth run's generated manifest (requirement 10), and
uploads everything as workflow artifacts — all offline. Downloading
from the network runs only when explicitly requested via the
`workflow_dispatch` `download` input.

## Archive ground truth (weekly / on demand)

`.github/workflows/licenses-dist.yml` (requirement 35) assembles the
binary tarball in the Docker build environment, then enumerates every jar
in it — including jars nested inside WARs (requirements 26, 27, 36) —
and gates each archive against:

- the `LICENSE-binary` the archive itself ships (requirement 38, the
  compliance direction: a shipped jar whose license the archive's
  license file does not state is a failure),
- the graph inventory `THIRD-PARTY.txt` (requirement 26), with
  `assembly-includes` as the expected off-graph exception,
- the root pom's `excludedArtifacts` curation (requirement 39: a curated
  exclusion that turns out to ship is a failure),
- the `shaded-jars` mapping (requirement 37) for graph entries shaded
  into top-level jars.

The tools also run standalone against any tarball or exploded layout:

```bash
python3 dev-support/licenses/enumerate-archive-jars.py \
  hadoop-dist/target/hadoop-<version>.tar.gz -o archive-jars.tsv
dev-support/licenses/check-archive-licenses.sh \
  archive-jars.tsv <extracted>/hadoop-<version>/LICENSE-binary \
  target/third-party/THIRD-PARTY.txt
```

The shipped `LICENSE-binary` itself is generated (requirement 40) from
the archives' enumerations plus the inventory, with the multi-license
policy of `Multi-License-Policy.md` applied in code. To regenerate it
against a ground-truth run's artifacts:

```bash
python3 dev-support/licenses/generate-archive-manifest.py \
  --inventory <run>/third-party/THIRD-PARTY.txt \
  --archive-tsv <run>/archive-ground-truth/*/archive-jars.tsv \
  --out LICENSE-binary
```

The dist workflow runs this generation itself and fails on any diff
against the committed file (the R40 drift gate); the per-push workflow
fails when the committed file drifts from the last successful run's
generated manifest (R10). Regenerate and commit — never hand-edit.

## Curation files

- `override-THIRD-PARTY.properties` — license overrides for dependencies
  with missing or wrong POM metadata
  (`groupId--artifactId--version=License Name`).
- `assembly-includes` — `g:a` entries that ship via assembly includes but
  are absent from the Maven compile/runtime graph (e.g. hsqldb in
  lib-examples). The archive gate treats them as expected absences and
  fails if one shows up in the inventory (a stale exception).
- `archive-jar-mappings` — filename stem to `g:a` for archive jars that
  resist automatic normalization (shaded jars whose own pom.properties is
  absent). The archive gate promotes matching rows before any check;
  own `org.apache.hadoop` jars become exempt, third-party ones must be
  licensed.
- `manifest-assets.txt` — the non-jar entries of `LICENSE-binary`
  (bundled webapp JS/CSS, npm packages, native sources), as
  `section<TAB>line`. `check-asset-manifest.py` gates every path-style
  entry against the source tree per push (requirement 7, fail-closed);
  package-style entries (`name vX.Y`) are validated by the archive-side
  asset gate (open, requirement 7 stage C).

## Refinements after the first manual-vs-automated comparison

- extended `licenseMerges` with the variants actually observed
  (BSD 2-clause and 3-clause are intentionally kept separate)
- `includeOptional=true` so optional deps that ship (e.g. checker-qual)
  are inventoried
- `excludedGroups` drops Maven/Plexus/Sisu build tooling (note: the
  plugin embeds the regex in a wider pattern — no `^`/`$` anchors)
- `normalize-licenses.sh` renames texts to the `LICENSE-<name>.txt`
  convention
- `resolve-licenses.sh` walks *every* leading license group of each
  report line (a dependency can carry several licenses, and license names
  can themselves contain parentheses — a naive `\([^()]*\)` match
  silently drops both) and rejects HTML junk texts even without `--strict`
- the committed `LICENSE-binary` is generated from the archives by
  `generate-archive-manifest.py` (requirement 40) and gated by drift
  detection in both workflows (requirement 10) — the R25 parity gate
  against a hand-maintained manifest is retired
- `excludedGroups` also drops our own reactor artifacts
  (`org.apache.hadoop`) and the shaded `hadoop-thirdparty` jars — they are
  not third-party
- generic `BSD License` declarations (stax2-api, dom4j, jdom2, jline —
  all 3-clause BSD) fold into the 3-clause merge
- `LICENSE-gplv2-ce.txt` covers the GPLv2 with Classpath Exception
  spellings (JMH, jersey)

Test tooling that enters the graph at compile scope is curated out via
`excludedArtifacts`: `hadoop-client-minicluster` declares its test-jar
support dependencies (mockito, jersey-test-framework, junit-jupiter...)
at compile+optional, and some upstream SDK POMs declare test tooling at
compile (the aliyun SDK's jacoco agent, JMH's jopt-simple, the tencent
SDK's ini4j). The scope filter cannot see these; only the tarball
ground-truth (requirement 26) can confirm the remaining ones. The
pattern matches bare artifactIds unanchored, so a new dependency whose
artifactId contains one of these names (e.g. anything `junit-*`) is
silently excluded too — re-audit the list whenever the dependency set
changes.

## Not covered (yet)

- Source-release `LICENSE.txt`/`licenses/` drift (the binary-side asset
  curation is gated; the source-release file is still hand-maintained
  prose — fixed alongside the binary curation, but not machine-checked).
- Archive-side non-jar asset enumeration (requirement 7 stage C): the
  archive asset gate that matches the tarball's actual JS/CSS/native
  assets (and jar-embedded webapps) against `manifest-assets.txt`.
- Whitelist/audit policy enforcement (allowed-license gating).
- Wiring the generated texts into `hadoop-dist`/`hadoop-assemblies` so the
  tarball ships them automatically (requirement 13).
