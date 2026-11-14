# Apache Hadoop MapReduce — Requirements (hadoop-mapreduce-project)

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

**Status:** DRAFT
**Date:** 2026-11-14
**Source doc:** `notes/architecture/hadoop-mapreduce-architecture.md` (Architecture, ~914 lines)
**ID scheme:** `FR-x` functional · `NFR-C-x` concurrency · `NFR-S-x` security ·
`NFR-L-x` logging/auditability · `NFR-I-x` integration. Numbering runs per document.

## Scope and derivation method

This document derives checkable requirements from the architecture walkthrough of
`hadoop-mapreduce-project/` (client-core, client-common, client-shuffle, client-app,
client-jobclient, client-hs, client-nativetask, plus small modules). Each requirement is a
single rule a reviewer can check against a proposed diff: reading the diff, the reviewer must
be able to say "this satisfies/violates FR-7". Every requirement cites its origin
(architecture-doc section + key class).

Derivation rules:
- Only behaviour stated in the architecture doc or verifiable in the source tree is
  included; nothing is invented.
- The architecture doc's §18 "Non-functional requirement candidates" (items R-NFR-1 …
  R-NFR-20) are **mapped and superseded** by the IDs below; the mapping table is at the
  end of §2.
- MUST = violation is a defect; SHOULD = deviation needs justification in the PR.

---

## 1. Functional requirements

### 1.1 Programming model contract (client-core, `org.apache.hadoop.mapreduce`)

- **FR-1 — Job lifecycle ownership.** `Job` must remain the user-facing lifecycle owner:
  `waitForCompletion()` calls `submit()` exactly once (one-shot, guarded) and then polls
  status through the `Cluster`; `Job` wraps a `JobConf` plus a `Cluster` and nothing heavier. (arch §2, `Job`)
- **FR-2 — InputFormat split contract.** `InputFormat.getSplits()` must cut input into
  `InputSplit`s that carry only location hints, never data; `createRecordReader()` must read
  a split as K,V records; the map task count must equal the split count. (arch §2, §4, `InputFormat`, `JobSplitWriter`)
- **FR-3 — Partitioning contract.** Each map output key must be routed to exactly one
  reducer via the configured `Partitioner`; the default must remain `hash(key) % numPartitions`
  (`HashPartitioner`). (arch §2, `Partitioner`, `HashPartitioner`)
- **FR-4 — Counter groups are fixed.** New framework-measurable quantities must be
  counters in `TaskCounter`, `JobCounter` or `FileSystemCounter` — not ad-hoc log lines or
  new parallel bookkeeping. (arch §2, §16.3, `TaskCounter`, `JobCounter`, `FileSystemCounter`)

### 1.2 Task runtime: sort/spill (client-core, `org.apache.hadoop.mapred`)

- **FR-5 — Sort-spill pipeline.** `MapTask.MapOutputBuffer` must collect serialized records
  into the circular `kvbuffer` with parallel metadata (`kvoffsets`/`kvindices`), and when
  collected metadata crosses the soft limit `kvbuffer.length * spillper`
  (`mapreduce.map.sort.spill.percent`) it must block collection while a dedicated
  `SpillThread` sorts the span (configured comparator), applies the optional combiner per
  partition, and writes one spill file per pass through `IFile`. (arch §3, §14.5, `MapOutputBuffer`, `SpillThread`)
- **FR-6 — Final merge.** On mapper completion, `mergeParts()` must multi-way merge all
  spill files into a single partitioned output file on the task's main thread (combiner
  applied only where merging would not change the result). (arch §3, §14.5, `MapTask.mergeParts`)
- **FR-7 — IFile as the on-disk contract.** Spill and merge output must be written in the
  `IFile` K/V sequence format with per-record checksums, compressed only when configured;
  any alternate execution path (including nativetask, FR-26) must emit the same format.
  (arch §3, §8, `IFile`)
- **FR-8 — Reduce phases before user code.** `ReduceTask.run()` must run copy (shuffle via
  the configured `ShuffleConsumerPlugin`, default `Shuffle`), then sort/merge, then invoke
  the user reducer over a grouping `ValueIterator` whose value groups are decided by the
  grouping comparator. (arch §3, `ReduceTask`, `Shuffle`, `ValueIterator`)

### 1.3 Job submission (client-jobclient + client-core)

