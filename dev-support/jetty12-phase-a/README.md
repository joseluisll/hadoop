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

Phase A (HADOOP-20012 to HADOOP-20016, combined as HADOOP-99999) prepares the
move to Jetty 12 / EE8 without changing what Hadoop does. It only changes
dependencies:

| JIRA | Change | Where it can show |
|---|---|---|
| HADOOP-20012 | catalog-webapp and timelineservice-hbase tests stop pulling third-party Jetty and the old servlet API | test classpath |
| HADOOP-20013 | duplicate `javax.annotation-api` 1.3.2 removed; `jakarta.annotation-api` 1.3.5 provides the same `javax.annotation` classes | runtime classpath of every daemon, LICENSE/NOTICE |
| HADOOP-20014 | Jersey test container moves from Jetty to the JDK HTTP server; `hadoop-client-minicluster` shades it, keeps `jetty-util`, stops copying `com.sun.net.httpserver` | test classpath, shaded minicluster jar |
| HADOOP-20015 | `jetty-webapp`/`jetty-servlet` declared in YARN common, RM, AHS, router | runtime classpath of YARN daemons |
| HADOOP-20016 | `jetty-http` declared in hadoop-common, HttpFS, shuffle, SLS | runtime classpath |

This harness builds the tree without the patch (**baseline**, default
`origin/PREPARATION`) and with it (**candidate**, default
`origin/HADOOP-99999`), runs the same checks on both, and reports every
difference. Differences the patch is meant to cause are listed, with the
JIRA that causes them, in two allowlists; anything else fails the run.

## What is checked

1. **Artifacts and dependencies** (`artifact-diff.sh`)
   - every file in the binary distribution, and every entry of every jar on
     both sides, by CRC (build timestamps and version-info files ignored), so
     identical code shows as identical;
   - the set of classes each launcher's real classpath can see
     (`hadoop`/`hdfs`/`yarn`/`mapred classpath --glob`, tools, timeline
     reader, shaded client, minicluster) and the jar each class is first
     loaded from;
   - every module's resolved dependencies, all scopes (`dependency:list`).
2. **End to end, in five architectures** (`e2e/run.sh`): real daemons
   started from each side's distribution tarball on one host, the same
   scenarios run against both sides. Each observation records whether the
   expectation held and a normalized view (HTTP status, content type,
   security headers, cookie attributes, JSON/XML shape, HTML title and
   assets, TLS protocol and cipher, CLI exit code, checksums of
   deterministic job output) that must be identical on both sides. Every
   daemon JVM logs the classes it loads, and all daemon and container logs
   are scanned for class loading, linkage and JAX-RS provider errors.
3. **Hadoop's own tests, by architecture** (`unit-tests.sh`): the tests of
   every module whose build phase A changes, and existing MiniKdc, HA,
   federation and mixed-topology tests, on both trees, compared test by
   test; plus the shaded client invariant checks and
   `hadoop-client-integration-tests`.

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

