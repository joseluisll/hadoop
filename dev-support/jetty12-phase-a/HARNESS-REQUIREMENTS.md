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

# Jetty 12 phase A harness: requirements

This document lists what the differential harness in this directory does
(**AS-IS**, implemented) and the improvements identified so far that are not
implemented yet (**TO-BE**). `README.md` explains how to run the harness and
read its report; this document states each behaviour as a numbered
requirement, so that a change to the harness can say which requirement it
adds, changes or removes.

Status of the AS-IS list: the harness on `feat/HADOOP-99999` as of 2026-11-01
(after `a82be803`, "record what clients see of an HTTP response").

## AS-IS: implemented requirements

### Purpose and principles

- **R1.** The harness compares a **baseline** tree (default `PREPARATION`:
  apache trunk plus the fork's `.github`) with a **candidate** tree (the
  phase A patch) and reports every difference between them.
- **R2.** A difference the patch is meant to cause is accepted only by a
  rule in an allowlist; every other difference fails the run.
- **R3.** The goal is to find what the patch changes for Hadoop's users that
  its JIRA, its PR or its release note does not say: unexpected changes, and
  impact on clients and downstream projects.
- **R4.** The same checks run on both sides with the same harness code, so
  a difference comes from the trees, not from the harness.

### Check 1: artifacts and dependencies (`artifact-diff.sh`, `lib/artifact_diff.py`)

- **R5.** Every file of the binary distribution is compared between the two
  sides (`dist-file-added`, `-removed`, `-changed`).
- **R6.** Every entry of every jar and war of the distribution is compared
  by CRC (`jar-entry-added`, `-removed`, `-changed`), so identical code shows
  as identical.
- **R7.** Build timestamps and version-info files are ignored, so two builds
  of the same code report no difference.
- **R8.** For each launcher (`hadoop`, `hdfs`, `yarn`, `mapred`, tools,
  timeline reader, shaded client, shaded minicluster), the set of classes its
  real classpath can see (`classpath --glob`) and the jar each class is first
  loaded from are compared (`class-added`, `class-removed`,
  `class-source-changed`).
- **R9.** Every module's resolved dependencies, in all scopes
  (`dependency:list`), are compared.
- **R10.** `artifact-diff.sh candidate candidate` compares a build with
  itself and must report no differences.

### Check 2: API compatibility (`lib/api_compat.py`, `lib/classfile.py`)

- **R11.** Every class that changes is read from its class file, without a
  JVM: classes the launchers load from another jar or with other bytes, the
  changed classes of jars present on both sides (Hadoop's jars and the
  shaded clients), and both copies of a replaced third-party jar (a new
  version or a new coordinate, which is also what Maven consumers of the
  non-shaded artifacts get).
- **R12.** Removed or less visible classes and members, final, static or
  kind changes, and a changed superclass or field type are **breaking**
  findings.
- **R13.** Abstract methods added to an interface or abstract class are
  **implementor** findings (`api-abstract-method-added`): code that
  implements or extends the type no longer compiles.
- **R14.** A changed JPMS module name is a **jpms** finding
  (`jar-module-name-changed`). The module name is read from `module-info`,
  then `Automatic-Module-Name`, then derived from the file name.
- **R15.** A class file for a newer Java than `--max-class-version` (61,
  Java 17) is a **jre** finding (`jar-class-version-raised`); a raise within
  the limit is information only.
- **R16.** Findings in relocated packages (`org.apache.hadoop.shaded.*`)
  and in `@InterfaceAudience.Private` classes are listed but never fail.
- **R17.** Subjects name jars by file name (`old.jar -> new.jar|class#member`),
  and one finding seen in several places is reported once with its locations.
- **R18.** Behaviour changes inside a method are out of scope for this check;
  checks 3 and 4 cover them.

### Check 3: end to end, five architectures (`e2e/run.sh`, `lib/compare_e2e.py`)

- **R19.** Real daemons are started from each side's distribution tarball on
  one host, and the same scenarios run against both sides.
- **R20.** Five architectures are covered: `simple` (one of every daemon,
  simple auth over HTTP), `secure` (Kerberos with MiniKdc, HTTPS only with
  SPNEGO, SASL data transfer, delegation tokens), `ha` (ZooKeeper, three
  journalnodes, NN HA with ZKFC, RM HA), `federated` (HDFS federation with
  RBF and ViewFS, YARN federation with router and GPG) and `mixed` (HA and
  non-HA namespaces behind two RBF routers, RM HA).
- **R21.** Every daemon instance has its own configuration directory, pid
  file and logs (`HADOOP_IDENT_STRING` is the instance name: `nn1`, `jn2`,
  `rm1`, `router2`, ...), so one host runs several instances of one daemon.
