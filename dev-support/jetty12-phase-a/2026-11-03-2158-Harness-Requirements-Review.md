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

# Harness requirements review, 2026-11-03 21:58

This review checks `HARNESS-REQUIREMENTS.md` (R1-R95 and T1-T25) against the
code on `feat/HARNESS` at commit `93165486a76`, and reads `README.md`,
`JETTY12-MIGRATION-PLAN.md`, `AGENTS.md`, the first CI batch of 2026-11-03
(`.review/inputs/2026-11-03-2138-Harness-Runs-Review.md`, runs 41574970529 to
41574972165) and the two earlier requirements reviews. Paths are relative to
`dev-support/jetty12-phase-a/` unless they start with `.github/`. It is a
snapshot: no harness code, requirement or rule was changed for it, and nothing
outside `.review/` was edited. The two self-tests were run and pass; no build,
cluster or CI job was run.

## Verdict

The harness implements almost all of what the document says, and the newest
requirements (R90-R95) are real code, not stubs. But the first CI batch shows
that several requirements do not yet do what they say: the scenario end marker
is lost (R82), the log scan reads class-load lines as errors (R39), the
class-load comparison treats a per-run application id as a different jar
(R38/R68), and the servlet probe compares only JSON types (R93). R90's POM
comparison also misses a declared `<version>` change. Every architecture run
and the A/A run FAIL for these reasons, so no run in the batch is a
trustworthy verdict on the patch.

| AS-IS result | Count | Requirements |
|---|---|---|
| Met | 70 | All others |
| Partly met | 22 | R2, R10, R14, R24, R30, R34, R37, R39, R42, R52, R54, R56, R57, R63, R67, R68, R70, R76, R78, R82, R88, R93 |
| Not met | 0 | — |
| Not checkable (process rule or principle) | 3 | R3, R65, R66 |

"Reproduced" means the harness's own code was run on synthetic inputs in
`.review/scratch/`; the command and output are in the finding. "From reading"
means the conclusion comes from the code at this commit. CI evidence is the
runs review's tables and `gh run view` on the run ids it names.

## Requirements

