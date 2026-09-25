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

Status: **in progress**. This file is updated as each test wave finishes and replaced by a final summary when the run is complete.

## What is tested
- **Build, shadedclient and wave 1:** `jetty-phase-c` @ `056c5623` merged with apache/trunk @ `90f0d1da`. That is PR [apache/hadoop#8704](https://github.com/apache/hadoop/pull/8704) as CI would merge it.
- **From wave 2 on:** `jetty12-keep-behaviour` merged with the same trunk. It is the PR plus the four keep-path commits, which change only `hadoop-common`, so `hadoop-common` is re-run on this tree.
- **Environment:** a Claude Code cloud container with 4 CPUs, 15 GB RAM and JDK 21.0.10, using the repo's `./mvnw` (Maven 3.9.15). Tests run **as root**, and **without native libraries** (`libhadoop.so` is not built).
- **Command:** `./mvnw test -fae -Dmaven.test.failure.ignore=true -Dcheckstyle.skip -Dspotbugs.skip -Dmaven.javadoc.skip`, one wave of modules at a time. Every failing test class is then re-run on plain trunk, to separate regressions from failures trunk already has.

## Build and packaging
| Check | Result |
|---|---|
| `install -DskipTests`, whole reactor | **PASS**: 119/119 modules, 17 min 48 s |
| shadedclient: `hadoop-client-check-invariants` and `-check-test-invariants` | **PASS** |
| shadedclient: `hadoop-client-integration-tests` | **PASS**: `ITUseMiniCluster` 2/2 and `ITUseHadoopCodecs` 3/3 |

## Keep-path commits (`jetty12-keep-behaviour`)
Run on the keep branch itself: `TestHttpServer` 39/39, `TestHttpServerLogs` 4/4 and `TestCommonConfigurationFields` 4/4 pass. Each of the four commits compiles on its own, tests included.

Added afterwards: `1800f323` fixes a units bug in the PR itself. `HttpServer2Metrics` published Jetty 12's nanosecond request and dispatch times under their "(in ms)" names, so they read a million times too high. With the fix, `TestHttpServer2Metrics` passes 2/2 and `TestHttpServer` 39/39, including a real-server check that `requestTimeMax` and `dispatchedTimeMax` are plausible milliseconds. Without the conversion all three checks fail.

## Wave 1: web-facing modules (23), finished 19:28Z (1 h 41 min)
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

## Wave 2: hadoop-hdfs, yarn-server-resourcemanager, hadoop-hdfs-rbf, mapreduce-client-jobclient
Not started.

## Wave 3: all remaining modules
Not started.

## Comparison with trunk
Not started.

## Progress log
- 2026-09-25T17:48Z: full build and shadedclient passed; wave 1 started.
- 2026-09-25T18:44Z: wave 1 on module 13 of 23 (nodemanager). 12 modules done; the only failures are the environment-looking ones above.
- 2026-09-25T19:18Z: nodemanager hung in `TestResourceLocalizationService` (see above). Its test JVM was killed and the module continued.
- 2026-09-25T19:23Z: metrics units fix `1800f323` pushed to jetty12-keep-behaviour. The keep-branch tree tested from wave 1b on includes it.
- 2026-09-25T19:28Z: wave 1 finished. 12 modules were clean; hadoop-common has 37 failures (environment); nodemanager has 58 F and 62 E (environment and container executor), plus 1 hang; 8 modules were skipped behind nodemanager. Switched the tree to jetty12-keep-behaviour + trunk; rebuild and wave 1b (hadoop-common plus the 8 skipped modules) started.
