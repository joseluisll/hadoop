<!---
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License. See accompanying LICENSE file.
-->

# Harness requirements review, 2026-11-02 15:36

This review checks `HARNESS-REQUIREMENTS.md` against the code on `feat/HARNESS`
at commit `b60dd3b7c9318a989754a252299c3ebe79b6f5aa`. It also reads `README.md`,
`AGENTS.md`, both earlier reviews and the five latest reports. No file outside
`.review/` was changed. The R41 reproduction uses the harness's own code on
synthetic inputs; nothing was built or run in CI.

## Verdict

The "Next plan" step 1 fixes for R45, R54 and R81 are real. R41 is only
partly fixed: a zero-byte `observations.jsonl` is now NOT RUN, but a file
holding only a newline still makes the run PASS; no harness code path writes
such a file, so this is a minor edge case. R40's threshold is "6 more",
not the "6 times more" the text says. R63 is unchanged and still Not met.
The R79 plan-check defects, the ignored Maven exit code and the scenarios that
die early remain as the previous review left them. The five latest reports are
PASS and their counts, unused rules and both-fail rows match the document.

| AS-IS result | Count | Requirements |
|---|---|---|
| Met | 59 | All others |
| Partly met | 18 | R2, R10, R14, R30, R34, R37, R40, R41, R42, R52, R57, R64, R67, R69, R70, R76, R78, R79 |
| Not met | 1 | R63 |
| Process rule, cannot be checked from code | 3 | R3, R65, R66 |

The previous review counted 58 Met, 16 Partly, 3 Not met and 3 process over 80
requirements. R54 is fixed (+1 Met); R41 moved from Not met to Partly; R40
moved from Met to Partly for the threshold wording; R81 is new and Met. That
gives 59 / 18 / 1 / 3 over 81.

How each finding was established:

- **Reproduced:** the harness's own code was run on synthetic inputs in
  `.review/scratch/`.
- **From reading:** the conclusion comes from reading the code and was not
  executed.
- **From an earlier review:** that review found it; this review only confirms
  it still applies and names the current line.

## Findings

### R40: the log-error threshold is "6 more", not "6 times more" (from reading)

R40 says a log error fails "when the candidate has it ... or the candidate has
it more than twice as often and at least 6 times more." `lib/compare_e2e.py:150`
uses `nb == 0 or n > max(2 * nb, nb + 5)`. That is "more than twice and more
than `nb + 5`", i.e. at least 6 more (the README's wording), not 6 times more.
If the text is right, the code is too lenient: with a baseline count of 10, a
candidate count of 16 passes while 6 times more would be 60. Either the text
or the one-line condition should change; the current README matches the code,
so the requirements text is the likelier fix.

### R41: a whitespace-only observations file PASSes (minor edge case, reproduced)

`lib/compare_e2e.py:182-183` treats a missing or zero-byte
`observations.jsonl` as absent and calls `not_run`. A file that holds only a
newline has size 1, so it is not caught: `load_obs` returns `{}`, the row loop
adds nothing, and line 244 sets `PASS`. The text says "no observations for (no
file, or an empty one)" is NOT RUN, so the verdict is wrong for such a file.

No harness code path writes one: `e2e/lib/probe.py:637` is the only writer
(`json.dumps(rec, sort_keys=True) + "\n"`) and `e2e/run.sh:53` creates the file
empty. The case needs a manual edit or a corrupted write, so it is a minor
edge case, not one that invalidates normal runs.

Reproduced with `.review/scratch/test_r41.py`:

```
baseline whitespace only, candidate one observation: exit=0 verdict='PASS'
  stdout: e2e comparison (simple): PASS {'MISSING': 1}
both sides whitespace only: exit=0 verdict='PASS'
  stdout: e2e comparison (simple): PASS {}
baseline one observation, candidate whitespace only: exit=1 verdict='FAIL'
both sides empty: exit=1 verdict='NOT RUN'
baseline empty, candidate one observation: exit=1 verdict='NOT RUN'
```

The first two cases should be NOT RUN. The fix is small: after line 187, if
`not b or not c`, call `not_run`, or count non-blank lines instead of bytes.
The "Next plan" calls R41 done; it is only partly done.

