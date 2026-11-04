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

# Jetty 12 migration plan (HADOOP-19912)

All status in this document was read from JIRA, GitHub and the fork on
2026-11-02 (the PRs, Yetus and Build) and 2026-11-01 (the rest), against
trunk at `57f78d283ae`. It is a snapshot: JIRA and the PRs
are the source of truth. PR numbers are `apache/hadoop` PRs.

**Where it stands:** none of the 17 subtasks is resolved, nothing is merged,
and no PR in the series has an approval. The code for every subtask exists.
The next bottleneck is review, starting with HADOOP-20012. Stages 1 and 2 have
no red result left that the patches cause: what remains is `test4tests` on
pom-only changes, trunk's SpotBugs debt, Yetus runs to repeat, and
HADOOP-19970's `TestJettyClasspath`, which passes once HADOOP-20014 merges.
See [HADOOP-19970: what it needs to merge](#hadoop-19970-what-it-needs-to-merge).

## Goal

Move Hadoop's web servers off Jetty 9.4, which is end of life (HADOOP-19910,
HADOOP-19915), to Jetty 12.1 on the ee8 environment.

Jetty 12 serves two servlet APIs side by side: ee8 serves `javax.servlet`,
ee10 and ee11 serve `jakarta.servlet`. Choosing ee8 keeps the servlet
namespace, Jersey 2 and every public signature as they are, so downstream
projects need not rebuild. The move to `jakarta` is a separate decision,
HADOOP-19395, which starts after this one. Jetty 12 needs Java 17, so this is
for trunk (3.6.0).

The umbrella is done when:

- no Jetty 9.4 artifact is left anywhere;
- every daemon serves on Jetty 12;
- the full test suite passes;
- the release note lists every incompatible change.

## Approach

The upgrade itself, HADOOP-19972, is incompatible. To keep it reviewable,
everything that also works on Jetty 9.4 lands first as its own small change,
so HADOOP-19972 shrinks to the port. The work runs in stages:

| Stage | Tickets | What it does | Changes behaviour? |
|---|---|---|---|
| 1. One Jetty, declared where used | 20012 to 20016 | Cleans the classpaths and removes Jetty API that Jetty 12 drops | No intended change |
| 2. One servlet API | 19970 | Moves to `jetty-servlet-api` 4.0.9 | No intended change |
| 3. Prepare for what Jetty 12 changes | 20049, 20003 to 20007 | Makes Hadoop independent of Jetty 12's differences, on 9.4 | Refusal details move to the body |
| 4. App catalog | 20008 or 19998 | Takes the last Jetty 9.4 user out of the way | 19998 retires a module |
| 5. Port | 19972 | Jetty 12.1 on ee8 | Yes, incompatible |
| Independent | 19999, 20000 | Guice 6, and drop `jsr311-api` | No intended change |

## Merge order

1. HADOOP-20012 first, as the reviewer asked, then 20014, 20013, 20015, 20016.
2. HADOOP-19970. It must come after 20014: until then `TestJettyClasspath`
   fails on the `jetty-continuation` 9.4.55 that the Jetty Jersey test provider
   brings. Expect one `NOTICE-binary` conflict with 20013.
3. HADOOP-20049. It must land before 19972, which it blocks in JIRA.
4. HADOOP-20003, then 20005, which is stacked on it. Then 20004, 20006 and
   20007. 20004 and 20006 conflict in `TestHttpServer`.
5. HADOOP-20008 or HADOOP-19998, not both. If 19998 retires the catalog,
   20008 and the catalog part of 20012 are unnecessary.
6. HADOOP-19972.

HADOOP-19999 and HADOOP-20000 can land at any time.

## PR tracking

Read this table with the notes below it: most red Yetus votes are not caused by
the patch.

- **Yetus:** the vote in the last `hadoop-yetus` comment, with its date and
  whether it ran on the PR's current head.
- **Build:** the `Build` check on the PR, from the fork's workflow.
- **Approval:** approving reviews. Reviews that only comment are not counted.

