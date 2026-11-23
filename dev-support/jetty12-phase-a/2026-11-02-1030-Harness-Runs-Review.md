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

# Harness runs review: impact on clients and downstream projects, 2026-11-02 10:30

This review reads the latest report of each architecture against
`HARNESS-REQUIREMENTS.md` on `feat/HARNESS` at `adc9b5d9d4a`. It asks one
question: could phase A change something for Hadoop's clients or downstream
projects without the harness reporting it? It is a snapshot. No harness code,
requirement or allowlist rule was changed for it. The proposals continue the
TO-BE numbering at T26. Each one says which existing item it extends, if any.

## Runs reviewed

All five runs compare the same two commits:

- Baseline: `4f4422ad703`.
- Candidate: `bc5d054a991`. This is the baseline plus `HADOOP-20012-upstream`
  to `HADOOP-20016-upstream` and `jetty-phase-a` (HADOOP-19970), 51 files.

`artifact-diff.json` and `api-compat.json` are byte-identical in all five
runs, so checks 1 and 2 are one result. Only checks 3 and 4 depend on the
architecture. Check 5 runs only in `simple` (R52).

| Run | Overall | End to end (match / diff / both fail) | Unit tests |
|---|---|---|---|
| [simple-run-19](https://github.com/joseluisll/hadoop/actions/runs/41362158654) | PASS | 903 / 14 / 0 | PASS, no flaky test |
| [mixed-run-8](https://github.com/joseluisll/hadoop/actions/runs/41362170714) | PASS | 524 / 8 / 0 | PASS, 1 flaky |
| [secure-run-11](https://github.com/joseluisll/hadoop/actions/runs/41362161900) | PASS | 569 / 8 / 11 | PASS, no flaky test |
| [ha-run-7](https://github.com/joseluisll/hadoop/actions/runs/41362164886) | PASS | 567 / 9 / 0 | PASS, no flaky test |
| [federated-run-9](https://github.com/joseluisll/hadoop/actions/runs/41362168160) | PASS | 431 / 8 / 9 | PASS, 1 fixed, 4 flaky |

Every check reports **unexpected: 0** in every run: 1,217 artifact
differences, 11 API findings and 248 downstream differences. No regression
appears in the end-to-end or unit checks, and no log error is new on the
candidate.

## What the runs show

### Impact that is reported

- **HADOOP-19970 accounts for almost every user-visible difference.**
  `javax.servlet-api-3.1.0.jar` and `jakarta.servlet-api-4.0.4.jar` are
  replaced by `jetty-servlet-api-4.0.9.jar` in `share/hadoop/common/lib` and
  `share/hadoop/hdfs/lib`. The change shows up as:
  - 510 `class-source-changed`;
  - 246 dependency changes (159 removed, 87 added);
  - the 8 `common-cli:load.*.javax.servlet.*` differences in every
    architecture.
- **The API findings all come from the servlet jar swap.**
  - 7 `api-abstract-method-added` on `javax.servlet.ServletContext`:
    `addJspFile`, `get`/`setRequestCharacterEncoding`,
    `get`/`setResponseCharacterEncoding` and `get`/`setSessionTimeout`.
  - 2 `jar-module-name-changed`, to `jetty.servlet.api`.
  - The class-file version rises to 55, which is within the Java 17 limit, so
    it is information only.

  The rules mark all 9 blocking findings as "announced: HADOOP-19970 release
  note".
- **Six downstream projects now get two copies of the `javax.servlet`
  packages.** Five are `own-jakarta-servlet` projects, for `hadoop-client`,
  `hadoop-mapreduce-client-core`, `hadoop-mapreduce-client-jobclient`,
  `hadoop-yarn-client` and `hadoop-yarn-common`. The sixth is
  `own-javax-servlet/hadoop-common`. Maven mediated the old jar against the
  project's own copy because they had the same coordinates. The new jar has
  other coordinates, so both copies stay on the classpath.
- **Jetty 9.4 leaves only where phase A intends.**
  - HADOOP-20012 and HADOOP-20014 remove the 9.4.44 test-scope jars of
    `hadoop-yarn-applications-catalog-webapp`.
  - HADOOP-20014 removes `jetty-continuation-9.4.55`,
    `jersey-container-jetty-http` and
    `jersey-test-framework-provider-jetty` from the compile scope of
    `hadoop-client-minicluster`.
- **HADOOP-20015 and HADOOP-20016 change bytecode only.** For example,
  `HttpServer2` in `hadoop-client-api` and `FederationInterceptor` in
  `hadoop-client-minicluster` have new bytecode. In `simple`, all 15 daemon
  web UIs, HttpFS, KMS, WebHDFS, RBF, the job history server and the RM REST
  API match on every observation.
- **61 accepted user-visible differences are not announced (R58).**
  - 52 come from HADOOP-20014: the shaded Jersey test container in
    `hadoop-client-minicluster` moved from Jetty to the JDK HTTP server. That
    is 33 classes and 2 `META-INF/services` files.
  - 9 come from HADOOP-20013: `javax.annotation-api-1.3.2.jar` is dropped from
    `share/hadoop/yarn/lib` and from the downstream resolution.

  T7 and T21 already cover these.

### Noise and flakes

- **Timeline server.** The 4 `yarn-timeline` differences in `simple` come
  from the timeline server's JSON writer (YARN-12030), and so does its
  one-side-only class loading. The timeline server loads 17 classes on the
  baseline only (Jackson) and 61 on the candidate only (JAXB). T10 covers
  this.
- **Vary headers.** `Vary` on static files differs in `simple`. This is
  pre-existing.
- **`TestFederationInterceptor#testSubClusterTimeOut`.** It passed on the
  baseline in both federated runs. On the candidate it failed in
  [federated-run-7](https://github.com/joseluisll/hadoop/actions/runs/41321411417),
  which made that run FAIL, and was flaky in federated-run-9.
  - HADOOP-20015 changes `FederationInterceptor`, but only by replacing
    Jetty's `ConcurrentHashSet` with `ConcurrentHashMap.newKeySet()`. The two
    are equivalent.
  - `README.md` already lists the test's race under "No JIRA yet".
- **Other flaky tests.** Each was flaky or failing on the baseline already,
  except `testRecoverWithAMRMProxyHA`, which was flaky on the baseline and
  passed on the candidate:
  - `TestRouterFaultTolerant#testWriteWithFailedSubcluster` (mixed);
  - `TestFederationInterceptor#testRecoverWithAMRMProxyHA` and
    `#testRecoverWithoutAMRMProxyHA` (federated);
  - `TestViewFileSystemHdfs#testTrashRootsAfterEncryptionZoneDeletion`
    (federated).

### What the runs do not verify

- **secure:** all 11 MapReduce observations fail on both sides
  (MAPREDUCE-7548). The run still passes. T8 covers the fix.
- **federated:** 9 `fed-yarn` observations fail on both sides (YARN-12024,
  YARN-12025). The run still passes. T9 covers the fix.
- **Unit tests:** check 4 runs a hand-made subset. For example, `simple` runs
  73 tests in `hadoop-hdfs`. Evidence for the full suite still comes from
  Yetus.

## Gaps

Each gap below is a way phase A could affect clients or downstream projects
without the harness reporting it.

| # | Seen in | What the run shows | Why it can be missed |
|---|---|---|---|
| G1 | simple-run-19 | 6 projects have new `downstream-dup-added` sets for `javax.servlet` | R51 reports that a duplicate set exists. It doesn't say which copy loads, or whether the copies differ in API |
| G2 | simple-run-19 | `javax.annotation-api-1.3.2` removed from `yarn/lib` and from 3 downstream resolutions | R14 compares replaced jars (removed plus added with classes in common). A jar removed with no replacement is never checked for where its classes now come from |
| G3 | simple-run-19 | `jetty-servlet-api` added to 87 module scopes (52 compile, 33 provided, 2 test) | R42's `changed` suite is a hand-made list of 23 modules. It doesn't cover every module whose classpath changed |
| G4 | simple-run-19 | 2 `META-INF/services` files of `hadoop-client-minicluster` rewritten by HADOOP-20014 | Nothing checks that the providers they name exist, or that a JerseyTest still starts on the shaded jar |
| G5 | simple-run-19 | 248 downstream differences, all from dependency resolution | R48 resolves projects but never compiles or runs one, so a break caused by classpath order cannot show up |
| G6 | simple-run-19 | Downstream scenarios declare a dependency next to Hadoop | No scenario excludes Hadoop's servlet or annotation jar, which Spark, Hive, HBase and Tez commonly do. An exclusion of `javax.servlet:javax.servlet-api` stops matching the new coordinate and nothing reports it |
| G7 | simple-run-19 | `older-jetty` declares `jetty-client` 9.4 only | No scenario declares `jetty-server` or `jetty-servlet` 9.4, or Jersey 1.x, next to Hadoop |
| G8 | all | 3 changed entries of `hadoop-client-api` and 8 of `hadoop-client-minicluster` outside the relocated packages | R56 gives counts. It doesn't say whether the classes are `@Public`, `@LimitedPrivate` (`HttpServer2`) or test code (`FSMainOperationsBaseTest`) |
| G9 | all | Hadoop jars: 0 API findings | Hadoop's own `@Public` and `@LimitedPrivate` signatures that use `javax.servlet` types (`HttpServer2`) now compile against another jar, and nothing lists them |
| G10 | secure-run-11, federated-run-9 | PASS with 11 and 9 observations failing on both sides | R54 gives PASS when a whole component compares nothing |
| G11 | federated-run-7, federated-run-9 | A test passes on the baseline and fails or is flaky on the candidate only | Check 4 has no history (T11). A test that fails only on the candidate, in a class a ticket changed, looks the same as a flake seen on both sides |
| G12 | mixed-run-8, secure-run-11, ha-run-7, federated-run-9 | Rules on lines 37, 45 and 53 of `e2e/expected-e2e-differences.txt` "matched nothing" | R59 cannot tell a rule meant for some architectures from a change that did not happen |
| G13 | all | Each side's daemons are driven by its own client | No run drives one side's daemons with the other side's client, so REST and WebHDFS compatibility between versions is never compared |

## Proposed TO-BE items

### Client and downstream impact

- **T26. Downstream compile-and-run smoke.**
  - For each R49 scenario, compile and run one small program against each
    side's installed artifacts. The program:
    - starts an `HttpServer2` with one filter and one servlet;
    - starts a MiniDFSCluster and a MiniYARNCluster from
      `hadoop-minicluster` in test scope;
    - runs one JerseyTest on the shaded `hadoop-client-minicluster`.
  - Record as observations whether each step succeeds, the servlet version
    the context reports (`getMajorVersion`/`getMinorVersion`) and the jar
    `javax.servlet.ServletContext` was loaded from.
  - Compare them with the check 3 rules.
  - This is the only check that turns a duplicate whose winner depends on
    classpath order (R51) into a pass or a fail.

  *Source: G5; simple-run-19.*
- **T27. Which duplicate wins, and how the copies differ.** For every
  `downstream-dup-added` and `downstream-dup-removed`:
  - report the jar that comes first in Maven's classpath order for that
    project;
  - compare the two copies with check 2's class-file comparison, so a
    duplicate whose winner has the older API is reported as an `implementor`
    or `breaking` impact in Impact on users.

  In `own-javax-servlet`, the project's own `javax.servlet-api` 3.1.0 may win
  over the `jetty-servlet-api` 4.0.9 that Hadoop's poms bring. That is
  harmless on Jetty 9.4. On Jetty 12 ee8 in phase B, which needs Servlet 4.0,
  it would become a `NoSuchMethodError`. Extends R51 and R57.
  *Source: G1; simple-run-19, `own-javax-servlet/hadoop-common`.*
- **T28. Exclusion scenarios.**
  - Add scenarios that exclude `javax.servlet:javax.servlet-api` and
    `jakarta.servlet:jakarta.servlet-api` from the Hadoop artifact, and one
    that excludes `javax.annotation:javax.annotation-api`.
  - An exclusion that removes a dependency on the baseline and matches nothing
    on the candidate is its own difference kind,
    `downstream-exclusion-ineffective`, with its own rules.

  Extends R49 and R50. *Source: G6; simple-run-19, the HADOOP-19970
  `downstream-dep-added`/`-removed` pairs.*
- **T29. More realistic downstream scenarios.** Add:
  - one scenario that declares `org.eclipse.jetty:jetty-server` and
    `jetty-servlet` 9.4 (as HBase and Ranger do);
  - one with Jersey 1.x (`com.sun.jersey:jersey-server` and
    `jersey-servlet`).

  Each version is an overridable variable, as in R49. *Source: G7.*
- **T30. Where removed classes come from now.**
  - For every jar removed from a lib directory (`dist-file-removed`) or from a
    downstream project (`downstream-dep-removed`), list per launcher view and
    per project:
    - the jar that now provides each of its classes;
    - the classes that are no longer provided at all, as their own difference
      kind (`class-gone`).
  - Compare the removed jar with each new provider, as R14 does for a
    replaced jar.

  *Source: G2; HADOOP-20013's `javax.annotation-api-1.3.2.jar`.*
- **T31. SPI integrity of the shaded jars.** On each side, every provider
  that a `META-INF/services` file of a shaded client jar names must be a class
  in that jar or in a dependency it declares. A provider that is missing on
  the candidate only fails the run. *Source: G4; simple-run-19, the
  `ContainerProvider` and `TestContainerFactory` service files of
  `hadoop-client-minicluster`.*
- **T32. Audience of visible shaded changes.** For each changed entry outside
  the relocated packages (R56), the report gives:
  - the class's `@InterfaceAudience` and `@InterfaceStability`, read from the
    class file;
  - or "test", when the class comes from a test jar.

  Impact on users then separates public API from `LimitedPrivate` and test
  code. *Source: G8.*
- **T33. Hadoop API that exposes a replaced jar.**
  - List the `@Public` and `@LimitedPrivate` members of Hadoop's classes whose
    signatures use a type from a replaced or removed third-party jar. For
    phase A that is `HttpServer2` and its `javax.servlet` parameters.
  - List them under Impact on users, for the callers named in
    `@LimitedPrivate`.

  *Source: G9.*

### Verdict and coverage

- **T34. Check 4's modules from check 1.**
  - Every module whose resolved compile or runtime dependencies change (R12)
    runs at least its `quick` tier on both sides.
  - The report lists the modules that changed but were not tested.

  Extends R42. *Source: G3.*
- **T35. Coverage floor.**
  - A component of check 3 with observations that fail on both sides is
    INCOMPLETE, not PASS, unless a rule accepts the hole and names its issue
    (for example MAPREDUCE-7548 or YARN-12024).
  - The report lists accepted holes next to the verdict.

  T8 and T9 remove the holes. This item keeps them visible until then.
  Extends R54. Needs the owner's decision.
  *Source: G10; secure-run-11, federated-run-9.*
- **T36. Tests failing only on the candidate across runs.**
  - For each flaky or failing test, the report shows its baseline and
    candidate results in the last N runs of the same architecture, read from
    the downloaded reports.
  - It marks a test that has never failed on the baseline, and says whether a
    ticket changed the test's class or the class it tests.

  Extends T11. *Source: G11;
  `TestFederationInterceptor#testSubClusterTimeOut` in federated-run-7 and
  federated-run-9.*
- **T37. Rules limited to some architectures.**
  - A rule may end with `@arch=<arch>[,<arch>...]`.
  - R59 then reports "matched nothing" only for the architectures the rule
    names.

  Extends R61 and R59. A change to the allowlist format: the replay (R80)
  must accept it. *Source: G12.*

### Before phase B

- **T38. Mixed client and server versions.**
  - Run the `simple` scenarios with the baseline's client tarball against the
    candidate's daemons, and the candidate's client against the baseline's
    daemons.
  - Compare each with the run that uses one side for both client and daemons.

  Phase A doesn't change wire formats, but it does change the servlet stack
  behind REST, WebHDFS and HttpFS. Phase B changes it much more, so this
  comparison should exist, and pass, before phase B. *Source: G13; R22.*

## Proposed order

1. **T28, T27, T30 and T31.** They are small, need no owner decision, and
   cover the impacts most likely to reach users unreported.
2. **T26, T34 and T35.** They need the most work. T35 changes verdicts and
   needs the owner's decision.
3. **T32, T33, T36 and T37.** They make the report sharper.
4. **T29 and T38.** T29 adds scenarios. T38 is needed before phase B.

## Decisions needed from the owner

- T35: should a component whose observations fail on both sides make the run
  INCOMPLETE?
- T37: may the allowlist format change?
- T26: should the smoke programs live in the harness, like
  `e2e/lib/KerbyKinit.java`, and run in the `simple` workflow with check 5?