The still-open findings of the previous review are not repeated here:
R63 (broad rules), the R79 plan-check defects, the ignored Maven exit code and
the scenarios that die early. See `2026-11-02-0012-Harness-Requirements-Review.md`.

### The previous review's findings, one by one

- **R54 (a passing ancestry check turned the overall verdict into FAIL):**
  fixed. `ancestry.py:93` writes `PASS`/`FAIL` and `report.py:99-100` accepts
  `PASS`; the latest `ancestry.json` is PASS.
- **R78 (ancestry check):** partly fixed. The check exists and ran, but
  "counts as contained" still needs the whole file to match
  (`ancestry.py:66`).
- **R79 (plan check):** partly fixed. The check exists and ran, but the
  deleted-file case, the `NOTICE_REPLAY` scope, the single-branch merge path
  and the branch order remain (`compare_plan.py:139-147,163-168,209-221`,
  `:77-84`).
- **R80 (replay):** fixed. `replay.py` lists rules that matched nothing and
  those that matched only in some directories; the latest runs show lines
  37/45/53.
- **R41 (empty observations):** partly fixed. Zero-byte is NOT RUN; a
  whitespace-only file still passes (minor edge case, reproduced above).
- **R63 (broad rules):** still open. `expected-e2e-differences.txt:45` is
  still the `Vary` rule with no ticket.
- **Its gaps:** pass-to-skipped is closed by R45, comparator tests by R81; the
  Maven exit code and the scenarios that die early are still open (see Gaps).

## AS-IS requirements

Status is from the code at `b60dd3b7c93`. "Run evidence" cites the five latest
reports (`simple-run-19`, `secure-run-11`, `ha-run-7`, `federated-run-9`,
`mixed-run-8`) or says "not exercised".

