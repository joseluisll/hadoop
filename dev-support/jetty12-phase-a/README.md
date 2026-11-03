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

# Jetty 12 migration, phase A: no-functional-change harness

Phase A (HADOOP-20012 to HADOOP-20016 and HADOOP-19970, combined as
HADOOP-99999) prepares the move to Jetty 12 / EE8 without changing what Hadoop
does. It only changes dependencies:

| JIRA | Change | Where it can show |
|---|---|---|
| HADOOP-20012 | catalog-webapp and timelineservice-hbase tests stop pulling third-party Jetty and the old servlet API | test classpath |
| HADOOP-20013 | duplicate `javax.annotation-api` 1.3.2 removed; `jakarta.annotation-api` 1.3.5 provides the same `javax.annotation` classes | runtime classpath of every daemon, LICENSE/NOTICE |
| HADOOP-20014 | Jersey test container moves from Jetty to the JDK HTTP server; `hadoop-client-minicluster` shades it, declares `jetty-util` and excludes `com.sun.net.httpserver` (neither changes the jar) | test classpath, shaded minicluster jar |
| HADOOP-20015 | `jetty-webapp`/`jetty-servlet` declared in YARN common, RM, AHS, router | runtime classpath of YARN daemons |
| HADOOP-20016 | `jetty-http` declared in hadoop-common, HttpFS, shuffle (optional, so not passed on to dependents), SLS (provided) | runtime classpath |
| HADOOP-19970 | moves to `jetty-servlet-api` 4.0.9 | test classpath, runtime classpath of web servers, LICENSE/NOTICE |

This harness builds the tree without the patch (**baseline**, default
`origin/PREPARATION`) and with it (**candidate**, default
`origin/feat/HARNESS`), runs the same checks on both, and reports every
difference. Differences the patch is meant to cause are listed, with the
JIRA that causes them, in allowlists; anything else fails the run. The
point is to find what the patch changes for Hadoop's users that its JIRA,
PR or release note does not say: each rule's reason names the ticket and,
for user-visible changes, where users are told (`announced: <where>`), and
the report lists the accepted changes nobody was told about.

## What is checked

1. **Artifacts and dependencies** (`artifact-diff.sh`)
   - every file in the binary distribution, and every entry of every jar on
     both sides, by CRC (build timestamps and version-info files ignored), so
     identical code shows as identical;
   - the set of classes each launcher's real classpath can see
     (`hadoop`/`hdfs`/`yarn`/`mapred classpath --glob`, tools, timeline
     reader, shaded client, minicluster) and the jar each class is first
     loaded from;
   - every module's resolved dependencies, all scopes (`dependency:list`);
   - every published POM's declared dependencies with their scope,
     `optional` flag, declared `<version>` (resolved from the POM's
     properties; a dependency with none is managed elsewhere) and exclusions,
     its managed versions and its parent, read from git for both refs
     (`pom-dependency-*`, `pom-managed-*`, `pom-parent-changed`,
     `pom-unparseable`, R90). A `pom-dependency-changed` detail lists the
     fields with the exclusions sorted, so two runs of one build write the
     same bytes. The dependency-reduced POMs the shaded
     clients publish are generated at build time and are not compared;
   - `LICENSE-binary` and `NOTICE-binary`: every third-party jar in the
     distribution is listed and every listed coordinate exists, and a jar new
     on the candidate that ships its own `META-INF/NOTICE*` is named in
     `NOTICE-binary` (R91). A mismatch on the candidate only fails the run; a
     mismatch on both sides is listed as pre-existing.
2. **API compatibility** (`lib/api_compat.py`, run by `artifact-diff.sh`):
   every class that changes, read from the class files (no JVM): the classes
   the launchers load from another jar or with other bytes (what the daemons
   run), the changed classes of jars on both sides (Hadoop's jars and the
   shaded clients) and both copies of a replaced jar (a third-party version
   or coordinate change, which is also what Maven consumers of the
   non-shaded artifacts get). It classifies what breaks code built against
   the old classes: removed or less visible classes and members, final,
   static or kind changes, a changed superclass or field type (breaking);
   abstract methods added to interfaces and abstract classes (code that
   implements or extends them no longer compiles); a changed JPMS module
   name; class files for a newer Java than `--max-class-version` (61, Java
   17). Relocated packages (`org.apache.hadoop.shaded.*`) and
   `@InterfaceAudience.Private` classes are listed but do not fail.
   Where a third-party jar is replaced (a jar removed on the candidate whose
   packages another added jar provides), it also lists the public types the
   added jar has and the removed one did not, and the public members added to
   types both have, in `api-compat.json`/`.md` and summarised in Impact on
   users as API code built against Hadoop may start to use (R92); the list
   does not change the verdict.
   Allowlist: `expected-api-differences.txt`. Behaviour changes inside a
   method are left to checks 3 and 4.
