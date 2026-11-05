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

# Harness runs review: first runs of R90 to R95, 2026-11-03 21:38

This review reads the latest report of each architecture, the first
attribution run and the two broken-candidate runs against
`HARNESS-REQUIREMENTS.md` on `feat/HARNESS` at `93165486a76`. It is a
snapshot: no harness code, requirement or allowlist rule was changed for it,
and nothing outside `.review/` was edited. The proposals continue the TO-BE
numbering at T39.

## Runs reviewed

- Baseline: `4f4422ad703` (`origin/PREPARATION`).
- Candidate: `93165486a76`: the baseline plus `HADOOP-20012-upstream` to
  `HADOOP-20016-upstream` and `jetty-phase-a` (HADOOP-19970), and the harness
  changes R90 to R95 (T12, T15, T23, T22, T19, T14).

`api-compat.json` is byte-identical in all five runs (md5 `3c06dad4`), so
check 2 is one result. `artifact-diff.json` md5s differ in the digest, but the
five runs do share one build: every summary count is identical (1,593
differences, 2 unexpected, the same class-path totals), and the rows that
differ are the same `pom-dependency-changed` entries with the elements of a
Python `frozenset` in another order. Check 1 is therefore also one result in
substance; the md5s differ because of a defect in R90's output (G8), not a
different build.

