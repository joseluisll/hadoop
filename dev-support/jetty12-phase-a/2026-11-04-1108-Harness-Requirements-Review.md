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

# Harness requirements review, 2026-11-04 11:08

This review checks `HARNESS-REQUIREMENTS.md` (R1-R95, the extensions T39-T48,
and the TO-BE items) against the code on `feat/HARNESS` at commit
`663408c0d70`, and reads `README.md`, `JETTY12-MIGRATION-PLAN.md`, `AGENTS.md`
and the 2026-11-04 10:44 runs review. Paths are relative to
`dev-support/jetty12-phase-a/` unless they start with `.github/`. It is a
snapshot: no harness code, requirement or allowlist rule was changed for it,
and nothing outside `.review/` was edited. The two self-tests were run and
pass; no build, cluster or CI job was run.

## Verdict

The harness implements almost all of what the document says, and the fixes of
the 2026-11-03 batch (T39-T48) are real code: the scenario marker, the
class-load scan, the per-run jar paths, the POM version and exclusions, the
probe values, the A/A gate and the attribution trees all behave as their
extensions say. The 2026-11-04 batch confirms that: the A/A run, both broken
candidate runs and the attribution run pass, and every architecture fails only
on `probe:probe-base` (federated also on one unit regression). That single
blocking difference is a probe defect, not a patch difference: `mappingJson()`
reflects on the `"absent"` sentinel, so the baseline's mapping values are
`error:IllegalArgumentException` instead of `"absent"`, and the report shows
only the first of six differing paths. Twelve requirements are partly met,
mostly because the text claims more than the code does; none is not met.

| AS-IS result | Count | Requirements |
|---|---|---|
| Met | 80 | All others |
| Partly met | 12 | R14, R24, R30, R42, R52, R54, R56, R63, R70, R78, R88, R93 |
| Not met | 0 | — |
| Not checkable (process rule or principle) | 3 | R3, R65, R66 |

"Reproduced" means the harness's own code was run on synthetic inputs in
`.review/scratch/` or its self-tests were run; the command and output are in
the finding. "From reading" means the conclusion comes from the code at this
commit. CI evidence is the 2026-11-04 10:44 runs review's tables, which this
review checked against the code.

## Requirements

