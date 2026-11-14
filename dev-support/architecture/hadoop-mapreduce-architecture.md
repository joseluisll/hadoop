# Apache Hadoop MapReduce — Architecture (hadoop-mapreduce-project)

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

An onboarding-oriented walkthrough of `hadoop-mapreduce-project/` on trunk, grounded in the
actual source tree. Depth: the component plus its first-level subcomponents (the
`hadoop-mapreduce-client-*` modules and `hadoop-mapreduce-examples`), with runtime behaviour
described end to end: submission → AM allocation → map task (sort/spill) → shuffle → reduce →
commit → history events.

## Table of contents

1. [Module layout](#1-module-layout)
2. [The MapReduce programming model (client-core, `org.apache.hadoop.mapreduce`)](#2-the-mapreduce-programming-model-client-core-orgapachehadoopmapreduce)
3. [Classic task runtime (client-core, `org.apache.hadoop.mapred`)](#3-classic-task-runtime-client-core-orgapachehadoopmapred)
4. [Job submission flow (client-jobclient + client-core)](#4-job-submission-flow-client-jobclient--client-core)
5. [The MapReduce ApplicationMaster (client-app)](#5-the-mapreduce-applicationmaster-client-app)
6. [Shuffle (client-shuffle + reduce-side fetcher in client-core)](#6-shuffle-client-shuffle--reduce-side-fetcher-in-client-core)
7. [JobHistoryServer (client-hs)](#7-jobhistoryserver-client-hs)
8. [Native task execution (client-nativetask, brief)](#8-native-task-execution-client-nativetask-brief)
9. [Small modules: client-common, client-hs-plugins, client-uploader](#9-small-modules-client-common-client-hs-plugins-client-uploader)
10. [hadoop-mapreduce-examples (brief)](#10-hadoop-mapreduce-examples-brief)
11. [End-to-end runtime flow](#11-end-to-end-runtime-flow)
12. [Failure handling](#12-failure-handling)
13. [Behaviour summary per subcomponent](#13-behaviour-summary-per-subcomponent)
14. [Concurrency (per subcomponent)](#14-concurrency-per-subcomponent)
15. [Security](#15-security)
16. [Logging and auditability](#16-logging-and-auditability)
17. [Integration points](#17-integration-points)
18. [Non-functional requirement candidates](#18-non-functional-requirement-candidates)

---

## 1. Module layout

`hadoop-mapreduce-project/` builds the MapReduce application framework on top of YARN.
`hadoop-mapreduce-client/pom.xml` declares the modules (build order matters):

| Module | Role |
|---|---|
| `hadoop-mapreduce-client-core` | Programming model, `JobConf`/`Job`, classic `Task` runtime, IFile, history event definitions |
| `hadoop-mapreduce-client-common` | Shared client/AM/JHS records: job IDs, `Counters`/`CounterGroup` PB impls, protocol request/response wrappers, `MRClientProtocol` machinery |
| `hadoop-mapreduce-client-shuffle` | `ShuffleHandler`, the NodeManager aux-service that serves map outputs |
| `hadoop-mapreduce-client-app` | The MapReduce ApplicationMaster (`MRAppMaster`) and its state machines |
| `hadoop-mapreduce-client-jobclient` | YARN-facing job client (`YARNRunner`, `ResourceMgrDelegate`) |
| `hadoop-mapreduce-client-hs` | JobHistoryServer (JHS) |
| `hadoop-mapreduce-client-hs-plugins` | `MapReduceTrackingUriPlugin` (lets the RM's web UI link to the JHS) |
| `hadoop-mapreduce-client-nativetask` | C++ map/reduce task execution with a Java bridge |
| `hadoop-mapreduce-client-uploader` | `FrameworkUploader`, packages MR framework jars into a shared-cache archive |

There is no "MapReduce daemon" for job scheduling any more: the old JobTracker is gone, the
ApplicationMaster is the scheduler for a single job, and the NodeManager hosts both the task
containers and the shuffle aux service.

## 2. The MapReduce programming model (client-core, `org.apache.hadoop.mapreduce`)

**Purpose.** The public API a user's job plugs into, plus the client-side `Job` orchestration.

**Key classes.** `Job` (the user-facing handle and submission driver), `Mapper`, `Reducer`,
`InputFormat`/`InputSplit`/`RecordReader`, `OutputFormat`/`RecordWriter`/`OutputCommitter`,
`Partitioner`, `Counters`/`Counter`/`CounterGroup`, context objects `JobContext`,
`TaskAttemptContext`, `MapContext`, `ReduceContext`, `TaskInputOutputContext`, and
`MRJobConfig`/`MRConfig` for configuration keys. Data structures are deliberately thin:
`Job` wraps a `JobConf` plus a `Cluster`; contexts wrap the same conf with task/attempt IDs.

**Behaviour.** `Job` implements `JobContext` and is the lifecycle owner: `waitForCompletion()`
calls `submit()` (one-shot, guarded), then polls status through the `Cluster`. The compute
interface is small — `Mapper.run()` loops `context.nextKeyValue()` and calls `map()`;
`Reducer.run()` loops over the values iterator per key via `ReduceContext`. `InputFormat`
answers two questions: how to cut input into `InputSplit`s (`getSplits`) and how to read a
split as `K,V` records (`createRecordReader`); splits carry only location hints, not data.
`OutputFormat` symmetrically creates a `RecordWriter` per task and an `OutputCommitter` for
job-level commit (see §11). `Partitioner` decides which reducer receives each map output key
(default: `hash(key) % numPartitions` in `HashPartitioner`). Counters are enum/group based;
framework counters live in `TaskCounter` and `JobCounter`, filesystem ones in
`FileSystemCounter`.

## 3. Classic task runtime (client-core, `org.apache.hadoop.mapred`)

**Purpose.** The code that actually executes inside a container, once the AM has launched it.
Despite the old `mapred` package name, this is what MRv2 tasks run.

**Key classes.** `Task` (abstract base, implements `Writable`), `MapTask`, `ReduceTask`,
`MapOutputCollector` (interface) with `MapTask.MapOutputBuffer` as the default in-memory
implementation, `TaskUmbilicalProtocol` (task ⇄ AM RPC), `TaskLog`, `JobConf`, `JobClient`
(legacy client facade), `TaskAttemptContextImpl`.

**Behaviour — MapTask sort/spill.** `MapTask.run()` opens the output via `NewOutputCollector`
(a `MapOutputCollector` that partitions through the `Partitioner`), then runs the user mapper
in a loop. `MapOutputBuffer` is the interesting data structure: a large circular key/value
byte buffer (`kvbuffer`) plus a parallel metadata array (`kvoffsets`/`kvindices`) holding
(partition, key offset, value offset). Collecting appends serialized bytes into the buffer and
records metadata; a lock (`spillLock`, conditions `spillReady`/`spillDone`) coordinates with a
dedicated `SpillThread`. When collected metadata crosses a *soft limit* —
`kvbuffer.length * spillper`, where spillper is `mapreduce.map.sort.spill.percent` — the
collect thread blocks while the spill thread sorts the in-memory span (quick-sort over the
metadata, comparing keys via the configured comparator), applies the optional combiner per
partition, and writes one spill file per pass through `IFile` (the on-disk K/V sequence
format, with per-record checksums; compressed if configured). Spills accumulate in the local
task dir; when the mapper finishes, `mergeParts()` does a multi-way merge of the spill files
into a single partitioned output file (again running the combiner where a merge would not
change the result, i.e. when the number of values from one spill for a key is below
`minNumSpillsForCombine` semantics — see `MapTask` for the exact predicate). Counters
`MAP_OUTPUT_RECORDS`, `SPILLED_RECORDS` track progress.

**Behaviour — ReduceTask.** `ReduceTask.run()` has two phases before user code: copy
(shuffle) and sort (merge), then `runNewReducer()`. The shuffle itself is delegated to a
`ShuffleConsumerPlugin` — default class `org.apache.hadoop.mapreduce.task.reduce.Shuffle`,
described in §6. Its `run()` returns a `RawKeyValueIterator` over the merged map output;
`ReduceTask` then wraps it in a grouping `ValueIterator` (grouping comparator decides value
groups per key) and invokes the user reducer, writing through the `RecordWriter`.

## 4. Job submission flow (client-jobclient + client-core)

**Purpose.** Everything between `job.waitForCompletion()` and an ApplicationMaster starting.

**Key classes.** In core: `Job.submit()`, `JobSubmitter`, `JobResourceUploader`,
`JobSubmissionFiles`, `Cluster`, `JobSplitWriter` (with `JobSplit` meta records). In
jobclient: `YARNRunner`, `ResourceMgrDelegate`, `ClientServiceDelegate`, `ClientCache`,
`YarnClientProtocolProvider`.

**Behaviour.** `Job.submit()` → `JobSubmitter.submitJobInternal()`:

1. `JobSubmissionFiles.getStagingDir()` resolves the per-user staging area under
   `yarn.app.mapreduce.am.staging-dir` (permissions set to 700).
2. `copyAndConfigureFiles()` uploads the job jar, `-libjars`, `-files`, `-archives` to the
   staging dir (`JobResourceUploader` handles the remote-copy and localization semantics).
3. `writeSplits()` computes `InputSplit`s via the `InputFormat` and writes
   `job.split`/`job.splitmetainfo` with `JobSplitWriter`; the map count = split count.
4. `writeConf()` writes the sanitized `job.xml` (job-token references stripped first).
5. Delegation tokens (`JobToken`, FS tokens) go into the `Credentials`; `JobSubmitter`
   also adds `mapreduce.job.token*` secret material for the shuffle.
6. Control transfers to `Cluster.getClient()` — under YARN that is
   `YarnClientProtocolProvider` → `YARNRunner`.

`YARNRunner` builds an `ApplicationSubmissionContext` (`createApplicationSubmissionContext`),
sets the AM launch command to `MRAppMaster` (with the job conf path, staging dir and user),
sets resources/ACLs/tokens, and calls `resMgrDelegate.submitApplication()` —
`ResourceMgrDelegate` wraps `YarnClientImpl`. All subsequent status/kill/counter calls go
through `ClientServiceDelegate`, which finds the current `MRClientProtocol` endpoint: first
the AM, and after the AM finishes, the JobHistoryServer. `ClientCache` memoizes proxies per
job; `NotRunningJob` stubs responses for jobs whose history is not yet loaded.

## 5. The MapReduce ApplicationMaster (client-app)

**Purpose.** One AM instance per job. It initializes the job from the staging dir, asks the
ResourceManager for containers, launches tasks, drives the state machines, commits the job,
and writes history events.

**Key classes.** `MRAppMaster` (composite YARN service), `JobImpl`/`TaskImpl`/
`MapTaskImpl`/`ReduceTaskImpl`/`TaskAttemptImpl` state machines (in
`org.apache.hadoop.mapreduce.v2.app.job.impl`), event classes under `job.event` (`JobEventType`,
`TaskEventType`, `TaskAttemptEventType`, `CommitterEventType`, ...), allocator side
`RMContainerAllocator`/`RMContainerRequestor`/`LocalContainerAllocator`, launcher
`ContainerLauncherImpl`, `CommitterEventHandler`, speculation `Speculator`/`DefaultSpeculator`
with `ExponentiallySmoothedTaskRuntimeEstimator`, and the AM web UI (`AMWebApp`).

**Main data structures.** An async `Dispatcher` (AsyncDispatcher) with typed event buses —
`JobEventType`, `TaskEventType`, `TaskAttemptEventType`, `ContainerAllocator.EventType`,
`ContainerLauncher.EventType`, `CommitterEventType`, and the history
`org.apache.hadoop.mapreduce.jobhistory.EventType`. Each state machine is a
`StateMachineFactory` wiring (state, event) → transition/hook. `AppContext` exposes
`getAllJobs()`/job/task/attempt maps to every subsystem.

**Behaviour.** `MRAppMaster.main()` → `init()`/`start()` (serviceInit in the code):
create the job classloader, create and register the dispatcher, then — in order — the
`JobEventDispatcher`, `TaskEventDispatcher`, `TaskAttemptEventDispatcher`,
`CommitterEventHandler`, `ContainerAllocator`, `ContainerLauncher`, the speculator, and the
`JobHistoryEventHandler` (the component that serializes history events, described in §7).
`MRAppMaster` verifies the staging dir exists and aborts with a diagnostic if it does not; on
successful jobs a staging-dir cleaner runs after AM unregistration with the RM.

*Job level.* `JobImpl` starts `NEW`; `JOB_INIT` (`InitTransition`) reads `job.xml`/splits
from staging, builds `MapTaskImpl`s and `ReduceTaskImpl`s, and wires the job's `Task`s.
`JOB_START` moves it to `RUNNING`; setup runs via the committer
(`JOB_SETUP_COMPLETED`), then tasks drive `JOB_TASK_COMPLETED`/`JOB_TASK_ATTEMPT_COMPLETED`
events toward completion, then `JOB_COMMIT_*` via `CommitterEventHandler`, then
`JOB_COMPLETED`. Kill is `JOB_KILL`; `JOB_AM_REBOOT` handles RM-level reboots;
`JOB_FAIL_WAIT_TIMEDOUT` bounds the fail-abort wait; `JOB_UPDATED_NODES` propagates node
decommission events to running attempts.

*Task attempt level.* `TaskAttemptImpl` starts `UNASSIGNED`; `TA_SCHEDULE` requests a
container; `TA_ASSIGNED` (a `TaskAttemptContainerAssignedEvent`) → `ASSIGNED`;
`ContainerLauncherImpl` sends the container-launch RPC to the NodeManager and fires
`TA_CONTAINER_LAUNCHED` → `RUNNING`. The task process talks back over
`TaskUmbilicalProtocol` (implemented by `MRAppMaster.TaskAttemptListenerImpl`): progress
pings, diagnostics (`TA_DIAGNOSTICS_UPDATE`), status updates, and commit protocol —
`TA_COMMIT_PENDING` when the task wants to commit, resolved to `TA_DONE` or failure.
`TA_CONTAINER_COMPLETED`/`TA_CONTAINER_CLEANED` handle container exits; `TA_TIMED_OUT` fires
on progress liveness timeouts; `TA_TOO_MANY_FETCH_FAILURE` is the reduce-side signal to fail
the map attempt whose outputs are unreachable. Successful attempts funnel through a
`FINISHING` state (`SUCCEEDED_FINISHING_TRANSITION`) so the commit decision is atomic; the
`TaskAttemptFinishingMonitor` times out attempts stuck finishing.

*Container allocation loop.* `RMContainerAllocator` (extends `RMContainerRequestor`, which
owns the `ApplicationMasterProtocol` heartbeat) runs on a scheduled callable: it converts
pending `ContainerRequestEvent`s into `ResourceRequest`s with distinct priorities —
`PRIORITY_FAST_FAIL_MAP` (5) for re-scheduled maps, `PRIORITY_OPPORTUNISTIC_MAP` (19),
`PRIORITY_MAP` (20), `PRIORITY_REDUCE` (10) — then issues `allocate()` and turns returned
containers into `TaskAttemptContainerAssignedEvent`s. Reduce ramp-up is gated by
`reduceSlowStart` (`mapreduce.job.reduce.slowstart.completedmaps`): reduce requests are only
made once that fraction of maps completes, with headroom/ramp-up limits checked in
`scheduleReduces()`. `LocalContainerAllocator` is the non-YARN (local) counterpart.
`ContainerFailedEvent`s feed back into request accounting and node failure tracking.

*Speculation.* `SpeculatorEvent`s stream task/attempt progress into `DefaultSpeculator`,
which periodically asks `ExponentiallySmoothedTaskRuntimeEstimator` for `estimatedRuntime`/
`thresholdRuntime` per attempt. An attempt becomes a speculation candidate only when
`thresholdRuntime()` says the attempt is running longer than the acceptable threshold *and*
the projected replacement (`estimatedNewAttemptRuntime`) finishes strictly earlier than the
current attempt's projected end; the winner is the attempt with the largest negative
slack (`estimatedEndTime - estimatedReplacementEndTime`), capped by
`mapreduce.job.speculative.maximum.allowed.tasks` and the slow-node exclusion logic. If
elected, the speculator adds a new attempt of the same task (`SpeculatorEvent` →
`TaskEvent` `T_ADD_SPEC_ATTEMPT`); the first attempt to succeed wins, siblings are killed.

## 6. Shuffle (client-shuffle + reduce-side fetcher in client-core)

**Purpose.** Move each map task's partitioned output to the reducer that owns the partition.
Two independent halves: a server on the NodeManager and a client inside the reduce task.

**Key classes (server).** `org.apache.hadoop.mapred.ShuffleHandler` (module
`hadoop-mapreduce-client-shuffle`), a Netty `AuxiliaryService` registered under the service
name `mapreduce_shuffle` (`ShuffleHandler.MAPREDUCE_SHUFFLE_SERVICEID`), default port
`DEFAULT_SHUFFLE_PORT = 13562`; supporting `ShuffleChannelInitializer`,
`ShuffleChannelHandler`/`ShuffleChannelHandlerContext`, `FadvisedFileRegion`,
`FadvisedChunkedFile` (zero-copy file sends with advisory read-ahead), and a LevelDB recovery
store named `mapreduce_shuffle_state` so shuffle registrations survive NM restarts.

**Key classes (client).** `org.apache.hadoop.mapreduce.task.reduce`: `Shuffle` (the
`ShuffleConsumerPlugin` entry), `ShuffleSchedulerImpl` + `EventFetcher` (hosts and completion
events), `Fetcher` (per-host HTTP copy), `MapHost`, `InMemoryMapOutput`/`OnDiskMapOutput`,
`MergeManagerImpl` + `MergeThread`, `LocalFetcher` (for local jobs), `ShuffleHeader`.

**Behaviour.** At AM start, `MRAppMaster` requests the NM aux services it needs; the NM
started `ShuffleHandler` at boot as an auxiliary service, so the shuffle port is served
whether or not any MR job runs on that node. The AM obtains a `JobToken` per job, registered
with the `ShuffleHandler` (the AM passes it in container launch service data; the handler
validates reduce-side fetchers against it). When a map task finishes, its output file
(partitioned IFile) stays on the map node's local disk; `TaskCompletionEvent`s flow through
the umbilical/AM to reduce tasks.

Reduce side, `Shuffle.run()` loops: `ShuffleSchedulerImpl` maintains per-host `MapHost`
queues of pending map outputs; `EventFetcher` polls `TaskCompletionEvent`s and queues hosts;
each `Fetcher` thread picks a host, issues HTTP GETs to `http://host:13562/mapOutput?job=...&map=...&reduce=...`,
and receives an IFile stream validated by `ShuffleHeader`. Output lands in memory
(`InMemoryMapOutput`) until `MergeManagerImpl`'s in-memory threshold forces an on-disk
merge (`OnDiskMapOutput`); a final merge across all segments produces the
`RawKeyValueIterator` handed back to `ReduceTask`. If a map output repeatedly fails to
fetch, the reduce reports fetch failures to the AM (`JOB_TASK_ATTEMPT_FETCH_FAILURE` →
`TA_TOO_MANY_FETCH_FAILURE` after `mapreduce.shuffle.max.fetch-failures`-gated accounting),
which kills and reschedules the offending map attempt. Note `ShuffleHandler` here is the
*server* only — the reduce-side fetcher code lives in client-core's `task.reduce` package.

## 7. JobHistoryServer (client-hs)

**Purpose.** A centralized, post-mortem view of every job: the durable store of job history
files and the web UI/RPC that serve them (also the `MRClientProtocol` endpoint after the AM
is gone, per §4).

**Key classes.** `JobHistoryServer` (service composition), `HistoryFileManager`,
`JobListCache` (inner class), `HistoryFileInfo`, `CompletedJob`/`CompletedTask`/
`CompletedTaskAttempt` (lazy read-only job model), `HistoryClientService`,
`HsWebApp`/`HsView` and the page classes (`HsJobPage`, `HsJobsBlock`, `HsTasksPage`, ...),
`HsWebServices` (REST), `HSAdmin`/`HSAdminServer` (refresh protocol), state stores
(`HistoryServerFileSystemStateStoreService`, `HistoryServerLeveldbStateStoreService`),
and the pluggable `HistoryStorage`/`CachedHistoryStorage`. The file format itself lives in
client-core `org.apache.hadoop.mapreduce.jobhistory`: `EventWriter`, `EventReader`,
`HistoryEvent` subclasses (`JobSubmittedEvent`, `JobInitedEvent`, `TaskStartedEvent`,
`MapAttemptFinishedEvent`, `TaskAttemptUnsuccessfulCompletionEvent`, `JobFinishedEvent`, ...),
and `JobHistoryParser` to read them back.

**Behaviour.** On the AM side, `JobHistoryEventHandler` receives every history event from the
dispatcher and writes them (Avro-serialized, JSON codec via `EventWriter`) into
`<staging>/job_history/...` inside the job's staging dir. At job completion the handler
finalizes the file and moves it to the JHS *intermediate-done* directory; a mover service in
`HistoryFileManager` later moves it to the canonical *done* directory on HDFS
(`mapreduce.jobhistory.done-dir`), naming files by serial/timestamp parts
(`FileNameIndexUtils` on the client-common side parses names). `HistoryFileManager` scans
both locations, maintains `JobListCache` (a `ConcurrentSkipListMap<JobId, HistoryFileInfo>`)
of file metadata, and deletes/ages out old files. `CompletedJob` lazily parses the history
file with `JobHistoryParser` and reconstructs ACLs, tasks, attempts, and counters on demand.
`HistoryClientService` exposes `MRClientProtocol` (so clients get counters/diagnostics after
AM termination) plus the web UI; `HsWebApp` routes pages through `HsView`, backed by
`HsJobBlock`, `HsTasksBlock` etc. For HA of the JHS itself, the state-store services persist
delegation tokens and JHS application state (LevelDB or filesystem).

## 8. Native task execution (client-nativetask, brief)

**Purpose.** Optional C++ execution of map tasks (and, where supported, the sort/serialize
hot path) for lower CPU and GC overhead.

**Key classes (Java side, `org.apache.hadoop.mapred.nativetask`).** `NativeRuntime`
(loads the native library, registers platforms), `Platforms`/`HadoopPlatform`
(compatibility detection per job), `NativeMapOutputCollectorDelegator` (swaps the Java
`MapOutputCollector` for the native one when the job is compatible),
`NativeBatchProcessor`, `CombinerHandler` (calls back into the Java combiner),
`NativeTaskOutputFiles`, serializers (`TextSerializer`, `VLongWritableSerializer`, ...),
and the byte-stream plumbing (`BufferPusher`/`BufferPuller`, `InputBuffer`/`OutputBuffer`).
The C++ side lives under `src/main/native/src` (`NativeTask.h`, codec implementations such as
`SnappyCodec`, sorters, `IFile` read/write).

**Behaviour.** `Platforms` inspects the job's key/value/comparator/codec classes; only
natively-supported combinations use the native collector. Data crosses the JNI boundary as
batches of serialized K/V buffers; the native side partitions, sorts (with pluggable
comparators), and spills in the same IFile format, so the shuffle protocol is unchanged.
Incompatible jobs fall back silently to the Java `MapOutputBuffer` path of §3.

## 9. Small modules: client-common, client-hs-plugins, client-uploader

- **client-common.** PB-impl wrappers for everything clients, AM and JHS exchange over
  `MRClientProtocol` (`GetJobReportRequest`/`Response`, `FailTaskAttemptRequest`, `Counters`/
  `CounterGroup` PB impls, `AMInfo`, `JobHistoryUtils`, `ClientHSSecurityInfo`/
  `ClientHSTokenSelector` for JHS tokens). Nothing runs on its own; it is the shared wire layer.
- **client-hs-plugins.** A single class, `MapReduceTrackingUriPlugin`: implements the YARN
  `TrackingUriPlugin` so the RM UI can render the JHS URL for finished applications.
- **client-uploader.** `FrameworkUploader`: packages the MR framework jars into an archive
  for the YARN shared cache, so containers reuse one uploaded copy instead of localizing
  per-job jars.

## 10. hadoop-mapreduce-examples (brief)

User-visible example jobs under `org.apache.hadoop.examples`: `WordCount` (the canonical
mapper/reducer/combiner example), `Sort`, `SecondarySort`, `Join`, `Grep`, `MultiFileWordCount`,
`RandomWriter`/`RandomTextWriter`, `QuasiMonteCarlo`/`BaileyBorweinPlouffe` (pi estimation),
`WordMean`/`WordMedian`/`WordStandardDeviation`, `DBCountPageView`, plus packages `pi`,
`terasort` (TeraSort/TeraGen/TeraValidate, the standard benchmark family), `dancing`
(sudoku via Knuth's dancing links), and `ExampleDriver`, which builds the programmatic
`main` dispatch table used by the `hadoop jar hadoop-mapreduce-examples.jar <program>` CLI.

## 11. End-to-end runtime flow

Putting the pieces together for a submitted job:

1. **Client.** `Job.waitForCompletion()` → `JobSubmitter.submitJobInternal()`: staging dir
   created, jars/splits/`job.xml` uploaded, tokens assembled; `YARNRunner` submits the
   application to the RM with `MRAppMaster` as launch command (§4).
2. **AM start.** RM allocates the AM container; `MRAppMaster.main()` starts services, loads
   the job from staging, `JobImpl` transitions `NEW → INITED → RUNNING` after setup
   (§5).
3. **Map phase.** `RMContainerAllocator` heartbeats the RM for map containers (priority 20)
   respecting locality and headroom; `ContainerLauncherImpl` launches each container, whose
   main class runs `MapTask.run()` (§3). Each map writes partitioned spill files, merged into
   one output per map node.
4. **Shuffle.** As maps complete, completion events reach running reduce attempts;
   `Shuffle.run()` fetches partitions over HTTP from each node's `ShuffleHandler` on port
   13562, merging in memory and on disk (§6). Reduce containers are only requested once
   `reduceSlowStart` maps are done.
5. **Reduce.** `ReduceTask.runNewReducer()` iterates the merged, grouped iterator and calls
   the user reducer; output goes to the task's temp directory on the destination FS.
6. **Commit.** Each task signals `TA_COMMIT_PENDING`; `CommitterEventHandler` on the AM
   serializes commit (`OutputCommitter.commitTask`, typically a rename in
   `FileOutputCommitter`), then `commitJob()` at the end; the job completes and the staging
   dir is cleaned (§5).
7. **History.** Throughout, `JobHistoryEventHandler` writes history events to the staging
   history file and moves it to the done dir at completion; the JHS parses it and serves the
   web UI (§7).

## 12. Failure handling

- **Task retries.** `TaskImpl` tracks attempts per task (`mapreduce.map.maxattempts` /
  `mapreduce.reduce.maxattempts`, default 4 via `MRJobConfig`). A failed attempt event
  (container exit, `TA_TIMED_OUT`, `TA_FAILMSG`) marks it FAILED; `TaskImpl` schedules a new
  attempt until the cap is hit, then fails the task, which fails the job unless killed by
  user action. Maps rescheduled after partially running get the fast-fail priority (5) in
  allocation.
- **Fetch failures / bad map nodes.** When a reduce cannot fetch a map output, it reports
  fetch failures; the AM (`JobImpl` handling `JOB_TASK_ATTEMPT_FETCH_FAILURE`) kills and
  reschedules the map attempt when failures exceed the threshold
  (`TA_TOO_MANY_FETCH_FAILURE`).
- **Node blacklisting.** The AM keeps per-node task-failure accounting in
  `RMContainerRequestor`: with `mapreduce.am.job.node.blacklisting.enable` (default true) it
  sends `ResourceBlacklistRequest` additions/removals on each heartbeat so the RM stops
  allocating on a repeatedly failing node, with `blacklistDisablePercent` unwinding the
  blacklist when too much of the cluster is blacklisted. (The old JobTracker-era
  `blacklistedNodes` tracker state is gone; what remains is this AM-driven request-level
  blacklisting, and `AMWebServices.BlacklistedNodesInfo` still surfaces it in the AM UI.)
- **Speculation.** Not an error path, but the classic slow-attempt mitigation — duplicate
  attempt launched when the runtime estimator projects a win; see §5.
- **AM failure.** MR AM restart recovery is disabled on trunk (`MRJobConfig.MR_AM_JOB_RECOVERY_ENABLE`
  defaults false): a dead AM means a new AM starts the job over. Application-level retry is
  the RM's `ApplicationMasterService` rescheduling the AM container.
- **Job-level cleanup.** `JOB_FAIL_WAIT_TIMEDOUT` bounds fail-abort waits; `JOB_AM_REBOOT`
  triggers a full reboot path; `CommitterEventHandler` issues `abortTask`/`abortJob` on the
  `OutputCommitter` so partial output never becomes visible.

## 13. Behaviour summary per subcomponent

- **Programming model (client-core, `mapreduce`).** Pure API + `Job` orchestration: splits,
  record readers/writers, partitioning, counters; no runtime behaviour of its own.
- **Classic task runtime (client-core, `mapred`).** Runs inside containers: `MapTask`
  collects into `MapOutputBuffer`, spills on soft limit, sorts, merges; `ReduceTask` copies,
  merges, groups, and invokes the reducer; all RPC to the AM via `TaskUmbilicalProtocol`.
- **Submission (client-jobclient + core).** Staging dir, jar/split/conf upload, tokens,
  then `YARNRunner` → RM `ApplicationSubmissionContext` with `MRAppMaster` as the AM.
- **ApplicationMaster (client-app).** Event-driven state machines (`JobImpl`, `TaskImpl`,
  `TaskAttemptImpl`) fed by an async dispatcher; `RMContainerAllocator` heartbeats the RM
  with priority-ordered requests and slow-start reduce ramping; `ContainerLauncherImpl`
  starts tasks; `CommitterEventHandler` serializes commits; `DefaultSpeculator` launches
  duplicate slow attempts.
- **Shuffle (client-shuffle + core fetcher).** `ShuffleHandler` Netty aux service on port
  13562 serves IFile partitions with job-token auth and LevelDB recovery; reduce-side
  `Shuffle`/`Fetcher`/`MergeManagerImpl` pipeline copies to in-memory/disk and merges into
  the reduce input.
- **JobHistoryServer (client-hs).** AM writes Avro/JSON history events; JHS moves files to
  the done dir, parses them lazily (`CompletedJob`, `JobHistoryParser`), serves
  `MRClientProtocol` and the web UI, with LevelDB/FS state stores for HA.
- **nativetask.** Transparent C++ map-output path for compatible jobs; same IFile/shuffle
  format, silent Java fallback.
- **Support modules.** client-common = shared wire records; hs-plugins = RM→JHS tracking
  URI link; uploader = framework jar packaging for the shared cache; examples = benchmark
  and demo jobs (`WordCount`, `terasort`, `pi`, ...).

---

## 14. Concurrency (per subcomponent)

This section states which threads exist and which state they are allowed to touch. The
invariant to keep in mind for any PR: **all AM-side state machines are single-threaded by
construction; every subsystem that does blocking work owns its own thread(s) and must not
block the dispatcher.**

### 14.1 MRAppMaster event dispatcher

- `MRAppMaster.createBaseDispatcher()` returns a single
  `org.apache.hadoop.yarn.event.AsyncDispatcher` (hadoop-yarn-common), which drains one
  `BlockingQueue` on **one** `eventHandlingThread` (default thread name
  `"AsyncDispatcher event handler"`). Event handlers registered in `serviceInit`: the
  `JobEventDispatcher` (`JobEventType`), `TaskEventDispatcher` (`TaskEventType`),
  `TaskAttemptEventDispatcher` (`TaskAttemptEventType`), `CommitterEventHandler`
  (`CommitterEventType`), `ContainerAllocator` (`ContainerAllocator.EventType`),
  `ContainerLauncher` (`ContainerLauncher.EventType`), the speculator
  (`Speculator.EventType`), and `JobHistoryEventHandler`
  (`org.apache.hadoop.mapreduce.jobhistory.EventType`).
- Consequently: transitions of **all** jobs/tasks/attempts of the AM are serialized through
  this single thread. A handler that blocks (RPC, FS I/O) stalls every state machine —
  long work must be handed to a dedicated pool (this is exactly what the committer and the
  allocator do, below).

### 14.2 Job/Task/TaskAttemptImpl state-machine confinement

- `JobImpl`, `TaskImpl` and `TaskAttemptImpl` mutate their `State` only inside transition
  callbacks invoked by the dispatcher thread; other components (allocator, launcher,
  task-runtime RPC, speculator, JHS) never call transitions directly — they post events.
- Threads that read AM state concurrently (the speculator thread, `WebServer` handler
  threads, `TaskAttemptListenerImpl` RPC handler threads) read through the
  `AppContext` maps (`getAllJobs()`, task/attempt lookup), which the state machines update
  atomically from the dispatcher thread.

### 14.3 RMContainerAllocator heartbeat thread

- `RMContainerAllocator` runs its scheduling loop on a dedicated `eventHandlingThread`
  (`RMContainerAllocator.java:249`): a loop while `!stopped` that drains pending
  `ContainerRequestEvent`s, converts them into priority-ordered `ResourceRequest`s and
  calls `heartbeat()` (line 284) → `allocate()` on the `ApplicationMasterProtocol`.
- `RMContainerRequestor` owns the heartbeat bookkeeping and must serialize it: responses
  (containers, blacklist updates) are accounted under its own synchronization before being
  converted into `TaskAttemptContainerAssignedEvent`s posted to the dispatcher.
- Requirement: the allocator thread must never dispatch directly into the state machines —
  it must only post events; heartbeats must be retried on `ApplicationMasterNotRegistered`
  style errors without losing outstanding request accounting.

### 14.4 Task JVM handshake and reuse

- Inside the container, `YarnChild` (`org.apache.hadoop.mapred`, client-app) runs **exactly
  one task** and exits; the container is then released.
- The JVM↔AM handshake is `TaskAttemptListenerImpl.getTask(JvmContext)` (client-app,
  `org.apache.hadoop.mapred`): the listener keeps a
  `ConcurrentMap<WrappedJvmID, Task> jvmIDToActiveAttemptMap` and a
  `Set<WrappedJvmID> launchedJVMs`; a JVM that asks for a task before its attempt is
  registered receives a **null** `JvmTask`, and `launchedJVMs` prevents handing the same
  task to two JVMs.
- `mapreduce.job.jvm.numtasks` (`MRJobConfig.JVM_NUMTASKS_TORUN`) is still read by
  `JobConf.getNumTasksToExecutePerJvm()`, but on trunk there is no MRv1-style `JvmManager`
  reuse loop in the MRv2 runtime: one task per container is the de-facto contract.
  Requirement: PRs must not assume JVM reuse across attempts.

### 14.5 MapTask threads

- `MapTask.MapOutputBuffer` runs **one** `SpillThread` (an inner `extends Thread`,
  `MapTask.java:1552`) coordinated with the collect thread by a
  `ReentrantLock spillLock` with conditions `spillReady`/`spillDone` (lines 940-942).
  The collector thread blocks (spillLock held) once collected metadata crosses the soft
  limit `kvbuffer.length * spillper` (`mapreduce.map.sort.spill.percent`); the spill thread
  sorts, optionally combines, and writes one IFile spill per pass.
- `mergeParts()` (final on-disk multi-way merge) runs on the task's main thread, not on a
  background merge thread. Requirement: user code running concurrently with the collector
  (e.g. a custom collector) must never touch `kvbuffer`/`kvindices` without spillLock.

### 14.6 ReduceTask threads

- `Shuffle.run()` (client-core, `org.apache.hadoop.mapreduce.task.reduce`) starts:
  1. one `EventFetcher` thread polling `TaskCompletionEvent`s;
  2. `numFetchers = jobConf.getInt(MRJobConfig.SHUFFLE_PARALLEL_COPIES, 5)`
     (`mapreduce.reduce.shuffle.parallelcopies`) `Fetcher` threads — exactly **1**
     `LocalFetcher` for local jobs;
  3. `MergeManagerImpl` background merge threads (`InMemoryMerger`/`OnDiskMerger` extending
     `MergeThread`) that spill in-memory segments to disk and merge on-disk segments.
- The final merge producing the `RawKeyValueIterator` blocks `ReduceTask.run()` until all
  fetcher/merge threads finish (`close()` joins them). Requirement: a
  `ShuffleConsumerPlugin` must return only after all its worker threads have terminated.

### 14.7 ShuffleHandler aux service threading

- `ShuffleHandler` is a Netty `AuxiliaryService`: **1** boss `NioEventLoopGroup` thread and
  `maxShuffleThreads` worker threads, where `maxShuffleThreads` is
  `mapreduce.shuffle.max.threads` (`MAX_SHUFFLE_THREADS`), default 0 →
  `2 * Runtime.availableProcessors()`; server channel `NioServerSocketChannel`; open
  channels tracked in a `ChannelGroup` for orderly shutdown.
- Job/attempt state survives NM restart via the LevelDB recovery store
  `mapreduce_shuffle_state`. Requirement: `ShuffleHandler` must never touch per-job state
  outside its own NIO threads once registered, and must keep serving concurrently for all
  jobs on the node (one shared boss/worker group, no per-job threads).

### 14.8 JobHistoryServer job-file scanner

- `HistoryFileManager` (client-hs) does **on-demand** scanning: `JobListCache` (a
  `ConcurrentSkipListMap<JobId, HistoryFileInfo>`) is filled when a job is looked up;
  `HistoryFileInfo.scanIfNeeded()` throttles re-scans of the user's intermediate-done
  directory by directory mtime.
- Moves of finalized history files are done by a `moveToDoneExecutor`
  (`HadoopThreadPoolExecutor`, thread name `MoveIntermediateToDone Thread #%d`, pool size
  from `mapreduce.jobhistory.move-intermediate-done.threadcount`).
- `JHSDelegationTokenSecretManager` runs its own rolling threads
  (`startThreads()` in `JobHistoryServer.serviceInit`); the cleaner keys
  `mapreduce.jobhistory.cleaner.enable` / `mapreduce.jobhistory.cleaner.interval.ms`
  (`JHAdminConfig.MR_HISTORY_CLEANER_ENABLE` / `MR_HISTORY_CLEANER_INTERVAL_MS`) govern
  aging-out of old history files. Requirement: scans must never block the
  `MRClientProtocol` handler threads of `HistoryClientService`.

### 14.9 Speculation thread and heuristics

- `DefaultSpeculator` runs a single `speculationBackgroundThread`
  (`DefaultSpeculator.java:101,222`) that loops: sleep one speculation period
  (`mapreduce.job.speculator.interval`), drain pending `SpeculatorEvent`s, update the
  runtime estimator (`ExponentiallySmoothedTaskRuntimeEstimator`), then scan running
  attempts for candidates.
- An attempt is a candidate only if `thresholdRuntime()` is exceeded **and** the projected
  replacement (`estimatedNewAttemptRuntime`) ends strictly earlier than the current
  attempt's projected end; the maximum number of concurrently speculative tasks is capped
  by `mapreduce.job.speculative.maximum.allowed.tasks`. The speculator posts
  `T_ADD_SPEC_ATTEMPT` to the dispatcher — it must never mutate `TaskImpl` state directly.

### 14.10 Commit/abort concurrency

- `CommitterEventHandler` runs an `eventHandlingThread` (`CommitterEvent Handler`) that
  feeds a `launcherPool` (`HadoopThreadPoolExecutor(5, 5, ...)`) executing
  `EventProcessor` runnables — so **task-level** commits (`commitTask`/`abortTask`) can run
  concurrently, up to 5.
- **Job-level** commit is strictly single-threaded: `jobCommitStarted()`
  (`CommitterEventHandler.java:187`) refuses a second concurrent job commit
  (throws if `jobCommitThread != null`) and `cancelJobCommit()` can interrupt a running
  `commitJob()` (bound by `mapreduce.job.committer.cancel-timers-on-jvm-exit`-style timeout
  config, `commitThreadCancelTimeoutMs`).
- Trunk **does not** guarantee arbitrary `OutputCommitter` concurrency: the framework
  serializes commits only as above; `OutputCommitter.isCommitJobRepeatable(JobContext)`
  (`OutputCommitter.java:~215`) defaults to `false`, meaning a retried AM commit is only
  allowed to run concurrently with a previous AM's in-progress commit if the committer
  explicitly overrides it (the javadoc states the retry "should be able to run
  concurrently with the previous operation" in that case).
- `TaskAttemptImpl` funnels every successful attempt through a `FINISHING` state so the
  "first attempt to commit wins" decision is atomic within the dispatcher thread; sibling
  speculative attempts are killed afterwards.

---

## 15. Security

Enforcing classes named here are all in `hadoop-mapreduce-client-*` unless stated otherwise.

### 15.1 Job token and shuffle secret

- **Job token.** `TokenCache` (`org.apache.hadoop.mapreduce.security`) manages the
  credentials blob: alias `JobToken` (`JOB_TOKEN`), HDFS file name `jobToken`
  (`JOB_TOKEN_HDFS_FILE`), config key `mapreduce.job.jobTokenFile`
  (`JOB_TOKENS_FILENAME`). The token is a `Token<JobTokenIdentifier>`; its secret manager
  is `JobTokenSecretManager` (`org.apache.hadoop.mapreduce.security.token`), which extends
  YARN's `SecretManager<JobTokenIdentifier>`.
- **Shuffle secret key.** `JobSubmitter.submitJobInternal()` generates a fresh shuffle
  secret when absent (lines 172-188): `KeyGenerator.getInstance("HmacSHA1")`
  (`SHUFFLE_KEYGEN_ALGORITHM`), key length `mapreduce.shuffle-key-length`
  (`MRJobConfig.SHUFFLE_KEY_LENGTH`, default 64) → stored in `Credentials` under the alias
  `MapReduceShuffleToken` (`TokenCache.setShuffleSecretKey`). If `JobImpl` finds no shuffle
  secret at AM init (`JobImpl.java:1562`), it falls back to the job token password.
- **Distribution.** The AM passes the serialized job token to the NodeManager as aux
  service data (`ShuffleHandler.serializeServiceData()`, lines 286-291); the NM-side
  `ShuffleHandler` owns its own `JobTokenSecretManager` (instantiated line 411) and calls
  `addJobToken(jobId, user, jobToken)` → `secretManager.addTokenForJob` (lines 593-597).
  Reduce fetchers authenticate their HTTP requests against this secret; every map output
  fetch must be validated (InvalidToken → fetch failure accounting, see §6/§12).
- **Encrypted spill.** `mapreduce.job.encrypted-intermediate-data`
  (`MRJobConfig.MR_ENCRYPTED_INTERMEDIATE_DATA`, default false), with
  `...-key-size-bits` and `...-buffer.kb` variants; the per-job spill key is passed via the
  `MapReduceEncryptedSpillKey` alias (`TokenCache.setEncryptedSpillKey`). When enabled,
  `JobSubmitter` **forces `mapreduce.am.max-attempts` to 1** (recovery across AM attempts
  is not supported with encrypted spill).

### 15.2 Task credential passing

- `YARNRunner` writes the full `Credentials` into the AM `ContainerLaunchContext`
  (`ts.writeTokenStorageToStream(dob)` → `securityTokens` ByteBuffer, in
  `createApplicationSubmissionContext`).
- The task container reads them back from the `jobToken` file via
  `TokenCache.loadTokens` (deprecated in favour of
  `Credentials.readTokenStorageFile`); `YarnChild` (line 342) and
  `TaskAttemptImpl` (line 1066) pull the shuffle secret from the task's credentials.
- The sanitized `job.xml` written to staging must have token references stripped first
  (`JobSubmitter.writeConf`); secrets travel only in the `Credentials` blob.

### 15.3 MR client delegation-token renewers

- `MRDelegationTokenRenewer` (client-common, `...v2.security`) extends YARN's
  `TokenRenewer`, matching `MRDelegationTokenIdentifier.KIND_NAME` (the JHS delegation
  token kind); it can renew/cancel JHS tokens over `HSClientProtocol`.
- The client obtains RM delegation tokens through `ResourceMgrDelegate.getDelegationToken`;
  `YARNRunner` supports forwarding renewal-relevant conf to the AM container via
  `mapreduce.job.send-token-conf` (`MRJobConfig.MR_JOB_SEND_TOKEN_CONF`,
  `setTokenRenewerConf`).
- `ApplicationSubmissionContext.cancelTokensWhenComplete` is set from
  `mapreduce.job.complete.cancel.delegation.tokens` (`JOB_CANCEL_DELEGATION_TOKEN`,
  default true) — the RM must cancel delegation tokens when the application finishes.

### 15.4 JHS web/RPC auth

- RPC: `HistoryClientService.serviceStart()` creates the `HSClientProtocol` server **with**
  `jhsDTSecretManager` as the RPC secret manager (delegation-token auth), backed by
  `JHSDelegationTokenSecretManager` (client-hs), started by the
  `HistoryServerSecretManagerService` sub-service. When
  `hadoop.security.authorization` is true, the server installs
  `ClientHSPolicyProvider` service ACLs.
- Client side: `ClientHSSecurityInfo` (`...v2.security.client`) selects
  `ClientHSTokenSelector` so the JHS delegation token in the user's UGI is picked
  automatically for `MRClientProtocol` calls after the AM is gone.
- Web: the JHS UI uses the YARN/Hadoop web-app stack; SPNEGO integration keys exist in
  `JHAdminConfig` (`MR_WEBAPP_SPNEGO_USER_NAME_KEY`, i.e.
  `mapreduce.jobhistory.webapp.spnego-user-name-key`); HTTP auth filters follow the
  standard `hadoop.http.authentication.*` configuration.

### 15.5 doAs / proxy behaviour in job submission and client RPC

- `ClientServiceDelegate.instantiateAMProxy` (lines 190-210) wraps the AM proxy in a
  **remote-user UGI of the current user** (`UserGroupInformation.createRemoteUser(...)`,
  adding the client-to-AM token when security is enabled) and calls `newUgi.doAs(...)`.
  This is gated by `mapreduce.job.am-access-disabled` (`JOB_AM_ACCESS_DISABLED`, default
  false): when true, the client never contacts the AM and falls back to the JHS.
- Server-side proxy-user enforcement (authenticated user ≠ job owner) is handled by the
  standard Hadoop `doAs`/impersonation rules: JHS administration RPCs
  (`HSAdminServer`) check the admin ACL
  (`mapreduce.jobhistory.admin.acl`) before `refresh*`/`delete` operations and write audit
  records (`HSAuditLogger.logFailure` with `UNAUTHORIZED_USER` on denial).

### 15.6 Input split and staging security

- Staging area permissions are enforced, not just requested:
  `JobSubmissionFiles.JOB_DIR_PERMISSION = 0700` (`JobSubmissionFiles.getStagingDir` fixes
  a wrong permission on an existing staging dir) and job files are written
  `JOB_FILE_PERMISSION = 0644`. Splits (`job.split`, `job.splitmetainfo`) therefore rely on
  the 0700 staging dir for confidentiality.
- Requirement: any new file under the staging dir must never be world/group writable and
  must not carry credentials in `job.xml` (token refs stripped).

### 15.7 Audit logging

- **`MRAuditLogger` does not exist on trunk.** The only MR audit logger is
  `HSAuditLogger` (client-hs, `org.apache.hadoop.mapreduce.v2.hs`), used by
  `HSAdminServer`: tab-separated `key=value` records with keys
  `USER, OPERATION, TARGET, RESULT, IP, PERMISSIONS, DESCRIPTION`
  (`HSAuditLogger.Keys`) and constants `SUCCESS`/`FAILURE`/`UNAUTHORIZED_USER`.
  Requirement: an audit-related PR in the MR domain must target the JHS layer (or YARN's
  `RMAuditLogger`/NM equivalents), not a non-existent MR daemon logger.

---

## 16. Logging and auditability

### 16.1 Task logs (`TaskLog`)

- `org.apache.hadoop.mapred.TaskLog` (client-core) manages per-task log files
  `STDOUT`, `STDERR`, `SYSLOG`, `PROFILE`, `DEBUGOUT` (`TaskLog.LogName`) in the
  container's log directory (YARN-provided `LOG_DIRS` env), plus an index file recording
  per-file start offset + length (written by `writeToIndexFile`, format
  `NAME: start-offset length`).
- `syncLogs()` is a `synchronized` background flush; a helper thread is literally named
  `"Thread for syncLogs"` and `syncLogsShutdown()` flushes on JVM exit. Roll-backups are
  controlled by `MRJobConfig.TASK_LOG_BACKUPS` (default 0 = no rolling).
- **Log aggregation** is a YARN-side feature (the NodeManager aggregates to the FS); MR
  interacts with it at two points: the JHS runs an `AggregatedLogDeletionService`
  (`JobHistoryServer` sub-service, admin-controlled via `HSAdminServer`) to age out
  aggregated logs, and the AM passes log-related env/config (e.g.
  `yarn.app.mapreduce.am.env`, `mapreduce.admin.user.env`) into container launch.

### 16.2 JHS event writing (`JobHistoryEventHandler`)

- Every state-machine transition of interest is mirrored into a
  `HistoryEvent` (`org.apache.hadoop.mapreduce.jobhistory`) and posted to the dispatcher;
  `JobHistoryEventHandler` (client-app) consumes them **on the dispatcher thread** and
  appends them Avro-serialized with a JSON codec through `EventWriter` (client-core) into
  the job's staging history directory.
- At job completion the handler finalizes and moves the file to the JHS
  *intermediate-done* directory; `HistoryFileManager` later moves it to the canonical
  *done* dir (`mapreduce.jobhistory.done-dir`, `JHAdminConfig.MR_HISTORY_DONE_DIR`),
  file names carrying serial/timestamp parts parsed by `FileNameIndexUtils` (client-common).
- Persisted content is complete and self-contained: job submitted/inited/finished, every
  task started/finished, every attempt launched/finished (including
  `TaskAttemptUnsuccessfulCompletionEvent` with diagnostics and failure reason), counters
  at finish, and the job conf. Requirement: an MR PR that adds a state transition with user
  visible effect must emit a corresponding `HistoryEvent` (otherwise the JHS view and all
  post-mortem tooling diverge from reality).

### 16.3 Counters and progress as the observable contract

- The task↔AM observable surface is `TaskUmbilicalProtocol` (client-core):
  `statusUpdate(TaskAttemptID, TaskStatus)` (progress + counters), `ping()`, `done()`,
  `commitPending()`, `fsError()`, `fatalError(..., boolean fastFail)`. Progress *is* the
  liveness signal: the AM's `TaskHeartbeatHandler` raises `TA_TIMED_OUT` when pings stop.
- The client↔AM/JHS surface is `MRClientProtocol`
  (`getJobReport`, `getTaskReports`, `getCounters`, `getDiagnostics`, ...), implemented by
  `MRAppMaster.TaskAttemptListenerImpl`-adjacent services while running and by
  `HistoryClientService` afterwards; `ClientServiceDelegate` picks the endpoint.
- Framework counter groups are fixed: `TaskCounter`, `JobCounter`, `FileSystemCounter`
  (client-core). Requirement: PRs must report progress via `context.progress()` /
  umbilical status updates and surface new measurable quantities as counters in one of
  these groups — not as ad-hoc logs.

### 16.4 MR audit

- As of §15.7, trunk audit coverage for MapReduce is limited to the JHS admin path
  (`HSAuditLogger` + `HSAdminServer`). Job submission/kill/counter access are audited (if
  at all) by the YARN layers (RM/NM audit loggers), not by MR code. A requirement
  statement should therefore say: "MR must not duplicate YARN's audit log; new
  MR-domain privileged operations must log through `HSAuditLogger`."

---

## 17. Integration points

### 17.1 MR ↔ YARN: `ApplicationSubmissionContext` fields set by `YARNRunner`

Verified in `YARNRunner.createApplicationSubmissionContext` (client-jobclient):

| Field | Source |
|---|---|
| `applicationId` | obtained from `ResourceMgrDelegate.getApplicationId()` |
| `queue` | `mapreduce.job.queuename` (`JobContext.QUEUE_NAME`) |
| `reservationID` | `mapreduce.job.reservation-id` (`JobContext.RESERVATION_ID`), parse failure → IOException |
| `applicationName` | `mapreduce.job.name` (`JobContext.JOB_NAME`) |
| `cancelTokensWhenComplete` | `mapreduce.job.complete.cancel.delegation.tokens` |
| `AMContainerSpec` | built by `setupContainerLaunchContextForAM` (local resources = staged job files; tokens ByteBuffer; command `MRAppMaster` + args) |
| `maxAppAttempts` | `mapreduce.am.max-attempts` (`MR_AM_MAX_ATTEMPTS`, default 2) |
| `AMContainerResourceRequests` | from AM resource conf (memory/vcores), with node-label expression from `MRJobConfig.AM_NODE_LABEL_EXP` |
| `nodeLabelExpression` | `mapreduce.job.node-label-expression` (`JobContext.JOB_NODE_LABEL_EXP`) |
| `applicationType` | constant `"MAPREDUCE"` (`MRJobConfig.MR_APPLICATION_TYPE`) |
| `applicationTags` | `mapreduce.job.tags` (`MRJobConfig.JOB_TAGS`) |
| `priority` | `mapreduce.job.priority` (`MRJobConfig.PRIORITY`) |

- AM-RM protocol usage: `RMContainerAllocator`/`RMContainerRequestor` drive
  `ApplicationMasterProtocol.allocate()` with priority-ordered `ResourceRequest`s
  (map 20, opportunistic map 19, fast-fail map 5, reduce 10; AM container requests use
  priority 0 — `AM_CONTAINER_PRIORITY` in `YARNRunner`) plus
  `ResourceBlacklistRequest` for node blacklisting; `finish` (unregistration) is sent once
  via `RMCommunicator.setShouldUnregister` when the job completes (`isLastAMRetry`).

### 17.2 Container environment variables

- Set by **MR** (`MRApps.setClasspath` / `setupContainerLaunchContextForAM`, client-common
  `MRApps`): `CLASSPATH` from `mapreduce.application.classpath`
  (`MRJobConfig.MAPREDUCE_APPLICATION_CLASSPATH`) + `yarn.application.classpath`;
  `APP_CLASSPATH` (used instead of `CLASSPATH` for the job classloader when
  `mapreduce.job.classloader` is true); `HADOOP_CONF_DIR`-style entries via
  `mapreduce.application.framework.path` (`MAPREDUCE_APPLICATION_FRAMEWORK_PATH`).
- From **conf-to-env** keys, expanded by the framework:
  `yarn.app.mapreduce.am.env` (`MRJobConfig.MR_AM_ENV`),
  `mapreduce.admin.user.env` (`MAPRED_ADMIN_USER_ENV`, sets
  `HADOOP_USER_NAME`-style defaults incl. `LD_LIBRARY_PATH` / `JAVA_LIBRARY_PATH`),
  `mapreduce.map.env` (`MAP_ENV`), `mapreduce.reduce.env` (`REDUCE_ENV`),
  `yarn.app.mapreduce.am.admin.user.env` (`MR_AM_ADMIN_USER_ENV`).
- Constants `MRJobConfig.STDOUT_LOGFILE_ENV` / `STDERR_LOGFILE_ENV` carry the AM log file
  locations into the environment.
- Set by **YARN** (not MR, but consumed by MR code): `CONTAINER_ID`, `NM_HOST`,
  `LOCAL_DIRS`, `LOG_DIRS`, `PWD` — `TaskLog` and `YarnChild` read `LOG_DIRS`; spill files
  land under `LOCAL_DIRS`. MR code must read the filesystem through these env vars and
  never hard-code node paths.

### 17.3 Key `mapreduce.*` config keys (integration-relevant subset)

- Shuffle transport: `mapreduce.shuffle.port` (`ShuffleHandler.SHUFFLE_PORT_CONFIG_KEY`,
  default 13562), `mapreduce.shuffle.max.threads`, service id
  `mapreduce_shuffle` (`MAPREDUCE_SHUFFLE_SERVICEID`); reduce side
  `mapreduce.reduce.shuffle.parallelcopies` (default 5),
  `mapreduce.reduce.shuffle.connect.timeout`, `mapreduce.reduce.shuffle.read.timeout`,
  `mapreduce.reduce.shuffle.maxfetchfailures`,
  `mapreduce.reduce.shuffle.max-host-failures` (default 5).
- Submission/placement: `yarn.app.mapreduce.am.staging-dir` (`MR_AM_STAGING_DIR`, default
  `/tmp/hadoop-yarn/staging`), `mapreduce.job.queuename`, node-label keys above,
  `mapreduce.job.tags`.
- AM lifecycle: `mapreduce.am.max-attempts` (default 2),
  `mapreduce.job.maxtaskfailures.per.tracker`, speculation keys (§14.9).
- Security: `mapreduce.shuffle-key-length`, `mapreduce.job.encrypted-intermediate-data*`,
  `mapreduce.job.send-token-conf`, `mapreduce.job.complete.cancel.delegation.tokens`,
  `mapreduce.job.am-access-disabled`, `mapreduce.job.jobTokenFile`.

### 17.4 History service endpoints

All in `JHAdminConfig` (client-common), prefix `mapreduce.jobhistory.`:

| Key | Default |
|---|---|
| `address` (`MR_HISTORY_ADDRESS`) | `0.0.0.0:10020` (`DEFAULT_MR_HISTORY_PORT`) |
| `webapp.address` (`MR_HISTORY_WEBAPP_ADDRESS`) | `0.0.0.0:19888` |
| `webapp.https.address` (`MR_HISTORY_WEBAPP_HTTPS_ADDRESS`) | `0.0.0.0:19890` |
| admin (`JHS_ADMIN_ADDRESS`) | separate admin RPC for refresh/delete |
| `done-dir` / `intermediate-done-dir` (`MR_HISTORY_DONE_DIR` / `MR_HISTORY_INTERMEDIATE_DONE_DIR`) | HDFS history roots |
| `bind-host`, `client.thread-count` (`MR_HISTORY_CLIENT_THREAD_COUNT`) | server sizing |

- Client↔JHS protocol is `HSClientProtocol`/`MRClientProtocol`; the RM links to the JHS
  through `MapReduceTrackingUriPlugin` (client-hs-plugins). `HSProxies` (client-hs)
  implements proxy-user access to history jobs.

### 17.5 `JobConf` staging-dir layout

Contents of `<staging>/<user>/.staging/<jobId>/` after a verified submission path:

| Entry | Producer |
|---|---|
| `job.jar` (+ `_libjars/`, `_files/`, `_archives/` when used) | `JobResourceUploader` |
| `job.xml` (sanitized, token refs stripped) | `JobSubmitter.writeConf` |
| `job.split` | `JobSplitWriter` (map count = split count) |
| `job.splitmetainfo` | `JobSplitWriter` / `JobSplit` metadata |
| `jobToken` (`TokenCache.JOB_TOKEN_HDFS_FILE`) | token storage written before submission |
| history stream subdir (AM-created, §16.2) | `JobHistoryEventHandler` |

- Permissions: directory 0700 (`JOB_DIR_PERMISSION`), files 0644
  (`JOB_FILE_PERMISSION`, enforced/normalized by `JobSubmissionFiles`).
- Requirement: additions to the staging layout must be AM-restart-safe (AM recovery is
  disabled by default — `mapreduce.am.max-attempts` semantics above) and must be cleaned by
  the post-unregistration staging cleaner on success.

---

## 18. Non-functional requirement candidates

Each bullet is a candidate requirement: subcomponent, key class, and the testable
behaviour. Formulate as MUST/SHOULD in a derived spec.

1. **Event-loop isolation (AM).** `MRAppMaster`/`AsyncDispatcher`: every registered
   event handler must complete quickly and never block on RPC, DFS or locks; long-running
   work must move to a dedicated executor (pattern: `CommitterEventHandler.launcherPool`).
2. **Single-threaded state transitions (AM).** `JobImpl`/`TaskImpl`/`TaskAttemptImpl`:
   state changes must happen only via dispatcher events; a PR introducing direct mutation
   from another thread (allocator, listener, web) is a defect.
3. **Heartbeat liveness (AM↔RM).** `RMContainerAllocator`/`RMContainerRequestor`: the AM
   must keep issuing `allocate()` heartbeats at the configured interval even while no
   container requests are pending; heartbeat failure must not lose outstanding request
   accounting.
4. **One task per container (task runtime).** `YarnChild` +
   `TaskAttemptListenerImpl.getTask()`: the AM must hand a task to a JVM only for the
   registered attempt (`jvmIDToActiveAttemptMap`), return null otherwise, and never hand
   the same task to two JVMs (`launchedJVMs`).
5. **Spill correctness under blocking (map).** `MapTask.MapOutputBuffer`/`SpillThread`:
   collection must block (not lose records) when the spill soft limit is hit, and the
   final merged output must contain every collected record exactly once
   (counter-checked via `SPILLED_RECORDS`, `MAP_OUTPUT_RECORDS`).
6. **Bounded shuffle concurrency (reduce).** `Shuffle`/`ShuffleSchedulerImpl`: fetcher
   thread count must equal `mapreduce.reduce.shuffle.parallelcopies` (1 `LocalFetcher`
   locally); all fetcher/merge threads must be joined before `ReduceTask` runs user code.
7. **Shuffle service robustness (shuffle).** `ShuffleHandler`: the aux service must keep
   serving all jobs on the node; registration state must survive NM restart
   (`mapreduce_shuffle_state` LevelDB); a fetch for an unregistered job must be rejected.
8. **Job-commit serialization (AM).** `CommitterEventHandler`: only one
   `commitJob()` may run at any time (`jobCommitStarted()` throws on re-entry);
   task-level commits may run concurrently but must not overlap `commitJob()` unless
   `OutputCommitter.isCommitJobRepeatable()` is true.
9. **Output atomicity (commit).** `OutputCommitter`/`CommitterEventHandler`: no partial
   task output may ever become visible; failed/incomplete tasks must receive
   `abortTask`, failed jobs `abortJob` (path via `CommitterEventType`).
10. **Speculation safety (AM).** `DefaultSpeculator`: a task must never have more
    concurrent speculative attempts than the `mapreduce.job.speculative.maximum.allowed.tasks`
    cap; exactly one sibling's success must win and the others must be killed.
11. **AM restart semantics (AM).** With `mapreduce.am.max-attempts` = 2 default and
    recovery disabled (`MRJobConfig.MR_AM_JOB_RECOVERY_ENABLE` false), a second AM must
    start the job over; encrypted-spill jobs (`mapreduce.job.encrypted-intermediate-data`)
    must additionally be forced to `max-attempts` 1 (`JobSubmitter`).
12. **Token hygiene (security).** `JobSubmitter.writeConf`/`TokenCache`: the sanitized
    `job.xml` must never contain job/shuffle token material; secrets travel only via the
    `Credentials` blob (`jobToken` file) and the AM container launch context.
13. **Shuffle authentication (security).** `ShuffleHandler` + `JobTokenSecretManager`:
    every map-output request must authenticate against the job's registered token;
    invalid tokens must produce a fetch failure on the client, never data.
14. **Staging privacy (security).** `JobSubmissionFiles`: the staging dir must be 0700 and
    submission files ≤ 0644; `getStagingDir` must repair a wrong permission on an
    existing directory.
15. **Delegation-token lifecycle (security/client).** `MRDelegationTokenRenewer`,
    `YARNRunner` (`cancelTokensWhenComplete`), `JHSDelegationTokenSecretManager`: JHS
    delegation tokens must be renewable via `TokenRenewer` and cancelled at application
    completion by default (`mapreduce.job.complete.cancel.delegation.tokens`).
16. **JHS authorization (security/JHS).** `HistoryClientService` + `ClientHSPolicyProvider`
    + `HSAdminServer`: JHS RPC must authenticate with `JHSDelegationTokenSecretManager`;
    admin operations must check `mapreduce.jobhistory.admin.acl` and write
    `HSAuditLogger` records on success *and* failure.
17. **History completeness (logging).** `JobHistoryEventHandler`/`EventWriter`: every
    job/task/attempt lifecycle transition must be persisted (including unsuccessful
    attempts with diagnostics) so the JHS can reconstruct the job exactly
    (`JobHistoryParser` round-trip).
18. **Progress liveness (observability).** `TaskUmbilicalProtocol.statusUpdate`/`ping` +
    `TaskHeartbeatHandler`: an attempt that stops reporting progress must be failed by
    `TA_TIMED_OUT` within the configured timeout; progress and counters must remain the
    only programmatic observability surface (`MRClientProtocol` reports).
19. **Log durability (logging).** `TaskLog` + `AggregatedLogDeletionService`: task
    stdout/stderr/syslog must be flushed (`syncLogsShutdown`) before container exit and
    indexable via the index file; aggregated-log deletion must be admin-gated
    (`HSAdminServer`).
20. **Config as contract (integration).** `YARNRunner.createApplicationSubmissionContext`
    + `MRApps`: every `ApplicationSubmissionContext`/`ContainerLaunchContext` field must
    be traceable to a documented `mapreduce.*`/`yarn.app.mapreduce.*` key (table in
    §17.1/§17.2); a PR adding a new placement/env knob must extend that mapping rather
    than read system properties in the AM.
