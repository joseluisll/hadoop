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

# Harness runs review: first runs after the 2026-11-03 fixes, 2026-11-04 10:44

This review reads the latest report of each architecture, the A/A run, the
two broken-candidate runs and the second attribution run against
`HARNESS-REQUIREMENTS.md` on `feat/HARNESS` at `4c8d4b2094f`. It is a
snapshot: no harness code, requirement or allowlist rule was changed for it,
and nothing outside `.review/` was edited. The proposals continue the TO-BE
numbering at T51.

## Runs reviewed

- Baseline: `4f4422ad703` (`origin/PREPARATION`).
- Candidate: `4c8d4b2094f`: the baseline plus `HADOOP-20012-upstream` to
  `HADOOP-20016-upstream` and `jetty-phase-a` (HADOOP-19970), and the harness
  fixes of `a11cd8d4453` (T39-T44 first part, T47) and `4c8d4b2094f` (T44
  second part, T45, T46, T48, T49, R63/R67, the HADOOP-20014 LICENSE rule).

`artifact-diff.json` is byte-identical in all five architecture runs (md5
`b2d8c622`) and `api-compat.json` too (`3c06dad4`), so checks 1 and 2 are one
result each. `downstream-compare.json` exists only in `simple` (`586c2b29`),
as R52 says. The five runs therefore share one candidate build. The report
says the candidate build was reused from `93165486a76`; the build key
excludes the harness (R73), so the distribution is the same code, and the
harness that ran is `4c8d4b2094f`.