| Req | Status | Evidence |
|---|---|---|
| R1 | Met | `lib/common.sh:29-30` (two refs), `compare.sh:70-111`; both sides built and compared. |
| R2 | Met | Only a rule accepts a difference (`artifact_diff.py:501-511`, `api_compat.py:398-407`, `compare_e2e.py:212-224`, `compare_unit.py:141-156`); the text's own exceptions (FIXED, BOTH_FAIL, candidate-only, one-side classes) are the ones the code lists without failing (`compare_e2e.py:257-268`). |
| R3 | Not checkable | A goal, not a behaviour. |
| R4 | Met | `compare.sh` runs the same scripts for both sides; `e2e/run.sh` and `unit-tests.sh` take the side as an argument. |
| R5 | Met | `build.sh:46-73` (worktree, `dist`/`install`). |
| R6 | Met | `build.sh:75-103` (`dependency:list`, MiniKdc and timeline test jar staged). |
| R7 | Met | `build.sh:69-70` (`-Pnative -Drequire.openssl -Drequire.snappy`). |
| R8 | Met | `artifact_diff.py:519-547`. |
| R9 | Met | `artifact_diff.py:87-110` (nested jar checksum), `:534-546`. |
| R10 | Met | `artifact_diff.py:56-64,82` (volatile entries and files, symlinks skipped). |
| R11 | Met | `artifact-diff.sh:36-64` (all seven views), `artifact_diff.py:549-566`. |
| R12 | Met | `artifact_diff.py:568-575` (test vs runtime by scope). |
| R13 | Met | `artifact-diff.sh:22-23,66-67`; CI runs it on every fresh build (`tmpl:248-251`). |
| R14 | Partly | `api_compat.py:325-355` compares changed classes, but a public class removed outright has no pair and gets no API finding. |
| R15 | Met | `api_compat.py:75-84,220-277` (all eleven kinds). |
| R16 | Met | `api_compat.py:82,268-276`. |
| R17 | Met | `classfile.py:177-204`, `api_compat.py:413-420`. |
| R18 | Met | `api_compat.py:421-425`. |
| R19 | Met | `api_compat.py:398,440-445` (relocated/private-audience are INFO). |
| R20 | Met | `api_compat.py:386-409` (file-name subject, dedupe with locations). |
| R21 | Met | Documented out of scope; checks 3 and 4 cover behaviour. |
| R22 | Met | `e2e/run.sh:41-133`, `e2e/cluster.sh`. |
| R23 | Met | `e2e/arch/{simple,secure,ha,federated,mixed}.sh` as described. |
| R24 | Partly | Per-instance pid/log (`cluster.sh:62-66`) and per-instance conf for multi-instance daemons (`ha.sh:48-59`, `mixed.sh:54-68`, `federated.sh:57-67`); single-instance daemons share `${HADOOP_CONF_DIR}` (`simple.sh:28-42`, `secure.sh:52-59`), so "every instance has its own configuration directory" is not literal. `start` wipes state (`cluster.sh:137-140`). |
| R25 | Met | Scenarios 00-90 read; each covers the listed area. |
| R26 | Met | `cluster.sh:74-134` (fail fast, `daemons.txt`), `run.sh:58-64` (`aborted.txt`, logs still collected). |
| R27 | Met | `run.sh:38`; `test_probe.py` passes. |
| R28 | Met | `probe.py:647-650`; five types (`:583`). |
| R29 | Met | `probe.py:390-421` (method, status, reason, error, headers, cookies, location, body, error_text). |
| R30 | Partly | `probe.py:65-72` compares three CORS headers; `access-control-allow-credentials`, `-expose-headers` and `-max-age` are name-only. |
| R31 | Met | `probe.py:433-472`. |
| R32 | Met | `probe.py:524-554`. |
| R33 | Met | `probe.py:557-577`. |
| R34 | Met | `probe.py:91-121` masks the listed values in every recorded field; `classload.py:47-59` masks the side and per-run ids in jar paths. |
| R35 | Met | `compare_e2e.py:109-147` (whole view, stack lines dropped). |
| R36 | Met | `compare_e2e.py:200-211`. |
| R37 | Met | `compare_e2e.py:257-268` fails on the four stated cases; FIXED and candidate-only MISSING are counted only, BOTH_FAIL is listed separately (`:272,361-368`), as the text says. |
| R38 | Met | `classload.py:108-126`, `compare_e2e.py:226-234`; a different jar fails unless a `classjar` rule matches. |
| R39 | Met | `logscan.py:35-42,69-74` (class-load logs skipped, T43). |
| R40 | Met | `compare_e2e.py:158` (`nb == 0 or n > max(2*nb, nb+5)` = "at least 6 more"). |
| R41 | Met | `compare_e2e.py:79-85,179-193` (non-blank lines; baseline aborted NOT RUN, candidate aborted FAIL). |
| R42 | Partly | `unit-tests.sh:70-141` has the suites, but `quick` runs whole modules for entries with an empty test list (`:157-163`), not only the web and Jersey tests. |
| R43 | Met | `unit-tests.sh:153-156`. |
| R44 | Met | `compare_unit.py:52-81` (pass/flaky/fail/skipped, unparseable = fail). |
| R45 | Met | `compare_unit.py:134-195`. |
| R46 | Met | `compare_unit.py:147-150,194-195` (listed, not failing). |
| R47 | Met | `unit-tests.sh:166-171`, `lib/stall-watch.sh:93-111`. |
| R48 | Met | `downstream-deps.sh:64-70` (the 14 artifacts). |
| R49 | Met | `downstream-deps.sh:54-62` (four scenarios, defaults as stated). |
| R50 | Met | `compare_downstream.py:52-65,111-117`. |
| R51 | Met | `downstream_classes.py:58-82`, `compare_downstream.py:118-123`. |
| R52 | Partly | Neither side: no section (`compare_downstream.py:91-93`). One side: verdict NOT RUN (`:95-100`), not FAIL as the text says; the run still exits non-zero. |
| R53 | Met | `compare.sh:45-51` (delete first), `:70-111`; `report.py:93-162`. |
| R54 | Partly | `report.py:116-117` gives PASS/INCOMPLETE/FAIL, but `report.py:164-166` returns 0 when a broken-candidate harness check passes although the overall verdict is FAIL (R69). |
| R55 | Met | `report.py:55-79,131-135`. |
| R56 | Partly | `impact.py:79-192` builds the three audiences, but `report.py:151-156` writes it after the verdict table, not at the start. |
| R57 | Met | `impact.py:180-191` lists projects that had no duplicate in the packages that now have one. |
| R58 | Met | `impact.py:194-208`. |
| R59 | Met | `artifact_diff.py:592-593,618-623`, `api_compat.py:449,543-544`, `compare_e2e.py:284-285,411-414`, `compare_unit.py:207,256-258`, `compare_downstream.py:136,179-183`. |
| R60 | Met | Five rule files; check 4 accepts only `candidate-only-fail` (`compare_unit.py:120,151-156`). |
| R61 | Met | `allowlist.py:31,48-53` (whole-subject match, `#` rule). |
| R62 | Met | `compare_e2e.py:212-224,231,247`; `e2e/expected-e2e-differences.txt:19-26`. |
| R63 | Partly | Every patch rule names a ticket, but the pre-existing rules name none (`e2e/expected-e2e-differences.txt:46,54,65`); R67 is the exception that allows it. Patterns are narrow. |
| R64 | Met | `api_compat.py:468-471`, `impact.py:48-51`; the rule files carry `announced:` for every user-visible change. |
| R65 | Not checkable | A process rule. |
| R66 | Not checkable | A process rule; the tool exists (`replay.sh`). |
| R67 | Met | `e2e/expected-e2e-differences.txt:46,54,65` say pre-existing and "no issue filed"; `:71-80` name YARN-12030. |
| R68 | Met | The A/A run is set up (`tmpl:100`), and `simple-run-aa-10` is PASS (runs review). T45's gate line is written (`report.py:122-144`). |
| R69 | Met | `report.py:82-90,118-121,164-166`; `tmpl:332` skips the unit jobs; self-tests cover the four outcomes. |
| R70 | Partly | One workflow per architecture and the run-name patterns are right, but each job resolves `PREPARATION` separately (`tmpl:99`, setup action `:50-65`), so a baseline that moves mid-run is checked against a different commit than the one built. |
| R71 | Met | `ci/wait-turn.sh:65-110`; `tmpl:110-193` (queue and queue-2, 340 minutes each). |
| R72 | Met | `tmpl:195-214` (native build image, `BUILD_SRC_DIR`), other jobs on `ubuntu-24.04`. |
| R73 | Met | `ci/build-key.sh:36-49`, `ci/find-build.sh`; retention 7/14/30 days (`tmpl:264,325,478`). |
| R74 | Met | `jetty12_phase_a_simple.yml:78,81` (four shards, tier full). |
| R75 | Met | `tmpl:458-478` (900 KB summary, full artifact). |
| R76 | Met | `run-all.sh:36-52` runs every step; `README.md:599` gives `PR_BRANCHES` the default "none". |
| R77 | Met | `README.md:245-398` documents the unexercised areas and the known both-side failures. |
| R78 | Partly | `ancestry.py:55-75` checks every baseline commit's change, but "counts as contained" needs the whole blob to match (`:66`), so a cherry-pick onto a file the patch also changes is reported missing. The queue job runs it before the wait (`tmpl:137-150`). |
| R79 | Met | `compare_plan.py:195-290` (deleted file, binary, landed, order); `PR_BRANCHES` set at `tmpl:105`; skipped when the sides are one commit (`common.sh:94-100`). |
| R80 | Met | `replay.py:154-201`, `replay.sh`; the `NEW_KINDS` exception (`:133,186-188`) is documented in `README.md:578-585`. |
| R81 | Met | `test_comparators.py` (run: all cases pass); `compare.sh:56`, `run-all.sh:34`, `tmpl:131-133`. |
| R82 | Met | `run.sh:65-95` records the marker; `env.sh:252-261` carries it in `SCENARIO_DONE_FILE` (T42). |
| R83 | Met | `compare_unit.py:151-156,193-195`. |
| R84 | Met | `50-mapreduce.sh:42-45,71-73`; CI `mapreduce-jobs:control-job` MATCH (runs review). |
| R85 | Met | `compare_unit.py:95-108,171-187`, `ci/history.sh`, `compare.sh:92-101`. |
| R86 | Met | `ha.sh:112`, `mixed.sh:81`, `federated.sh:100`. |
| R87 | Met | `compare_e2e.py:239-252,266-267`; `tmpl:456` sets `CLASSONLY_FAIL: "false"`; the rules cover the timeline server and the Servlet 4.0 types (`e2e/expected-e2e-differences.txt:71-86`). The A/A run's 15 unexpected one-side classes are a gap (T54), not a violation of this text. |
| R88 | Partly | `85-federation.sh:139-171` submits directly and defines the five checks, but in `federated-run-11` the router listing omits the application, so the three listing checks are BOTH_FAIL and the two reads by id are never compared (runs review, T49). |
| R89 | Met | `attribution.sh:65-72,90-133`, `attribution.py:52-58,95-140,180-183`, `jetty12_phase_a_attribution.yml:171-226` (one job per tree). T47 and T48 are in `attribution.py:52-58,95-140`. |
| R90 | Met | `artifact_diff.py:277-320` (scope, optional, declared version, type/classifier, exclusions, managed versions, parent, `pom-unparseable`); T40 at `:191-192`, T41 at `:214-221`. |
| R91 | Met | `artifact_diff.py:325-484`; the two HADOOP-20014 entries are accepted by `expected-differences.txt:79` until T50. |
| R92 | Met | `api_compat.py:287-302,357-381,520-531`, `impact.py:113-119`. |
| R93 | Partly | `ServletProbe.java:114-129` reflects on the `"absent"` sentinel, so a missing `getHttpServletMapping` is reported as `error:IllegalArgumentException`, not `"absent"` (G2); `push_supported` is always `"absent"` (G6). The scenario starts it and sends raw HTTP/1.0 and HTTP/1.1 (`10-web-common.sh:89-112`). |
| R94 | Met | `10-web-common.sh:77-80` (PUT/OPTIONS/TRACE/HEAD over HTTP/1.0 on every probed server). |
| R95 | Met | `conf.sh:106-131` (`-Xlog` in the three container options), `run.sh:99-108` (merge per type), `classload.py`. |

