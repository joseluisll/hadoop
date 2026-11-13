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
# Pruning analysis: per-jar inbound counts and who-pulls-it attribution on 3.5.0 (2026-11-13 04:12 CET)

## Context

Work item T00034 (owner-approved 2026-11-12) called for a standalone
jdeps-based pruning analysis of the shipped-but-unused jars, demoed on
the official hadoop-3.5.0 tarball, reporting per jar: g:a, class count,
inbound references from Hadoop, inbound references from other jars, and
a CANDIDATE verdict, plus who-pulls-it dependency attribution. When the
work started it became clear the project already ships a validated
engine for the reachability half: `unused-jar-candidates.py` (landed
with the pruning dry run, 2026-11-12) scans the same archive with a
pure-Python constant-pool scanner, mutation-sweep-validated, and had
already produced the 3.5.0 candidate list. The owner chose (2026-11-13)
to extend the existing tool instead of building a second jdeps script,
and to close T00034 as covered by it. This record documents the
extension and the 3.5.0 evidence run. The change was reviewed
independently before it was committed (see "Review before commit").

## Why not jdeps

The originally specified engine was measured and rejected on this
archive's real data:

- `jdeps --multi-release 17 -verbose:class` over the deduplicated share/
  jars cannot build its module configuration: jars carrying
  `module-info.class` (dnsjava, asm-tree, jackson-annotations, ...) become
  explicit modules whose `requires` must resolve. dnsjava requires
  org.slf4j, and jdeps died on `FindException: Module org.slf4j not
  found` even with `--ignore-missing-deps` (config-time failure, before
  analysis; the same failure a 56-minute full-tree run hit on 2026-11-12).
- Making the module set resolvable needs an iterative eviction loop:
  20 jars fail automatic-module derivation outright (all the
  `hadoop-*-sources.jar` / `-test-sources.jar` files and
  hadoop-shaded-protobuf_3_25), and `asm-tree-9.7.1` requires
  `org.objectweb.asm` transitively — but asm core does not ship in the
  archive at all (only asm-tree and asm-commons do), so asm-tree can
  never sit on a resolvable module path.
- The pure-Python scanner needs none of this, runs the whole archive in
  ~40 s, and its rules were already mutation-sweep validated.

## What was added to unused-jar-candidates.py

- `-t`/`--tsv <file>` writes the full per-jar-file pruning report (every
  third-party jar file, used or not): `g:a:v`, `path`, `classes`,
  `inbound_hadoop`, `inbound_other`, `verdict`, `pulled_in_by`. The
  verdict is the existing closure-based one (candidate / no-class /
  kept / used / used-optional); the inbound counts are DIRECT
  references only and are informational. `inbound_hadoop` counts
  references from Hadoop's own jars, WEB-INF/classes and the
  distribution's etc/bin/sbin/libexec text files (one pseudo-source);
  `inbound_other` counts references from other third-party jars.
  References from the jar itself and from another copy of the same g:a
  (lib directories repeating common/lib) do not count — a candidate
  referred to only by its own duplicate is still unused. The same-g:a
  rule subsumes the self-edge case, so there is no separate self check.
- `--poms <source-tree>` adds the who-pulls-it attribution: it walks
  the Hadoop source checkout's pom.xml files and names, per artifact,
  every module whose pom declares it, sorted (any `<dependency>`
  element, dependencyManagement included). `transitive` marks an artifact no
  module pom declares directly — it arrives through another artifact's
  own pom (the netty codecs through netty-all; resolving that needs the
  parent artifact's pom, which the tool does not fetch). Attribution is
  informational: where a jar comes from, never a removal proof.
- The existing text report is unchanged (its consumers keep their
  shape); the TSV is additional output.

Test suite extended (28-row fixture world, +1 duplicate-copy case):
duplicate copies of one g:a, self-referencing classes, service-edge
inbound, config-text inbound, WAR private copies, dependencyManagement
attribution, fail-closed on `--poms` with no pom. Mutation sweep over
the counting logic: all four injected faults (drop same-g:a exclusion,
swap hadoop/other attribution, drop text pseudo-source, count own-side
edges as other-jars) are caught by the suite; the code was restored
byte-identical afterwards.

## The 3.5.0 evidence run

Official hadoop-3.5.0 binary tarball, sha512-verified against the
published digest; archive TSV from the preserved 3.5.0 baseline
enumeration; poms from the official 3.5.0 source tarball. Runtime
39.7 s, 443 third-party jar files:

- verdicts: 263 used, 116 used-only-by-optional-features, 23 no-class,
  41 candidate rows = 26 unique g:a (the txt report's candidate section
  lists exactly the same 26).
- candidates: the netty codec/handler/transport family inside the YARN
  catalog WAR and hdfs/lib (codec-haproxy/http2/memcache/mqtt/redis/
  smtp/socks/stomp/xml, handler-proxy, handler-ssl-ocsp,
  transport-rxtx/sctp/udt), azure-keyvault-core 1.0.0 + azure-storage
  7.0.1, kerb-crypto + kerby-config 2.0.3, jakarta.servlet.jsp-api
  2.3.6, commons-csv 1.9.0, jetty-annotations + jetty-plus
  9.4.58.v20250814, jersey-media-json-jettison 2.46, jcodings 1.0.13,
  asm-commons + asm-tree 9.7.1.
- no candidate has any inbound reference from Hadoop's side (hadoop
  classes, WEB-INF/classes or config text) — by construction of the
  verdict, but the TSV column makes it visible per row.