| Req | Status | Evidence |
|---|---|---|
| R1 | Met | `lib/common.sh:29-30` (two refs), `compare.sh:70-111`; both sides built and compared. |
| R2 | Partly | `artifact_diff.py:486-496` accepts only by rule, but R37/R38/R45 list FIXED, BOTH_FAIL, candidate-only and one-side classes without failing (`compare_e2e.py:257-268`, `compare_unit.py:194-195`). |
| R3 | Not checkable | A goal, not a behaviour. |
| R4 | Met | `compare.sh` runs the same scripts for both sides; `e2e/run.sh` and `unit-tests.sh` take the side as an argument. |
| R5 | Met | `build.sh:46-73` (worktree, `dist`/`install`). |
| R6 | Met | `build.sh:76-103` (`dependency:list`, MiniKdc and timeline test jar staged). |
| R7 | Met | `build.sh:70` (`-Pnative -Drequire.openssl -Drequire.snappy`). |
| R8 | Met | `artifact_diff.py:76-84,505-532`. |
| R9 | Met | `artifact_diff.py:87-110` (nested jar checksum), `:519-531`. |
| R10 | Partly | `VOLATILE_ENTRY`/`VOLATILE_FILE` at `:56-64` match the list, but symlinks are skipped at `:82` and the text does not say so. |
| R11 | Met | `artifact-diff.sh:36-64` (all seven views), `artifact_diff.py:534-551`. |
| R12 | Met | `artifact_diff.py:553-560` (test vs runtime by scope). |
| R13 | Met | `artifact-diff.sh:30-33,66-67`; CI runs it on every fresh build (`tmpl:248-251`). |
| R14 | Partly | `api_compat.py:325-355` compares changed classes, but a public class removed outright has no pair and gets no API finding. |
| R15 | Met | `api_compat.py:220-277` (all eleven kinds). |
| R16 | Met | `api_compat.py:268-276`. |
| R17 | Met | `classfile.py:177-193`, `api_compat.py:413-420`. |
| R18 | Met | `api_compat.py:421-425`. |
| R19 | Met | `api_compat.py:398-404,440-441` (relocated/private-audience are INFO). |
| R20 | Met | `api_compat.py:386-409` (file-name subject, dedupe with locations). |
| R21 | Met | Documented out of scope; checks 3 and 4 cover behaviour. |
| R22 | Met | `e2e/run.sh:41-138`, `e2e/cluster.sh`. |
| R23 | Met | `e2e/arch/{simple,secure,ha,federated,mixed}.sh` as described. |
| R24 | Partly | Per-instance pid/log (`cluster.sh:62-66`) and per-instance conf for multi-instance daemons (`ha.sh:47-60`, `mixed.sh:52-69`); single-instance daemons share `${HADOOP_CONF_DIR}`, so "every instance has its own configuration directory" is not literal. `start` wipes state (`cluster.sh:137-140`). |
| R25 | Met | Scenarios 00-90 read; each covers the listed area. |
| R26 | Met | `cluster.sh:74-134` (fail fast, `daemons.txt`), `run.sh:59-63` (`aborted.txt`, logs still collected). |
| R27 | Met | `run.sh:38`; `test_probe.py` passes. |
| R28 | Met | `probe.py:634-637`; five types. |
| R29 | Met | `probe.py:379-410` (method, status, reason, error, headers, cookies, location, body, error_text). |
| R30 | Partly | `probe.py:65-72` compares three CORS headers; `access-control-allow-credentials`, `-expose-headers` and `-max-age` are name-only. |
| R31 | Met | `probe.py:422-461`. |
| R32 | Met | `probe.py:513-543`. |
| R33 | Met | `probe.py:546-566`. |
| R34 | Partly | `probe.py:91-127` masks the listed values in the probe's fields, but header values other than SPNEGO tokens and the class-load jar paths (`classload.py:49-59`) are not masked. |
| R35 | Met | `compare_e2e.py:98-131,196-205` (whole view, stack lines dropped). |
| R36 | Met | `compare_e2e.py:196-211`. |
| R37 | Partly | `compare_e2e.py:257-268` fails on the four stated cases, but FIXED and candidate-only MISSING are counted and not listed (`write_markdown` has no section for them). |
| R38 | Met | `classload.py:95-113`, `compare_e2e.py:226-234`; a different jar fails unless a `classjar` rule matches. The per-run path noise is a finding under R68. |
| R39 | Partly | `logscan.py:34-48,78-87` scans the container `classload-*.log` files and matches class names, so six class-load lines are reported as new errors in every run (G2, reproduced). |
| R40 | Met | `compare_e2e.py:150-162` (`nb == 0 or n > max(2*nb, nb+5)` = "at least 6 more"). |
| R41 | Met | `compare_e2e.py:79-85,178-193` (non-blank lines; baseline aborted NOT RUN, candidate aborted FAIL). |
| R42 | Partly | `unit-tests.sh:70-141` has the suites, but `quick` runs whole modules for entries with an empty test list (`:157-163`), and the README's lists differ slightly (e.g. `TestDelegationToken`, `TestHttpFSServerWebServer`). |
| R43 | Met | `unit-tests.sh:153-156`. |
| R44 | Met | `compare_unit.py:52-81` (pass/flaky/fail/skipped, unparseable = fail). |
| R45 | Met | `compare_unit.py:134-137,188-197`. |
| R46 | Met | `compare_unit.py:198-207` (listed, not failing). |
| R47 | Met | `unit-tests.sh:166-171`, `lib/stall-watch.sh`. |
| R48 | Met | `downstream-deps.sh:64-70` (the 14 artifacts). |
| R49 | Met | `downstream-deps.sh:54-62` (four scenarios, defaults as stated). |
| R50 | Met | `compare_downstream.py:111-117`. |
| R51 | Met | `downstream_classes.py:58-82`, `compare_downstream.py:118-123`. |
| R52 | Partly | Neither side: no section (`compare_downstream.py:91-93`). One side: verdict NOT RUN (`:95-100`), not FAIL as the text says; the run still exits non-zero. |
| R53 | Met | `compare.sh:45-51` (delete first), `:84-111`. |
| R54 | Partly | `report.py:116-117` gives PASS/INCOMPLETE/FAIL, but `report.py:151-153` returns 0 when a broken-candidate harness check passes although the overall verdict is FAIL (R69). |
| R55 | Met | `report.py:55-79,123-131`. |
| R56 | Partly | `impact.py` builds the three audiences, but `report.py:141-143` writes it after the verdict table, not at the start. |
| R57 | Partly | `impact.py:186-191` lists projects with a new duplicate set, but a project that already had an unchanged duplicate in another package is still listed as having had none. |
| R58 | Met | `impact.py:194-208`. |
| R59 | Met | `artifact_diff.py:577`, `api_compat.py:449`, `compare_e2e.py:284`, `compare_unit.py:207`, `compare_downstream.py:136`. |
| R60 | Met | Five rule files; check 4 accepts only `candidate-only-fail` (`compare_unit.py:151-156`). |
| R61 | Met | `allowlist.py:31-53` (whole-subject match, `#` rule). |
| R62 | Met | `compare_e2e.py:42-48,212-224`; `classonly` at `:247`. |
| R63 | Partly | Every patch rule names a ticket except the pre-existing `Vary` rule (`e2e/expected-e2e-differences.txt:46`); `expected-differences.txt:125` and `:140` name the wrong ticket (G10). |
| R64 | Met | `api_compat.py:468-471`, `impact.py:48-51`; the rule files now carry `announced:` for every user-visible change. |
| R65 | Not checkable | A process rule. |
| R66 | Not checkable | A process rule; the tool exists (`replay.sh`). |
| R67 | Partly | `e2e/expected-e2e-differences.txt:46` (Vary) and `:54` (job counters) say pre-existing but name no issue. |
| R68 | Partly | The A/A run is set up (`tmpl:100`), but `simple-run-aa-9` FAILs with 120 blocking `classjar` moves, one probe DIFF and six log errors (G2/G3/G5). |
| R69 | Met | `report.py:82-90,118-131`; `tmpl:332` skips the unit jobs; self-tests cover the four outcomes. |
| R70 | Partly | One workflow per architecture and the run-name patterns are right, but each job resolves `PREPARATION` separately (`tmpl:99,140-145`), so a baseline that moves mid-run is checked against a different commit than the one built. |
| R71 | Met | `ci/wait-turn.sh:65-110`; `tmpl:110-193` (queue and queue-2, 340 minutes each). |
| R72 | Met | `tmpl:195-230` (native build image, `BUILD_SRC_DIR`), other jobs on `ubuntu-24.04`. |
| R73 | Met | `ci/build-key.sh:36-49`, `ci/find-build.sh`; retention 7/14/30 days (`tmpl:264,325,401,478`). |
| R74 | Met | `jetty12_phase_a_simple.yml:78-81` (four shards, tier full). |
| R75 | Met | `tmpl:458-478` (900 KB summary, full artifact). |
| R76 | Partly | `run-all.sh` runs every step, but the README gives `PR_BRANCHES` a default that does not exist (`README.md:569`), so a local run skips the plan check. |
| R77 | Met | `README.md:231-375` documents the unexercised areas and the known both-side failures. |
| R78 | Partly | `ancestry.py:55-75` checks every baseline commit's change, but "counts as contained" needs the whole blob to match (`:66`), so a cherry-pick onto a file the patch also changes is reported missing. The queue job runs it before the wait (`tmpl:137-150`). |
| R79 | Met | `compare_plan.py:144-184,230-255` (deleted file, binary, landed, order); `PR_BRANCHES` set at `tmpl:105`; skipped when the sides are one commit (`common.sh:94-100`). |
| R80 | Met | `replay.py:154-201`, `replay.sh`; the `NEW_KINDS` exception (`:133,186-188`) is documented in `README.md:553-555` but not in R80. |
| R81 | Met | `test_comparators.py` (run: all cases pass); `compare.sh:56`, `run-all.sh:34`, `tmpl:131-133`. Its "does not cover" sentence (`HARNESS-REQUIREMENTS.md:445-447`) is stale. |
| R82 | Partly | `run.sh:80-100` records the marker, but `10-web-common.sh:27` and `70-secure.sh:29` run `set --`, which replaces `$5`, so the marker is written to the instance's URL (G1, reproduced). |
| R83 | Met | `compare_unit.py:151-156,193-195`. |
| R84 | Met | `50-mapreduce.sh:42-45,71-73`; CI `mapreduce-jobs:control-job` MATCH. |
| R85 | Met | `compare_unit.py:171-187`, `ci/history.sh`, `compare.sh:92-101`. |
| R86 | Met | `ha.sh:112`, `mixed.sh:81`, `federated.sh:100`. |
| R87 | Met | `compare_e2e.py:243-267`; `tmpl:456` sets `CLASSONLY_FAIL: "false"`. |
| R88 | Partly | `85-federation.sh:139-171` submits directly and defines the five checks, but in `federated-run-10` the router listing omits the application, so all five are BOTH_FAIL and the two reads by id are never compared (G7). |
| R89 | Met | `attribution.sh:65-72,90-133`, `attribution.py`, `jetty12_phase_a_attribution.yml:171-226` (one job per tree). |
| R90 | Met | `artifact_diff.py:262-305` (scope, optional, type/classifier, exclusions, managed versions, parent, `pom-unparseable`). A direct `<version>` is not compared (G8, reproduced); the text does not claim it. |
| R91 | Met | `artifact_diff.py:308-469`; CI reports two genuine stale entries (patch defect, not a harness defect). |
| R92 | Met | `api_compat.py:287-302,357-381`, `impact.py:113-119`. |
| R93 | Partly | `ServletProbe.java:91-129`, `10-web-common.sh:89-112`; the answers are compared only by JSON type (G5, reproduced). R93 says the scenario "records its answers as observations"; it records only their JSON types, so no answer is compared by value. *Relabelled Met to Partly by the checking session.* |
| R94 | Met | `10-web-common.sh:77-80` (PUT/OPTIONS/TRACE/HEAD over HTTP/1.0 on every probed server). |
| R95 | Met | `conf.sh:106-131` (`-Xlog` in the three container options), `run.sh:106-118` (merge per type), `compare_e2e.py:369-378`. |