## TO-BE items

T26-T38 are the 2026-11-02 runs review's items, still open; T39-T50 are the
2026-11-03 items; T51-T56 are the 2026-11-04 runs review's proposals.

| Item | Status | Evidence |
|---|---|---|
| T1 | Open | Only the HTTP/1.0-without-Host case is used (`10-web-common.sh:77-80`); the malformed request line, lowercase method, over-long header and `Transfer-Encoding`+`Content-Length` cases are absent. |
| T2 | Open | `classload.py:39` still strips the version before comparing. |
| T3 | Done as R87; evidence part open | `compare_e2e.py:239-252` reports and matches one-side classes; the raw class-load and class-resolution lines are not kept (`classload.py:75-95`). |
| T4 | Open | No per-field counts in `impact.py` or `report.py`. |
| T5 | Done as R78 | `ancestry.py`, `common.sh:106-123`. |
| T6 | Done as R80 | `replay.py`, `replay.sh`. |
| T7 | Done | Every user-visible rule carries `announced:` (the five rule files). |
| T8 | Done as R84 | `50-mapreduce.sh:42-45,71-73`. |
| T9 | Done as R88 | `85-federation.sh:139-171`; the checks are BOTH_FAIL in CI (T49). |
| T10 | Done as R87 | `e2e/expected-e2e-differences.txt:71-80`. |
| T11 | Done as R85 | `compare_unit.py:95-108,171-187`, `ci/history.sh`. |
| T12 | Done as R90 | `artifact_diff.py:277-320`. |
| T13 | Open | `downstream-deps.sh:64-70` is still the original 14 artifacts. |
| T14 | Done as R95 | `conf.sh:106-131`, `run.sh:99-108`. |
| T15 | Done as R91 | `artifact_diff.py:325-484`. |
| T16 | Done as R79 | `compare_plan.py`. |
| T17 | Done as R89 | `attribution.sh`, `attribution.py`, the attribution workflow. |
| T18 | Closed by owner decision | No automation; `announced:` is checked by hand. |
| T19 | Done as R94 | `10-web-common.sh:77-80`. |
| T20 | Done as R83 | `compare_unit.py:151-156`. |
| T21 | Done with T7 | The HADOOP-20013 rules agree on `announced:`. |
| T22 | Done as R93 | `ServletProbe.java`, `10-web-common.sh:89-112`; the probe defect (G2) remains. |
| T23 | Done as R92 | `api_compat.py:287-302,357-381`. |
| T24 | Done | `e2e/expected-e2e-differences.txt:54` no longer names MAPREDUCE-7548. |
| T25 | Done as R86 | `ha.sh:112`, `mixed.sh:81`, `federated.sh:100`. |
| T26 | Open | No downstream project is compiled or run (runs review, G8). |
| T27 | Open | No duplicate winner is reported (runs review, G8). |
| T28 | Open | No exclusion scenario exists. |
| T29 | Open | Only the four R49 scenarios. |
| T30 | Open | No `class-gone` check. |
| T31 | Open | No SPI check. |
| T32 | Open | Counts only for shaded changes. |
| T33 | Open | No Hadoop-jar API finding. |
| T34 | Open | Fixed unit lists. |
| T35 | Open | `both_fail` is ignored in the verdict. |
| T36 | Open | History is present but not the never-failed logic. |
| T37 | Open | No `@arch=` (runs review, G5). |
| T38 | Open | No mixed-version run. |
| T39 | Done | `probe.py:157-164`, `10-web-common.sh:102-104` (`--shape json-values`). |
| T40 | Done | `artifact_diff.py:191-192` (declared version compared). |
| T41 | Done | `artifact_diff.py:214-221` (exclusions sorted). |
| T42 | Done | `env.sh:252-261` (`SCENARIO_DONE_FILE`). |
| T43 | Done | `logscan.py:69-74` (class-load logs skipped). |
| T44 | Done | `classload.py:47-59` (per-run ids masked); `e2e/expected-e2e-differences.txt:65` (`classjar javax.activation`). |
| T45 | Done | `report.py:122-144` (A/A gate line). |
| T46 | Decided | `tmpl:456` keeps `CLASSONLY_FAIL: "false"`; the A/A run has 15 unexpected one-side classes. |
| T47 | Done | `attribution.py:52-58,180-183` (missing tree fails). |
| T48 | Done | `attribution.py:95-140` (interactions); `expected-differences.txt:149-150` (retagged). |
| T49 | Decided | R88 stays; the YARN issue is not filed. |
| T50 | Open | `artifact_diff.py:383-396` cannot see bundled jars. |
| T51 | Proposed | `ServletProbe.java:114-129` (the `"absent"` sentinel). |
| T52 | Proposed | `compare_e2e.py:109-131,335-337` (only the first differing path). |
| T53 | Proposed | `ServletProbe.java:100-101` (`push_supported` always `"absent"`). |
| T54 | Proposed | `report.py:122-129` (the gate ignores one-side classes). |
| T55 | Proposed | `README.md:384-398` (the flake is not listed). |
| T56 | Proposed | The A/A and broken runs exist only for `simple`. |

