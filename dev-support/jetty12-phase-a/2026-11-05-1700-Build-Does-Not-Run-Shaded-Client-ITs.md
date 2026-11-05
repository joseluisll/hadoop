<!---
  Licensed to the Apache Software Foundation (ASF) under one
  or more contributor license agreements.  See the NOTICE file
  distributed with this work for additional information
  regarding copyright ownership.  The ASF licenses this file
  to you under the Apache License, Version 2.0 (the
  "License"); you may not use this file except in compliance
  with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License. See accompanying LICENSE file.
-->

# The Build workflow does not run `verify`, so it cannot see a broken shaded client

Found on 2026-11-05 while diagnosing apache/hadoop#8704 (HADOOP-19972). Every
fact below is from the run of that PR: Yetus build 34 on `4eed8b2dd2a`
(<https://ci-hadoop.apache.org/job/hadoop-multibranch/job/PR-8704/34/>), its
artifacts `branch-shadedclient.txt` and `patch-shadedclient.txt`, and the Build
run <https://github.com/apache/hadoop/runs/126919996783>, which was green on the
same commit.

## Verdict

**The Build workflow and Yetus do not test the same thing, and this is not
limited to the fork.** The `build-and-test` job runs three Maven goals, none of
which reaches `verify` on the shaded client modules:

```
Build:  ./mvnw $MAVEN_ARGS clean install -DskipTests
Build:  ./mvnw $MAVEN_ARGS ${{ matrix.modules }} clean install -am -DskipTests
Test:   ./mvnw $MAVEN_ARGS ${{ matrix.modules }} test \
          -Dsurefire.excludesFile=$PWD/.github/gha-tests/exclude-tests.txt
```

(`.github/workflows/tmpl_build_and_test.yml:175`, `:308`, `:311`.) `install` and
`test` stop before the `integration-test` and `verify` phases, so the Failsafe
tests of `hadoop-client-integration-tests` — the only tests that exercise the
shaded jars from a downstream point of view — never run on GitHub Actions. Yetus
does run them, through its `shadedclient` plugin, which invokes `verify` on the
three `hadoop-client-modules` test modules.

The result is a class of defect that only Yetus can catch, and a branch can sit
green on Build for hours while its shaded client jars are broken.

## Why this matters for 2026-11-05's failure

HADOOP-19972 adds `org.eclipse.jetty.toolchain:jetty-schemas` because Jetty 12's
ee8 `WebDescriptor` resolves the `web.xml` DTDs and schemas through
`javax.servlet.Servlet.class.getResource("resources/...")` — that is, from inside
whichever jar owns the relocated `Servlet.class`. In the shaded
`hadoop-client-runtime` jar that jar is the shaded one, so `jetty-schemas` must be
shaded into it next to `org/apache/hadoop/shaded/javax/servlet/`.

Commit `032e8f1` then added an exclusion of `jetty-schemas` to `hadoop-client`'s
`hadoop-common` dependency, on the reading that "nothing a client uses" needs it.
`hadoop-client-runtime` shades `hadoop-client`, so the exclusion propagated into
the shaded jar, and the DTDs went missing from it. On the patch side Yetus
reported:

```
java.io.IOException: Unable to initialize WebAppContext
Caused by: java.lang.IllegalStateException: Unable to add catalog:
  hadoop-client-runtime-3.6.0-SNAPSHOT.jar!/org/apache/hadoop/shaded/org/eclipse/jetty/ee8/webapp/catalog-ee8.xml
Caused by: java.io.FileNotFoundException: Unable to find ref
  [org/apache/hadoop/shaded/javax/servlet/resources/web-app_2_2.dtd]
  in same archive as org.apache.hadoop.shaded.javax.servlet.Servlet
```

`ITUseMiniCluster` failed both tests, and the branch (pre-patch) side of the same
step was `+1` with all five tests passing. The commit message of `032e8f1` cites
`TestHttpServer` and `TestJettyClasspath` as evidence — both pass, because they
run on hadoop-common's unshaded test classpath where `jetty-schemas` is still
present. Nothing in Build could disagree with that conclusion.

That is the shape of the gap: a change to the shaded client's contents is checked
by Build only for "does it compile and can the invariants be listed", never for
"can a downstream program use it".

## Scope

- **Not fork-only.** `tmpl_build_and_test.yml` is on `PREPARATION`/trunk; the
  three goals above are apache/hadoop's own. Any apache/hadoop PR that breaks the
  shaded client will show the same split.
- **Not a Yetus defect.** Yetus is doing the right thing here.
- **Not about the 80 extant SpotBugs warnings.** Those are a separate, known
  Yetus-only signal and are not part of this report.
- **Covered, in part, by the Jetty 12 phase A harness.** `unit-tests.sh` has a
  `client` suite that runs exactly these three modules with `verify`
  (`dev-support/jetty12-phase-a/unit-tests.sh:136-151`; the suite is also listed
  in `README.md:253`), and the simple-architecture workflow passes
  `["changed","client"]` as its default unit suites
  (`jetty12_phase_a_simple.yml`). In the latest simple run
  (`jetty12-phase-a-simple-run-21`), `client/hadoop-client-integration-tests` is
  `5/0/0/0` on both sides. So the failure would have been caught by a harness run
  on the right pair of sides, but the harness is Jetty-migration infrastructure on
  the fork, not the gate that runs on every push, and it compares two commits
  rather than gating one.

## What should change

Three options, in increasing cost. The first is what this report proposes.

1. **Make Build run the client integration tests.** Add one step to the
   `build-and-test` job that runs `verify` on
   `hadoop-client-integration-tests` (and the two invariant modules) after the
   existing `install`. It is one Maven invocation, needs no new image, and it is
   the same command Yetus already runs:

   ```
   ./mvnw $MAVEN_ARGS verify -pl hadoop-client-modules/hadoop-client-integration-tests \
     -am -Dtest=NoUnitTests -Dmaven.javadoc.skip=true \
     -Dsurefire.excludesFile=$PWD/.github/gha-tests/exclude-tests.txt
   ```

   The `ITUseMiniCluster` class starts a MiniDFS and a MiniYARN cluster; that is
   why it is a Failsafe test and not a Surefire one. In the Yetus log the whole
   `verify` of the three client modules plus the 40-module reactor it needs took
   11m42s, and `ITUseMiniCluster` itself took 28s when it passed. On a build
   machine that has already installed the tree, the added step is much shorter.

2. **Run `verify` rather than `test` for the client modules** in the existing
   matrix entry (`-pl :hadoop-client-integration-tests` is already in the list at
   `:284`). This changes one goal in one step and needs no new step, but it makes
   the whole matrix entry slower and less obviously targeted.

3. **Leave Build as it is and make the client suite a required harness run**
   before any `jetty-phase-*` PR is merged. Cheaper for apache/hadoop, but the
   gap remains for every other change to the shaded clients.

Whichever is chosen, the fix belongs in apache/hadoop, not in the fork: the fork's
workflows are regenerated from the fork's own files, and a fork-only guard would
hide the problem from the project.

## Draft JIRA issue

**Type:** Improvement
**Component:** build
**Affects version:** 3.6.0
**Fix version:** 3.6.0
**Assignee:** (unset — first person to pick it up)
**Labels:** test-coverage, shaded-client

### Summary

Build workflow does not run the shaded client integration tests

### Description

`hadoop-client-integration-tests` holds the only tests that exercise the shaded
`hadoop-client-api`, `hadoop-client-runtime` and `hadoop-client-minicluster` jars
the way a downstream program uses them: `ITUseHadoopCodecs` and
`ITUseMiniCluster` start a MiniDFS and a MiniYARN cluster from those jars and
perform real reads and writes over HDFS and WebHDFS.

They are Failsafe tests, so they run in the `integration-test` and `verify`
phases. The GitHub Actions `build-and-test` job stops at `install` and `test`
(`.github/workflows/tmpl_build_and_test.yml`), so they never run there, even
though the job's matrix already includes
`-pl :hadoop-client-integration-tests`.

Precommit (Yetus) does run them, through its `shadedclient` plugin, which
invokes `verify` on `hadoop-client-check-invariants`,
`hadoop-client-check-test-invariants` and `hadoop-client-integration-tests`. A PR
can therefore be green on Build and red on Yetus for a defect in the shaded
client jars, and be merged on the strength of the green Build.

This was observed on apache/hadoop#8704 (HADOOP-19972): a `jetty-schemas`
exclusion in `hadoop-client` removed the `web.xml` DTDs from the shaded
`hadoop-client-runtime` jar, so every `WebAppContext` failed with "Unable to find
ref [org/apache/hadoop/shaded/javax/servlet/resources/web-app_2_2.dtd] in same
archive as org.apache.hadoop.shaded.javax.servlet.Servlet". Build run
<https://github.com/apache/hadoop/runs/126919996783> was green on that commit;
Yetus build 34
(<https://ci-hadoop.apache.org/job/hadoop-multibranch/job/PR-8704/34/>) was `-1`
on `shadedclient`.

### Acceptance criteria

- The `build-and-test` job runs the Failsafe tests of
  `hadoop-client-integration-tests` on every push it already builds.
- A change that removes a resource the shaded client needs (the `jetty-schemas`
  exclusion above is the reproduction) makes the job fail.
- The added runtime is reported in the PR; the class takes a few minutes on a
  loaded Yetus worker and less on a GHA runner.

### Reproduction

On any tree that has HADOOP-19972's ee8 artifacts, add to
`hadoop-client-modules/hadoop-client/pom.xml`, in the `hadoop-common`
dependency's exclusions:

```xml
<exclusion>
  <groupId>org.eclipse.jetty.toolchain</groupId>
  <artifactId>jetty-schemas</artifactId>
</exclusion>
```

Then `./mvnw --batch-mode -fae -am clean verify -pl
hadoop-client-modules/hadoop-client-integration-tests -Dtest=NoUnitTests
-Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true` fails in
`ITUseMiniCluster`'s `BeforeEach`, while `clean install -DskipTests` and `test`
(build's goals) succeed.

## What the harness already covers, and the requirement it suggests

`unit-tests.sh`'s `client` suite is the check that would have caught this, and it
is already in the default unit-suite list of the phase A workflows. Two
observations for `HARNESS-REQUIREMENTS.md`:

1. The client suite compares the two sides test by test, so a failure present on
   **both** sides does not fail the run (the report above shows
   `client/hadoop-client-integration-tests | 5/0/0/0 | 5/0/0/0`, a match). That
   is the intended design for a no-functional-change harness, but it means a
   candidate-only regression is what gets caught, not a baseline that was already
   broken. Worth stating explicitly next to the `client` row of "What is
   checked".
2. The harness runs `verify` for the client suite only because of a special case
   (`[[ "${suite}" == client ]] && goal=verify`). A future suite that needs
   Failsafe tests to run must remember the same special case; a per-suite goal
   field in the `SUITE_*` entries would remove the trap.