## TO-BE items

| Item | Status | Evidence |
|---|---|---|
| T1 | Partly | Only the HTTP/1.0-without-Host case is used (`10-web-common.sh:77-80`); the malformed request line, lowercase method, over-long header and `Transfer-Encoding`+`Content-Length` cases are absent. |
| T2 | Open | `classload.py:39` still strips the version before comparing. |
| T3 | Done as R87; evidence part open | `compare_e2e.py:243-267` reports and matches one-side classes; the raw class-load and class-resolution lines are not kept (`classload.py:77-79`). |
| T4 | Open | No per-field counts in `impact.py` or `report.py`. |
| T7 | Done | Every user-visible rule carries `announced:` (the five rule files). |
| T8 | Done as R84 | `50-mapreduce.sh:42-45,71-73`. |
| T9 | Done as R88 | `85-federation.sh:139-171`; the checks do not compare anything in CI (G7). |
| T10 | Done as R87 | `e2e/expected-e2e-differences.txt:67-76`. |
| T11 | Done as R85 | `compare_unit.py:171-187`, `ci/history.sh`. |
| T12 | Done as R90 | `artifact_diff.py:262-305`. |
| T13 | Open | `downstream-deps.sh:64-70` is still the original 14 artifacts. |
| T14 | Done as R95 | `conf.sh:106-131`, `run.sh:106-118`. |
| T15 | Done as R91 | `artifact_diff.py:308-469`. |
| T17 | Done as R89 | `attribution.sh`, `attribution.py`, the attribution workflow. |
| T18 | Closed by owner decision | No automation; `announced:` is checked by hand. |
| T19 | Done as R94 | `10-web-common.sh:77-80`. |
| T20 | Done as R83 | `compare_unit.py:151-156`. |
| T21 | Done with T7 | The HADOOP-20013 rules agree on `announced:`. |
| T22 | Done as R93 | `ServletProbe.java`, `10-web-common.sh:89-112`. |
| T23 | Done as R92 | `api_compat.py:287-302,357-381`. |
| T24 | Done | `e2e/expected-e2e-differences.txt:54` no longer names MAPREDUCE-7548. |
| T25 | Done as R86 | `ha.sh:112`, `mixed.sh:81`, `federated.sh:100`. |