## Serious findings

### 1. The probe's mapping answer is unreadable, and it is the only blocking difference (R93, G2; from reading, CI evidence)

`ServletProbe.mappingJson()` (`e2e/lib/ServletProbe.java:114-129`) checks only
`mapping == null` before `Class.forName("javax.servlet.http.HttpServletMapping")`
and reflecting on the value. When `getHttpServletMapping` is missing,
`reflect()` (`:135-147`) returns the string `"absent"`, which is not null, so
the method reflects on that string. The baseline's `mapping` fields are
therefore `"error:IllegalArgumentException"` (the runs review's
`simple-run-21-baseline-observations.jsonl`), not `"absent"` as R93 promises.
The candidate's empty mapping is the Servlet 4.0 default method's answer. The
real difference is "method absent" vs "default empty mapping", but the report
cannot say so.

This is the only blocking end-to-end difference in every architecture
(`probe:probe-base`, runs review), so it is what keeps every normal run red.
Fix: return `"absent"` when the value is the `"absent"` string (or check
`instanceof String`) before `Class.forName`, and add a probe self-test that
runs the probe against a 3.1 classpath and asserts `mapping: "absent"`. Two
lines plus a test; T51.

### 2. A multi-field DIFF shows only the first differing path's values (R35/R37, G1; from reading)

