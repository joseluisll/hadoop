# Automated license collection

Prototype for automating the collection and distribution of third-party
dependency licenses, complementing the hand-maintained `licenses/`
directory and the Apache RAT header checks. The binary distribution's
license texts are NOT hand-maintained: `texts/` is the single home, and
the tarball's `licenses-binary/` directory is generated from it and the
manifest (requirement 13).

**Branch context.** The tooling lives on this branch
(`feat/LICENSES`, trunk-based). The `feat/LICENSES-3.5` branch carries
the same system ported to the branch-3.5 release line and validated
against the official 3.5.0 release: its committed `LICENSE-binary` is
derived from the 3.5.1-SNAPSHOT archive's own enumeration (dist run
42682946618). Its manual source-release files (`LICENSE.txt`) are the
comparison baseline and are never edited there, so that branch's R48
gate stays red by design; its findings are report material. The tooling
under `dev-support/licenses/` (scripts, workflow logic, requirements,
records) is kept complete on this branch; the 3.5 branch differs only
in branch data (curation rows and texts for what 3.5 ships, the
cloud-storage dist steps it lacks). `analysis-3.5/` in that branch's
root (copied here as `dev-support/licenses/analysis-3.5/` from
`51e4baacf21`; the deviation scripts in `deviations/` read the curation
files of this directory and reproduce their recorded `.txt` outputs) holds the
automated-vs-manual comparison package (provenance-separated sources,
reproducible deviation analyses, executive summary) that backs the
proposal to adopt this system into Hadoop's release procedure; the
adoption requirements (trunk/PR operation, release gating, precommit
vote, ASF infrastructure) are R41–R54 in `License-Management.md`.

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
`license-slugs.sh`, shared by both scripts. Store provenance: the
component-specific texts (`atlaskit`, `react`, `leveldb`, `re2j`, ...)
are the former repo-root `licenses-binary/` texts, migrated here
2026-11-09 when the tarball's directory became generated (requirement
13); `edl-1.0` is the canonical eclipse.org plain text, and `gplv2-ce`
is the JMH project's COPYING (GPLv2 plus the Classpath Exception); the
generic resolve-store texts were seeded from SPDX and upstream sources.

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

Regenerating the tarball's `licenses-binary/` directory (requirement 13;
the dist workflow does this before the Maven build — the cloud-storage
assembly copies the directory during the reactor — and
`dist-layout-stitching` regenerates it again for the main dist):

```bash
python3 dev-support/licenses/generate-archive-manifest.py \
  --emit-licenses-dir-only --manifest LICENSE-binary \
  --licenses-dir <target-dir>
```

A store text ships when LICENSE-binary references it (its slug or its
`licenses-binary-aliases` token, whole word). `texts-generic` lists the
resolve-store texts that never ship; section-title alias rows make a
section's generic text ship whenever the section is present.

To refresh the local store from the network (rare, reviewed in a PR):

```bash
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-download-licenses
dev-support/licenses/normalize-licenses.sh target/licenses /tmp/downloaded
# review /tmp/downloaded, then copy vetted texts into texts/
```

## Release time: the release-check driver (requirement 44)

`run-release-checks.sh` packages the whole generate-and-verify suite as
ONE callable, fail-closed step for the exact tarballs being voted on —
the thing `create-release` (upstream) or the fork's release prototype
invokes after tarball assembly. It re-runs the same gates the CI
workflows run (R36/R38/R39/R26/R27 archive gate, R7 stage-C assets,
R10/R40 committed drift, R53 texts, R14 NOTICE coverage), regenerates
LICENSE-binary and `licenses-binary/` from this run's enumerations
(R40/R13), and on GREEN publishes the RC artifact set (THIRD-PARTY.txt,
generated manifest, texts dir, sha512) plus an RM offline checklist;
on RED it prints a fix list — every failed requirement with the
configuration file where the change belongs and a per-check log with
the exact entries.

```bash
# release mode (RM host or release prototype): tarballs + repo checkout
dev-support/licenses/run-release-checks.sh \
  --tarballs <dir-with-tarballs> --repo <checkout> [--out <dir>]
# supply the dependency inventory: --third-party <file>, --collect, or
# the repo's pre-collected target/third-party/THIRD-PARTY.txt

# verification mode (offline voter verifier): one command over a
# staged/downloaded RC directory (tarballs + .sha512 + THIRD-PARTY.txt);
# add --keys <KEYS> to verify signatures too
dev-support/licenses/run-release-checks.sh --verify-only <rc-dir> \
  --repo <checkout-of-the-release-tag>
```

