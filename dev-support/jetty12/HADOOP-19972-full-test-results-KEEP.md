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

## Wave 1: web-facing modules (23), in progress
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
| hadoop-yarn-server-nodemanager, and 10 more | *running* | | | |

### Failing test classes so far (not yet compared with trunk)
All of the `hadoop-common` failures below are in file-permission, disk-check or native-library tests. None involve HTTP or Jetty.
- **Root user:** these assert that a directory without permissions cannot be read or deleted, which root can always do.
  - `fs.TestFileUtil`, `fs.TestFsShellCopy`, `fs.TestLocalDirAllocator`, `fs.TestLocalFileSystem`
  - `fs.TestFSMainOperationsLocalFileSystem`, `fs.viewfs.TestFSMainOperationsLocalFileSystem`, `fs.shell.TestPathData`
  - `util.TestDiskChecker`, `util.TestBasicDiskValidator`, `util.TestReadWriteDiskValidator`
  - `metrics2.sink.TestRollingFileSystemSinkWithLocal`
- **No native library:** `util.TestNativeCodeLoader` reports "libhadoop.so testing was required, but libhadoop.so was not loaded".
- **hadoop-yarn-server-nodemanager** (still running): `TestLinuxContainerExecutorWithMocks`, `TestNodeStatusUpdater`, `amrmproxy.TestFederationInterceptor`. Not yet examined.

## Wave 2: hadoop-hdfs, yarn-server-resourcemanager, hadoop-hdfs-rbf, mapreduce-client-jobclient
Not started.

## Wave 3: all remaining modules
Not started.

## Comparison with trunk
Not started.

## Progress log
- 2026-09-25T17:48Z: full build and shadedclient passed; wave 1 started.
- 2026-09-25T18:44Z: wave 1 on module 13 of 23 (nodemanager). 12 modules done; the only failures are the environment-looking ones above.
