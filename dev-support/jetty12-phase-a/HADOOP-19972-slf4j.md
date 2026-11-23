# HADOOP-19972: Jetty 12.1.14 and slf4j 1.7.36

Checked on `origin/jetty-phase-c` at `907cfc03d9a`, on 2026-10-31.

## Verdict

The question was whether Jetty 12, recalled as being built for slf4j 2, would drop log events or fail on Hadoop's slf4j 1.7.36.

**That claim is half right, and there is one real problem, but not the one it predicted.**

- **The claim was right about the declaration.** Jetty 12.1.14 is built against slf4j 2.0.17.
- **Jetty does not need slf4j 2.** It calls only API that exists in 1.7.36. In Hadoop's own distribution, Jetty's events are not dropped, nothing fails, and `/logLevel` works.
- **There is a real regression for Maven consumers of the non-shaded artifacts.** Jetty's declaration gives them a new path to `slf4j-api:2.0.17`. Depending on declaration order, a working client ends up with `slf4j-api:2.0.17` and `slf4j-reload4j:1.7.36`. slf4j 2 ignores that binding, so **all logging on the classpath goes to NOP**, Hadoop's included, not just Jetty's. On trunk the same projects log normally.

**What should change:**

1. Keep slf4j 1.7.36 for HADOOP-19972.
2. Fix the regression in **HADOOP-20049**, a subtask of HADOOP-19912 created on 2026-10-31, landing before HADOOP-19972 or together with it. See "What should change" below.
3. Add the harness observations listed below.

Moving to slf4j 2 is not needed for Jetty 12. If anyone wants it, it needs its own ticket.

## Findings

### 1. What Jetty declares

`org.eclipse.jetty:jetty-project:12.1.14` sets `<slf4j.version>2.0.17</slf4j.version>` and manages `org.slf4j:slf4j-api` at that version.

| Pom | slf4j declaration |
|---|---|
| `jetty-util`, `jetty-http`, `jetty-io`, `jetty-server`, `jetty-session`, `jetty-security`, `jetty-xml`, `jetty-client`, `jetty-alpn-client` | `org.slf4j:slf4j-api` compile, not optional, 2.0.17 through the parent |
| `jetty-ee8-nested`, `jetty-ee8-servlet`, `jetty-ee8-webapp`, `jetty-ee8-security`, `jetty-ee-webapp` | same |
| `jetty-ee8-websocket-jetty-client`, `-jetty-server`, `-servlet`, `jetty-websocket-core-common` | same |
| `jetty-bom`, `jetty-ee8-bom` | no `slf4j-api` entry (`jetty-bom` lists only `jetty-slf4j-impl`) |
| Most of the above | `org.eclipse.jetty:jetty-slf4j-impl`, test scope only |
| `jetty-slf4j-impl:12.1.14` | `slf4j-api`, compile. Not on any Hadoop classpath |

The published jars also state 2.x in their metadata. Each has OSGi `Import-Package: org.slf4j;version="[2.0,3.0)"`, and `module-info` has `requires org.slf4j` (`requires transitive` in several).

Neither applies to Hadoop, which runs on the classpath. In any case, slf4j-api 1.7.36 has `Automatic-Module-Name: org.slf4j`, so the module name would resolve.

### 2. What resolves in Hadoop

| Scope | `slf4j-api` | Binding |
|---|---|---|
| `hadoop-common` | 1.7.36 compile | `slf4j-reload4j` 1.7.36 compile |
| `hadoop-yarn-server-resourcemanager` | 1.7.36 compile | `slf4j-reload4j` 1.7.36 test |
| `hadoop-client-runtime` | 1.7.36 runtime | none (`reload4j` 1.2.22 optional) |
| `hadoop-client-minicluster` | 1.7.36 compile | none |
| `share/hadoop/common/lib` | `slf4j-api-1.7.36.jar` | `slf4j-reload4j-1.7.36.jar`, `reload4j-1.2.22.jar`, plus `jul-to-slf4j-1.7.36.jar` |

No slf4j 2 jar is in the distribution, and `jetty-slf4j-impl` is not there either. Inside the build, `hadoop-project` dependency management pins 1.7.36.

**Nothing enforces an slf4j version.** The `depcheck` enforcer execution bans `org.slf4j:slf4j-log4j12` and `log4j:log4j`, and it has `DependencyConvergence`, but both act on Hadoop's own modules, where 1.7.36 is managed. They cannot see what a consumer resolves. The shaded-client invariants only allow `slf4j-api` to stay unshaded.

### 3. Bytecode

