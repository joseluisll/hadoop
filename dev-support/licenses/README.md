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
dev-support/licenses/check-licenses-parity.sh \
  target/third-party/THIRD-PARTY.txt LICENSE-binary \
  dev-support/licenses/assembly-includes
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
local store (`--strict`), runs the parity gate against the manual
`LICENSE-binary` manifest, and uploads everything as workflow artifacts —
all offline. Downloading from the network runs only when explicitly
requested via the `workflow_dispatch` `download` input.

## Curation files

- `override-THIRD-PARTY.properties` — license overrides for dependencies
  with missing or wrong POM metadata
  (`groupId--artifactId--version=License Name`).
- `assembly-includes` — `g:a` entries that ship via assembly includes but
  are absent from the Maven compile/runtime graph (e.g. hsqldb in
  lib-examples). The parity gate treats them as expected absences and
  fails if one shows up in the inventory (a stale exception).

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
- `check-licenses-parity.sh` gates the inventory against the manual
  `LICENSE-binary` manifest (requirement 25): every `g:a` the manual
  manifest tracks must appear in the generated inventory
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

- JavaScript/other non-Maven assets still need the hand-maintained files in
  `licenses/`.
- Wiring the generated texts into `hadoop-dist`/`hadoop-assemblies` so the
  tarball ships them automatically.
- Whitelist/audit policy enforcement (allowed-license gating).
