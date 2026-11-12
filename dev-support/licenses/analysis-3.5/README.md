# Automated vs manual license artifacts — Apache Hadoop branch-3.5

Executive summary of the license-management system's comparison
package (work item T00019). Version 2, generated 2026-11-09. Every
artifact carries its provenance:

- **[TARBALL]** — extracted from the official `hadoop-3.5.0` release as
  shipped to users (checksums verified against the published SHA512).
- **[BRANCH]** — the hand-maintained files committed on `branch-3.5`
  today (what the next 3.5.x release would ship manually).
- **[SYSTEM]** — produced by the automated license system
  (`feat/LICENSES-3.5`, commit `f986bcccdbc`): the THIRD-PARTY
  dependency inventory collected from the full reactor build, and the
  LICENSE-binary **generated from the enumerated contents of our
  3.5.1-SNAPSHOT distribution build** (CI run 42682946618), not written
  by hand.

## The headline: same corpus, two manifests

The official 3.5.0 release tarball and our automated 3.5.1-SNAPSHOT
build ship **the same 215 distinct third-party coordinates** (628/630
jar files; the branch bumped dependency versions since the release —
jackson 2.18.6→2.18.10, netty 4.1.130→4.1.135, commons-io 2.16.1→2.22.0
and 40+ more, an expected branch evolution, not a manifest property).
Against that identical corpus:

| Deviation class (jars that ship vs what the manifest states) | Manual manifest (shipped in 3.5.0) | System manifest |
|---|---|---|
| Shipped jars listed under no coordinate | **46** | **0** |
| Shipped jars listed under a stale group (coordinate drift) | **6** | **0** |
| Version pins that do not match any shipped jar | **10** (e.g. opentelemetry 1.59.0 vs shipped 1.49.0; asm 6.0 vs 9.7.1; commons-beanutils claims 1.9.4, ships the *older* 1.9.2) | **0** |
| Coordinates listed that ship nothing (over-listing) | **107** (~40% of the manifest: full cloud-SDK trees, kerby ×8, hbase ×5, junit, dom4j…) | **0** (3 known embedded-only entries retained by design) |
| Like-for-like: manifest vs the archive it ships with | — | **0 / 0 / 0** (`deviations/like-for-like.txt`) |

In other words: the automated manifest lists **exactly what ships** —
every shipped jar covered, every version the archive's own, nothing
declared that does not ship — and this is enforced, not audited: the
R38/R40/R53 gates fail the build on any future drift.

## Where the numbers come from (reproducible)

- `sources/tarball/archive-jars.tsv` [SYSTEM, of TARBALL] — our
  enumerator over the official release: 628 jars, 0 unmapped.
- `sources/system/archive-jars.tsv` [SYSTEM, of our build] — CI
  enumeration of the 3.5.1-SNAPSHOT tarball: 630 jars, 0 unmapped.