- **R22.** The scenarios cover the CLI and class loading through all four
  launchers (00), every daemon's common web endpoints (10), HDFS (20), HDFS
  services: RBF, HttpFS, KMS, NFS (30), YARN (40), MapReduce (50), tools (60),
  security (70), HA failover (80), federation (85) and the mixed topology (90),
  as listed in `README.md`.
- **R23.** Each observation records whether its expectation held and a
  normalized view that must be identical on both sides.
- **R24.** For an HTTP response the view holds the method, the status and
  the reason phrase, the content type, the values of the security headers,
  the names of the other headers, the cookie names and attributes (not their
  values), the `Location` path and whether it is absolute (`location_form`),
  the JSON/XML/HTML shape of the body, and for status 400 and above the text
  of the error response (`error_text`).
- **R25.** For TLS the view holds the protocol, the cipher and the
  certificate; for a CLI call its exit code; for a job the checksums of its
  deterministic output.
- **R26.** `probe.py raw` can send a request byte for byte, for what a
  client library refuses or rewrites, and records a server that closes,
  resets or does not answer in HTTP.
- **R27.** Host names, addresses and the line numbers of Java stack frames
  are masked in every recorded field, so an error page with a stack trace does
  not differ only because a jar was recompiled.
- **R28.** `e2e/run.sh` first runs `e2e/lib/test_probe.py`, which checks the
  probe against a local server, before it starts a cluster.
- **R29.** The comparison checks every field of the view (no fixed list of
  fields), so a field added to the probe is compared without changing the
  comparator.
- **R30.** Observations are classified MATCH, DIFF, REGRESSION (held on the
  baseline, not on the candidate), MISSING (only on the baseline), BOTH_FAIL
  and FIXED.
- **R31.** Every daemon JVM logs the classes it loads; a class loaded from a
  different jar on the candidate is a difference (`classjar`).
- **R32.** All daemon and container logs are scanned for class-loading,
  linkage and JAX-RS provider errors; an error new on the candidate, or more
  than twice the baseline's count and at least 6 more, fails the run.
- **R33.** An observation id recorded twice on a side fails the run.
- **R34.** Fail fast: a daemon whose process exits or whose main thread dies
  is reported at once; if any daemon is not up after start-up, the scenarios
  are skipped, logs and class loading are still collected, and the result is
  FAIL for the candidate and NOT RUN for the baseline.
- **R35.** An architecture a side has no observations for is NOT RUN, and
  the run is not a PASS.

### Check 4: Hadoop's own tests (`unit-tests.sh`, `lib/compare_unit.py`)

- **R36.** Existing Hadoop tests run on both trees in suites by architecture:
  `changed` (the modules phase A changes, tiers `quick` and `full`, split in
  `changed-1` to `changed-4` in CI), `secure`, `ha`, `federated`, `mixed` and
  `client` (shaded client invariants and `hadoop-client-integration-tests`).
- **R37.** Results are compared test by test; each test is pass, flaky
  (failed, then passed on a re-run), fail or skipped.
- **R38.** A test that passed or was flaky on the baseline and fails on the
  candidate is a regression and fails the run; a test missing on the
  candidate fails the run; a module with no test reports on a side fails the
  run.
- **R39.** Tests failing on both sides, fixed tests and flaky tests are
  listed without failing the run.
- **R40.** A test JVM running more than 600 s gets periodic snapshots of its
  sockets, TCP counters and threads (`lib/stall-watch.sh`).

### Check 5: what downstream projects resolve (`downstream-deps.sh`, `lib/compare_downstream.py`)

- **R41.** One small Maven project per published Hadoop artifact
  (hadoop-common, the HDFS, MapReduce and YARN clients, hadoop-client, the
  shaded clients, the miniclusters) is resolved against each side's installed
  artifacts.
- **R42.** Four scenarios are resolved: `plain`, `older-jetty` (next to an
  older Jetty client), `own-javax-servlet` (next to
  `javax.servlet:javax.servlet-api:3.1.0`, as HBase declares it) and
  `own-jakarta-servlet` (next to `jakarta.servlet:jakarta.servlet-api:4.0.4`,
  as Spark and Hive declare it); the coordinates can be overridden with
  `DOWNSTREAM_JAVAX_SERVLET` and `DOWNSTREAM_JAKARTA_SERVLET`.
- **R43.** Added, removed and changed dependencies are compared
  (`downstream-dep-added`, `-removed`, `-changed`).
- **R44.** Each project's classpath is scanned for packages whose classes
  more than one jar provides (`lib/downstream_classes.py`); a new set of
  such jars (`downstream-dup-added`) or a removed one (`downstream-dup-removed`)
  is a difference, because Maven mediates versions of one coordinate only and
  classpath order then decides which copy loads.