| Req | Status | Code evidence | Run evidence |
|---|---|---|---|
| R1 | Met | `compare.sh:82-114`, `build.sh:41-88` | PASS in all five |
| R2 | Partly | `compare_e2e.py:235-244`, `compare_unit.py:125` (exceptions) | PASS |
| R3 | Process | `HARNESS-REQUIREMENTS.md:38-40` | — |
| R4 | Met | `compare.sh` runs the same scripts for both sides | PASS |
| R5 | Met | `build.sh:46-67` (worktree, `dist`/`install`) | build reused, `report.md:5-7` |
| R6 | Met | `build.sh:78-103` (dependency:list, tools) | `artifact-diff.json` |
| R7 | Met | `build.sh:70` (`-Pnative -Drequire.openssl -Drequire.snappy`) | `tmpl_jetty12_phase_a.yml:179-186` |
| R8 | Met | `artifact_diff.py:167-194` | 1,217 differences, 0 unexpected |
| R9 | Met | `artifact_diff.py:85-108` | 1,217 differences |
| R10 | Partly | `artifact_diff.py:54-62`, symlinks skipped at `:80` | 1,217 differences |
| R11 | Met | `artifact-diff.sh:36-64`, `artifact_diff.py:121-132` | `artifact-diff.json` |
| R12 | Met | `artifact_diff.py:215-222` | `artifact-diff.json` |
| R13 | Met | `artifact-diff.sh` self-compare; workflow `:227` | build PASS |
| R14 | Partly | `api_compat.py:308-337` pairs need the class on both sides | 11 findings, 0 unexpected |
| R15 | Met | `api_compat.py:82`, `:271-276` | 7 `api-abstract-method-added` |
| R16 | Met | `api_compat.py:233-234`, `:268-269` | 0 implementor |
| R17 | Met | `api_compat.py:367-381`, `classfile.py:177-194` | 2 `jar-module-name-changed` |
| R18 | Met | `api_compat.py:377-381` | class version 55, info only |
| R19 | Met | `api_compat.py:354`, `:396-397` | no blocking relocated |
| R20 | Met | `api_compat.py:342-365`, `:423-426` | `api-compat.json` |
| R21 | Met | documented out of scope; checks 3/4 | — |
| R22 | Met | `e2e/run.sh:41-115` | 2,994 match overall |
| R23 | Met | `e2e/arch/*.sh` (five) | all five PASS |
| R24 | Met | `e2e/cluster.sh:62-66`, `:137-139` | daemons up |
| R25 | Met | `e2e/scenarios/00-90` | 00-90 ran |
| R26 | Met | `e2e/cluster.sh:74-86`, `run.sh:59-63` | no aborted.txt |
| R27 | Met | `e2e/run.sh:38` | test_probe passed |
| R28 | Met | `probe.py:634-637` | observations.jsonl |
| R29 | Met | `probe.py:379-410` | views compared |
| R30 | Partly | `probe.py:65-72` (3 CORS headers only) | 14/8/9/8 diffs |
| R31 | Met | `probe.py:422-461` | not exercised (T1) |
| R32 | Met | `probe.py:513-543` | secure TLS observations |
| R33 | Met | `probe.py:546-566` | CLI observations |
| R34 | Partly | `probe.py:76-78`, `:91-121` (SPNEGO only; TLS unmasked) | — |
| R35 | Met | `compare_e2e.py:101-139` | every field compared |
| R36 | Met | `compare_e2e.py:193-204` | MATCH/DIFF counts |
| R37 | Partly | `compare_e2e.py:317-330` (FIXED/candidate-only not listed) | — |
| R38 | Met | `classload.py:95-113`, `compare_e2e.py:219-227` | 0 unexpected class jars |
| R39 | Met | `logscan.py:34-41` | 0 new log errors |
| R40 | Partly | `compare_e2e.py:150` ("6 more" vs "6 times") | 0 new log errors |
| R41 | Partly | `compare_e2e.py:182-183` (whitespace not caught) | not exercised |
| R42 | Partly | `unit-tests.sh:157-163` (quick runs whole modules) | unit PASS |
| R43 | Met | `unit-tests.sh:153-155` (`UNIT_RERUNS`) | PASS |
| R44 | Met | `compare_unit.py:38-67` | PASS |
| R45 | Met | `compare_unit.py:98-103`, `:125` | PASS, 0 skipped |
| R46 | Met | `compare_unit.py:149-158` | flaky listed |
| R47 | Met | `unit-tests.sh:166`, `stall-watch.sh` | no stalls |
| R48 | Met | `downstream-deps.sh:64-70` | 248 differences |
| R49 | Met | `downstream-deps.sh:56-62` | 4 scenarios |
| R50 | Met | `compare_downstream.py:111-117` | 248 differences |
| R51 | Met | `downstream_classes.py`, `compare_downstream.py:118-123` | 6 new duplicate sets |
| R52 | Partly | `compare_downstream.py:95-100` (NOT RUN, not FAIL) | simple PASS |
| R53 | Met | `compare.sh:45-51`, `report.py:76-124` | `report.md` |
| R54 | Met | `ancestry.py:93`, `report.py:99-100` | Overall PASS |
| R55 | Met | `report.py:49-72` | commits named |
| R56 | Met | `impact.py:79-121` | `impact.md` |
| R57 | Partly | `impact.py:165-176` (existing duplicate) | 6 new sets |
| R58 | Met | `impact.py:179-193` | 61 / 53 |
| R59 | Met | `artifact_diff.py:232`, `api_compat.py:405`, `compare_e2e.py:256`, `compare_downstream.py:136` | Lines 37 and 45 matched only in simple-run-19, line 53 only in ha-run-7 (replay). Line 37 unused in secure/ha/federated/mixed; 45 in the same four; 53 in simple/secure/federated/mixed. |
| R60 | Met | four allowlists used in `compare.sh` | — |
| R61 | Met | `allowlist.py:30-52` | replay works |
| R62 | Met | `compare_e2e.py:42-48`, `:205-212` | replay works |
| R63 | Not met | `e2e/expected-e2e-differences.txt:45` (no ticket, broad) | — |
| R64 | Partly | unannounced rules remain (`impact.md`) | 61 / 53 |
| R65 | Process | rules added by hand | — |
| R66 | Process | replay before commit | replay run |
| R67 | Partly | `expected-e2e-differences.txt:45,53` | — |
| R68 | Met | `tmpl_jetty12_phase_a.yml:99`, `lib/common.sh:94-100` | `simple-run-aa-8` PASS |
| R69 | Partly | `ci/break_candidate.py:46-59,105-137`, `ci/artifacts.sh:57,67-83` (no verdict assertion) | broken run queued |
| R70 | Partly | `tmpl_jetty12_phase_a.yml:94-106` (per-job PREPARATION) | PASS |
| R71 | Met | `ci/wait-turn.sh:65-110`, queue/queue-2 `tmpl:109-169` | — |
| R72 | Met | `tmpl_jetty12_phase_a.yml:179-186` | build PASS |
| R73 | Met | `ci/build-key.sh:42-49`, `ci/find-build.sh:35-42` | builds reused |
| R74 | Met | `unit-tests.sh:183-203` (`changed-1`..`-4`) | — |
| R75 | Met | `tmpl_jetty12_phase_a.yml:416-436` | run summary |
| R76 | Partly | `compare.sh:65` (PR_BRANCHES unset skips) | — |
| R77 | Met | `README.md:230-316`; both-fail rows | 11 secure, 9 federated |
| R78 | Partly | `ancestry.py:66` (whole-blob match) | `ancestry.json` PASS; the cited ha-run-4/mixed-run-5/federated-run-6 predate the check |
| R79 | Partly | `compare_plan.py:139-147,163-168,209-221` | `compare-plan.json` PASS |
| R80 | Met | `replay.py:109-148`, `replay.sh` | ha-run-3 363, mixed-run-4 519, federated-run-5 320 `unexpected_class_jars`; latest 0 |
| R81 | Met | `test_comparators.py`, `compare.sh:56`, `run-all.sh:34`, workflow `:126` | self-check ok |