- **FR-9 — Staging layout.** Submission must place, under the per-user staging dir resolved
  from `yarn.app.mapreduce.am.staging-dir`: `job.jar` (+ `_libjars`/`_files`/`_archives`),
  sanitized `job.xml`, `job.split`, `job.splitmetainfo`, and `jobToken`, with directory
  permission 0700 and file permissions 0644. (arch §4, §17.5, `JobSubmitter`, `JobSubmissionFiles`)
- **FR-10 — Split persistence.** Splits computed by the `InputFormat` must be written as
  `job.split`/`job.splitmetainfo` by `JobSplitWriter`; map count = split count. (arch §4, `JobSplitWriter`)
- **FR-11 — YARN submission shape.** `YARNRunner` must build the
  `ApplicationSubmissionContext` with the AM launch command set to `MRAppMaster` (job conf
  path, staging dir, user), set resources/ACLs/tokens, and submit via
  `ResourceMgrDelegate.submitApplication()`; all subsequent status/kill/counter calls must go
  through `ClientServiceDelegate`, targeting the AM first and the JobHistoryServer after AM
  termination. (arch §4, `YARNRunner`, `ClientServiceDelegate`)

### 1.4 MRAppMaster: state machines and allocator (client-app)

- **FR-12 — Job state machine.** `JobImpl` must move `NEW → INITED → RUNNING → … →
  COMPLETED`, where `JOB_INIT` reads `job.xml`/splits from staging and builds
  `MapTaskImpl`/`ReduceTaskImpl`, setup runs via the committer, completion is driven by
  task/commit events, and `JOB_KILL`/`JOB_AM_REBOOT`/`JOB_FAIL_WAIT_TIMEDOUT`/
  `JOB_UPDATED_NODES` are handled as specified. (arch §5, `JobImpl`)
- **FR-13 — Attempt lifecycle.** `TaskAttemptImpl` must move `UNASSIGNED → ASSIGNED →
  RUNNING` (via container assignment and `ContainerLauncherImpl`), talk back over
  `TaskUmbilicalProtocol` (progress, diagnostics, status, commit-pending), and handle
  `TA_CONTAINER_COMPLETED`, `TA_TIMED_OUT` and `TA_TOO_MANY_FETCH_FAILURE` by failing and
  rescheduling. (arch §5, `TaskAttemptImpl`, `TaskAttemptListenerImpl`)
- **FR-14 — Allocation priorities.** `RMContainerAllocator` must issue `ResourceRequest`s
  with distinct priorities: fast-fail map 5, opportunistic map 19, map 20, reduce 10; AM
  container requests use priority 0. (arch §5, §17.1, `RMContainerAllocator`)
- **FR-15 — Reduce slow start.** Reduce container requests must be made only once the
  fraction `mapreduce.job.reduce.slowstart.completedmaps` of maps has completed, with
  headroom/ramp-up limits checked in `scheduleReduces()`. (arch §5, `RMContainerAllocator.scheduleReduces`)
- **FR-16 — Speculation election.** An attempt may become a speculation candidate only when
  `thresholdRuntime()` is exceeded AND the projected replacement finishes strictly earlier
  than the current attempt's projected end; the winner must have the largest negative slack,
  subject to the `mapreduce.job.speculative.maximum.allowed.tasks` cap; the first attempt to
  succeed wins and siblings are killed. (arch §5, §14.9, `DefaultSpeculator`, `ExponentiallySmoothedTaskRuntimeEstimator`)
- **FR-17 — Task failure cap.** A task must be retried up to `mapreduce.map.maxattempts` /
  `mapreduce.reduce.maxattempts` (default 4); when the cap is hit the task fails and the job
  fails, unless killed by user action. (arch §12, `TaskImpl`)

### 1.5 Shuffle (client-shuffle + reduce-side fetcher in client-core)

- **FR-18 — ShuffleHandler service shape.** `ShuffleHandler` must remain a Netty
  `AuxiliaryService` registered under the id `mapreduce_shuffle`, serving the default port
  13562 (`mapreduce.shuffle.port`), with job/attempt registration state surviving NM
  restart via the LevelDB store `mapreduce_shuffle_state`. (arch §6, §14.7, `ShuffleHandler`)
- **FR-19 — Fetch protocol.** Reduce fetchers must copy map output via HTTP GET
  `http://host:13562/mapOutput?job=…&map=…&reduce=…`, receiving an IFile stream validated by
  `ShuffleHeader`. (arch §6, `Fetcher`, `ShuffleHeader`)