- four candidates are referenced only by ANOTHER candidate (the chain
  is jointly unused): azure-keyvault-core ← azure-storage,
  netty-codec-socks ← netty-handler-proxy, jetty-plus ←
  jetty-annotations, asm-tree ← asm-commons.
- attribution: 273 of 443 jar files are declared by at least one module
  pom, 170 are transitive. Notable declared-but-candidate rows:
  azure-storage (hadoop-azure + hadoop-project), commons-csv
  (yarn-server-timelineservice + hadoop-project), jersey-media-json-
  jettison (ten modules + hadoop-project) — declared, shipped, and
  unreachable from Hadoop code.

## Closing the open cross-check item (netty-handler-ssl-ocsp)

The 2026-11-12 pruning record stated a byte-level cross-check found no
own-unit reference to any candidate, with the only hits being split
packages, but the netty-handler-ssl-ocsp hit had been left uninspected.
Inspected now:

- The hdfs/lib hit is netty-handler's OWN class
  `io/netty/handler/ssl/ocsp/OcspClientHandler.class`: the byte search
  for `io/netty/handler/ssl/ocsp/OcspClient` matched as a PREFIX of
  OcspClientHandler. Not a reference; the two jars share no class.
  The candidate verdict for netty-handler-ssl-ocsp stands.
- The codec/xml half of the sentence did not reproduce: netty-codec
  contains no byte hit for any of netty-codec-xml's 16 class names in
  hdfs/lib (and no class overlap). The scanner itself resolves full
  class names by exact set lookup, so the prefix trap cannot affect its
  verdicts — only the one-off byte search was exposed to it. The
  2026-11-12 record's cross-check sentence is now fully backed by
  inspection; its wording ("one class each in codec/xml and ssl/ocsp")
  overstates the codec/xml half and should be read with this record
  alongside it.

## Deltas to the earlier dry-run numbers

The 2026-11-12 first run reported 33 unreferenced jars; this run's
candidate set is 26 unique g:a (41 jar files). The difference is the
optional-feature section landed since then (commit 07dca62438a): jars
reached only from optional features moved out of the plain candidate
list into the used-optional section. The g:a sets agree where they
overlap.

## Review before commit (2026-11-13)

An independent review of the uncommitted change found and fixed:

- `pulled_in_by` joined a set, so multi-module lists came out in hash
  order (different on every run; visible in the first 3.5.0 TSV, e.g.
  reload4j). Now sorted; the suite has a two-module case that fails on
  7 of 10 hash seeds without the fix.
- The flag was `-t/--tsv-out` while the docstring and this record said
  `--tsv`. Now `-t/--tsv`.
- Verdict precedence differed from the text report: a keep-listed jar
  that is reached anyway was `kept` in the TSV but stale in the text
  report. The TSV now uses the text report's order (reached = used /
  used-optional; only unreached jars are no-class / kept / candidate),
  with a suite case for it. No 3.5.0 row changes.
- Small cleanups: keep file loaded once, a duplicated test assertion
  dropped.

The 3.5.0 run was repeated with the fixed code (41.5 s): the text
report is byte-identical to the first run's, the TSV's first six
columns are identical, and every count above holds.

## Files

- `dev-support/licenses/unused-jar-candidates.py` — extension
- `dev-support/licenses/test-unused-jar-candidates.py` — suite extension
- Evidence run outputs (scratch, not for commit):
  `.review/scratch/baseline-3.5.0/pruning-report-3.5.0.tsv` and
  `unused-jar-candidates-3.5.0.txt`

## Standing caveats

Unchanged and repeated here because they bound every number above: the
scan is informational only and never a gate; reflection, by-name
ServiceLoader and native loading are invisible to it; share/hadoop/*/lib
is also the user-application class path, so removing any jar is a
compatibility call for the project, and a pruning change still needs the
full test suite on a real build.