3. **End to end, in five architectures** (`e2e/run.sh`): real daemons
   started from each side's distribution tarball on one host, the same
   scenarios run against both sides. Each observation records whether the
   expectation held and a normalized view (HTTP status and reason phrase,
   content type, security headers, the names of the other headers, cookie
   attributes, whether a `Location` is absolute, JSON/XML shape, the text of
   an error response, HTML title and assets, TLS protocol and cipher, CLI exit
   code, checksums of deterministic job output) that must be identical on
   both sides. `probe.py raw` sends a request byte for byte, for what a client
   library refuses or rewrites. `e2e/run.sh` first runs
   `e2e/lib/test_probe.py`, which checks the probe against a local server,
   without a cluster; `compare.sh` first runs `lib/test_comparators.py`,
   which checks the comparison scripts the same way, and `run-all.sh` and the
   workflow's queue job run it before their builds and their wait. Every
   daemon JVM logs the classes it loads; a class loaded on one side only is
   listed per daemon and accepted only by a `classonly <daemon>:<class>` rule
   (R87), and an unexpected one fails the end-to-end check only when
   `CLASSONLY_FAIL=true` (the default, `false`, lists it as "would fail"
   without changing the verdict). Before the jar a class came from is
   compared, the side name and the per-run application, container and
   filecache ids are masked, so a container's `job.jar` under two
   application ids is not a move (T44). A servlet probe (R93) runs an
   HttpServer2 on the side's classpath and records what a servlet sees at run
   time, by value: its JSON answers keep their values (with the usual masks),
   so a difference shows what each side answered. The
   scenarios also send raw HTTP/1.0 requests (R94). MapReduce container JVMs
   log their class loads (R95), collected and compared per container type.
   All daemon and container logs
   are scanned for class loading, linkage and JAX-RS provider errors, except
   the class-load logs themselves: their `[class,load]` lines name exception
   classes without an error having happened (T43). Line
   numbers in Java stack frames are dropped before comparing, so an error
   page that prints a stack trace does not differ just because a jar in it
   was recompiled or upgraded.
4. **Hadoop's own tests, by architecture** (`unit-tests.sh`): the tests of
   every module whose build phase A changes, and existing MiniKdc, HA,
   federation and mixed-topology tests, on both trees, compared test by
   test; plus the shaded client invariant checks and
   `hadoop-client-integration-tests`.
5. **What downstream projects resolve** (`downstream-deps.sh`): one small
   Maven project per published Hadoop artifact (hadoop-common, the HDFS,
   MapReduce and YARN clients, hadoop-client, the shaded clients, the
   miniclusters), resolved against each side's installed artifacts in four
   scenarios: alone, next to an older Jetty client, and next to the
   project's own servlet API under the `javax.servlet` coordinate (as HBase
   declares it) and under `jakarta.servlet` (as Spark and Hive). Check 1
   compares Hadoop's own modules; this one shows what Maven's nearest-wins
   mediation picks in a project that depends on Hadoop, which a dependency
   declared directly in a Hadoop pom can change. Maven mediates versions of
   one coordinate only, so each project's classpath is also scanned for
   classes that more than one jar provides (`lib/downstream_classes.py`):
   a new set of such jars (`downstream-dup-added`) means a downstream
   project now gets two copies of the same classes and classpath order
   decides which one loads. Allowlist:
   `expected-downstream-differences.txt`. It runs with the `client` unit
   suite (the `simple` workflow) and in `run-all.sh`; the report has the
   section only when it ran.

Before any of that, `compare.sh` checks that the two trees are what they
claim to be, and stops without comparing when they are not:

- **The candidate contains the baseline's commits** (`lib/ancestry.py`):
  every baseline commit's change to a file outside the harness and `.github/`
  must be in the candidate's tree. When it is not, the candidate was built on
  an older trunk than the baseline (ha-run-4, mixed-run-5 and federated-run-6
  failed this way), and those commits' changes would be reported as
  differences caused by the patch. The report names the missing commits and
  the files they change.
- **The candidate is the baseline plus the PR branches**
  (`lib/compare_plan.py`): with `PR_BRANCHES` set, the candidate's change
  against the baseline must be exactly the combined change of those branches,
  replayed per file in merge order. A file changed by no branch, a file a
  branch changes or deletes and the candidate does not match, or a file whose
  replay does not reproduce the candidate's content is reported with the
  files. A file a branch deletes and the candidate does not have is a match;
  a replay that keeps the file while the candidate lacks it, or the other way
  round, is a difference. A conflict the candidate resolved by hand and a
  binary blob cannot be replayed; the intended resolutions are listed in
  `lib/compare_plan.py` (`NOTICE-binary`), and a file with no resolution there
  counts as a difference. A branch already merged into the baseline, as
  commits or squashed (same `git patch-id`), is listed as landed and not
  replayed, so a merged PR does not stop the runs; remove it from
  `PR_BRANCHES` and `PR_ORDER` when the report lists it. A branch only partly
  merged is not landed.

Either check failing writes its own section as the report and exits 1. Set
`ANCESTRY_CHECK=false` or `PLAN_CHECK=false` to compare anyway. Both are
skipped when the two sides resolve to the same commit: a self-comparison run
(`jetty12-phase-a-<arch>-run-aa-*`, R68) has no patch, so the plan check would
report every PR branch file as missing and stop the run before it compared
anything. The workflow sets `PR_BRANCHES` for those runs too; the check is
skipped all the same. In CI the queue job runs both checks first, before it
waits for its turn and before any build, and the run stops there when either
fails; its summary holds their sections.

The report starts with **Impact on users** (`lib/impact.py`), built from all
the checks: for the daemons and applications on the Hadoop classpath, the
users of each shaded client jar and the Maven projects in each downstream
scenario, what changes, how much of it is accepted by a rule, and which
accepted user-visible differences have no `announced:` in their rule. It has
no verdict of its own.

## Architectures

Each architecture is a file in `e2e/arch/` listing its daemon instances.
Every instance gets its own configuration directory, pid file and logs
(`HADOOP_IDENT_STRING` is the instance name), so one host runs two
namenodes, three journalnodes, two resource managers or two routers.