I checked every `org/slf4j` class and member reference against the real `slf4j-api-1.7.36.jar`, walking superinterfaces. The scan parsed the class files and loaded no code.

| Check | Result |
|---|---|
| 24 Jetty 12.1.14 jars, 2,196 classes | **0 unresolved references** |
| Classes referenced | Only `org/slf4j/Logger` and `org/slf4j/LoggerFactory` |
| Methods used | `getLogger(Class)`, `getLogger(String)`, `isXEnabled()`, `trace`/`debug`/`info`/`warn`/`error`, `getName()` |
| Raw constant-pool search, 25 jars with `jetty-servlet-api`, 2,282 classes | No `LoggingEventBuilder`, `SLF4JServiceProvider`, `atInfo`/`atDebug`/`atWarn` and so on, and no `org.slf4j` strings |
| `META-INF/services` | No slf4j provider files in any of the 24 jars |
| Shaded `hadoop-client-runtime` and `hadoop-client-minicluster` | 0 unresolved against 1.7.36 |

**Negative control:** the same scanner run on `jetty-slf4j-impl-12.1.14.jar` reports `org/slf4j/spi/SLF4JServiceProvider`, the one real 2-only reference. It also reports `Level.ordinal()`, a false positive, because the scanner does not follow `java.lang.Enum`. So it can find what it looks for, and that jar is not on Hadoop's classpath.

There are no slf4j 2-only hits for Hadoop's code paths to reach.

### 4. Observed behaviour

**A real `HttpServer2`.** The same `JettyLogProbe` ran on both distributions with the real launcher classpath, `slf4j-reload4j` binding and a file appender.

| | Trunk (Jetty 9.4.58) | `jetty-phase-c` (Jetty 12.1.14) |
|---|---|---|
| Logger class for Jetty | `org.slf4j.impl.Reload4jLoggerAdapter` | same |
| INFO at startup | yes (`org.eclipse.jetty.server.Server: jetty-9.4.58...`) | yes (`...: jetty-12.1.14; built: ...`) |
| WARN from a throwing servlet | `org.eclipse.jetty.server.HttpChannel: /boom` | `org.eclipse.jetty.ee8.nested.HttpChannel: /boom` |
| DEBUG after `/logLevel` set it | yes | yes, 1,240 log lines in total against 1,203 on trunk |
| Access log (`http.requests.probe`) | yes | yes |
| `SLF4J:` messages on stderr or in the log | none | none |

**Real daemons.** A NameNode and a ResourceManager ran from each distribution, using the distribution's own `log4j.properties` and `bin/hdfs --daemon start`.

| | Trunk | `jetty-phase-c` |
|---|---|---|
| NameNode: `curl /imagetransfer` | `WARN org.eclipse.jetty.server.HttpChannel: handleException /imagetransfer ...` | `WARN org.eclipse.jetty.ee8.nested.HttpChannel: handleException /imagetransfer ...` |
| NameNode: `/fsck` | WARN, same logger pattern | WARN, same logger pattern |
| `hadoop daemonlog -setlevel ... org.eclipse.jetty DEBUG` | 13,565 NameNode and 13,444 RM DEBUG lines | 13,402 and 13,228 |
| `daemonlog` reset to INFO | Effective level INFO | Effective level INFO |
| `.out` files | no `SLF4J` lines | no `SLF4J` lines |

The one count gap I followed up was at shutdown: the RM logs 3 context `Stopped` lines on trunk and none on `jetty-phase-c`. That is Jetty's own change: `ContextHandler` in 12.1.14 has no `Stopped` log literal. It does not indicate lost events.

### 5. Hadoop's log settings

| File | Entry | Status |
|---|---|---|
| `hadoop-kms/src/main/conf/kms-log4j.properties:41` | `log4j.logger.org.eclipse.jetty=INFO` | Still applies. log4j is hierarchical, so it covers `org.eclipse.jetty.ee8.*` |
| `hadoop-yarn-services-api/.../log4j-server.properties:76` | `log4j.logger.org.mortbay.log=DEBUG` | Stale and does nothing, but it is the same on trunk |
| `hadoop-common/src/main/conf/log4j.properties` | No Jetty entries; Jetty inherits the root logger | Works, as the daemon runs show |

With a KMS-shaped entry (`org.eclipse.jetty=WARN`), no Jetty INFO lines appeared, the 3 WARNs did, and `/logLevel` reported `org.eclipse.jetty.ee8` at effective level WARN. I tested this shape with the probe, not with a running KMS.

`/logLevel` reads and sets `org.eclipse.jetty`, `.server`, `.ee8` and `.ee8.nested`. Setting `org.eclipse.jetty.ee8` to ERROR suppressed the next `/boom` WARN, leaving 3 WARNs. Trunk logs 4, because its logger is not under `.ee8`.