- **FR-20 — Fetch-failure escalation.** A reduce that repeatedly fails to fetch a map
  output must report fetch failures to the AM; after `mapreduce.reduce.shuffle.maxfetchfailures`
  -gated accounting the AM must kill and reschedule the offending map attempt
  (`TA_TOO_MANY_FETCH_FAILURE`). (arch §6, §12, `JobImpl`, `TA_TOO_MANY_FETCH_FAILURE`)
- **FR-21 — Merge pipeline.** Fetched output must land in memory (`InMemoryMapOutput`) until
  `MergeManagerImpl`'s in-memory threshold forces an on-disk merge (`OnDiskMapOutput`), and a
  final merge across all segments must produce the `RawKeyValueIterator` handed to
  `ReduceTask`. (arch §6, `MergeManagerImpl`)

### 1.6 JobHistoryServer (client-hs)

- **FR-22 — History file flow.** `JobHistoryEventHandler` must write every history event
  (Avro, JSON codec via `EventWriter`) into the job's staging history dir, finalize the file
  at job completion, move it to the JHS intermediate-done directory, from where
  `HistoryFileManager` moves it to the canonical done dir (`mapreduce.jobhistory.done-dir`)
  with serial/timestamp file names parsed by `FileNameIndexUtils`. (arch §7, §16.2, `JobHistoryEventHandler`, `HistoryFileManager`)
- **FR-23 — Post-mortem serving.** `CompletedJob` must lazily parse the history file with
  `JobHistoryParser` (ACLs, tasks, attempts, counters on demand); `HistoryClientService`
  must expose `MRClientProtocol` (counters/diagnostics after AM termination) and the web UI,
  with REST via `HsWebServices`. (arch §7, `CompletedJob`, `HistoryClientService`)
- **FR-24 — History aging.** `HistoryFileManager` must scan both intermediate-done and done
  locations, maintain `JobListCache`, and age out old files governed by
  `mapreduce.jobhistory.cleaner.enable`/`...interval.ms`. (arch §7, §14.8, `HistoryFileManager`, `JobListCache`)

### 1.7 Native task execution (client-nativetask)

- **FR-25 — Native compatibility gate.** `Platforms`/`HadoopPlatform` must inspect the
  job's key/value/comparator/codec classes, and only natively-supported combinations may
  swap the Java `MapOutputCollector` for the native one
  (`NativeMapOutputCollectorDelegator`). (arch §8, `Platforms`, `NativeMapOutputCollectorDelegator`)
- **FR-26 — Native fallback and wire equality.** Incompatible jobs must fall back silently
  to the Java `MapOutputBuffer` path, and the native path must partition, sort and spill in
  the same IFile format so the shuffle protocol is unchanged. (arch §8, §13)

### 1.8 Commit, failure handling and recovery

- **FR-27 — Output atomicity.** No partial task output may ever become visible: successful
  tasks commit via `OutputCommitter.commitTask` (serialized by `CommitterEventHandler`),
  failed/incomplete tasks must receive `abortTask` and failed jobs `abortJob`. (arch §11, §12, §14.10, `CommitterEventHandler`, R-NFR-9)
- **FR-28 — Node blacklisting.** With `mapreduce.am.job.node.blacklisting.enable` (default
  true) the AM must keep per-node task-failure accounting and send `ResourceBlacklistRequest`
  additions/removals on each heartbeat, with `blacklistDisablePercent` unwinding the
  blacklist when too much of the cluster is blacklisted. (arch §12, `RMContainerRequestor`)
- **FR-29 — AM restart semantics.** With recovery disabled on trunk
  (`MRJobConfig.MR_AM_JOB_RECOVERY_ENABLE` false), a second AM must start the job over;
  application-level retry is the RM rescheduling the AM container within
  `mapreduce.am.max-attempts` (default 2). (arch §12, §18.11, `MRAppMaster`)
- **FR-30 — Staging cleanup on success.** On successful jobs a staging-dir cleaner must run
  after AM unregistration with the RM; `MRAppMaster` must abort with a diagnostic if the
  staging dir does not exist at start. (arch §5, `MRAppMaster`)

---

## 2. Non-functional requirements

### 2.1 Concurrency (NFR-C)

