<!--
  Licensed to the Apache Software Foundation (ASF) under one or more
  contributor license agreements.  See the NOTICE file distributed with
  this work for additional information regarding copyright ownership.
  The ASF licenses this file to You under the Apache License, Version 2.0
  (the "License"); you may not use this file except in compliance with
  the License.  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->
# Pruning support: what the licence tooling can add, and the jar layout report (2026-11-12 16:31 CET)

## Context

In apache/hadoop#8943 (HADOOP-20070, Netty 4.2.20), pan3793 asked to
prune jars Hadoop does not use (e.g. `netty-codec-redis`) before
upgrading; pjfanning asked for a regular check of the binary tarball
against `LICENSE-binary` instead of reviewing it per PR. This system
already does that check (R36–R40) and keeps `LICENSE-binary` in step with
whatever ships, but it gave no input for deciding what to prune.

## What the existing data answers

`enumerate-archive-jars.py` already records every jar, its lib directory
and its `g:a:v`, including jars nested in WARs. That answers "what ships,
where, how many copies". It does not answer the two questions pruning
needs: why a jar is in the archive (which dependency path), and whether
anything uses it.

## Extensions and estimates

| # | Extension | Reuses | Effort | Status |
|---|---|---|---|---|
| 1 | Jar layout report: same artifact at two versions in one lib directory, artifacts at several versions, the same jar copied into several lib directories, extra on-disk bytes | `archive-jars.tsv`; the R40 generator's row loader; the dist workflow's per-archive loop and artifact upload | 0.5 day | **Done** (this record) |
| 2 | Unused-jar candidates: per classpath unit (everything outside WARs, each WAR), start from Hadoop's own jars, follow class references (planned with `jdeps`, built in pure Python — see below — plus `META-INF/services`), report shipped jars never reached; a self-cleaning keep-list for jars loaded by name (Netty native transports, Jersey/HK2 discovery, logging back-ends, JDBC drivers) | The enumerator's unpacked tree; JDK 17 `jdeps` in the build image; the self-cleaning curation-file pattern of `archive-asset-allowlist` | 2–3 days + 1–3 days keep-list curation | **Done** as a dry run (below); keep-list curation open |
| 3 | Dependency path per shipped jar (`mvn dependency:tree`, joined to the jar list by module) | The inventory step of the same workflow | 1–2 days, +5–10 min per run | Deferred |
| 4 | Archive delta for a pruning PR: jars added/removed against the baseline run, in the job summary | The R10 baseline-artifact download; the R40 regeneration already drops the licence lines | 0.5–1 day | **Done** (below) |

