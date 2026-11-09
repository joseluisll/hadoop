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
# License management requirements review, 2026-11-08 23:36

Reviewed `dev-support/licenses/License-Management.md` (v2.2, 40
requirements) against commit `d4efb02b836c15bf60b98b8756c870117f94e6fb`
(`feat/LICENSES`, fork `joseluisll/hadoop`): both workflows, the `licenses`
profile of the root `pom.xml`, every script and curation file under
`dev-support/licenses/`, the 18-text store, `LICENSE-binary`, `LICENSE.txt`,
`NOTICE-binary`, the dist/cloud assembly wiring, `create-release`, and the
build-env changes the branch carries. Evidence beyond the code: read-only
`gh run list/view` on the fork, the generator's self-check, and experiments on
synthetic inputs. Nothing in the repository was changed; no Maven build, Docker
build or test suite was run (AGENTS.md).

**Who did what.** A Hermes worker (`glm-5.3-flash` via `melious`) read every
file on the checklist, settled a first verdict for each requirement with
file:line evidence and wrote the experiments. It stopped on an exhausted
provider balance before writing this report. The reviewing session then
re-checked the worker's evidence, re-ran its experiments, ran its own (the
exclusion-pattern and single-line parser tests, CI metadata, the earlier-review
recheck), changed four verdicts (R10, R35, R38 and R16, see the table), added
findings F1–F3 and F6, and wrote the report. Every verdict below rests on
evidence produced in this review.

## Verdict

The collection core and the archive-derived manifest work as specified: the
generated `LICENSE-binary` is the artifact of record, it is gated in both
directions, and every tool tested fails closed on bad input. The weaknesses
are in *when* the gates run, not in what they check. A dependency change made
outside the archive workflow's path filter is never checked per push (F1); the
weekly safety net has never fired (F2); and the workflows only work on the
fork branch (F3). Three requirements (R9, R11, R13) are not started.

| Status | Count | Requirements |
|---|---|---|
| Met | 29 | all others |
| Partly met | 8 | R7, R10, R12, R14, R29, R31, R35, R38 |
| Not met | 3 | R9, R11, R13 |
| Not checkable | 0 | — |
| **Total** | **40** | |

**Reproduced** means shown by running the project's own code (or the exact
pattern it uses) on synthetic inputs in `.review/scratch/`, with the command
given. **From reading** means argued from the code at the cited lines.

## Requirements

