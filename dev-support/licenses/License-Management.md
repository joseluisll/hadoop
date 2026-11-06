# Automatic license management — requirements

Requirements for automating the collection, validation, and distribution of
third-party license information in this repository. The prototype on the
`LICENSES` branch (`licenses` Maven profile + `licenses.yml` workflow)
implements the collection core; the remaining items describe the full
solution.

## Goal

**Reach at least the same level of license inventory and management as the
current manual process** — i.e. the automated output must cover every
dependency tracked by the hand-maintained `licenses/` and
`licenses-binary/` directories (no regressions), while additionally
surfacing dependencies the manual process misses. The manual files remain
the baseline of record until the automated inventory is proven to be a
superset of them for the covered modules.

## Collection

1. **Dependency inventory** — the build SHALL enumerate every compile- and
   runtime-scoped dependency, including transitive ones, across all modules
   that ship in the distribution.
2. **Scope filtering** — test, provided, and build-only tooling
   dependencies SHALL be excluded from the shipped license set.
3. **License resolution** — each dependency SHALL be mapped to a license
   identifier, using POM metadata first and curated overrides where metadata
   is missing or wrong.
4. **Name normalization** — license name variants (e.g. "Apache License
   2.0" vs. "The Apache Software License, Version 2.0") SHALL be merged
   into canonical names, ideally SPDX identifiers.
5. **License texts** — the full license text for every detected license
   SHALL be downloaded or otherwise obtained, not just referenced by name.
6. **Missing-license detection** — dependencies with no resolvable license
   SHALL be reported; whether they fail the build SHALL be configurable
   (`failOnMissing`).
7. **Non-Maven assets** — bundled JavaScript, native, and other non-Maven
   assets (currently covered by the hand-maintained `licenses/` directory)
   SHALL be included in the inventory, either via manifests or curated
   configuration.

## Validation

8. **Header checks** — source-file license headers SHALL continue to be
   validated by Apache RAT; the collection tooling complements, and does
   not replace, RAT.
9. **Allowlist policy** — a configurable list of approved licenses SHALL
   gate the build, so that newly introduced dependencies with
   non-approved licenses fail CI.
10. **Drift detection** — CI SHALL fail when the checked-in license files
    (`licenses/`, `licenses-binary/`, NOTICE) drift from the generated
    output, forcing them to be regenerated on dependency changes.
11. **Precommit integration** — license validation SHOULD run in the Yetus
    precommit pipeline alongside RAT.

## Distribution

12. **Report generation** — a `THIRD-PARTY` report listing every shipped
    dependency and its license SHALL be produced per release.
13. **Text bundling** — collected license texts SHALL be wired into
    `hadoop-dist`/`hadoop-assemblies` so release tarballs ship them
    automatically, replacing the manual `licenses-binary/` maintenance.
14. **NOTICE accuracy** — attribution-required licenses (e.g. BSD, MIT,
    EPL) SHALL be reflected in the shipped NOTICE file.
15. **CI artifacts** — every collection run SHALL publish the generated
    reports and license texts as workflow artifacts for review.
16. **Reproducibility** — collection output SHALL be deterministic for a
    given dependency set, so diffs in review reflect only real changes.

## Operations

17. **Single command** — maintainers SHALL be able to regenerate all
    license artifacts with one Maven invocation (documented in
    `dev-support/licenses/README.md`).
18. **Performance** — a full collection run SHOULD complete within normal
    CI time budgets; scoped runs (e.g. `-pl hadoop-common -am`) SHALL be
    supported for fast iteration.
19. **Network resilience** — failures to fetch remote license texts
    (404/403, renamed URLs) SHALL be reported as warnings with a fallback
    to curated local copies, not silently dropped.

## Requirements added from the first automated-vs-manual comparison

The first collected output (hadoop-common subtree, 134 dependencies) was
compared against the hand-maintained `licenses/` and `licenses-binary/`
directories. It surfaced the following additional requirements:

20. **Observed-variant merging** — the normalization table SHALL cover the
    license name variants actually seen in the dependency graph (three
    Apache-2.0 spellings, three EPL-1.0 spellings, BSD 2-clause vs.
    3-clause variants, EDL, CDDL+GPLv2-CE). BSD 2-clause and 3-clause
    SHALL NOT be merged into each other: they are different licenses.
21. **Curated overrides** — a versioned override file
    (`dev-support/licenses/override-THIRD-PARTY.properties`) SHALL carry
    license information for dependencies with missing or wrong POM
    metadata, reviewed like any other source change.
22. **Optional dependencies** — optional dependencies that still ship in
    the distribution (e.g. guava's `checker-qual`, tracked manually in
    `licenses-binary/`) SHALL be included in the inventory.
23. **Build-tooling exclusion** — Maven/Plexus/Sisu and other build-only
    groups SHALL be excluded so the inventory reflects only shipped
    artifacts.
24. **Naming convention** — generated license texts SHALL be renamed to
    the project's `LICENSE-<name>.txt` convention
    (`dev-support/licenses/normalize-licenses.sh`) so they can replace or
    be diffed against the hand-maintained files.
25. **Parity gate** — for each covered module, the generated inventory
    SHALL contain every dependency tracked by the manual `licenses/` and
    `licenses-binary/` files that ships from that module; any gap SHALL
    fail CI until explained by a curated override or a correction to the
    manual baseline. This is the acceptance test for the goal above.

## Implementation status (prototype on branch `LICENSES`)

| Requirement | Status |
|---|---|
| 1–5, 15, 17–19 | Implemented (`licenses` profile + `licenses.yml`) |
| 6 | Implemented via `failOnMissing` (currently `true`) |
| 8 | Existing (Apache RAT) |
| 20–23 | Implemented (licenseMerges, overrideFile, includeOptional, excludedGroups) |
| 24 | Implemented (`normalize-licenses.sh`, runs in CI) |
| 25 | Open — first manual comparison done ad hoc; CI gate not yet wired |
| 7, 9–14, 16 | Open |