The earlier runs review's T26-T38 are all still open: no downstream
compile/run (T26), no duplicate winner (T27), no exclusion scenario (T28), only
the `older-jetty` scenario (T29), no `class-gone` (T30), no SPI check (T31),
counts only for shaded changes (T32), no Hadoop-jar API finding (T33), fixed
unit lists (T34), `both_fail` ignored in the verdict (T35), history present but
not the never-failed logic (T36), no `@arch=` (T37), no mixed-version run
(T38).

## Serious findings

### 1. The scenario end marker is lost, so every run reports a false early end (R82, G1; reproduced)

`e2e/run.sh:80-88` passes the done file as the fifth positional parameter of
`bash -c`, and writes it at the end with `: > "$5"`. `10-web-common.sh:27` and
`70-secure.sh:29` run `set -- ${line}` inside the scenario, which replaces the
positional parameters with the instance's fields, so `$5` is the instance's
readiness URL. The marker is never written, and `run.sh:94-100` records
`scenario:<name>.completed` as failed. That is why `10-web-common.completed` is
BOTH_FAIL in all five architectures and in the A/A run, and
`70-secure.completed` in `secure`, with the extra log line
`_: line 7: http://localhost:19888/jmx: No such file or directory`.

Reproduced with `.review/scratch/repro_g1.py`:

```
exit: 1
stderr: _: línea 4: HDFS_NAMENODE: No existe el archivo o el directorio
_: línea 5: http://localhost:19888/jmx: No existe el archivo o el directorio
done file exists: False
=> run.sh records scenario.completed = false (ended before its last line)
```

Fix: carry the done file in an environment variable (or a name the scenarios
cannot overwrite) instead of `$5`; two lines in `run.sh` plus the two
scenarios. T42.

### 2. The log scan reads class-load lines as errors (R39, G2; reproduced)

`logscan.py:78-87` walks the whole log directory, which includes the container
`classload-*.log` files that R95 adds under `userlogs/`. `PATTERN` (`:34-41`)
matches the class names in `[class,load]` lines, and `MASKS` (`:42-48`) does not
mask the side's path, so the same line on both sides becomes two different
messages and each is "new on the candidate" with `baseline_count: 0`. That is
the six `new_log_errors` in every run, including the A/A run.

