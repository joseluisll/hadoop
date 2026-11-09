<!--
   Licensed to the Apache Software Foundation (ASF) under one or more
   contributor license agreements.  See the NOTICE file distributed with
   this work for additional information regarding copyright ownership.
   The ASF licenses this file to you under the Apache License, Version 2.0
   (the "License"); you may not use this file except in compliance with
   the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.-->
# R7 stage C: archive-side asset gate, 2026-11-09 ~02:30

Stage C of requirement 7 is the archive twin of the stage B source-tree
gate: `check-archive-assets.py` enumerates every non-jar asset the
distribution ships, both as plain archive files and embedded in jars or
WARs. It then checks that population against `manifest-assets.txt` and
the new `archive-asset-allowlist`. The gate fails closed. It runs in
`licenses-dist.yml` for the main `hadoop-<version>` archive, which is
now built with `-Pyarn-ui` (see "The CI archive was not
release-shaped" below).

## Decisions (the three design forks)

1. **Jar-embedded coverage is derived, not curated.** The gate scans
   every jar and WAR for asset entries. A manifest entry covers an asset
   when its path components (after stripping `src/main[/resources]`)
   appear as a contiguous subsequence of the asset's path. Source-path
   entries therefore cover loose files
   (`share/hadoop/hdfs/webapps/static/...`) and embedded entries
   (`webapps/static/...`) alike, without a jar-to-module map. Entries
   under Java package roots (`org/`, `com/`, `javax/`, `java/`,
   `META-INF/`) are the jar's own internals and are licensed jar-side.
   The accepted residual risk is a third-party asset bundled under a
   package path.
2. **Curated, self-cleaning allowlist.** `archive-asset-allowlist`
   exempts Hadoop-authored UI code, the dist-built `.gz` twins, and
   third-party jars' self-description pages (about/license/readme
   html). A row that matches no shipped asset fails the gate, the same
   way `assembly-includes` works.
3. **Content probes for package-style (npm) entries.** Each entry needs
   archive evidence for its pinned version. The evidence is checked in
   order, most anchored first:
   1. a shipped `vendor|node_modules/<name>/package.json` or
      `bower.json` at the package root whose `version` equals the pin;
   2. a banner or lockfile-style string (`name@version`,
      `name vX.Y.Z`, ...) in a shipped text asset;
   3. when the package's installed tree ships but carries no version
      (a lone font file), an exact pin (no range) in a source-tree
      `package.json`.

   A miss names the version the shipped manifests do carry, so the
   curation fix is in the message. A package-style entry also covers
   its own installed tree (`vendor/<name>/**`, `node_modules/<name>/**`),
   so an npm tree copied into a WAR needs no path-style entry, which
   the source tree could not resolve anyway.

## What the first real-data run found (archive of run 42374519973-full)

- **Shipped but unlisted, a real LICENSE-binary gap.** The YARN
  application-catalog WAR ships an npm-installed `vendor/` tree with
  jquery 3.3.1, angular 1.6.10, angular-route 1.6.10 and bootstrap 3.3.7
  (MIT), plus the roboto-fontface 0.10.0 font (Apache-2.0). None of
  these was in `LICENSE-binary`. The versions come from the WAR's own
  package manifests. roboto-fontface ships only `Roboto-Regular.woff`,
  so its version is the exact pin in the catalog's `package.json`. All
  five are now in `manifest-assets.txt`, and `LICENSE-binary` was
  regenerated from the artifacts of dist run 42539836743. The diff is
  exactly those five lines. The run's CI-generated file was
  byte-identical to the committed one before the change.
- **Hadoop-authored, allowlisted:** `webapps/static/dt-sorting/natural.js`
  (ASF header) and `webapps/static/test.css` (hadoop-common's test jar).
- **Heuristic false positives, fixed in the gate:** html-named `.class`
  files (Guava's `com/google/common/html/`) and the terasort PNGs under
  `org/apache/` are package internals.

Result: 0 uncovered, 0 absent, 0 stale allowlist rows; 5 of 98
package-style entries probe ok.

## The CI archive was not release-shaped

The remaining 93 probe misses are every Ember YARN UI entry
(`ember v2.2.0`, `jquery v2.1.4`, ...) and every Capacity Scheduler UI
entry (`react 19.1.0`, `radix-ui/*`, ...). Neither UI is in the archive.
Both are packaged as WARs only under `-Pyarn-ui`
(`yarn.ui.packaging=war`). `licenses-dist.yml` builds `-Pdist,native`,
while `dev-support/bin/create-release` builds `-Pdist,src,yarn-ui`. The
release tarball ships both UIs, and the CI ground truth has neither.
This affects the jar gates too (R26/R36/R40 never see what those WARs
embed), not only the asset probe.

Fix: the dist build now runs `-Pdist,native,yarn-ui`, so the ground
truth matches the release. The asset gate runs after the jar gates for
the main `hadoop-<version>` archive. The cloud-storage dist ships SDK
jars and no web assets, so the gate skips it. `archive-assets.tsv` and
`assets.log` are uploaded with the ground-truth artifact. The cost is
frontend-maven-plugin's node/yarn/bower downloads and the two UI builds
on every dist run.

Expected on the first yarn-ui run: the npm probes list the Ember and
Capacity Scheduler entries that are really stale, and the R40 drift gate
catches whatever jars the UI WARs embed. That output is the curation
worklist.

## Verification

- `check-archive-assets.py` on the untarred archive of run
  42374519973-full: exit 1 with only the 93 UI-entry probe misses listed
  above. Before this change: 167 uncovered and 93 misses.
- Self-check of the package path helpers (scoped names, nested
  `node_modules`, a manifest that is not at the package root).
- `check-asset-manifest.py` (stage B, R48, R53): passed.
- `generate-archive-manifest.py` on run 42539836743's artifacts: the
  diff against the committed `LICENSE-binary` is the five new lines.
