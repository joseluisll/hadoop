<!--
  Licensed to the Apache Software Foundation (ASF) under one or more
  contributor license agreements.  See the NOTICE file distributed with
  this work for additional information regarding copyright ownership.
  The ASF licenses this file to You under the Apache License, Version 2.0
  (the "License"); you may not use this file except in compliance with
  the License.  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

# HADOOP-19972 — full build and test results (keep path)

Status: **run 2 in progress**. Run 1 was stopped at 19:31Z because most of its failures came from the test environment, not the code (see "Run 1: superseded" below). Run 2 starts over in a corrected environment. This file is updated as each step finishes.

## Run 2: what is tested
- **Tree:** `jetty12-keep-behaviour` @ `618f27c5`, merged with apache/trunk @ `90f0d1da`. That is PR [apache/hadoop#8704](https://github.com/apache/hadoop/pull/8704) (`jetty-phase-c` @ `056c5623`), plus the four keep-path commits and the metrics units fix `1800f323`.
- **Environment:** a Claude Code cloud container with 4 CPUs, 15 GB RAM and JDK 21.0.10, using the repo's `./mvnw` (Maven 3.9.15). Three corrections from run 1:
  1. **Non-root.** Maven and every test JVM run as an unprivileged user (`builder`, uid 1001), as in Hadoop's CI image.
  2. **Disk headroom.** The tree is on `/dev/shm` (a 16 GB tmpfs, nearly empty). On the container's root disk, Java sees 24.7 GB usable out of 252 GB total, which reads as 90.2% full. The NodeManager's disk health checker (`max-disk-utilization-per-disk-percentage` = 90.0) therefore rejected every local directory.
  3. **Native library.** `libhadoop.so` is built with `-Pnative` in hadoop-common, and tests run with `-Drequire.test.libhadoop=true`, as CI's native build does. Every module's test JVM finds it through `LD_LIBRARY_PATH`. The C/C++ HDFS client (`hadoop-hdfs-native-client`'s libhdfs++) is not built natively: it needs Boost 1.86 and protobuf 3.25 with abseil compiled from source, and its tests are C/C++ tests that do not involve Jetty.
- **Commands:** `./mvnw test -fn -Dmaven.test.failure.ignore=true -Drequire.test.libhadoop=true -Dcheckstyle.skip -Dspotbugs.skip -Dmaven.javadoc.skip`, one wave of modules at a time. `-fn` means a failing module no longer causes its dependents to be skipped. Every failing test class is then re-run on plain trunk in the same environment.

## Run 2: results
### Build
`install -DskipTests` (whole reactor) as `builder`: **PASS** in 13 min 26 s. `libhadoop.so` is built with `-Pnative` in hadoop-common.

### Environment check
Before the full run, ten of the classes that failed in run 1 for environmental reasons were re-run in the run-2 environment. **All pass: 10 classes, 285 tests, 0 failures, 0 errors.**

| Class | Run 1 cause | Run 2 |
|---|---|---|
| `util.TestNativeCodeLoader` | no libhadoop | 1/1 |
| `util.TestDiskChecker` | root | 14/14 |
| `util.TestBasicDiskValidator` | root | 14/14 |
| `fs.TestFileUtil` | root | 50/50 |
| `fs.TestLocalDirAllocator` | root | 48/48 |
| `nodemanager.TestDirectoryCollection` | disk "90% full" | 9/9 |
| `nodemanager.TestLocalDirsHandlerService` | disk "90% full" | 3/3 |
| `nodemanager.health.TestNodeHealthCheckerService` | disk "90% full" | 3/3 |
| `nodemanager.webapp.TestNMWebServices` | disk "90% full" | 19/19 |
| `nodemanager.containermanager.linux.runtime.TestDockerContainerRuntime` | root ("uid: 0 below threshold") | 124/124 |

### Steps
The steps run in order: shadedclient, wave 1 (the 23 web-facing modules), wave 2 (hadoop-hdfs, yarn-server-resourcemanager, hadoop-hdfs-rbf and mapreduce-client-jobclient), then wave 3 (all remaining modules). A watchdog kills any test JVM that makes no progress for 20 minutes, after taking a thread dump, and records it here as a hang. Results follow as each step finishes.

---

# Run 1: superseded
Run 1 tested `jetty-phase-c` @ `056c5623` merged with apache/trunk @ `90f0d1da`, **as root, on the container's root disk, without native libraries**. The build (119/119 modules) and the shadedclient checks passed; their results are below. The unit test failures were dominated by the environment:
- **Root:** tests that expect a permission denial got none: hadoop-common's disk-checker and file-permission tests. In the NodeManager, `TestDockerContainerRuntime` failed with "uid: 0 below threshold: 1" (50 errors), and `TestNodeManagerReboot` expected a non-root user cache.
- **Disk "90% full":** the NodeManager rejected all local directories. This caused `TestDirectoryCollection`, `TestLocalDirsHandlerService`, `TestNodeHealthCheckerService`, `TestNMWebServices` (before any HTTP request) and `TestLinuxContainerExecutorWithMocks` to fail, and probably most container-lifecycle failures that followed.
- **No `libhadoop.so`:** `TestNativeCodeLoader` failed. Without `-Drequire.test.libhadoop`, Maven passes the literal `${require.test.libhadoop}`, which the test reads as "required".
- A hang in `TestResourceLocalizationService` had to be killed. That made Maven treat the NodeManager as failed and skip its 8 dependents.

## Run 1: build and packaging
| Check | Result |
|---|---|
| `install -DskipTests`, whole reactor | **PASS**: 119/119 modules, 17 min 48 s |
| shadedclient: `hadoop-client-check-invariants` and `-check-test-invariants` | **PASS** |
| shadedclient: `hadoop-client-integration-tests` | **PASS**: `ITUseMiniCluster` 2/2 and `ITUseHadoopCodecs` 3/3 |

## Keep-path commits (`jetty12-keep-behaviour`): tests on the branch itself
Run on the keep branch itself: `TestHttpServer` 39/39, `TestHttpServerLogs` 4/4 and `TestCommonConfigurationFields` 4/4 pass. Each of the four commits compiles on its own, tests included.

Added afterwards: `1800f323` fixes a units bug in the PR itself. `HttpServer2Metrics` published Jetty 12's nanosecond request and dispatch times under their "(in ms)" names, so they read a million times too high. With the fix, `TestHttpServer2Metrics` passes 2/2 and `TestHttpServer` 39/39, including a real-server check that `requestTimeMax` and `dispatchedTimeMax` are plausible milliseconds. Without the conversion all three checks fail.

## Run 1, wave 1: web-facing modules (as root, no native, root disk)
| Module | Run | Failures | Errors | Skipped |
|---|---|---|---|---|
| hadoop-auth | 186 | 0 | 0 | 0 |
| hadoop-common | 5574 | 37 | 0 | 380 |
| hadoop-nfs | 25 | 0 | 0 | 0 |
| hadoop-kms | 49 | 0 | 0 | 0 |
| hadoop-hdfs-client | 91 | 0 | 0 | 2 |
| hadoop-hdfs-httpfs | 607 | 0 | 0 | 0 |
| hadoop-hdfs-nfs | 71 | 0 | 0 | 0 |
| hadoop-yarn-common | 540 | 0 | 0 | 7 |
| hadoop-yarn-server-common | 553 | 0 | 0 | 11 |
| hadoop-yarn-server-applicationhistoryservice | 209 | 0 | 0 | 0 |
| hadoop-yarn-server-timelineservice | 85 | 0 | 0 | 0 |
| hadoop-yarn-server-web-proxy | 54 | 0 | 0 | 0 |
| hadoop-yarn-server-nodemanager | 1238 | 58 | 62 | 57 |
| hadoop-yarn-server-globalpolicygenerator | 33 | 0 | 0 | 0 |
| hadoop-resourceestimator | 47 | 0 | 0 | 0 |

When the hung `TestResourceLocalizationService` test JVM was killed, surefire marked `hadoop-yarn-server-nodemanager` as a build failure ("The forked VM terminated without properly saying goodbye"). Maven then **skipped the 8 modules that depend on it**: hadoop-yarn-client, hadoop-mapreduce-client-shuffle, -app and -hs, hadoop-yarn-server-router, hadoop-yarn-services-api, hadoop-yarn-applications-catalog-webapp and hadoop-sls. They run in wave 1b. From wave 1b on, runs use `--fail-never`, so a failing module no longer skips its dependents.

### Failing test classes (not yet compared with trunk)
All of the `hadoop-common` failures below are in file-permission, disk-check or native-library tests. None involve HTTP or Jetty.
- **Root user:** these assert that a directory without permissions cannot be read or deleted, which root can always do.
  - `fs.TestFileUtil`, `fs.TestFsShellCopy`, `fs.TestLocalDirAllocator`, `fs.TestLocalFileSystem`
  - `fs.TestFSMainOperationsLocalFileSystem`, `fs.viewfs.TestFSMainOperationsLocalFileSystem`, `fs.shell.TestPathData`
  - `util.TestDiskChecker`, `util.TestBasicDiskValidator`, `util.TestReadWriteDiskValidator`
  - `metrics2.sink.TestRollingFileSystemSinkWithLocal`
- **No native library:** `util.TestNativeCodeLoader` reports "libhadoop.so testing was required, but libhadoop.so was not loaded".
- **hadoop-yarn-server-nodemanager**: 19 classes. The only web-layer class, `webapp.TestNMWebServices`, fails before any HTTP request (see Disk health). The rest have not been examined individually yet:
  - **Linux container executor, Docker and cgroups** (need a real container runtime or cgroup hierarchy): `linux.runtime.TestDockerContainerRuntime` (2 F, 50 E), `linux.runtime.docker.TestDockerClient`, `linux.resources.TestCGroupsHandlerImpl`, `TestLinuxContainerExecutorWithMocks`.
  - **Disk health**: the NodeManager's disk checker rejects every local directory in this container. `TestDirectoryCollection`, `TestLocalDirsHandlerService` and `health.TestNodeHealthCheckerService` fail on it. `webapp.TestNMWebServices` (2 E, `testContainerLogsWith{New,Old}API`) fails in test setup with `DiskErrorException: No space available in any of the local directories`, before any HTTP request is made.
  - **Container lifecycle and scheduling**: `containermanager.TestContainerManager` (18 F), `launcher.TestContainerLaunch` (7 F, 6 E), `scheduler.TestContainerSchedulerQueuing` (11 F, 1 E), `scheduler.TestContainerSchedulerOppContainersByResources`, `monitor.TestContainersMonitor`, `logaggregation.TestLogAggregationService`, `TestNodeStatusUpdater`, `TestNodeManagerResync`, `TestNodeManagerReboot`, `TestNodeManagerShutdown`, `amrmproxy.TestFederationInterceptor`. Many launch real processes through the container executor, which likely hits the same environment limits.
  - All are for the trunk comparison.
- **Hang:** `localizer.TestResourceLocalizationService`. `testLocalizerHeartbeatWhenAppCleaningUp` busy-waited in `DummyExecutor.waitForLocalizers` (a `Thread.yield()` loop, `TestResourceLocalizationService.java:1112`) for 20 minutes at 100% CPU with no output. JUnit's same-thread timeout cannot interrupt that loop. The test JVM was killed at 19:18Z so the wave could continue. This is a test-side busy wait in the localizer, with no HTTP or Jetty involvement; it will be compared with trunk.

# Progress log
- 2026-09-25T17:48Z: full build and shadedclient passed; wave 1 started.
- 2026-09-25T18:44Z: wave 1 on module 13 of 23 (nodemanager). 12 modules done; the only failures are the environment-looking ones above.
- 2026-09-25T19:18Z: nodemanager hung in `TestResourceLocalizationService` (see above). Its test JVM was killed and the module continued.
- 2026-09-25T19:23Z: metrics units fix `1800f323` pushed to jetty12-keep-behaviour. The keep-branch tree tested from wave 1b on includes it.
- 2026-09-25T19:28Z: wave 1 finished. 12 modules were clean; hadoop-common has 37 failures (environment); nodemanager has 58 F and 62 E (environment and container executor), plus 1 hang; 8 modules were skipped behind nodemanager. Switched the tree to jetty12-keep-behaviour + trunk; rebuild and wave 1b (hadoop-common plus the 8 skipped modules) started.
- 2026-09-25T19:31Z: run 1 stopped at the user's request; most failures were environmental. Wave 1b was cancelled.
- 2026-09-25T19:36Z: run 2 set up: non-root `builder` user, tree on /dev/shm, `libhadoop.so` via `-Pnative`. Full build started.
- 2026-09-25T19:55Z: run 2 build passed; libhadoop built; the environment check passed (10 classes, 285 tests). Started shadedclient and waves 1 to 3, plus the hang watchdog.