| Ticket | JIRA status | Assignee | PR | Yetus | On head? | Build | Approval |
|---|---|---|---|---|---|---|---|
| [HADOOP-20012](https://issues.apache.org/jira/browse/HADOOP-20012) | In Progress | Jose Luis López | [#8890](https://github.com/apache/hadoop/pull/8890) | -1, 11-01 | Yes | Pass | None |
| [HADOOP-20014](https://issues.apache.org/jira/browse/HADOOP-20014) | In Progress | Jose Luis López | [#8892](https://github.com/apache/hadoop/pull/8892) | -1, 11-02 | Yes | Pass | None |
| [HADOOP-20013](https://issues.apache.org/jira/browse/HADOOP-20013) | In Progress | Jose Luis López | [#8891](https://github.com/apache/hadoop/pull/8891) | -1 (patch), 11-01 | Yes | Pass | None |
| [HADOOP-20015](https://issues.apache.org/jira/browse/HADOOP-20015) | In Progress | Jose Luis López | [#8893](https://github.com/apache/hadoop/pull/8893) | -1 (patch), 11-01 | Yes | Pass | None |
| [HADOOP-20016](https://issues.apache.org/jira/browse/HADOOP-20016) | In Progress | Jose Luis López | [#8894](https://github.com/apache/hadoop/pull/8894) | -1 (patch), 11-01 | Yes | Pass | None |
| [HADOOP-19970](https://issues.apache.org/jira/browse/HADOOP-19970) | In Progress | Jose Luis López | [#8699](https://github.com/apache/hadoop/pull/8699), draft | -1, 11-02 | Yes | Fail | None |
| [HADOOP-20049](https://issues.apache.org/jira/browse/HADOOP-20049) | Open | Jose Luis López | [#8903](https://github.com/apache/hadoop/pull/8903) | -1, 11-01 | Yes | Pass | None |
| [HADOOP-20003](https://issues.apache.org/jira/browse/HADOOP-20003) | Open | None | No PR | - | - | - | - |
| [HADOOP-20005](https://issues.apache.org/jira/browse/HADOOP-20005) | Open | None | No PR | - | - | - | - |
| [HADOOP-20004](https://issues.apache.org/jira/browse/HADOOP-20004) | Open | None | No PR | - | - | - | - |
| [HADOOP-20006](https://issues.apache.org/jira/browse/HADOOP-20006) | Open | None | No PR | - | - | - | - |
| [HADOOP-20007](https://issues.apache.org/jira/browse/HADOOP-20007) | Open | None | No PR | - | - | - | - |
| [HADOOP-20008](https://issues.apache.org/jira/browse/HADOOP-20008) | Open | None | No PR | - | - | - | - |
| [HADOOP-19998](https://issues.apache.org/jira/browse/HADOOP-19998) | Open | None | No PR | - | - | - | - |
| [HADOOP-19999](https://issues.apache.org/jira/browse/HADOOP-19999) | Open | None | No PR | - | - | - | - |
| [HADOOP-20000](https://issues.apache.org/jira/browse/HADOOP-20000) | Open | None | No PR | - | - | - | - |
| [HADOOP-19972](https://issues.apache.org/jira/browse/HADOOP-19972) | Open | Jose Luis López | [#8704](https://github.com/apache/hadoop/pull/8704), draft | -1, 10-31 | Yes | Pass | None |

The tickets without a PR have their commit staged on the fork (tag
`staged/<JIRA>`). Their code matches the published `<JIRA>` branch.

### What the red results mean

- **#8890 (20012):** `test4tests` only, on the current head. It is a pom
  change with no test.
- **#8891, #8893, #8894 (20013, 20015, 20016):** the last Yetus run, at
  21:20 on 2026-11-01, three minutes after the heads were pushed, says the
  patch "does not apply to trunk". GitHub reports all three mergeable and
  their Build checks pass, so the run needs repeating; the cause is not
  identified. Before that push, #8893 and #8894 had Yetus +1 and #8891 only
  branch-side SpotBugs (trunk's 80 existing warnings).
- **#8892 (20014):** `test4tests` only, on the current head (2026-11-02).
  The Build check now passes; the earlier failure after the trunk merge did
  not come back.
- **#8699 (19970):** branch-side SpotBugs, as above, and four unit failures,
  all `TestJettyClasspath` (mapred, nodemanager, applicationhistoryservice,
  yarn-common), expected until 20014 merges. `TestCapacityOverTimePolicy`
  no longer fails. Reviewers pjfanning and pan3793 commented earlier; the PR
  was then split into 20012 to 20016.
- **#8903 (20049):** `test4tests` only, on the current head; the
  `TestNameNodeMXBean` failure did not come back after the rebase.
- **#8704 (19972):** branch-side SpotBugs, as above, and one unit failure,
  `TestSSLHttpServerMTLS`, a known intermittent test (HADOOP-19997,
  [#8783](https://github.com/apache/hadoop/pull/8783)). This run is the full
  suite on Jetty 12. It predates 20048 and 20049, and the branch is 4 commits
  behind trunk.

## The subtasks

### Stage 1: one Jetty, declared where used

- **HADOOP-20012, exclude third-party Jetty from tests.** The catalog-webapp and
  timelineservice-hbase tests stop pulling third-party Jetty and the old servlet
  API. Solr's exclusions are declared once, on `solr-test-framework`.
- **HADOOP-20014, run Jersey tests on the JDK HTTP server.** Jersey 2 has no
  container for Jetty 12, so `JerseyTest` must leave Jetty before the upgrade.
  12 module poms switch provider, and `hadoop-client-minicluster` follows.
  Production HTTP is not touched.
- **HADOOP-20013, remove the duplicate `javax.annotation-api`.**
  `jakarta.annotation-api` 1.3.5 is already on the classpath and provides the
  same classes. It updates `LICENSE-binary` and `NOTICE-binary`, and adds
  `TestAnnotationApiClasspath`.
- **HADOOP-20015, declare YARN's Jetty artifacts.** `jetty-webapp` and
  `jetty-servlet` are declared in the modules that use them (yarn-common, RM,
  AHS, Router). It also replaces Jetty's `Log` and `ConcurrentHashSet`, which
  Jetty 12 removes.
- **HADOOP-20016, declare `jetty-http` where it is imported.** Covers
  hadoop-common, HttpFS, the shuffle handler and SLS. It also removes Jetty's
  `Log` and a context cast in `HttpServer2#inferMimeType`.

### Stage 2: one servlet API

- **HADOOP-19970, move to `jetty-servlet-api` 4.0.9.** `HttpServer2` and its
  filters compile against `javax.servlet`, which today arrives only as
  `javax.servlet-api` 3.1.0 through `jetty-server`. This manages one servlet API
  everywhere, declares it in hadoop-common, and adds classpath tests that hold
  one servlet API and one Jetty release in place.

### Stage 3: prepare for what Jetty 12 changes

- **HADOOP-20049, keep slf4j at the managed version.** Jetty 12.1.14 declares
  `slf4j-api` 2.0.17 at compile scope. Consumers that declare `hadoop-yarn-client`,
  `hadoop-hdfs` or `hadoop-hdfs-nfs` before `hadoop-client` would resolve it next
  to the 1.7.36 binding and silently lose all logging. The three modules declare
  `slf4j-api`. Shaded clients are not affected.
- **HADOOP-20003, clients read a refusal's reason from the body.** Jetty 12 sends
  no custom HTTP reason phrase, so clients would see "Unauthorized" instead of
  the real reason. New `ResponseDetail` in hadoop-auth reads a capped amount of
  the error body. Known gap: on Jetty 12, a non-JSON, non-auth 403 from KMS has
  its body consumed by `isAuthenticationFailure`, which affects a proxy in front
  of KMS; KMS's own denials are JSON.
- **HADOOP-20005, write a refused fsimage transfer's reason into the body.**
  `ImageServlet` commits the response before the container can write an error
  page, so a standby or SecondaryNameNode would see a bare status code.
- **HADOOP-20004, send a filter's refusal in the body for every method.** Jetty
  writes error bodies only for GET, POST and HEAD, so a refused PUT or DELETE
  would lose its message. A new request attribute marks these errors, and
  `HttpServer2` installs an error handler for them.
- **HADOOP-20006, clear the charset with the content type.** On Jetty 12,
  `setContentType(null)` leaves the charset behind, and WebHDFS answers
  `application/octet-stream;charset=null`. New `JettyUtils#clearContentType`
  replaces 14 call sites.
- **HADOOP-20007, test what downstream projects rely on.** HBase, Hive, Spark,
  Ozone and Knox compile against hadoop-auth's filters and `HttpServer2`.
  `TestDownstreamServletCompatibility` enforces the `javax.servlet` promise, and
  further tests pin the `HttpServer2` behaviour the port must keep.

### Stage 4: the application catalog

The catalog embeds Solr 8.11.2, which is compiled against Jetty 9.4, so it cannot
share a classpath with Jetty 12.

- **HADOOP-20008, give the catalog its own Jetty version.** New
  `solr.jetty.version`, set to 9.4.58.v20250814, decouples it from Hadoop's
  Jetty. The build still ships Jetty 9.4 inside the catalog, so this alone
  does not satisfy the umbrella's goal.
- **HADOOP-19998, move the catalog off Solr 8 and Jetty 9.4.** The staged commit
  retires the module. Solr 10 would need Java 21 and `jakarta`. Retiring needs
  agreement on the dev list and a release note. The `[DISCUSS]` mail has not been
  sent.

### Stage 5: the port

- **HADOOP-19972, upgrade to Jetty 12 ee8.** Jetty 9.4.58 to 12.1.14. On
  `jetty-phase-c`, the branch carries the prerequisites plus 4 port commits (65
  files, +1166/−445). Assigned, flagged Incompatible, target 3.6.0. The Release
  Note and Fix Version are set at merge. Check for a newer 12.1.x then, and
  reviewers should confirm that `SUSPICIOUS_PATH_CHARACTERS` stays in the default.

### Independent

- **HADOOP-19999, upgrade Guice 5.1.0 to 6.0.0.** Guice 6 accepts both
  `javax.inject` and `jakarta.inject`, and `guice-servlet` 6 still uses
  `javax.servlet`, so it prepares HADOOP-19395 with no namespace change.
- **HADOOP-20000, remove `jsr311-api`.** It duplicates JAX-RS 2.1 on the
  classpath of `hadoop-yarn-server-timelineservice-hbase-tests`.

## Related issues

### Blockers linked to HADOOP-19972 or 19970

| Ticket | Status | PR | Note |
|---|---|---|---|
| HADOOP-19979 | Resolved (Later) | - | |
| HADOOP-19993, HADOOP-19995 | Resolved | | SpotBugs |
| YARN-11993, YARN-12004, MAPREDUCE-7545 | Resolved | | |
| HADOOP-19982 | Patch Available | [#8725](https://github.com/apache/hadoop/pull/8725) | Yetus -1 (SpotBugs, unit); no approval. It is unrelated to Jetty, so it should be Relates, not a blocker. |

### Found while building the harness

None of these blocks the series. Several leave harness checks failing on both
sides.

| Ticket | Status | PR | Yetus | Build | Approval | Effect on the harness |
|---|---|---|---|---|---|---|
| YARN-12030 | Patch Available | [#8841](https://github.com/apache/hadoop/pull/8841) | +1 | Pass | pjfanning, 10-31 | Timeline server picks its JSON writer at random; rules `obsdiff` and T10 change when it lands |
| YARN-12024 | Patch Available | [#8840](https://github.com/apache/hadoop/pull/8840) | +1 | Pass | None | `federated` application checks fail on both sides |
| YARN-12025 | Patch Available | [#8838](https://github.com/apache/hadoop/pull/8838) | +1 | Pass | None | `federated` REST submission fails on both sides |
| YARN-12031 | Patch Available | [#8839](https://github.com/apache/hadoop/pull/8839) | +1 | Pass | None | Related Router work, not cited by the harness |
| YARN-12052 | Open | [#8907](https://github.com/apache/hadoop/pull/8907) | +1 | Pass | None | Timeline v1 field names; references YARN-12030 |
| HADOOP-20018 | Open | [#8873](https://github.com/apache/hadoop/pull/8873), by dajiaohuang | +1 | Awaiting approval to run | None | Worked around by per-ZKFC ports |
| HADOOP-20048 | Open | No PR | - | - | - | Race in `TestHttpServer#testHttpServer2Metrics`, a flaky test in harness runs (T11) |
| MAPREDUCE-7548 | Open | No PR | - | - | - | `secure` compares no MapReduce work (T8) |
| No JIRA yet | - | - | - | - | - | WebHDFS through the RBF router redirects to an address that may be unreachable, and the read fails with 403; worked around by `rpc-bind-host` |

## The harness

The differential harness in this directory (HADOOP-99999) builds trunk and the
combination of 20012 to 20016 and 19970, runs the same checks on both, and fails
on any difference that no rule accepts. See `README.md` and
`HARNESS-REQUIREMENTS.md`.

- **Covers:** stages 1 and 2 only. It does not cover 20049, 20048, the rest of
  stage 3, stage 4 or 19972.
- **Latest runs, batch of 2026-11-03:** on baseline `4f4422ad` and candidate
  `93165486a76`, all five architectures and the A/A run are FAIL, and both
  broken-candidate runs caught their breakage (`Harness check: PASS`). The
  failures are harness defects, not patch defects: a scenario's done marker
  was lost in the two scenarios that run `set --`, class-load log lines were
  read as errors, a container's per-run `job.jar` path counted as a class
  move, and the servlet probe compared only JSON types. T42, T43, T44's
  first and second parts, T39, T40, T41, T45, T47 and T48 fix them; the next
  batch must show them gone. The previous batch (launched 2026-11-01 23:27,
  candidate `bc5d054a`) was all PASS, but it predates R84-R89 and the checks
  that now fail.
- **Now proven when the run gets that far:** the candidate's ancestry against
  the baseline and its change against the PR branches are checked before
  anything is compared, and the run stops when either check fails (R78 to R80
  in the requirements; formerly T5, T16 and T6).
- **Run in the 2026-11-03 batch** (`feat/HARNESS`, R84 to R89): MapReduce
  under Kerberos compares real jobs despite MAPREDUCE-7548, with a control
  job that notices when the fix lands; classes loaded on one side only are
  matched against rules, and can fail the run behind a switch; deterministic
  HDFS client failover; flaky test history from earlier runs; YARN
  federation checks on an application submitted to a sub-cluster directly;
  and attribution runs, which check artifacts, API and downstream resolution
  for each PR branch alone and for each prefix of the merge order. The
  attribution run's `ticket-6` tree is HADOOP-19970 alone, which shows which
  accepted differences are its own; a ticket tree from the second ticket on
  lists an UNEXPECTED difference as an interaction rather than failing, and
  the two POM rules HADOOP-20015 adds are tagged to it (T48). The first
  attribution run listed 9 trees
  because `prefix-5`'s job failed on its runner ("No space left on device");
  T47 now names a missing tree and fails on it, and the tree jobs free the
  runner's preinstalled toolchains.

Its own "phase A" means 20012 to 20016 with 19970, and its "phase B" means the
Jetty upgrade, HADOOP-19972. Neither is the branch `jetty-phase-b`, which is
HADOOP-19971, nor the phases of HADOOP-19395.

## HADOOP-19970: what it needs to merge

HADOOP-19970 can merge when all of these hold:

1. **Its prerequisites are in trunk:** 20012, 20014, 20013, 20015 and 20016,
   in that order. Its own JIRA blockers (MAPREDUCE-7545, HADOOP-19979,
   YARN-12004, YARN-12005) are all resolved; the link "blocked by
   HADOOP-20014" is not made yet.
2. **Its PR is green on its head:** rebased on that trunk, the Build check
   passes and Yetus has no -1 the patch causes. `TestJettyClasspath` passes
   once 20014 is in; branch-side SpotBugs is trunk's debt and is explained on
   the PR.
3. **The harness passes on it** (`dev-support/jetty12-phase-a`):
   - all five architectures pass on the candidate, with the A/A and
     broken-candidate runs green;
   - the attribution run passes: in `ticket-6` (HADOOP-19970 alone) every
     HADOOP-19970 rule matches and any UNEXPECTED difference is listed as an
     interaction (T48), and every prefix tree passes;
   - the detection gaps that bear on what HADOOP-19970 changes are closed
     (implemented as R90-R95; the 2026-11-03 batch is the first to exercise
     them): published POMs (T12), LICENSE and NOTICE consistency (T15), the
     servlet behaviour probe with the HTTP/1.0 default answers (T22, T19),
     the API the new servlet API jar makes available (T23), and class
     loading in container JVMs (T14).
4. **Its release note** says what users see: the servlet API coordinate
   changes from `javax.servlet:javax.servlet-api` 3.1.0 to
   `org.eclipse.jetty.toolchain:jetty-servlet-api` 4.0.9 with the
   `javax.servlet` packages unchanged, the Servlet 4.0 types and methods that
   become available (from T23), and every accepted user-visible difference of
   its own whose rule says `announced: HADOOP-19970 release note`, checked by
   hand (T18).
5. **A committer approves the PR.**

### Course of action

1. **Run what the harness gained** (owner's OK to push the run branches):
   the five architectures, the A/A and two broken-candidate runs, and
   `jetty12-phase-a-attribution-run-1`. The first batch ran on 2026-11-03 and
   failed on harness defects (T42, T43, T44's first part, T39), now fixed;
   run a fresh batch and settle what it shows. Turn on `CLASSONLY_FAIL` only
   when an A/A run reports zero unexpected one-side classes (T46).
2. **Repeat Yetus on #8891, #8893 and #8894**, whose last run could not apply
   the patch, so that all five stage 1 PRs show only `test4tests` or trunk's
   SpotBugs. Then ask for review of #8890 first, as pjfanning asked.
3. **Close HADOOP-19970's detection gaps**, one implementation round each,
   with all five architectures run after each: T12 and T15 (static, no
   cluster), then T23, then T22 with T19, then T14.
4. **Draft HADOOP-19970's release note** from the harness's Impact on users
   and the T23 list, while stage 1 is in review.
5. **When 20014 is in trunk:** rebase HADOOP-19970 on trunk, check Build and
   Yetus on the new head, run the harness on it once more, mark #8699 ready
   for review, and ask the earlier reviewers (pjfanning, pan3793).
6. Then HADOOP-20049, which comes next in the merge order.

## Open items

Owner's actions:

1. Get reviews on #8890 to #8894, starting with #8890.
2. Repeat Yetus on #8891, #8893 and #8894.
3. Send the `[DISCUSS]` mail on retiring the catalog, which decides between 20008
   and 19998.

JIRA changes not yet made:

- On HADOOP-19972: change HADOOP-19982 from blocker to Relates, and link 20003 to
  20008 and 20012 to 20016 as blockers.
- Add HADOOP-19970 blocked by HADOOP-20014, and HADOOP-20005 blocked by
  HADOOP-20003.
- Assign 20003 to 20008 and 19998 to 20000.

After the prerequisites settle, #8704 needs rebuilding on trunk with 20049.

## After this: HADOOP-19395

The `javax` to `jakarta` move (Jetty ee10 or ee11, Jersey 3, JAXB 4) starts only
after HADOOP-19912 lands. HADOOP-19999 prepares it. HADOOP-19971 (`jetty-phase-b`,
draft [#8703](https://github.com/apache/hadoop/pull/8703)) is listed as preparation
but HADOOP-19972 does not depend on it, and it may be revisited or discarded.