- **NFR-C-1 — Event-loop isolation.** All AM event handlers on the single
  `AsyncDispatcher` thread must complete quickly and never block on RPC, DFS I/O or locks;
  long-running work must move to a dedicated executor (pattern:
  `CommitterEventHandler.launcherPool`). A handler that blocks stalls every state machine.
  (arch §14.1, §18.1, `AsyncDispatcher`)
- **NFR-C-2 — State-machine thread confinement.** `JobImpl`, `TaskImpl` and
  `TaskAttemptImpl` must mutate their `State` only inside transition callbacks invoked by
  the dispatcher thread; every other component (allocator, launcher, task RPC, speculator,
  JHS) must post events instead of calling transitions. A PR that mutates state directly
  from another thread is a defect. (arch §14.2, §18.2, `JobImpl`/`TaskImpl`/`TaskAttemptImpl`)
- **NFR-C-3 — Concurrent readers via AppContext.** Threads that read AM state concurrently
  (speculator thread, `WebServer` handlers, `TaskAttemptListenerImpl` RPC handlers) must
  read through the `AppContext` maps (`getAllJobs()`, task/attempt lookup), which the state
  machines update atomically on the dispatcher thread. (arch §14.2, `AppContext`)
- **NFR-C-4 — Allocator heartbeat discipline.** `RMContainerAllocator` must run its
  scheduling loop on its dedicated thread, must never dispatch into the state machines
  (events only), must keep issuing `allocate()` heartbeats at the configured interval even
  with no pending container requests, and must retry on
  `ApplicationMasterNotRegistered`-style errors without losing outstanding request
  accounting; `RMContainerRequestor` must serialize heartbeat bookkeeping under its own
  synchronization. (arch §14.3, §18.3, `RMContainerAllocator`, `RMContainerRequestor`)
- **NFR-C-5 — One task per container.** `YarnChild` must run exactly one task and exit;
  `TaskAttemptListenerImpl.getTask()` must return a null `JvmTask` for a JVM whose attempt
  is not registered (`jvmIDToActiveAttemptMap`), must never hand the same task to two JVMs
  (`launchedJVMs`), and PRs must not assume MRv1-style JVM reuse across attempts
  (`mapreduce.job.jvm.numtasks` is read but unused by the MRv2 runtime). (arch §14.4, §18.4, `YarnChild`, `TaskAttemptListenerImpl`)
- **NFR-C-6 — Spill correctness under blocking.** Collection must block (never lose or
  duplicate records) when the spill soft limit is hit; `kvbuffer`/`kvindices` must be
  touched only under `spillLock` (conditions `spillReady`/`spillDone`); the final merged
  output must contain every collected record exactly once, counter-checked via
  `MAP_OUTPUT_RECORDS`/`SPILLED_RECORDS`; `mergeParts()` runs on the task main thread.
  (arch §14.5, §18.5, `MapOutputBuffer`, `SpillThread`)
- **NFR-C-7 — Bounded shuffle concurrency and full join.** `Shuffle.run()` must start
  exactly one `EventFetcher`, exactly `mapreduce.reduce.shuffle.parallelcopies` (default 5)
  `Fetcher` threads (exactly 1 `LocalFetcher` for local jobs), and `MergeManagerImpl`
  background merge threads; a `ShuffleConsumerPlugin` must return only after all its worker
  threads have terminated (final merge joins them before `ReduceTask` runs user code).
  (arch §14.6, §18.6, `Shuffle`, `ShuffleSchedulerImpl`, `MergeManagerImpl`)
- **NFR-C-8 — ShuffleHandler service robustness.** `ShuffleHandler` must keep serving all
  jobs on the node from one shared boss/worker NIO group (1 boss thread,
  `mapreduce.shuffle.max.threads` workers, default 0 → 2 × availableProcessors), must never
  touch per-job state outside its NIO threads once registered, must survive NM restart via
  the LevelDB store, and must reject a fetch for an unregistered job. (arch §14.7, §18.7, `ShuffleHandler`)
- **NFR-C-9 — JHS scanning must not block serving.** `HistoryFileManager` scans on demand
  (`JobListCache`, `HistoryFileInfo.scanIfNeeded()` throttled by directory mtime) and moves
  files on the `moveToDoneExecutor`; scans must never block the `MRClientProtocol` handler
  threads of `HistoryClientService`. (arch §14.8, `HistoryFileManager`)
