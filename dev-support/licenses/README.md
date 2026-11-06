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
`texts/` (`LICENSE-<name>.txt`, seeded from SPDX and upstream sources) and
are resolved by `resolve-licenses.sh`, which fails (with `--strict`) when
a detected license has no local text. License names are normalized via
`licenseMerges`; the canonical-name → file-slug mapping lives in
`license-slugs.sh`, shared by both scripts.

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

## Usage

```bash
# the aggregate goals resolve artifacts from the local repository,
# so the modules must be installed first
mvn install -DskipTests -Dmaven.javadoc.skip=true
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-add-third-party \
  org.codehaus.mojo:license-maven-plugin:aggregate-download-licenses
```

Results land in `target/third-party` and `target/licenses` of the
aggregating module. For a quick run over a single module:

```bash
mvn -Plicenses -DskipTests \
  org.codehaus.mojo:license-maven-plugin:aggregate-add-third-party \
  org.codehaus.mojo:license-maven-plugin:aggregate-download-licenses \
  -pl hadoop-common-project/hadoop-common -am
```

## CI

`.github/workflows/licenses.yml` installs the full reactor (no skipped
modules), builds the `THIRD-PARTY` inventory, resolves texts from the
local store, and uploads everything as workflow artifacts — all offline.
Downloading from the network runs only when explicitly requested via the
`workflow_dispatch` `download` input. The workflow can be extended to fail
when the checked-in license files drift from the generated output.

## Curation files

- `override-THIRD-PARTY.properties` — license overrides for dependencies
  with missing or wrong POM metadata
  (`groupId--artifactId--version=License Name`).

## Refinements after the first manual-vs-automated comparison

- extended `licenseMerges` with the variants actually observed
  (BSD 2-clause and 3-clause are intentionally kept separate)
- `includeOptional=true` so optional deps that ship (e.g. checker-qual)
  are inventoried
- `excludedGroups` drops Maven/Plexus/Sisu build tooling (note: the
  plugin embeds the regex in a wider pattern — no `^`/`$` anchors)
- `normalize-licenses.sh` renames texts to the `LICENSE-<name>.txt`
  convention

Known limitation: `checker-qual` (manually tracked in
`licenses-binary/`) is explicitly excluded from guava in
`hadoop-project/pom.xml`, so it does not appear in the hadoop-common
subtree inventory. The parity check (requirement 25) needs a
full-reactor run to be meaningful.

## Not covered (yet)

- JavaScript/other non-Maven assets still need the hand-maintained files in
  `licenses/`.
- Wiring the generated texts into `hadoop-dist`/`hadoop-assemblies` so the
  tarball ships them automatically.
- Whitelist/audit policy enforcement (allowed-license gating).