| Architecture | Topology | Scenarios |
|---|---|---|
| `simple` | one of every daemon, simple auth over HTTP: namenode, datanode, secondary namenode, journalnode, HDFS router, HttpFS, KMS, NFS gateway (as root), resource manager, node manager, timeline server, web proxy, YARN router, shared cache manager, timeline reader v2, job history server | 00 10 20 30 40 50 60 |
| `secure` | Kerberos (KDC from `hadoop-minikdc`), every web server HTTPS only with SPNEGO, SASL data transfer with block tokens, KMS and HttpFS with Kerberos over HTTPS, delegation tokens: namenode, datanode, KMS, HttpFS, resource manager, node manager, timeline server, job history server | 00 10 20 30 50 70 |
| `ha` | ZooKeeper, three journalnodes, two namenodes with ZKFC automatic failover, two resource managers with leader election and the ZooKeeper state store, datanode, node manager, job history server | 00 10 20 50 80 |
| `federated` | HDFS federation (two namespaces, one datanode with two block pools, RBF router with the ZooKeeper state store, ViewFS) and YARN federation (two sub-clusters, YARN router with the federation interceptors, global policy generator, ZooKeeper federation state store) | 00 10 85 |
| `mixed` | an HA namespace and a non-HA one federated behind two RBF routers that clients use as one HA nameservice (the default file system, so YARN and MapReduce go through RBF), RM HA | 00 10 80 85 90 |

In `ha`, `mixed` and `federated`, the clients set
`dfs.client.failover.random.order=false` so each tries the active namenode
first; the standby does not load request classes on one side only (R86).

| Scenario | What it does |
|---|---|
| `00-cli-common` | `hadoop` CLI, credential provider, local file system; loads the javax.annotation, servlet, JAX-RS, Jersey and Jetty classes through all four launchers and records the jar each comes from |
| `10-web-common` | on every daemon instance's web server: `/jmx` (query, get, callback, bad query, no user), `/conf` (XML, JSON), `/stacks`, `/logLevel` get/set, `/logs/` listing and traversal attempt, `/prom`, static content, 404s, `/isActive`, `HEAD`/`OPTIONS`/`TRACE`/`POST`, security headers; under TLS the closed HTTP port and the 401 without credentials; also starts the servlet probe (R93) and sends raw HTTP/1.0 requests to it and to Hadoop's own servlets (R94) |
| `20-hdfs` | file system shell, ACLs, xattrs, snapshots, quotas, storage and EC policies, cache directives, fsck, image fetch, `oiv`, `oev`, `saveNamespace`, balancer, mover, disk balancer; WebHDFS REST (about 45 operations, two-step create/append through the datanode, errors); WebHDFS client; namenode, datanode, SNN, JN web UIs and servlets |
| `30-hdfs-services` | RBF mount table and RPC/WebHDFS through the router; HttpFS REST and client; KMS keys over CLI and REST, EEK generate/decrypt; encryption zone read over RPC, WebHDFS and HttpFS; NFS gateway |
| `40-yarn` | YARN CLI, distributed shell, RM REST in JSON and XML, application submit and kill through REST, RM UI, node manager, timeline v1 entity round trip, application history, web proxy, YARN router, shared cache manager, timeline reader, YARN services API (create, flex, stop, destroy) |
| `50-mapreduce` | pi, wordcount, grep, teragen/terasort/teravalidate with checksums, job CLI, the AM's REST API and UI through the proxy while a job runs, job kill, job history REST and UI |
| `60-tools` | DistCp over HDFS, WebHDFS and HttpFS; HAR; streaming; rumen; gridmix; SLS with its Jetty UI; resource estimator REST; cloud connector and other tools' entry classes |
| `70-secure` | TLS protocol, cipher and certificate per server, TLS 1.1 refused; SPNEGO 401s and a forged auth cookie; KDiag; RPC without a ticket; `fetchdt` and RPC with a token file; WebHDFS delegation token get/use/renew/cancel |
| `80-ha` | active/standby `/isActive`, standby WebHDFS StandbyException, standby RM redirects; kill the active namenode, then the active RM: failover through ZooKeeper, data and applications survive, the killed daemon returns as standby, graceful failback |
| `85-federation` | both namespaces, cross-namespace DistCp; RBF single and multi-destination mounts, quotas, rename across mounts refused, WebHDFS and UI through the router; ViewFS; YARN router REST aggregated over both sub-clusters, client RPC, an application placed on one sub-cluster, GPG UI |
| `90-mixed` | MapReduce with RBF as the default file system across HA and non-HA namespaces; both routers share one mount table; kill a router and keep reading, writing and running jobs through the other |

## Reused Hadoop test code

- **MiniKdc** (`hadoop-minikdc`) is the KDC of the secure architecture; when
  the host has no `kinit`, its Kerby client library gets the ticket
  (`e2e/lib/KerbyKinit.java`).
- **ZooKeeper** runs from the jars the distribution already ships.
- The **timeline service test jar** provides the file system storage the
  timeline reader runs on.
- The **unit test suites** are Hadoop's existing tests, grouped by what they
  exercise:

| Suite | Tests |
|---|---|
| `changed` | the modules phase A changes (web and Jersey tests in `quick`, everything in `full`, in parallel where a module has Hadoop's `parallel-tests` profile), plus the HTTP tests of KMS, HDFS, RBF, timeline service and MR jobs (the listed tests in both tiers); `changed-1` to `changed-4` split it for CI |
| `secure` | `TestHttpServerWithSpnego`, `TestSSLHttpServer*`, `TestKDiag*`, `TestSecureNameNode`, `TestSaslDataTransfer`, `TestWebHdfsTokens`, `TestDelegationToken`, `TestBlockTokenWithDFS*`, `TestKMS`, `TestHttpFSWithKerberos`, `TestHttpFSServerWebServer`, `TestRouterWithSecureStartup`, `TestRouterHttpDelegationToken`, `TestRouterSecurityManager`, `TestRMWebappAuthentication`, `TestRMWebServicesDelegationTokenAuthentication`, `TestRMWebServicesHttpStaticUserPermissions`, `TestTimelineAuthenticationFilterForV1`, `TestSecureLogins`, `TestJHSSecurity` |
| `ha` | `TestZKFailoverController`, `TestNodeFencer`, `TestWebHDFSForHA`, `TestFailoverWithBlockTokensEnabled`, `TestHAStateTransitions`, `TestDFSZKFailoverController`, `TestStandbyCheckpoints`, `TestDelegationTokensWithHA`, `TestQuorumJournalManager`, `TestRMFailover`, `TestApplicationClientProtocolOnHA`, `TestResourceTrackerOnHA`, `TestRMHA`, `TestRMEmbeddedElector` |
| `federated` | `TestViewFileSystemHdfs`, `TestViewFsHdfs`, `TestRefreshNamenodes`, `TestWebHdfsWithMultipleNameNodes`, `TestMultipleNNPortQOP`, `TestRouterRpc`, `TestRouterAdminCLI`, `TestRouterMountTable`, `TestRouterWebHdfsMethods`, `TestRouterWebHDFSContract*`, `TestFederationClientInterceptor`, `TestFederationInterceptorREST`, `TestRouterWebServicesREST`, `TestGlobalPolicyGenerator`, `TestFederationInterceptor`, `TestZookeeperFederationStateStore` |
| `mixed` | `TestSecureNNWithQJM` (secure + HA), `TestRouterNamenodeHeartbeat`, `TestRouterNamenodeMonitoring`, `TestRouterFaultTolerant`, `TestObserverWithRouter`, `TestRouterRPCClientRetries` |
| `client` | `hadoop-client-check-invariants`, `hadoop-client-check-test-invariants`, `hadoop-client-integration-tests` |

## Not exercised end to end, and why

- **Timeline service v2 with HBase storage**: needs an HBase cluster. The
  reader runs with file system storage end to end; the `changed` suite runs
  `hadoop-yarn-server-timelineservice-hbase-tests`, whose tests start an
  HBase minicluster: in `quick` the reader's web services on HBase storage
  (`TestTimelineReaderWebServicesHBaseStorage`), in `full` all of them.
- **YARN registry DNS**: needs a registry in ZooKeeper and has no web
  server; phase A does not touch it.
- **Cloud connectors**: need cloud credentials; only class loading is
  compared. Phase A does not touch them.
- **Dynamometer**: needs a captured fsimage and audit logs and a long run;
  only class loading is compared.
- **NFS mounts**: mounting needs a kernel NFS client; the gateway's RPC
  services are checked instead.
- **Log aggregation under Kerberos**: it needs the native `libhadoop`
  (SecureIOUtils), so `secure` turns it on only when the distribution has
  `lib/native/libhadoop.so`: in CI, which builds both sides with it, and
  locally with `BUILD_NATIVE=true`. The other architectures always
  aggregate logs.
- **MapReduce on YARN federation**: with both sub-clusters on one host, the
  AMRMProxy address a job needs is ambiguous; YARN federation is exercised
  with distributed shell, which finds its home RM through the node manager.
- **Distributed shell application master class loading**: its Java options are
  set in `Client.java` without a configuration hook the harness can use
  (`-Xlog` would have to be added to the client's command line), so only the
  MapReduce application master and its tasks log their class loads (R95).

Run, but compared on neither side, because they fail on both (see known
issues below). A PASS says nothing about them:

- **MapReduce under Kerberos** (MAPREDUCE-7548): every job of `secure` used
  to fail, so the jobs, their output, the job history server's job and task
  pages and the AM's REST API and UI through the proxy with SPNEGO were not
  compared there. The harness now submits the jobs with
  `-D hadoop.security.authorization=false` in the job's own configuration
  (`MR_SEC_OPTS` in `e2e/scenarios/50-mapreduce.sh`), so the AM skips its
  ACL check and the jobs run and are compared. A control job without the
  override is expected to fail (`--expect-rc 1`), so the harness notices
  when the bug is fixed. The other architectures run MapReduce without
  Kerberos.
- **Distributed shell and REST submissions through the YARN router**
  (YARN-12024, YARN-12025): `federated` records them failing on both sides;
  only the router's read-only REST calls and client RPC are compared.
- **Timeline server JSON responses** (put, events, domains, application
  history): the JSON writer is chosen at random at each start (YARN-12030), so only their
  status and checks are compared, not their shape (`obsdiff`).

## Known issues found on both sides

These are not caused by phase A; the harness records them, and they show as
"failing on both sides":

- `slsrun.sh` builds the simulated RM's configuration from
  `new Configuration(false)` plus `sls-runner.xml`, so `yarn-site.xml` is not
  read and the scheduler class is null (NPE in `RMRunner.startRM`). The
  harness puts the scheduler and RM ports in `sls-runner.xml` to still
  exercise SLS.
- MAPREDUCE-7548: MapReduce jobs fail on a cluster with service-level authorization
  (`hadoop.security.authorization=true`, the `secure` architecture): the
  MR application master rejects its own tasks with "Protocol interface
  org.apache.hadoop.mapred.TaskUmbilicalProtocol is not known".
  `TaskUmbilicalProtocolPB` declares the protocol name
  `org.apache.hadoop.mapred.TaskUmbilicalProtocol`, so the RPC server
  authorizes calls against that interface, but `MRAMPolicyProvider`
  registers the ACL under `TaskUmbilicalProtocolPB`. (HDFS does it the other
  way: `HDFSPolicyProvider` lists `ClientProtocol` for
  `ClientNamenodeProtocolPB`.) The harness works around it by submitting the
  `secure` jobs with `-D hadoop.security.authorization=false` in the job's
  own configuration, which skips the AM's ACL check only (the daemons keep
  authorization on from `core-site.xml`). A control job without the override
  is expected to fail, so the harness notices when the bug is fixed.
- YARN-12024: distributed shell cannot be submitted through the YARN router: its client
  tolerates `YARNFeatureNotEnabledException` from `getResourceProfiles`
  (resource profiles are off by default), but
  `FederationClientInterceptor.getResourceProfiles` wraps the sub-clusters'
  exceptions in a plain `YarnException` ("invokeConcurrent Failed"), so the
  client gives up. The REST submission `federated` also tries fails too
  (YARN-12025). Without the application, the checks that read it back
  (`router-app`, `router-app-state`, `router-app-status`,
  `app-on-one-subcluster`) are recorded as failed rather than run against
  an empty id. The harness also submits a distributed shell application to
  sub-cluster sc1's resource manager directly. The router's REST and RPC
  listings must show it (`router-apps-direct`, `router-app-list-direct`) and
  it must be on exactly one sub-cluster (`app-on-one-subcluster-direct`). The
  router finds an application by id only through the home sub-cluster that
  a submission through the router records in the state store, so the reads
  by id (`router-app-direct`, `router-app-state-direct`) are recorded
  without an expectation and compared between the sides (R88).
- YARN-12025: the YARN router's REST API cannot forward requests whose answer has a
  body to read, e.g. `POST /ws/v1/cluster/apps/new-application` answers 503
  "No active SubCluster available" after "MessageBodyReader not found for
  media type=application/json ... NewApplication":
  `RouterWebServiceUtil.invokeRMWebService` ignores the client it is given
  and builds a bare `ClientBuilder.newClient()` with no JSON provider
  registered. Phase A changes no JSON provider jar on the router's
  classpath, and the CI runs of `federated` fail the same way on the
  baseline.
- HADOOP-20018: when the ZKFC cannot bind its RPC port, it exits with a
  NullPointerException (`this.rpcServer` is null in
  `ZKFailoverController`) that hides the BindException behind it. Each ZKFC
  of the harness has its own `dfs.ha.zkfc.port`, so the runs do not hit it;
  it was seen while setting them up.
- YARN-12030: the timeline server picks its JSON writer at random at each
  start. `ApplicationHistoryServer#configure` registers both
  `JettisonFeature` and `YarnJacksonJaxbJsonProvider`, and for the put
  response, events, domains and the application history DAOs Jersey uses
  either one. Restarting one build six times answered once with Jackson
  (lists as arrays, empty list `[]`, declared field order) and otherwise
  with Jettison (one-element lists collapsed to an object, empty list `""`,
  `eventInfoJAXB` field names). The first CI run of `simple` hit one writer
  on each side. The harness accepts either shape for these responses
  (`obsdiff` in `e2e/expected-e2e-differences.txt`); their other checks
  still apply.
- Jetty's `DefaultServlet` (HttpServer2 turns its precompressed "gzip"
  option on) adds `Vary: Accept-Encoding` to a static file only when it finds
  a precompressed variant (the hadoop-yarn-common jar ships
  `webapps/static/yarn.css.gz`), and one build sends it in one run and not in
  the next: the candidate sent it on the RM's `yarn.css` in CI runs 3 and 4 of
  `simple` and not in run 5, with identical code. The harness lets that one
  header differ (`obsfield` in `e2e/expected-e2e-differences.txt`); any other
  difference in the same observation still fails.