## Partly met

| Req | Gap |
|---|---|
| R2 | The text says every other difference fails, but FIXED, BOTH_FAIL and candidate-only MISSING are listed without failing. |
| R10 | Symlinks are skipped (`artifact_diff.py:80`) and the text does not say so. |
| R14 | A public class removed outright gets no API finding: pairs need the class on both sides (`api_compat.py:308-337`). |
| R30 | "The CORS headers" are three; `allow-credentials`, `expose-headers` and `max-age` are compared by name only (`probe.py:65-72`). |
| R34 | "Every recorded field" is too strong: `HEADER_MASKS` masks SPNEGO tokens only and TLS fields are not masked (`probe.py:76-78`, `:91-121`). |
| R37 | FIXED and candidate-only observations are counted in the report but not listed (`compare_e2e.py:317-330`). |
| R40 | The threshold is "6 more", not "6 times more" (`compare_e2e.py:150`). |
| R41 | A whitespace-only observations file still PASSes (reproduced; `compare_e2e.py:182-183`). |
| R42 | README test lists differ from `unit-tests.sh`, and `quick` runs whole modules for entries with no test list (`unit-tests.sh:157-163`). |
| R52 | With results on one side only, the verdict is NOT RUN and overall INCOMPLETE, not a failure (`compare_downstream.py:95-100`). |
| R57 | A project with an existing, unchanged duplicate can be reported as having had none (`impact.py:165-176`). |
| R64 | Unannounced rules remain (61 in simple, 53 elsewhere). |
| R67 | The `Vary` rule names no issue, and the job-counter rule names the wrong one (`expected-e2e-differences.txt:45,53`). |
| R69 | Nothing asserts the intended check failed, so a broken run that wrongly passes shows green (`ci/artifacts.sh:67-83`). |
| R70 | Each job resolves `PREPARATION` separately (`tmpl_jetty12_phase_a.yml:98`). |
| R76 | The README gives `PR_BRANCHES` a default, but none exists, so local runs skip the plan check (`compare.sh:65`). |
| R78 | "Counts as contained" needs the whole file to match; a cherry-pick onto a file the patch also changes is reported missing (`ancestry.py:66`). |
| R79 | The previous review's defects remain: a file deleted by a branch and absent on the candidate is reported `replay-differs` (`compare_plan.py:139-147,214-221`); `NOTICE_REPLAY` checks only its listed lines (`:163-168`); a single branch's file also goes through `git merge-file` (`:209-221`), not "tip blob applied whole"; and `PR_ORDER` (`:77-84`) puts HADOOP-20013 before HADOOP-20014 while `JETTY12-MIGRATION-PLAN.md:61` says 20014 first. |

## Documentation out of date

- **`JETTY12-MIGRATION-PLAN.md`:** it says `ha` run 5 "was still running"
  (line 259), but `older/ha-run-5/report.md:9` says `Overall: PASS`. It also
  says the `federated` run 7 regression is "not yet identified" (lines 258-259),
  while `README.md:302-316` attributes it to
  `TestFederationInterceptor#testSubClusterTimeOut`; `older/federated-run-7/report.md:9`
  is FAIL on the unit tests.
