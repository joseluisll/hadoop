# Automatic license management — requirements (v3.2)

Requirements for automating the collection, validation, and distribution of
third-party license information in this repository. The implementation
on the `feat/LICENSES` branch (trunk-based; `licenses` Maven profile +
`licenses-ground-truth.yml` workflow + `dev-support/licenses/` tooling) implements
the collection core. The `feat/LICENSES-3.5` branch carries the same
system ported to the branch-3.5 release line and validates it against
the official 3.5.0 release artifacts (`analysis-3.5/` in that branch's
root, copied on this branch to `dev-support/licenses/analysis-3.5/`) —
the evidence base for proposing adoption into the release
procedure (R44).

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
10. **Drift detection** — CI SHALL fail when a checked-in shipped license
    file drifts from what it must describe: `LICENSE-binary` from the
    archive-derived manifest (R40), and `licenses-binary/` from the
    components `LICENSE-binary` lists (R53). The source-release
    `LICENSE.txt` is covered by R48, the `texts/` store by `--strict`
    resolution (R6); `NOTICE-binary` stays curated prose, reviewed in pull
    requests. *(Narrowed in v2.4: previously named `licenses/`,
    `licenses-binary/`, NOTICE and `texts/` as drift-checked against a
    generated output most of them do not have.)*
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

## Requirements added in v2.3 (adoption review, 2026-11-08)

Findings behind these: the 2026-11-08 requirements review
(`2026-11-08-2336-License-Management-Requirements-Review.md`, findings
F1–F6), which checked what it takes for Apache Hadoop to adopt this as an
automatic process. The gates check correctly; what is missing is that they
run where and when the project needs them: on trunk and pull requests, on
every dependency change, at release time, and in the precommit vote.

41. **Upstream operation** — the per-push and archive workflows SHALL run on
    pushes to trunk and on pull requests to apache/hadoop, and the R10
    baseline lookup SHALL resolve the base branch's last successful archive
    run independently of the run's own ref name (`<n>/merge` on a pull
    request) and of other branches' run volume (today: the 100 newest
    successful runs of all branches, filtered afterwards). (F3)
42. **Dependency-change coverage** — every push or pull request that changes
    any `pom.xml` or assembly descriptor SHALL be checked for
    shipped-dependency changes against the committed manifest, either by an
    archive run or by a graph-vs-manifest comparison against the last
    archive enumeration. Tightens R10 and fills the per-push slot R25 held:
    the archive workflow's path filter covers only the root `pom.xml`, while
    dependency versions live in `hadoop-project/pom.xml` and the module
    poms. (F1)
43. **Baseline freshness** — the archive run SHALL run on a schedule that
    fires from the default branch; its baseline artifact SHALL be retained
    longer than the schedule period; and a missing or expired baseline SHALL
    fail with the exact command to recover (dispatch the archive run).
    Tightens R35: a schedule declared on a non-default branch never fires.
    (F2)
44. **Release gating** — the release process (`create-release`, the
    HowToRelease steps) SHALL run the archive gates (R38, R39) and the R40
    generator against the exact source and binary tarballs being voted on,
    and SHALL publish the THIRD-PARTY report (R12) with the release.
    Tightens R12 and R38.
45. **Precommit vote** — a Yetus plugin SHALL run the per-push checks (store
    resolution `--strict`, the asset gate, the R42 comparison) and vote -1
    on failure, so reviewers see the result where they already look.
    Tightens R11.
46. **ASF license categories** — the allowlist (R9) SHALL follow the ASF
    third-party license policy: Category A allowed; Category B allowed only
    in binary form with its handling recorded; Category X failing the build;
    a license not yet classified failing until it is. Tightens R9.
47. **Anchored curation patterns** — `excludedArtifacts` and every other
    curated pattern SHALL match whole artifactIds (or `g:a`); an unanchored
    or duplicated alternative SHALL fail validation. Tightens R2 and R39:
    today `junit-.*` also excludes `my-junit-extras`, and `junit-.*` is
    listed twice. (F4)
48. **Source-release accuracy** — every path in `LICENSE.txt` and every file
    in `licenses/` SHALL be validated per push against the source tree, and
    every bundled third-party source file known to the asset manifest SHALL
    appear in `LICENSE.txt`. Extends R7 to the source release, which is an
    official ASF distribution too. (F5)