| Req | Status | Evidence |
|---|---|---|
| 1 | Met | `pom.xml:929,931` includeTransitive, compile+runtime; full reactor `licenses.yml:56-61`, goal `:69-74` |
| 2 | Met | `pom.xml:933` excludes test,provided; curated `excludedArtifacts` `:964` for compile-scope test tooling. Hole: substring matching (F4) |
| 3 | Met | `pom.xml:944` overrideUrl → `override-THIRD-PARTY.properties` (4 entries) |
| 4 | Met | `pom.xml:969-991` licenseMerges; earlier `MIT license` / `Eclipse Public License v. 2.0` variants now merged (`:970`, `:981`) |
| 5 | Met | 18 store texts, none HTML (`grep -l -i '<!doctype\|<html' texts/*` → none); resolution offline; download only on the dispatch input `licenses.yml:31-34,172-179` |
| 6 | Met | **Reproduced**: `bash .review/scratch/exp-resolve.sh` → `--strict` lists all four missing texts (BSD-2, GPLv2-CE, Public Domain, Missing License), exit 1; non-strict exit 0; an HTML text is rejected, exit 1. `failOnMissing` `pom.xml:938` |
| 7 | Partly met | Stage B: `check-asset-manifest.py` per push (`licenses.yml:167-169`). **Reproduced**: `bash .review/scratch/exp-asset.sh` → real manifest exit 0; bogus path, malformed line and empty file each exit 1. But 91 of 116 entries are package-style (`PACKAGE_STYLE`, `check-asset-manifest.py:51`) and validated by nothing until stage C |
| 8 | Met | RAT config untouched (`pom.xml:607-632`); tooling complements it |
| 9 | Not met | No allowlist in the code; only `README.md:183` mentions it |
| 10 | Partly met | LICENSE-binary drift gate per push (`licenses.yml:110-161`) and in the dist run (`licenses-dist.yml:200-217`), fail-closed on a missing run or artifact (`:146-156`). But R10 names `licenses/`, `licenses-binary/`, NOTICE and `texts/` too, and none of those is drift-checked (F6); and it is blind to dependency changes outside the dist path filter (F1) |
| 11 | Not met | No Yetus wiring; `dev-support/bin/test-patch` and `yetus-wrapper` untouched by the branch |
| 12 | Partly met | `THIRD-PARTY.txt` produced and uploaded per CI run (`licenses.yml:69-74,181-190`; dist run too), but not per release: `create-release` has no license step |
| 13 | Not met | `dist-layout-stitching:120-125` and `hadoop-dist.xml:134-146` still ship the hand-kept `licenses-binary/`; `texts/` is not wired |
| 14 | Partly met | `NOTICE-binary` carries attributions but is hand-curated, with no check; the cloud dist reuses the main file |
| 15 | Met | `upload-artifact` in both workflows (`licenses.yml:183`, `licenses-dist.yml:221`) |
| 16 | Met | Generator sorts and is deterministic (self-check: `python3 -I dev-support/licenses/test-generate-archive-manifest.py` → `11 tests passed`); the dist R40 gate regenerates from fresh archives and diffs: green on 71073d88145 (run 42519178850), so regeneration reproduces the committed file. Default path offline. The status table still lists 16 as open |
| 17 | Met | `README.md:32-42`: one `mvn install`, one goal, one script |
| 18 | Met | `-pl` scoping documented (`README.md:44-50`); collect runs take 9–12 min (42528393491: 22:04→22:13; 42519178640: 20:15→20:27) |
| 19 | Met | Download default false (`licenses.yml:31-34`); missing texts reported, never silently dropped (R6 experiment) |
| 20 | Met | BSD 2-/3-clause kept separate (`pom.xml:971,975`); observed variants merged |
| 21 | Met | Versioned override file. From reading: entries are version-pinned, so a dependency bump drops its override; `failOnMissing` then fails loudly, not silently |
| 22 | Met | `includeOptional` `pom.xml:941`; checker-qual in `LICENSE-binary` (MIT section) |
| 23 | Met | `excludedGroups` `pom.xml:949` |
| 24 | Met | `license-slugs.sh`, `normalize-licenses.sh`; store follows `LICENSE-<slug>.txt` |
| 25 | Met | Retired per its own transitional clause (`check-licenses-parity.sh` gone: `git ls-files \| grep -c check-licenses-parity` → 0). Its replacement leaves a gap (F1) |
| 26 | Met | Archive vs inventory, `check-archive-licenses.sh:246-259`; validated by the 2026-11-07 ground-truth runs (records) |
| 27 | Met | WAR-nested jars walked, `enumerate-archive-jars.py:190-202` |
| 28 | Met | `Multi-License-Policy.md` applied in code, `generate-archive-manifest.py:109-158` |
| 29 | Partly met | Override mechanism exists; no recorded per-artifact justification for no-metadata cases (e.g. zookeeper-jute) |
| 30 | Met | Manifest generated from parsed TSV rows; malformed or partial rows exit 2 (`generate-archive-manifest.py:205-215`); self-check `test_unmapped_partial_row` |
| 31 | Partly met | R31 check is a warning only and one-direction (`check-archive-licenses.sh:283-300`); no WAR-vs-standalone version divergence flag |
| 32 | Met | Generated manifest lists only enumerated jars, so nothing stale survives by construction; earlier prunes recorded |
| 33 | Met | 18 plain-text licenses (first 15 lines read, HTML grep empty) |
| 34 | Met | `mvn install` without `-pl`, `licenses.yml:56-61` |
| 35 | Partly met | Separate workflow with dispatch and path trigger (`licenses-dist.yml:32-48`), but the weekly `cron` (`:47`) has never fired: GitHub runs schedules from the default branch only, and `git show origin/trunk:.github/workflows/licenses-dist.yml` fails (absent on trunk) (F2) |
| 36 | Met | pom.properties first, then manifest, then filename (`enumerate-archive-jars.py:149-173`); unmapped/partial rows fail (`check-archive-licenses.sh:224-233`) |
| 37 | Met | `shaded-jars` mapping; generator merges embedded coordinates (`generate-archive-manifest.py:317-321`) |
| 38 | Partly met | Gate fail-closed (`check-archive-licenses.sh:237-242`; missing LICENSE-binary fails, `licenses-dist.yml:183-186`). But R38 "applies per release, to the exact archive being distributed": it gates CI-built archives, and `create-release` does not run it on the release manager's tarballs |
| 39 | Met | Exclusions checked against the archive (`check-archive-licenses.sh:201-219`); justifications in README and records. Same substring hole as R2 (F4), caught only on a dist run |
| 40 | Met | Committed `LICENSE-binary` is generator output, drift-gated in both workflows |

