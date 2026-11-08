# Automatic license management — requirements (v2.1)

Requirements for automating the collection, validation, and distribution of
third-party license information in this repository. The implementation on the
`feat/LICENSES` branch (`licenses` Maven profile + `licenses.yml` workflow +
`dev-support/licenses/` tooling) implements the collection core.

## Goal

**Reach at least the same level of license inventory and management as the
current manual process** — the automated output must cover every dependency
tracked by the hand-maintained `licenses/` and `licenses-binary/`
directories (no regressions), while additionally surfacing dependencies the
manual process misses. The manual files remain the baseline of record until
the automated inventory is proven to be a superset of them for the covered
modules.

**End state (v2.1, from pjfanning/hadoop#116):** ASF policy requires every
official distribution — source releases and convenience binaries alike — to
carry a license that accurately describes what is *in that archive*. Today
the binary tarball bundles libraries that `LICENSE-binary` does not list,
so the archives are not compliant. The module's end state is that each
distributed archive's license file is generated from, and validated
against, that archive's actual contents (R38, R40).

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
    *Transitional (see the transition plan): retires when R40 generates
    the shipped manifest from archive contents; its per-push slot is
    then taken by drift detection (R10) against the generated
    baseline.*

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

## Requirements added in v2.1 (archive ground truth and compliance)

Findings behind these: the graph-vs-tarball divergences demonstrated in
the parity work (compile-scoped test tooling leaking through
`hadoop-client-minicluster` and upstream SDK POMs; `hadoop-gcp` shading
opencensus/google-cloud classes into itself; the catalog webapp WAR
bundling jars the standalone tree does not), and pjfanning's tarball
audit (37 bundled-but-unlisted jars; jacoco/ini4j listed yet absent).

35. **Dist-build operation** — archive validation (R26) SHALL run as its
    own CI concern (separate workflow or schedule, e.g. nightly/weekly
    plus `workflow_dispatch`), distinct from the per-push graph gate,
    because assembling the tarball requires the Docker native-build
    environment and minutes-scale time the per-push budget does not
    have. The per-push gate and the archive gate complement each other;
    neither replaces the other.
36. **Archive enumeration** — a tool SHALL enumerate every jar in the
    assembled binary tarball, including jars nested inside WARs, and
    normalize each to a `g:a:v` coordinate for comparison with the
    inventory. Normalization SHALL prefer embedded jar metadata
    (`META-INF/maven/*/pom.properties`, `META-INF/MANIFEST.MF`
    `Implementation-*` attributes) over filename parsing; jars that
    resist normalization SHALL be listed for manual mapping rather than
    silently dropped.
37. **Shaded-jar policy** — when a shipping jar relocates and embeds
    other artifacts (e.g. `hadoop-gcp` embedding opencensus and
    google-cloud classes), the archive's view (one jar) SHALL win over
    the graph's view (several GAVs) for completeness checks; the
    embedded artifacts' licenses still apply and their texts SHALL
    remain in the resolved set. A curated mapping SHALL record which
    top-level jars embed which coordinates.
38. **Archive-completeness gate** — the compliance direction SHALL be
    explicit: any jar present in the distributed archive whose license
    is not stated by the archive's license file is a failure. This is
    the inverse of the parity gate (R25): R25 protects the inventory
    from losing coverage; R38 protects the archive from carrying
    unlicensed content. It applies per release, to the exact archive
    being distributed.
39. **Curated-exclusion justification** — every artifact excluded from
    the inventory by curation rather than by scope (e.g.
    `excludedArtifacts`: the jacoco agent, jopt-simple, ini4j, the
    minicluster test-support set) SHALL carry a recorded justification
    and SHALL be confirmed absent from the assembled archive by R26's
    ground-truth run. An exclusion that turns out to ship SHALL fail
    the archive gate.
40. **Archive-derived manifest generation** — the end-state generator
    (R12/R13) SHALL derive the shipped license file from the archive's
    actual contents (enumerated per R36), not from the dependency graph
    alone, so that each distributed archive is compliant by
    construction. The graph-based inventory remains the early-warning
    gate; the archive-derived manifest is the artifact of record.

## Implementation status (branch `feat/LICENSES`, v2.1)

Open work items, the transition plan, and in-flight CI verification are
tracked in the claude-mem work state for this project (list
`license-management`), not in this document. This section records only the
status each requirement reached; consult the work state for what is still
open and what is in flight.

| Requirement | Status |
|---|---|
| 1–4, 15, 17–18 | Implemented (`licenses` profile + `licenses.yml`) |
| 5, 19, 33 | Implemented — `texts/` store + `resolve-licenses.sh`; download behind `workflow_dispatch` input |
| 6 | Implemented via `failOnMissing` and `--strict` (HTML-junk rejection included) |
| 8 | Existing (Apache RAT) |
| 7 | Partial — stage A curation fix + stage B source-tree gate landed 2026-11-08 (stale nvd3/angular/d3-3.5.17/lz4 entries pruned, d3-v4.1.1 and nativetask lz4 added; `check-asset-manifest.py` gates `manifest-assets.txt` per-push; record: `2026-11-08-0930-R7-Assets-Stages-A-B.md`). Open: stage C archive-side asset gate (incl. jar-embedded webapps) |
| 10 | Implemented for LICENSE-binary 2026-11-08 — the per-push gate diffs the committed file against the last successful dist run's generated manifest; the dist workflow diffs it against what its own archives generate (R40 drift gate). Selection is commit-aware (fixed 2026-11-08 after run 42461135530 raced its same-push archive run): a same-commit archive run is deferred to when succeeded or in flight and fails the gate when failed; only a commit with no archive run — no manifest input touched — compares against the previous commit's baseline. First green per-push drift-gate run 2026-11-08 (collect run 42474966366 on commit 404fe3abbee) — the first green collect since the Stage 3 switch |
| 20–24 | Implemented (licenseMerges, overrideUrl, includeOptional, excludedGroups, license-slugs.sh) |
| 34 | Implemented — full `mvn install` reactor, no `-pl` scoping |
| 25 | **Retired 2026-11-08** with the Stage 3 switch — its per-push slot is taken by R10 drift detection against the archive-derived manifest; the tooling (`check-licenses-parity.sh`) is deleted (record: `2026-11-08-0800-Stage3-Switch-Generated-Manifest.md`). It was implemented and green from the 2026-11-07 curation pass until retirement |
| 26–27 | Implemented and validated by the first ground-truth run 2026-11-07 (42374519973): the real tarball was enumerated (264 jars incl. the catalog webapp WAR's nested libs), R38 caught 47 unlicensed shipped jars, R36/R37 mapping curated; gate bugs found by the run were fixed (see the run record) |
| 28–29 | **28 Done 2026-11-07** — curated multi-license policy (`Multi-License-Policy.md`: prefer Apache-2.0, then EDL, then EPL-2.0; jersey/hk2 keep their combined section) applied to the shipped manifest, two misplaced entries corrected (checker-qual → MIT, jakarta.activation-api → EDL; record: `2026-11-07-1630-R28-Policy-Application.md`). 29 Partially — override mechanism exists; disambiguation policy done, no-metadata justification coverage still partial |
| 30–32 | Addressed by two 2026-11-07 passes: the curation pass (record: `2026-11-07-1150-...md` — malformed entries fixed, versions aligned, 30 stale entries pruned) and the archive-verified prune (record: `2026-11-07-1700-R32-Prune-Declared-Not-Shipped.md` — 10 declared-but-not-shipped entries pruned: kerby x8 non-embedded, jsr311-api, jersey-container-jdk-http; the manual manifest is now exact against the two distributed archives: 302 g:a, every one enumerated or recorded as shaded-embedded) |
| 7, 9, 11–14, 16 | Open (7: archive-side asset gate — stages A+B landed 2026-11-08, see the R7 row) |
| 35–38 | Landed 2026-11-07 — `licenses-dist.yml` (weekly + `workflow_dispatch`), archive enumeration incl. WAR-nested jars, archive-completeness and archive-vs-inventory gates; validated by the first ground-truth run. 2026-11-08: the build-env image's unattended downloads were hardened with curl `--fail --retry` (`/root/.curlrc` written by all five Linux Dockerfiles) after three consecutive image builds died on transient CDN 503s / mid-transfer drops (spotbugs, boost, intel-isa-l, protobuf — one different download each attempt); `Dockerfile_ubuntu_24` added to the dist `paths:` filter as a gate input. The same failure class recurred on the hardened image 2026-11-08 (commit 404fe3abbee): dist-archive run 42474966167 and Build run 42474966726 both died on `curl: (22)` HTTP 504 from `pkg-resolver/install-protobuf.sh` (protobuf v3.25.5 GitHub archive) — a multi-minute 504 outage outlasts the ~30 s curlrc retry window; the dist step's cmake-compile failure and the Build Test jobs' Docker-pull failures were secondary fallout, and no gate logic or curation was implicated. Open follow-ups: script-level retry loop (5 attempts, 60 s sleep) in `install-protobuf.sh` — must ride a NEW commit, reruns replay the old image — and switching `licenses-dist.yml` to pull the GHCR-cached base image the Build workflow already pushes instead of rebuilding (~20 min per run). Both landed 2026-11-08 (record: `2026-11-08-1940-Dist-CI-Resilience-Retry-And-Image-Cache.md`): the protobuf/abseil downloads retry 5×60 s with `--fail`; the dist workflow caches the build-env image in GHCR under a content-addressed tag (hash of `Dockerfile_ubuntu_24` + `pkg-resolver/` + `hadoop_env_checks.sh`) — a cache hit is provably built from this commit's inputs, misses build-and-push, and `start-build-env.sh` skips its own build under `HADOOP_BUILD_ENV_PREBUILT=1`. Residual exposure: the googletest FetchContent download inside the dist build (hadoop-hdfs-native-client) is a build-time cmake fetch neither change covers — OPEN work item (hit once, HTTP 503, archive run 42474966167): harden it with a retrying fetch (FetchContent download retry or pre-seeded googletest in the build-env image) before it becomes the recurring failure point the pkg-resolver downloads were |
| 39 | Exclusion justifications recorded (2026-11-07 curation record + README); archive confirmation starts with the first dist run |
| 40 | Integrated 2026-11-08 — the committed `LICENSE-binary` IS the generator's output (artifact of record), regenerated and drift-gated by the dist workflow per run; validated against run 42413534907 and the 42427570912/42427570914 pair (record: `2026-11-07-1730-R40-Generator.md`, switch record: `2026-11-08-0800-Stage3-Switch-Generated-Manifest.md`). NOTICE-binary stays curated (attribution corpus is prose; protected by R10) |

## Review changelog

- **v1** — initial 19 requirements.
- **v1.1** — +20–25 from the automated-vs-manual comparison; goal and
  parity gate stated.
- **v1.2** — +26–32 from pjfanning/hadoop#116 findings.
- **v2** — +33–34 from CI log analysis; requirements 5 and 19 revised to
  make license texts local-first and the default path offline;
  `overrideFile` migrated to `overrideUrl` (deprecation).
- **v2.1** — +35–40 from the graph-vs-archive ground-truth analysis;
  end-state goal restated per ASF distribution policy (every archive's
  license file describes that archive's contents); status table updated
  to the `feat/LICENSES` implementation; transition plan added (manual
  gate → archive-derived licensing, with stage tracking).
- **v2.2** — plan content (transition plan, stage tracking, open-item
  lists) moved out of this document into the project's claude-mem work
  state (list `license-management`); this document keeps requirements
  and per-requirement status only.