**Logger names did change.** An operator's fine-grained settings stop matching, though repository config is unaffected. Announce this in the release note:

| Jetty 9.4 | Jetty 12 ee8 |
|---|---|
| `org.eclipse.jetty.server.HttpChannel` | `org.eclipse.jetty.ee8.nested.HttpChannel` and `org.eclipse.jetty.server.internal.HttpChannelState` |
| `org.eclipse.jetty.server.HttpConnection` | `org.eclipse.jetty.server.internal.HttpConnection` |
| `org.eclipse.jetty.server.session` | `org.eclipse.jetty.session.*`, `org.eclipse.jetty.ee8.nested.SessionHandler` |
| `org.eclipse.jetty.servlet.*` | `org.eclipse.jetty.ee8.servlet.*` |
| `org.eclipse.jetty.util.log` (`Logging initialized ... Slf4jLog`) | Gone; the line no longer appears |

### 6. Downstream

#### The regression

Fresh consumer projects with default Maven mediation, on trunk-era snapshots and on `jetty-phase-c`:

| Consumer's dependencies, in order | Trunk | `jetty-phase-c` |
|---|---|---|
| `hadoop-yarn-client`, then `hadoop-client` | 1.7.36, Reload4j | **api 2.0.17 + binding 1.7.36: NOP** |
| `hadoop-hdfs`, then `hadoop-client` | 1.7.36, Reload4j | **api 2.0.17 + binding 1.7.36: NOP** |
| `hadoop-client`, then `hadoop-yarn-client` | 1.7.36, Reload4j | 1.7.36, Reload4j |
| `hadoop-yarn-client`, then `hadoop-common` | 1.7.36, Reload4j | 1.7.36, Reload4j |
| `hadoop-hdfs`, then `hadoop-common` | 1.7.36, Reload4j | 1.7.36, Reload4j |
| `hadoop-yarn-client` alone | 1.7.36, Reload4j | api 2.0.17: NOP (but cannot run, no `hadoop-common`) |
| `hadoop-hdfs` alone | no slf4j at all | api 2.0.17: NOP (but cannot run, no `hadoop-common`) |

The first two rows are working clients: `YarnClient.createYarnClient()` succeeds and every logger is `NOPLogger`. The only sign is this at startup, on stderr:

```
SLF4J(W): No SLF4J providers were found.
SLF4J(W): Defaulting to no-operation (NOP) logger implementation
SLF4J(W): Class path contains SLF4J bindings targeting slf4j-api versions 1.7.x or earlier.
SLF4J(W): Ignoring binding found at [...slf4j-reload4j-1.7.36.jar!/org/slf4j/impl/StaticLoggerBinder.class]
```

With `hadoop-hdfs` then `hadoop-client`, `HttpServer2` also runs with no output: 0 log lines, 0 access log lines, and `/logLevel` answers `Sorry, setting log level is only supported for log4j loggers`.

**Cause.** In Jetty 9.4, `slf4j-api` is `provided` and optional, so it never reached consumers. In Jetty 12 it is compile scope. `hadoop-yarn-client`, `hadoop-hdfs` and `hadoop-hdfs-nfs` declare Jetty directly, do not declare `slf4j-api`, and keep `hadoop-common` at `provided`. So Jetty's 2.0.17 sits at depth 3, for example:

```
consumer -> hadoop-yarn-client -> jetty-ee8-websocket-jetty-client -> slf4j-api:2.0.17
```

Hadoop's own `slf4j-api:1.7.36` path through `hadoop-client` is also at depth 3, so the first one declared wins. A Hadoop parent's dependency management does not reach a consumer's view of Jetty's transitive dependencies. The binding has no such competitor, so it stays at 1.7.36.

**How widely it applies.** I resolved all 89 published Hadoop jar artifacts as sole dependencies. Exactly three moved to 2.0.17: `hadoop-hdfs`, `hadoop-hdfs-nfs`, `hadoop-yarn-client`. The same three, and no others, flip when each of the 89 is declared before `hadoop-client`. Other orderings and larger dependency sets were not swept. I do not know how common these orderings are in real projects. Projects that manage slf4j themselves are unaffected.

#### Already broken on trunk, and not caused by Jetty

| Consumer | Result on both sides |
|---|---|
| `hadoop-common` + `slf4j-api:2.0.17` only | NOP |
| `hadoop-common` + `slf4j-api:2.0.17` + `slf4j-reload4j:2.0.17` | Logging works, Jetty INFO and WARN reach log4j, but **`/logLevel` refuses**: `Sorry, setting log level is only supported for log4j loggers` |