Reproduced with `.review/scratch/repro_g2.py` and `repro_g2b.py`:

```
{"containers": {"ClassCastException source: file:/x/hadoop-common.jar": 1}}
=> reported as log errors: 1

baseline messages: ['ClassCastException source: file:/w/baseline/dist/...']
candidate messages: ['ClassCastException source: file:/w/candidate/dist/...']
=> new on the candidate: 1 (baseline_count 0)
```

Fix: skip `classload-*.log` (or only `[class,load]` lines) in `logscan.py`, and
mask the side root in messages; small. T43.

### 3. The class-load comparison treats a per-run application id as a different jar (R68, G3/G4; reproduced)

`classload.py:49-59` keeps the jar's absolute path, and `:103-106` compares the
directory after masking only `/baseline/` and `/candidate/`. A container's
`job.jar` lives under `application_<id>_<n>/container_<id>_.../`, so the same
class on both sides is a `classjar` move. `simple-run-aa-9` has 120 blocking
moves (60 `map`, 37 `mr-am`, 23 `reduce`), and `mixed-run-9` adds 30 moves
between `jakarta.activation-api-1.2.1.jar` and `jakarta.activation-1.2.2.jar`,
two jars that both ship on both sides.

Reproduced with `.review/scratch/repro_g3.py`:

```
{'org.example.Foo': ['<side>/.../application_111_0001/.../job.jar',
                     '<side>/.../application_222_0001/.../job.jar']}
=> blocking classjar moves: 1
```

