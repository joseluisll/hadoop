# Automatic license management — requirements (v2)

Requirements for automating the collection, validation, and distribution of
third-party license information in this repository. The prototype on the
`LICENSES` branch (`licenses` Maven profile + `licenses.yml` workflow +
`dev-support/licenses/` tooling) implements the collection core.

## Goal

**Reach at least the same level of license inventory and management as the
current manual process** — the automated output must cover every dependency
tracked by the hand-maintained `licenses/` and `licenses-binary/`
directories (no regressions), while additionally surfacing dependencies the
manual process misses. The manual files remain the baseline of record until
the automated inventory is proven to be a superset of them for the covered
modules.

**Design principle (v2):** license information is project data. License
texts SHALL be versioned in the codebase (`dev-support/licenses/texts/`),
where they can be reviewed, analyzed, collected, and managed like any other
source. Downloading texts from the network is an optional, explicitly
requested operation — never part of the default build or CI run.

## Collection

1. **Dependency inventory** — the build SHALL enumerate every compile- and
   runtime-scoped dependency, including transitive ones, across all modules
   that ship in the distribution.
2. **Scope filtering** — test, provided, and build-only tooling
   dependencies SHALL be excluded from the shipped license set.
3. **License resolution** — each dependency SHALL be mapped to a license
   identifier, using POM metadata first and curated overrides where metadata
   is missing or wrong.
4. **Name normalization** — license name variants SHALL be merged into
   canonical names, ideally SPDX identifiers.
5. **Local-first license texts** — the full text of every detected license
   SHALL be resolved from the versioned store in
   `dev-support/licenses/texts/`. Network download
   (`aggregate-download-licenses`) SHALL be available only as an explicit
   opt-in, used to *update* the store, never as the default resolution
   path. *(Revised in v2: previously "download or otherwise obtain".)*
6. **Missing-license detection** — dependencies with no resolvable license,
   and licenses with no text in the local store, SHALL be reported; whether
   they fail the build SHALL be configurable (`failOnMissing`,
   `resolve-licenses.sh --strict`).
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
    (`licenses/`, `licenses-binary/`, NOTICE, and the
    `dev-support/licenses/texts/` store) drift from the generated output.
11. **Precommit integration** — license validation SHOULD run in the Yetus
    precommit pipeline alongside RAT.

## Distribution

12. **Report generation** — a `THIRD-PARTY` report listing every shipped
    dependency and its license SHALL be produced per release.
13. **Text bundling** — license texts from the versioned store SHALL be
    wired into `hadoop-dist`/`hadoop-assemblies` so release tarballs ship
    them automatically, replacing the manual `licenses-binary/`
    maintenance.
14. **NOTICE accuracy** — attribution-required licenses (e.g. BSD, MIT,
    EPL) SHALL be reflected in the shipped NOTICE file.
15. **CI artifacts** — every collection run SHALL publish the generated
    reports and resolved license texts as workflow artifacts for review.
16. **Reproducibility** — collection output SHALL be deterministic for a
    given dependency set and text store, so diffs in review reflect only
    real changes. A default run SHALL NOT depend on network availability
    or third-party site behavior.

## Operations

17. **Single command** — maintainers SHALL be able to regenerate all
    license artifacts with one Maven invocation plus one script
    (documented in `dev-support/licenses/README.md`).
18. **Performance** — a full collection run SHOULD complete within normal
    CI time budgets; scoped runs (e.g. `-pl hadoop-common -am`) SHALL be
    supported for fast iteration.
