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
mvn -Plicenses -DskipTests process-sources
```

Results land in `target/third-party` and `target/licenses` of the
aggregating module.

## CI

`.github/workflows/licenses.yml` runs the collection on pushes to
`LICENSES`, uploads the generated reports as workflow artifacts, and can be
extended to fail when the checked-in license files drift from the generated
output.

## Not covered (yet)

- JavaScript/other non-Maven assets still need the hand-maintained files in
  `licenses/`.
- Wiring the generated texts into `hadoop-dist`/`hadoop-assemblies` so the
  tarball ships them automatically.
- Whitelist/audit policy enforcement (allowed-license gating).