- **NFR-C-10 — Speculator thread confinement.** `DefaultSpeculator` must run its candidate
  scan on its single background thread, must post `T_ADD_SPEC_ATTEMPT` to the dispatcher,
  and must never mutate `TaskImpl` state directly. (arch §14.9, `DefaultSpeculator`)
- **NFR-C-11 — Commit serialization.** Only one `commitJob()` may run at any time
  (`jobCommitStarted()` throws on re-entry; `cancelJobCommit()` may interrupt it);
  task-level commits may run concurrently up to the launcher pool of 5; `TaskAttemptImpl`
  must funnel successful attempts through `FINISHING` so the first-attempt-to-commit-wins
  decision is atomic within the dispatcher thread, and speculative siblings are killed
  afterwards. (arch §14.10, §18.8, §18.10, `CommitterEventHandler`, `TaskAttemptImpl`)

### 2.2 Security (NFR-S)

- **NFR-S-1 — Shuffle secret generation.** The shuffle secret must be generated per job
  when absent (`JobSubmitter`: `HmacSHA1` key generator, length
  `mapreduce.shuffle-key-length`, default 64), stored in `Credentials` under the
  `MapReduceShuffleToken` alias; if `JobImpl` finds no shuffle secret at AM init it must
  fall back to the job token password. (arch §15.1, `JobSubmitter`, `TokenCache.setShuffleSecretKey`)
- **NFR-S-2 — Shuffle authentication.** Every map-output fetch request must authenticate
  against the job's token registered with the NM-side `ShuffleHandler`
  (`addJobToken` → `JobTokenSecretManager`); an invalid token must produce a fetch failure
  on the client (feeding FR-20 accounting), never data. (arch §15.1, §18.13, `ShuffleHandler`, `JobTokenSecretManager`)
- **NFR-S-3 — Token hygiene in job.xml.** The sanitized `job.xml` written to staging must
  never contain job/shuffle token material (token references stripped by
  `JobSubmitter.writeConf` before writing); secrets travel only in the `Credentials` blob
  (`jobToken` file) and the AM container launch context. (arch §15.2, §18.12, `JobSubmitter.writeConf`, `TokenCache`)
- **NFR-S-4 — Credential passing path.** `YARNRunner` must write the full `Credentials`
  into the AM `ContainerLaunchContext`; task containers must read them back from the
  `jobToken` file (`Credentials.readTokenStorageFile`), and `YarnChild`/`TaskAttemptImpl`
  must pull the shuffle secret from the task's credentials. (arch §15.2, `YARNRunner`, `YarnChild`)
- **NFR-S-5 — Delegation-token lifecycle.** JHS delegation tokens must be renewable/cancellable
  via `MRDelegationTokenRenewer` (`TokenRenewer` matching
  `MRDelegationTokenIdentifier.KIND_NAME`), renewal conf may be forwarded to the AM via
  `mapreduce.job.send-token-conf`, and the RM must cancel delegation tokens at application
  completion by default (`mapreduce.job.complete.cancel.delegation.tokens`, default true).
  (arch §15.3, §18.15, `MRDelegationTokenRenewer`, `YARNRunner`)
- **NFR-S-6 — JHS RPC/web auth.** `HistoryClientService` must start `HSClientProtocol` with
  `JHSDelegationTokenSecretManager` as the RPC secret manager, install
  `ClientHSPolicyProvider` service ACLs when `hadoop.security.authorization` is true, and
  the client must select the JHS token automatically via `ClientHSSecurityInfo`/
  `ClientHSTokenSelector`; web auth follows the standard `hadoop.http.authentication.*`
  and SPNEGO keys in `JHAdminConfig`. (arch §15.4, §18.16, `HistoryClientService`, `ClientHSPolicyProvider`)
- **NFR-S-7 — doAs / proxy-user behaviour.** `ClientServiceDelegate.instantiateAMProxy`
  must wrap the AM proxy in a remote-user UGI of the current user (with the client-to-AM
  token when security is enabled), gated by `mapreduce.job.am-access-disabled` (default
  false, true ⇒ fall back to the JHS); `HSAdminServer` must check the
  `mapreduce.jobhistory.admin.acl` before `refresh*`/`delete` operations. (arch §15.5, `ClientServiceDelegate`, `HSAdminServer`)