- No JIRA yet: a WebHDFS read through the HDFS router (RBF) redirects the
  client to a datanode with `namenoderpcaddress=<router id>`, and the router
  id is the local hostname plus the RPC port (`Router#setRpcServerAddress`),
  not the configured `dfs.federation.router.rpc-address`. A router bound to
  one address the hostname does not resolve to (on CI runners the hostname is
  a private address, the harness binds `localhost`) leaves the datanode unable
  to reach it, and the read fails with 403. The harness sets
  `dfs.federation.router.rpc-bind-host=0.0.0.0`.
- No JIRA yet: `TestFederationInterceptor#testSubClusterTimeOut` (node
  manager, `federated` unit suite) can fail on either side with
  `expected: <2> but was: <0>` at the assertion after its 800 ms sleep.
  `FederationInterceptor#getTimedOutSCs` skips a sub-cluster only when its
  last response time is strictly greater than the AM's last heartbeat time,
  and both are `MonotonicClock` readings in milliseconds. When the sub-clusters
  answer within the same millisecond as the heartbeat, the two are equal, both
  sub-clusters count as timed out after the sleep, and the test sees no
  cluster nodes. It failed on the candidate of federated-run-7, twice in one
  job; the log shows the heartbeat and both sub-cluster allocations in the
  same millisecond. HADOOP-20015's change in that class (Jetty's
  `ConcurrentHashSet` replaced by `ConcurrentHashMap.newKeySet()` for the NM
  tokens of secondary sub-clusters) is not on the timeout path, the same code
  passed in federated-run-5 and -6, and 50 local runs on each side passed
  (0/50 and 0/50). A failure of this test only is not a phase A regression.

## Running it

### In CI

One workflow per architecture, so each can be run, re-run and read on its
own; all five share `.github/workflows/tmpl_jetty12_phase_a.yml`:

| Workflow | Architecture | Unit test suites |
|---|---|---|
| `jetty12_phase_a_simple.yml` | `simple` | `changed` (tier `quick` or `full`), `client` |
| `jetty12_phase_a_secure.yml` | `secure` | `secure` |
| `jetty12_phase_a_ha.yml` | `ha` | `ha` |
| `jetty12_phase_a_federated.yml` | `federated` | `federated` |
| `jetty12_phase_a_mixed.yml` | `mixed` | `mixed` |

Each builds both sides (with a self-comparison of each build), runs its
architecture end to end on both, runs its unit suites on both, and compares
them; `report.md` goes to the run summary and the `report-<arch>` artifact.
The artifact and dependency comparison is part of every report.

A workflow starts by hand:

- **Run workflow** in the Actions tab, with the two refs (and the tier for
  `simple`). GitHub only offers this for workflows on the default branch
  (`trunk` in this fork), so until then use:
- a tag named `jetty12-phase-a-<arch>-run-*`, which runs the tagged commit
  as the candidate against `PREPARATION`:

  ```
  git tag jetty12-phase-a-secure-run-1 origin/feat/HARNESS
  git push origin jetty12-phase-a-secure-run-1
  ```

- or a branch with the same name pattern, where tags cannot be pushed:

  ```
  git push origin origin/feat/HARNESS:refs/heads/jetty12-phase-a-secure-run-1
  ```

Two runs check the harness itself instead of the patch, chosen by the
branch (or tag) name:

- `jetty12-phase-a-<arch>-run-aa-*`: the baseline against itself (both
  sides build `PREPARATION`). Every difference it reports is noise the
  harness must mask or allow.
- `jetty12-phase-a-<arch>-run-broken-<case>-<n>`: the candidate's
  distribution is broken on purpose before it is compared or run
  (`ci/break_candidate.py`). The overall verdict is FAIL, and the report adds
  a harness check: it PASSes, and the run is green, only when the artifacts
  and every end-to-end architecture FAIL and the tree checks do not. A red
  broken run means the harness missed that kind of breakage, or stopped
  before it could see it.

A third name runs longer, not differently: `jetty12-phase-a-simple-run-full-<n>`
runs the `changed` suite in tier `full`, every test of the modules phase A
changes, split into four jobs per side (`changed-1` to `changed-4`) because
the resource manager's tests alone take hours and a job stops after 6. The
tier applies to the `changed` suite only: the other suites are lists of
chosen tests whose modules phase A does not change, and run them in both
tiers (whole modules would repeat HDFS, common, the resource manager and
the routers across the architectures without adding evidence).

| Case | Change to the candidate | Kind of breakage |
|---|---|---|
| `annotation` (also `run-broken-<n>`) | delete `jakarta.annotation-api`, the only `javax.annotation` jar after HADOOP-20013 | a dependency the patch relies on goes missing |
| `jetty` | delete `jetty-http` | massive: no web server starts |
| `static` | delete `share/hadoop/hdfs/webapps/static/hadoop.css` | narrow: one static file of the namenode UI |
| `webhdfs-user` | set `dfs.webhdfs.user.provider.user.pattern` to `^hdfs$` in the `hdfs-default.xml` of the hadoop-hdfs jar | a changed default, nothing missing: WebHDFS rejects the harness user |

The report says when a run is one of these, and lists the changes. A
broken-candidate run skips the unit test jobs: they build from source and
cannot see the broken distribution. Other
changes can be given to `ci/artifacts.sh unpack-build` in `BREAK_CANDIDATE`
(specs of `ci/break_candidate.py`).

Before waiting, each run checks the comparison scripts
(`lib/test_comparators.py`), so a broken comparator fails at once instead of
after the wait and the builds (R81).

Runs go **one at a time**, across all five workflows, oldest first: each
run's first jobs wait (polling every minute) until no earlier harness run
is queued or running (`ci/wait-turn.sh`), so starting several runs queues
them instead of running them side by side. A job runs 6 hours at most, so
the wait is split over two jobs ("Wait for earlier harness runs" and its
"continued" job) of up to 340 minutes each; a run still waiting after about
11 hours fails there and has to be started again.
"Re-run failed jobs" skips the waiting job, which already succeeded, so such
a re-run can overlap another run; push a new run branch instead.

In CI the distributions are built **with the native libraries**, inside
Hadoop's build image (`ghcr.io/apache/hadoop/gha-build-ubuntu_24-image-cache:trunk-static`,
published by apache/hadoop from `dev-support/docker`, as
`tmpl_build_and_test.yml` uses); the end-to-end and unit jobs run on the
plain Ubuntu 24.04 runner. Both sides are built at the same path
(`BUILD_SRC_DIR`), because the native libraries embed their source paths:
built at the two worktree paths, identical code gives 17 differing native
files. A local native build (both sides in one `WORKDIR`) shows those
differences; set `BUILD_SRC_DIR` and build one side at a time to avoid them.

Builds are **reused between runs**: most runs change only the harness, and
the baseline is the same commit every time. Each fresh build is also saved
as an artifact named after its key (`ci/build-key.sh`: the side's code
without the harness and `.github`, the harness files that shape the build,
the JDK), and a later run with the same key downloads it instead of building
(`ci/find-build.sh`): the packed distribution for the build jobs, the
installed Maven artifacts for the unit jobs, which then only check out the
tree. Artifacts are used rather than the actions cache because a cache can
only be read on the branch that saved it, and every run has its own branch;
they expire after 7 days. A reused build names the current commit in the
report and keeps the one that built it in `build/reused-from.txt`.

A workflow is 5 to 7 jobs (two builds, two end-to-end runs, two or four
unit suite runs, the comparison); each fits a standard GitHub-hosted runner
(4 vCPUs, 16 GB, 6-hour job limit for public repositories).

### Attribution runs