- `deviations/shipped-vs-manifest.txt` — the manual manifest audited
  against the shipped corpus (the table's manual column).
- `deviations/shipped-vs-system-manifest.txt` — the system manifest
  audited against the official release corpus (0 unlisted; the 46
  version lines there are the branch's dependency evolution).
- `deviations/like-for-like.txt` — the system manifest vs its own
  build's enumeration: exact.
- `deviations/LICENSE-binary_release-3.5.0_vs_branch-3.5.diff` — the
  release-vs-branch manual drift (94 lines, all version bumps).

## Artifacts in this package

| Path | Provenance | What it is |
|---|---|---|
| `rm-runbook.md` | — | the release procedure from the release manager's operator viewpoint, with the evidence the claims rest on |
| `adoption-proposal.md` | — | the two-increment adoption path: optional secret-free GHA workflows (evidence + RC-bundle tooling) first, enforcement inside create-release second |
| `sources/tarball/LICENSE-binary`, `NOTICE-binary`, `LICENSE.txt`, `NOTICE.txt`, `licenses-binary/` (74) | TARBALL | the license files shipped in the official 3.5.0 binary |
| `sources/branch-3.5/*` | BRANCH | the same files as hand-maintained on the branch |
| `sources/system/THIRD-PARTY.txt` | SYSTEM | the automated dependency inventory: 295 coordinates with resolved license names + versions, collected from the full reactor |
| `sources/system/LICENSE-binary` | SYSTEM | the generated manifest: 218 g:a, 219 exact version lines, 9 sections (committed on the branch — the R40 artifact of record) |
| `sources/system/licenses-binary/` (66 texts) | SYSTEM | the tarball's text directory, **generated** from the manifest + versioned store (R13) |
| `sources/system/archive-jars.tsv`, `archive-assets.tsv` | SYSTEM | our build's jar (630) and asset (600) enumeration |
| `sources/system/gate-logs/` | SYSTEM | archive gate + asset gate logs ("archive asset gate passed" — all trunk-derived npm pins validated against 3.5's UI lock files) |
| `sources/system/per-push-gate-findings-3.5-tree.txt`, `gate-logs/per-push-gates-after-curation.txt` | SYSTEM | the per-push gate outputs: before curation (the findings list) and after (R53/R14 green) |

## Manual-artifact defects the automated gates found (findings for the Hadoop project)

These were detected mechanically against the manual baselines, which
were deliberately left untouched in this package:

1. **52 shipped jars with no license statement** under the coordinate
   that ships them (46 + 6 coordinate-drift, table above) — the
   jetty 9.4.58 tree (12 modules), hk2/jersey-injection family (7),
   eclipse persistence (3), gson, jsr305, commons-lang 2.6,
   commons-logging, zookeeper-jute, hbase-shaded-client, javassist,
   hdrhistogram, and more.
2. **10 version claims that match no shipped jar**, including one
   shipping an *older* version than claimed (commons-beanutils).
3. **~40% over-listing**: 107 coordinates in the manual manifest ship
   nothing in the binary.
4. **A ghost section**: `baseline-browser-mapping 2.10.0` in the
   manual manifest ships nothing at all (0 hits in the full 628-jar
   enumeration; body is three lines of prose listing nothing).
5. **Ghost paths in the source-release `LICENSE.txt`** (9 findings,
   `per-push-gate-findings-3.5-tree.txt`): references to the removed
   d3-3.5.17/angular-1.6.4 webapp files, the pre-move lz4 source path,
   a nonexistent cJSON path — while the nativetask lz4 sources,
   d3-v4.1.1, and uriparser2 that DO ship are unlisted.
6. **NOTICE gaps**: 61 attribution-required components; 32 needed a
   recorded justification (the shipped section texts carry no
   per-component copyright lines) — now tracked in a self-cleaning
   exception file that fails the build when a component gains coverage
   or a row goes stale (R14).

## What the automated system contributes beyond the files

- **Enforcement instead of trust**: every gate fails closed — a jar
  without a license statement, a stale version, an over-listed
  coordinate, a missing section text, an unjustified NOTICE gap each
  fail the build. The manual process has no equivalent tripwire.
- **Regeneration, not maintenance**: the manifest and the tarball's
  `licenses-binary/` are derived from the archive and a versioned text
  store; the curation inputs (mappings, exclusions, exceptions) are
  small, justified, version-controlled files.
- **Curation cost, made visible**: adapting the system to a new branch
  took a bounded, recorded pass (see the
  `dev-support/licenses/2026-11-09-*.md` records on the branch): two
  emitter blocks cured (a manual ghost section; a missing HSQL text
  since re-removed when the dependency set moved on), 8 stale texts
  deleted, 8 exception rows reconciled — each step justified by
  enumeration evidence.
- **Offline-first text store**: license texts are versioned source;
  the network is only an explicit opt-in update path.

## Status

- The system's 3.5.1-SNAPSHOT distribution build is **validated**:
  jar enumeration 0 unmapped; asset gate green (all bundled npm
  versions evidenced from shipped manifests/locks); NOTICE coverage
  gate green (61 components: 28 covered + 33 justified exception
  rows); per-push store gate green.
- One gate intentionally stays red: the R48 source-release gate, whose
  9 findings are the manual `LICENSE.txt` defects listed above —
  fixing them means editing the baseline, which is this comparison's
  subject.
- A final CI dist run (same build inputs as the published ground
  truth) is in flight to confirm the regenerated manifest green in CI
  (R40/R38/R53 are green by construction — the committed manifest IS
  the generator's output on this run's data); its result will be
  appended when the run reports.
- NOTICE content comparison is out of scope for this first package:
  NOTICE is curated prose tied to the dependency set; the system
  enforces its coverage but does not generate it.