| Scenario | What it does |
|---|---|
| `00-cli-common` | `hadoop` CLI, credential provider, local file system; loads the javax.annotation, servlet, JAX-RS, Jersey and Jetty classes through all four launchers and records the jar each comes from |
| `10-web-common` | on every daemon instance's web server: `/jmx` (query, get, callback, bad query, no user), `/conf` (XML, JSON), `/stacks`, `/logLevel` get/set, `/logs/` listing and traversal attempt, `/prom`, static content, 404s, `/isActive`, `HEAD`/`OPTIONS`/`TRACE`/`POST`, security headers; under TLS the closed HTTP port and the 401 without credentials |
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
| `changed` | the modules phase A changes (web and Jersey tests in `quick`, everything in `full`), plus the HTTP tests of KMS, HDFS, RBF, timeline service and MR jobs |
| `secure` | `TestHttpServerWithSpnego`, `TestSSLHttpServer*`, `TestKDiag*`, `TestSecureNameNode`, `TestSaslDataTransfer`, `TestWebHdfsTokens`, `TestBlockTokenWithDFS*`, `TestKMS`, `TestHttpFSWithKerberos`, `TestRouterWithSecureStartup`, `TestRouterHttpDelegationToken`, `TestRouterSecurityManager`, `TestRMWebappAuthentication`, `TestRMWebServicesDelegationTokenAuthentication`, `TestTimelineAuthenticationFilterForV1`, `TestSecureLogins`, `TestJHSSecurity` |
| `ha` | `TestZKFailoverController`, `TestNodeFencer`, `TestWebHDFSForHA`, `TestFailoverWithBlockTokensEnabled`, `TestHAStateTransitions`, `TestDFSZKFailoverController`, `TestStandbyCheckpoints`, `TestDelegationTokensWithHA`, `TestQuorumJournalManager`, `TestRMFailover`, `TestApplicationClientProtocolOnHA`, `TestResourceTrackerOnHA`, `TestRMHA`, `TestRMEmbeddedElector` |
| `federated` | `TestViewFileSystemHdfs`, `TestViewFsHdfs`, `TestRefreshNamenodes`, `TestWebHdfsWithMultipleNameNodes`, `TestMultipleNNPortQOP`, `TestRouterRpc`, `TestRouterAdminCLI`, `TestRouterMountTable`, `TestRouterWebHdfsMethods`, `TestRouterWebHDFSContract*`, `TestFederationClientInterceptor`, `TestFederationInterceptorREST`, `TestRouterWebServicesREST`, `TestGlobalPolicyGenerator`, `TestFederationInterceptor`, `TestZookeeperFederationStateStore` |
| `mixed` | `TestSecureNNWithQJM` (secure + HA), `TestRouterNamenodeHeartbeat`, `TestRouterNamenodeMonitoring`, `TestRouterFaultTolerant`, `TestObserverWithRouter`, `TestRouterRPCClientRetries` |
| `client` | `hadoop-client-check-invariants`, `hadoop-client-check-test-invariants`, `hadoop-client-integration-tests` |

## Not exercised end to end, and why

- **Timeline service v2 with HBase storage**: needs an HBase cluster. The
  reader runs with file system storage; the HBase modules' tests run in the
  `changed` suite's `full` tier.
- **YARN registry DNS**: needs a registry in ZooKeeper and has no web
  server; phase A does not touch it.
- **Cloud connectors**: need cloud credentials; only class loading is
  compared. Phase A does not touch them.
- **Dynamometer**: needs a captured fsimage and audit logs and a long run;
  only class loading is compared.
- **NFS mounts**: mounting needs a kernel NFS client; the gateway's RPC
  services are checked instead.
- **Log aggregation under Kerberos**: it needs the native `libhadoop`
  (SecureIOUtils), and the distributions are built without `-Pnative`, so
  `secure` turns it off; the other architectures aggregate logs.
- **MapReduce on YARN federation**: with both sub-clusters on one host, the
  AMRMProxy address a job needs is ambiguous; YARN federation is exercised
  with distributed shell, which finds its home RM through the node manager.

Run, but compared on neither side, because they fail on both (see known
issues below). A PASS says nothing about them:

- **MapReduce under Kerberos** (MAPREDUCE-7548): every job of `secure`
  fails, so the jobs, their output, the job history server's job and task
  pages and the AM's REST API and UI through the proxy with SPNEGO are not
  compared there. The other architectures run MapReduce without Kerberos.
- **Distributed shell and REST submissions through the YARN router**
  (YARN-12024, YARN-12025): `federated` records them failing on both sides;
  only the router's read-only REST calls and client RPC are compared.
- **Timeline server JSON responses** (put, events, domains, application
  history): the JSON writer is chosen at random at each start, so only their
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
  `ClientNamenodeProtocolPB`.) The MapReduce observations of `secure` fail
  on both sides until it is fixed.