- **NFR-S-8 — Staging privacy.** The staging dir must be 0700 and submission files ≤ 0644
  (`JobSubmissionFiles.JOB_DIR_PERMISSION`/`JOB_FILE_PERMISSION`), `getStagingDir` must
  repair a wrong permission on an existing staging dir, and splits rely on the 0700 dir for
  confidentiality. (arch §15.6, §18.14, `JobSubmissionFiles`)
- **NFR-S-9 — Encrypted-spill constraints.** When `mapreduce.job.encrypted-intermediate-data`
  is enabled, `JobSubmitter` must force `mapreduce.am.max-attempts` to 1 (recovery is not
  supported with encrypted spill) and the per-job spill key must be passed via the
  `MapReduceEncryptedSpillKey` alias, never via job.xml. (arch §15.1, §18.11, `JobSubmitter`, `TokenCache.setEncryptedSpillKey`)
- **NFR-S-10 — Audit logger reality.** `MRAuditLogger` does not exist on trunk: the only MR
  audit logger is `HSAuditLogger` (tab-separated `key=value` records: USER, OPERATION,
  TARGET, RESULT, IP, PERMISSIONS, DESCRIPTION). JHS admin operations must write
  `HSAuditLogger` records on success AND failure (`UNAUTHORIZED_USER` on denial); audit
  PRs in the MR domain must target the JHS layer (or YARN's loggers), not a non-existent
  MR daemon logger. (arch §15.7, §16.4, §18.16, `HSAuditLogger`, `HSAdminServer`)

### 2.3 Logging and auditability (NFR-L)

- **NFR-L-1 — Task log durability.** `TaskLog` must manage `STDOUT`/`STDERR`/`SYSLOG`/
  `PROFILE`/`DEBUGOUT` in the YARN-provided `LOG_DIRS` plus an index file (`NAME:
  start-offset length`); logs must be flushed (`syncLogsShutdown`) before container exit;
  roll-backups governed by `MRJobConfig.TASK_LOG_BUPS`-style config (default 0 = no
  rolling). (arch §16.1, §18.19, `TaskLog`)
- **NFR-L-2 — Log-aggregation boundary.** Log aggregation is a YARN (NodeManager) feature;
  MR's only touch points are the JHS-run `AggregatedLogDeletionService` (admin-gated via
  `HSAdminServer`) and container env/config passing. A PR must not re-implement aggregation
  inside MR. (arch §16.1, `AggregatedLogDeletionService`)
- **NFR-L-3 — History completeness.** Every job/task/attempt lifecycle transition with a
  user-visible effect must emit a corresponding `HistoryEvent` — including
  `TaskAttemptUnsuccessfulCompletionEvent` with diagnostics and failure reason, counters at
  finish, and the job conf — so `JobHistoryParser` can reconstruct the job exactly; an MR
  PR that adds a transition without an event breaks the JHS view and all post-mortem
  tooling. (arch §16.2, §18.17, `JobHistoryEventHandler`, `EventWriter`)
- **NFR-L-4 — Progress as the liveness contract.** Attempts must report progress via
  `TaskUmbilicalProtocol.statusUpdate`/`ping` (`context.progress()`); an attempt that stops
  reporting must be failed by `TA_TIMED_OUT` within the configured timeout; new measurable
  quantities must surface as counters (per FR-4) and through `MRClientProtocol` reports —
  not as ad-hoc logs. (arch §16.3, §18.18, `TaskUmbilicalProtocol`, `TaskHeartbeatHandler`)
- **NFR-L-5 — No duplicated audit trail.** MR must not duplicate YARN's audit log (RM/NM
  loggers already audit submission/kill/counter access); new MR-domain privileged
  operations must log through `HSAuditLogger`. (arch §16.4, `HSAuditLogger`)

### 2.4 Integration (NFR-I)

- **NFR-I-1 — Config-as-contract for submission.** Every
  `ApplicationSubmissionContext`/`ContainerLaunchContext` field set by `YARNRunner`/`MRApps`
  must be traceable to a documented `mapreduce.*`/`yarn.app.mapreduce.*` key (queue
  `mapreduce.job.queuename`, name, reservation-id, node-label-expression, tags, priority,
  `mapreduce.am.max-attempts`, application type constant `MAPREDUCE`, classpath keys, env
  keys); a PR adding a new placement/env knob must extend that mapping rather than read
  system properties in the AM. (arch §17.1–17.3, §18.20, `YARNRunner`, `MRApps`)
