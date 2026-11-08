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
2026-11-06 (morning, UTC+1), against trunk at `c815ec8e1e9`, which is the
merge of HADOOP-20014. It is a snapshot: JIRA and the PRs are the source of
truth. PR numbers are `apache/hadoop` PRs.

**Where it stands:** HADOOP-20014 is the first subtask in trunk (merged
2026-11-05, approved by pan3793). HADOOP-20015 is approved by pan3793 and
waits for Yetus and Build on the head that carries the last review fix.
Every other subtask except HADOOP-19998 now has a PR: nine were opened on
2026-11-05 (20003 to 20008, 19999, 20000, plus HADOOP-20048 outside the
umbrella), so 16 PRs are open in the series. No red result left on any of
them is caused by its patch: what remains is `test4tests` on pom-only
changes, trunk's 80 SpotBugs warnings, flaky tests (HADOOP-19997,
HADOOP-19982, HADOOP-20048), and Yetus runs that have not yet reported on the
current head. HADOOP-19970's only patch-caused failure, `TestJettyClasspath`,
is gone now that HADOOP-20014 is in trunk. The bottleneck is review
capacity, and pan3793 is the one committer engaged. See
[Course of action](#course-of-action-proposal-of-2026-11-06).

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
| 2. One servlet API | 19970 | Moves to `javax.servlet-api` 4.0.1 | No intended change |
| 3. Prepare for what Jetty 12 changes | 20049, 20003 to 20007 | Makes Hadoop independent of Jetty 12's differences, on 9.4 | Refusal details move to the body |
| 4. App catalog | 20008 or 19998 | Takes the last Jetty 9.4 user out of the way | 19998 retires a module |
| 5. Port | 19972 | Jetty 12.1 on ee8 | Yes, incompatible |
| Independent | 19999, 20000 | Guice 6, and drop `jsr311-api` | No intended change |

## Merge order

1. Stage 1: HADOOP-20014 is in trunk. HADOOP-20015 next, since it is approved,
   then 20012 (the one pjfanning asked for first), 20013 and 20016. After the
   2026-11-04 rescope, 20015 (Java changes) and 20016 (pom changes) are
   independent of each other, and the four remaining PRs do not depend on each
   other either. Expect one `NOTICE-binary` conflict between 20013 and 19970.
2. HADOOP-19970. Its `TestJettyClasspath` failures ended with HADOOP-20014.
3. HADOOP-20049. It must land before 19972, which it blocks in JIRA.
4. HADOOP-20003, then 20005, which is stacked on it (#8947 carries both
   commits). Then 20004, 20006 and 20007. 20004 and 20006 conflict in
   `TestHttpServer`.
5. HADOOP-20008 or HADOOP-19998, not both. If 19998 retires the catalog,
   20008 and the catalog part of 20012 are unnecessary.
6. HADOOP-19972.

HADOOP-19999 and HADOOP-20000 can land at any time.

## PR tracking

Read this table with the notes below it: most red Yetus votes are not caused by
the patch.

- **Yetus:** the vote in the last `hadoop-yetus` comment, with its date and
  whether it ran on the PR's current head.
- **Build:** the `Build` check on the PR, from the fork's workflow. "Queued"
  means the fork's run has not started: on 2026-11-06 at 07:00 the fork had
  16 Build runs queued since 2026-11-05 22:10 and the ones that finished took
  about 8.5 hours each.
- **Approval:** approving reviews. Reviews that only comment are not counted.

| Ticket | JIRA status | Assignee | PR | Yetus | On head? | Build | Approval |
|---|---|---|---|---|---|---|---|
| [HADOOP-20014](https://issues.apache.org/jira/browse/HADOOP-20014) | Resolved | Jose Luis López | [#8892](https://github.com/apache/hadoop/pull/8892), merged 11-05 | - | - | - | pan3793 |
| [HADOOP-20015](https://issues.apache.org/jira/browse/HADOOP-20015) | In Progress | Jose Luis López | [#8893](https://github.com/apache/hadoop/pull/8893) | -1, 11-04 | No (head 11-06) | Queued | pan3793, 11-05 |
| [HADOOP-20012](https://issues.apache.org/jira/browse/HADOOP-20012) | In Progress | Jose Luis López | [#8890](https://github.com/apache/hadoop/pull/8890) | -1, 11-06 | Yes | Queued | None |
| [HADOOP-20013](https://issues.apache.org/jira/browse/HADOOP-20013) | In Progress | Jose Luis López | [#8891](https://github.com/apache/hadoop/pull/8891) | -1, 11-05 | No (trunk merged 11-05) | Queued | None |
| [HADOOP-20016](https://issues.apache.org/jira/browse/HADOOP-20016) | In Progress | Jose Luis López | [#8894](https://github.com/apache/hadoop/pull/8894) | -1 (patch), 11-01 | No (rescoped 11-04) | Queued | None |
| [HADOOP-19970](https://issues.apache.org/jira/browse/HADOOP-19970) | In Progress | Jose Luis López | [#8699](https://github.com/apache/hadoop/pull/8699), draft | -1, 11-05 | No (head 11-04, Yetus merged trunk) | Queued | None |
| [HADOOP-20049](https://issues.apache.org/jira/browse/HADOOP-20049) | Open | Jose Luis López | [#8903](https://github.com/apache/hadoop/pull/8903) | -1, 11-06 | Yes | Queued | None |
| [HADOOP-20003](https://issues.apache.org/jira/browse/HADOOP-20003) | Open | None | [#8945](https://github.com/apache/hadoop/pull/8945), draft | +1, 11-06 | Yes | Pass | None |
| [HADOOP-20005](https://issues.apache.org/jira/browse/HADOOP-20005) | Open | None | [#8947](https://github.com/apache/hadoop/pull/8947), draft, stacked on #8945 | none yet | - | Fail (flaky) | None |
| [HADOOP-20004](https://issues.apache.org/jira/browse/HADOOP-20004) | Open | None | [#8946](https://github.com/apache/hadoop/pull/8946), draft | +1, 11-06 | Yes | Queued | None |
| [HADOOP-20006](https://issues.apache.org/jira/browse/HADOOP-20006) | Open | None | [#8948](https://github.com/apache/hadoop/pull/8948), draft | none yet | - | Fail (flaky) | None |
| [HADOOP-20007](https://issues.apache.org/jira/browse/HADOOP-20007) | Open | None | [#8949](https://github.com/apache/hadoop/pull/8949), draft | +1, 11-06 | Yes | Pass | None |
| [HADOOP-20008](https://issues.apache.org/jira/browse/HADOOP-20008) | Open | None | [#8950](https://github.com/apache/hadoop/pull/8950), draft | -1, 11-06 | Yes | Queued | None |
| [HADOOP-19998](https://issues.apache.org/jira/browse/HADOOP-19998) | Open | None | No PR | - | - | - | - |
| [HADOOP-19999](https://issues.apache.org/jira/browse/HADOOP-19999) | Open | None | [#8944](https://github.com/apache/hadoop/pull/8944), draft | none yet | - | Queued | None |
| [HADOOP-20000](https://issues.apache.org/jira/browse/HADOOP-20000) | Open | None | [#8940](https://github.com/apache/hadoop/pull/8940) | -1, 11-05 | Yes | Queued | None |
| [HADOOP-19972](https://issues.apache.org/jira/browse/HADOOP-19972) | Open | Jose Luis López | [#8704](https://github.com/apache/hadoop/pull/8704), draft | -1, 11-05 | No (head 11-06) | Queued | None |

The nine PRs opened on 2026-11-05 come from the generated `<JIRA>` branches
(one commit each on trunk `c815ec8e1e9`). 20003 to 20008 and 19998 to 20000
are still unassigned in JIRA.

### What the red results mean

- **#8893 (20015):** the last Yetus (build 8, 2026-11-04) failed three YARN
  unit modules; the only named test is `TestSubmitApplicationWithRMHA`, which
  the patch does not touch. Since then the head changed twice: the 2026-11-05
  review fixes (`MultiException` out of `HttpServer2`, `MultipleFailuresError`
  in `TestLogAggregationService`, nits) and, on 2026-11-06, pan3793's last
  suggestion to keep `addSuppressed`. pan3793 approved on 2026-11-05. The head
  `7610c8fd644` has no Yetus or Build result yet.
- **#8890 (20012):** `test4tests` only, on the current head (build of
  2026-11-06). It is a pom change with no test.
- **#8891 (20013):** build 6 (2026-11-05) ran the whole root for 434 minutes
  because the patch touches `LICENSE-binary`; it reports trunk's SpotBugs and
  "root in the patch failed" with no named test in the summary. The log shows
  HDFS flakes (`TestDFSClientRetries`, HADOOP-19982's test, `TestBalancerRPCDelay`,
  `TestBlockManager`, `TestFileCreation`, `TestViewFileSystemHdfs`) and a
  ResourceManager surefire fork that died ("The forked VM terminated"). None
  involves `javax.annotation-api`. The head moved on 2026-11-05 23:40 (trunk
  merge), so the run needs repeating anyway.
- **#8894 (20016):** the last Yetus (2026-11-01) is the "does not apply"
  run from before the rescope. The 2026-11-04 head `914b446837b` plus the
  2026-11-06 empty commit `c6aa864bbef` have no Yetus yet; the branch is 4
  commits behind trunk. The fork's Build on the generated `HADOOP-20016`
  branch failed on `TestSSLHttpServerMTLS` only (HADOOP-19997). pan3793
  questioned the module declarations on 2026-11-04 ("I would leverage
  Maven's built-in transitive dependency management"); the answer (the
  declarations are `optional`, downstream resolution is unchanged, and they
  can be dropped if preferred) has had no reply.
- **#8699 (19970):** build 32 (2026-11-05, on Yetus's merge of the head with
  trunk, so with HADOOP-20014 in) shows trunk's SpotBugs and one unit failure,
  `TestYarnNativeServices`, which is unrelated and intermittent.
  `TestJettyClasspath` no longer fails. `jetty-phase-a` still carries its own
  HADOOP-20014 commit, now a 5-line leftover in the minicluster pom, and the
  pre-review version of HADOOP-20015; see [Stage 5](#stage-5-the-port).
- **#8903 (20049):** `test4tests` and `TestNameNodeMXBean` (a known flaky
  test, HDFS-17225 on the fork) on the current head.
- **#8945, #8946, #8949 (20003, 20004, 20007):** Yetus +1 on the head.
  Build passes on 20003 and 20007.
- **#8947 (20005), #8948 (20006):** no Yetus yet. The fork's Build failed on
  `TestZKDelegationTokenSecretManager` (20005) and on
  `TestNamenodeCapacityReport` and `TestDFSInputStreamBlockLocations` (20006),
  all flaky and unrelated.
- **#8950 (20008), #8940 (20000):** `test4tests` only; both are pom changes.
- **#8704 (19972):** build 34 (2026-11-05 15:03, on `bf9bf372ffd`) was the
  first -1 the patch caused since the full-suite run of 2026-10-31:
  `shadedclient` failed because commit `bf9bf372ffd` excluded `jetty-schemas`
  from `hadoop-client`, and `hadoop-client-runtime` shades `hadoop-client`,
  so the web.xml DTDs went missing from the shaded jar and `ITUseMiniCluster`
  failed. `d5f478b2db9` (2026-11-05 17:02) keeps `jetty-schemas` in the shaded
  client. Build 31, which posted after build 34, is the older full run with
  `TestSSLHttpServerMTLS` only. The head `5c47e102dda` has no Yetus yet. The
  fork's Build was green on the broken commit: see
  [The Build workflow and the shaded client](#the-build-workflow-and-the-shaded-client).

## The subtasks

### Stage 1: one Jetty, declared where used

- **HADOOP-20012, exclude third-party Jetty from tests.** The catalog-webapp and
  timelineservice-hbase tests stop pulling third-party Jetty and the old servlet
  API. Solr's exclusions are declared once, on `solr-test-framework`.
- **HADOOP-20014, run Jersey tests on the JDK HTTP server. In trunk since
  2026-11-05 (`c815ec8e1e9`).** Jersey 2 has no container for Jetty 12, so
  `JerseyTest` had to leave Jetty before the upgrade. 12 module poms switched
  provider, and `hadoop-client-minicluster` followed. Production HTTP is not
  touched.
- **HADOOP-20013, remove the duplicate `javax.annotation-api`.**
  `jakarta.annotation-api` 1.3.5 is already on the classpath and provides the
  same classes. It updates `LICENSE-binary` and `NOTICE-binary`, and adds
  `TestAnnotationApiClasspath`.
- **HADOOP-20015, stop using Jetty 9.4 APIs that Jetty 12 removes. Approved.**
  Every use, in main and test code across the repository, of a Jetty 9.4 class
  that Jetty 12 no longer has, where the JDK, SLF4J or the servlet API does the
  same job: Jetty's `Log` in 8 test files (hadoop-common and YARN),
  `ConcurrentHashSet` in `FederationInterceptor`, the borrowed logger in
  `TestDockerCommandExecutor`, `MultiException` in `TestLogAggregationService`
  and in `HttpServer2` (after review: `stop()` collects a `List<Exception>`
  and throws the first with the rest suppressed), and the Jetty context cast
  in `HttpServer2#inferMimeType`. No pom change. The review also settled what
  is left to HADOOP-19972: `RequestLogHandler` is gone in 12.1.14, and
  `WebSocketServlet`, `WebSocketServletFactory`, `HandlerCollection` and
  `SessionHandler` move to the ee8 or `org.eclipse.jetty.session` packages.
- **HADOOP-20016, declare the Jetty artifacts each module imports directly.**
  Every module that imports Jetty classes from an artifact it only receives
  transitively declares that artifact, at the scope it already resolves at:
  `jetty-http` and `jetty-io` are managed in `hadoop-project`; `jetty-http`
  is declared in hadoop-common, the shuffle handler, HttpFS and SLS;
  `jetty-webapp` in yarn-common, RM, AHS and the Router; `jetty-io` in
  hadoop-hdfs; and `jetty-servlet` and `jetty-util` in HttpFS, jobclient, the
  NodeManager, the Router and web-proxy. No Java change. The declarations are
  `optional` (`provided` in SLS) so downstream resolution is unchanged; the
  port does not need them, since `jetty-server` 12 still brings `jetty-http`.
  pan3793 is not convinced by them; the `dependencyManagement` entries are
  what he asked for and are already in the PR.

### Stage 2: one servlet API

- **HADOOP-19970, move to `javax.servlet-api` 4.0.1.** `HttpServer2` and its
  filters compile against `javax.servlet`, which today arrives only as
  `javax.servlet-api` 3.1.0 through `jetty-server`. This manages one servlet API
  everywhere, declares it in hadoop-common, and adds classpath tests that hold
  one servlet API and one Jetty release in place. The coordinate is
  `javax.servlet:javax.servlet-api` 4.0.1 (decided 2026-11-04 with pan3793,
  after a downstream root-POM survey; pjfanning had asked the same on
  2026-10-28), not `jetty-servlet-api` 4.0.9. #8699 carries it since
  2026-11-04 (`2a1ad45a58b`), and the JIRA summary, description and the
  "blocked by HADOOP-20014" link are updated. On Jetty 12 ee8,
  `org.eclipse.jetty.toolchain:jetty-schemas` 4.0.3 supplies the web.xml
  schemas that `javax.servlet-api` does not ship.

### Stage 3: prepare for what Jetty 12 changes

- **HADOOP-20049, keep slf4j at the managed version.** Jetty 12.1.14 declares
  `slf4j-api` 2.0.17 at compile scope. Consumers that declare `hadoop-yarn-client`,
  `hadoop-hdfs` or `hadoop-hdfs-nfs` before `hadoop-client` would resolve it next
  to the 1.7.36 binding and silently lose all logging. The three modules declare
  `slf4j-api`. Shaded clients are not affected. pjfanning was asked to look on
  2026-11-01; no reply.
- **HADOOP-20003, clients read a refusal's reason from the body.** Jetty 12 sends
  no custom HTTP reason phrase, so clients would see "Unauthorized" instead of
  the real reason. New `ResponseDetail` in hadoop-auth reads a capped amount of
  the error body. Known gap: on Jetty 12, a non-JSON, non-auth 403 from KMS has
  its body consumed by `isAuthenticationFailure`, which affects a proxy in front
  of KMS; KMS's own denials are JSON.
- **HADOOP-20005, write a refused fsimage transfer's reason into the body.**
  `ImageServlet` commits the response before the container can write an error
  page, so a standby or SecondaryNameNode would see a bare status code. The
  servlet writes the reason into the body and keeps the phrase through
  `setStatus(int, String)`, without the Jetty cast; `Util#doGetUrl`,
  `TransferFsImage` and `EditLogFileInputStream` read the body through
  `ResponseDetail`. #8947 is stacked on #8945.
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
  `TestDownstreamServletCompatibility` enforces the `javax.servlet` promise and
  pins the `HttpServer2` behaviour the port must keep (absolute redirect
  `Location`, no `/static` listing, odd path segments reaching the servlet,
  `/logs` admin check without `hadoop.log.dir`). The one production change
  sets `relativeRedirectAllowed` explicitly, because Jetty 12 flips its
  default.

### Stage 4: the application catalog

The catalog embeds Solr 8.11.2, which is compiled against Jetty 9.4, so it cannot
share a classpath with Jetty 12.

- **HADOOP-20008, give the catalog its own Jetty version.** New
  `solr.jetty.version`, set to 9.4.58.v20250814, decouples it from Hadoop's
  Jetty. The build still ships Jetty 9.4 inside the catalog, so this alone
  does not satisfy the umbrella's goal. Harmless on its own: app.war ships the
  same Jetty as today.
- **HADOOP-19998, move the catalog off Solr 8 and Jetty 9.4.** The staged commit
  retires the module. Solr 10 would need Java 21 and `jakarta`. Retiring needs
  agreement on the dev list and a release note. The `[DISCUSS]` mail has not
  been sent: common-dev has only the JIRA creation notices for 19998 and
  20008.

### Stage 5: the port

- **HADOOP-19972, upgrade to Jetty 12 ee8.** Jetty 9.4.58 to 12.1.14.
  `jetty-phase-c` (head `5c47e102dda`) is 22 commits on trunk `c815ec8e1e9`:
  the stage 1 and 2 commits (without 20014, which trunk now has), 20049,
  20003 to 20008, and 7 port commits, the last of which (`d5f478b2db9`) keeps
  `jetty-schemas` in the shaded client after Yetus build 34 caught the broken
  `hadoop-client-runtime`. Assigned, flagged Incompatible, target 3.6.0. The
  Release Note and Fix Version are set at merge. Check for a newer 12.1.x
  then, and reviewers should confirm that `SUSPICIOUS_PATH_CHARACTERS` stays
  in the default.

  **The stacked prerequisite commits do not all equal the PRs** (patch-ids
  compared on 2026-11-06): 20003, 20004, 20008, 20016 and 20049 match their
  PR branches; 20005, 20006 and 20007 are the 2026-10-30 versions (20007 is
  two commits on the branch, one squashed commit in #8949); 20015 on
  `jetty-phase-a` and `jetty-phase-c` is the pre-review version (the PR added
  pan3793's fixes on 2026-11-05 and 2026-11-06); and `jetty-phase-a` keeps a
  5-line remnant of its own HADOOP-20014 commit. Both branches need a rebuild
  from the PR branches (`stacked-pr`) before the next harness batch and
  before #8699 is marked ready.

### Independent

- **HADOOP-19999, upgrade Guice 5.1.0 to 6.0.0.** Guice 6 accepts both
  `javax.inject` and `jakarta.inject`, and `guice-servlet` 6 still uses
  `javax.servlet`, so it prepares HADOOP-19395 with no namespace change.
  #8944, draft, waits for its first Yetus.
- **HADOOP-20000, remove `jsr311-api`.** It duplicates JAX-RS 2.1 on the
  classpath of `hadoop-yarn-server-timelineservice-hbase-tests`. #8940, Yetus
  `test4tests` only.

## Related issues

### Linked to HADOOP-19972 or 19970

| Ticket | Status | PR | Note |
|---|---|---|---|
| HADOOP-19979 | Resolved (Later) | - | |
| HADOOP-19993, HADOOP-19995 | Resolved | | SpotBugs |
| YARN-11993, YARN-12004, YARN-12005, MAPREDUCE-7545 | Resolved | | |
| HADOOP-19982 | Patch Available | [#8725](https://github.com/apache/hadoop/pull/8725) | Now "relates to" 19972, as proposed. Yetus -1 (SpotBugs, unit); no approval. Its `TestDFSClientRetries` still fails in other PRs' root runs. |

JIRA now links 20003 to 20008 and 20012 to 20016 as blockers of 19972, and
19970 as blocked by 20014, so the link changes proposed on 2026-11-02 are
made.

### Flaky tests that redden the series' Build and Yetus runs

| Ticket | Status | PR | Yetus | Approval | Seen in |
|---|---|---|---|---|---|
| HADOOP-19997 `TestSSLHttpServerMTLS` | Patch Available | [#8783](https://github.com/apache/hadoop/pull/8783) | +1 since 10-07 | None, reviewers pinged 10-07 | #8704 build 31, Build on `HADOOP-20016` |
| HADOOP-20048 `TestHttpServer#testHttpServer2Metrics` | Open | [#8951](https://github.com/apache/hadoop/pull/8951), draft | +1, 11-06 | None | harness runs (T11) |
| HDFS-17225 `TestNameNodeMXBean` | fork branch, Build pass | - | - | - | #8903 |

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
| MAPREDUCE-7548 | Open | No PR | - | - | - | `secure` compares no MapReduce work (T8) |
| No JIRA yet | - | - | - | - | - | WebHDFS through the RBF router redirects to an address that may be unreachable, and the read fails with 403; worked around by `rpc-bind-host` |

### The Build workflow and the shaded client

Found on 2026-11-05 while diagnosing #8704 build 34, written up in
`2026-11-05-1700-Build-Does-Not-Run-Shaded-Client-ITs.md`. The `Build`
workflow runs `install -DskipTests` and `test`, never `verify`, so the
Failsafe tests of `hadoop-client-integration-tests`, the only tests that use
the shaded jars, never run on GitHub Actions; Yetus runs them through its
`shadedclient` plugin. The workflow is apache/hadoop's own, so every PR that
breaks the shaded client shows the same split. The document proposes one
`verify` step on the three client modules and holds a draft JIRA (not
filed). The harness's `client` unit suite does run them, on both sides.

## The harness

The differential harness in this directory (HADOOP-99999) builds `PREPARATION`
and the combination of 20012 to 20016 and 19970, runs the same checks on both,
and fails on any difference that no rule accepts. See `README.md` and
`HARNESS-REQUIREMENTS.md`.

- **Covers:** stages 1 and 2 only. It does not cover 20049, 20048, the rest of
  stage 3, stage 4 or 19972. `PR_BRANCHES` still lists
  `HADOOP-20014-upstream`; R79 lists a branch already in the baseline as
  landed and does not replay it, so the merge of HADOOP-20014 needs no
  change there.
- **Latest batch, 2026-11-04 00:06** (candidate `4c8d4b2094f`, baseline
  `4f4422ad703`; reviewed in `2026-11-04-1044-Harness-Runs-Review.md`): the
  A/A run, both broken-candidate runs and the second attribution run (10
  trees) PASS. All five architectures FAIL on one difference,
  `probe:probe-base`, which is a probe defect (`mappingJson()` reflected on
  the `"absent"` sentinel), and `federated` also on one unit regression. The
  accepted impact is unchanged since 2026-11-03: 1,593 artifact differences,
  11 API findings (9 blocking, all HADOOP-19970's `ServletContext` and module
  name changes), 248 downstream differences, 0 unexpected anywhere. Note
  that this batch still measured `jetty-servlet-api` 4.0.9; the candidate has
  since moved to `javax.servlet-api` 4.0.1, so the HADOOP-19970 rules and the
  impact text change at the next batch.
- **Since then:** the 2026-11-04 round (T26, T27, T37, T50 to T56) fixed the
  probe and the other findings of the 2026-11-04 11:08 requirements review
  (80 requirements met, 12 partly met, 0 not met), and `feat/HARNESS` was
  rewritten on 2026-11-04 as PREPARATION plus six squashed ticket commits plus
  one harness commit, then merged with PREPARATION on 2026-11-05
  (`fb7c53c2125`). **No batch has run on it.** The next batch is the one that
  must show every architecture PASS, with an A/A and a broken-static run per
  architecture (T56).
- **Open after that batch** (`HARNESS-REQUIREMENTS.md`, "Next plan"): the
  HADOOP-19970 `mapping.match` probe value; `CLASSONLY_FAIL` once an A/A run
  shows zero unexpected one-side classes (T46); the YARN issue for T49's
  router listing; then step 2's detection gaps in order T12 and T15, T23,
  T22 with T19, T14, then T13, T1, T3 evidence, T4.

Its own "phase A" means 20012 to 20016 with 19970, and its "phase B" means the
Jetty upgrade, HADOOP-19972. Neither is the branch `jetty-phase-b`, which is
HADOOP-19971, nor the phases of HADOOP-19395.

## HADOOP-19970: what it needs to merge

HADOOP-19970 can merge when all of these hold:

1. **Its prerequisites are in trunk:** 20014 is. 20012, 20013, 20015 and
   20016 are not. Strictly, only 20014 was a technical prerequisite (the
   `TestJettyClasspath` failures); the others are prerequisites by the
   agreed merge order, so that the servlet API change reviews alone.
2. **Its PR is green on its head:** rebuilt from the current PR branches,
   the Build check passes and Yetus has no -1 the patch causes. Build 32
   already shows only trunk's SpotBugs and an unrelated flaky test.
3. **The harness passes on it** (`dev-support/jetty12-phase-a`):
   - all five architectures pass on the candidate, with the A/A and
     broken-candidate runs green (the next batch);
   - the attribution run passes: in `ticket-6` (HADOOP-19970 alone) every
     HADOOP-19970 rule matches and any UNEXPECTED difference is listed as an
     interaction (T48), and every prefix tree passes (attribution-run-2 did);
   - the detection gaps that bear on what HADOOP-19970 changes are closed
     (R90-R95, exercised since the 2026-11-03 batch): published POMs (T12),
     LICENSE and NOTICE consistency (T15), the servlet behaviour probe with
     the HTTP/1.0 default answers (T22, T19), the API the new servlet API jar
     makes available (T23), and class loading in container JVMs (T14).
4. **Its release note** says what users see: the servlet API version
   changes from `javax.servlet:javax.servlet-api` 3.1.0 to 4.0.1 (same
   coordinate, mediated by Maven) with the `javax.servlet` packages
   unchanged, the Servlet 4.0 types and methods that become available (from
   T23), and every accepted user-visible difference of its own whose rule says
   `announced: HADOOP-19970 release note`, checked by hand (T18). On Jetty 12
   ee8, `org.eclipse.jetty.toolchain:jetty-schemas` 4.0.3 supplies the
   web.xml schemas.

   Draft sentence for the owner (not final): *The servlet API on the
   classpath becomes `javax.servlet:javax.servlet-api` 4.0.1 (the
   `javax.servlet` namespace, the Servlet 4.0 API) instead of 3.1.0. The
   Jetty 9.4 container still reports Servlet 3.1. Code that calls the Servlet
   4.0 methods now finds them; on Jetty 9.4 `getHttpServletMapping()` returns
   a mapping with empty values and `newPushBuilder()` returns null. On Jetty
   12 ee8, `org.eclipse.jetty.toolchain:jetty-schemas` 4.0.3 supplies the
   web.xml schemas.*
5. **A committer approves the PR.**

## Course of action (proposal of 2026-11-06)

The series has moved from "nothing merged, no reviews" to "one merged, one
approved, every PR up". What limits it now is one engaged reviewer and the
fork's Build throughput, so the proposal spends review attention in merge
order and keeps everything else off the reviewer's path.

1. **Finish HADOOP-20015 this week.** It is approved. Wait for Yetus and
   Build on `7610c8fd644`, answer the vote on the PR (the YARN unit failures
   of build 8 were unrelated), and ask pan3793 to commit. Resolve the JIRA
   with a one-line release note (none needed: no behaviour change).
2. **Hand pan3793 the rest of stage 1, one at a time, in this order:**
   #8890 (20012), #8891 (20013), #8894 (20016). Before each ask, make sure the
   PR shows only `test4tests` or trunk's SpotBugs: repeat Yetus on #8891 and
   #8894 (both heads have no run), and justify `test4tests` in the PR body
   where it applies. On #8894, decide the open point now rather than let it
   stall: if pan3793 still prefers transitive resolution, reduce the PR to
   the two `dependencyManagement` entries and drop the module declarations,
   since the port does not need them (recommended: offer that fallback in
   the reply and let pan3793 choose).
3. **Rebuild `jetty-phase-a` and `jetty-phase-c` from the PR branches**
   (`stacked-pr`): drop the 20014 remnant, take 20015 from
   `HADOOP-20015-upstream`, 20005 to 20007 from their `<JIRA>` branches.
   Then mark #8699 ready for review as soon as 20015 is in trunk, and ask
   pjfanning and pan3793, who both reviewed it before. 19970 does not have
   to wait for 20012, 20013 and 20016 technically, and it is the change the
   harness proves; asking early gives the reviewers time while stage 1 lands.
4. **Run one harness batch on the rebuilt `jetty-phase-a`:** the five
   architectures with an A/A and a broken-static run each, and the
   attribution run. Read it against the 2026-11-04 review's open items
   (probe fix, `mapping.match`, `CLASSONLY_FAIL`, the 4.0.1 rules). Then
   draft HADOOP-19970's release note from `impact.md` and the T23 list.
   Do the step 2 detection gaps (T12, T15, T23, T22 with T19, T14) in
   parallel with the review; do not hold the "ready for review" on them.
5. **Get the flaky-test fixes in:** #8783 (HADOOP-19997, Yetus +1 since
   2026-10-07) and #8951 (HADOOP-20048, Yetus +1): un-draft #8951, ask a
   committer for both. They are small, and they are the reason the series'
   Build runs go red.
6. **Stage 3 behind stage 1 in the queue, not in parallel:** un-draft
   #8945 (20003), #8946 (20004) and #8949 (20007), which are green, and get
   Yetus on #8947 and #8948; assign the six JIRAs. Ask for review only once
   #8699 is in review, so the reviewer sees one topic at a time. #8903
   (20049) goes right after 19970.
7. **Decide stage 4 now:** send the `[DISCUSS]` mail on retiring the catalog
   (HADOOP-19998). Independently, #8950 (20008) is harmless and can land any
   time; if the list agrees to retire, close 20008 as Won't Fix instead.
8. **HADOOP-19972:** wait for Yetus on `5c47e102dda` (the `jetty-schemas`
   fix); rebuild on the PR branches with step 3; keep it draft until 20049
   and stage 3 are in. File the Build-coverage JIRA from the 2026-11-05
   draft, so `verify` on the client modules runs in the project's workflow,
   not only in Yetus.
9. **Fork Build throughput:** with 16 runs queued and 8.5-hour runs, "Build
   pending" will outlast most Yetus runs. Options: cancel the queued runs of
   branches with no PR, or trigger Build only on `feat/` pushes that are
   about to become a PR. This is an owner decision; the plan assumes Yetus
   is the vote reviewers read.
10. **HADOOP-19395 and HADOOP-19971:** no action. #8703 is green (Yetus +1,
    2026-11-04) and independent, but asking for its review now competes with
    stage 1 for the same reviewer, and the 2026-10-05 position was to revisit
    or discard it. Re-evaluate after 19972 lands.

## Open items

Owner's actions:

1. Ask pan3793 to commit #8893, then review #8890, #8891, #8894 in that order.
2. Repeat Yetus on #8891 and #8894 (no run on the current heads).
3. Reply to pan3793 on #8894 with the fallback (dependencyManagement only).
4. Send the `[DISCUSS]` mail on retiring the catalog (HADOOP-19998).
5. OK the rebuild and force-push of `jetty-phase-a` and `jetty-phase-c`, and
   the next harness batch.
6. Un-draft #8945, #8946, #8949, #8951 once their Build is green; get Yetus
   on #8947, #8948, #8944.

JIRA changes not yet made:

- Assign 20003 to 20008 and 19998 to 20000.
- On HADOOP-19972: the description's "Depends on" list should name 20049
  and 20003 to 20008, 20012 to 20016 as JIRA links do.
- File the Build-coverage improvement from
  `2026-11-05-1700-Build-Does-Not-Run-Shaded-Client-ITs.md`.
- File the WebHDFS-through-router redirect issue found by the harness.

## After this: HADOOP-19395

The `javax` to `jakarta` move (Jetty ee10 or ee11, Jersey 3, JAXB 4) starts only
after HADOOP-19912 lands. Its JIRA (updated 2026-10-04) sizes it at 3,368
Java EE references in 44 modules and 86 Public or LimitedPrivate classes, and
splits it into Phase A on trunk (HADOOP-19971, HADOOP-19625 dependency map,
HADOOP-20001 compatibility policy for the dev list, HADOOP-20002 inventory
script and OpenRewrite recipe; HADOOP-19861, hadoop-cos annotations, is Shilun
Fan's, #8421) and Phase B on a feature branch, B1 to B7 by module group, merged
by vote. Open decisions: ee10 or ee11, deprecate or break, branch or one
change. Of the five subtasks, only 19971 and 19861 have a PR; 19625, 20001 and
20002 are unassigned and have no activity since 2026-10-04. HADOOP-19999
prepares it.

HADOOP-19971 (`jetty-phase-b`, draft [#8703](https://github.com/apache/hadoop/pull/8703),
10 commits on trunk `c815ec8e1e9`, head `3c65eae0ddb`, Yetus +1 on 2026-11-04)
removes servlet and Jetty types from the secret providers, `CertificateUtil`,
the shuffle handler and the YARN services client. It depends on nothing, and
nothing in HADOOP-19972 depends on it. The plan is to land it with or just
before the namespace change in HADOOP-19395, in the next major release. When it
is rebased after HADOOP-20016 lands, drop the shuffle module's `jetty-http`
declaration (it comes from HADOOP-20016 as optional and from HADOOP-19972, not
from HADOOP-19970); the change then touches 17 files and includes one dependency
change. The servlet API move in HADOOP-19970 does not affect it. If
HADOOP-19972 has landed, re-check the shuffle headers and the `user.name`
encoding against whatever Jetty classes it left in those two places. It works
on Jetty 9.4 and on the Jetty 12 ee8 environment, and commits the namespace
change to neither ee10 nor ee11.