## Serious findings

### F1 (from reading) — a dependency change outside the dist path filter gets no license check per push

`licenses-dist.yml:33-44` runs on push only when its paths change, and the only
pom in the list is the root `pom.xml`. Dependency versions live in
`hadoop-project/pom.xml` (290 `<version>` elements) and in each module's pom,
none of them in the filter. For such a commit, the per-push R10 gate
(`licenses.yml:110-161`) finds no same-commit archive run and compares the
committed `LICENSE-binary` with the *previous* archive run's manifest
(`:144-160`). The two match, because neither the file nor the baseline changed,
so the gate passes. Nothing in `licenses.yml` compares the fresh
`THIRD-PARTY.txt` with `LICENSE-binary`
(`grep -n 'generate-archive-manifest\|check-archive' licenses.yml` → nothing):
that per-push comparison went away with R25. The comment at `licenses.yml:106-109`
states the assumption this breaks: "its paths did not hit the dist workflow's
filter, so LICENSE-binary and every other manifest input are unchanged".

Effect: adding or bumping a shipped dependency passes CI. It is caught only on
the next archive run, and the scheduled one never fires (F2).

Fix, small: add `'**/pom.xml'` and `hadoop-assemblies/**` to the dist path
filter (cost: one ~38-minute archive run per dependency change), or, cheaper per
push, run the generator against the last archive run's TSVs plus the fresh
`THIRD-PARTY.txt` and fail on a new or changed GAV.

### F2 (from reading) — the weekly archive run has never fired, and the baseline artifact expires

GitHub runs `schedule` triggers from the default branch only, and the workflow
is not on trunk (`git show origin/trunk:.github/workflows/licenses-dist.yml` →
`fatal: ... exists on disk, but not in 'origin/trunk'`). Every archive run so far
came from a push or a dispatch. Separately, `upload-artifact` sets no
`retention-days` (`licenses-dist.yml:221`), so the repository default (90 days)
applies. After that the per-push gate's `gh run download` (`licenses.yml:152`)
fails and every push goes red until someone dispatches the archive run. That is
fail-closed, which is correct, but it surprises whoever pushes next. On a fresh
repository the gate also fails until a first archive run succeeds
(`licenses.yml:146-148`).

Fix, small: on the fork, set the fork's default branch, or rely on dispatch
and say so. Upstream, the workflow on trunk makes the cron real; set
`retention-days` above the schedule period and print the dispatch command in
the R10 failure message.

### F3 (from reading) — the workflows only work on the fork branch

Both workflows trigger on `push` to `feat/LICENSES` only (`licenses.yml:25-29`,
`licenses-dist.yml:33-35`), with no `pull_request` trigger, so no Hadoop PR
would be checked. The R10 gate would also break as written once moved:

- It keys runs by `GITHUB_REF_NAME` (`licenses.yml:122`), which on a
  `pull_request` run is `<n>/merge`, a branch no archive run has.
- It looks for the last success among the 100 newest successful runs of all
  branches, then filters by branch (`:144-145`). On apache/hadoop, other branches
  and PRs can push the branch's last success out of that page; the result is
  then empty and the gate fails (`:146-148`).
- `licenses-dist.yml:55` needs `packages: write` to push the GHCR image cache.
  `GITHUB_TOKEN` is read-only on PRs from forks, and whether ASF infrastructure
  allows GHCR publishing on apache/hadoop is not established.

Fix, medium: add `pull_request` and trunk triggers; key the baseline lookup to
the PR's base branch (or a trunk-only archive run) and query it with
`branch=` and `status=success` server-side; make the image cache optional
(pull-only on PRs).

