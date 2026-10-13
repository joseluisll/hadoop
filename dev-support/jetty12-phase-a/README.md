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
`origin/HADOOP-99999`), runs the same checks against both, and reports every
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
2. **End-to-end cluster** (`e2e/run.sh`): a single-host cluster started from
   the side's distribution tarball with every daemon, and the same scenarios
   run on both sides (about 900 observations). Each observation records
   whether the expectation held and a normalized view (HTTP status, content
   type, security headers, JSON/XML shape, HTML title and assets, CLI exit
   code, checksums of deterministic job output) that must be identical on
   both sides. Each daemon's JVM also logs every class it loads, and all
   daemon and container logs are scanned for class-loading, linkage and
   JAX-RS provider errors.
3. **Unit and integration tests** (`unit-tests.sh`): the Maven tests of every
   module whose build phase A changes, plus the HTTP tests of the modules
   that run those servers, on both trees, compared test by test. The shaded
   client invariant checks and `hadoop-client-integration-tests` (which uses
   the minicluster jar from a downstream point of view) run too.

## Coverage

| Component | Daemon / tool | What the scenarios do |
|---|---|---|
| hadoop-common | every daemon's HttpServer2 | `/jmx` (query, get, JSONP, bad query), `/conf` (XML, JSON, by name), `/stacks`, `/logLevel` get/set, `/logs/` listing and traversal attempt, `/prom`, static content, 404s, `HEAD`/`OPTIONS`/`TRACE`/`POST`, security headers (`10-web-common.sh`) |
| hadoop-common | CLI | `version`, `classpath`, `envvars`, `conftest`, `checknative`, credential provider, local file system, loading of the javax.annotation, servlet, JAX-RS, Jersey and Jetty classes through all four launchers (`00-cli-common.sh`) |
| HDFS | namenode, datanode, secondary namenode, journalnode | file system shell, ACLs, xattrs, snapshots and diff, quotas, storage policies, EC policies, cache directives, fsck, image fetch, `oiv`, `oev`, `saveNamespace`, balancer, mover, disk balancer; WebHDFS REST (about 45 operations including two-step create/append through the datanode, ranges, snapshots, error bodies, permissions); the WebHDFS client file system; namenode, datanode, SNN and JN web UIs, fsck and image transfer servlets (`20-hdfs.sh`) |
| HDFS RBF | dfsrouter | mount table admin, RPC through the router, WebHDFS through the router, federation UI (`30-hdfs-services.sh`) |
| HttpFS | httpfs | the WebHDFS REST API (about 30 operations) including data upload, errors, authentication; WebHDFS client against HttpFS |
| KMS | kms | key create/roll/list/delete via CLI and REST, EEK generate and decrypt, errors, authentication; HDFS encryption zone write/read over RPC, WebHDFS and HttpFS |
| NFS gateway | portmap, nfs3 (as root) | start-up, JMX, `rpcinfo`, `showmount` |
| YARN | resourcemanager | CLI, REST in JSON and XML (cluster, scheduler, apps, nodes, labels, activities, errors), application submission and kill through REST in JSON and XML, web UI pages |
| YARN | nodemanager | REST, web UI, distributed shell containers, log aggregation |
| YARN | timeline server | timeline v1 entity POST/GET round trip, application history REST and UI |
| YARN | web proxy | proxying to a running MapReduce AM, finished and unknown applications |
| YARN | router, GPG, shared cache manager, timeline reader v2 | REST and UI through the router, router client RPC, GPG and SCM UIs, timeline reader REST (file system storage) |
| YARN | services API | create, status, flex, stop, destroy a service through the RM's REST API |
| MapReduce | jobs, history server, shuffle | pi, wordcount, grep, teragen/terasort/teravalidate with checksums compared, job CLI, the AM's REST API and UI through the proxy while a job runs, job kill, history server REST (JSON and XML) and UI (`50-mapreduce.sh`) |
| hadoop-tools | distcp, archives, streaming, rumen, gridmix | DistCp over HDFS, WebHDFS and HttpFS, HAR create and read, streaming job, rumen trace, gridmix sleep jobs from that trace (`60-tools.sh`) |
| hadoop-tools | SLS | a simulation from the bundled trace, its Jetty web UI and the in-process RM |
| hadoop-tools | resource estimator | its REST service: translate a log, history, estimate, delete |
| hadoop-tools | cloud connectors, dynamometer, fs2img, fedbalance, extras, datajoin | entry classes load from the tools classpath the same way on both sides |
| hadoop-client | api, runtime, minicluster | jar contents, visible classes, invariant checks, `hadoop-client-integration-tests` |

