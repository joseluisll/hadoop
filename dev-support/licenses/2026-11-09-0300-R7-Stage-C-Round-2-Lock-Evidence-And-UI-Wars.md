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
# R7 stage C round 2: lock-file evidence and the UI WARs, 2026-11-09 ~03:00

Closes the open item the first yarn-ui-shaped run left (record:
`2026-11-09-0230-R7-Stage-C-Archive-Asset-Gate.md`): archive run
42543652715 on 5dce2dabd53 built the release-shaped dist
(`-Pdist,native,yarn-ui`, as `create-release`) and failed the new asset
gate on the shape change it itself introduced.

## What the red run found

1. **~90 uncovered files** — the two UI WARs the `-Pyarn-ui` build now
   ships, unpacked as `share/hadoop/yarn/webapps/ui2` (Ember YARN UI) and
   `share/hadoop/yarn/webapps/scheduler-ui` (react Capacity Scheduler
   UI): hashed bundle chunks, sourcemaps, compiled css, bundled
   fonts/images, ember/vite build output, Hadoop-authored support files
   (hadoop_logo.png, spinner.gif, configs.env, crossdomain.xml, msw mock
   fixtures), and WAR packaging metadata.
2. **93 probe misses** — the ember and react npm package entries DO ship
   now, but inside minified bundles that carry no `name@version` string:
   content probing cannot see them (the false-positive risk accepted when
   probes were chosen, now with evidence in hand).
3. **One stale pin** — `bootstrap v3.3.6`: the yarn-ui bower pin is 3.4.1
   (the catalog WAR's vendor bootstrap 3.3.7 entry, landed with round 1,
   is separate and correct).
4. **A 15-entry jar worklist** (warning-level, from the new shape):
   kerby ×8 (minus kerb-core, which the catalog WAR embeds), jmh ×2,
   jsr311-api, kfs, opentelemetry-common, jersey-container-jdk-http —
   inventory entries that ship nowhere under `-Pyarn-ui`. Curation
   direction (root-pom `excludedArtifacts` vs a fork-side inventory
   exception) is an open design fork, tracked in work state.

## Round 2: lock files as version evidence (gate tier d)

The dist build installs each UI module's dependencies from its committed
lock file before bundling, so the lock IS what ships — archive-equivalent
evidence for packages whose bundle is minified. `check-archive-assets.py`
now resolves package-style entries in fallback order: (a) shipped
vendor/node_modules package manifests, (b) content probe, (c) exact
source-tree pins, **(d) a pin in the shipping module's committed lock
file (`package-lock.json`, `yarn.lock`, `bower.json`) while the module's
built UI tree ships in the archive** — the module→tree binding is the
curated, self-cleaning `ui-archive-trees` map. bower has no lock file, so
a bower range whose floor equals the pin is accepted as the strongest
available evidence. Entries whose content is compiled into a listed jar
with no probeable string (native leveldb inside leveldbjni-all) are
exempted via `archive-asset-pin-exceptions` — self-cleaning in both
directions (a row whose manifest entry is gone fails; an entry needing an
exemption without one fails).

## Curation: the pins were stale, not the packages

Diffing the manifest's 97 package entries against the modules' committed
locks (`hadoop-yarn-ui` yarn.lock + bower.json, `hadoop-yarn-capacity-
scheduler-ui` package-lock.json, catalog-webapp package.json) found the
hand-maintained-era versions had drifted wholesale:

- 47 realignments to lock evidence — among them ember 2.2.0 → 2.8.0,
  jquery 2.1.4 → 3.6.0 (yarn-ui bower; the catalog's separate jquery
  3.3.1 entry stays), jquery-ui 1.11.4 → 1.12.1, em-table 0.1.6 → 0.12.0,
  em-helpers 0.5.13 → 0.8.0, bootstrap v3.3.6 → 3.4.1, react 19.1.0 →
  19.2.4, the fourteen radix-ui components (+1 patch each), react-router
  7.5.3 → 7.13.0, tailwindcss 4.1.4 → 4.1.18, isbot 5.1.27 → 5.1.34.
- `ember-cli-ic-ajax v0.2.1` pruned — pinned nowhere in bower.json,
  package.json or yarn.lock.
- `datatables v1.11.5` renamed to its real npm name `datatables.net
  1.11.5` (bower-exact pin; the shipped `dt-1.11.5` tree in
  hadoop-yarn-common).
- `LICENSE-binary` regenerated with
  `generate-archive-manifest.py` against run 42543652715's two archive
  TSVs + inventory: the diff against the committed file contains EXACTLY
  the curation set above and nothing else.
- Allowlist: the two UI trees' bundle output exempted as compiled build
  artifacts of the lock-pinned dependency sets (a dependency change is
  caught by the lock evidence on the package entries; a UI removal makes
  the rows stale and fails the gate until pruned), plus the Hadoop-
  authored support files and WAR packaging metadata.

Observation recorded for the next review: build-tooling packages (vite,
vitest, eslint, prettier, typescript, ember-cli-*, broccoli-*) stay
listed per the hand-maintained practice although they do not ship as
files — LICENSE-binary over-lists them by that measure.

## Validation

- `test-check-archive-assets.py` (new): 10 synthetic cases — every
  evidence tier (shipped manifest, content probe, source pin, yarn.lock
  pin, bower range floor, package-lock nested positions, pin exception)
  and every failure class (uncovered, listed-but-absent, stale allowlist
  row, stale ui-archive-trees row at parse and at enumeration, version
  drift with the shipped-versions hint, stale pin exception, zero-jar /
  zero-asset / missing-input fail-closed guards).
- The gate passes on a reconstruction of run 42543652715's asset
  population (173 file-level + 427 jar-embedded paths from the run's
  `archive-assets.tsv`, the catalog WAR's real vendor bytes) — 97/97
  package entries evidenced.
- The per-push stage-B gates (`check-asset-manifest.py`: R7 stage B,
  R48, R53) pass against the edited manifest.