49. **Gate self-tests** — each gate tool (`resolve-licenses.sh`,
    `check-asset-manifest.py`, `enumerate-archive-jars.py`,
    `check-archive-licenses.sh`, `generate-archive-manifest.py`) SHALL have a
    synthetic-input self-test covering a passing input and each failure
    class, run per push.
50. **ASF infrastructure compliance** — the workflows SHALL use only actions
    and token permissions available to apache/hadoop under ASF
    infrastructure policy; any registry or cache publishing (today: GHCR
    with `packages: write`) SHALL be confirmed with INFRA or replaced, and
    SHALL degrade to pull-only on pull requests from forks, where
    `GITHUB_TOKEN` is read-only. (F3)
51. **Self-service regeneration** — when a gate finds manifest drift, the run
    SHALL publish the regenerated `LICENSE-binary` as a ready-to-apply patch
    (and MAY open a bot pull request), so a contributor never needs the
    Docker dist build to fix it.
52. **Curation hygiene** — every curated entry (overrides, jar mappings,
    shaded-jar mappings, exclusions, assembly includes) SHALL carry a
    recorded justification, and an entry whose artifact or version no
    longer appears in the graph or the archive SHALL be flagged for removal.
    Tightens R21, R29 and R39 (overrides are version-pinned today).
53. **Shipped texts match the manifest** — the set of `LICENSE-*.txt` files
    the binary tarball ships SHALL equal the set of license texts the
    generated manifest references, and SHALL come from the `texts/` store.
    Makes R13 checkable and covers the `licenses-binary/` part of R10. (F6)
54. **Upstream change split** — build-environment resilience changes
    (Dockerfiles, download retry, the googletest pre-seed) SHALL be proposed
    under their own JIRA, separately from the license tooling.
55. **Upstream evidence provenance** — every claim made to upstream
    (HADOOP-20078 and follow-ups) SHALL be reproducible from published,
    provenance-labeled sources (`analysis-3.5/` on `feat/LICENSES-3.5`) and
    SHALL be verified against FINAL released artifacts — the final release
    tags in the ASF repository and the published, checksum-verified tarballs —
    never against RC tags or branch proxies (the GitHub mirror of
    apache/hadoop carries only the RC tags; the final tags live in ASF
    gitbox as `rel/release-*`).
56. **Release-history monitoring** — for each new upstream release, the
    changes to the license files since the previous release SHALL be
    analyzed and recorded (commits touching them, file-level diffs between
    the release tags, and how the release tarballs distribute the files and
    the license-text directories), keeping the adoption evidence current and
    re-measuring drift against the latest release. First pass 2026-11-10
    (T00023): 3.4.2, 3.4.3 and 3.5.0.

## Implementation status (branches `feat/LICENSES` and `feat/LICENSES-3.5`, v3.2)

Open work items, the transition plan, and in-flight CI verification are
tracked in the claude-mem work state for this project (list
`license-management`), not in this document. This section records only the
status each requirement reached; consult the work state for what is still
open and what is in flight.