The pruning reports (unused-jar candidates, archive delta) are CI-side
dry runs and deliberately not part of this step: informational, never a
gate. Synthetic coverage: `test-run-release-checks.py` (13 cases: green
release and verification paths plus every fail-closed one).

## CI

`.github/workflows/licenses.yml` installs the full reactor (no skipped
modules), builds the `THIRD-PARTY` inventory, resolves texts from the
local store (`--strict`), runs `check-asset-manifest.py` (the asset
manifest against the source tree, requirement 7 stage B; the
source-release `LICENSE.txt`, requirement 48; the `texts/` store,
requirement 53; NOTICE-binary coverage, requirement 14), fails when the
committed `LICENSE-binary`
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
  into top-level jars,
- the archive's non-jar asset population — loose files and assets
  embedded in jars/WARs — against `manifest-assets.txt` +
  `archive-asset-allowlist` (`check-archive-assets.py`, requirement 7
  stage C; the build is release-shaped, `-Pyarn-ui`, so the UI WAR
  trees are enumerated too),
- the shipped texts: the R40 step regenerates `LICENSE-binary` from the
  run's own archives (fail on diff — requirement 40) and re-emits each
  tarball's `licenses-binary/` from the fresh manifest, failing when it
  differs from what the archive ships (requirement 53).

Each archive also gets a jar layout report (`jar-layout-report.py`,
`layout-report.md` in the artifact and the job summary). It is pruning
input, not a gate: one artifact at two versions in the same lib
directory, artifacts shipped at several versions, and the same jar
copied into several lib directories, with the on-disk bytes the extra
copies take.

A pruning dry run follows the gates in its own step (report only,
`continue-on-error`, so it can never turn the run red; it changes
nothing):

- `unused-jar-candidates.py` writes `unused-jar-candidates.txt` per
  archive: the third-party jars nothing in the archive refers to. It
  starts from Hadoop's own jars, each WAR's `WEB-INF/classes` and the
  class names in `etc/`, `bin/`, `sbin/` and `libexec/`, and follows the
  class names in class-file constant pools (types, signatures, string
  constants) and text resources, plus `META-INF/services` providers and
  resource paths named in string constants (`a/b/schema.xsd`, so a jar
  shipped only for its resources counts as used).
  Pure Python: `jdeps` aborts on Hadoop's modular jars. It is
  conservative (any reference counts as use), so a candidate has no
  reference at all; jars with no class files are listed apart, and
  `unused-jar-keep` moves jars known to be loaded by a name the scan
  cannot see out of the candidates. A second section lists the jars that
  are used, but only by optional features: each Hadoop jar belongs to a
  feature by where it ships (core is `share/hadoop/{common,hdfs,
  mapreduce,yarn}`; optional are each WAR, each `tools/lib` tool,
  `yarn/timelineservice`, `yarn/csi`, `share/hadoop/client` and the test
  jars), and a jar reached from optional features but not from core is
  listed with them. A row whose artifact core also uses is that feature's
  private copy: dropping the feature removes the copy, not the artifact.
  Service providers count only on their own class path, so a WAR's
  providers belong to the WAR.