| Run | Overall | End to end (match / diff / both fail) | Unit tests |
|---|---|---|---|
| [simple-run-20](https://github.com/joseluisll/hadoop/actions/runs/41574970529) | FAIL | 983 / 11 / 1 | PASS, 2 flaky, 13 candidate-only tests pass |
| [secure-run-12](https://github.com/joseluisll/hadoop/actions/runs/41574970838) | FAIL | 626 / 10 / 2 | PASS, no flaky |
| [ha-run-8](https://github.com/joseluisll/hadoop/actions/runs/41574971189) | FAIL | 621 / 10 / 1 | PASS, 1 flaky |
| [mixed-run-9](https://github.com/joseluisll/hadoop/actions/runs/41574971497) | FAIL | 590 / 9 / 1 | PASS, no flaky |
| [federated-run-10](https://github.com/joseluisll/hadoop/actions/runs/41574971505) | FAIL | 488 / 9 / 15 | PASS, 5 flaky |
| [simple-run-aa-9](https://github.com/joseluisll/hadoop/actions/runs/41574971545) | FAIL | 992 / 2 / 1 | PASS, no flaky |
| [broken-webhdfs-user-8](https://github.com/joseluisll/hadoop/actions/runs/41574971597) | FAIL, harness check PASS | 921 / 21 / 1, 50 regressions | NOT RUN |
| [broken-static-6](https://github.com/joseluisll/hadoop/actions/runs/41574972165) | FAIL, harness check PASS | 977 / 16 / 1, 1 regression | NOT RUN |
| [attribution-run-1](https://github.com/joseluisll/hadoop/actions/runs/41574971687) | FAIL | 9 trees, `prefix-5` absent | — |

## What the runs show

### Impact that is reported

The largest accepted differences, from `report.md` section "Artifacts and
dependencies" in simple-run-20:

| Ticket | Differences |
|---|---|
| HADOOP-19970 | 510 `class-source-changed`, 159 `dep-removed`, 87 `dep-added`, 85 `jar-entry-changed`, 42 `jar-entry-added`, 19 `pom-dependency-added`, 17 `pom-dependency-removed` |
| HADOOP-20013 | 41 `dep-removed`, 1 `dist-file-removed`, 1 `jar-entry-added` |
| HADOOP-20014 | 27 + 19 + 19 `dep-removed`, 19 + 19 `dep-added`, 24 `class-removed`, 25 `jar-entry-removed`, 16 `jar-entry-added`, 15 `class-added`, 12 `pom-dependency-removed` and `-added` |
| HADOOP-20015 | 6 `jar-entry-changed` (ConcurrentHashMap), 4 `jar-entry-changed` (SLF4J) |
| HADOOP-20016 | 15 `jar-entry-changed` (SLF4J), 6 `jar-entry-changed` (getMimeType), 8 `pom-dependency-added` |
| HADOOP-20012 | 3 `pom-dependency-changed` |

- **HADOOP-19970 is the user-visible change.** 474 classes move from
  `javax.servlet-api-3.1.0.jar` and 36 from `jakarta.servlet-api-4.0.4.jar`
  to `jetty-servlet-api-4.0.9.jar`; 9 API findings (2 module-name changes and
  7 `api-abstract-method-added`); the replaced jar adds 5 public types and 22
  public members (`api-compat.md`, "API a replaced jar makes available").
- **The downstream effect is reported and accepted.** 248 differences in the
  56 projects, unexpected 0 (`downstream-compare.md`, simple-run-20); six
  projects gain a `javax.servlet` duplicate set (`Impact on users`).
- **Two license entries are genuinely wrong.** `Unexpected differences` in
  every run reports `license-entry-stale` for
  `org.glassfish.jersey.containers:jersey-container-jdk-http:2.46` and
  `org.glassfish.jersey.test-framework.providers:jersey-test-framework-provider-jdk-http:2.46`
  ("no jar in the distribution"). `git diff 4f4422ad703 93165486a76 --
  LICENSE-binary` adds both and removes `jersey-test-framework-provider-jetty`;
  the digest shows 19 test-scope additions of each and the check itself finds
  no such jar in the distribution. HADOOP-20014 must remove the two entries
  from `LICENSE-binary` before merge.
  This is the only patch defect that check 1 reports, and it fails every run.
- **The broken candidates were caught.** `broken-webhdfs-user-8` fails with 50
  regressions in `hdfs-webhdfs` and elsewhere; `broken-static-6` with
  `hdfs-web:nn-static-css` status 404. Both reports say "Harness check:
  **PASS**" and skip the unit suites (R69).

### Noise and flakes

- **The six "new log errors" are not errors.** Every run, including the A/A
  run, lists the same six, with `baseline_count: 0`
  (`e2e-compare-<arch>.json`, `new_log_errors`): `ClassCastException`,
  `MessageBodyProviderNotFoundException`, `ModelValidationException`,
  `NoContentException`, `ServiceConfigurationError` and
  `WebApplicationException`, each with a `source: file:` path. They are
  class names in T14's `-Xlog:class+load` lines, read by `logscan.py`.
- **The class-load comparison fails on the control run.** simple-run-aa-9 has
  `blocking.unexpected_class_jars: 120`: 60 `map`, 37 `mr-am` and 23
  `reduce` moves from `.../baseline/.../application_<id>/.../job.jar` to
  `.../candidate/.../application_<id>/.../job.jar`. simple-run-20 has the same
  120; mixed-run-9 29 and federated-run-10 29. mixed-run-9 adds 30 moves of
  three classes on ten daemons from `jakarta.activation-api-1.2.1.jar` to
  `jakarta.activation-1.2.2.jar`; no `dist-file-*` difference exists for
  either jar.
- **A scenario is reported as ending early because of the harness.**
  `scenario:10-web-common.completed` is BOTH_FAIL in all five architectures
  and in the A/A run; `scenario:70-secure.completed` is also BOTH_FAIL in
  secure. The extra log ends with
  `_: line 7: http://localhost:19888/jmx: No such file or directory` after
  461 `[PASS]` lines and no `[FAIL]`.
- **The one probe difference is real, but unexplained.**
  `probe:probe-base` differs at `/body/json/mapping/match: "str" vs "null"`
  in every architecture run and both broken runs, and matches in the A/A run.
  The comparator prints the baseline first (`compare_e2e.py:203-205`), so the
  baseline records a string and the candidate JSON null; what the value is,
  and why, is not recorded (G5).
- **Federated still compares no YARN application through the router.** 14
  `fed-yarn` observations and the scenario marker are BOTH_FAIL. The direct
  submission `fed-yarn:dshell-direct-sc1` MATCHes, but
  `router-apps-direct`, `router-app-list-direct` and
  `app-on-one-subcluster-direct` are BOTH_FAIL "no jetty12-direct-sc1
  application on the router" (G7).
- **The expected noise is as documented:** the 8 `common-cli` servlet-load
  differences, `mapreduce-am:am-job-counters` (timing), the `Vary` static-file
  differences in simple, and the timeline-server classes (all accepted by the
  `classonly timelineserver:` rules: 18 baseline / 58 candidate in secure).

### What the runs do not verify

- The router's read paths in `federated`: the direct submission runs, but the
  five other direct checks (two listings, two reads by id and
  `app-on-one-subcluster-direct`) are BOTH_FAIL; the reads by id are recorded
  without an expectation.
- The probe's actual answers: only their JSON types are compared (G5).
- Classes loaded on one side only fail nothing: `CLASSONLY_FAIL` is off, and
  7 to 249 unexpected classes remain per architecture (G9).
- `prefix-5` in the attribution run (a runner disk failure, not in the
  report).
- The unit suites are the hand-made lists of R42, and no run drives one side's
  client against the other side's daemons (T38).

## Gaps

| # | Seen in | What the run shows | Why it can be missed |
|---|---|---|---|
| G1 | all six normal runs | `scenario:10-web-common.completed` (and `70-secure.completed` in secure) BOTH_FAIL after every check passed (`e2e-compare-<arch>.json`, `both_fail`; extra log line 462) | `e2e/run.sh:80-88` passes the done file as `$5` to a `bash -c` shell; `10-web-common.sh:27` and `70-secure.sh:29` run `set -- ${line}`, so `: > "$5"` writes to the instance's URL. R82 faithfully reports a scenario that ends early, but every run reports a false one |
| G2 | all six normal runs | Six `new_log_errors` in `e2e-compare-<arch>.json`, baseline 0, including the A/A run | `logscan.py:34-41,80-85` scans `classload-*.log` and matches class names (`java.lang.ClassCastException`, ...); the message keeps the side-specific path |
| G3 | simple-20, mixed-9, federated-10, A/A-9 | 120, 59 (29 job.jar + 30 activation), 29 and 120 blocking `unexpected_class_jars` (`e2e-compare-<arch>.json`, `class_jar_moves`) | `classload.py:40-46,103-106` compares jar directory and name; `job.jar` paths carry the per-run application id, and two shipped jars provide the same `jakarta.activation` classes |
| G4 | mixed-9 | 30 of the 59 moves are `jakarta.activation-api-1.2.1.jar` -> `jakarta.activation-1.2.2.jar` across ten daemons; no dist difference | R38 treats a different artifact name as a difference, but both jars ship on both sides and classpath order decides |
| G5 | all normal and broken runs | The only probe difference is a type change, `/body/json/mapping/match: "str" vs "null"`; the A/A run matches | `probe.py:130-154,274-276` records JSON values as `"str"`/`"num"`/`"bool"`; `10-web-common.sh:102-104` uses `--shape json`. Servlet versions, jar name, mapping values and push support are never compared by value |
| G6 | attribution-run-1 | `attribution.json` has 9 trees and no `prefix-5`; the run says "9 trees" and nothing else | `attribution.py:143-151` iterates only directories that exist; no expected-tree list. `gh run view 41574971687` shows `Tree prefix-5` failed with "No space left on device" |
| G7 | federated-10 | `dshell-direct-sc1` MATCH; `router-apps-direct`, `router-app-list-direct` and `app-on-one-subcluster-direct` BOTH_FAIL | `85-federation.sh:149-170` derives all five from the router's `/apps` listing; if the listing omits the app, the checks compare nothing and R88's expected result is not met |
| G8 | all five | digest md5s for `artifact-diff.json` differ while counts are identical; the differing rows are the same content with another `frozenset` order | `artifact_diff.py:288` formats `frozenset(exclusions)` in the detail; `_pom_dep` (`:178-194`) and `compare_poms` (`:285-288`) omit the declared `<version>`, so a direct dependency version change is not a difference |
| G9 | all six normal runs | 8 (simple), 16 (secure), 15 (ha), 249 (mixed), 7 (federated) and 10 (A/A) unexpected one-side classes; mixed's 249 include 206 `historyserver` classes loaded on the baseline only | R87 keeps them non-blocking with `CLASSONLY_FAIL=false`; the A/A run has 10 on one build, so turning it on would fail the control run |
| G10 | attribution ticket-5, ticket-6 | Two rules tagged with the wrong ticket; one UNEXPECTED POM change in a ticket tree | `expected-differences.txt:125` (`jetty-servlet`, tagged HADOOP-19970) and `:140` (`jetty-webapp`, tagged HADOOP-20016) are added by HADOOP-20015; ticket-6 has `pom-dependency-changed ...hadoop-yarn-common|...jersey-test-framework-provider-jetty` because 19970 alone removes an exclusion that the combined candidate no longer shows |

## Proposed TO-BE items

### Verdicts and coverage first

- **T39. Record the servlet probe's answers, not their JSON types.**
  Compare a stable projection of the probe body by value: the four servlet
  version numbers, `http_servlet_jar`, `mapping.match_value`/`pattern`/
  `servlet_name`/`match`, `push_supported` and `new_push_builder`; mask only
  what is run-specific. Add the probe's two runs to the comparator self-test.
  Then the `mapping.match` difference can be read, its cause identified and
  HADOOP-19970's release note updated if it is intended. Extends R93.
  *Source: G5; all runs.*

- **T40. Compare a published POM's declared dependency version.** Resolve the
  `<version>` of every declared dependency from the same POM's properties and
  report a change as `pom-dependency-changed` (or
  `pom-dependency-version-changed`), as R90 already does for managed
  versions. A direct version change in a published POM is visible to Maven
  consumers and is currently invisible. Extends R90.
  *Source: G8; `artifact_diff.py:178-194,285-288`.*

- **T41. Make `artifact-diff.json` deterministic.** Format the exclusions of
  a `pom-dependency-changed` detail as a sorted list, not a Python
  `frozenset` repr, so two runs of one build produce the same bytes. Until
  then the digest's md5 parity cannot distinguish one build from two. Extends
  R90.
  *Source: G8; the five md5s in `digest.txt`.*

- **T42. Fix the scenario done marker.** Carry the done file in an
  environment variable (or in a name the scenarios cannot overwrite), not as
  the `bash -c` positional parameter the scenarios reuse with `set --`; add a
  scenario self-test whose body uses `set --` and must still write the marker.
  Extends R82. *Source: G1; `e2e/run.sh:80-88`,
  `10-web-common.sh:27`, `70-secure.sh:29`.*

- **T43. Keep class-load logs out of the error scan.** Exclude
  `classload-*.log` (and the class-load pattern) from `logscan.py`, or scan
  only messages that are not `[class,load]` lines. Add a comparator case with
  a class-load line naming an exception class. Extends R39 and R95.
  *Source: G2; all runs.*

- **T44. Normalise the class-load comparison.** Mask the per-run application
  id and the side root in every jar path (R34 applies to recorded fields), and
  treat a class whose baseline and candidate jars both ship on both sides and
  provide the same class as not a difference. The A/A run must then have no
  blocking `unexpected_class_jars`. Extends R38 and R95.
  *Source: G3, G4; simple-aa-9, mixed-9.*

- **T45. Make the A/A run a gate.** An A/A run that reports any blocking
  difference is a harness failure: require `PASS` (or at least zero blocking
  entries) before a normal batch is read, and list the blocking entries that
  made it fail. Extends R68. Needs the owner's decision because it changes
  acceptance.
  *Source: G3, G9; simple-run-aa-9 FAIL.*

- **T46. A noise budget before `CLASSONLY_FAIL`.** Keep the switch off until
  an A/A run reports zero unexpected one-side classes, or mask the classes
  that differ between two runs of one build (record them from an A/A run) and
  fail only on classes not in that set. Extends R87 and the T3 extension.
  Needs the owner's decision.
  *Source: G9; 10 one-side classes in simple-run-aa-9.*

- **T47. Attribution must know its trees.** Build the expected list from
  `PR_ORDER` (`ticket-1..6` and `prefix-2..5`), report a missing tree as a
  problem, and fail the attribution job when a tree's results are absent.
  A runner failure then cannot silently shrink the report. Extends R89.
  *Source: G6; attribution-run-1.*

- **T48. Correct the attribution rules.** Retag `expected-differences.txt`
  lines 125 and 140 to HADOOP-20015, and add a rule for ticket-6's
  `pom-dependency-changed ...hadoop-yarn-common|...jersey-test-framework-provider-jetty`
  (or decide that a ticket tree without its merge predecessors is not a
  shippable state and do not fail on such interactions). Changes rules:
  needs the owner's decision (R65) and a replay (R80).
  *Source: G10; attribution ticket-5, ticket-6.*

- **T49. Record the federated direct reads without an expectation until the
  router listing is understood.** `dshell-direct-sc1` runs on both sides but
  the router's `/apps` listing omits it, on both sides. Record
  `router-apps-direct`, `router-app-list-direct` and
  `app-on-one-subcluster-direct` as comparisons, not expectations, and file a
  YARN issue for the listing; `app-on-one-subcluster-direct` can use the
  sub-cluster's own listing meanwhile. Extends R88.
  *Source: G7; federated-run-10.*

## Proposed order

1. **HADOOP-20014's `LICENSE-binary`.** Not a harness change: remove the two
   stale test-scope entries so check 1 can pass.
2. **T42, T43, T44.** They remove the false failures that make every run red
   for a non-patch reason; all are small and need no decision.
3. **T45 and T47.** Make the A/A run and the attribution report trustworthy
   before the next batch is read.
4. **T48 and T46** (owner decisions), then **T39**, which turns the probe into
   the behaviour check R93 intended.
5. **T40, T41, T49.** Static and federation coverage; T40/T41 are small.

## Decisions needed from the owner

- **HADOOP-20014:** remove the two test-scope coordinates from
  `LICENSE-binary` (the check's verdict is correct).
- **T45:** may an A/A run with a blocking difference block a batch?
- **T46:** keep `CLASSONLY_FAIL` off until the A/A noise is understood, and on
  what budget?
- **T48:** the two rule retags and the new ticket-6 rule need agreement (R65)
  and a replay.
- **T49:** whether R88's listing expectations stay, and whether to file a YARN
  issue for the router listing that omits a directly submitted application.
- **T39:** if the `mapping.match` difference is a real HADOOP-19970 behaviour
  change, its release note should say so.

## Earlier reviews

The earlier runs review (2026-11-02 10:30) proposed G1-G13 and T26-T38:

| Item | Status with this review's evidence |
|---|---|
| G1 duplicate winner | still seen: `downstream-compare.md` lists the duplicate sets, no winner or API comparison |
| G2 removed classes' new provider | still seen: HADOOP-20013's `javax.annotation-api` removal has no `class-gone`/provider list |
| G3 changed modules not all tested | still seen: the unit tables are R42's lists |
| G4 SPI integrity | still seen: HADOOP-20014 changes service files; no check |
| G5 downstream compile/run | still seen: check 5 resolves only |
| G6 exclusion scenarios | still seen: no `downstream-exclusion-*` |
| G7 more scenarios | still seen: only `older-jetty` |
| G8 audience of shaded changes | still seen: counts only |
| G9 Hadoop API exposing the replaced jar | still seen: no Hadoop-jar API finding |
| G10 PASS with BOTH_FAIL | not rechecked: no run in this batch is PASS with BOTH_FAIL; secure and federated still have 2 and 15 |
| G11 flaky history | no longer seen: R85's history is in `unit-compare.md` |
| G12 rules limited to architectures | still seen: lines 38, 46, 54 and the `classonly timelineserver:` rules are unused in several runs |
| G13 mixed client/server | still seen: no such run |

Its T26-T38, one by one:

- T26 (downstream compile/run): not implemented; `downstream-compare.md` has
  resolution only.
- T27 (which duplicate wins): not implemented; no winner or API comparison in
  `downstream-compare.md`.
- T28 (exclusion scenarios): not implemented; no `downstream-exclusion-*`.
- T29 (more scenarios): not implemented; the four R49 scenarios only.
- T30 (where removed classes come from): not implemented; no `class-gone`.
- T31 (SPI integrity): not implemented; HADOOP-20014 changes service files and
  no check reads them.
- T32 (audience of shaded changes): not implemented; `impact.md` gives counts.
- T33 (Hadoop API exposing the replaced jar): not implemented; no Hadoop-jar
  API finding.
- T34 (modules from check 1 in check 4): not implemented; the unit tables are
  R42's lists.
- T35 (coverage floor): not implemented; `compare_e2e.py:268` still ignores
  `both_fail` in the verdict.
- T36 (tests failing only on the candidate across runs): partly: R85's history
  is present, the never-failed-on-baseline and changed-class logic is not.
- T37 (rules limited to architectures): not implemented; no `@arch=`.
- T38 (mixed client/server): not implemented; no such run.

The 2026-11-02 00:12 and 15:36 requirements reviews:

- R54 ancestry verdict: no longer seen; `ancestry.md` is PASS in every run.
- R41 whitespace-only observations: no longer seen; `compare_e2e.py:79-85`
  counts non-blank lines.
- R40 threshold wording: no longer seen; the requirement says "at least 6
  more".
- R63 broad rules: still seen; `e2e/expected-e2e-differences.txt:46` is still
  `obsfield [a-z0-9:-]+/headers/vary` with no ticket, and the `classjar` rule
  does not name the destination jar.
- R78-R80 never in CI: no longer seen; `ancestry.md` and `compare-plan.md`
  are PASS in simple-run-20 (and the report's first two checks are PASS in
  every run).
- Maven exit code, the late ancestry check and plan coverage: not rechecked
  from these reports.
- Scenarios that die early: R82 now records them, but the runs show a harness
  bug (G1) rather than a scenario bug.
- Self-checks: still only `simple` has A/A and broken runs.
- Check 4 has no allowlist for a one-sided flake: still open; no such test in
  these runs.
- T1, T2, T4, T13 and T18: open or not rechecked; no implementation evidence
  in these reports.
- T3 as R87, T7 with T21 as the rule files, T8 as R84, T10 as R87, T11 as
  R85, T12 as R90, T14 as R95, T15 as R91, T17 as R89, T19 as R94, T20 as
  R83, T22 as R93, T23 as R92, T24 as the rule wording, and T25 as R86. The
  runs show defects in R90, R93 and R95 (G5, G8, G3); R84 works
  (`mapreduce-jobs:control-job` MATCH); R88's checks do not compare anything
  (G7).

## What this review did not cover

- No build, test, cluster run or download; only the reports in `.review/`.
- The 1,593 artifact differences, the 975 class-jar moves and the class-load
  tables were summarised by scripts, not read row by row; the unexpected rows,
  the POM sections and the license entries were read.
- The raw `observations.jsonl` files and the daemon logs are not in the inputs,
  so the probe values behind `/body/json/mapping/match` and the exact
  `classload-*.log` lines were not seen; the conclusions rest on the
  comparator and the report.
- The attribution tree job logs were not read beyond `gh run view
  41574971687`; the cause of `prefix-5` is the runner's "No space left on
  device".
- The earlier reviews' requirement-by-requirement statuses were not all
  rechecked; the items above are the ones these runs can settle.
- No file is marked `[!]`.