- **R45.** The downstream check runs with the `client` suite (the `simple`
  workflow) and in `run-all.sh`; the report has its section only when it ran.

### Report (`compare.sh`, `lib/report.py`, `lib/impact.py`)

- **R46.** `report.md` has an overall verdict, a verdict per check and
  architecture, and one section per check; supporting JSON sits next to it.
- **R47.** The overall verdict is PASS only when every check passes; any
  check that is NOT RUN makes the run not a PASS.
- **R48.** The report starts with **Impact on users**, built from all checks,
  per audience: daemons and applications on the Hadoop classpath, users of
  each shaded client jar (`hadoop-client-api`, `-runtime`, `-minicluster`),
  and Maven projects in each downstream scenario. It has no verdict of its
  own.
- **R49.** Impact on users lists the projects that had no duplicate classes
  and now have them.
- **R50.** Impact on users lists the accepted user-visible differences
  whose rule has no `announced:` (API, downstream, shaded client jars and lib
  jars), grouped by rule reason.
- **R51.** The report lists the allowlist rules that matched nothing (a
  change the patch should have made did not show up).
- **R52.** The report says when a build was reused and from which commit.

### Allowlist rules

- **R53.** There are four allowlists: `expected-differences.txt` (check 1),
  `expected-api-differences.txt` (check 2), `e2e/expected-e2e-differences.txt`
  (check 3) and `expected-downstream-differences.txt` (check 5).
- **R54.** A rule is `<kind> <regex>  # reason`; the regex must match the
  whole subject, and a `#` starts the reason only when it is preceded by
  whitespace and followed by whitespace or the end of the line, so a regex
  may contain `#`.
- **R55.** End-to-end rule kinds: `obs`, `obsdiff` (excuses a DIFF, never a
  REGRESSION), `obsfield` (excuses a DIFF when every differing JSON path
  matches), `classjar` (`<daemon>:<class>`) and `logscan`.
- **R56.** Every rule names the ticket that causes the difference, and
  patterns are kept narrow: limited to the entries the patch is meant to
  change.
- **R57.** A rule for a user-visible difference (an API finding, a
  downstream dependency or duplicate, a change in a shaded client or a lib
  jar) says where users are told: `announced: <where>`. A value starting with
  "no" or "not" counts as not announced.
- **R58.** Rules are not added automatically: differences found by a run are
  analysed against the scope of the tickets (HADOOP-19970, HADOOP-20012 to
  HADOOP-20016), proposed, and added only once the owner agrees.
- **R59.** A proposed rule is replayed against the reports of the runs it is
  meant for before it is committed.
- **R60.** Rules for pre-existing, non-deterministic behaviour found on both
  sides (YARN-12030 timeline JSON writer, `Vary` on static files, job counters
  read mid-run) name the issue and are marked pre-existing.

### Harness self-checks

- **R61.** A run named `jetty12-phase-a-<arch>-run-aa-*` compares the
  baseline with itself; every difference it reports is noise the harness must
  mask or allow.
- **R62.** A run named `jetty12-phase-a-<arch>-run-broken-<case>-<n>` breaks
  the candidate's distribution on purpose (`ci/break_candidate.py`: cases
  `annotation`, `jetty`, `static`, `webhdfs-user`); its verdict must be FAIL.

### CI and execution

- **R63.** One workflow per architecture, sharing
  `.github/workflows/tmpl_jetty12_phase_a.yml`; a run starts by pushing a
  branch or tag named `jetty12-phase-a-<arch>-run-<n>` (candidate = that
  commit, baseline = `PREPARATION` at that time), or by hand with two refs.
- **R64.** Both sides are built with the native libraries in Hadoop's build
  image, at the same source path (`BUILD_SRC_DIR`), so native files do not
  differ for identical code.
- **R65.** Builds are reused between runs by a key made of the side's code
  (without the harness and `.github`), the harness files that shape the
  build and the JDK, stored as artifacts for 7 days.
- **R66.** A `full` tier (`jetty12-phase-a-simple-run-full-<n>`) runs every
  test of the modules phase A changes; other suites run their listed tests in
  both tiers.
- **R67.** The harness also runs on one machine (`run-all.sh`, or each step
  by hand) with the variables documented in `README.md`.
- **R68.** What is not exercised end to end, and what fails on both sides
  because of known issues (MAPREDUCE-7548, YARN-12024, YARN-12025, YARN-12030,
  HADOOP-20018, the SLS configuration bug, the RBF router id), is documented
  in `README.md`; a PASS says nothing about those observations.

## TO-BE: identified improvements

Identified during the runs and reviews up to 2026-11-01; none is
implemented yet. Each says where it came from.