| Run | Overall | End to end (match / diff / both fail) | Unit tests |
|---|---|---|---|
| [simple-run-21](https://github.com/joseluisll/hadoop/actions/runs/41744301944) | FAIL | 984 / 11 / 0 | PASS, 1 flaky, 13 candidate-only tests pass |
| [secure-run-13](https://github.com/joseluisll/hadoop/actions/runs/41744302460) | FAIL | 628 / 10 / 0 | PASS, no flaky |
| [ha-run-9](https://github.com/joseluisll/hadoop/actions/runs/41744301942) | FAIL | 623 / 9 / 0 | PASS, no flaky |
| [mixed-run-10](https://github.com/joseluisll/hadoop/actions/runs/41744302407) | FAIL | 591 / 9 / 0 | PASS, no flaky |
| [federated-run-11](https://github.com/joseluisll/hadoop/actions/runs/41744303166) | FAIL | 489 / 9 / 14 | FAIL, 1 regression, 1 flaky |
| [simple-run-aa-10](https://github.com/joseluisll/hadoop/actions/runs/41744302648) | PASS | 992 / 3 / 0 | PASS, no flaky |
| [broken-webhdfs-user-9](https://github.com/joseluisll/hadoop/actions/runs/41744303303) | FAIL, harness check PASS | 918 / 25 / 0, 50 regressions, 2 missing | NOT RUN |
| [broken-static-7](https://github.com/joseluisll/hadoop/actions/runs/41744303070) | FAIL, harness check PASS | caught | NOT RUN |
| [attribution-run-2](https://github.com/joseluisll/hadoop/actions/runs/41744303173) | PASS | 10 trees | — |

## What the runs show

### Impact that is reported

The accepted differences are the same as the 2026-11-03 batch, and the
digest's counts are unchanged: 1,593 artifact differences, 0 unexpected; 11
API findings, 9 blocking, 0 unexpected; 248 downstream differences, 0
unexpected (`artifact-diff.json`, `api-compat.json`,
`downstream-compare.json`, simple-run-21).

- **HADOOP-19970 is the user-visible change.** 474 classes move from
  `javax.servlet-api-3.1.0.jar` and 36 from `jakarta.servlet-api-4.0.4.jar`
  to `jetty-servlet-api-4.0.9.jar` (`impact.md`, "Daemons and applications").
  The 9 blocking API findings are 2 `jar-module-name-changed` and 7
  `api-abstract-method-added` on `javax.servlet.ServletContext`
  (`api-compat.md`, "Accepted impacts"). The replaced jar adds 5 public types
  and 22 public members (`api-compat.md`, "API a replaced jar makes
  available").
- **The downstream effect is reported and accepted.** 248 differences in 56
  projects, 0 unexpected; six projects gain a `javax.servlet` duplicate set
  (`downstream-compare.md`; `impact.md`, "Maven projects").
- **The two HADOOP-20014 `license-entry-stale` entries are still there, now
  accepted.** `artifact-diff.json` lists
  `org.glassfish.jersey.containers:jersey-container-jdk-http:2.46` and
  `org.glassfish.jersey.test-framework.providers:jersey-test-framework-provider-jdk-http:2.46`
  as `EXPECTED`, by the rule at `expected-differences.txt:79`. The 2026-11-03
  review's "two license entries are genuinely wrong" is therefore no longer a
  failing difference, but the entries themselves remain until T50 makes the
  LICENSE check count bundled jars.
- **The broken candidates were caught.** `broken-webhdfs-user-9` fails with
  50 regressions in `hdfs-webhdfs` and elsewhere; `broken-static-7` removes
  `hadoop.css`. Both say "Harness check: **PASS**" and skip the unit suites
  (R69).
- **The attribution run is complete.** `attribution.json` has the 10 expected
  trees (`prefix-2` to `prefix-5`, `ticket-1` to `ticket-6`), all PASS.
  `ticket-6` (HADOOP-19970) lists one interaction,
  `artifact-diff: UNEXPECTED pom-dependency-changed org.apache.hadoop:hadoop-yarn-common|org.glassfish.jersey.test-framework.providers:jersey-test-framework-provider-jetty`,
  as T48 says it should.

### Noise and flakes

- **The 2026-11-03 defects are gone.** No `scenario:*.completed` is
  BOTH_FAIL in any run; `new_log_errors` is 0 in every run; no `job.jar` move
  appears in the class-load tables; the `classjar javax.activation` rule
  matched nothing (replay over the five runs). T42, T43 and T44's two parts
  did what they were meant to.
- **The A/A run passes for the first time.** `simple-run-aa-10` is
  `Overall: **PASS**` and `Harness check: **PASS**` (`report.md:11-13`). Its
  three expected DIFFs are `mapreduce-am:am-job-counters`,
  `yarn-rm-web:yarn-css` and `yarn-rm-web:yarn-dt-js`
  (`e2e-compare-simple.md`, "Expected differences").
- **The A/A run still has 15 unexpected one-side classes.** `report.md`
  "Classes loaded on one side only (15: 0 accepted, 15 would fail with
  CLASSONLY_FAIL=true)": `kms` baseline `ValueQueue$3`, `mr-am` candidate
  `DefaultSpeculator$TaskAttemptHistoryStatistics`, four `nodemanager` netty
  classes, one `resourcemanager` baseline Jackson class, four
  `resourcemanager` candidate `org.eclipse.jetty.http.*` classes and four
  `router` candidate Jackson classes. T46's condition ("zero unexpected
  one-side classes") is therefore not met, and the A/A gate passes only
  because `CLASSONLY_FAIL=false`.
- **The normal runs' one-side class noise is larger.** simple 9, secure 14,
  ha 31, mixed 14, federated 5 unexpected one-side classes
  (`report.md`, "Classes loaded on one side only" in each run). Most are
  timing: `jn2`/`jn3` checkpoint classes, `nn2` proto classes,
  `historyserver` retry classes, `mr-am` `DefaultSpeculator`, `rm1`
  `ActiveStandbyElector$8`, and the secure `map` container's `SleepJob`
  classes (R84's jobs now run).
- **The timeline-server and `Vary` rules are architecture-specific.** Replay
  over the five runs: `obsfield .../headers/vary` matched only in `simple`;
  `obsfield mapreduce-am:am-job-counters/...` and the ten
  `classonly timelineserver:` rules matched only in `secure`; the
  `obsdiff yarn-timeline:` rule and the `classjar javax.activation` rule
  matched nothing. R59 reports them as unused in the other architectures
  (T37).
- **Federated's 14 `fed-yarn` BOTH_FAIL observations are unchanged**
  (`report.md`, "Failing on both sides (14)"): the router listing omits the
  directly submitted application on both sides (YARN-12024, YARN-12025, T49).
- **Federated's unit regression is a known flake on both sides.**
  `TestFederationInterceptor#testRecoverWithoutAMRMProxyHA` is pass on the
  baseline and fail on the candidate (`unit-compare.json`, `regressions`),
  and its history is 3 baseline / 2 candidate failures in 5 runs
  (`unit-compare.json`, `history`). The only change to
  `FederationInterceptor` is `ConcurrentHashSet` to
  `ConcurrentHashMap.newKeySet()` (`git diff 4f4422ad703 4c8d4b2094f --
  .../FederationInterceptor.java`), which is equivalent. `README.md` lists
  only `testSubClusterTimeOut` as the known flake, not this test.

### What the runs do not verify

- **The probe's actual answers.** `probe:probe-base` is the only blocking
  end-to-end difference in every architecture, and the report's `detail`
  shows only the first differing field, `/body/json/http_servlet_jar:
  "javax.servlet-api-3.1.0.jar" vs "jetty-servlet-api-4.0.9.jar"`
  (`report.md`, "Unexpected differences (1)"). The `fields` list in
  `e2e-compare-simple.json` names six paths, including
  `/body/json/mapping/match`, `match_value`, `pattern`, `servlet_name` and
  `new_push_builder`, but the report gives none of their values.
- **The baseline's mapping values are a probe defect, not behaviour.** The
  raw observations show the baseline's `mapping` fields all
  `"error:IllegalArgumentException"` and `new_push_builder: "absent"`; the
  candidate's `match: null`, `match_value`/`pattern`/`servlet_name` `""` and
  `new_push_builder: "null"`; both report `servlet_api` 3.1
  (`simple-run-21-baseline-observations.jsonl`,
  `simple-run-21-candidate-observations.jsonl`, `probe-base`). The cause is
  in `ServletProbe.java`: `reflect()` returns the string `"absent"` when
  `getHttpServletMapping` is missing (`:135-147`), and `mappingJson()` only
  checks for `null` before `Class.forName("javax.servlet.http.HttpServletMapping")`
  and reflecting on that string (`:114-129`), which throws
  `IllegalArgumentException`. The candidate's empty values are consistent
  with the Servlet 4.0 default method's empty mapping, which Jetty 9.4's
  request does not override. The real difference is "method absent" vs
  "default empty mapping", not the error values.
- **Which class path provides the interface on the baseline is not
  identified.** The probe runs with
  `-cp ${RUN}:${DIST}/etc/hadoop:${DIST}/share/hadoop/common/*:${DIST}/share/hadoop/common/lib/*`
  (`10-web-common.sh:94`). The baseline's `share/hadoop/common/lib` holds
  `javax.servlet-api-3.1.0.jar` and `jakarta.servlet-api-4.0.4.jar`
  (`artifact-diff.json`, `dist-file-removed`), and neither coordinate
  provides `javax.servlet.http.HttpServletMapping`. The report does not
  record the probe JVM's class path or the jar the interface came from, so
  the source is not identified from the inputs.
- **Push support is never reported.** `push_supported` is `"absent"` on both
  sides in every run, and `isPushSupported` is not in the API-added list
  (`api-compat.md`, "API a replaced jar makes available"), so the probe's
  push-support field reports nothing.
- **The downstream duplicate winner and a compile/run are still not
  checked.** `downstream-compare.md` reports the six new duplicate sets but
  not which copy Maven puts first, and no project is compiled or run
  (T26/T27, still open).
- **The A/A and broken-candidate self-checks run only in `simple`.** The
  other four architectures' noise and breakage detection are not gated.

## Gaps

| # | Seen in | What the run shows | Why it can be missed |
|---|---|---|---|
| G1 | all five architecture runs | `probe:probe-base` is the only blocking DIFF; its `detail` shows only `/body/json/http_servlet_jar`, while `fields` names six paths (`report.md`, "Unexpected differences (1)"; `e2e-compare-simple.json`, `rows`) | `compare_e2e.py:109-131` returns only the first differing path, and `write_markdown` (`:335-337`) writes only `detail`; the other paths are in the JSON without values |
| G2 | simple-run-21 | baseline `mapping` fields are `"error:IllegalArgumentException"`, candidate's are an empty mapping (`probe-base` observations) | `ServletProbe.java:114-129` reflects on the `"absent"` sentinel; no probe self-test covers the missing-method case |
| G3 | simple-run-aa-10 | A/A PASS with 15 unexpected one-side classes (`report.md`, "Classes loaded on one side only (15: 0 accepted, 15 would fail)") | `report.py:124-129` gates only the check verdicts; `CLASSONLY_FAIL=false` keeps the classes non-blocking (T46) |
| G4 | federated-run-11 | `TestFederationInterceptor#testRecoverWithoutAMRMProxyHA` pass to fail; history 3/2 in 5 (`unit-compare.json`) | `README.md` lists only `testSubClusterTimeOut`; R45 cannot accept a regression, so the run stays FAIL |
| G5 | all five | the `Vary` rule matched only in `simple`, the counters and timeline-server rules only in `secure`, two rules matched nothing (replay) | R59 reports them as unused in the other architectures; no `@arch=` (T37) |
| G6 | all five | `push_supported` is `"absent"` on both sides (`probe-base` observations) | `isPushSupported` is not in the 4.0 API the probe compiles against; R93 still names it |
| G7 | all five | the two HADOOP-20014 `license-entry-stale` entries are `EXPECTED` (`artifact-diff.json`) | the LICENSE check cannot see jars bundled in the shaded clients (T50) |
| G8 | simple-run-21 | six downstream projects gain a `javax.servlet` duplicate set, no winner or compile/run (`downstream-compare.md`; `impact.md`) | R51 reports the set, not which copy loads; T26/T27 still open |
| G9 | all five | the A/A and broken-candidate runs exist only for `simple` | the other architectures' noise and breakage detection are not gated |

## Proposed TO-BE items

### Probe and report

- **T51. Fix the probe's absent-mapping sentinel.** In
  `ServletProbe.mappingJson()`, return `"absent"` when the value is the
  `"absent"` string (or check `instanceof String`) before `Class.forName`,
  so a missing `getHttpServletMapping` is reported as absent instead of
  `error:IllegalArgumentException`. Add a probe self-test that runs the
  probe against a 3.1 classpath and asserts `mapping: "absent"`. The DIFF
  remains (absent vs an empty mapping), but it becomes readable.
  Extends R93. *Source: G2; simple-run-21.*

- **T52. Show every differing field's values in the report.** When a DIFF
  has more than one differing path, write each path with both sides' values
  (masked) in the report, not only the first. The `fields` list is already
  in `e2e-compare-<arch>.json`; add the values there and in the markdown.
  Extends R35 and R37. *Source: G1; all five runs.*

- **T53. Check push support with the API that exists.** `isPushSupported`
  is not in the 4.0 API the probe compiles against, so `push_supported` is
  always `"absent"`. Either remove the field or report whether
  `newPushBuilder()` returns a `PushBuilder` (the candidate's `"null"` is
  the default). Extends R93. *Source: G6; all five runs.*

### Verdict and coverage

- **T54. Gate the A/A run on one-side class noise, or record its noise
  set.** The A/A run passes with 15 unexpected one-side classes, so T46's
  condition is not met and the gate does not cover the class-load noise.
  Either make the A/A gate require zero unexpected one-side classes, or
  record the A/A run's set as the noise budget and fail only on classes
  outside it. Changes a verdict: needs the owner's decision. Extends R68,
  R87 and T46. *Source: G3; simple-run-aa-10.*

- **T55. Document `testRecoverWithoutAMRMProxyHA` as a known flake.** Its
  history is 3 baseline / 2 candidate failures in 5 runs, and the only
  change to `FederationInterceptor` is equivalent. Add it to `README.md`'s
  known issues and R77's list, as `testSubClusterTimeOut` already is, or
  fix the test. Extends R77. *Source: G4; federated-run-11.*

- **T56. Run the A/A and broken-candidate self-checks for every
  architecture.** The A/A gate and the broken-candidate check exist only in
  `simple`, so the other four architectures' noise and breakage detection
  are not gated. Add one A/A run and one broken run per architecture, or at
  least record each architecture's A/A noise set. Extends R68 and R69.
  *Source: G9; the batch.*

- **T37 (2026-11-02 runs review, not yet adopted). Mark architecture-specific rules.** The `Vary`, job-counter and
  timeline-server rules match in one architecture only, and two rules match
  nowhere. Let a rule end with `@arch=<arch>[,...]` so R59 reports "matched
  nothing" only for the architectures it names. Changes the allowlist
  format: needs the owner's decision and a replay. Extends R61 and R59.
  *Source: G5; replay over the five runs.*

### Client and downstream impact

- **T26 and T27 (2026-11-02 runs review, not yet adopted). Which duplicate wins, and whether it compiles and runs.** This is
  the 2026-11-02 review's T27 and T26, still open: the six new
  `javax.servlet` duplicate sets are reported, but not which copy Maven
  puts first, and no downstream project is compiled or run. In
  `own-javax-servlet` the project's own 3.1.0 may win over the 4.0.9 jar;
  harmless on Jetty 9.4, a `NoSuchMethodError` in phase B. Extends R51 and
  R57. *Source: G8; simple-run-21.*

## Proposed order

1. **T51, T52, T53.** Small probe and report fixes; they make the only
   blocking difference readable and remove a dead field. No owner decision.
2. **T55.** A documentation fix; it stops a known flake from looking like a
   regression.
3. **T54 and T37** (owner decisions), then **T56** (more self-check runs).
4. **T26 and T27**, which is the largest and the one that matters most
   before phase B.

## Decisions needed from the owner

- **T54:** may the A/A gate require zero unexpected one-side classes, or
  should the A/A run's set become the noise budget?
- **T37:** may the allowlist format gain `@arch=`?
- **The probe difference:** after T51, the DIFF is "method absent" vs an
  empty mapping. Does it need a narrow `obsfield` rule, or a sentence in
  HADOOP-19970's release note? (The brief's claim 7; propose, do not
  decide.)
- **T55:** is `testRecoverWithoutAMRMProxyHA` accepted as a known flake, or
  should it be investigated before the next batch?

## Earlier reviews

The 2026-11-03 21:38 runs review proposed G1-G10 and T39-T49:

| Item | Status with this review's evidence |
|---|---|
| G1 scenario marker | no longer seen: no `scenario:*.completed` BOTH_FAIL in any run |
| G2 log errors | no longer seen: `new_log_errors` 0 in every run |
| G3 `job.jar` moves | no longer seen: no `job.jar` move in the class-load tables |
| G4 activation moves | no longer seen: the `classjar javax.activation` rule matched nothing |
| G5 probe types | partly: values are recorded (T39), but the probe defect (G2) and the report detail (G1) remain |
| G6 attribution missing tree | no longer seen: 10 trees, all PASS |
| G7 federated listing | still seen: 14 `fed-yarn` BOTH_FAIL (T49 decided, R88 stays) |
| G8 POM determinism/version | no longer seen: `artifact-diff.json` md5 identical in all five runs; details carry `version=` and sorted exclusions |
| G9 one-side classes | still seen: A/A 15 unexpected, normal runs 5-31 |
| G10 attribution rules | no longer seen: `ticket-6` interaction listed, no failure |

Its T39-T49: T39 done (values recorded); T40 and T41 done (version and
sorted exclusions); T42 done (no false early end); T43 done (0 log errors);
T44 both parts done (no `job.jar` or activation moves); T45 done (A/A gate
line); T46 decided (switch off, and the A/A still has 15); T47 done (10
trees); T48 done (retag and interaction); T49 decided (R88 stays).

The 2026-11-03 21:58 requirements review's partly-met items, at this commit:

- R39, R82, R38, R90, R93: the defects it reproduced are fixed (T43, T42,
  T44, T40/T41, T39). R93 is still partly met because of the probe defect
  (G2) and the dead push field (G6).
- R88: still partly met (T49, 14 BOTH_FAIL).
- R87: still partly met (`CLASSONLY_FAIL=false`, A/A 15).
- R63/R67: the `Vary` and job-counter rules now say "no issue filed;
  announced: no", but the `Vary` rule still names no ticket (it is
  pre-existing, so there is none to name).
- R54 (broken run exits 0 with overall FAIL), R56 (Impact after the verdict
  table), R57 (existing duplicate), R14 (removed class), R30 (CORS), R34
  (masking), R37 (FIXED/candidate-only not listed), R42 (test lists), R52
  (one side NOT RUN), R70 (per-job `PREPARATION`), R76 (`PR_BRANCHES`
  default), R78 (whole-blob match): not rechecked by these runs; the code
  is unchanged, so they stand as the requirements review found them.

The 2026-11-02 10:30 runs review's G1-G13 and T26-T38 are all still open:
no downstream compile/run (T26), no duplicate winner (T27), no exclusion
scenario (T28), only the four R49 scenarios (T29), no `class-gone` (T30),
no SPI check (T31), counts only for shaded changes (T32), no Hadoop-jar API
finding (T33), fixed unit lists (T34), `both_fail` ignored in the verdict
(T35), history present but not the never-failed logic (T36), no `@arch=`
(T37), no mixed-version run (T38). The latest runs show the same six new
duplicate sets and the same 14 federated BOTH_FAIL, so G1, G5, G10 and G13
are still seen; the rest are not rechecked.

## What this review did not cover

- No build, test, cluster run or download; only the reports in `.review/`.
- The 1,593 artifact differences, the class-jar moves and the class-load
  tables were summarised by scripts, not read row by row; the unexpected
  rows, the POM details and the license entries were read.
- The probe JVM's class path and the jar that provides
  `javax.servlet.http.HttpServletMapping` on the baseline are not in the
  reports, so the source of the interface is not identified (G2).
- The `e2e-compare-<arch>.md` files for secure, ha, mixed and federated
  were read through the identical sections embedded in each `report.md`,
  not as separate files; the A/A and broken `e2e-compare-simple.md` were
  read directly.
- The earlier reviews' requirement-by-requirement statuses were not all
  rechecked; the items above are the ones these runs can settle.
- No file on the checklist is marked `[!]`.

Checked afterwards by the session that briefed this review: two proposals,
first numbered T57 and T58, restated the 2026-11-02 runs review's T37 and
T26/T27, which were never adopted; they keep those numbers here, so this
review's new items are T51 to T56.