The second row is because `GenericsUtil.java:37` hard-codes `org.slf4j.impl.Reload4jLoggerAdapter`, and slf4j-reload4j 2 moved that class to `org.slf4j.reload4j`.

`hadoop-azure` and `hadoop-cloud-storage` resolve `slf4j-api:2.0.9` through `arrow-vector`, which is also on trunk and unrelated to Jetty.

#### Shaded clients

| | `hadoop-client-runtime` | `hadoop-client-minicluster` |
|---|---|---|
| slf4j classes in the jar | 0 | 0 |
| Relocated slf4j | No | No |
| `dependency-reduced-pom` | `slf4j-api:1.7.36`, runtime | Through `hadoop-client-runtime` |
| Jetty | Relocated to `org.apache.hadoop.shaded.org.eclipse.jetty` | Same |

slf4j is left for the consumer, as on trunk. Their fresh-consumer resolution is 1.7.36 on both sides, so the regression does not touch them.

A real slf4j 2 consumer (`slf4j-api:2.0.17`, `slf4j-reload4j:2.0.17`) ran `MiniDFSCluster` from `hadoop-client-minicluster` on both sides. The web UI answered, and Jetty's INFO and WARN events reached log4j under `org.apache.hadoop.shaded.org.eclipse.jetty.*`. That shaded prefix is on trunk too, so a consumer's `org.eclipse.jetty` setting does not match it on either side.

## What should change

**Keep 1.7.36.** Jetty works correctly on it, and the bytecode proves that for all of Jetty, not just the paths the probe exercised.

**Fix the regression in HADOOP-20049, a subtask of HADOOP-19912.** It must not land after HADOOP-19972, or trunk carries the regression in between. The form validated below is an exclusion on the 12.1.14 entries, but only `jetty-server`, `jetty-util` and `jetty-http` exist before HADOOP-19972; that ticket creates the other 5, and Jetty 9.4 has no compile dependency on slf4j, so the exclusion does nothing until then. The subtask therefore has two options:

- **Land first, declaring `slf4j-api`** in `hadoop-hdfs`, `hadoop-hdfs-nfs` and `hadoop-yarn-client`. This needs no change to HADOOP-19972. **Chosen, in apache/hadoop#8903.** Tested against `jetty-phase-c` artifacts with edited pom copies. The commit compiles on Jetty 9.4; it has not been built together with Jetty 12.
- **Stack on HADOOP-19972 with the exclusion** and merge the two together. Also works, and passed a full build, but it cannot land first.

Both gave the same result against an unfixed control. Declared before `hadoop-client`, the 3 artifacts that resolved `slf4j-api` 2.0.17 unfixed resolve 1.7.36 with either fix, and the other 86 of the 89 stay as they were. The real consumers go from NOP to Reload4j, and `hadoop-hdfs` then `hadoop-client` goes from 0 log lines to 906. One difference: with the declaration, `hadoop-hdfs` and `hadoop-hdfs-nfs` alone resolve `slf4j-api` 1.7.36, where trunk resolves none.

For the exclusion, in `hadoop-project/pom.xml`, add this to the 8 managed Jetty entries with an `org.eclipse.jetty*` group: `jetty-server`, `jetty-http`, `jetty-util`, `jetty-ee8-nested`, `jetty-ee8-servlet`, `jetty-ee8-webapp`, `jetty-ee8-websocket-jetty-server`, `jetty-ee8-websocket-jetty-client`.

```xml
<exclusions>
  <exclusion>
    <groupId>org.slf4j</groupId>
    <artifactId>slf4j-api</artifactId>
  </exclusion>
</exclusions>
```

`jetty-ee8-websocket-jetty-server` already has an `<exclusions>` block, so add to it.

The exclusion is one place, and it puts these modules back to their trunk state. Coverage of both options was tested only in the orderings listed here.

**Validated on a scratch copy only; the exclusion is not committed anywhere:**

| Check, with the exclusion | Result |
|---|---|
| All 89 artifacts as sole dependency | No `slf4j-api` 2.0.17 left. Only the `arrow-vector` 2.0.9 cases remain |
| `hadoop-yarn-client`, then `hadoop-client` | 1.7.36, Reload4j, `YarnClientImpl` created |
| `hadoop-hdfs`, then `hadoop-client` | 1.7.36, Reload4j, Jetty INFO, WARN, DEBUG and access log all present |
| `hadoop-hdfs` alone | No slf4j, as on trunk (`hadoop-hdfs-nfs` likewise) |
| Full `package -Pdist -DskipTests` build | BUILD SUCCESS, all 120 modules, 0 compile errors. `share/hadoop/common/lib` file list identical. Only `slf4j-api-1.7.36.jar` and `slf4j-reload4j-1.7.36.jar` in the distribution |