- **T1. Raw-request scenarios.** `probe.py raw` (R26) is not used by any
  scenario yet. Add raw requests to `10-web-common` against every web server:
  a malformed request line, a lowercase method, an over-long header,
  `Transfer-Encoding` together with `Content-Length`, and HTTP/1.0 without
  `Host`. These are where Jetty 12 behaves most differently from 9.4.
  *Source: review of the new probe fields, secure-run-9.*
- **T2. Error text of XML error bodies.** 17 of the 94 error responses in
  secure-run-9 recorded an empty `error_text`. Some have no body (`jmx-trace`,
  405), but `conf-bad-name` (404, `text/xml`) has one and nothing is
  extracted, so a change in that body would go unseen. Extract the text of
  XML (and other) error bodies, and record an empty body explicitly.
  *Source: secure-run-9 observations.*
- **T3. Report the new probe fields.** The report should say, per
  architecture, how many observations recorded each field (reason phrase,
  header names, `location_form`, `error_text`, raw) and how many of them
  differ, so a run where they all match still shows they were compared.
  *Source: question "do you use the new info provided by the harness?".*
- **T4. Candidate built on a different trunk than the baseline.** ha-run-4,
  mixed-run-5 and federated-run-6 failed on 5 `AppsBlock` entries because the
  candidate branch lacked a trunk commit (YARN-12051) that the baseline
  (`PREPARATION` at run time) had. Before comparing, check that the
  candidate contains the baseline's trunk commits; if not, stop with a clear
  verdict that names the missing commits, instead of reporting them as
  differences caused by the patch.
  *Source: ha-run-4, mixed-run-5, federated-run-6.*
- **T5. Validate rules against every architecture's daemon names.** The
  first HADOOP-19970 `classjar` rule matched daemon names with `[a-z]+` and
  missed the numbered instances (`nn1`, `jn2`, `rm1`, `router2`, `nmsc1`, ...),
  which failed ha-run-3, mixed-run-4 and federated-run-5. Make the replay of
  R59 a script in the harness that checks a rule file against the latest
  report of every architecture, and use it before committing rules.
  *Source: ha-run-3, mixed-run-4, federated-run-5.*
- **T6. Announce the older accepted differences.** 53 accepted user-visible
  differences have no `announced:` (R50): the shaded test container classes
  in `hadoop-client-minicluster` (HADOOP-20014, 41 + 9 + 2) and the dropped
  duplicate `javax.annotation-api` jar (HADOOP-20013, 1). Either add
  `announced:` with where users are told, or have the JIRAs and release notes
  say it. Needs the owner's decision per ticket.
  *Source: secure-run-8 and later reports.*
- **T7. MapReduce under Kerberos.** In `secure`, 11 MapReduce observations
  fail on both sides (MAPREDUCE-7548), so jobs, job history and the AM's REST
  API under SPNEGO are compared nowhere. Find a harness-side configuration
  that lets the jobs run (for example an ACL entry the MR AM's policy provider
  accepts) while MAPREDUCE-7548 is open, so these checks compare something.
  *Source: secure-run-4, -6, -8, -9.*
- **T8. YARN federation application checks.** In `federated`, 9 observations
  fail on both sides (YARN-12024, YARN-12025); `router-app`,
  `router-app-state`, `router-app-status` and `app-on-one-subcluster` read
  back an application that could not be submitted through the router. Submit
  the application to one sub-cluster's RM directly and read it back through
  the router, so the router's read paths are compared.
  *Source: federated-run-5.*
- **T9. Timeline server class-load noise.** The timeline server loads either
  Jettison/JAXB or Jackson classes depending on the writer chosen at start-up
  (YARN-12030); its class-load comparison flips between runs (secure-run-6
  and secure-run-8 in opposite directions). Mark or mask these classes in
  `classload-compare-*.json`, as the observations already are (`obsdiff`), so
  a real class-load change of the timeline server is not hidden in the noise.
  *Source: secure-run-8.*
- **T10. Flaky test history.** `TestHttpServer2Metrics#testHttpServer2Metrics`
  (a race in the test, pre-existing) was flaky in three runs, and other tests
  appear flaky in single runs (`TestBlockTokenWithDFSStriped#testEnd2End`,
  `TestFederationInterceptor#testRecover*`, `TestRouterRpc#testNamenodeMetrics`).
  Keep a record of flaky tests across runs in the report, so a test that turns
  flaky only on the candidate stands out. The `TestHttpServer2Metrics` race
  itself is a Hadoop fix, outside the harness.
  *Source: simple runs 14 to 16, federated-run-6, secure-run-9.*

## Changing this document

When a harness change adds, changes or removes a behaviour, update the
matching requirement here and in `README.md` in the same commit. When a
TO-BE item is implemented, move it to the AS-IS list as a new requirement
and say so in the commit message.