### F4 (reproduced) — `excludedArtifacts` matches substrings, with a duplicated alternative

The pattern (`pom.xml:964`) is matched unanchored, both by the plugin (README
says so) and by the R39 gate (`[[ "$artifact" =~ $exclude_pattern ]]`,
`check-archive-licenses.sh:205`). Reproduced with the gate's own extraction and
match:

```bash
pat="$(awk '/<excludedArtifacts>/ { sub(/.*<excludedArtifacts>/, ""); sub(/<\/excludedArtifacts>.*/, ""); print; exit }' pom.xml)"
for a in junit-jupiter-api my-junit-extras java-hamcrest xbyte-buddy-agent; do [[ $a =~ $pat ]] && echo "MATCH $a"; done
# MATCH junit-jupiter-api / MATCH my-junit-extras / MATCH java-hamcrest / MATCH xbyte-buddy-agent
```

A new shipped dependency whose name merely contains `junit-`, `hamcrest` or
`byte-buddy` is dropped from the graph inventory, and the only check that
would catch it, R39 in the archive run, depends on F1/F2 being fixed. No artifact
in today's `LICENSE-binary` matches, so there is no live leak. `junit-.*` appears
twice. Fix, small: anchor each alternative (`^(...)$` in the gate; `\b` or
explicit full names for the plugin) and drop the duplicate.

### F5 (reproduced) — the source-release `LICENSE.txt` names a path that does not exist, and misses one that ships

`LICENSE.txt:219` lists
`hadoop-common-project/hadoop-common/src/main/native/src/org/apache/hadoop/io/compress/lz4/{lz4.h,lz4.c,lz4hc.h,lz4hc.c}`:
`ls` of that directory → `No such file or directory`. The bundled
`hadoop-mapreduce-client-nativetask/src/main/native/lz4/lz4.{c,h}` (BSD-2) is not
listed. The binary-side asset manifest got this fix (2026-11-08 R7 record); the
source-side file did not, and no tool reads `LICENSE.txt`
(`check-asset-manifest.py` reads only `manifest-assets.txt`). The source tarball
is an official ASF release too, so this is a compliance error today. Fix, small
(two lines); keeping it right needs a gate (R48 below).

### F6 (from reading) — R10 promises drift detection for four inputs the gates do not check

R10 names `licenses/`, `licenses-binary/`, NOTICE and the `texts/` store. Only
`LICENSE-binary` is compared. `licenses-binary/` is what the tarball actually
ships (`dist-layout-stitching:120-125`), and no check ties it to the licenses
the generated manifest names. Fix: either narrow R10's text to what is gated, or
gate `licenses-binary/` against the manifest's license set (a per-push set
comparison).

## Partly met

| Req | Gap |
|---|---|
| 7 | 91 of 116 asset entries (package-style) are validated by nothing until stage C |
| 10 | Only `LICENSE-binary` is drift-checked (F6); blind to pom changes outside the path filter (F1) |
| 12 | THIRD-PARTY is per CI run, not per release; `create-release` has no license step |
| 14 | NOTICE-binary hand-curated, unchecked; the cloud dist shares it without its own review |
| 29 | No recorded per-artifact justification for no-metadata artifacts |
| 31 | Version check is a warning, one direction only; no WAR-vs-standalone divergence flag |
| 35 | The schedule never fires (F2) |
| 38 | Release tarballs built by the release manager are not gated |

## Documentation out of date

- Status table, R16 "Open": the R40 gate's green regeneration (run 42519178850)
  and the generator self-check show it met.
- Status table, R10 "Implemented": true for `LICENSE-binary` only (F6).
- Status table, R35–38 and README "weekly": the schedule has never run (F2).
- Status table, R39 "archive confirmation starts with the first dist run":
  the dist runs of 2026-11-07/08 have happened; the row should say what they
  confirmed.
- `licenses.yml:106-109` comment: "every other manifest input [is] unchanged"
  when the dist filter is not hit — false for module poms (F1).

## Gaps with no requirement or to-do item

- Operation on upstream trunk and pull requests, and a baseline lookup that
  scales (F3).
- Dependency-change coverage between archive runs (F1).
- Bootstrap and expiry of the baseline artifact (F2).
- Source-release `LICENSE.txt` / `licenses/` accuracy (F5). R7 covers the binary
  side only.