`compare_e2e.first_difference()` (`lib/compare_e2e.py:109-131`) returns the
first differing path only, and `write_markdown()` (`:335-337`) writes only
`detail`. `differing_paths()` (`:134-147`) computes every path for the
`obsfield` rules and stores them in `fields`, but no value is written for the
others. The probe DIFF has six differing paths (`/body/json/mapping/match`,
`match_value`, `pattern`, `servlet_name`, `new_push_builder`,
`http_servlet_jar`), and the report shows one. The self-test
(`test_comparators.py:399-408`) checks only the first path's values, so it
would not catch a regression here. Fix: write every differing path with both
sides' values (masked) in the JSON and the markdown; T52.

### 3. The A/A gate passes with 15 unexpected one-side classes (R68/T45, G3; from reading, CI evidence)

`report.py:122-129` sets `aa_check` from the check verdicts only. With
`CLASSONLY_FAIL=false` (`tmpl:456`), an unexpected one-side class does not
change the end-to-end verdict (`compare_e2e.py:266-267`), so
`simple-run-aa-10` is `Harness check: **PASS**` with 15 unexpected one-side
classes (runs review). T46's condition ("zero unexpected one-side classes") is
not met, and the gate does not cover the class-load comparison. Fix: include
the unexpected one-side classes in the gate, or record the A/A run's set as
the noise budget; T54, owner decision.

### 4. Push support is never reported (R93, G6; from reading, CI evidence)

`ServletProbe.baseJson()` (`:100-101`) calls `isPushSupported` through
reflection, but the runs review shows `push_supported` is `"absent"` on both
sides in every run, and `isPushSupported` is not in the API-added list. The
field reports nothing. Fix: remove the field or report whether
`newPushBuilder()` returns a `PushBuilder`; T53.

### 5. A known flake is not documented, so it looks like a regression (R77, G4; CI evidence)

`TestFederationInterceptor#testRecoverWithoutAMRMProxyHA` is pass on the
baseline and fail on the candidate in `federated-run-11`, with a history of 3
baseline / 2 candidate failures in 5 runs (runs review). The only change to
`FederationInterceptor` is `ConcurrentHashSet` to
`ConcurrentHashMap.newKeySet()`, which is equivalent. `README.md:384-398`
lists only `testSubClusterTimeOut`. R45 cannot accept a regression, so the run
stays FAIL. Fix: add it to the known issues and R77's list, or investigate it;
T55.

### 6. Architecture-specific rules are reported unused elsewhere (R59, G5; CI evidence)