19. **Offline default** — the default collection path SHALL require no
    network access beyond Maven artifact resolution. The optional download
    mode SHALL report failures (403s, dead URLs, timeouts — 22 observed in
    one run against gnu.org, jquery.org and glassfish.dev.java.net) and
    never silently drop a license. *(Revised in v2: was "network
    resilience" for a download-based default.)*

## Requirements added from the first automated-vs-manual comparison

20. **Observed-variant merging** — the normalization table SHALL cover the
    license name variants actually seen in the dependency graph (three
    Apache-2.0 spellings, three EPL-1.0 spellings, BSD 2-clause vs.
    3-clause variants, EDL, CDDL+GPLv2-CE). BSD 2-clause and 3-clause
    SHALL NOT be merged into each other: they are different licenses.
21. **Curated overrides** — a versioned override file
    (`dev-support/licenses/override-THIRD-PARTY.properties`, wired via
    `overrideUrl`) SHALL carry license information for dependencies with
    missing or wrong POM metadata, reviewed like any other source change.
22. **Optional dependencies** — optional dependencies that still ship in
    the distribution (e.g. guava's `checker-qual`, tracked manually in
    `licenses-binary/`) SHALL be included in the inventory.
23. **Build-tooling exclusion** — Maven/Plexus/Sisu and other build-only
    groups SHALL be excluded so the inventory reflects only shipped
    artifacts.
24. **Naming convention** — generated license texts SHALL follow the
    project's `LICENSE-<name>.txt` convention (`license-slugs.sh`) so they
    can replace or be diffed against the hand-maintained files.
25. **Parity gate** — for each covered module, the generated inventory
    SHALL contain every dependency tracked by the manual `licenses/` and
    `licenses-binary/` files that ships from that module; any gap SHALL
    fail CI until explained by a curated override or a correction to the
    manual baseline. This is the acceptance test for the goal above.

## Requirements from real-world findings (pjfanning/hadoop#116)

26. **Ground truth is the distribution** — the inventory SHALL be
    validated against the jars in the assembled release tarball, not only
    against the Maven dependency graph.
27. **WAR coverage** — jars nested in webapp WARs SHALL be inventoried;
    artifacts shipping only inside WARs (e.g. solr-solrj, http2-*,
    httpmime, jcl-over-slf4j in the YARN catalog webapp) must not be
    missed.
28. **Multi-license disambiguation** — artifacts under multiple licenses
    (e.g. javassist: MPL/LGPL/Apache; org.eclipse.persistence: EPL+EDL;
    HdrHistogram: CC0/BSD; hk2: EPL2/GPL+CPE) SHALL be listed under the
    license chosen by a curated, documented policy.
29. **No-metadata curation** — artifacts declaring no license in jar or
    POM (e.g. zookeeper-jute) SHALL get reviewed curated entries with a
    recorded justification.
30. **Entry format validation** — malformed inventory entries (e.g.
    `com.google.code.gson:2.9.0` in place of `gson:2.9.0`) SHALL fail
    validation.
31. **Version consistency** — listed versions SHALL match the shipped jar
    versions; divergent versions between standalone jars and WAR contents
    SHALL be flagged.
32. **Pruning** — entries for artifacts that no longer ship (build
    plugins, test libraries, removed deps) SHALL be flagged for removal;
    license sections left empty by pruning SHALL be dropped.

## Requirements added in review v2 (CI log analysis)

33. **Local license store** — canonical license texts SHALL live in the
    repository (`dev-support/licenses/texts/`), seeded from authoritative
    plain-text sources (SPDX license-list-data, upstream LICENSE files,
    existing repo files) and reviewed in pull requests. Rationale: the
    download-based approach produced HTML error pages instead of license
    texts and failed entirely for LGPL-2.1 and jQuery.
34. **Full-reactor coverage** — CI SHALL run the collection over the
    entire reactor; no module may be skipped. Scoped runs are allowed
    locally for iteration only (requirement 18). Rationale: the scoped
    prototype skipped all but one module's contribution to the aggregate.

## Implementation status (branch `LICENSES`, v2)

| Requirement | Status |
|---|---|
| 1–4, 15, 17–18 | Implemented (`licenses` profile + `licenses.yml`) |
| 5, 19, 33 | Implemented — `texts/` store (17 canonical texts) + `resolve-licenses.sh`; download behind `workflow_dispatch` input |
| 6 | Implemented via `failOnMissing` and `--strict` |
| 8 | Existing (Apache RAT) |
| 20–24 | Implemented (licenseMerges, overrideUrl, includeOptional, excludedGroups, license-slugs.sh) |
| 34 | Implemented — full `mvn install` reactor, no `-pl` scoping |
| 25 | Open — first manual comparison done ad hoc; CI gate not yet wired |
| 26–27 | Open — requires validating against the assembled dist tarball (`-Pdist`), including WAR contents |
| 28–29 | Partially — override mechanism exists; disambiguation policy not yet curated |
| 30–32 | Open |
| 7, 9–14, 16 | Open |

## Review changelog

- **v1** — initial 19 requirements.
- **v1.1** — +20–25 from the automated-vs-manual comparison; goal and
  parity gate stated.
- **v1.2** — +26–32 from pjfanning/hadoop#116 findings.
- **v2** — +33–34 from CI log analysis; requirements 5 and 19 revised to
  make license texts local-first and the default path offline;
  `overrideFile` migrated to `overrideUrl` (deprecation).
