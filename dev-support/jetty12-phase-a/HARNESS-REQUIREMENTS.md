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

The AS-IS list was extracted from the code on `feat/HADOOP-99999` (renamed
`feat/HARNESS` on 2026-11-01) as of
2026-11-01 (after `a82be803`, "record what clients see of an HTTP
response"); each group names the files it comes from.

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

### Build (`build.sh`)

- **R5.** Each side is checked out in its own git worktree and built: the
  binary distribution (`dist`), or only `mvn install` without tests for the
  unit suites (`install`).
- **R6.** A `dist` build also records every module's resolved dependencies
  in all scopes (`dependency:list`, one line per
  `module<TAB>group:artifact:type[:classifier]:version:scope`) and stages the
  Hadoop test code the end-to-end runs reuse (`hadoop-minikdc` with its
  dependencies, the timeline service test jar).
- **R7.** `BUILD_NATIVE=true` builds the native libraries and fails when
  OpenSSL or Snappy support cannot be built.

### Check 1: artifacts and dependencies (`artifact-diff.sh`, `lib/artifact_diff.py`)

- **R8.** Every file of the binary distribution is compared between the two
  sides (`dist-file-added`, `-removed`, `-changed`).
- **R9.** Every entry of every jar and war present on both sides is compared
  by CRC (`jar-entry-added`, `-removed`, `-changed`). A jar nested in a war
  (`WEB-INF/lib`) is compared as one checksum of its own entries.
- **R10.** Entries that differ between any two builds of the same code are
  ignored: `META-INF/MANIFEST.MF`, `META-INF/maven/**/pom.xml` and
  `pom.properties`, `META-INF/DEPENDENCIES`, `*-version-info.properties`,
  `httpfs.properties` and jar signature files; in the distribution, `*.pid`
  files, `logs/` and version-info files.
- **R11.** For each launcher view (`hadoop`, `hdfs`, `yarn`, `mapred` from
  `classpath --glob`; `tools` = mapred plus `share/hadoop/tools`;
  `yarn-timelinereader` = yarn plus `share/hadoop/yarn/timelineservice`;
  `client` = `hadoop-client-api` and `-runtime`; `client-minicluster` = all
  shaded client jars), the classes it can see and the jar each one is first
  loaded from, with its version, are compared (`class-added`,
  `class-removed`, `class-source-changed`).
- **R12.** Every module's resolved dependencies are compared (`dep-added`,
  `dep-removed`; a version change shows as one of each), each tagged `test` or
  `runtime` by its scope.
- **R13.** `artifact-diff.sh <side> <side>` compares a build with itself and
  must report no difference; in CI every fresh build runs it, and the build
  job fails if it does not pass.

### Check 2: API compatibility (`lib/api_compat.py`, `lib/classfile.py`)

- **R14.** Every class that changes is read from its class file, without a
  JVM: classes a launcher loads from another jar or with other bytes, the
  changed classes of jars present on both sides (Hadoop's jars and the
  shaded clients), and both copies of a replaced third-party jar (removed and
  added with classes in common: a new version or a new coordinate, which is
  also what Maven consumers of the non-shaded artifacts get).
- **R15.** **Breaking** findings: `api-class-made-invisible`,
  `api-class-kind-changed`, `api-class-made-final`, `api-class-made-abstract`,
  `api-superclass-changed`, `api-interface-removed`, `api-member-removed`,
  `api-member-visibility-reduced`, `api-member-static-changed`,
  `api-field-type-changed`, `api-method-made-final`.
- **R16.** **Implementor** findings: `api-abstract-method-added` and
  `api-method-made-abstract`. Code that implements or extends the type no
  longer compiles; code already compiled works until the method is called.
- **R17.** **jpms** finding: `jar-module-name-changed`, for each pair of
  jars. The module name is read from `module-info`, then
  `Automatic-Module-Name`, then derived from the file name.
- **R18.** **jre** finding: `jar-class-version-raised` above
  `--max-class-version` (61, Java 17); a raise within the limit is
  information only. Additions are counted, not reported as findings.
- **R19.** Findings in relocated packages (`org.apache.hadoop.shaded.*`)
  and in `@InterfaceAudience.Private` classes are listed but never fail.
- **R20.** Subjects name jars by file name (`old.jar -> new.jar|class#member`,
  or `jar|class#member` for the same jar); one finding seen in several places
  is reported once with its locations.
- **R21.** Behaviour changes inside a method are out of scope for this check;
  checks 3 and 4 cover them.

### Check 3: end to end, five architectures (`e2e/run.sh`, `e2e/cluster.sh`, `e2e/lib/*`, `lib/compare_e2e.py`)

#### Clusters

- **R22.** Real daemons are started from each side's distribution tarball on
  one host, and the same scenarios run against both sides.
- **R23.** Five architectures are covered: `simple` (one of every daemon,
  simple auth over HTTP), `secure` (Kerberos with MiniKdc, HTTPS only with
  SPNEGO, SASL data transfer, delegation tokens), `ha` (ZooKeeper, three
  journalnodes, NN HA with ZKFC, RM HA), `federated` (HDFS federation with
  RBF and ViewFS, YARN federation with router and GPG) and `mixed` (HA and
  non-HA namespaces behind two RBF routers, RM HA).
- **R24.** Every daemon instance has its own configuration directory, pid
  file and log (`HADOOP_IDENT_STRING` is the instance name: `nn1`, `jn2`,
  `rm1`, `router2`, ...), so one host runs several instances of one daemon;
  `start` wipes the architecture's previous state.