Not exercised end to end, and why:

- **Timeline service v2 with HBase storage**: needs an HBase cluster. The
  reader runs with file system storage; the HBase modules' tests run in the
  unit tier `full`.
- **YARN registry DNS**: needs ZooKeeper and has no web server; phase A does
  not touch it.
- **Cloud connectors**: need cloud credentials; only class loading is
  compared. Phase A does not touch them.
- **Dynamometer**: needs a captured fsimage and audit logs and a long run;
  only class loading is compared.
- **NFS mounts**: mounting needs a kernel NFS client; the gateway's RPC
  services are checked instead.
- **Kerberos / TLS**: the cluster runs with simple authentication over HTTP.

## Running it

Requirements: Linux, JDK 17 or later, Python 3, curl, git, about 25 GB of
disk and 16 GB of memory. Maven comes from the tree's own `./mvnw`. Docker
is not needed; inside the Hadoop build image (`start-build-env.sh`) it works
the same.

```
# everything: build both sides, e2e on both, quick unit tier, report
dev-support/jetty12-phase-a/run-all.sh quick

# or step by step
dev-support/jetty12-phase-a/build.sh baseline
dev-support/jetty12-phase-a/build.sh candidate
dev-support/jetty12-phase-a/e2e/run.sh baseline
dev-support/jetty12-phase-a/e2e/run.sh candidate
dev-support/jetty12-phase-a/unit-tests.sh baseline quick
dev-support/jetty12-phase-a/unit-tests.sh candidate quick
dev-support/jetty12-phase-a/compare.sh
```

Rough durations on 4 cores: build 40-60 minutes per side, e2e 30-45 minutes
per side, unit tier `quick` 2-3 hours per side, `full` most of a day.

| Variable | Default | Meaning |
|---|---|---|
| `WORKDIR` | `~/jetty12-phase-a-work` | worktrees, Maven repository, cluster state, results |
| `BASELINE_REF` / `CANDIDATE_REF` | `origin/PREPARATION` / `origin/HADOOP-99999` | the two trees |
| `MAVEN_MIRROR_URL` | none | mirror of Maven Central, e.g. `https://maven-central.storage-download.googleapis.com/maven2` when the build host is rate-limited |
| `MVN_EXTRA_ARGS` | none | added to every Maven call |
| `M2_REPO` | `$WORKDIR/m2` | Maven repository; both sides share downloads but install into separate prefixes |
| `UNIT_RERUNS` | 1 | re-runs of a failing test before it counts as failed |
| `E2E_NFS` | `auto` | start the NFS gateway (`auto` = when running as root) |
| `E2E_GRIDMIX` | `true` | run the gridmix sleep jobs |
| `E2E_NM_MEMORY_MB` | 6144 | node manager memory |
| `DAEMON_HEAP` | `384m` | heap of each daemon |

Single parts can be re-run: `e2e/run.sh candidate 40-yarn` runs one
scenario file, `unit-tests.sh candidate quick resourcemanager` one module,
`e2e/cluster.sh candidate start|status|stop` drives the cluster by hand.
`artifact-diff.sh candidate candidate` compares one build with itself,
which must report no differences.

## Reading the report

`$WORKDIR/results/compare/report.md` has one section per check and an
overall verdict. Supporting data sits next to it (`artifact-diff.json`,
`e2e-compare.json`, `classload-compare.json`, `unit-compare.json`) and
under `results/<side>/` (raw observations, CLI output, daemon start-up,
scenario logs, surefire reports).

- **UNEXPECTED** artifact differences, **DIFF**/**REGRESSION**/**MISSING**
  observations, classes loaded from an unexpected jar, log errors only the
  candidate has, and unit tests that passed on the baseline but fail on the
  candidate fail the run.
- **BOTH_FAIL** observations and tests failing on both sides are not caused
  by the patch, but each one hides what it was checking: look at them before
  relying on a run.
- "Allowlist rules that matched nothing" means a change the patch should
  have made did not show up; check why.

When the patch changes, update `expected-differences.txt` and
`e2e/expected-e2e-differences.txt`, naming the JIRA for each rule, and keep
the patterns narrow.