A fork-only workflow, `.github/workflows/jetty12_phase_a_attribution.yml`,
starts on a push to a branch named `jetty12-phase-a-attribution-run-*`. It
runs checks 1, 2 and 5 (artifacts and dependencies, API compatibility and what
downstream projects resolve) on each tree of the merge order: each PR branch
alone (`ticket-<n>`) and each prefix of the merge order of length 2 to 5
(`prefix-<n>`), with the branches and order from `PR_ORDER` in
`lib/compare_plan.py`. `attribution.sh list` prints the tree names and
`attribution.sh <tree>` creates the tree as a detached merge commit in a
worktree under `WORKDIR`, without creating a branch, and runs those checks
against the baseline into `results/attribution/<tree>/`. In CI,
`attribution.sh merge <tree>` and `attribution.sh compare <tree>` run those two
halves apart: one job builds the baseline for every tree, each tree job
builds only its candidate, and both reuse a saved build of the same code
(`.github/actions/jetty12-phase-a-build-side`, with the build job's keys), so
a baseline that a normal run saved is not built again. A final job downloads
every tree's results and runs `lib/attribution.py`, which writes
`attribution.json` and `attribution.md` and fails when a ticket's rule matched
nothing in its own tree, a difference is UNEXPECTED, or a tree of `PR_ORDER`
has no results (`missing tree <name>`), so a failed tree job cannot shrink
the report silently (T47).

### On one machine

Requirements: Linux, JDK 17 or later, Python 3, curl (with GSS-API for the
secure architecture), git, about 30 GB of disk and 16 GB of memory. Maven
comes from the tree's own `./mvnw`. `kinit` is used when present. Docker is
not needed; inside the Hadoop build image (`start-build-env.sh`) it works
the same.

```
# everything: build both sides, all architectures, all unit suites, report
dev-support/jetty12-phase-a/run-all.sh quick

# or step by step
dev-support/jetty12-phase-a/build.sh baseline
dev-support/jetty12-phase-a/build.sh candidate
dev-support/jetty12-phase-a/e2e/run.sh baseline all
dev-support/jetty12-phase-a/e2e/run.sh candidate all
dev-support/jetty12-phase-a/unit-tests.sh baseline all quick
dev-support/jetty12-phase-a/unit-tests.sh candidate all quick
dev-support/jetty12-phase-a/compare.sh simple,secure,ha,federated,mixed
```

Rough durations on 4 cores: build 35-60 minutes per side, each
architecture 10-30 minutes per side, unit suites from minutes (`client`)
to hours (`changed` full).

A new or edited allowlist rule is replayed against the reports already
written before it is committed (R66), without a build or a run:

```
# this machine's results, or one or more downloaded report-<arch> artifacts
dev-support/jetty12-phase-a/replay.sh
dev-support/jetty12-phase-a/replay.sh ~/reports/report-ha ~/reports/report-mixed
```

It matches each rule the way its comparison does and prints the rules that
matched nothing anywhere (the ones a run would report as unused) and the
rules that matched in only some directories, which is how a pattern limited
to `[a-z]+` missed the numbered daemons (`nn1`, `rm1`, `router2`, ...) in
ha-run-3, mixed-run-4 and federated-run-5. A rule whose kind none of the
directories recorded data for (`pom-*`, `license-*`, `notice-*`) is printed as
"not replayable" and does not fail. It exits 1 when a rule that could have
matched did not. In CI, download the reports first:

```
gh run download <run id> -p 'report-*' -D ~/reports
dev-support/jetty12-phase-a/replay.sh ~/reports/report-*
```

| Variable | Default | Meaning |
|---|---|---|
| `WORKDIR` | `~/jetty12-phase-a-work` | worktrees, Maven repository, cluster state, results |
| `BASELINE_REF` / `CANDIDATE_REF` | `origin/PREPARATION` / `origin/feat/HARNESS` | the two trees |
| `ANCESTRY_CHECK` | `true` | `compare.sh` stops when the candidate lacks a baseline commit's change (`lib/ancestry.py`) |
| `PLAN_CHECK` | `true` | `compare.sh` stops when the candidate is not the baseline plus `PR_BRANCHES` (`lib/compare_plan.py`) |
| `CLASSONLY_FAIL` | `false` | whether an unexpected one-side class fails the end-to-end check (R87); with `false` it is listed as "would fail" without changing the verdict; in CI the Compare step of `tmpl_jetty12_phase_a.yml` sets it |
| `PR_BRANCHES` | none | the branches merged into trunk, in merge order, comma-separated (e.g. `origin/HADOOP-20012-upstream,...,origin/jetty-phase-a`); the plan check runs only when set. The workflow sets it for every run; a run whose two sides are one commit skips the check |
| `MAVEN_MIRROR_URL` | none | mirror of Maven Central, e.g. `https://maven-central.storage-download.googleapis.com/maven2` when the build host is rate-limited |
| `MVN_EXTRA_ARGS` | none | added to every Maven call |
| `BUILD_NATIVE` | `false` | build the distribution with the native libraries (`-Pnative`, OpenSSL and Snappy required); needs the toolchain of `start-build-env.sh`, which CI uses |
| `BUILD_SRC_DIR` | `$WORKDIR/<side>/src` | worktree to build in, for either side; a CI build job builds one side and sets it so both sides' native libraries are built at the same path |
| `M2_REPO` | `$WORKDIR/m2` | Maven repository; both sides share downloads but install into separate prefixes |
| `UNIT_RERUNS` | 1 | re-runs of a failing test before it counts as failed |
| `E2E_NFS` | `auto` | start the NFS gateway in `simple` (`auto` = when running as root) |
| `E2E_GRIDMIX` | `true` | run the gridmix sleep jobs |
| `E2E_START_TIMEOUT` | 180 | seconds to wait for a daemon's web endpoint (stops early when the daemon exits) |
| `E2E_NM_MEMORY_MB` | 6144 | node manager memory (split between sub-clusters in `federated`) |
| `DAEMON_HEAP` | `384m` | heap of each daemon |

Single parts can be re-run: `e2e/run.sh candidate ha 80-ha` runs one
scenario of one architecture, `unit-tests.sh candidate secure` one suite,
`e2e/cluster.sh candidate mixed start|status|stop|kill|restart` drives a
cluster by hand. `artifact-diff.sh candidate candidate` compares a build
with itself, which must report no differences.

## Reading the report

`$WORKDIR/results/compare/report.md` has one section per check and
architecture and an overall verdict. Supporting data sits next to it
(`ancestry.json`, `compare-plan.json`, `artifact-diff.json`, `api-compat.json`,
`e2e-compare-<arch>.json`, `classload-compare-<arch>.json`,
`unit-compare.json`, `downstream-compare.json`, `impact.md`) and under
`results/<side>/` (raw observations, CLI output, daemon start-up, scenario
logs, surefire reports).

When `UNIT_HISTORY_DIR` names earlier runs' report directories, the unit
comparison's `unit-compare.json` and its section in `report.md` also say, for
every test that fails or is flaky in the run, in how many of those runs it was
fail or flaky on each side (`--history`, R85). It does not change the verdict.
In CI the `compare` job downloads those directories first with
`ci/history.sh <repo> <workflow file name> <arch> <dest dir>`: the
`report-<arch>` artifact of the last five completed normal runs of that
workflow (no aa or broken run) other than the current one, each into `<dest dir>/<run id>`, skipping a run
without the artifact.

A test JVM that runs for more than 600 s (`STALL_AFTER`; Hadoop kills it at
900 s) gets snapshots of every TCP socket's kernel state (`ss -tinmoep`), the
kernel's TCP counters and its threads, every 2 minutes, in
`results/<side>/unit/<suite>__<module>/stalls/` (`lib/stall-watch.sh`). It
was added after an HDFS read over loopback in
`TestMRIntermediateDataEncryption` crawled for half an hour in Hadoop's CI
with both ends waiting on the socket (the symptom of MAPREDUCE-7099); the
`changed` suite runs that test for this reason only.

To reproduce that stall on purpose, `stall-repro.sh <side>` runs the test
class in a loop (4.5 hours by default) and keeps the reports, test output
and watcher snapshots of every run with a case over 60 s; the watcher starts
at 150 s there, samples every 30 s and captures loopback packets. In CI,
pushing a branch named `jetty12-phase-a-stall-repro-*` starts the workflow
`Stall reproduction (Jetty 12 phase A harness)`: 8 shards in Hadoop's build
image, where the stall happened, on PREPARATION, with a summary of all
shards. It is not part of the comparison. A branch named
`jetty12-phase-a-stall-repro-scr-*` runs the variant `short-circuit`
(`STALL_REPRO_VARIANT`): hadoop-common's native library is built and HDFS
short-circuit local reads are turned on, so the test's input reads go
through a UNIX domain socket instead of TCP; each run counts the
datanode's short-circuit grants, and none in the first run stops the
script.

The first CI run (8 shards, 525 runs) reproduced it 5 times. In every stall
the map task's socket receive buffer had shrunk to 2 KB (once to 27 KB) after
the kernel pruned its receive queue, and the datanode, with 64 KB loopback
segments, could send only 2 KB per 200 ms persist-timer probe. The runners'
kernel was 6.17.0-1022-azure; HDFS sets no receive buffer size on these
sockets.

- **UNEXPECTED** artifact, API or downstream differences, **DIFF**/**REGRESSION**/**MISSING**
  observations, classes loaded from an unexpected jar, log errors that are
  new on the candidate or much more frequent there (more than twice the
  baseline's count and at least 6 more), an observation id recorded twice,
  unit tests that passed on the baseline but fail on the candidate, unit
  tests that ran on the baseline but are missing or skipped on the candidate,
  a unit test module whose Maven run failed on the candidate and succeeded on
  the baseline, a unit test module with no test reports on a side, and a unit
  test that exists only on the candidate and fails there with no
  `candidate-only-fail` rule in `expected-unit-differences.txt` (a known
  flake, one rule per test) fail the run. The report lists every
  candidate-only test with its result.
- An architecture given to `compare.sh` (or found on either side) that a
  side has no observations for, or only an observations file with no non-blank
  line, is **NOT RUN**, and the run is not a PASS.
- **Fail fast**: a daemon whose process exits, or whose main thread dies, is
  reported at once instead of after its start timeout, and when any daemon
  is not up after the start (`daemons.txt`), the scenarios are skipped; the
  logs and class loading are still collected. The comparison then says which
  daemons did not start: **FAIL** for the candidate, **NOT RUN** for the
  baseline.
- **A scenario that ends early** is an observation: every scenario records
  `scenario:<name>.completed`, failed when the script did not reach its last
  line, and `scenario:<name>.timeout` when it was cut off. Its observations
  after that point are lost, so the end is compared instead (R82). The
  marker's file name reaches the scenario's shell in an environment variable,
  so a scenario that runs `set --` (`10-web-common`, `70-secure`) cannot
  overwrite it (T42).
- **BOTH_FAIL** observations, tests failing on both sides and unit modules
  whose Maven run failed on both sides are not caused by the patch, but each
  one hides what it was checking: look at them before relying on a run.
- "Allowlist rules that matched nothing" means a change the patch should
  have made did not show up; check why. `replay.sh` finds the same rules
  without a run, and also the rules whose pattern misses some architecture's
  names.
- "The run stopped before comparing" means the candidate is not the baseline
  plus its PR branches: an older trunk, or a change no PR branch makes. The
  sections above it name the commits or files; nothing below them was
  compared.

When the patch changes, update `expected-differences.txt`,
`expected-api-differences.txt`, `expected-downstream-differences.txt`,
`expected-unit-differences.txt` and `e2e/expected-e2e-differences.txt`, naming the JIRA for each rule, and keep
the patterns narrow. Before adding a rule for a user-visible difference
(an API finding, a downstream dependency or duplicate, a change in a shaded
client or a lib jar), make sure the JIRA, the PR or the release note says
it, and write where in the rule (`# HADOOP-NNNNN: why; announced: release
note`).