- YARN-12024: distributed shell cannot be submitted through the YARN router: its client
  tolerates `YARNFeatureNotEnabledException` from `getResourceProfiles`
  (resource profiles are off by default), but
  `FederationClientInterceptor.getResourceProfiles` wraps the sub-clusters'
  exceptions in a plain `YarnException` ("invokeConcurrent Failed"), so the
  client gives up. `federated` also submits through the router's REST API,
  which works.
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
- No JIRA yet: the timeline server picks its JSON writer at random at each
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
  a precompressed variant, and one build sends it in one run and not in the
  next: the candidate sent it on the RM's `yarn.css` in CI runs 3 and 4 of
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
  git tag jetty12-phase-a-secure-run-1 origin/HADOOP-99999
  git push origin jetty12-phase-a-secure-run-1
  ```

- or a branch with the same name pattern, where tags cannot be pushed:

  ```
  git push origin origin/HADOOP-99999:refs/heads/jetty12-phase-a-secure-run-1
  ```

Two runs check the harness itself instead of the patch, chosen by the
branch (or tag) name:

- `jetty12-phase-a-<arch>-run-aa-*`: the baseline against itself (both
  sides build `PREPARATION`). Every difference it reports is noise the
  harness must mask or allow.
- `jetty12-phase-a-<arch>-run-broken-*`: the candidate's distribution loses
  `jakarta.annotation-api` before it is compared or run (after HADOOP-20013
  the only jar with the `javax.annotation` classes). The verdict must be
  FAIL; if it is not, the harness misses a broken dependency.

The report says when a run is one of these. The jars to remove can also be
set with `BREAK_CANDIDATE` (file name globs) for `ci/artifacts.sh
unpack-build`.

Runs go **one at a time**, across all five workflows, oldest first: each
run's first job waits (polling every minute) until no earlier harness run
is queued or running (`ci/wait-turn.sh`), so starting several runs queues
them instead of running them side by side. A run that waits more than 6
hours (the job limit) fails in that job and has to be started again.

A workflow is 5 to 7 jobs (two builds, two end-to-end runs, two or four
unit suite runs, the comparison); each fits a standard GitHub-hosted runner
(4 vCPUs, 16 GB, 6-hour job limit for public repositories).

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

| Variable | Default | Meaning |
|---|---|---|
| `WORKDIR` | `~/jetty12-phase-a-work` | worktrees, Maven repository, cluster state, results |
| `BASELINE_REF` / `CANDIDATE_REF` | `origin/PREPARATION` / `origin/HADOOP-99999` | the two trees |
| `MAVEN_MIRROR_URL` | none | mirror of Maven Central, e.g. `https://maven-central.storage-download.googleapis.com/maven2` when the build host is rate-limited |
| `MVN_EXTRA_ARGS` | none | added to every Maven call |
| `M2_REPO` | `$WORKDIR/m2` | Maven repository; both sides share downloads but install into separate prefixes |
| `UNIT_RERUNS` | 1 | re-runs of a failing test before it counts as failed |
| `E2E_NFS` | `auto` | start the NFS gateway in `simple` (`auto` = when running as root) |
| `E2E_GRIDMIX` | `true` | run the gridmix sleep jobs |
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
(`artifact-diff.json`, `e2e-compare-<arch>.json`,
`classload-compare-<arch>.json`, `unit-compare.json`) and under
`results/<side>/` (raw observations, CLI output, daemon start-up, scenario
logs, surefire reports).

- **UNEXPECTED** artifact differences, **DIFF**/**REGRESSION**/**MISSING**
  observations, classes loaded from an unexpected jar, log errors that are
  new on the candidate or much more frequent there (more than twice the
  baseline's count and at least 6 more), an observation id recorded twice,
  unit tests that passed on the baseline but fail on the candidate, and a
  unit test module with no test reports on a side fail the run.
- An architecture given to `compare.sh` (or found on either side) that a
  side has no observations for is **NOT RUN**, and the run is not a PASS.
- **BOTH_FAIL** observations and tests failing on both sides are not caused
  by the patch, but each one hides what it was checking: look at them before
  relying on a run.
- "Allowlist rules that matched nothing" means a change the patch should
  have made did not show up; check why.

When the patch changes, update `expected-differences.txt` and
`e2e/expected-e2e-differences.txt`, naming the JIRA for each rule, and keep
the patterns narrow.