Fix: mask the application/container ids and the side root in every jar path
(R34's list), and treat two shipped jars that provide the same class as not a
move; small. T44.

### 4. R90 misses a declared dependency version and is not deterministic (G8; reproduced)

`artifact_diff.py:178-194` builds the dependency key from group, artifact, type
and classifier only; the declared `<version>` is never read, so a direct
version change in a published POM is invisible. `:285-288` formats the detail
as a Python tuple containing a `frozenset`, whose repr order depends on the
hash seed, so two runs of one build write different bytes.

Reproduced with `.review/scratch/repro_g8.py`:

```
version-only POM change recorded as: []
=> a direct <version> change is invisible
detail per hash seed: 2 distinct spellings
   (('compile', 'false', frozenset({'x:y', 'x:z'})), ...)
   (('compile', 'false', frozenset({'x:z', 'x:y'})), ...)
```

Fix: resolve and compare the declared version (T40), and format exclusions as a
sorted list (T41); small.

### 5. The servlet probe's answers are compared only by JSON type (R93, G5; reproduced)

`probe.py:130-154` records a JSON value as `"str"`, `"num"`, `"bool"` or
`"null"`, and `10-web-common.sh:102-104` uses `--shape json`. The only probe
difference in the batch, `probe:probe-base` `/body/json/mapping/match:
"str" vs "null"`, therefore cannot be read: the baseline's string and the
candidate's null are not recorded, and the servlet versions, jar name, mapping
values and push support are never compared by value.

Reproduced with `.review/scratch/repro_g5.py`:

```
baseline view: {'json': {'mapping': {'match': 'str', 'match_value': 'str'}}}
candidate view: {'json': {'mapping': {'match': 'null', 'match_value': 'str'}}}
=> the values /probe/* and EXACT are not recorded; only their types are
```

Fix: compare a stable projection of the probe body by value (T39); small.

### 6. The federated direct checks compare nothing (R88, G7)

`85-federation.sh:149-171` derives all five direct checks from the router's
`/apps` listing. In `federated-run-10` the listing omits the directly submitted
application on both sides, so `router-apps-direct`, `router-app-list-direct`,
`router-app-direct`, `router-app-state-direct` and
`app-on-one-subcluster-direct` are all recorded as failed checks (BOTH_FAIL),
and the two reads by id that R88 says are "recorded with no expected status and
compared between the sides" are never performed. The direct submission itself
(`dshell-direct-sc1`) MATCHes. Fix: record the reads by id as comparisons even
when the listing is empty, and decide whether the listing expectations stay
(T49); small.

### 7. The attribution report silently drops a failed tree (R89, G6)

`attribution.py:143-145` iterates only the directories that exist, and the
workflow's `report` job downloads only the artifacts that were uploaded. In
`attribution-run-1` the `Tree prefix-5` job failed (`gh run view
41574971687`: `Tree prefix-5: failure`), so `attribution.json` has 9 trees and
no `prefix-5`, and the report says "9 trees" with no problem. The runs review
reports the job's cause as "No space left on device". Fix: build the expected
list from `PR_ORDER` and report a missing tree as a problem (T47); small.

### 8. Two rules name the wrong ticket (R63, G10)

`expected-differences.txt:125` (`pom-dependency-added ...jetty-servlet`) says
HADOOP-19970 and `:140` (`pom-dependency-added ...jetty-webapp`) says
HADOOP-20016, but `README.md:26` and `JETTY12-MIGRATION-PLAN.md:153-155` say
HADOOP-20015 declares both. The attribution run shows the effect: `ticket-5`
(HADOOP-20015) has these rules unused, and `ticket-6` (HADOOP-19970 alone) has
an UNEXPECTED `pom-dependency-changed` for
`hadoop-yarn-common|...jersey-test-framework-provider-jetty`. Fix: retag the two
rules and decide the ticket-6 interaction (T48); needs the owner's agreement
(R65) and a replay (R80).

### 9. `CLASSONLY_FAIL` cannot be turned on yet (R87, G9)

`tmpl:456` sets `CLASSONLY_FAIL: "false"`, and the A/A run still has 10
unexpected one-side classes (8 in `simple`, 16 in `secure`, 15 in `ha`, 249 in
`mixed`, 7 in `federated`). Turning the switch on would fail the control run,
so the failing part of T3 stays off. Fix: mask the classes that differ between
two runs of one build, or keep the switch off until an A/A run reports zero
(T46); needs the owner's decision.

### 10. The only patch defect check 1 reports is real (R91)

Every run reports `license-entry-stale` for
`org.glassfish.jersey.containers:jersey-container-jdk-http:2.46` and
`org.glassfish.jersey.test-framework.providers:jersey-test-framework-provider-jdk-http:2.46`
("no jar in the distribution"). `git diff 4f4422ad703 93165486a76 --
LICENSE-binary` adds both and removes `jersey-test-framework-provider-jetty`,
and the check finds no such jar. This is not a harness defect: HADOOP-20014
must remove the two entries before merge. The check is doing its job.

## Partly met

| Req | Gap |
|---|---|
| R2 | "Every other difference fails" is not true: FIXED, BOTH_FAIL, candidate-only and one-side classes are listed without failing. |
| R10 | Symlinks are skipped and the text does not say so. |
| R14 | A public class removed outright gets no API finding; only check 1 sees it. |
| R24 | Single-instance daemons share one configuration directory. |
| R30 | Three CORS headers are compared by value; the other three by name only. |
| R34 | Header values other than SPNEGO tokens, and the class-load jar paths, are not masked. |
| R37 | FIXED and candidate-only MISSING are counted but not listed. |
| R39 | Class-load lines are reported as log errors. |
| R42 | `quick` runs whole modules for entries with no test list; the README's lists differ slightly. |
| R52 | One side with results gives NOT RUN, not FAIL. |
| R54 | A broken-candidate run exits 0 with overall FAIL (R69). |
| R56 | Impact on users is written after the verdict table, not at the start. |
| R57 | A project with an existing unchanged duplicate can be listed as having had none. |
| R63 | The `Vary` rule names no ticket; two rules name the wrong ticket. |
| R67 | The `Vary` and job-counter rules name no issue. |
| R68 | The A/A run FAILs on blocking noise. |
| R70 | Each job resolves `PREPARATION` separately. |
| R76 | The README's `PR_BRANCHES` default does not exist. |
| R78 | A cherry-pick onto a file the patch also changes is reported missing. |
| R82 | The done marker is lost in the two scenarios that use `set --`. |
| R88 | The direct checks are BOTH_FAIL and the reads by id are never compared. |
| R93 | The probe's answers are recorded as JSON types only, not by value (G5). |

## Documentation out of date

- **`HARNESS-REQUIREMENTS.md:621-624`:** the TO-BE introduction says "the rest
  are not implemented yet", but T12, T14, T15, T19, T22 and T23 are done as
  R90-R95 (their own entries say so).
- **`HARNESS-REQUIREMENTS.md:848-856,912-931`:** the "Next plan" says steps 3
  and 4 are "not yet run in CI or on a cluster" and that step 2a "needs the
  owner's OK to push". The 2026-11-03 batch is that run.
- **`HARNESS-REQUIREMENTS.md:445-447`:** R81 says the self-test "does not cover
  `compare_plan.py`, `artifact_diff.py`, `api_compat.py` or `impact.py`". It
  now covers the first three (plan, T12/T15, T23 additions) and attribution;
  only `impact.py` is uncovered.
- **`HARNESS-REQUIREMENTS.md:519-528` (R80):** the text says replay "exits 1
  when a rule matched nothing"; `replay.py:133,186-188` exempts a `pom-*`,
  `license-*` or `notice-*` rule whose kind no report recorded. `README.md:553-555`
  documents the exception; R80 does not.
- **`README.md:569`:** the `PR_BRANCHES` row gives a default ("the six PR
  branches in merge order") that no code sets; `common.sh:116` only runs the
  plan check when the variable is non-empty.
- **`JETTY12-MIGRATION-PLAN.md:265-267,274-283,301-311,323-326`:** it says the
  latest runs are all PASS on `bc5d054a`, that R84-R89 are "not yet run in CI",
  and that the harness passes on HADOOP-19970. The 2026-11-03 batch is FAIL on
  every architecture, and the A/A and broken runs have now run.
- **`README.md:225`:** the `secure` suite list omits `TestDelegationToken`,
  `TestHttpFSServerWebServer` and `TestRMWebServicesHttpStaticUserPermissions`,
  which `unit-tests.sh:106-116` runs.

## Gaps with no requirement or to-do item

- **A/A noise budget:** nothing defines how much noise an A/A run may report
  before a batch is read; T45/T46 propose it but are not requirements.
- **Attribution tree completeness:** nothing requires every tree of `PR_ORDER`
  to be present; T47 proposes it.
- **Umbrella exit criteria:** no requirement checks "no Jetty 9.4 artifact
  left", JDK 21/25 runs, or a mixed-version client/server run (the plan lists
  the last two as "before phase B").
- **Check 4 one-sided flake:** a test flaky on the baseline and failing on the
  candidate still fails as a regression; there is no rule for it.
- **`impact.py` has no self-test:** R81's list leaves it out, and it is the one
  comparator with no verdict.
- **The `Vary` difference has no JIRA:** the rule says pre-existing but names
  no issue (R67).

## Open items

Confirmed still open, with the confidence each was checked at:

- **T1:** only the HTTP/1.0-without-Host case is used (R94); the malformed
  request line, lowercase method, over-long header and
  `Transfer-Encoding`+`Content-Length` cases are absent (searched `raw` in
  `e2e/scenarios/`). High confidence.
- **T2:** `classload.py:39` still strips the version before comparing. High.
- **T3 evidence part:** the raw class-load and class-resolution lines are not
  kept; only `<daemon>.classes.tsv` is written (`classload.py:77-79`). High.
- **T4:** no per-field counts in `impact.py` or `report.py`. High.
- **T13:** `downstream-deps.sh:64-70` is still the original 14 artifacts. High.
- **T18:** closed by the owner's decision (no automation); nothing to do.
- **T26-T38:** all still open; the runs review's table matches the code (no
  compile/run, no duplicate winner, no exclusion scenario, no `class-gone`, no
  SPI check, counts only for shaded changes, no Hadoop-jar API finding, fixed
  unit lists, `both_fail` ignored in the verdict, history present but not the
  never-failed logic, no `@arch=`, no mixed-version run). High for the ones
  searched; medium for T32/T33, which are "nothing seen" rather than searched.

