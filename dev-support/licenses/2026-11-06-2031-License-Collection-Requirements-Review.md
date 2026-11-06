<!-- Licensed to the Apache Software Foundation (ASF) under one or more
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
# Automatic license collection requirements review, 2026-11-06 20:31

Reviewed `dev-support/licenses/License-Management.md` (v2, 34 requirements)
against commit `b61d19ff2f4e6386cdab20c0da8931d8af2ddf91` (`feat/LICENSES`):
the `licenses` Maven profile (`pom.xml:916-989`), the workflow
(`.github/workflows/licenses.yml`), the four scripts/properties files and
the 17-text store under `dev-support/licenses/`, and the hand-maintained
baselines `licenses/` (15 files), `licenses-binary/` (74 files),
`LICENSE-binary` and `NOTICE-binary`. Evidence beyond the code: the CI
artifact (`collected-licenses`) of run 42278633837 (the last successful full
run at review time; downloaded to `.review/scratch/run-42278633837/`), read-only
`gh run list/view` over all 15 workflow runs, and script experiments on
synthetic inputs in `.review/scratch/`. Nothing outside `.review/` was
changed; no build was run (AGENTS.md: builds need the owner's approval).

## Verdict

The collection core is real and works end to end in CI: a full-reactor
install (118 module installs observed in the run log) feeds a single
root-level aggregate that lists **411 dependencies** with resolved license
names, and 14 of the 17 local texts resolve. But the module's stated goal —
no regressions against the manual baseline (R25) — **fails today**: 33
dependencies tracked by `LICENSE-binary` do not appear in the generated
inventory (13 of them stale manual entries, ~20 real inventory gaps), and
two resolution bugs silently drop licenses from texts: multi-license lines
expose only their first license name, and nested-parenthesis license names
(the JMH GPL-with-Classpath-exception entries) are invisible even to
`--strict`. Four of the 17 "canonical" texts are HTML error pages, including
the two the v2 revision (R33) says the store was created to prevent. Until
those are fixed, the generated inventory cannot be the baseline of record.

Counts from the table below: **Met 8, Partly met 12, Not met 13, Not
checkable 1** (R8). "Reproduced" = demonstrated by running
`resolve-licenses.sh`/`normalize-licenses.sh` on inputs in
`.review/scratch/` or by extracting from the CI artifact; "from reading" =
argued from the reviewed files only.

## Requirements

| # | Requirement (short) | Status | Evidence |
|---|---|---|---|
| 1 | Dependency inventory, transitive, shipping modules | Partly met | Root aggregate lists 411 deps (`THIRD-PARTY.txt:2`), goal runs once at `hadoop-main` (run log `aggregate-add-third-party (default-cli) @ hadoop-main`), but coverage is the Maven graph only — not validated against the assembled distribution (R26), WAR contents (R27) or assembly-included jars |
| 2 | Scope filtering (no test/provided/build tooling) | Partly met | `pom.xml:931-933` excludedScopes test,provided; **reproduced**: `hsqldb` is test/provided scope in every consuming pom yet ships in the dist's `lib-examples` (`hadoop-mapreduce-dist.xml:188-193`) and so vanishes from the inventory |
| 3 | License resolution (POM first, curated overrides) | Met | `pom.xml:944` overrideUrl → `override-THIRD-PARTY.properties:20-25`; run log shows aliyun SDK entries overridden (present as Apache-2.0 in `THIRD-PARTY.txt` despite POMs declaring none) |
| 4 | Name normalization to canonical names | Partly met | `pom.xml:948-968` licenseMerges covers 40+ variants, but `MIT license` (lowercase, animal-sniffer) stays distinct from `MIT License` in `THIRD-PARTY.txt` (unmerged variant), and "ideally SPDX" is not done (prose names) |
| 5 | Local-first full texts for every detected license | Partly met | `resolve-licenses.sh:38-50` resolves locally, no network; but 4/17 texts are HTML junk (`texts/LICENSE-bouncycastle.txt:1`, `LICENSE-bsd.txt:1`, `LICENSE-cddl-gplv2-ce.txt:1`, `LICENSE-edl-1.0.txt:1`), and 2nd+ licenses on 56 multi-license lines get no text (reproduced, see F1) |
| 6 | Missing-license detection, configurable failure | Partly met | `--strict` exits 1 (reproduced: `exit=1` on synthetic missing license), `failOnMissing` at `pom.xml:938`; but the JMH GPL-CPE entries never appear in the missing list (reproduced, see F2) — missing detection has blind spots |
| 7 | Non-Maven assets (JS/native) in inventory | Not met | No manifest or curated config exists; `licenses/` still hand-maintained; README "Not covered (yet)" admits it |
| 8 | RAT header checks continue | Not checkable | Process requirement; RAT config unchanged (`pom.xml:607-627`), tooling does not touch it, but this review did not run RAT |
| 9 | Allowlist policy gating CI | Not met | No allowlist anywhere; `licenses.yml` has no gating step |
| 10 | Drift detection vs checked-in files | Not met | No CI comparison of `licenses/`, `licenses-binary/`, `texts/` against generated output |
| 11 | Precommit (Yetus) integration | Not met | No Yetus wiring; `dev-support/` precommit patch process untouched by this branch |
| 12 | THIRD-PARTY report per release | Partly met | `THIRD-PARTY.txt` is produced per run into `target/third-party/` (`pom.xml:936`), artifact uploaded (`licenses.yml:87-97`); but no per-release wiring and the shipped manifest `LICENSE-binary` is not generated |
| 13 | Texts wired into `hadoop-dist`/`hadoop-assemblies` | Not met | `hadoop-dist.xml:136-143` and `dist-layout-stitching:123-124` still copy the hand-maintained `licenses-binary/` and `LICENSE-binary`; no generated text reaches the tarball |
| 14 | NOTICE accuracy | Not met | `NOTICE-binary` manual; no automated attribution check exists |
| 15 | CI artifacts for review | Met | `licenses.yml:87-97` upload-artifact@v4, `if-no-files-found: warn`; artifact of run 42278633837 contains THIRD-PARTY.txt + 14 resolved texts |
| 16 | Reproducible, offline-deterministic | Partly met | Scripts sort and dedupe (`resolve-licenses.sh:50` `sort -u`); default path offline; run-to-run determinism of the Maven aggregate output not verified (one artifact inspected) |
| 17 | Single command regeneration | Partly met | README documents install + goal + script (3 steps, `README.md:25-44`); no wrapper script; README's duplicated second Usage block (`README.md:56-76`) contradicts the first |
| 18 | Performance / scoped runs | Met | Full run 18-21 min in CI (runs 42275620899, 42278843685); `-pl ... -am` documented (`README.md:38-42`) |
| 19 | Offline default; download reports failures | Partly met | Default path offline (download step `if: inputs.download`, skipped in run 42275620899 steps); the optional download's failure reporting (`normalize-licenses.sh`) copies whatever exists, no 403/error detection |
| 20 | Observed-variant merging; BSD 2≠3 | Partly met | Most observed variants merged (`pom.xml:952-968`) and BSD 2/3 kept separate; **reproduced**: `MIT license` and `Eclipse Public License v. 2.0` (eclipselink) remain unmerged distinct entries in `THIRD-PARTY.txt` |
| 21 | Curated overrides, versioned, reviewed | Met | `override-THIRD-PARTY.properties` in-repo, `overrideUrl` wired (`pom.xml:944`); note: entries are version-pinned (`com.aliyun--aliyun-java-sdk-core--4.5.10`) so a dependency bump silently loses the override |
| 22 | Optional deps that ship included | Met | `includeOptional=true` (`pom.xml:941`); `checker-qual:3.49.0` present in `THIRD-PARTY.txt` despite the guava exclusion (`hadoop-project/pom.xml:1916-1919`) |
| 23 | Build-tooling exclusion | Met | `excludedGroups` (`pom.xml:947`) drops maven/plexus/sisu; no build tooling in `THIRD-PARTY.txt` (checked: no `org.apache.maven`, `plexus` GAs) |
| 24 | `LICENSE-<name>.txt` convention | Met | `license-slugs.sh:21-50` shared mapping; `normalize-licenses.sh:36-43` renames to convention; resolved texts follow it (artifact listing) |
| 25 | **Parity gate** (no regressions vs manual) | Not met | **Reproduced**: 33 GAs in `LICENSE-binary` absent from `THIRD-PARTY.txt` (13 stale manual entries: `hamcrest-core`, `sshd-*`, `htrace-*`, `wro4j-maven-plugin`, `joni`, `hbase-*`...; ~20 real gaps: `paranamer`, `cedarsoftware:*`, `commons-digester`, `commons-validator`, `azure-storage`, `jaxb-impl`, `accessors-smart`, `opencensus-contrib-grpc-metrics`, `jsp-api`, `guice` (wrong groupId in manual), `hsqldb`, `asm`); 149 GAs generated but not manual (extras). No CI gate wired |
| 26 | Ground truth = assembled dist | Not met | No `-Pdist` run, no tarball validation anywhere |
| 27 | WAR-nested jars inventoried | Not met | No WAR unpacking; `solr-solrj`, `httpmime`, `jcl-over-slf4j`, `http2-*` appear in the inventory only via their Maven coordinates, not from WAR contents; nothing checks what a WAR actually embeds |
| 28 | Multi-license disambiguation policy | Not met | No curated policy; 56 lines carry 2-10 licenses each (`THIRD-PARTY.txt:379` jersey 10-license line) with no chosen license; javassist shows 3 (`:386`) |
| 29 | No-metadata curation, justified | Partly met | aliyun + aopalliance overridden with justifying comments (`override-THIRD-PARTY.properties:20-25`); `zookeeper-jute` needed none (POM carries Apache-2.0, `THIRD-PARTY.txt` zookeeper-jute 3.6.2 + 3.8.6); but no recorded policy for the class of cases |
| 30 | Entry format validation | Not met | Malformed `LICENSE-binary` entries confirmed: `:260` `com.google.code.gson:2.9.0` (groupId:version, no artifactId — real `com.google.code.gson:gson:2.9.0`), `:257-258` `com.google:guice` / `com.google:guice-servlet` (wrong groupId; generated has `com.google.inject:guice:5.1.0`), `:275` `com.jamesmurty.utils:java-xmlbuilder-1.2.jar` (version carrying `.jar`); no validator exists |
| 31 | Version consistency | Not met | Manual `failureaccess:1.0, 1.0.2` vs generated `1.0.1-1.0.3`; manual `guava:33.4.8-jre` vs generated also `33.4.0-jre`; no cross-check |
| 32 | Pruning of stale entries | Not met | Stale `LICENSE-binary` entries confirmed: `hamcrest-core` (test-only, appears only as exclusion comments), `sshd-core/common/sftp` (test scope in `hadoop-common/pom.xml`), `wro4j-maven-plugin` (build tool), `htrace-core/4`, `joni`, `hbase-*` (only as test/exclusions); no pruning tool |
| 33 | Local store seeded from authoritative sources | Partly met | 13/17 texts are real license texts (apache-2.0, mit, lgpl-2.1, cddl, epl-*, mpl-1.1, bsd-*, go, w3c, jquery, json, public-domain/CC0); **4 are HTML error pages** (`LICENSE-bouncycastle.txt` = bouncycastle.org homepage with cookie-banner scripts; `LICENSE-bsd.txt` = opensource page; `LICENSE-cddl-gplv2-ce.txt` = GitHub HTML; `LICENSE-edl-1.0.txt` = eclipse.org page with GTM scripts) — exactly the failure mode R33 cites as the store's reason |
| 34 | Full reactor, no skipped modules | Met | `licenses.yml:56-60` `mvn install` without `-pl`; 118 module installs in run 42278843685's log, none skipped (121 poms exist; the 3 non-installed are the root aggregator, `hadoop-coverage` (pom packaging, enforcer-only) and `hadoop-dist`/`hadoop-cloud-storage-dist` which are `-Pdist` tarball assemblies with no code — no jar of them exists to license), goal invoked once at `hadoop-main` |

## Serious findings

### F1 (reproduced) — `resolve-licenses.sh` reads only the first license of each line; 2nd+ licenses get no text and no missing report

`resolve-licenses.sh:50` greps `^\s+\([^()]+\)` per line, which matches the
first paren group only. The real inventory has 56 multi-license lines. In
the CI artifact, `licenses-resolved/` contains 14 texts and **no
`LICENSE-jquery.txt` or `LICENSE-w3c.txt`**, although 9 dependencies carry
`(jQuery license)` and 9 carry `(W3C license)` — always as 2nd+ license on
jersey lines (`THIRD-PARTY.txt:379`). Reproduction:

```
printf 'Lists of 2 third-party dependencies.\n     (CDDL + GPLv2 with classpath exception) (EPL 2.0) Jakarta Servlet (jakarta.servlet:jakarta.servlet-api:4.0.4 - https://x)\n' > .review/scratch/rtest/TP-multi.txt
bash dev-support/licenses/resolve-licenses.sh .review/scratch/rtest/TP-multi.txt dev-support/licenses/texts .review/scratch/rtest/out-multi
# -> Resolved 2 license text(s)   [cddl-gplv2-ce + epl-1.0 only; EPL 2.0 line invisible]
```

Worst instance: a dependency whose *first* license resolves is never
reported for its others even with `--strict` (the artifact's resolved set
demonstrates it: jersey lines' `(W3C license)` and `(jQuery license)`
produced no text and no MISSING line). Fix size: a loop over all leading
`(..)` groups before the GAV paren, ~15 lines.

### F2 (reproduced) — nested-parenthesis license names are silently dropped entirely (JMH GPL-CPE)

The same regex `[^()]+` cannot match `(GNU General Public License (GPL),
version 2, with the Classpath exception)` — the nested `(GPL)` breaks it.
The two JMH entries (`org.openjdk.jmh:jmh-core/-generator-annprocess`,
compile scope in `hadoop-tools/hadoop-benchmark/pom.xml:40-47`, shipped in
the tools dist) resolve **no text and produce no missing-list entry**: they
are invisible to both `failOnMissing` bookkeeping downstream and
`resolve-licenses.sh --strict`. Reproduction (from the artifact):

```
head -1 .review/scratch/run-42278633837/target/third-party/THIRD-PARTY.txt > .review/scratch/rtest/TP3-v2.txt
grep '(GPL), version 2' .review/scratch/run-42278633837/target/third-party/THIRD-PARTY.txt >> .review/scratch/rtest/TP3-v2.txt
bash dev-support/licenses/resolve-licenses.sh .review/scratch/rtest/TP3-v2.txt dev-support/licenses/texts .review/scratch/rtest/out4-v2
# -> "Resolved 0 license text(s)", exit 0: the two JMH lines produce neither a copy nor a MISSING entry
# (and --strict would pass the same way)
```

### F3 (reproduced) — 4 of 17 store texts are HTML error pages, the exact failure R33 says the store exists to prevent

`head` on each shows HTML doctypes: `LICENSE-bouncycastle.txt` is the
bouncycastle.org homepage (cookie-consent scripts, no license text),
`LICENSE-cddl-gplv2-ce.txt` (499 KB) a GitHub page, `LICENSE-edl-1.0.txt`
an eclipse.org page, `LICENSE-bsd.txt` (1592 lines) an HTML page. These
would ship verbatim into `target/licenses-resolved` in every CI run — the
CI artifact confirms `LICENSE-bouncycastle.txt` was "resolved". Fix: seed
from SPDX license-list-data (plain text) or the existing
`licenses-binary/LICENSE-bouncycastle.txt`, and add a `grep -q '<'`
HTML-junk check to `resolve-licenses.sh --strict`.

### F4 (reproduced) — the parity gate (R25) fails today: 33 manual GAs missing from the generated inventory

`comm` of G:A pairs (case-insensitive) between `LICENSE-binary` (277 GAs)
and `THIRD-PARTY.txt` (393 GAs): **33** manual entries absent from the
generated inventory, **149** generated entries absent from the manual
baseline. Of the 33: ~13 are stale manual entries (`hamcrest-core`,
`sshd-core/common/sftp` — test scope in `hadoop-common`, `wro4j-maven-plugin`,
`htrace-core/4`, `joni`, `hbase-*`, `azure-storage` superseded by
cosmosdb/data-lake...) and ~20 are real inventory gaps (`paranamer`,
`cedarsoftware:java-util/json-io`, `commons-digester`, `commons-validator`,
`azure-keyvault-core`, `jaxb-impl`, `accessors-smart`,
`opencensus-contrib-grpc-metrics`, `javax.servlet.jsp:jsp-api`, `guice` —
manual has wrong groupId `com.google:guice`, generated has
`com.google.inject:guice` — `hsqldb`, `asm`, `jcip-annotations`...). The
manual-vs-generated comparison has no CI gate; this review's script is in
`.review/scratch/rtest/parity.sh`.

### F5 — README's second "## Usage" section documents the retired v1 flow and contradicts the first

`README.md:56-76` still shows `aggregate-download-licenses` in the default
invocation and "Results land in target/third-party and target/licenses",
contradicting the v2 first block (`README.md:25-44`, downloads opt-in) and
R5/R19/R33. Anyone following it would download from the network by default.
Fix: delete the second Usage section (`README.md:56-76`, ~20 lines).

## Partly met

See the table — R1, R2, R4, R5, R6, R12, R16, R17, R19, R20, R29, R33.

## Documentation out of date

- `README.md:56-76` duplicated stale Usage block (F5).
- `README.md:103-108` "Known limitation: checker-qual ... does not appear in
  the hadoop-common subtree inventory" — **refuted by the CI artifact**:
  `checker-qual:3.49.0` is in `THIRD-PARTY.txt` (includeOptional + another
  dependency path carries it). The limitation note should be removed or
  re-verified per module.
- `License-Management.md` status table rows "R26–27 Open", "R30–32 Open",
  "R7, 9–14, 16 Open" — **confirmed accurate** by this review; row
  "R1–4, 15, 17–18 Implemented" is broadly right but hides R4/R20's
  unmerged variants (see table).
- `README.md:11-14` says the `licenses` profile wires
  `aggregate-download-licenses` as an execution — true (`pom.xml:978-984`)
  but the executions bind to the default lifecycle only via
  `process-sources`-style invocation; since CI invokes goals directly
  (`default-cli`), the bound execution only matters for
  `mvn -Plicenses <phase>` runs, which the README's own examples don't use.

## Gaps with no requirement or to-do item

- **Version drift of curated overrides**: `override-THIRD-PARTY.properties`
  pins versions (`com.aliyun--aliyun-java-sdk-core--4.5.10`); a dependency
  bump silently drops the override and reintroduces a no-license artifact.
  The plugin also accepts `groupId--artifactId` keys without version — a
  requirement should say which form is canonical and CI should fail on an
  override that matched nothing (the run log shows the plugin warns "has no
  name (but exist)" per aliyun entry every run — currently unactioned noise).
- **`LICENSE-binary` is also stale in the *other* direction**: 149 generated
  GAs are not in it (e.g. `aopalliance`, `flatbuffers-java`,
  `google-cloud-storage`, `guice` under its real groupId) — the manual
  process under-reports, which is the module's stated added value, but no
  requirement covers *generating* the replacement manifest.
- **Multi-version duplicates**: `THIRD-PARTY.txt` lists both
  `error_prone_annotations:2.30.0` and `:2.36.0`, `guava:33.4.0-jre` and
  `33.4.8-jre`, `zookeeper-jute:3.6.2` and `3.8.6` — inventory-vs-dist
  validation (R26) will need a dedup policy; not covered by any requirement.
- **CI noise**: 670 `[WARNING]` lines in run 42278843685's inventory step;
  nothing aggregates or gates on warnings.

## Open items

Confirmed still open (high confidence, from code + CI evidence):
- R25 parity gate — no gate, comparison fails today (F4).
- R26–R27 — no dist tarball or WAR validation exists anywhere on the branch.
- R9–R11, R13, R14 — no allowlist, drift check, Yetus wiring, dist wiring or
  NOTICE automation.
- The two in-progress runs (42278843685 on `feat/LICENSES`, 42278633837 on
  the old `LICENSES` branch name) both completed `success` by review time
  (21m32s / 17m54s); the branch rename did not change CI behavior.

## Recommended order

1. **Fix `resolve-licenses.sh` parsing (F1+F2) and add an HTML-junk check to
   `--strict` (F3)** — every later comparison and every shipped text
   depends on resolution being complete; today's outputs are silently
   partial. (~1 day: extract *every* leading `(...)` group per line with a
   paren-depth loop or small Python parser, so multi-license lines yield all
   names and nested-paren names like the JMH GPL-CPE line are captured;
   `grep -qi '<!doctype\|<html'` guard on each resolved text.)
   Advances R5, R6, R33, and makes R16's determinism meaningful.
2. **Re-seed the 4 broken texts from authoritative sources** (SPDX
   license-list-data or the existing `licenses-binary/` files where
   trustworthy — `LICENSE-bouncycastle.txt` already exists there as a real
   text). Reviewable in a PR today. Advances R33 to Met; unblocks R13.
3. **Wire the parity comparison as a CI gate (R25)** — the script exists
   (this review's `parity.sh`, ~30 lines, belongs in
   `dev-support/licenses/`): compare `THIRD-PARTY.txt` GAs against
   `LICENSE-binary` GAs case-insensitively, print both directions, and fail
   only on *manual-but-not-generated* after the stale entries are curated.
   This is the module's acceptance test; it should run in `licenses.yml`.
4. **Curate the manual baseline split (R30/R31/R32)** — one-time cleanup of
   `LICENSE-binary`: fix malformed entries (`com.google.code.gson:2.9.0`,
   `com.google:guice` → `com.google.inject:guice`, strip `.jar` from
   versions), delete the 13 confirmed-stale entries, record version policy.
   After this, step 3's gate can be strict both ways.
5. **Add the missing ~20 dependencies' licenses** (paranamer, cedarsoftware,
   commons-digester/validator, jaxb-impl, accessors-smart, opencensus-grpc,
   jsp-api, hsqldb, asm, jcip, guice under real coordinates) — most resolve
   from POM metadata once inventory scope is right (R2: assemblies include
   test-scope jars in `lib-examples`; decide policy: inventory =
   Maven-compile+runtime graph *plus* assembly-included jars).
6. **`-Pdist` ground-truth validation (R26/R27)** — build the binary
   tarball in CI (or nightly), list its jars (`unzip -l` the WARs too, per
   pjfanning), diff against `THIRD-PARTY.txt`, fail on unexplained jars.
   This closes the R1/R2 scope-vs-reality hole for good and enables R31.
7. **Multi-license policy (R28) + override hygiene (R21/R29)** — decide per
   ambiguous artifact (jersey = CDDL+GPLv2-CE chosen? javassist = Apache?),
   curate into `override-THIRD-PARTY.properties` with justification
   comments, and make version-unpinned (`groupId--artifactId`) keys the
   canonical form so bumps don't drop overrides.
8. **Drift + allowlist + Yetus (R9, R10, R11)** — now that output is
   trustworthy: allowlist of license names failing CI on new
   non-approved licenses; drift check of `texts/` store; precommit
   integration so the checks run in the Yetus pipeline alongside RAT.
9. **Distribution wiring (R12, R13, R14)** — generate `LICENSE-binary`'s
   replacement and `THIRD-PARTY` manifest from the inventory at release
   time, copy resolved texts into `hadoop-dist` assembly replacing
   `dist-layout-stitching:123-124`'s manual `licenses-binary/` copy,
   derive NOTICE-binary attribution sections. This is the final "manual
   process retired" state; do it last, after the gate proves the inventory.
   Non-Maven assets (R7) can stay manual for now with a `licenses-manifest`
   listing the JS/native files so RAT + review cover them.

Pending decisions to make along the way (recommendation in parentheses):
- Inventory scope policy for assembly-only jars like `hsqldb` (include —
  they ship, via a small assembly-includes manifest).
- Canonical override key form (unpinned `g--a`, with a CI check that every
  key matched something).
- Whether `MIT license`-vs-`MIT License` style variants get merged in
  `licenseMerges` (yes — add the lowercase variants observed:
  `MIT license`, `Eclipse Public License v. 2.0`).
- Whether the extras direction of the parity gate (149 GAs the manual
  baseline misses) blocks or just warns (warn until step 9 replaces the
  manual baseline).

## Earlier review

None — this is the first requirements review of the document.

## What this review did not cover

- No Maven build or test was run (AGENTS.md policy); all inventory evidence
  comes from the CI artifact of run 42278633837 and the read-only run logs.
  The artifact is one run — run-to-run determinism (R16) was not verified.
- `texts/` spot-read 4-5 files fully; the 13 clean texts were verified
  non-empty and non-HTML, not read line by line. `licenses/` and
  `licenses-binary/` were listed and their names/manifests compared, not
  their contents.
- R8 (RAT) not executed; classification "Not checkable" from reading the
  unchanged config only.
- The 33-entry and 149-entry parity lists were produced by shell
  extraction with case-insensitive GA matching; ~3 borderline entries
  (e.g. `com.google.j2objc` version-only differences) were eyeballed, not
  individually resolved.
- `normalize-licenses.sh` tested only on synthetic inputs (4 files), not
  against a real plugin download directory (would require the download
  goal and network).