What none of them does: prove a removal safe (the archive build runs
`-DskipTests`; a pruning PR still needs the full test suite), protect
downstream users (`share/hadoop/*/lib` is also the user-application
classpath, so an unused jar can still be relied on — a compatibility
call for the project), or edit poms (replacing `netty-all` with the
modules Hadoop uses stays manual; #4 shows its effect).

## The jar layout report (#1)

- `jar-layout-report.py` reads one `archive-jars.tsv` and prints
  Markdown. Rows are read with `load_archive_rows` from
  `generate-archive-manifest.py` — the same validation,
  `archive-jar-mappings` promotion and own-jar exclusion the R40
  generator uses; the generator's `load_archive_ga_versions` is now
  built on it, and its output is unchanged (byte-identical
  `LICENSE-binary` on run 42868918625's inputs). Jars it cannot identify
  are listed, not counted. Report only: exit 0 on well-formed input, 2 on
  malformed input.
- `licenses-dist.yml` runs it per archive after the enumeration, adds it
  to the job summary and uploads `layout-report.md` with the ground
  truth. A crash of the script fails the step.
- `test-jar-layout-report.py` is a synthetic self-test; it catches three
  seeded mutations (conflict threshold, size arithmetic, own-jar
  filter). Like the other self-tests it is not yet run per push (R49).

### First results (trunk, run 42868918625, `7f0f98943e4`)

543 third-party jar files, 315 distinct `g:a:v`, 8 lib directories:

- **1 same-directory conflict:** `com.google.guava:failureaccess` 1.0.2
  and 1.0.3 side by side in `share/hadoop/common/lib` — the strongest
  first pruning JIRA (a real classpath conflict, not only size).
- **13 artifacts at several versions:** grpc 1.69 (`yarn/csi/lib`) vs
  1.70 (`common/lib`) ×8 modules, `proto-google-common-protos`,
  `error_prone_annotations`, opentelemetry 1.47 vs 1.49
  (`yarn/timelineservice/lib`), `zookeeper-jute` 3.6.2 in the catalog
  WAR vs 3.8.6 elsewhere.
- **140 `g:a:v` copied into several lib directories:** 78 shared by
  `common/lib` + `hdfs/lib` + the catalog WAR, 24 by `hdfs/lib` + the
  WAR, 21 by the WAR + `yarn/lib`, 13 by `common/lib` + `hdfs/lib`, 4 by
  `common/lib` + the WAR. `dev-support/bin/dist-layout-stitching`
  deduplicates only the modules after common and hdfs, so `hdfs/lib`
  repeats `common/lib`.
- Netty: 9 jars in `common/lib`, 36 in `hdfs/lib`, 36 in the catalog WAR;
  the unused-looking codecs (`redis`, `stomp`, `mqtt`, …) come in through
  `netty-all` in `hdfs/lib` and the WAR. Extension #2 is what answers
  whether they are used.

The cloud-storage dist (129 jars, one directory) has no conflicts,
splits or copies.

Not yet verified: the extra-bytes figures, which need the unpacked tree
`--root` points at; the downloaded artifact has only the TSVs, so the
first archive run with this change is the first real check.

## Unused-jar candidates (#2) and archive delta (#4), dry run (2026-11-12)

Both run in their own step of `licenses-dist.yml`, after the gates, with
`continue-on-error`: they only write reports (`unused-jar-candidates.txt`
per archive, `archive-delta.txt`, both in the artifact and the job
summary) and can never turn the run red, which the per-push R10 gate
depends on. Nothing in the tree is changed.

### unused-jar-candidates.py

- **jdeps does not work here:** on the 3.5.0 tree it aborts with
  `FindException: Module org.slf4j not found, required by org.dnsjava`
  (modular jars on a class-path scan), and `--ignore-missing-deps` does
  not help. The scan is pure Python instead: it reads each class file's
  constant pool (class entries, descriptors, generic signatures and
  string constants, which also catches `Class.forName("...")` literals)
  and the text resources of each jar.
- **Model:** nodes are the TSV's jars plus each WAR's `WEB-INF/classes`;
  roots are Hadoop's own jars (and jars the curation cannot identify),
  every `WEB-INF/classes`, and the class names in the distribution's
  `etc/`, `bin/`, `sbin/` and `libexec/`. A reference resolves to the
  same unit first (a WAR's own copy), else anywhere. Service providers
  count as used when their interface's jar is used, or the interface is
  a JDK one (not `javax.annotation.processing.Processor`, compile-time
  only). Conservative: any reference is use.
- **False "used" found and fixed:** `META-INF/native-image/**` (GraalVM
  reflection configs) and `META-INF/maven/**` (embedded poms) name
  classes without loading them. Shaded jars (`hadoop-client-minicluster`,
  `hbase-shaded-client-byo-hadoop`) carry both, unrelocated, for every
  netty module they shade, which made every netty codec in `hdfs/lib`
  look used. Both trees are skipped now.
- `unused-jar-keep` (empty) moves jars known to be loaded by a name the
  scan cannot see out of the candidates; stale rows are reported.
- **Resources** (review fix): a non-class entry outside `META-INF/`
  counts as used when a string constant names its path with a directory
  and an extension (`getResource("a/b/schema.xsd")`, optional leading
  slash; bare names like `log4j.properties` do not count). It changes no
  3.5.0 verdict. The review's example for it was wrong: `jetty-webapp`
  names `javax/servlet/jsp/resources/jsp_2_3.xsd`, but `jsp-api` ships
  no `.xsd` files, so `jsp-api` stays a candidate.
- Self-test `test-unused-jar-candidates.py`; it catches ten seeded
  mutations (metadata skip, long/double slots, compile-only services,
  string constants, root text files, same-unit preference, and four on
  resource indexing and the resource-path pattern).

**Official 3.5.0 tarball** (sha512-verified, 629 jars, 34–41 s, 175 MB):
41 candidates, 23 no-class jars. An independent byte-level search of
every other jar for each candidate's packages (relocated names in shaded
jars ignored) found no reference to any of the 41 from its own unit; the
only hits were split packages (`netty-codec` and `netty-handler` hold
one class each in the `codec/xml` and `ssl/ocsp` packages) and other
units' references to the WAR copies' main-unit twins.

- `hdfs/lib`: netty `codec-haproxy`, `codec-memcache`, `codec-mqtt`,
  `codec-redis`, `codec-smtp`, `codec-stomp`, `codec-xml`,
  `handler-ssl-ocsp`, `transport-rxtx`, `transport-sctp`,
  `transport-udt` — the modules `netty-all` pulls in and nothing uses
  (the apache/hadoop#8943 question); the same set again in the catalog
  WAR, plus `codec-http2`, `codec-socks`, `handler-proxy` there.
- `common/lib` (+ `hdfs/lib` copies): `azure-storage` and
  `azure-keyvault-core` (gone on trunk already), `kerb-crypto`,
  `kerby-config`, `jakarta.servlet.jsp-api`.
- `yarn/lib`: `commons-csv`, `jcodings`, `jetty-annotations`,
  `jetty-plus`, and `asm-commons`/`asm-tree` (which only
  `jetty-annotations` would use).
- Catalog WAR: `jersey-media-json-jettison`.
- No class files (review by hand): netty native transports and
  `resolver-dns-native-macos` classifier jars, `netty-all` (an
  aggregator in 4.1), `listenablefuture` (the empty Guava stub),
  `grpc-context` in `yarn/csi/lib`.

Each candidate still needs a human check before any pom change: the
scan cannot see names built at run time or user code relying on
`share/hadoop/*/lib`.

### archive-delta.py

Third-party jars removed (`-`), added (`+`), re-versioned (`~`) or
copied into other lib directories (`#`) between two runs' enumerations,
archive by archive; the release version is normalized out of paths (WAR
file names repeat it) and out of archive names (review fix: a trunk
version bump matched no archive and compared nothing). A `~` line is
followed by where each dropped (`    -`) and new (`    +`) version ships
(review fix). In the workflow the baseline is the last successful run of
the workflow on the branch, fetched with the same API query as the R10
gate; with no baseline, or an expired one, it says so and skips. The
step goes on past a failing report and fails at its end (review fix:
one crash used to stop the rest), still without turning the run red.

- Two consecutive trunk runs (42704097221 → 42868918625, docs-only
  change): no change.
- 3.5.0 → trunk (`7f0f98943e4`): 2 removed (`azure-storage`,
  `azure-keyvault-core`), 89 added, 60 re-versioned, 7 copy changes (158
  in all) — including `failureaccess` gaining 1.0.2 in `common/lib` next
  to 1.0.3, the same-directory conflict the layout report shows.
- Self-test `test-archive-delta.py`.

## First CI results on trunk (run 43261414588, `1c737274769`)

The archive run is green, every step included ("Pruning dry run":
success). Reports in its `archive-ground-truth` artifact.

**Layout report** (first produced by run 43249270763): the `--root`
sizes work on the real tree; the 78 jars shared by `common/lib`,
`hdfs/lib` and the catalog WAR take 41.6 MiB in redundant on-disk
copies, the 13 shared by `common/lib` and `hdfs/lib` only 1.1 MiB.
Groups whose only other copy is inside a WAR print "0.0 MiB" (WAR copies
are not counted).

**Archive delta** against run 43249270763: 0 changes in both archives,
as expected (same dependencies).

**Unused-jar candidates, `hadoop-3.6.0-SNAPSHOT`:** 43, plus 24 jars
with no class files.

- Same as the official 3.5.0 tarball: the unused netty modules in
  `hdfs/lib` (`codec-haproxy`, `codec-memcache`, `codec-mqtt`,
  `codec-redis`, `codec-smtp`, `codec-stomp`, `codec-xml`,
  `handler-ssl-ocsp`, `transport-rxtx`, `transport-sctp`,
  `transport-udt`) and again in the catalog WAR with `codec-http2`,
  `codec-socks`, `handler-proxy`; `kerb-crypto`, `kerby-config`,
  `jakarta.servlet.jsp-api`; `commons-csv`, `jcodings`,
  `jetty-annotations`, `jetty-plus`, `asm-commons`, `asm-tree` in
  `yarn/lib`; `jersey-media-json-jettison` in the WAR.
- Gone since 3.5.0: `azure-storage`, `azure-keyvault-core` (trunk
  removed them).
- New on trunk, two kinds of pruning target the netty discussion did not
  cover:
  - **Unshaded copies of SDKs a connector already shades into itself:**
    `bce-java-sdk` (`hadoop-bos` relocates `com.baidubce` to
    `org.apache.hadoop.fs.bos.shaded.com.baidubce`),
    `grpc-google-cloud-storage-v2` and `grpc-inprocess` (`hadoop-gcp`
    shades `com.google.api.grpc` and relocates `io`, `com`, `org` under
    `com.google.cloud.hadoop.repackaged.ossgcs`). Nothing loads the
    separate jars.
  - **Shipped test tooling:** `org.jacoco.agent-0.8.5-runtime.jar`
    (code coverage) in `common/lib`, listed in `LICENSE-binary`. The
    README attributes it to a cloud SDK declaring it at compile scope;
    which one is not yet confirmed.

**Unused-jar candidates, `hadoop-cloud-storage-dist-3.6.0-SNAPSHOT`:**
5 — the same `bce-java-sdk`, `grpc-google-cloud-storage-v2`,
`grpc-inprocess` and jacoco agent, plus `javax.annotation-api`; no-class:
`listenablefuture` (the empty Guava stub) and `grpc-context`.

All are candidates for a human check, not removals.

## Why so few candidates, and the optional-feature section (2026-11-12)

**The low count is real.** Rerun on the official 3.5.0 tarball under
stricter models (scratch harness, not shipped), the never-referenced set
stays small: 41 jar files / 26 g:a (shipped tool), 41 / 26 without
Hadoop's test jars as roots, 49 / 30 class-level, 51 / 31 class-level
without test roots, 55 / 33 also ignoring class names in third-party
strings; giving `share/hadoop/client` its own class path changes none.
No test framework ships, so test roots change nothing. Traced chains are
genuine (`jsch` ← `SFTPFileSystem`, `re2j` ← `GlobPattern`, `jline` ←
the YARN container shell, `curator-recipes` ← the RM leader elector).
The strictest model adds `proto-google-common-protos`, `kerby-pkix`,
`kerby-util` and netty `codec-dns`, `codec-socks`, `resolver-dns`,
`resolver-dns-classes-macos`, `transport-classes-kqueue`.

**The larger opportunity is feature-level**, now a second report
section: jars used only by optional features. Each Hadoop jar belongs to
a feature by where it ships (core: `share/hadoop/{common,hdfs,mapreduce,
yarn}`; optional: each WAR, each `tools/lib` tool, `yarn/timelineservice`,
`yarn/csi`, `share/hadoop/client`, test jars). Two defects found and
fixed while building it, both of which made everything in the WAR look
core:

- JDK service providers were all seeded into core; six WAR jars
  (`solr-solrj`, `netty-common`, `woodstox-core`, `bcprov`, `dnsjava`,
  `mssql-jdbc`) provide JDK interfaces. A provider now belongs to the
  feature where it ships.
- 207 service edges crossed a class-path boundary (main-class-path
  `SecurityInfo`, `TokenIdentifier`, `TokenRenewer`… interfaces pulling
  WAR providers, and the WAR's copies pulling main ones). Service edges
  now stay within one class path; a provider whose interface is not on
  its own class path is a seed, as a JDK one. The never-referenced
  section is unchanged by both fixes.

**3.5.0 result:** 129 jar files used only by optional features — 22
artifacts that only these features need, and 107 private copies of
artifacts core uses too:

| Feature | Jars | Only this feature needs | Private copies |
|---|---|---|---|
| YARN application catalog WAR (82 MB, 158 jars) | 116 | 9: `solr-solrj`, `httpmime`, Jetty `http2-client`/`-common`/`-hpack`/`-http-client-transport`, `jetty-alpn-client`, `jetty-alpn-java-client`, `jcl-over-slf4j` | 107 |
| Timeline service v2 (`yarn/timelineservice`, 37 MB) | 11 | 11: the Cosmos DB / RxJava stack (`azure-cosmosdb*` ×4, `rxjava`, `rxjava-string`, `rxjava-extras`, `rxnetty`, `java-uuid-generator`, `commons-validator`, `commons-digester`) | 0 |
| `tools:hadoop-kafka` | 1 | `kafka-clients` (8.8 MB) | 0 |
| `tools:hadoop-resourceestimator` (+ tests) | 1 | `ojalgo` (1.6 MB) | 0 |

Dropping or slimming those features is what would remove them; the
catalog WAR is 15% of `share/hadoop` and bundles its own copies of
`hadoop-common`, `hadoop-hdfs`, `hadoop-hdfs-client`, `guava`, `bcprov`
and even `hadoop-common-3.5.0-tests.jar`. Self-test: the feature
classification, core exclusion, provider placement (WAR, `tools/lib`),
the same-class-path service rule and the private-copy note are each
covered (all seeded mutations caught).