| Requirement | Status |
|---|---|
| 1–4, 15, 17–18 | Implemented (`licenses` profile + the source-gates job of `licenses-ground-truth.yml`). R2: the substring matching of `excludedArtifacts` (2026-11-08 review F4) is fixed 2026-11-08 — see the R47 row |
| 5, 19, 33 | Implemented — `texts/` store + `resolve-licenses.sh`; download behind `workflow_dispatch` input |
| 6 | Implemented via `failOnMissing` and `--strict` (HTML-junk rejection included) |
| 8 | Existing (Apache RAT) |
| 7 | CI term: `assets`. Partial — stage A curation fix + stage B source-tree gate landed 2026-11-08 (stale nvd3/angular/d3-3.5.17/lz4 entries pruned, d3-v4.1.1 and nativetask lz4 added; `check-asset-manifest.py` gates `manifest-assets.txt` per-push; record: `2026-11-08-0930-R7-Assets-Stages-A-B.md`). Stage C gate `check-archive-assets.py` + `archive-asset-allowlist` implemented-on-branch 2026-11-09: file and jar-embedded assets all covered; it found the catalog WAR's unlisted vendor tree (jquery 3.3.1, angular/angular-route 1.6.10, bootstrap 3.3.7, roboto-fontface 0.10.0), now in `LICENSE-binary`. The dist build now runs `-Pyarn-ui` (release-shaped, as `create-release`) and runs the gate on the main archive. Round 2 2026-11-09: package-style npm entries carry version evidence in tiers — shipped vendor manifests, content probe, exact source pins, committed LOCK FILES via the self-cleaning `ui-archive-trees` map (the dist installs from those locks; bower range floors accepted), `archive-asset-pin-exceptions` for compiled-in natives. The first yarn-ui run found the UI WAR trees (`webapps/ui2`, `webapps/scheduler-ui`) unlisted and 48 npm pins drifted from the modules' committed locks — realigned (ember 2.8.0, jquery 3.6.0, react 19.2.4, radix-ui +1 patch each…), `ember-cli-ic-ajax` pruned (pinned nowhere), `datatables` renamed `datatables.net`; `LICENSE-binary` regenerated against run 42543652715's archives, residual exactly the curation set; synthetic suite `test-check-archive-assets.py` (10 cases). Records: `2026-11-09-0230-R7-Stage-C-Archive-Asset-Gate.md`, `2026-11-09-0300-R7-Stage-C-Round-2-Lock-Evidence-And-UI-Wars.md` |
| 10 | CI term: `drift`. Partly — implemented for LICENSE-binary 2026-11-08 — the per-push gate diffs the committed file against the last successful dist run's generated manifest; the dist workflow diffs it against what its own archives generate (R40 drift gate). Selection is commit-aware (fixed 2026-11-08 after run 42461135530 raced its same-push archive run): a same-commit archive run is deferred to when succeeded or in flight and fails the gate when failed; only a commit with no archive run — no manifest input touched — compares against the previous commit's baseline. First green per-push drift-gate run 2026-11-08 (collect run 42474966366 on commit 404fe3abbee) — the first green collect since the Stage 3 switch. The 2026-11-08 review's F6 (R10 named files no gate compared) is resolved 2026-11-08 by the v2.4 narrowing plus the R53 `licenses-binary/` gate. Still open: a dependency change outside the archive workflow's path filter (any module pom, incl. `hadoop-project/pom.xml`) passes, because the gate then compares against the previous commit's baseline (F1, see R42) |
| 20–24 | Implemented (licenseMerges, overrideUrl, includeOptional, excludedGroups, license-slugs.sh) |
| 34 | Implemented — full `mvn install` reactor, no `-pl` scoping |
| 25 | **Retired 2026-11-08** with the Stage 3 switch — its per-push slot is taken by R10 drift detection against the archive-derived manifest; the tooling (`check-licenses-parity.sh`) is deleted (record: `2026-11-08-0800-Stage3-Switch-Generated-Manifest.md`). It was implemented and green from the 2026-11-07 curation pass until retirement |
| 26–27 | CI term: `inventory`. Implemented and validated by the first ground-truth run 2026-11-07 (42374519973): the real tarball was enumerated (264 jars incl. the catalog webapp WAR's nested libs), R38 caught 47 unlicensed shipped jars, R36/R37 mapping curated; gate bugs found by the run were fixed (see the run record) |
| 28–29 | **28 Done 2026-11-07** — curated multi-license policy (`Multi-License-Policy.md`: prefer Apache-2.0, then EDL, then EPL-2.0; jersey/hk2 keep their combined section) applied to the shipped manifest, two misplaced entries corrected (checker-qual → MIT, jakarta.activation-api → EDL; record: `2026-11-07-1630-R28-Policy-Application.md`). 29 Partially — override mechanism exists; disambiguation policy done, no-metadata justification coverage still partial |
| 30–32 | CI term (31): `versions`. Addressed by two 2026-11-07 passes: the curation pass (record: `2026-11-07-1150-...md` — malformed entries fixed, versions aligned, 30 stale entries pruned) and the archive-verified prune (record: `2026-11-07-1700-R32-Prune-Declared-Not-Shipped.md` — 10 declared-but-not-shipped entries pruned: kerby x8 non-embedded, jsr311-api, jersey-container-jdk-http; the manual manifest is now exact against the two distributed archives: 302 g:a, every one enumerated or recorded as shaded-embedded) |
| 9, 11 | Open (7 implemented 2026-11-09 — stages A+B+C complete, see the R7 row) |
| 14 | CI term: `notice`. Implemented 2026-11-09 (owner-scoped coverage gate; record: `2026-11-09-1120-R14-Notice-Coverage-Gate.md`) — `check-asset-manifest.py` fails when a component in an attribution-required LICENSE-binary section (all but Public Domain) is neither mentioned in NOTICE-binary, nor covered by a shipped component text carrying the copyright line, nor recorded in `notice-exceptions` with a justification (39 rows: 36 legacy gaps + 3 added by the round-2 review; a `notice-aliases` map absorbs NOTICE prose-name mismatches). Rows self-clean both directions: a stale row fails the gate, and so does an uncovered component without one — so every NEW component is enforced immediately and the legacy gaps burn down as component texts land. A round-2 independent review (2026-11-09) caught the gate fail-open — a never-shipping `texts-generic` text (JSON.org `json`, which false-matches `javax.json` coordinates) was credited as coverage for 3 components — fixed by restricting coverage texts to the R13 emitter's ship set; verified the fixed gate fails on exactly those 3 components without their rows. A strict mention-only gate was probed first and rejected by the owner: 71 of 75 attribution-required components had no NOTICE mention, so enforcing it literally required authoring that attribution corpus by hand |
| 13 | CI term: `bundling`. Implemented 2026-11-09 — the tarball's `licenses-binary/` directory is generated from the versioned `texts/` store and the manifest, replacing the hand-kept repo-root directory (66 texts migrated into `texts/`, `go` renamed `re2j`; section-title alias rows ship each present section's generic text; `texts-generic` exempts resolve-store texts that never ship). Emitter: `generate-archive-manifest.py --emit-licenses-dir-only` (fail-closed: empty store/manifest, populated output dir, missing/empty text, section with no shipped text). Wiring: `dist-layout-stitching` regenerates the directory for the main dist, a pre-build step generates it for the cloud-storage assembly, and the R40 drift step re-emits from the fresh manifest and diffs both tarballs' shipped directories (R53, dist side). Manual maintenance retired; record: `2026-11-09-1110-R13-Text-Bundling-Store-Migration.md` |
| 12 | Partly — the THIRD-PARTY inventory is produced and published by every CI run (both workflows), not per release: `create-release` has no license step (see R44) |
| 16 | Implemented — the generator is deterministic (self-check `test-generate-archive-manifest.py`, 11 tests) and the dist R40 gate regenerates `LICENSE-binary` from fresh archives and finds no diff (green on run 42519178850); the default path is offline (2026-11-08 review) |
| 35–38 | CI terms: 35 `enumeration`, 36 `jar-naming`, 37 `inventory`, 38 `coverage`. Landed 2026-11-07 — now job `archive-ground-truth` of `licenses-ground-truth.yml` (weekly + `workflow_dispatch`; 2026-11-12 merge, formerly `licenses-dist.yml`), archive enumeration incl. WAR-nested jars, archive-completeness and archive-vs-inventory gates; validated by the first ground-truth run. 2026-11-08: the build-env image's unattended downloads were hardened with curl `--fail --retry` (`/root/.curlrc` written by all five Linux Dockerfiles) after three consecutive image builds died on transient CDN 503s / mid-transfer drops (spotbugs, boost, intel-isa-l, protobuf — one different download each attempt); `Dockerfile_ubuntu_24` added to the dist `paths:` filter as a gate input. The same failure class recurred on the hardened image 2026-11-08 (commit 404fe3abbee): dist-archive run 42474966167 and Build run 42474966726 both died on `curl: (22)` HTTP 504 from `pkg-resolver/install-protobuf.sh` (protobuf v3.25.5 GitHub archive) — a multi-minute 504 outage outlasts the ~30 s curlrc retry window; the dist step's cmake-compile failure and the Build Test jobs' Docker-pull failures were secondary fallout, and no gate logic or curation was implicated. Open follow-ups: script-level retry loop (5 attempts, 60 s sleep) in `install-protobuf.sh` — must ride a NEW commit, reruns replay the old image — and switching `licenses-dist.yml` to pull the GHCR-cached base image the Build workflow already pushes instead of rebuilding (~20 min per run). Both landed 2026-11-08 (record: `2026-11-08-1940-Dist-CI-Resilience-Retry-And-Image-Cache.md`): the protobuf/abseil downloads retry 5×60 s with `--fail`; the dist workflow caches the build-env image in GHCR under a content-addressed tag (hash of `Dockerfile_ubuntu_24` + `pkg-resolver/` + `hadoop_env_checks.sh`) — a cache hit is provably built from this commit's inputs, misses build-and-push, and `start-build-env.sh` skips its own build under `HADOOP_BUILD_ENV_PREBUILT=1`. Both real-image validations passed 2026-11-08: the manifest-denial rerun (42511445584) pushed the cache image successfully and the next dist run (42519178850, commit 71073d88145) showed `Cache hit` and was green, as was the same-push collect run (R10 gate satisfied against the same-commit archive run). The residual googletest exposure is CLOSED 2026-11-08 (record: `2026-11-08-2200-Googletest-Preseed-Offline-Native-Build.md`): the pinned googletest source (release-1.10.0, commit `703bd9ca`) is pre-seeded into the build-env image at `/opt/googletest-<commit>` by `pkg-resolver/install-googletest-preseed.sh` (script-level retry via the shared `download-with-retry.sh`), and libhdfspp's CMakeLists uses `FETCHCONTENT_SOURCE_DIR_GOOGLETEST` to consume it when present — the preseed path is derived from the CMakeLists' own `GOOGLETEST_COMMIT` pin, so bumping the pin falls back to the URL download rather than a stale tree. Real-image validation passed 2026-11-08 on the new image tag: archive run 42528156324 (4494b532b44) was the expected one-time cache miss and its image build logged `Preseeded googletest 703bd9ca…` in place; archive runs 42532039456 and 42533828604 show `Cache hit` on the new tag, and the dist cmake-compile step shows no googletest download. Remaining dist-build download exposure: Maven artifact resolution only (protected by Maven's built-in resolver retry). Gaps found by the 2026-11-08 review: the weekly `schedule` has never fired — GitHub runs schedules from the default branch only, and the workflow is not on trunk; every archive run so far came from a push or a dispatch (F2, R35 partly; see R43). R38 gates CI-built archives, not the release manager's tarballs (R38 partly; see R44) |
| 39 | CI term: `exclusions`. Implemented — exclusion justifications recorded (2026-11-07 curation record + README); the archive runs since 2026-11-07 confirm no curated exclusion ships. The substring-matching hole (F4) is fixed 2026-11-08 (see the R47 row) |
| 47 | CI term: `exclusion-pattern`. Implemented 2026-11-08 (review F4) — `excludedGroups` and `excludedArtifacts` written anchored, `^(?:...)(?=:)` and `(?<=:)(?:...)$`, because the plugin wraps each as `[^:]*(PATTERN)[^:]*` inside its g:a field (read from license-maven-plugin 2.5.0 `ArtifactFilters.toGaPattern`; the patterns were checked against that wrapping in jshell); the duplicate `junit-.*` dropped; `check-archive-licenses.sh` fails unless the artifact pattern has the anchored form or if an alternative repeats, and matches the alternatives as `^(...)$` |
| 48 | Partly — 2026-11-08 (review F5): `check-asset-manifest.py` fails when a path `LICENSE.txt` names does not resolve (a `node_modules` entry resolves through its `package.json`) or when a path-style asset of `manifest-assets.txt` is missing from `LICENSE.txt`. Fixed with it: the removed hadoop-common lz4 path replaced by the nativetask lz4 sources, the moved `cJSON/` path, and libhdfspp's `third_party/uriparser2` (MIT, ships in the native client) added to both licence files. Open: the `licenses/` texts, and bundled code neither file knows about (libhdfspp `third_party/rapidxml-1.13` and `tr2`) |
| 53 | CI term: `texts`. Implemented 2026-11-09 (direction 2 of the 2026-11-08 gate; record: `2026-11-09-1110-R13-Text-Bundling-Store-Migration.md`) — the shipped set is now derived, not compared: the tarball's `licenses-binary/` directory is the R13 emitter's output from the manifest and the `texts/` store, so it equals the referenced set by construction, and the dist R40 step re-emits from the fresh manifest and diffs both tarballs' shipped directories. Per push, the R53 gate in `check-asset-manifest.py` keeps the reference direction against the store: every component-specific text (anything not in `texts-generic`) must still be referenced by its slug or `licenses-binary-aliases` token; alias/text and texts-generic/text mismatches fail; the 2026-11-08 pass removed 8 stale texts and added 2 missing UI package entries (class-variance-authority 0.7.1, react-hook-form 7.59.0) |
| 42 | **Retired by the trigger plan 2026-11-12** — the per-push/per-PR archive validation the wiring below provides was rejected by the community; the plan is a one-shot run during RC preparation (the R44 driver) plus scheduled refreshes, and drift is caught there fail-closed. The paths filter is kept in the workflow file only as a record of what per-push coverage would watch. Originally: Implemented on the branch 2026-11-09 (review F1, the review's stopgap; record: `2026-11-09-0120-F1-F2-Dependency-Coverage-And-Baseline-Freshness.md`) — the dist workflow's push paths now cover `**/pom.xml` and `hadoop-assemblies/**` (plus the root `pom.xml`), so every dependency or assembly change triggers an archive run whose R38/R40 gates validate the shipped set; the R10 gate's assumption comment updated to match. The cheaper per-push generator comparison against the last enumeration remains the upstream option if the ~38-min archive run per pom change is too heavy (revisit under R41/F3); pull-request coverage waits for R41 |
| 43 | Trigger plan 2026-11-12: with per-push triggers retired, the weekly cron (active on the fork, whose default branch is feat/LICENSES) and manual dispatch refresh the baseline; the 90-day cap and the fail-closed recovery command stand. Partly 2026-11-09 (review F2; record: `2026-11-09-0120-F1-F2-Dependency-Coverage-And-Baseline-Freshness.md`) — every R10 failure message (no baseline run, artifact download failure, missing generated manifest, drift) prints the exact dispatch command to recover, and the download is explicitly fail-checked. The baseline artifact sets `retention-days: 90` — the platform cap for a public repository (365 was rejected in review: GitHub limits artifacts to 1–90 days on public repos); expiry stays fail-closed behind the printed recovery command, and the cap is a non-issue upstream where the org's retention setting plus the weekly cron (R41) refresh the baseline. Open: the weekly cron stays inert until the workflow lands on the default branch (R41) — on the fork the baseline refreshes by push and dispatch only |
| 41, 45, 46, 49–52, 54 | Open — proposed in v2.3 from the 2026-11-08 review; TRIGGER-PLAN UPDATE 2026-11-12: R41's per-PR/push trigger proposal is DROPPED (community rejection) — the upstream ask is now the RC-time one-shot step (R44 driver, wired into create-release) plus an optional scheduled refresh |
| 44 | Implemented on the branch 2026-11-12 (T00028; test suite `test-run-release-checks.py`, 13 synthetic cases) — `dev-support/licenses/run-release-checks.sh` is the ONE callable, fail-closed release-time step: given the built tarballs and a repo checkout (plus the dependency inventory — pre-collected, `--collect`, or `--third-party`), it enumerates every binary tarball (source archives noted, never jar-gated), runs the archive gate (R36/R38/R39/R47/R26/R27), the stage-C asset gate (R7, main dist), regenerates LICENSE-binary + `licenses-binary/` from this run's enumerations (R40/R13) and gates committed-vs-generated drift (R10/R40), shipped-texts drift (R53) and NOTICE coverage (R14, via the same check module the per-push graph gate uses). GREEN publishes the RC artifact set (THIRD-PARTY.txt, generated manifest, texts dir, sha512) and an RM offline checklist (sign → stage → Nexus → tag → vote) into the output dir; RED prints a fix list attributing each failure to the exact requirement and the configuration file where the change belongs. `--verify-only <rc-dir>` is the offline voter verifier: checksums (and GPG with `--keys`) plus the full gate re-run against the RC's own THIRD-PARTY.txt and shipped manifest — one-command verification for voters. Validated locally on synthetic worlds (green + every fail-closed path); fork-CI ground-truth validation of the packaging rides the next push (owner approval) |
| 55 | Met for the filed proposal 2026-11-10 — every number in HADOOP-20078 traces to `analysis-3.5/`; the supporting release-history analysis (T00023) was verified against the FINAL release tags (`rel/release-3.4.3`, `rel/release-3.5.0` in ASF gitbox) and the published, sha512-verified 3.5.0 tarball, not RC proxies |
| 56 | First pass done 2026-11-10 (T00023, details in the work state): final release tag == last RC commit for both 3.4.3 and 3.5.0 — no release-only license commits exist; the tarball's LICENSE-binary is byte-identical to the repo file at the release commit and its `licenses-binary/` dir matches the repo dir at the tag. Maintenance happens entirely during development: 69/12/15 LICENSE-binary commits per cycle (3.4.3→3.5.0 / 3.4.2→3.4.3 / 3.4.1→3.4.2), almost all ride-alongs with dependency/CVE-upgrade PRs (~2 dedicated); 3.4.3→3.5.0 content delta = 68 version bumps, 70 new components, 8 removed; text dir 43→74 (+31, YARN UI v2 npm stack); NOTICE-binary byte-identical between the two releases. Refresh due at each upstream release |
| 40 | CI term: `drift`. Integrated 2026-11-08 — the committed `LICENSE-binary` IS the generator's output (artifact of record), regenerated and drift-gated by the dist workflow per run; validated against run 42413534907 and the 42427570912/42427570914 pair (record: `2026-11-07-1730-R40-Generator.md`, switch record: `2026-11-08-0800-Stage3-Switch-Generated-Manifest.md`). Validated on the 3.5 release line too (`feat/LICENSES-3.5`): the committed manifest is derived from run 42682946618's own 3.5.1-SNAPSHOT archive enumeration + inventory (218 g:a, 123 asset lines, 9 sections), with same-inputs confirmation runs in flight (records: `2026-11-09-1930-T00019-3.5-Port-Triage-And-Emitter-Unblock.md`, `2026-11-09-2020-T00019-3.5-Archive-Derived-Manifest.md`). NOTICE-binary stays curated (attribution corpus is prose; protected by R10) |

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
- **v2.3** — +41–54 from the 2026-11-08 requirements review
  (`2026-11-08-2336-License-Management-Requirements-Review.md`): upstream
  adoption (trunk and pull requests, Yetus, release gating, ASF
  infrastructure), dependency-change coverage, baseline freshness, anchored
  curation patterns, source-release accuracy and gate self-tests. Status
  table corrected: 10, 12, 35 and 38 partly met; 16 implemented.
- **v2.4** — requirement 10 narrowed to the files a gate can compare
  (`LICENSE-binary`, `licenses-binary/`); the others are assigned to R6,
  R48 and curation. Status: 47 implemented, 48 and 53 partly (review
  findings F4, F5 and F6 fixed).
- **v2.5** — R7 stage C complete 2026-11-09: the archive-side asset gate
  (`check-archive-assets.py`) covers file-level, jar/WAR-embedded and the
  release-shaped `-Pyarn-ui` UI WAR assets; npm package entries carry
  tiered version evidence (shipped vendor manifests, content probe,
  source pins, committed lock files via `ui-archive-trees`;
  `archive-asset-pin-exceptions` for compiled-in natives). 48 npm pins
  realigned to the modules' committed locks, `ember-cli-ic-ajax` pruned,
  `datatables` renamed `datatables.net`; status: 7 implemented (see
  `2026-11-09-0300-R7-Stage-C-Round-2-Lock-Evidence-And-UI-Wars.md`).
- **v2.6** — R13 and R14 implemented 2026-11-09. R13: the tarball's
  `licenses-binary/` directory is generated from the versioned `texts/`
  store and the manifest (emitter mode of `generate-archive-manifest.py`;
  the 66 hand-kept texts migrated into the store, `go` renamed `re2j`),
  wired into `dist-layout-stitching`, the cloud-storage assembly's
  pre-build step, and a dist-side R53 diff in the R40 drift step; the
  per-push R53 gate now checks the store. R14: a NOTICE-coverage gate
  enforces that every attribution-required component is mentioned in
  NOTICE-binary, covered by a copyright-carrying component text, or
  recorded in `notice-exceptions` with a justification (36 legacy-gap
  rows, self-cleaning). Status: 13, 14 and 53 implemented.
- **v2.7** — R14 gate fail-open fixed 2026-11-09 (round-2 independent
  review of T00005/T00006, pre-push): the coverage check credited
  never-shipping `texts-generic` texts (JSON.org `json` false-matching
  `javax.json` coordinates) and section-kind texts as attribution
  coverage; coverage texts are now restricted to the R13 emitter's ship
  set, 3 `notice-exceptions` rows added (36 → 39), and the shared
  alias/texts-generic parsers were deduplicated with explicit
  empty-token rejection. Status: 13, 14 and 53 implemented (unchanged;
  this entry records the correction).
- **v2.8** — the system validated on a release line (T00019,
  `feat/LICENSES-3.5`, 2026-11-09): ported to branch-3.5 and validated
  against the official 3.5.0 release. Three dist runs; the final one
  (42682946618) built release-shaped (`-Pyarn-ui` restored, profiles in
  the module poms) and the archive asset gate passed unmodified — every
  trunk-derived npm pin validated against 3.5's UI lock files. The
  committed `LICENSE-binary` became the manifest generated from that
  run's own archive enumeration + inventory (R40 flow; 218 g:a, 123
  asset lines, 9 sections, 66 shipped texts); the R53/R14/asset-manifest
  gates are green after a self-cleaning curation pass (8 store texts for
  components that no longer ship, 7 stale `notice-exceptions` rows
  dropped, 1 added). R48 stays red by design: the manual source-release
  files are the comparison baseline and their findings are report
  material, not fixes. The automated-vs-manual comparison package
  (`analysis-3.5/` on that branch — provenance-separated sources, three
  separate deviation analyses, executive summary) is committed at
  75d1b84101e and backs the proposal to adopt the system into Hadoop's
  release procedure (R44); same-inputs confirmation dist runs were in
  flight at commit time and are recorded in the work state. Status:
  R40 gains 3.5-line validation evidence (row updated); no requirement
  changed state.
- **v2.9** — +55–56 from the upstream release-history analysis (T00023,
  2026-11-10, for the HADOOP-20078 production proposal): verified against
  the final release tags (`rel/release-3.4.3`, `rel/release-3.5.0`, ASF
  gitbox) and the published 3.5.0 tarball that no release-only license
  commits exist (final tag == last RC commit for both releases; the
  tarball's files are byte-identical to the repo at the release commit),
  and that license-file maintenance happens entirely during development
  (69/12/15 commits per cycle, riding dependency-upgrade PRs) — which is
  where the measured drift accumulates and why a release-time
  generate-and-verify step (R44) is the right adoption slot. R55 pins the
  evidence provenance (final artifacts, not RC proxies), R56 makes the
  per-release license-history analysis a standing duty. Status: no
  existing requirement changed state.
- **v3.0** — R44 implemented 2026-11-12 (T00028): the release-time
  driver `dev-support/licenses/run-release-checks.sh` packages the whole
  generate-and-verify suite as one callable, fail-closed step for the
  tarballs being voted on — the same gates the CI workflows run
  (archive R36/R38/R39/R47/R26/R27, stage-C assets R7, committed drift
  R10/R40, texts R53, NOTICE coverage R14), with a RED fix list that
  names the requirement and the configuration file, a GREEN RC artifact
  set (THIRD-PARTY.txt, generated manifest, texts dir, sha512) plus an
  RM offline checklist, and an offline `--verify-only` voter mode over
  a staged/downloaded RC. Synthetic coverage: 13-case suite
  (`test-run-release-checks.py`); fork-CI ground-truth validation of
  the packaging rides the next push. R44 status: implemented-on-branch.
  No other requirement changed state.
- **v3.1** — CI naming convention + trigger plan change 2026-11-12.
  (1) Every CI-facing gate now carries a human TERM (not the requirement
  ID) in workflow step names, gate logs and the R44 driver's fix list:
  `assets` (7), `drift` (10, 40), `bundling` (13), `notice` (14),
  `inventory` (26–27), `versions` (31), `jar-naming` (36), `coverage`
  (38), `exclusions` (39), `exclusion-pattern` (47), `texts` (53);
  recorded per requirement in the status rows above. R-IDs remain the
  doc-internal pointers and the check scripts' stable output tokens.
  (2) Trigger plan (owner, community feedback): per-push and per-PR
  license gates are RETIRED — `licenses.yml` runs quarterly by schedule
  or on dispatch, `licenses-dist.yml` weekly by schedule or on dispatch
  (its weekly cron is now the active baseline refresher on the fork),
  and the authoritative checks run ONE SHOT during RC preparation via
  the release workflows calling the R44 driver. R41's PR-trigger
  proposal is dropped; R42's push-path wiring is retired (kept inert as
  a record); R43's weekly schedule is the standing baseline refresh.
- **v3.2** — workflow consolidation 2026-11-12: the two standing
  workflows merged into ONE, `licenses-ground-truth.yml` ("Licenses:
  ground truth (archive + source gates)"), because the collect job
  always consumed the archive job's baseline — now job
  `source-gates` (needs job `archive-ground-truth`) validates the
  committed state against the SAME run's archive artifact and the
  fragile cross-run baseline lookup (the retired R10 selection logic)
  is gone. Workflow family and titles: `licenses-ground-truth.yml`
  (standing validation, weekly + dispatch), `licenses-verify-rc.yml`
  ("Licenses: verify release candidate"), `licenses-build-rc-unsigned.yml`
  ("Licenses: build unsigned RC bundle"). No gate logic changed.