- **R25.** The scenarios cover the CLI and class loading through all four
  launchers (00), every daemon's common web endpoints (10), HDFS (20), HDFS
  services: RBF, HttpFS, KMS, NFS (30), YARN (40), MapReduce (50), tools (60),
  security (70), HA failover with `kill -9` (80), federation (85) and the
  mixed topology (90), as listed in `README.md`.
- **R26.** Fail fast: a daemon's readiness wait ends at once when its process
  is gone or its main thread died (KMS and HttpFS keep the JVM alive when
  their web application fails), else after `E2E_START_TIMEOUT` (180 s). Each
  daemon's state is written to `daemons.txt` (`up`, `start-failed`,
  `not-ready`); if any daemon is not up, the scenarios are skipped
  (`aborted.txt`) while logs and class loading are still collected.
- **R27.** `e2e/run.sh` first runs `e2e/lib/test_probe.py`, which checks the
  probe against a local server, and stops if it fails.

#### Observations (`e2e/lib/probe.py`)

- **R28.** Each observation is a JSON line with `ok` (did this side meet the
  expectation), its problems, and `obs`, a normalized view that must be
  identical on both sides. Types: `http`, `raw`, `tls`, `cli`, `assert`.
- **R29.** An HTTP view holds the method, the status and the reason phrase,
  a connection error if any, the headers, the cookie names and attributes
  (not their values), the `Location` path without volatile query parameters
  and how it is written (`location_form`: scheme absolute, network-path,
  absolute-path, relative), the shape of the body (JSON structure, XML
  structure, HTML title and assets, or a checksum or text), and for status 400
  and above the text of the error response (`error_text`: the string leaves of
  a JSON body, `element=text` pairs of an XML body, or the message of an
  HTML or text page).
- **R30.** These header values are compared: `content-type`, the security
  headers (`x-frame-options`, `x-content-type-options`, `x-xss-protection`,
  `strict-transport-security`, `content-security-policy`), the CORS headers,
  `cache-control`, `pragma`, `www-authenticate`, `allow`, `content-encoding`,
  `transfer-encoding`, `vary`, `server` and `accept-ranges`. Every other
  header is compared by name only; `content-length` is ignored. SPNEGO
  tokens in header values are masked.
- **R31.** `probe.py raw` sends a request byte for byte, for what a client
  library refuses or rewrites, and records a server that closes, resets or
  does not answer in HTTP.
- **R32.** A TLS view holds the negotiated protocol and cipher and the
  certificate's subject and alternative names; a server that accepts TLS 1.1
  or older fails the observation.
- **R33.** A CLI view holds the exit code, the shape of its output
  (checksum, text or lines) and the groups captured by its expected regexes
  (for example a computed job checksum), which must match on both sides.
- **R34.** Values that change from run to run are masked in every recorded
  field: application, attempt, container, job, task and block ids, UUIDs,
  numbers of 10 digits or more, timestamps, identity hashes, delegation
  tokens, `elapsedTime`, the side name in paths, IPv4 addresses, this host's
  name and the line numbers of Java stack frames.

#### Comparison (`lib/compare_e2e.py`)

- **R35.** The comparison checks every field of the view (no fixed list of
  fields), so a field added to the probe is compared without changing the
  comparator. Stack-frame line numbers are dropped again before comparing,
  for results recorded before the probe masked them.
- **R36.** Observations are classified: MATCH and DIFF (both sides met the
  expectation; views compared), REGRESSION (met on the baseline only), FIXED
  (met on the candidate only), BOTH_FAIL (views not compared) and MISSING
  (recorded on one side only).
- **R37.** The run fails on an unexpected DIFF, an unexpected REGRESSION, an
  observation recorded only on the baseline, and an observation id recorded
  twice on a side. An observation recorded only on the candidate, FIXED and
  BOTH_FAIL are listed without failing.
- **R38.** Every daemon JVM logs the classes it loads (`-Xlog:class+load`).
  JDK classes and classes generated at run time are left out. A class loaded
  on both sides from a jar with another artifact name or in another directory
  is a difference (`classjar`) and fails the run unless a rule accepts it; a
  jar's version is not part of the comparison. Classes loaded on one side
  only are counted per daemon without failing.