Replay over the five runs: the `Vary` rule matched only in `simple`, the
job-counter and ten timeline-server rules only in `secure`, and the
`obsdiff yarn-timeline:` and `classjar javax.activation` rules matched nothing
(runs review). R59 reports them as unused in the other architectures. Fix: let
a rule end with `@arch=<arch>[,...]`; T37, owner decision and a replay.

### 7. The downstream duplicate winner and a compile/run are not checked (R51/R57, G8; CI evidence)

`downstream-compare.md` reports six new `javax.servlet` duplicate sets but not
which copy Maven puts first, and no project is compiled or run (runs review).
In `own-javax-servlet` the project's own 3.1.0 may win over the 4.0.9 jar;
harmless on Jetty 9.4, a `NoSuchMethodError` in phase B. Fix: report the
winner and compile/run one project; T26/T27.

### 8. The A/A and broken-candidate self-checks run only in `simple` (R68/R69, G9; from reading, CI evidence)

The workflows exist for all five architectures, but the batch has an A/A run
and broken runs only for `simple` (runs review). The other four architectures'
noise and breakage detection are not gated. Fix: one A/A run and one broken
run per architecture, or record each architecture's A/A noise set; T56.

### 9. The LICENSE check cannot see jars bundled in the shaded clients (R91, G7; from reading, CI evidence)

`artifact_diff.py:383-396` walks `share/` for jars shipped as files, so an
artifact bundled in a `hadoop-client-*` jar shows as `license-entry-stale`.
The two HADOOP-20014 entries are accepted by `expected-differences.txt:79`
until T50 counts bundled artifacts. Fix: count the bundled artifacts from the
dependency data or the jars' `pom.properties`; T50.

## Partly met

| Req | Gap |
|---|---|
| R14 | A public class removed outright gets no API finding: pairs need the class on both sides (`api_compat.py:325-355`). |
| R24 | Single-instance daemons share one configuration directory (`simple.sh:28-42`, `secure.sh:52-59`). |
| R30 | Three CORS headers are compared by value; `allow-credentials`, `expose-headers` and `max-age` by name only (`probe.py:65-72`). |
| R42 | `quick` runs whole modules for entries with no test list (`unit-tests.sh:157-163`), not only the web and Jersey tests. |
| R52 | With results on one side only, the verdict is NOT RUN and overall INCOMPLETE, not a failure (`compare_downstream.py:95-100`). |
| R54 | A broken-candidate run exits 0 with overall FAIL (R69) (`report.py:164-166`). |
| R56 | Impact on users is written after the verdict table, not at the start (`report.py:151-156`). |
| R63 | The pre-existing rules name no ticket (`e2e/expected-e2e-differences.txt:46,54,65`); R67 allows it. |
| R70 | Each job resolves `PREPARATION` separately (`tmpl:99`, setup action `:50-65`). |
| R78 | "Counts as contained" needs the whole file to match; a cherry-pick onto a file the patch also changes is reported missing (`ancestry.py:66`). |
| R88 | The direct checks are BOTH_FAIL and the reads by id are never compared (runs review, T49). |
| R93 | The probe's mapping answer is `error:IllegalArgumentException` instead of `"absent"` (G2), and `push_supported` is always `"absent"` (G6). |

## Documentation out of date

- **`HARNESS-REQUIREMENTS.md:718-727`:** the TO-BE introduction says "What is
  left: T50; the YARN issue for T49; a fresh batch to confirm these fixes,
  including the HADOOP-19970 `mapping.match` probe value, which waits for that
  batch's recorded probe values". The fresh batch has run (2026-11-04); the
  probe value is recorded but unreadable (G2).
- **`HARNESS-REQUIREMENTS.md:1013-1031` (Next plan):** it says "The next work
  is a fresh batch (step 2a) with those fixes". That batch has run.
- **`HARNESS-REQUIREMENTS.md:1087-1097` (step 2a):** it describes the
  2026-11-03 batch as the latest and says "Every normal run FAILed". The
  2026-11-04 batch is the next one and is not mentioned.
- **`HARNESS-REQUIREMENTS.md:654-656` (T46 extension):** it says "the A/A run
  of 2026-11-03 (`simple-run-aa-9`) had 10". The 2026-11-04 A/A run
  (`simple-run-aa-10`) has 15.
- **`JETTY12-MIGRATION-PLAN.md:265-295`:** it says the latest runs are the
  2026-11-03 batch, all five architectures and the A/A run FAIL. The
  2026-11-04 batch has the A/A PASS and the architectures FAIL only on
  `probe:probe-base`.
- **`README.md:384-398`:** the known issues list `testSubClusterTimeOut` but
  not `testRecoverWithoutAMRMProxyHA` (T55).

## Gaps with no requirement or to-do item

- **Umbrella exit criteria:** no requirement checks "no Jetty 9.4 artifact
  left", JDK 21/25 runs, or a mixed-version client/server run (the plan lists
  the last two as "before phase B").
