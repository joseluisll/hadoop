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
| 2 | Unused-jar candidates: per classpath (`common`+`hdfs`, `yarn`, each WAR), start from Hadoop's own jars, follow class references (`jdeps -R -summary --ignore-missing-deps`, plus `META-INF/services`), report shipped jars never reached; a self-cleaning keep-list for jars loaded by name (Netty native transports, Jersey/HK2 discovery, logging back-ends, JDBC drivers) | The enumerator's unpacked tree; JDK 17 `jdeps` in the build image; the self-cleaning curation-file pattern of `archive-asset-allowlist` | 2–3 days + 1–3 days keep-list curation | Open |
| 3 | Dependency path per shipped jar (`mvn dependency:tree`, joined to the jar list by module) | The inventory step of the same workflow | 1–2 days, +5–10 min per run | Open, only if reviewers ask |
| 4 | Archive delta for a pruning PR: jars added/removed against the baseline run, in the job summary | The R10 baseline-artifact download; the R40 regeneration already drops the licence lines | 0.5–1 day | Open |

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