- **NFR-I-2 — Container environment contract.** MR must set `CLASSPATH`/`APP_CLASSPATH`
  from `mapreduce.application.classpath` (+`yarn.application.classpath`) and expand the
  conf-to-env keys (`yarn.app.mapreduce.am.env`, `mapreduce.admin.user.env`,
  `mapreduce.map.env`, `mapreduce.reduce.env`, admin user env); MR code must read YARN-provided
  `CONTAINER_ID`/`NM_HOST`/`LOCAL_DIRS`/`LOG_DIRS`/`PWD` from the environment and never
  hard-code node paths. (arch §17.2, `MRApps`, `TaskLog`, `YarnChild`)
- **NFR-I-3 — Shuffle transport keys.** The shuffle transport must remain configurable
  through its documented keys only: `mapreduce.shuffle.port` (default 13562),
  `mapreduce.shuffle.max.threads`, service id `mapreduce_shuffle`,
  `mapreduce.reduce.shuffle.parallelcopies` (default 5), connect/read timeouts,
  `mapreduce.reduce.shuffle.maxfetchfailures`, `mapreduce.reduce.shuffle.max-host-failures`
  (default 5). (arch §17.3, `ShuffleHandler`, `MRJobConfig`)
- **NFR-I-4 — JHS endpoint keys.** JHS endpoints and roots must remain keyed in
  `JHAdminConfig` under `mapreduce.jobhistory.`: `address` (default 0.0.0.0:10020),
  `webapp.address` (19888), `webapp.https.address` (19890), separate admin RPC address,
  `done-dir`/`intermediate-done-dir`, `bind-host`, `client.thread-count`. (arch §17.4, `JHAdminConfig`)
- **NFR-I-5 — RM→JHS tracking link.** The RM UI must link to the JHS for finished
  applications via `MapReduceTrackingUriPlugin` (client-hs-plugins); a PR changing
  tracking-URL generation must keep this plugin working. (arch §9, §17.4, `MapReduceTrackingUriPlugin`)
- **NFR-I-6 — Staging layout stability.** Additions to the staging layout
  (`<staging>/<user>/.staging/<jobId>/`) must be AM-restart-safe (AM recovery is disabled
  by default, see FR-29) and must be cleaned by the post-unregistration staging cleaner on
  success; permissions per NFR-S-8. (arch §17.5, `JobSubmissionFiles`)

### 2.5 Mapping of the architecture doc's R-NFR candidates (superseded)

| arch §18 item | This document |
|---|---|
| R-NFR-1 event-loop isolation | NFR-C-1 |
| R-NFR-2 single-threaded state transitions | NFR-C-2 |
| R-NFR-3 heartbeat liveness | NFR-C-4 |
| R-NFR-4 one task per container | NFR-C-5 |
| R-NFR-5 spill correctness under blocking | NFR-C-6 |
| R-NFR-6 bounded shuffle concurrency | NFR-C-7 |
| R-NFR-7 shuffle service robustness | NFR-C-8 |
| R-NFR-8 job-commit serialization | NFR-C-11 |
| R-NFR-9 output atomicity | FR-27 |
| R-NFR-10 speculation safety | FR-16 + NFR-C-10, NFR-C-11 |
| R-NFR-11 AM restart semantics | FR-29 + NFR-S-9 |
| R-NFR-12 token hygiene | NFR-S-3 |
| R-NFR-13 shuffle authentication | NFR-S-2 |
| R-NFR-14 staging privacy | NFR-S-8 |
| R-NFR-15 delegation-token lifecycle | NFR-S-5 |
| R-NFR-16 JHS authorization | NFR-S-6 + NFR-S-10 |
| R-NFR-17 history completeness | NFR-L-3 |
| R-NFR-18 progress liveness | NFR-L-4 |
| R-NFR-19 log durability | NFR-L-1 |
| R-NFR-20 config as contract | NFR-I-1 |

---

## 3. PR-review checklists

### 3.1 Programming model & task runtime
- [ ] New API surface keeps `Job` the lifecycle owner; submission stays one-shot (FR-1).
- [ ] New input/output plumbing honours split-count = map-count and the partitioner contract (FR-2, FR-3).
- [ ] New measurable metrics land as counters in `TaskCounter`/`JobCounter`/`FileSystemCounter` (FR-4, NFR-L-4).
- [ ] Changes to `MapOutputBuffer`/`SpillThread` keep the soft-limit block, single spill thread, and exactly-once merge (FR-5, FR-6, NFR-C-6).
- [ ] New on-disk output stays in IFile format with checksums (FR-7).
- [ ] Reduce-side changes keep copy → merge → grouped-reduce ordering and full thread join (FR-8, NFR-C-7).

