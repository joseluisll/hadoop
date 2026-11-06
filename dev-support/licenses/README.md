# Automated license collection

Prototype for automating the collection and distribution of third-party
dependency licenses, complementing the hand-maintained `licenses/` and
`licenses-binary/` directories and the Apache RAT header checks.

## How it works

The root `pom.xml` defines a `licenses` profile that wires in
`org.codehaus.mojo:license-maven-plugin` with two executions:

- `aggregate-add-third-party` — builds `THIRD-PARTY` reports listing every
  (transitive) compile/runtime dependency with its resolved license.
- `aggregate-download-licenses` — downloads the license *texts* into
  `target/licenses`.

License names are normalized via `licenseMerges` so that variants such as
"Apache License 2.0" and "The Apache Software License, Version 2.0" collapse
into a single entry. Test and provided scopes are excluded so only what ships
in the distribution is collected.

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

`.github/workflows/licenses.yml` runs the collection on pushes to
`LICENSES`, normalizes the downloaded texts into `LICENSE-<name>.txt`
files (`normalize-licenses.sh`), and uploads everything as workflow
artifacts. It can be extended to fail when the checked-in license files
drift from the generated output.

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