**Move to slf4j 2 only as a separate ticket, and only if someone wants it for its own sake.** It would change the binding every downstream gets, and it first needs `GenericsUtil` fixed, or `/logLevel` stops working in the daemons. Jetty 12 gives no reason to do it now.

## What the harness should record

Add both to step 3. Neither is covered by `logscan.py`, which looks only for linkage and provider errors.

**A. Consumer logging binding, in `downstream-deps.sh`.** For every project, record this tuple:

```
<artifact> <scenario> slf4j-api=<version> binding=<artifact:version|none> factory=<LoggerFactory.getILoggerFactory() class name>
```

- **Fail** when `factory` is `org.slf4j.helpers.NOPLoggerFactory` on the candidate and not on the baseline, or when the `slf4j-api` major version differs from the binding's.
- **Add a scenario** `then-hadoop-client`: the Hadoop artifact, then `hadoop-client`. The existing `plain` scenario already shows `hadoop-yarn-client` going from 1.7.36 to 2.0.17, but only the new scenario shows a client that works and logs nothing.
- **Add `hadoop-hdfs-nfs`** to `ARTIFACTS`.
- **Do not allowlist** an `org.slf4j:slf4j-api` version change in `expected-downstream-differences.txt`.

**B. Jetty log delivery, in the e2e runs, per daemon with an HTTP server:**

1. The log contains `INFO org.eclipse.jetty.server.Server: jetty-<jetty.version>`.
2. `GET /logLevel?log=org.eclipse.jetty` reports `Log Class: org.slf4j.impl.Reload4jLoggerAdapter`.
3. After `hadoop daemonlog -setlevel <addr> org.eclipse.jetty DEBUG` and one request, the count of `DEBUG org.eclipse.jetty` lines is above 0. Setting it back to INFO reports `Effective Level: INFO`.
4. On the NameNode, `GET /imagetransfer` gives HTTP 410 and exactly one `WARN org.eclipse.jetty.ee8.nested.HttpChannel: handleException /imagetransfer` (`org.eclipse.jetty.server.HttpChannel` on the Jetty 9 baseline).
5. No line matching `^SLF4J(\(W\))?:` in any `.log` or `.out`. Add that pattern to `logscan.py`'s `PATTERN`.

Compare presence, not line counts: DEBUG volume differs between Jetty versions, and the logger names and message text change as listed in section 5.

## Side findings, unrelated to slf4j

None of these is fixed here. They belong with the HADOOP-19972 compatibility notes.

- **Access log format.** An absent `Referer` or `User-Agent` logs as `""` on Jetty 12, and as `"-"` on trunk. Log parsers may care.
- **Bad requests in the access log.** A request rejected for a malformed header is logged on `jetty-phase-c` (`"GET /bad HTTP/1.1" 400`) and not on trunk.
- **`/%c0`.** The NameNode answers 400 on `jetty-phase-c`, and 404 on trunk.
- **Missing `/static` directory.** Jetty 12 refuses a missing base resource, and `HttpServer2` handles that for `/logs` but not for `/static`. A missing `<webapps>/static` stops `start()` with `Base Resource is not valid`. Both `webapps` directories in the distribution have `static`, so this only affects code embedding `HttpServer2` with its own webapps directory. My own probe hit it first.

## Not verified

- Real downstream projects (Spark, Hive, HBase, Tez). I used synthetic consumers only, and how common the bad ordering is remains unknown.
- A logback consumer. The slf4j 2 runs used `slf4j-reload4j:2.0.17`.
- A running KMS or HttpFS daemon, a NodeManager, and TLS or Kerberos daemons. The NameNode, ResourceManager and probe paths were plain HTTP.
- Unit tests with the exclusion applied. Only the build and the checks above ran.
- Baselines: the probe and daemon runs used a build of `84f77af53c9` (`PREPARATION` merged with trunk, `hadoop-project/pom.xml` identical to `upstream/trunk`). The Maven consumer baseline used the `3.6.0-SNAPSHOT` artifacts in `~/.m2`, from early October, on Jetty 9.4.58 and slf4j 1.7.36. Neither is exactly `upstream/trunk`.

## How this was run

Everything ran in a scratch worktree at `907cfc03d9a`, built with Java 17 and `install -Pdist -DskipTests` into a private Maven repo layered over `~/.m2`, so the shared repo was not written. No tests were run through Maven.