- **R39.** All daemon logs, `.out` files, container logs and scenario logs
  are scanned for class-loading, linkage and JAX-RS provider errors
  (`NoClassDefFoundError`, `ClassNotFoundException`, `NoSuchMethodError`,
  `NoSuchFieldError`, `LinkageError`, `AbstractMethodError`,
  `IncompatibleClassChangeError`, `ExceptionInInitializerError`,
  `UnsupportedClassVersionError`, `ServiceConfigurationError`,
  `IllegalAccessError`, `VerifyError`, `ClassCastException`, message body
  reader or writer not found, `NoContentException`,
  `ModelValidationException`, `WebApplicationException`, "Could not
  instantiate"), with ids and numbers masked.
- **R40.** A log error fails the run when the candidate has it and the
  baseline does not, or the candidate has it more than twice as often and at
  least 6 times more.
- **R41.** If the baseline's daemons did not all start, the architecture is
  NOT RUN; if the candidate's did not, it is FAIL (with the log errors); an
  architecture a side has no observations for (no file, or an empty one) is
  NOT RUN.

### Check 4: Hadoop's own tests (`unit-tests.sh`, `lib/compare_unit.py`)

- **R42.** Existing Hadoop tests run on both trees in suites: `changed` (the
  modules phase A changes plus the HTTP tests of the servers it affects; tier
  `quick` runs the web and Jersey tests, `full` every test, with Hadoop's
  `parallel-tests` profile where a module has it; split in `changed-1` to
  `changed-4` for CI), `secure`, `ha`, `federated`, `mixed` (listed tests in
  both tiers) and `client` (shaded client invariants and
  `hadoop-client-integration-tests`).
- **R43.** A failing test is re-run `UNIT_RERUNS` times (default 1) by
  surefire and failsafe, so it shows as flaky instead of failed; test failures
  do not stop the Maven run.
- **R44.** Results are compared test by test; each test is pass, flaky,
  fail or skipped, and an unparseable report counts as a failed test.
- **R45.** The suite fails on a test that passed or was flaky on the
  baseline and fails on the candidate, on a test that ran (not skipped) on
  the baseline and is missing or skipped on the candidate, and on a module
  with no test reports on a side (except modules that only run checks, such
  as the shaded client invariants, when their Maven run succeeded on both
  sides). With no modules at all it is NOT RUN.
- **R46.** Tests failing on both sides, fixed tests and flaky tests are
  listed without failing.
- **R47.** A test JVM running more than `STALL_AFTER` (600 s) gets periodic
  snapshots of its sockets, TCP counters and threads (`lib/stall-watch.sh`).

### Check 5: what downstream projects resolve (`downstream-deps.sh`, `lib/downstream_classes.py`, `lib/compare_downstream.py`)

- **R48.** One small Maven project per Hadoop artifact and scenario is
  resolved against each side's installed artifacts, offline for Hadoop's own
  (`-nsu`). Artifacts: hadoop-common, hadoop-hdfs-client, hadoop-hdfs,
  hadoop-mapreduce-client-core, -jobclient, -shuffle, hadoop-yarn-api,
  -common, -client, hadoop-client, hadoop-client-api, hadoop-client-runtime,
  and hadoop-minicluster and hadoop-client-minicluster in test scope.
- **R49.** Four scenarios, each declaring one dependency after the Hadoop
  artifact: `plain` (none), `older-jetty` (`DOWNSTREAM_JETTY_CLIENT`, default
  `org.eclipse.jetty:jetty-client:9.4.40.v20210413`), `own-javax-servlet`
  (`DOWNSTREAM_JAVAX_SERVLET`, default `javax.servlet:javax.servlet-api:3.1.0`,
  as HBase declares it) and `own-jakarta-servlet` (`DOWNSTREAM_JAKARTA_SERVLET`,
  default `jakarta.servlet:jakarta.servlet-api:4.0.4`, as Spark and Hive).
- **R50.** Resolved dependencies are compared (`downstream-dep-added`,
  `-removed`, `-changed` with old and new version and scope).
- **R51.** Each project's classpath is scanned for packages whose classes
  more than one jar provides; a new set of such jars (`downstream-dup-added`)
  or a removed one (`downstream-dup-removed`) is a difference, because Maven
  mediates versions of one coordinate only and classpath order then decides
  which copy loads.
- **R52.** The check runs with the `client` suite (the `simple` workflow)
  and in `run-all.sh`. When neither side has results the report has no
  downstream section; when only one side has them the check fails.

### Report (`compare.sh`, `lib/report.py`, `lib/impact.py`)

- **R53.** `compare.sh` deletes the previous comparison first, so nothing
  from an earlier run is reported, then runs every comparison and writes
  `report.md` with a verdict per check and architecture and one section per
  check; the supporting JSON sits next to it.
- **R54.** The overall verdict is **PASS** when every check passes,
  **INCOMPLETE** when every check passes or is NOT RUN, and **FAIL**
  otherwise; `compare.sh` exits 0 only on PASS.
- **R55.** The report names both commits, says when a build was reused and
  from which commit, and says when the run is a harness check (baseline
  against itself, or a deliberately broken candidate with the list of
  changes).
- **R56.** The report starts with **Impact on users**, built from all
  checks, per audience: daemons and applications on the Hadoop classpath,
  users of each shaded client jar (`hadoop-client-api`, `-runtime`,
  `-minicluster`, with how many changed entries are outside the relocated
  packages) and Maven projects in each downstream scenario. It has no verdict
  of its own.
- **R57.** Impact on users lists the projects that had no duplicate classes
  and now have them.
- **R58.** Impact on users lists the accepted user-visible differences
  whose rule has no `announced:` (API findings, downstream differences, and
  changes in the shaded client jars and the lib directories), grouped by rule
  reason.
- **R59.** Every comparison lists the allowlist rules that matched nothing
  (a change the patch should have made did not show up).

### Allowlist rules

- **R60.** There are four allowlists: `expected-differences.txt` (check 1),
  `expected-api-differences.txt` (check 2), `e2e/expected-e2e-differences.txt`
  (check 3) and `expected-downstream-differences.txt` (check 5). Check 4 has
  none: a regression always fails.
- **R61.** A rule is `<kind> <regex>  # reason`; the regex must match the
  whole subject, and a `#` starts the reason only when it is preceded by
  whitespace and followed by whitespace or the end of the line, so a regex
  may contain `#`.
- **R62.** End-to-end rule kinds: `obs` (excuses a DIFF, a REGRESSION or a
  MISSING), `obsdiff` (a DIFF only), `obsfield` (a DIFF when every differing
  JSON path matches a rule), `classjar` (`<daemon>:<class>`) and `logscan`
  (`<source>:<message>`).
- **R63.** Every rule names the ticket that causes the difference, and
  patterns are kept narrow: limited to the entries the patch is meant to
  change.
- **R64.** A rule for a user-visible difference (an API finding, a
  downstream dependency or duplicate, a change in a shaded client or a lib
  jar) says where users are told: `announced: <where>`. A value starting with
  "no" or "not", or no `announced:` at all, counts as not announced.
- **R65.** Rules are not added automatically: differences found by a run are
  analysed against the scope of the tickets (HADOOP-19970, HADOOP-20012 to
  HADOOP-20016), proposed, and added only once the owner agrees.
- **R66.** A proposed rule is replayed against the reports of the runs it is
  meant for before it is committed (`replay.sh`, R80).
- **R67.** Rules for pre-existing, non-deterministic behaviour seen on both
  sides (YARN-12030 timeline JSON writer, `Vary` on static files, job counters
  read mid-run) name the issue and say it is pre-existing.

### Harness self-checks

- **R68.** A run whose two sides are the same commit (in CI, a branch named
  `jetty12-phase-a-<arch>-run-aa-*`) compares the baseline with itself; every
  difference it reports is noise the harness must mask or allow.
- **R69.** A run named `jetty12-phase-a-<arch>-run-broken-<case>-<n>`
  breaks the candidate's distribution on purpose (`ci/break_candidate.py`:
  `annotation`, the default, removes `jakarta.annotation-api`; `jetty`
  removes `jetty-http`; `static` removes the namenode's `hadoop.css`;
  `webhdfs-user` changes a default in `hdfs-default.xml`); its verdict must be
  FAIL. These runs skip the unit jobs, which build from source and cannot see
  the broken distribution.