- **Check 4 one-sided flake:** a test flaky on the baseline and failing on the
  candidate still fails as a regression; there is no rule for it.
- **`impact.py` has no self-test:** R81's list leaves it out, and it is the one
  comparator with no verdict.
- **The `Vary` difference has no JIRA:** the rule says pre-existing and "no
  issue filed" (R67), so nothing tracks it.
- **The probe's push support:** R93 names `isPushSupported()`, but the field
  reports nothing and no requirement says what to do (T53 proposes it).

## Open items

Confirmed still open, with the confidence each was checked at:

- **T1:** only the HTTP/1.0-without-Host case is used (R94); the malformed
  request line, lowercase method, over-long header and
  `Transfer-Encoding`+`Content-Length` cases are absent (searched `raw` in
  `e2e/scenarios/`). High confidence.
- **T2:** `classload.py:39` still strips the version before comparing. High.
- **T3 evidence part:** the raw class-load and class-resolution lines are not
  kept; only `<daemon>.classes.tsv` is written (`classload.py:75-95`). High.
- **T4:** no per-field counts in `impact.py` or `report.py`. High.
- **T13:** `downstream-deps.sh:64-70` is still the original 14 artifacts. High.
- **T18:** closed by the owner's decision (no automation); nothing to do.
- **T26, T27, T37:** open; the runs review's table matches the code (no
  compile/run, no duplicate winner, no `@arch=`). High for the ones searched.
- **T50:** open; the LICENSE check still cannot see bundled jars
  (`artifact_diff.py:383-396`). High.
- **T51-T56:** proposed by the runs review; none is implemented. High.
- **The YARN issue for T49:** not filed; R88 stays as written. High.
- **The HADOOP-19970 `mapping.match` probe value:** recorded but unreadable
  (G2); it needs T51 and then a decision on the rule or release-note sentence.

## Recommended order

1. **T51 and T52.** They make the only blocking difference readable: the probe
   reports `"absent"` instead of an error, and the report shows every differing
   field's values. Small, no owner decision.
2. **T53.** Remove or fix the dead push-support field. Small.
3. **T55.** Document `testRecoverWithoutAMRMProxyHA` as a known flake, so it
   stops looking like a regression. Documentation only.
4. **T54 and T37** (owner decisions), then **T56** (more self-check runs).
5. **T26 and T27**, the largest and the one that matters most before phase B.
6. **T50** and the YARN issue for T49.
7. The Partly met fixes: R14 (removed class), R42 (quick whole modules), R70
   (per-job `PREPARATION`), R78 (whole-blob match), R52 (NOT RUN), and the
   text-or-code choices of R24, R30, R54, R56 and R63.

Recommendations for the pending decisions:

- **T54:** make the A/A gate require zero unexpected one-side classes, and
  record the A/A run's set as the noise budget if that is too strict. Reason:
  the gate currently passes with 15 noise classes, so it does not gate the
  class-load comparison.
- **T37:** yes to `@arch=`, with a replay. Reason: the `Vary`, job-counter and
  timeline-server rules are architecture-specific and R59 reports them unused
  elsewhere.
- **T55:** accept `testRecoverWithoutAMRMProxyHA` as a known flake and document
  it. Reason: it is pass-to-fail with a 3/2 history in 5 runs, and the only
  change to `FederationInterceptor` is equivalent.
- **The probe difference:** after T51, the DIFF is "method absent" vs an empty
  mapping. Recommend a narrow `obsfield` rule for
  `probe:probe-base/body/json/mapping` plus a sentence in HADOOP-19970's
  release note, because the difference is real (the 4.0 default method returns
  an empty mapping) and user-visible only to code that calls
  `getHttpServletMapping`.

## The runs review's proposals

| Item | Assessment |
|---|---|
| T51 | Extends R93 correctly: R93 says a missing method is reported as `"absent"`, and the code does not do that for `getHttpServletMapping`. Not a duplicate. |
| T52 | Extends R35 and R37 correctly: R35 says every field is compared, R37 says an unexpected DIFF fails, but neither says the report shows every differing field's values. Not a duplicate. |
| T53 | Extends R93 correctly: R93 names `isPushSupported()`, and the field reports nothing. Not a duplicate. |
| T54 | Extends R68, R87 and T46 correctly: R68 says the A/A differences are noise to mask or allow, and T45's gate only looks at check verdicts. Not a duplicate of T46 (which is about the `CLASSONLY_FAIL` switch). |
| T55 | Extends R77 correctly: R77 lists known both-side failures, and this test is a pass-to-fail regression. Not a duplicate. |
| T56 | Extends R68 and R69 correctly: neither says every architecture must have an A/A and a broken run. Not a duplicate. |
| T26, T27 | Extend R51 and R57 correctly: R51 reports duplicate sets, R57 lists the projects, but neither says which copy wins or that a project compiles and runs. Not duplicates. |
| T37 | Extends R61 and R59 correctly: R61 defines the rule format, R59 reports unused rules, but neither has an architecture qualifier. Not a duplicate. |