### 3.2 Submission
- [ ] Staging files match the documented layout and permissions; job.xml has no token refs (FR-9, NFR-S-3, NFR-S-8).
- [ ] New submission knobs are `mapreduce.*`/`yarn.app.mapreduce.*` keys reflected in the ASC mapping (NFR-I-1).
- [ ] Client failover path (AM → JHS via `ClientServiceDelegate`) is preserved (FR-11).

### 3.3 MRAppMaster
- [ ] No new direct state mutation outside dispatcher transitions; everything is events (NFR-C-2, NFR-C-3).
- [ ] New handlers on the dispatcher never block; long work goes to a dedicated executor (NFR-C-1).
- [ ] Allocator changes keep heartbeat cadence, priority ordering (5/19/20/10) and slow-start gating (FR-14, FR-15, NFR-C-4).
- [ ] Speculation changes keep the threshold + strictly-earlier-end condition and the cap (FR-16, NFR-C-10).
- [ ] Commit path keeps single `commitJob()` and FINISHING-state atomicity (NFR-C-11, FR-27).
- [ ] Any new state transition emits a matching `HistoryEvent` (NFR-L-3).
- [ ] Blacklisting and failure-cap behaviour preserved (FR-17, FR-28, FR-29).

### 3.4 Shuffle
- [ ] Server changes keep the `mapreduce_shuffle` service id, port key, LevelDB recovery and reject unregistered jobs (FR-18, NFR-C-8).
- [ ] Fetch auth is enforced on every request; InvalidToken feeds fetch-failure accounting (NFR-S-2, FR-20).
- [ ] No per-job threads on the shuffle server; shared NIO group (NFR-C-8).
- [ ] Fetcher pool sizes still derive from `parallelcopies`; `LocalFetcher` count stays 1 locally (NFR-C-7).

### 3.5 JobHistoryServer
- [ ] History file naming/move flow (staging → intermediate-done → done) unchanged or extended compatibly (FR-22, NFR-I-4).
- [ ] Scans and file moves stay off the `MRClientProtocol` handler threads (NFR-C-9).
- [ ] New admin operations check the admin ACL and write `HSAuditLogger` records on success and failure (NFR-S-7, NFR-S-10).
- [ ] RPC secret manager / policy provider wiring preserved (NFR-S-6).

### 3.6 Security (cross-cutting)
- [ ] No secret material in job.xml or any new staging file (NFR-S-3).
- [ ] Credentials travel only via the `Credentials` blob / launch context (NFR-S-4).
- [ ] Encrypted-spill jobs still forced to `max-attempts` 1 (NFR-S-9).
- [ ] Delegation tokens still cancelled at completion by default (NFR-S-5).

### 3.7 Nativetask & integration
- [ ] Native path still gated by `Platforms` compatibility and falls back silently to Java (FR-25, FR-26).
- [ ] New env/config plumbing uses the documented keys; no hard-coded node paths; YARN env vars read, not assumed (NFR-I-1, NFR-I-2).
- [ ] Staging-layout additions are AM-restart-safe and cleaned on success (NFR-I-6, FR-30).

---

## 4. References

- Source: `notes/architecture/hadoop-mapreduce-architecture.md` — sections cited per
  requirement as (arch §n[.m]).
- Key source roots: `hadoop-mapreduce-client/hadoop-mapreduce-client-core`
  (`org.apache.hadoop.mapreduce`, `org.apache.hadoop.mapred`,
  `org.apache.hadoop.mapreduce.jobhistory`, `org.apache.hadoop.mapreduce.task.reduce`),
  `...client-app` (`org.apache.hadoop.mapreduce.v2.app.job.impl`,
  `org.apache.hadoop.mapred` AM-side), `...client-shuffle`
  (`org.apache.hadoop.mapred.ShuffleHandler`), `...client-hs`
  (`org.apache.hadoop.mapreduce.v2.hs`), `...client-jobclient`, `...client-common`,
  `...client-nativetask`.
- The §18 R-NFR candidate list of the source doc is superseded by the mapping in §2.5;
  cite the new IDs in reviews.