- **R81.** `compare.sh` first runs `lib/test_comparators.py`, as `e2e/run.sh`
  runs `e2e/lib/test_probe.py`, and stops if it fails, before the ancestry
  check; `run-all.sh` runs it before its builds, and the workflow's queue
  job runs it after checkout and before waiting for earlier runs. The check
  runs each comparator the way the scripts do (`python3 -I <script> ...`) on
  synthetic inputs in a temporary directory, with a throwaway git repository
  for `ancestry.py` (git run without inherited `GIT_*` variables and with
  `core.hooksPath=/dev/null`), and asserts the verdict each writes and its
  exit code, failing with the case name and the comparator's stderr when a
  comparator crashes without writing JSON:
  `compare_e2e.py` (identical observations PASS; a differing observation
  FAILs; a missing or empty `observations.jsonl` is NOT RUN; a DIFF an
  `obs` or `obsdiff` rule matches PASSes, but an `obsdiff` rule does not
  excuse a REGRESSION; an `obsfield` rule matching only some differing
  fields FAILs and one matching every field PASSes; a rule matching only a
  prefix of the subject does not excuse a DIFF; an observation only on the
  baseline, a duplicate observation id, a class loaded from a different jar
  without a `classjar` rule and a new log error on the candidate each FAIL;
  candidate daemons not starting FAILs and baseline daemons not starting is
  NOT RUN);
  `compare_unit.py` (tests passing on both sides PASS; pass to fail, flaky
  to fail, missing or skipped on the candidate FAILs);
  `compare_downstream.py` (identical results PASS; an unmatched difference
  FAILs); `ancestry.py` (candidate contains every baseline commit PASSes;
  a cherry-picked baseline commit PASSes; a baseline commit changing only
  ignored paths PASSes; one the candidate lacks FAILs); and `report.py`
  (all checks PASS; one check FAILs; one NOT RUN and the rest PASS is
  INCOMPLETE). It does not cover `compare_plan.py`, `artifact_diff.py`,
  `api_compat.py` or `impact.py`, which need PR branches or built
  distributions, or have no verdict.

### CI and execution (`.github/workflows/*jetty12_phase_a*.yml`, `ci/*`)

- **R70.** One workflow per architecture, sharing
  `tmpl_jetty12_phase_a.yml`. A run starts on a pushed tag or branch named
  `jetty12-phase-a-<arch>-run-*` (candidate = that commit, baseline =
  `PREPARATION` at that time) or by hand with two refs.
- **R71.** Runs go one at a time across all five workflows, oldest first:
  the first two jobs wait for every earlier harness run (`ci/wait-turn.sh`,
  up to about 11 hours) instead of letting GitHub cancel pending runs.
- **R72.** Both sides are built with the native libraries in Hadoop's build
  image, at the same source path (`BUILD_SRC_DIR`), so native files do not
  differ for identical code. The other jobs run on the plain Ubuntu runner.
- **R73.** Builds are reused between runs by a key made of the side's code
  (every file except the harness and `.github`), the harness files that
  shape the build, the JDK and, for a distribution, the native flag, the
  build image and the build path (`ci/build-key.sh`, `ci/find-build.sh`).
  Builds are kept as artifacts for 7 days, end-to-end results for 14 days and
  reports for 30 days.
- **R74.** A branch named `jetty12-phase-a-simple-run-full-<n>` (or the
  `full` tier by hand) runs the `changed` suite in tier `full`, in four
  shards.
- **R75.** The report goes to the run summary (cut at 900 KB) and, in full,
  to the `report-<arch>` artifact.