## Earlier review

The 2026-11-03 21:58 review's findings, at this commit:

- **Scenario end marker lost (R82, G1):** fixed. `env.sh:252-261` carries the
  marker in `SCENARIO_DONE_FILE`; `test_probe.py`'s `done_marker_case` passes.
- **Log scan reads class-load lines (R39, G2):** fixed. `logscan.py:69-74`
  skips class-load logs; `test_probe.py`'s `logscan_case` passes.
- **Class-load per-run application id (R68, G3/G4):** fixed.
  `classload.py:47-59` masks the ids; `test_comparators.py`'s "the same
  `job.jar` under two application ids is not a move" passes.
- **R90 misses a declared version and is not deterministic (G8):** fixed.
  `artifact_diff.py:191-192` compares the version and `:214-221` sorts the
  exclusions; the T40/T41 self-tests pass.
- **Probe answers compared only by type (R93, G5):** partly fixed. T39 records
  the values (`probe.py:157-164`, `10-web-common.sh:102-104`), but the probe
  defect (G2) and the report detail (G1) remain.
- **Federated direct checks compare nothing (R88, G7):** still open. T49 is
  decided (R88 stays) and the 14 `fed-yarn` BOTH_FAIL are unchanged.
- **Attribution report drops a failed tree (R89, G6):** fixed. T47 builds the
  expected list and reports a missing tree (`attribution.py:52-58,180-183`);
  the self-test passes.
- **Two rules name the wrong ticket (R63, G10):** fixed. T48 retagged them to
  HADOOP-20015 (`expected-differences.txt:149-150`).
- **`CLASSONLY_FAIL` cannot be turned on (R87, G9):** still open. T46 is
  decided (the switch stays off) and the A/A run has 15 unexpected one-side
  classes.
- **The only patch defect check 1 reports is real (R91):** partly fixed. The
  two entries are now accepted by `expected-differences.txt:79`; T50 is open.

Its partly-met list differs from this review's where the text or the code has
changed since: R2, R10, R34, R37, R57, R67, R68, R76 and R82 are Met here
(the text now states the exceptions, the symlink rule, the FIXED/candidate-only
handling and the `PR_BRANCHES` default, and the A/A run and the marker are
fixed); R14, R24, R30, R42, R52, R54, R56, R63, R70, R78, R88 and R93 remain
partly met.

The 2026-11-02 15:36 review's findings:

- **R40 threshold:** fixed. The text now says "at least 6 more"
  (`HARNESS-REQUIREMENTS.md:333-334`), which is what `compare_e2e.py:158`
  does.
- **R41 whitespace-only file:** fixed. `compare_e2e.py:79-85` counts non-blank
  lines; the self-test covers the blank-line cases.
- **R54 ancestry verdict:** fixed. `ancestry.py:93` writes PASS/FAIL and
  `report.py:45-52` accepts it. The new R54 gap is the broken-run exit code.
- **R63 broad rules:** still open (partly met). The `Vary` rule names no
  ticket, and the `classjar` rule does not name the destination jar.
- **R79 plan-check defects:** fixed. The deleted-file case is a match
  (`compare_plan.py:244-245`), the text describes `git merge-file` for one
  branch, and `PR_ORDER` follows the migration plan.
- **R78 whole-blob match:** still open (partly met).
- **Maven exit code:** fixed. `compare_unit.py:134-137` fails a module whose
  Maven run failed on the candidate only.
- **Scenarios that die early:** fixed by R82 and T42.
- **Late ancestry check:** fixed. The queue job runs both tree checks before
  the wait (`tmpl:137-150`).
- **As PRs land:** fixed. A squash-merged branch is listed as landed
  (`compare_plan.py:131-142`).
- **Plan coverage and the one-sided flake:** still open (see Gaps).

## What this review did not cover

- No Maven build, cluster run or CI job was run. The reproductions use the
  harness's own Python modules and self-tests on synthetic inputs; the CI
  facts come from the 2026-11-04 10:44 runs review's tables.
- The raw `observations.jsonl` files, the daemon logs and the downloaded
  reports are not in the inputs, so the exact probe values behind
  `/body/json/mapping/match` and the exact `classload-*.log` lines were not
  seen; the conclusions rest on the comparator code and the runs review.
- The 1,593 artifact differences, the class-jar moves and the class-load tables
  were not read row by row; the unexpected rows, the POM rules and the license
  entries were.
- T26-T38 were checked by search and by the runs review, not by reading every
  comparator path they would need.
- No file on the checklist is marked `[!]`.