- **`README.md`:** the opening table leaves out HADOOP-19970 (lines 21-27). It
  also says the workflow leaves `PR_BRANCHES` empty for `-run-aa-` runs
  (line 483), but `contains(...) && '' || 'origin/...'` in
  `tmpl_jetty12_phase_a.yml:104` returns the branch list. That is harmless,
  because `compare.sh:59` skips both checks when the sides are one commit.
- **`lib/compare_plan.py`:** the docstring says "or in the config, 'replay
  PATH ...'" (line 52), but no config file exists; `NOTICE_REPLAY` is a dict.
  It also says the replay's result must differ or the entry is unused
  (line 53-54), but `replay_used` is added for every path a branch changes
  (`:208-223`), so a matching replay still counts as used.

## Gaps with no requirement or to-do item

These are in addition to the previous review's gaps. Its pass-to-skipped and
comparator-test gaps are now closed by R45 and R81.

- **Whitespace-only observations (minor):** a file with only blank lines
  passes as PASS (reproduced above). No harness path writes one; R41 says "no
  observations", the code checks size 0 only.
- **Maven exit code:** still ignored when a module has some reports
  (`lib/compare_unit.py`: `maven_exit` is used only by `checks_only`).
- **Scenarios that die early:** still only a timeout is recorded; a scenario
  that dies the same way on both sides loses its observations without failing.
- **Late ancestry check:** R78 still runs in the final job, after hours of work.
- **Self-checks:** only `simple` has `aa` or `broken` runs. `simple-run-aa-8`
  succeeded; the broken run was still queued when the reports were downloaded,
  so R69 has no fresh evidence in them.
- **As PRs land:** nothing says what to do when a branch merges; a squash-merged
  branch would show as `missing` and stop every run until it is removed from
  `PR_BRANCHES`.
- **Plan coverage:** no requirement checks the umbrella's exit criteria, such as
  no Jetty 9.4 artifact left. JDK 21/25 and mixed-version runs have no T number.
- **Check 4 has no allowlist:** a one-sided flake fails the run, so "all five
  pass" depends on luck or a manual exception.

## Open items

Each line gives the item's status, what the latest runs show, and the search
that settled it. Searches ran over `lib/`, `ci/`, `e2e/` and the root shell
scripts, excluding `*.md`; rule searches also covered the four `*.txt`.

### TO-BE T1-T25