- Self-tests of the gates: only `test-generate-archive-manifest.py` exists, and
  CI runs none (`grep -n test-generate .github/workflows/licenses*.yml` → none).
  `check-archive-licenses.sh`, `enumerate-archive-jars.py`,
  `check-asset-manifest.py` and `resolve-licenses.sh` have no regression tests,
  though this review's scratch experiments show they are easy to write.
- Release-manager workflow: nothing in `create-release` or the HowToRelease
  steps runs the generator or gates on the release tarballs (R12/R38).
- Contributor workflow when the drift gate fails: regeneration needs a
  ~38-minute Docker dist build, and the dist run's generated manifest is an
  artifact a contributor must download and commit by hand.
- ASF infrastructure fit: the GHCR cache and `packages: write` (F3).
- Branch scope: the branch carries build-environment changes (five Dockerfiles,
  `download-with-retry.sh`, protobuf retry, googletest pre-seed in libhdfspp
  `CMakeLists.txt:116-141`) that are not license tooling and need their own
  JIRA upstream.

## Proposed future requirements

Priority **must** = needed before proposing this to Apache Hadoop as an
automatic process; **later** = after adoption.

| Id | Requirement | Rationale | Priority |
|---|---|---|---|
| R41 | **Upstream operation** — the per-push and archive workflows SHALL run on pushes to trunk and on pull requests to apache/hadoop, and the R10 baseline lookup SHALL resolve the base branch's last successful archive run independently of the run's own ref name and of other branches' run volume. | F3: `licenses.yml:122,144`; triggers branch-only | must |
| R42 | **Dependency-change coverage** — every push or PR that changes any `pom.xml` or assembly descriptor SHALL be checked for shipped-dependency changes against the committed manifest, either by an archive run or by a graph-vs-manifest comparison against the last archive enumeration. Tightens R10 and R25's replacement. | F1: dist path filter covers only root `pom.xml`; no per-push inventory comparison | must |
| R43 | **Baseline freshness** — the archive run SHALL run on a schedule that fires from the default branch, its baseline artifact SHALL be retained longer than the schedule period, and a missing or expired baseline SHALL fail with the exact dispatch command to recover. Tightens R35. | F2: cron inert; no `retention-days` | must |
| R44 | **Release gating** — the release process (`create-release` / HowToRelease) SHALL run the archive gates (R38, R39) and the R40 generator against the exact source and binary tarballs being voted on, and SHALL produce the THIRD-PARTY report (R12) as a release artifact. | R12/R38 partly met; `create-release` has no license step | must |
| R45 | **Precommit vote** — a Yetus plugin SHALL run the per-push checks (store resolution `--strict`, asset gate, R42 comparison) and vote -1 on failure, so reviewers see the result where they already look. Tightens R11. | R11 not met; Hadoop reviewers read Yetus | must |
| R46 | **ASF license categories** — the allowlist (R9) SHALL follow ASF third-party policy: Category A allowed, Category B allowed only in binary form with recorded handling, Category X failing the build, and unknown licenses failing until classified. Tightens R9. | R9 not met; ASF policy defines the categories | must |
| R47 | **Anchored curation patterns** — `excludedArtifacts` and every curated pattern SHALL match whole artifactIds (or `g:a`); a duplicate or unanchored alternative SHALL fail validation. Tightens R2/R39. | F4, reproduced | must |
| R48 | **Source-release accuracy** — every path in `LICENSE.txt` and every file in `licenses/` SHALL be validated per push against the source tree, and every bundled third-party source file known to the asset manifest SHALL appear in `LICENSE.txt`. Extends R7 to the source release. | F5, reproduced | must |
| R49 | **Gate self-tests** — each gate tool SHALL have a synthetic-input self-test, covering a passing input and each failure class, run per push. | Only the generator has one; CI runs none | must |
| R50 | **ASF infrastructure compliance** — the workflows SHALL use only actions and token permissions available to apache/hadoop under ASF infrastructure policy; any registry or cache publishing SHALL be confirmed with INFRA or replaced (e.g. by `actions/cache` or the image the Build workflow already uses), and SHALL degrade to pull-only on PRs from forks. | F3: `packages: write`, GHCR | must |
| R51 | **Self-service regeneration** — when a gate finds drift, the run SHALL publish the regenerated `LICENSE-binary` as a ready-to-apply patch (and MAY open a bot PR), so a contributor never needs the Docker dist build to fix it. | Gap: contributor workflow | later |
| R52 | **Curation hygiene** — every curated entry (overrides, jar mappings, shaded-jar mappings, exclusions, assembly includes) SHALL carry a justification, and an entry whose artifact or version no longer appears in the graph or archive SHALL be flagged for removal. Tightens R21/R29/R39. | Version-pinned overrides; R29 partly met | later |
| R53 | **Licence files shipped match the manifest** — the set of `LICENSE-*.txt` files the tarball ships SHALL equal the set of license texts the generated manifest references, generated from the `texts/` store. Makes R13 checkable; resolves F6. | R13 not met; F6 | later |
| R54 | **Upstream change split** — build-environment resilience changes SHALL be proposed under their own JIRA, separately from the license tooling. | Branch scope gap | later |