- `archive-delta.py` writes `archive-delta.txt`: the third-party jars
  added, removed, re-versioned or copied into other lib directories
  against the last successful run of this workflow on the branch (the R10
  gate's lookup), with where each changed version ships. Archives are
  matched without their release version, so a trunk version bump still
  compares like for like. It shows what a pruning change did to the
  archive.

The step goes on when one report fails (a warning per failure) and
fails only at its end, still without turning the run red.

Both land in the artifact and the job summary. Why a jar is in the
archive (its dependency path) is not reported yet.

The Docker build-env image comes from a GHCR cache under a
content-addressed tag (the hash of the files the image build consumes),
provided by `build-env-image.sh`. On a miss it waits while an earlier
in-flight run of the workflow is building the image, and pulls it when it
appears, so two pushes close together build it once; otherwise it builds
and pushes it. The workflow has no concurrency group on purpose: GitHub
would cancel queued runs, and a cancelled archive run fails that commit's
per-push drift gate (requirement 10).

The tools also run standalone against any tarball or exploded layout:

```bash
python3 dev-support/licenses/enumerate-archive-jars.py \
  hadoop-dist/target/hadoop-<version>.tar.gz -o archive-jars.tsv
dev-support/licenses/check-archive-licenses.sh \
  archive-jars.tsv <extracted>/hadoop-<version>/LICENSE-binary \
  target/third-party/THIRD-PARTY.txt
python3 dev-support/licenses/check-archive-assets.py \
  <extracted>/hadoop-<version> . --tsv archive-assets.tsv
python3 dev-support/licenses/jar-layout-report.py \
  archive-jars.tsv --root <dir the TSV paths are relative to>
python3 dev-support/licenses/unused-jar-candidates.py \
  <dir the TSV paths are relative to> archive-jars.tsv -o unused-jar-candidates.txt
python3 dev-support/licenses/archive-delta.py \
  <baseline>/archive-ground-truth <current>/archive-ground-truth
```

Gate tooling has synthetic self-tests (not yet wired into per-push CI,
requirement 49): `test-generate-archive-manifest.py` (happy paths plus
every fail-closed path of the generator and emitter) and
`test-check-archive-assets.py` (coverage matching, evidence tiers,
self-cleaning allowlist rows), `test-jar-layout-report.py`,
`test-unused-jar-candidates.py` and `test-archive-delta.py`.

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
  asset gate (`check-archive-assets.py`, requirement 7 stage C), which
  also lets them cover their own installed `vendor/<name>/` or
  `node_modules/<name>/` tree. The same script checks the
  source-release `LICENSE.txt` (requirement 48: every path it names
  resolves, and every path-style asset entry is listed in it) and
  `licenses-binary/` (requirement 53, below).
- `archive-asset-allowlist` — archive asset paths exempt from manifest
  coverage in the stage C gate: Hadoop-authored UI code, dist-built
  `.gz` twins, third-party jars' about/license html. Component globs,
  matched as a contiguous path subsequence; a row that matches no
  shipped asset fails the gate (self-cleaning).
- `licenses-binary-aliases` — `slug<TAB>token` for the
  `licenses-binary/LICENSE-<slug>.txt` texts whose slug is not the name
  `LICENSE-binary` lists the component under. Every text must match a
  listed component (by its slug or this token, whole word), so a text
  for a component that no longer ships fails the per-push gate instead of
  shipping in the tarball; a row whose text is gone fails too.
- `unused-jar-keep` — `g:a  # reason` for jars the pruning dry run
  finds unreferenced but that are loaded by a name it cannot see (built
  at run time, set outside the archive, JNI). Report only: a row naming
  no shipped jar, or a jar found referenced anyway, is listed as stale.

## Refinements after the first manual-vs-automated comparison

- extended `licenseMerges` with the variants actually observed
  (BSD 2-clause and 3-clause are intentionally kept separate)
- `includeOptional=true` so optional deps that ship (e.g. checker-qual)
  are inventoried
- `excludedGroups` drops Maven/Plexus/Sisu build tooling. The plugin
  wraps the regex as `[^:]*(PATTERN)[^:]*:[^:]+`, so it is written
  anchored, `^(?:...)(?=:)`, to match whole groupIds only (requirement 47)
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
ground-truth (requirement 26) can confirm the remaining ones. The plugin
wraps the pattern as `[^:]+:[^:]*(PATTERN)[^:]*`, which makes a bare
alternative a substring match (`junit-.*` would also exclude
`my-junit-extras`), so it is written anchored, `(?<=:)(?:alt|...)$`, and
matches whole artifactIds only (requirement 47). In the pom the
lookbehind's `<` must be written `&lt;`: a bare `<` is not well-formed XML
and Maven refuses to read the pom. The archive gate
(`check-archive-licenses.sh`, requirement 39) reads the same element,
fails unless it has that anchored form or if an alternative is listed
twice, and matches the alternatives as `^(alt|...)$`.

## Not covered (yet)

- The source-release `licenses/` texts, and `LICENSE.txt` entries for
  bundled code the asset manifest does not know about (paths it names are
  gated, requirement 48; e.g. libhdfspp's `third_party/rapidxml-1.13` and
  `tr2` are listed in neither licence file).
- Whitelist/audit policy enforcement (allowed-license gating,
  requirements 9 and 46).
- Upstream adoption (requirements 41–46, 49–52, 54): trunk and
  pull-request operation, a scheduled default-branch archive run,
  wiring the gates into `create-release` and the precommit vote, ASF
  infrastructure compliance, and per-push self-tests. These are the
  subject of the release-procedure proposal the `analysis-3.5/`
  package supports (on `feat/LICENSES-3.5`, copied here).