- **R76.** The harness also runs on one machine (`run-all.sh`, or each step
  by hand) with the variables documented in `README.md`.
- **R77.** What is not exercised end to end, and what fails on both sides
  because of known issues (MAPREDUCE-7548, YARN-12024, YARN-12025, YARN-12030,
  HADOOP-20018, the SLS configuration bug, the RBF router id, the
  `TestFederationInterceptor#testSubClusterTimeOut` race), is documented
  in `README.md`; a PASS says nothing about those observations.
- **R78.** `compare.sh` first checks that the candidate contains the
  baseline's commits (`lib/ancestry.py`): every baseline commit's change to a
  file outside the harness and `.github/` must be in the candidate's tree.
  When one is not, the candidate was built on an older trunk than the
  baseline (ha-run-4, mixed-run-5 and federated-run-6 failed on 5 `AppsBlock`
  entries this way, YARN-12051), and the comparison stops before running:
  its report names the missing commits and the files they change. A change
  the candidate already has from a merge or cherry-pick counts as contained.
  A merge commit counts against its first parent, as a rebase would replay
  it. Set `ANCESTRY_CHECK=false` to compare anyway. *Formerly T5.*
- **R79.** When `PR_BRANCHES` names the branches merged into trunk, in merge
  order, `compare.sh` also checks that the candidate's change against the
  baseline, without the harness and `.github/`, is exactly their combined
  change (`lib/compare_plan.py`): per file, one branch's change is its tip
  blob applied whole, and several branches' changes are replayed in order as
  three-way merges (`git merge-file`). A file changed on the candidate by no
  branch, a file a branch changes and the candidate does not, or a file whose
  replay does not reproduce the candidate's blob stops the comparison and is
  reported with its kind and the branches that change it. A binary blob
  cannot be merged as text (a branch's change is applied whole) and a
  conflict the candidate resolved by hand does not replay; the intended
  resolutions are listed in the module (`NOTICE_REPLAY`: NOTICE-binary drops
  both tickets' removed lines and keeps the added `jakarta.annotation-api`
  entry) and a file with no entry there counts as a difference. Set
  `PLAN_CHECK=false` to compare anyway. The workflow sets `PR_BRANCHES` to the
  six branches in merge order, so CI runs the check; both checks are skipped
  when the two sides resolve to one commit (a self-comparison run, R68), which
  has no patch for them to check. *Formerly T16.*
- **R80.** `replay.sh` (and `lib/replay.py`) replays every rule file against
  one or more saved compare directories, each matching its rules the way its
  comparison does, without a build or a run, so a new or edited rule is tried
  against the latest report of every architecture before it is committed
  (R66). It lists the rules that matched nothing in any directory (the ones a
  run would report as unused, R59) and the rules that matched in only some
  directories (a pattern that misses an architecture's names: the first
  HADOOP-19970 `classjar` rule's `[a-z]+` missed `nn1`, `jn2`, `rm1`,
  `router2`, `nmsc1`, ... and failed ha-run-3, mixed-run-4 and
  federated-run-5), and exits 1 when a rule matched nothing. *Formerly T6.*

## TO-BE: identified improvements

Identified during the runs and reviews up to 2026-11-01; none is
implemented yet. Each says where it came from.

- **T1. Raw-request scenarios.** `probe.py raw` (R31) is not used by any
  scenario yet. Add raw requests to `10-web-common` against every web server:
  a malformed request line, a lowercase method, an over-long header,
  `Transfer-Encoding` together with `Content-Length`, and HTTP/1.0 without
  `Host`. These are where Jetty 12 behaves most differently from 9.4.
  *Source: review of the new probe fields, secure-run-9.*
- **T2. Jar versions in the class-load comparison.** R38 compares the jar a
  daemon loads a class from by artifact name and directory, without its
  version. A class loaded from a newer release of the same artifact
  (`jetty-server-9.4.x.jar` to `jetty-server-12.x.jar` in phase B) is not a
  difference in what the daemons actually load; only the launcher view of
  check 1 (R11) shows it. Record a version change as its own difference
  (`classjar-version`), with its own rules, so phase B's Jetty upgrade is seen
  per daemon. *Source: requirement extraction from `e2e/lib/classload.py`.*
- **T3. Classes loaded on one side only.** R38 counts them without failing
  and without rules, so a daemon that stops loading a class (a feature that
  no longer initializes) or starts loading another library goes unreported.
  Report them per daemon in the end-to-end section and Impact on users,
  after masking the known noise (T10). Decide with the owner whether they
  should fail without a rule. *Source: requirement extraction from
  `lib/compare_e2e.py`; secure-run-8 timeline server.*

  Extension (2026-11-01): every daemon of every architecture loads
  `javax.servlet.http.HttpServletMapping` on the candidate only, and the
  namenode, the HDFS router and the node manager also `PushBuilder`
  (Servlet 4.0 types, from HADOOP-19970). Most likely the bytecode verifier
  loads them while linking the 4.0 `HttpServletRequest` and
  `HttpServletRequestWrapper`, whose default methods return these types; it
  cannot be confirmed, because only a sorted class list per daemon is kept
  (`<daemon>.classes.tsv`). So:
  - keep, per daemon, the raw `-Xlog:class+load` lines (in load order) of the
    classes loaded on one side only;
  - also log class resolution (`-Xlog:class+resolve=debug`, format to be
    confirmed on the runner's JDK), which names the class that caused each
    resolution and whether the verifier did it, and keep its lines for those
    classes, so the report can say what triggered each one;
  - add a rule kind `classonly <daemon>:<class>` (with reason and
    `announced:`) to accept such a class explicitly instead of letting it
    pass unseen.
  *Source: simple-run-17, secure-run-9, mixed-run-6, federated-run-7.*
- **T4. Report the new probe fields.** The report should say, per
  architecture, how many observations recorded each field (reason phrase,
  header names, `location_form`, `error_text`, raw) and how many differ, so
  a run where they all match still shows they were compared.
  *Source: question "do you use the new info provided by the harness?".*
- **T7. Announce the older accepted differences.** 53 accepted user-visible
  differences have no `announced:` (R58): the shaded test container classes
  in `hadoop-client-minicluster` (HADOOP-20014, 41 + 9 + 2) and the dropped
  duplicate `javax.annotation-api` jar (HADOOP-20013, 1). Either add
  `announced:` with where users are told, or have the JIRAs and release notes
  say it. Needs the owner's decision per ticket.
  *Source: secure-run-8 and later reports.*
- **T8. MapReduce under Kerberos.** In `secure`, 11 MapReduce observations
  fail on both sides (MAPREDUCE-7548), so jobs, job history and the AM's REST
  API under SPNEGO are compared nowhere. Find a harness-side configuration
  that lets the jobs run (for example an ACL entry the MR AM's policy provider
  accepts) while MAPREDUCE-7548 is open, so these checks compare something.
  *Source: secure-run-4, -6, -8, -9.*
- **T9. YARN federation application checks.** In `federated`, 9 observations
  fail on both sides (YARN-12024, YARN-12025); `router-app`,
  `router-app-state`, `router-app-status` and `app-on-one-subcluster` read
  back an application that could not be submitted through the router. Submit
  the application to one sub-cluster's RM directly and read it back through
  the router, so the router's read paths are compared.
  *Source: federated-run-5.*
- **T10. Timeline server class-load noise.** The timeline server loads either
  Jettison/JAXB or Jackson classes depending on the writer chosen at start-up
  (YARN-12030); its classes loaded on one side only flip between runs
  (secure-run-6 and secure-run-8 in opposite directions). Mask these classes,
  as the observations already are (`obsdiff`), so T3 can report the rest.
  *Source: secure-run-8.*
- **T11. Flaky test history.** `TestHttpServer2Metrics#testHttpServer2Metrics`
  (a race in the test, pre-existing) was flaky in three runs, and other tests
  appear flaky in single runs (`TestBlockTokenWithDFSStriped#testEnd2End`,
  `TestFederationInterceptor#testRecover*`, `TestRouterRpc#testNamenodeMetrics`).
  Keep a record of flaky tests across runs in the report, so a test that turns
  flaky only on the candidate stands out. The `TestHttpServer2Metrics` race
  itself is a Hadoop fix, outside the harness.
  *Source: simple runs 14 to 16, federated-run-6, secure-run-9.*

The next items come from analysing the AS-IS requirements against what
HADOOP-20012 to HADOOP-20016 and HADOOP-19970 change (2026-11-01).

- **T12. Published POMs.** R10 ignores `META-INF/maven/**/pom.xml` as build
  metadata, and the installed `.pom` files are not compared, so the declared
  dependencies of the published artifacts are never compared. That is where
  HADOOP-20015 (scope `provided` or `compile`), HADOOP-20016 (`optional`) and
  HADOOP-19970 (exclusions, `dependencyManagement`) make their change; check 5
  sees only its effects, in 4 scenarios for 14 artifacts. Compare, for every
  published artifact, the declared dependencies with their scope, `optional`
  flag and exclusions, the managed versions and the parent, as differences of
  their own kind (`pom-*`) with their own rules.
  *Source: requirements analysis; `lib/artifact_diff.py` `VOLATILE_ENTRY`.*
- **T13. Downstream artifacts the tickets touch.** R48 has none of the
  modules HADOOP-20015 and HADOOP-20016 change as Maven dependencies. Add
  `hadoop-yarn-server-common`, `-resourcemanager`, `-applicationhistoryservice`,
  `-router` and `hadoop-yarn-server-tests` (what MiniYARNCluster users depend
  on), `hadoop-hdfs-httpfs`, `hadoop-sls` and `hadoop-mapreduce-client-app`.
  *Source: requirements analysis; `downstream-deps.sh` `ARTIFACTS`.*
- **T14. Class loading in container JVMs.** Only daemon JVMs log the classes
  they load (R38, `e2e/cluster.sh`). The MapReduce application master (which
  serves a web UI on the servlet API), its tasks and the distributed shell
  application master load `javax.annotation` and `javax.servlet` classes from
  the YARN application classpath, which HADOOP-20013 and HADOOP-19970 change.
  Add `-Xlog:class+load` to their Java options, collect the logs with the
  container logs, and compare by container type with `classjar` rules.
  *Source: requirements analysis; `e2e/lib/conf.sh`.*
- **T15. LICENSE and NOTICE consistency.** HADOOP-19970 and HADOOP-20013 add
  and remove third-party jars; check 1 only reports that `LICENSE-binary`
  changed. On each side, check that every third-party jar in the distribution
  is listed in `LICENSE-binary` (and `NOTICE-binary` where its license needs
  it) and that no jar is listed that the distribution no longer has; a
  mismatch on the candidate only fails the run. This is an ASF release
  requirement. *Source: requirements analysis.*
- **T17. Differences attributed to one ticket.** The tickets merge into trunk
  one at a time and every intermediate trunk state ships, but the harness runs
  only their combination: a rule's ticket is only what its text says, and an
  interaction between tickets is invisible (HADOOP-19970's
  `testSingleJettyRelease` fails without HADOOP-20014). Add per-ticket runs
  (trunk plus one ticket's upstream branch) and runs for each prefix of the
  merge order, limited to checks 1, 2 and 5 (no cluster), and require each
  ticket's rules to match in its own run. Needs the owner's decision.
  *Source: requirements analysis.*
- **T18. Verify `announced:`.** `announced:` is free text (R64); a release
  note can change after the rule is written (HADOOP-19970's was rewritten
  twice). For `announced: <JIRA> release note`, read the JIRA's release note
  field and report rules whose difference (artifact, coordinate, class or
  module name) it does not mention. It reports, it does not fail. Needs the
  owner's decision. *Source: requirements analysis.*
- **T19. Servlet default responses over HTTP/1.0.** HADOOP-19970 swaps the
  classes that build `HttpServlet`'s default answers (405 or 400 for an
  unsupported method, depending on the request's protocol; `Allow` for
  OPTIONS; TRACE; HEAD). The scenarios send them over HTTP/1.1 only. Send an
  unsupported method, OPTIONS and HEAD over HTTP/1.0 to every servlet with
  `probe.py raw` (part of T1). The HTTP/2 difference between servlet API
  4.0.4 and 4.0.9 cannot be reached on Jetty 9.4 and belongs to phase B.
  *Source: requirements analysis.*
- **T20. Tests that exist only on the candidate.** R45 counts a failure as a
  regression only when the test passed or was flaky on the baseline, so a
  test the patch adds is never compared: if it fails on the candidate, the
  run still passes. The tickets add such tests (`TestJettyClasspath` in six
  modules and `TestAnnotationApiClasspath`: 13 tests in simple-run-17, all
  passing). A test that exists only on the candidate and fails there (after
  its re-runs) fails the run; the report lists the candidate-only tests with
  their results. *Source: simple-run-17; `lib/compare_unit.py`.*
- **T21. Consistent announcement of HADOOP-20013's rules.** The same
  HADOOP-20013 change has rules that disagree: the downstream
  `downstream-dup-removed` rule says `announced: HADOOP-20013 JIRA`, while the
  downstream `downstream-dep-removed` rule and the artifact rule for the
  dropped `javax.annotation-api` jar say nothing, so 9 of its differences show
  as accepted but unannounced (61 in simple-run-17, 53 in the runs without the
  downstream check). Give every rule of one ticket and one change the same
  `announced:` value, decided with T7.
  *Source: simple-run-17; `expected-downstream-differences.txt`,
  `expected-differences.txt`.*
- **T22. Servlet behaviour probe.** Loading a class is not a behaviour
  change; what a servlet sees at run time is. Add a small probe servlet,
  compiled and run against each side's Hadoop classpath (as
  `e2e/lib/KerbyKinit.java` is), deployed in an `HttpServer2`, that records as
  observations: the servlet version the context reports
  (`getMajorVersion`/`getMinorVersion`, `getEffectiveMajorVersion`/
  `getEffectiveMinorVersion`); what `getHttpServletMapping()` returns on a
  request; `isPushSupported()` and `newPushBuilder()`; the default
  `HttpServlet` answers (an unsupported method over HTTP/1.0 and HTTP/1.1,
  OPTIONS `Allow`, TRACE, HEAD, which also covers T19 without Hadoop's own
  servlets); and the Servlet 4.0 forward and include request attributes
  (`javax.servlet.forward.mapping`, `javax.servlet.include.mapping`) after a
  `RequestDispatcher` call. It answers, for HADOOP-19970, whether Jetty 9.4
  behaves differently with the 4.0 API on the classpath, and becomes the
  baseline for phase B, when Jetty 12's ee8 environment changes these
  answers. *Source: the Servlet 4.0 classes of T3.*
- **T23. API made available by a replaced jar.** R18 counts additions but
  does not list them. The new servlet API jar adds Servlet 4.0 types
  (`HttpServletMapping`, `MappingMatch`, `PushBuilder`, `GenericFilter`,
  `HttpFilter`, ...) and methods (`HttpServletRequest#newPushBuilder`,
  `getTrailerFields`, ...). Code built against Hadoop's classpath can start to
  use them, then fail with `NoSuchMethodError` or `NoClassDefFoundError`
  where only Servlet 3.1 is present (a downstream project that replaces
  Hadoop's servlet API with `javax.servlet-api` 3.1, or an older Hadoop).
  List the public types and members a replaced third-party jar adds in
  Impact on users, as API that code built against Hadoop may start to depend
  on; the HADOOP-19970 release note says the packages are unchanged, not that
  4.0 types become available. *Source: the Servlet 4.0 classes of T3.*
- **T24. Reason of the job-counter rule.** The `obsfield` rule
  `mapreduce-am:am-job-counters/body/json/jobCounters/counterGroup` gives
  "(MAPREDUCE-7548 under Kerberos)" as its reason, but it also accepts the
  difference in `ha` (ha-run-5), which has no Kerberos: the counters of a
  running job depend on when they are read, in every architecture. Reword the
  reason to the actual cause ("job counters read mid-run depend on timing,
  pre-existing") without MAPREDUCE-7548, so the rule does not claim a cause it
  does not have (R67). A change to an allowlist rule: needs the owner's
  agreement, and a replay (R80) before it is committed.
  *Source: ha-run-5; `e2e/expected-e2e-differences.txt`.*
- **T25. Deterministic client failover order.** In this tree
  `dfs.client.failover.random.order` defaults to `true`, so each HDFS client
  tries a random namenode first, and whichever requests reach the standby are
  deserialized there before they are rejected. In ha-run-5, `nn2` loaded
  different client RPC classes on each side (cache directives and snapshots
  on the baseline; cache pools, snapshot diffs, storage policies and edit
  rolls on the candidate). Nothing fails, but it adds noise to the
  one-side-only class view of T3. Set `dfs.client.failover.random.order=false`
  in the configurations of `ha`, `mixed` and `federated`, so both sides send
  client requests to the active namenode first. It does not change what the
  scenarios check: failover itself is driven by the scenarios.
  *Source: ha-run-5; `hdfs-default.xml`.*

Withdrawn after review: "extract the text of XML error bodies". The probe
already extracts it (R29); the 17 error responses of secure-run-9 with an
empty `error_text` all have an empty body (`jmx-trace`, `conf-bad-name`,
`nn-imagetransfer-noargs`), which their body shape records.

## Next plan

Proposed course of action (2026-11-01), pending the owner's decisions in
step 0. The requirements document comes first: no harness process or allowlist rule changes until the
step that covers it. In step 1, T5, T6 and T16 are implemented (R78 to R80)
and the verdict defects of the review of 2026-11-02 are fixed (R41, R45, R54);
T20 and T24 remain, both needing the owner. The next work is step 2, whose
items need no owner decision.

### Step 0: requirements and decisions (document only)

1. Record T12 to T25 in TO-BE, and the extension of T3 (done).
2. Owner decisions to record here before the steps that need them:
   - T3: should a class loaded on one side only fail the run without a rule?
   - T17: per-ticket and merge-order runs, yes or no?
   - T18: verify `announced:` against the JIRA release notes, yes or no?
   - T7 with T21: how to announce the accepted, unannounced HADOOP-20013 and
     HADOOP-20014 differences (53, or 61 with the downstream check), with one
     `announced:` value per ticket and change (no code needed).

### Step 1: trustworthy verdicts (partly done)

Cheap, and prevents false results like ha-run-3 to -4, mixed-run-4 to -5 and
federated-run-5 to -6. Each run must still end with all five architectures
passing.

Done as AS-IS requirements: T5 as R78, T16 as R79 and T6 as R80 (below).

Fixed after the review of 2026-11-02
(`2026-11-02-Harness-Requirements-Review.md`), whose other findings stay open
there:

- R54: a passing ancestry check no longer turns the overall verdict into FAIL;
  `lib/ancestry.py` writes `PASS` or `FAIL` like every other comparison.
- R41: an empty `observations.jsonl` is NOT RUN, not a PASS.
- R45: a test that ran on the baseline and is skipped on the candidate fails
  the suite. Check 4 has no allowlist, so a skip the patch intends fails too.
- R81: `lib/test_comparators.py` checks the verdicts and exit codes of
  `compare_e2e.py`, `compare_unit.py`, `compare_downstream.py`, `ancestry.py`
  and `report.py`; `compare.sh` runs it first, `run-all.sh` runs it before
  its builds, and the workflow's queue job runs it before waiting; this
  closes the review's "Tests for the comparators" gap.

Still open, both needing the owner's decision:

- T20: fail the run on a failing test that exists only on the candidate.
- T24: reword the job-counter rule's reason (with the owner's agreement,
  replayed with R80).

### Step 2: detection gaps for phase A and HADOOP-19970

- T12: compare the published POMs.
- T13: add the downstream artifacts the tickets touch.
- T14: class loading in container JVMs.
- T15: LICENSE and NOTICE consistency.
- T1 with T19: raw-request scenarios, including HTTP/1.0.
- T22: the servlet behaviour probe.
- T3, evidence part: keep the raw class-load and class-resolution lines of
  the classes loaded on one side only (its reporting part stays in step 4).
- T23: list the API a replaced jar makes available.
- T4: report the new probe fields.

### Step 3: attribution (if decided in step 0)

- T17: per-ticket and merge-order runs.
- T18: verify `announced:`.

### Step 4: pre-existing holes in coverage

- T10 and T25, then T3: mask the timeline server's class-load noise and make
  the client failover order deterministic, then report classes loaded on one
  side only.
- T11: flaky test history.
- T8 and T9: MapReduce under Kerberos and the YARN federation application
  checks. They cost more; they restore coverage that is now zero, but not
  specific to these tickets.

### Before phase B

- T2: jar versions in the class-load comparison (in phase A no artifact
  changes only its version: HADOOP-19970 changes the coordinate, HADOOP-20013
  removes a jar).
- End-to-end runs on JDK 21 and 25 as well as 17 (not yet a TO-BE item).
- A mixed-version scenario: the baseline's clients against the candidate's
  cluster and the other way round (not yet a TO-BE item).

Each step ends with all five architectures run on the result; an item that is
done moves to AS-IS as a new requirement, with its `README.md` update, in the
same commit.

## Changing this document

When a harness change adds, changes or removes a behaviour, update the
matching requirement here and in `README.md` in the same commit. When a
TO-BE item is implemented, move it to the AS-IS list as a new requirement
and say so in the commit message.