## Open items

Confirmed still open by search or by reading the code:

- **R7 stage C:** no archive-side asset check exists (searched). High confidence.
- **R9:** no allowlist code (grep). High.
- **R11:** no Yetus wiring (grep, `dev-support/bin` untouched). High.
- **R12 per-release, R13, R14:** `create-release` and `dist-layout-stitching`
  read. High.
- **R16:** the status table says open, but the evidence says met (see table).

## Recommended order

1. **F1, then F2** (small). Until a dependency change triggers a check, the
   gates' green results do not cover the most common change. Adding the poms to
   the dist path filter is a one-line stopgap.
2. **F4 and F5** (two small edits), plus R47/R48 so they stay fixed.
3. **R49 self-tests**, so the later CI moves (R41) have regression protection.
4. **R41 + R50 (F3), then R45 (Yetus)**, as the upstream adoption package with
   R46 (ASF categories, which is R9).
5. **R44** release gating; then R13/R53, R51, R52.

Pending decisions:

- **Narrow R10's wording or gate the extra files?** Recommend gating
  `licenses-binary/` against the manifest (R53); drop `licenses/` and `texts/`
  from R10, since R48 and the store's own review cover them.
- **GHCR cache upstream?** Recommend asking INFRA before proposing it. Until
  then, fall back to the Build workflow's existing image path.

## Earlier review

`2026-11-06-2031-License-Collection-Requirements-Review.md`:

| Finding | Now | Evidence |
|---|---|---|
| F1 — only the first license of each line read | Fixed | R6 experiment: all licenses of multi-license lines resolved or reported |
| F2 — nested-paren names (JMH GPL-CPE) dropped | Fixed | Single-line run: `GNU General Public License (GPL), version 2, with the Classpath exception` reported missing, exit 1 |
| F3 — 4 store texts are HTML pages | Fixed | HTML grep over `texts/` → none |
| F4 — parity gate fails, 33 GAs missing | Superseded | Manifest now generated from the archive; R25 retired; the dist R40 gate is green |
| F5 — README's duplicated Usage section | Fixed | `grep -c '^## Usage' README.md` → 1 |
| R4/R20 — `MIT license`, EPL v. 2.0 unmerged | Fixed | `pom.xml:970,981` |
| R2 — hsqldb ships off-graph | Fixed | `assembly-includes` now empty; pruned in cc8d34c622a after ground truth showed it absent |
| R21 — version-pinned overrides | Still open | `override-THIRD-PARTY.properties` entries still pinned; now fails loudly via `failOnMissing` (R52) |

## What this review did not cover

- No Maven, Docker or archive build was run, so the plugin-side behaviour of
  `excludedArtifacts` (F4) rests on README and code reading, and R26/R27/R38
  validation rests on the dated run records and run metadata, not on a new
  tarball.
- The archive runs for d4efb02b836 and 4494b532b44 were still in progress at
  23:36; their result is not part of this review.
- No CI artifact was downloaded; NOTICE-binary's attribution completeness (R14)
  was not checked entry by entry.
- R18's CI budget was judged from run durations only.
- The worker's notes and experiments are kept in the session scratchpad
  (`req-review-licenses/review/`).