## The runs review's T39-T49

| Item | Assessment |
|---|---|
| T39 | Extends R93 correctly: R93 records the answers but does not say by value; T39 makes the comparison read them. Not a duplicate. |
| T40 | Extends R90 correctly: R90 compares scope, optional, exclusions, managed versions and parent, not a declared `<version>`. Not a duplicate. |
| T41 | Extends R90 correctly (it fixes R90's output format); it is a defect fix rather than a new behaviour, and it contradicts nothing. |
| T42 | Extends R82 correctly: R82 promises the marker, the code loses it. Not a duplicate. |
| T43 | Extends R39 and R95 correctly: R39 says scan for errors, not class-load lines. Not a duplicate. |
| T44 | Extends R38 and R95 correctly: R38's "another directory" rule needs the per-run path masked. Not a duplicate. |
| T45 | Extends R68 correctly: R68 says the A/A differences are noise to mask or allow; T45 makes that a gate. Needs the owner's decision. |
| T46 | Extends R87 and the T3 extension correctly: R87 leaves the switch to the owner after a batch; T46 defines the condition. Needs the owner's decision. |
| T47 | Extends R89 correctly: R89 checks the trees it is given, not that every tree is present. Not a duplicate. |
| T48 | Corrects rules to satisfy R63 (every rule names its ticket) and needs R65's agreement and R80's replay. It extends no R or T item; it is a rule fix, not a duplicate or a contradiction. |
| T49 | Contradicts R88 as written: R88 says the router's REST and RPC listings "must show" the application and it "must be on exactly one sub-cluster"; T49 would record those three as comparisons. It would need R88 amended, not just extended. |

## Recommended order

1. **T42, T43, T44.** They remove the false failures that make every run red
   for a non-patch reason; all are small and need no decision. Until they land,
   no run's verdict can be read.
2. **T40, T41.** Small, static, and they make check 1's output deterministic
   and complete.
3. **T45 and T47.** Make the A/A run and the attribution report trustworthy
   before the next batch is read. Recommend: yes to both (an A/A run with a
   blocking difference is a harness failure; a missing tree is a problem).
4. **T48** (owner's agreement and a replay), then **T46** (keep
   `CLASSONLY_FAIL` off until an A/A run reports zero unexpected one-side
   classes), then **T39**, which turns the probe into the behaviour check R93
   intended.
5. **T49.** Recommend amending R88: keep the listing expectations, record the
   reads by id as comparisons, and file a YARN issue for the listing that omits
   a directly submitted application.
6. **HADOOP-20014's `LICENSE-binary`.** Not a harness change: remove the two
   stale test-scope entries so check 1 can pass.

## Earlier review

The 2026-11-02 15:36 review's findings, at this commit:

- **R40 threshold:** fixed. The text now says "at least 6 more"
  (`HARNESS-REQUIREMENTS.md:277-278`), which is what `compare_e2e.py:150`
  does.
- **R41 whitespace-only file:** fixed. `compare_e2e.py:79-85` counts non-blank
  lines; the self-test covers the blank-line cases.
- **R54 ancestry verdict:** fixed. `ancestry.py:93` writes PASS/FAIL and
  `report.py:45-52` accepts it. The new R54 gap is the broken-run exit code.
- **R63 broad rules:** still open. `e2e/expected-e2e-differences.txt:46` is
  still the `Vary` rule with no ticket, and the `classjar` rule still does not
  name the destination jar.
- **R79 plan-check defects:** fixed. The deleted-file case is a match
  (`compare_plan.py:244-245`), the text now describes `git merge-file` for one
  branch, and `PR_ORDER` follows the migration plan.
- **R78 whole-blob match:** still open (partly met).
- **Maven exit code:** fixed. `compare_unit.py:134-137` fails a module whose
  Maven run failed on the candidate only.
- **Scenarios that die early:** R82 now records them, but the marker bug (G1)
  makes it report false ones.
- **Late ancestry check:** fixed. The queue job runs both tree checks before
  the wait (`tmpl:137-150`).
- **As PRs land:** fixed. A squash-merged branch is listed as landed
  (`compare_plan.py:131-142`).
- **Plan coverage and the one-sided flake:** still open (see Gaps).

The 2026-11-02 00:12 review's findings:

- **R54 CONTAINED vs PASS:** fixed (above).
- **R78-R80 never in CI:** fixed. `ancestry.md` and `compare-plan.md` are PASS
  in the 2026-11-03 runs, and the queue job runs them.
- **R41 empty results file:** fixed (above).
- **R63 broad rules:** still open.
- **R2 wording:** still open (partly met).
- **R10 symlinks:** still open (partly met).
- **R14 removed class:** still open (partly met).
- **R30 CORS headers:** still open (partly met).
- **R34 masking:** still open (partly met).
- **R37 FIXED/candidate-only not listed:** still open (partly met).
- **R42 test lists:** still open (partly met).
- **R52 NOT RUN:** still open (partly met).
- **R57 existing duplicate:** still open (partly met).
- **R64 unannounced rules:** fixed. The rule files now carry `announced:` for
  every user-visible change (T7/T21).
- **R67 Vary/job-counter issues:** partly fixed. T24 reworded the job-counter
  reason; neither rule names an issue.
- **R69 no verdict assertion:** fixed. `report.py:82-90` and the self-tests
  assert the broken-candidate outcome.
- **R70 per-job PREPARATION:** still open (partly met).
- **R76 PR_BRANCHES default:** still open (partly met).
- **R79 defects:** fixed (above).
- **Pass-to-skipped:** fixed by R45.
- **Maven exit code:** fixed.
- **Scenarios that die early:** R82 added, but G1 breaks it.
- **Late ancestry check:** fixed.
- **Tests for the comparators:** fixed by R81.
- **As PRs land:** fixed.
- **Plan coverage and the one-sided flake:** still open.

## What this review did not cover

- No Maven build, cluster run or CI job was run. The reproductions use the
  harness's own Python modules on synthetic inputs; the CI facts come from the
  runs review's tables and `gh run view` on the run ids it names.
- The raw `observations.jsonl` files, the daemon logs and the downloaded
  reports are not in the inputs, so the exact probe values behind
  `/body/json/mapping/match` and the exact `classload-*.log` lines were not
  seen; the conclusions rest on the comparator code and the runs review.
- The `prefix-5` job's log was not available (`gh run view --log-failed` says
  "log not found"); its failure is confirmed from the job list, and the cause
  ("No space left on device") is the runs review's.
- The 1,593 artifact differences, the class-jar moves and the class-load tables
  were not read row by row; the unexpected rows, the POM rules and the license
  entries were.
- T26-T38 were checked by search and by the runs review, not by reading every
  comparator path they would need.
- No file on the checklist is marked `[!]`.