| Item | Status | Latest runs | Checked with |
|---|---|---|---|
| T1 | Open | No `raw` request in any scenario, so R31 is unexercised. | `raw` in `e2e/`: only `probe.py`, `test_probe.py`; the `ez-raw` CLI is unrelated. |
| T2 | Open | A class still compares by jar name without its version (`classload.py:104-106`). | `classjar-version`: no hits. |
| T3 | Open | One-side classes are counted per daemon, not listed; Impact lists none (`compare_e2e.py:332-339`). | `one side only`: `classload.py:24`, `compare_e2e.py:337`. |
| T4 | Open | No per-field counts in the report. | `reason_phrase\|location_form\|error_text` in `impact.py`, `report.py`: no hits. |
| T5 | Done as R78 | `ancestry.json` PASS in all five latest runs. | `ancestry.py:66,93`; reproduced by R78. |
| T6 | Done as R80 | Replay output; latest runs list unused rules. | `replay.py:109-148`; replay run. |
| T7 | Open | `impact.md`: 53 accepted differences without `announced:` (61 in simple). | `announced` in the rule files; HADOOP-20014 rules lack it. |
| T8 | Open | 11 both-fail observations in `secure-run-11`. | `MAPREDUCE-7548`: rule/comment only, no fix. |
| T9 | Open | 9 both-fail observations in `federated-run-9`. | `YARN-12024\|YARN-12025`: scenario comments only. |
| T10 | Open | Timeline observations are masked (`obsdiff`); class-load noise is not. | `YARN-12030\|Jettison`: rule/comment only. |
| T11 | Open | No cross-run history in `unit-compare.json`. | `history` in `compare_unit.py`, `report.py`, `impact.py`: no hits. |
| T12 | Open | POM entries are still volatile (`artifact_diff.py:56`). | `META-INF/maven\|pom.xml`: only `VOLATILE_ENTRY`. |
| T13 | Open | `ARTIFACTS` is still the original 14 (`downstream-deps.sh:64-70`). | `hadoop-yarn-server-common\|hadoop-hdfs-httpfs\|hadoop-sls\|hadoop-yarn-server-tests`: no hits. |
| T14 | Open | `-Xlog:class+load` is only on daemons (`cluster.sh:55`). | `Xlog:class+load`: no container hit. |
| T15 | Open | Check 1 reports the change; nothing checks LICENSE/NOTICE consistency. | `LICENSE-binary\|NOTICE-binary`: only `compare_plan.py`'s docstring. |
| T16 | Done as R79 | `compare-plan.json` PASS in all five latest runs. | `compare_plan.py`; run evidence. |
| T17 | Open | No per-ticket or merge-prefix run. | `per-ticket\|prefix of the merge\|merge-order`: docs only. |
| T18 | Open | `announced:` is free text; no JIRA release note is read. | `release note` in `lib/`: docstrings/prose only. |
| T19 | Open | No HTTP/1.0 request. | `HTTP/1.0`: no hits. |
| T20 | Open | A candidate-only failing test is not compared; the runs review counts 13 candidate-only tests in simple-run-17. | `candidate-only` in `compare_unit.py`, `report.py`: no hits. |
| T21 | Open | HADOOP-20013 rules disagree: `expected-differences.txt:36,37` and `expected-downstream-differences.txt:27` lack `announced:`; line 47 has it. Latest `impact.md`: 61 (simple), 53 (others). | `HADOOP-20013` in the rule files. |
| T22 | Open | No servlet behaviour probe. | `getHttpServletMapping\|PushBuilder\|getMajorVersion`: no hits. |
| T23 | Open | `api-compat.json` counts `public_members_added`; `impact.py` lists no types. | `public_members_added`: `api_compat.py` only. |
| T24 | Open | Rule line 53 still names MAPREDUCE-7548. | `MAPREDUCE-7548` in `expected-e2e-differences.txt:53`. |
| T25 | Open | Failover order is still random. | `failover.random.order`: no hits. |

### TO-BE T26-T38

| Item | Status | Latest runs | Checked with |
|---|---|---|---|
| T26 | Open | No downstream program is compiled or run; simple-run-19 has 248 resolution differences (G5). | `MiniDFSCluster\|MiniYARNCluster\|javac`: no hits. |
| T27 | Open | 72 `downstream-dup-added` rows in simple-run-19; no winner or API comparison (G1). | `classpath order\|winner`: `compare_downstream.py:35,173`, `downstream_classes.py:26` explain it; none is reported. |
| T28 | Open | No exclusion scenario exists; G6 shows none excludes Hadoop's servlet or annotation jar. | `exclusion`: no hits in code. |
| T29 | Open | Only the `older-jetty` client scenario (G7). | `jersey-server\|jetty-server`: no hits. |
| T30 | Open | `dist-file-removed` javax.annotation-api in simple-run-19; no `class-gone` (G2). | `class-gone`: only the runs review. |
| T31 | Open | 2 `META-INF/services` files rewritten (G4). | `META-INF/services`: no hits. |
| T32 | Open | 3 + 8 changed entries outside the relocated packages (G8). | `InterfaceAudience\|InterfaceStability` in `impact.py`, `artifact_diff.py`: no hits. |
| T33 | Open | 0 API findings on Hadoop jars (G9). | `LimitedPrivate\|InterfaceAudience.Public` in `lib/`: no hits. |
| T34 | Open | 87 module scopes changed (G3); `unit-tests.sh` does not read `dependencies.tsv`. | `dependencies.tsv`: only `artifact_diff.py` reads the build's file. |
| T35 | Open | 11 + 9 both-fail observations and the run is PASS (G10). | `BOTH_FAIL`: reported at `compare_e2e.py:204,248,298,300`; `report.py:99-100` does not make it INCOMPLETE. |
| T36 | Open | federated-run-9's `unit-compare.json` lists flaky tests (G11). | `history\|last N runs`: no hits. |
| T37 | Open | ha-run-7 reports lines 37/45 unused; simple-run-19 line 53 (G12). | `@arch=`: only the runs review. |
| T38 | Open | Every architecture drives its daemons with its own client (G13). | `mixed-version\|cross-version\|other side's client`: no hits. |

The "Next plan" step 1: R45, R54 and R81 are done and behave as described.
R78-R80 are in the code and ran in the latest reports (`ancestry.json` and
`compare-plan.json` PASS). R41 is only partly done; its remaining case is the
minor edge case above.

## Recommended order

1. Fix R40's threshold (small; it changes when a log error fails). R41's
   whitespace case is a minor edge case, but the check is the same size.
2. Fix the R79 plan-check defects and narrow the R63 `Vary` rule. The plan-check
   fixes are moderate; the rule fix is one line plus a ticket.
3. Address the Maven exit code and the scenarios that die early; both shrink
   what is compared without failing.
4. Then step 2 detection work: T12, T13, T14, T15, T1/T19, T22, T3 evidence,
   T23, T4.
5. Then step 4: T10 and T25, then T3 reporting, T11, T8 and T9.

Step 0 decisions (checked against the code and the latest reports; the
previous review's recommendations still hold):

- **T3:** still undecided. One-side classes are counted per daemon only
  (`compare_e2e.py:332-339`), so the previous review's "report first, fail
  after T10 and T25" is still the right order.
- **T17:** still undecided. `PR_ORDER` exists but no per-ticket or prefix run
  does, so its "yes for checks 1, 2 and 5" still applies.
- **T18:** still undecided. `announced:` is free text (`api_compat.py:423-426`),
  so a manual check at release-note time remains the cheap option.
- **T7 with T21:** still undecided. `impact.md` still shows 61 (simple) and 53
  (others), and the HADOOP-20013 rules still disagree on `announced:`
  (`expected-differences.txt:36,37` vs `:47`).

## Implementation proposal

Added after the review by the session that checked it. It reorders the
recommendation above so that what can make a verdict wrong comes first, and
records the owner's two decisions.

**Step 1: one fix batch.** Each code change goes in the same commit as its R
text and README line.

| Item | Change | Size |
|---|---|---|
| Maven exit code (R45) | `compare_unit.py`: a module whose Maven run failed on the candidate and succeeded on the baseline fails the suite and is listed; failed on both is listed without failing. A crashed module can pass today. | ~5 lines, plus cases in `test_comparators.py` |
| R79, deleted file | A file a branch deletes and the candidate does not have is a match, not `replay-differs` (`compare_plan.py:208-213`). | small |
| R79, single branch | One branch's change is its tip blob applied whole, as the text says, not a `git merge-file` (`compare_plan.py:131-158`). | small |
| R79, order | `PR_ORDER` follows `JETTY12-MIGRATION-PLAN.md:61`: 20012, 20014, 20013, 20015, 20016, then `jetty-phase-a`. | 2 lines |
| R40 | Reword the text to "at least 6 more", which is what the code and the README do. | 1 line |
| R41 | Count non-blank lines instead of bytes (`compare_e2e.py:182-183`). | 1 line |
| Out-of-date text | `JETTY12-MIGRATION-PLAN.md:257-259`, the README's opening table (HADOOP-19970), the `compare_plan.py` docstring (lines 52-54). | text only |

**Step 2: R63.** File a JIRA for the `Vary` difference, then narrow rule 45 to
`yarn-rm-web`, the only place it matches. Separate from step 1, because it
needs the ticket number.

**Step 3: verify.** Run the five architectures and an `aa` run on the fixed
harness, wait for `simple-run-broken-webhdfs-user-7` (R69's only evidence), and
review the new runs.

**Step 4: "Next plan" step 2,** in the order above, after the step 0
decisions.

Decisions taken by the owner on 2026-11-02:

- **R40:** fix the text, not the code.
- **`PR_ORDER`:** follow the migration plan.

## What this review did not cover

- No Maven build, cluster or CI job was run. The R41 reproduction used
  `compare_e2e.py` on synthetic inputs; the Maven-exit finding comes from the
  previous review's reproduction and the current code.
- The Java test fixtures under `e2e/lib/*.java`, the per-architecture caller
  workflows, and the generated HTML/JSON reports beyond the sections cited
  were not read line by line.
- The 61 and 53 counts were verified against `impact.md`; the individual
  differences were not recounted.
