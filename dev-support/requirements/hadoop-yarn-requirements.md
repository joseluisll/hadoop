# Apache Hadoop YARN — Requirements for PR Review

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

**Status:** DRAFT
**Date:** 2026-11-14
**Source doc:** `notes/architecture/hadoop-yarn-architecture.md` — architecture notes
verified against the `hadoop-yarn-project/` source tree of this checkout.

---

## Scope and derivation method

This document turns the YARN architecture notes into checkable requirements for
reviewing proposed PR diffs against the architecture. Every numbered item is a
single rule: a reviewer reading a diff must be able to declare
"this satisfies / violates `<ID>`" for the touched code.

**Derivation method.** Each requirement was derived from exactly one of:

1. a behaviour explicitly stated in the architecture doc (its §-number is cited), or
2. a class/contract verified to exist in this checkout's source tree by the
   architecture analysis (the enforcing class is named alongside).

Nothing else was invented: where the architecture doc marks behaviour as
designed-but-not-hard-enforced ("should"), the requirement says *should* and is
reviewed as a design-conformance check, not an invariant. Requirements that
only make sense under a configuration flag state the flag explicitly.

**ID scheme** (numbering runs per document, stable across revisions):

| Prefix | Domain |
|---|---|
| `FR-n` | Functional requirement (observable behaviour of a component) |
| `NFR-C-n` | Non-functional: concurrency / threading model |
| `NFR-S-n` | Non-functional: security (tokens, ACLs, executors, cGroups) |
| `NFR-L-n` | Non-functional: logging, audit, metrics |
| `NFR-I-n` | Non-functional: integration (ports, protocols, configuration) |

Each requirement cites its origin as `(arch §<section>, <key class>)` — the
section of the source architecture doc plus the class that enforces the rule
in this checkout.

**Mapping of the source doc's NFR-candidate list (arch §21) to this document.**
The `R-NFR-n` items are superseded by the requirements below; the mapping is:

| Source item (arch §21) | This document |
|---|---|
| R-NFR-1 … R-NFR-13 (concurrency candidates) | NFR-C-1 … NFR-C-13, in order |
| R-NFR-14 (per-daemon Kerberos identity) | NFR-S-1 |
| R-NFR-15 / -16 / -17 / -18 / -19 / -20 | NFR-S-2 / -3 / -4 / -5 / -6 / -7, in order |
| R-NFR-21 (RM audit) / R-NFR-22 (log aggregation) | NFR-L-1 / NFR-L-3 |
| R-NFR-23 / -24 / -25 (ports, runtimes, registry) | NFR-I-1 / NFR-I-2 / NFR-I-3 |


NFR-S-8, NFR-S-9, NFR-L-2, NFR-L-4, NFR-L-5, NFR-I-4, NFR-I-5 are additional
requirements derived from arch §18, §19 and §20 that the R-NFR list did not
cover explicitly.

---

## 1. Functional requirements

### 1.1 hadoop-yarn-api — protocol and record contracts

- **FR-1 — Client protocol surface.**
  `ApplicationClientProtocol` must expose application submit and kill (`SubmitApplicationRequest` /
  `KillApplicationRequest`), `ApplicationReport` queries, new-application / new-submission-context
  acquisition, delegation tokens, and queue/node reports (arch §3, `ApplicationClientProtocol`).
- **FR-2 — AM allocation contract.**
  `ApplicationMasterProtocol` must support `RegisterApplicationMasterRequest`, the
  `AllocateRequest`/`AllocateResponse` heartbeat-allocate cycle, and
  `FinishApplicationMasterRequest`; this is the allocation contract between AM and RM (arch §3,
  `ApplicationMasterProtocol`).
- **FR-3 — Node-to-RM contract.**
  `ResourceTracker` must support `RegisterNodeManagerRequest` and `NodeHeartbeatRequest` carrying
  `NodeStatus` (container statuses, kept containers, health), with the response returning the
  containers to launch or clean up (arch §3, `ResourceTracker`).
- **FR-4 — Container management contract.**
  `ContainerManagementProtocol` must support `StartContainersRequest`, `StopContainersRequest`,
  `GetContainerStatusesRequest`, and `ContainerUpdateRequest` for in-place resource changes (arch
  §3, `ContainerManagementProtocol`).
- **FR-5 — Hierarchical identifiers.**
  `ApplicationId` (cluster timestamp + sequence), `ApplicationAttemptId`, and `ContainerId` must
  remain the hierarchical join keys across every state machine: `ContainerId` wraps an attempt,
  which wraps an application (arch §3, record classes).
- **FR-6 — Resource model.**
  `Resource` must express memory MB, vcores, and custom resources (e.g. GPUs, FPGAs) through the
  `resource` package (`ResourceInformation`, `ResourceTypes`); new resource types must extend this
  model, not bypass it (arch §3, `Resource`).
- **FR-7 — Container record completeness.**
  A `Container` record must carry its id, `NodeId`, `Resource`, priority, `ContainerToken`, and
  `ExecutionType` (guaranteed/opportunistic) (arch §3, `Container`).
- **FR-8 — Launch context contents.**
  `ContainerLaunchContext` must carry commands, environment, the `LocalResource` map (URLs +
  timestamps + sizes for localization), ACLs, and the token buffer (arch §3,
  `ContainerLaunchContext`).
- **FR-9 — Wire compatibility.**
  Any change to a protocol record or RPC argument must remain compatible at the protobuf level, and
  the API module must stay free of server-side logic (arch §3, protobuf record model).

### 1.2 ResourceManager — applications and recovery

- **FR-10 — Submission handling.**
  `RMAppManager` must validate the `ApplicationSubmissionContext` arriving at
  `ClientRMService.submitApplication`, create an `RMAppImpl`, register it in `RMContext`, and post
  `RMAppEventType.START` (arch §7.2, `RMAppManager`).
- **FR-11 — RMApp state machine.**
  `RMAppImpl` must implement the `RMAppState` transition set — NEW, NEW_SAVING, SUBMITTED, ACCEPTED,
  RUNNING, FINAL_SAVING, FINISHING, FINISHED, FAILED, KILLING, KILLED — as a dispatcher-driven
  transition table (arch §7.3, `RMAppImpl`).
- **FR-12 — Persist before accept.**
  A submitted application must pass through `NEW_SAVING`, writing its submission context to the
  state store, before attempt scheduling begins at `ACCEPTED` (arch §7.3, `RMAppImpl` /
  `RMStateStore`).
- **FR-13 — Attempt state machine.**
  `RMAppAttemptImpl` must implement the `RMAppAttemptState` set including the saving variants, with
  SCHEDULED = AM container request outstanding, ALLOCATED = container granted, LAUNCHED = AM started
  on an NM, RUNNING = AM registered (arch §7.3, `RMAppAttemptImpl`).
- **FR-14 — Attempt retry policy.**
  On attempt failure, `RMAppImpl` must retry with a new `ApplicationAttemptId` until
  `maxAppAttempts` (default 2, subject to the AM failure validity window) and otherwise move the
  application to FAILED (arch §7.3, `RMAppImpl`).
- **FR-15 — Operator surface.**
  `AdminService` must remain the only path for operator actions (refresh queues, refresh nodes, HA
  transition to standby); a PR adding an operator action must route it through `AdminService` (arch
  §7.2, `AdminService`).
- **FR-16 — RM restart recovery.**
  On RM restart, the `RMStateStore` implementations must replay applications/attempts
  (`RMAppRecoverEvent`) and, with work-preserving restart, reacquire containers from NMs
  (`RMContainerRecoverEvent`) (arch §9, `recovery/RMStateStore`).

### 1.3 ResourceManager — scheduler behaviour

- **FR-17 — Hierarchical queue scheduling.**
  `CapacityScheduler` must schedule through hierarchical queues (`CSQueue`, parent/leaf,
  `AbstractManagedParentQueue` for auto-created queues) with capacity computed by pluggable
  calculators and user limits via the users manager (arch §7.4, `CapacityScheduler`).
- **FR-18 — Fair scheduling.**
  `FairScheduler` must load queues from the allocations XML via `AllocationFileLoaderService` and
  drive preemption from starvation state (`FSStarvedApps`, `FSPreemptionThread`) (arch §7.4,
  `FairScheduler`).
- **FR-19 — Atomic placement commits.**
  Multi-node placement decisions must go through the `AbstractYarnScheduler` commit protocol
  (`ResourceCommitRequest`, `ContainerAllocationProposal`, `AssignmentInformation`) with reservation
  support — not through ad-hoc per-node mutation (arch §7.4, `AbstractYarnScheduler`).
- **FR-20 — Allocation delivery.**
  Scheduler allocation results must reach the AM as `Allocation` objects wrapped in
  `AllocateResponse` by `ApplicationMasterService` (arch §7.4, `ApplicationMasterService`,
  `DefaultAMSProcessor`).
- **FR-21 — Opportunistic containers.**
  When enabled, opportunistic container allocation must be served by
  `OpportunisticContainerAllocatorAMService`, and the default `ApplicationMasterService` path must
  be unchanged when it is disabled (arch §7.4, `OpportunisticContainerAllocatorAMService`).
- **FR-22 — Preemption contract.**
  Preemption must be implemented against the `PreemptableResourceScheduler` contract; a scheduler PR
  must not preempt outside that interface (arch §7.4, `PreemptableResourceScheduler`).

### 1.4 ResourceManager — node tracking and liveness

- **FR-23 — Node registration.**
  A NM `RegisterNodeManagerRequest` arriving at `ResourceTrackerService` must produce an
  `RMNodeStartedEvent` and bring up an `RMNodeImpl` as the RM's mirror of the node (arch §7.5,
  `ResourceTrackerService`).
- **FR-24 — Heartbeat propagation.**
  Each `NodeHeartbeatRequest` must become an `RMNodeStatusEvent`; container status deltas must be
  forwarded to the scheduler and `RMContainerImpl` (arch §7.5, `RMNodeImpl`).
- **FR-25 — Node state transitions.**
  `RMNodeImpl` must support NEW → RUNNING → UNHEALTHY / DECOMMISSIONED / LOST transitions driven by
  heartbeat expiry and health reports, routed through `NodesListManager` (arch §7.5, `RMNodeImpl`).
- **FR-26 — Container tracking states.**
  `RMContainerImpl` must implement the NEW, RESERVED, ALLOCATED, ACQUIRED, RUNNING, COMPLETED,
  EXPIRED, RELEASED, KILLED state set, with RESERVED an optional intermediate state (arch §7.5,
  `RMContainerImpl`).
- **FR-27 — AM expiry.**
  `AMLivelinessMonitor` must post `RMAppAttemptEventType.AM_EXPIRED` when an AM misses heartbeats,
  and `AMFinishingMonitor` must bound the FINISHING state (arch §7.6, `AMLivelinessMonitor`).
- **FR-28 — Allocation expiry.**
  `ContainerAllocationExpirer` must mark containers `EXPIRED` in `RMContainerImpl` and release them
  when the NM does not acknowledge a launch within the configured window, protecting against leaked
  allocations (arch §7.6, `ContainerAllocationExpirer`).
- **FR-29 — Node-loss handling.**
  `NMLivelinessMonitor` expiry or an unhealthy report must lead to killing all `RMContainer`s on the
  node (`KILLED`) and rescheduling the affected work; the AM sees released containers and re-asks
  (arch §9, `NMLivelinessMonitor`, `RMNodeImpl`).

### 1.5 NodeManager — container lifecycle

- **FR-30 — Heartbeat action application.**
  `NodeStatusUpdaterImpl` must apply every `NodeHeartbeatResponse` action — containers to launch,
  clean up, or signal — by dispatching `ContainersLauncherEvent`, `CMgrCompletedContainersEvent`, or
  `CMgrSignalContainersEvent` internally (arch §8.1, `NodeStatusUpdaterImpl`).
- **FR-31 — Status reporting.**
  The NM heartbeat must report container completion statuses, the node's `Resource` (including
  reconfigurations and opportunistic/NM-resource updates via `NodeResourceMonitorImpl`), and
  `NodeHealthChecker` output (disk `DirectoryCollection` health, health scripts) (arch §8.1,
  `NodeStatusUpdaterImpl`).
- **FR-32 — Heartbeat-loss policy.**
  Losing the RM heartbeat loop must trigger the shutdown-or-keep-running decision defined by
  `NodeManagerEvent` handling, not an unhandled exit (arch §8.1, `NodeManager`).
- **FR-33 — Container start path.**
  `ContainerManagerImpl` must validate tokens, authorize the application, and initialize a
  `ContainerImpl` state machine for every `StartContainersRequest` (arch §8.2,
  `ContainerManagerImpl`).
- **FR-34 — Container states.**
  `ContainerImpl` must implement the `ContainerState` set (NEW, LOCALIZING, LOCALIZATION_FAILED,
  SCHEDULED, RUNNING, RELAUNCHING, REINITIALIZING, REINITIALIZING_AWAITING_KILL,
  EXITED_WITH_SUCCESS, EXITED_WITH_FAILURE, KILLING, CONTAINER_CLEANEDUP_AFTER_KILL,
  CONTAINER_RESOURCES_CLEANINGUP, DONE, PAUSING, PAUSED, RESUMING) with the documented event set
  (`ContainerInitEvent`, `ContainerResourceLocalizedEvent`, `ContainerResourceFailedEvent`,
  `ContainerExitEvent`, `ContainerKillEvent`, `ContainerReInitEvent`, `ContainerPauseEvent`) (arch
  §8.2, `ContainerImpl`).
- **FR-35 — Localization tracking.**
  `ResourceLocalizationService` must track localization per application and per container through
  `LocalResourcesTrackerImpl` and `LocalizedResource` entries transitioning DOWNLOADING → LOCALIZED
  / FAILED (arch §8.3, `ResourceLocalizationService`).
- **FR-36 — Localization fetch paths.**
  Public resources must be fetched in parallel by `PublicLocalizer`; private resources must be
  fetched by one spawned `ContainerLocalizer` per (user, application), honouring
  `LocalDirsHandlerService`, `LocalCacheDirectoryManager` disk bookkeeping, and the shared-cache
  fetch path (arch §8.3, `PublicLocalizer`, `ContainerLocalizer`).
- **FR-37 — Launch task selection.**
  `ContainersLauncher` must select the per-container runnable by situation — `ContainerLaunch`,
  `ContainerRelaunch` (per `ContainerRetryPolicy`/`SlidingWindowRetryPolicy`),
  `RecoveredContainerLaunch`/`RecoverPausedContainerLaunch` (NM restart recovery), or
  `ContainerCleanup` (arch §8.4, `ContainersLauncher`).
- **FR-38 — Executor delegation.**
  `LinuxContainerExecutor` must delegate all privileged work through
  `PrivilegedOperation`/`PrivilegedOperationExecutor` invoking the setuid container-executor binary;
  `DefaultContainerExecutor` remains the shell-based fallback (arch §8.4/§18.5,
  `LinuxContainerExecutor`).
- **FR-39 — Memory limit enforcement.**
  `ContainersMonitorImpl` must poll process trees and kill — posting `ContainerExitEvent` with
  failure diagnostics — any container exceeding its memory/virtual-memory limits, and publish per-
  container metrics (arch §8.5, `ContainersMonitorImpl`).
- **FR-40 — Auxiliary service lifecycle.**
  `AuxServices` must receive `AuxServicesEvent`s on application/container lifecycle so auxiliary
  services (shuffle handler, `PerNodeTimelineCollectorsAuxService`, AMRMProxy) can clean up their
  state (arch §8.5, `AuxServices`).
- **FR-41 — Log handling on finish.**
  On application finish, `ContainerManagerImpl` must notify the configured `LogHandler`:
  `NonAggregatingLogHandler` (retain locally, scheduled delete) or `LogAggregationService` (upload
  to remote FS) (arch §8.5/§19.2, `NonAggregatingLogHandler`, `LogAggregationService`).

### 1.6 Application lifecycle end-to-end

- **FR-42 — Lifecycle ordering.**
  The full loop must hold: submit (getNewApplication → submitApplication) → RMApp NEW→ACCEPTED →
  attempt SCHEDULED→ALLOCATED → AM launched by `ApplicationMasterLauncher` with the AMRMToken in its
  launch context → AM registers → allocate-loop grants containers → NM localizes and launches →
  heartbeat statuses flow back → finish/kill or fail/retry (arch §9, `ApplicationMasterLauncher`).
- **FR-43 — AM death recovery.**
  When the AM dies, expiry must fail the attempt and `RMAppImpl` must retry with a new attempt
  reusing the saved `ContainerLaunchContext` from the state store, until `maxAppAttempts` (arch §9,
  `RMStateStore`).
- **FR-44 — Container failure propagation.**
  A container's exit status (`ContainerExitStatus`) must surface as `ContainerImpl`
  EXITED_WITH_FAILURE (with possible relaunch per retry policy), then `RMContainerImpl.COMPLETED`,
  then notification to the AM in `AllocateResponse` so the AM decides on retry (arch §9,
  `ContainerImpl`, `RMContainerImpl`).
- **FR-45 — Application finish.**
  `finishApplicationMaster` must move the attempt RUNNING→FINISHING→FINISHED and the app to FINISHED
  carrying `FinalApplicationStatus`, with logs aggregated and the app cleaned from the RM completion
  lists (arch §9, `RMAppAttemptImpl`, `RMAppImpl`).

### 1.7 ApplicationHistoryService and TimelineService v2

- **FR-46 — History store and write-through.**
  `ApplicationHistoryServer` must serve history through a pluggable `ApplicationHistoryStore`
  (`FileSystemApplicationHistoryStore` on HDFS, `MemoryApplicationHistoryStore` for tests) behind
  the `ApplicationHistoryWriter`/`Reader` interfaces, and a write-through store must let
  `ApplicationReport`s survive RM state-store eviction, served by the AHS web UI (arch §10,
  `ApplicationHistoryManagerImpl`).
- **FR-47 — Collector placement.**
  ATS v2 app-level collectors (`AppLevelTimelineCollector`) must run either in-RM (single-node
  mode) or on the NM hosting the AM (ephemeral mode via `PerNodeTimelineCollectorsAuxService` and
  `NodeTimelineCollectorManager`) (arch §11, `TimelineCollectorManager`).
- **FR-48 — Storage SPI.**
  Timeline reads and writes must go through the `TimelineWriter`/`TimelineReader` SPIs (HBase
  `HBaseTimelineWriterImpl`/`HBaseTimelineReaderImpl`, document-store implementations, `NoOp*`
  defaults, `OfflineAggregationWriter` for flow-activity aggregation); REST readers serve
  entity/flow queries (arch §11, `storage/TimelineWriter`).
- **FR-49 — RM lifecycle timeline events.**
  `RMApplicationHistoryWriter` must write app/attempt lifecycle events as timeline entities through
  the `TimelineWriter` SPI (arch §11/§19.4, `RMApplicationHistoryWriter`).

### 1.8 Router, GlobalPolicyGenerator, WebAppProxy

- **FR-50 — Router proxying.**
  `RouterClientRMService` must proxy `ApplicationClientProtocol` calls through the interceptor chain
  (`ClientRequestInterceptor` → `FederationClientInterceptor` → default / passthrough
  implementations), resolving each application's home sub-cluster from the federation state store
  before forwarding; admin operations must mirror the pattern (`RMAdminRequestInterceptor` chain),
  the Router must cache sub-cluster info per interceptor implementation, purge stale federation
  records, and count forwarded calls in `RouterMetrics` (arch §12, `RouterClientRMService`,
  `RouterMetrics`).
- **FR-51 — GPG control-plane only.**
  The GPG must run federation policy generation (weight/balance policies), sub-cluster pruning, and
  finished-application cleanup on a periodic schedule, issuing RM admin calls only — it must never
  move running containers (arch §12, `GlobalPolicyGenerator`).
- **FR-52 — Proxy access control.**
  `WebAppProxyServlet` must look up the AM web address via `AppReportFetcher`, check the user's
  `ApplicationAccessType.VIEW_APP` ACL, and only then reverse-proxy to the AM UI using attempt-id-
  aware URLs (`ProxyUriUtils`) (arch §13, `WebAppProxyServlet`).
- **FR-53 — Proxy redirect, fallback, certificates.**
  If the AM restarts and changes address, the proxy must re-resolve and redirect; if the application
  is finished, it must fall back to AHS/timeline log URLs; and `ProxyCA` must sign AM-provided
  certificates for the AM HTTPS filter path (arch §13, `ProxyCA`, `AppReportFetcher`).

### 1.9 SharedCacheManager

- **FR-54 — Shared cache contract and eviction.**
  `ClientProtocolService` must implement `ClientSCMProtocol` so clients upload a resource once and
  reference it in `LocalResource` (visibility PUBLIC, type SHARED_CACHE on the NM localizer side),
  with checksum-based store integrity; `SharedCacheCleaner` (with NM-side `LocalCacheCleaner`) must
  evict entries by LRU policy (arch §14, `ClientSCMProtocol`, `SharedCacheCleaner`).

### 1.10 Application-facing modules

- **FR-55 — Client library contract.**
  `YarnClient`, `AMRMClient(+Async)`, and `NMClient(+Async)` must preserve the reference AM loop —
  register → add `ContainerRequest`s → `allocate()` heartbeat returning containers, cluster-resource
  updates, and `AMCommand`s → start containers via NMClient → finish with `FinalApplicationStatus` —
  and RM `AMCommand`s (resync/reboot) must surface to the AM callback handler rather than be
  swallowed (arch §5, `AMRMClientImpl`, `AMRMClientAsync`).
- **FR-56 — Reference applications.**
  `distributedshell` must exercise the full client→RM→NM contract via
  `AMRMClientAsync`/`NMClientAsync` (including `PlacementSpec`), and `unmanaged-am-launcher` must
  let an AM running outside YARN obtain a UAM path via the `uam` classes in server-common (arch
  §15, `distributedshell`, `unmanaged-am-launcher`).
- **FR-57 — Service registry publishing.**
  YARN services should publish and read endpoints through the registry API
  (`org.apache.hadoop.registry.client.api.RegistryOperations`, implemented in `hadoop-common-
  project/hadoop-registry`, ZK-backed with `RegistrySecurity` ACLs) so peers can discover them
  without direct configuration (arch §15/§20.2, `RegistryOperations`).
- **FR-58 — CSI volume mounting.**
  The `hadoop-yarn-csi` adaptors (`CsiAdaptorProtocol` plugins, client, translator) must let YARN
  containers mount external volumes (HDFS/Ozone drivers) (arch §15, `CsiAdaptorProtocol`).

---

## 2. Non-functional requirements

### 2.1 Concurrency (NFR-C)

- **NFR-C-1 — Single-thread dispatcher contract.**
  Every state machine registered on an `AsyncDispatcher` (`RMAppImpl`, `RMAppAttemptImpl`,
  `RMNodeImpl`, `RMContainerImpl`, `ContainerImpl`, …) must execute its transitions serially on the
  single event-handler thread; handlers must never perform blocking I/O or remote calls inside
  `handle()` — a slow handler stalls the whole daemon's event flow (arch §17.1, `AsyncDispatcher`).
  *(supersedes R-NFR-1)*
- **NFR-C-2 — No scheduler-internal locking.**
  In default (synchronous) mode, all `CapacityScheduler` queue-tree mutation must happen on the RM
  dispatcher thread via `SchedulerEventType` handlers; `CapacityScheduler` must contain no internal
  lock objects, and RPC threads (`ApplicationMasterService.allocate`) must never mutate scheduler
  state directly — cross-thread input must be funnelled through events (arch §17.2,
  `CapacityScheduler`). *(supersedes R-NFR-2)*
- **NFR-C-3 — Async scheduling mode.**
  When `yarn.resourcemanager.scheduler.capacity.schedule-asynchronously.enable` is true, scheduling
  must be performed only by `CapacityScheduler .AsyncScheduleThread`s (interval `.scheduling-
  interval-ms`, backlog capped at `.maximum-pending-backlogs`) with multi-node commits applied by
  `ResourceCommitterService` (arch §17.2, `CapacityScheduler`). *(supersedes R-NFR-3)*
- **NFR-C-4 — Fail-fast thread death.**
  Any uncaught exception on the RM dispatcher thread or an `AsyncScheduleThread` must trigger
  `RMFatalEvent` via `RMCriticalThreadUncaughtExceptionHandler` and move the RM to standby/shutdown
  — never silent thread death (arch §17.2/§17.6, `RMCriticalThreadUncaughtExceptionHandler`).
  *(supersedes R-NFR-4)*
- **NFR-C-5 — Queue-depth observability.**
  `AsyncDispatcher` must keep logging event-queue size growth (`lastEventQueueSizeLogged`); a PR
  must not remove the stuck-event diagnostics (`printEventDetailsExecutor` is diagnostic-only and
  must never dispatch events) (arch §17.1, `AsyncDispatcher`). *(supersedes R-NFR-5)*
- **NFR-C-6 — Heartbeat handler hygiene.**
  `ApplicationMasterService.allocate()` must run on RPC handler threads, complete in bounded time
  per heartbeat (dispatch work, return previous allocations), and never execute on the scheduler
  dispatch thread (arch §17.2, `ApplicationMasterService`). *(supersedes R-NFR-6)*
- **NFR-C-7 — One launcher task per container.**
  Each running NM container must be owned by exactly one `ContainersLauncher` task at a time (cached
  thread pool; tasks: `ContainerLaunch`, `ContainerRelaunch`, `RecoveredContainerLaunch`,
  `RecoverPausedContainerLaunch`, `ContainerCleanup`) (arch §17.4, `ContainersLauncher`).
  *(supersedes R-NFR-7)*
- **NFR-C-8 — Localizer thread model.**
  Public localization must use a fixed pool of `yarn.nodemanager.localizer.fetch.thread-count`
  threads (default 4, "PublicLocalizer #%d"); private localization must run one `ContainerLocalizer`
  per (user, application); cache cleanup runs on a single scheduled executor (arch §17.4,
  `ResourceLocalizationService`). *(supersedes R-NFR-8)*
- **NFR-C-9 — Monitor threads.**
  `ContainersMonitorImpl` must keep its dedicated threads (`MonitoringThread` for process-tree
  polling, `LogMonitorThread` for log-dir sizes, `CGroupElasticMemoryController` when enabled) and
  must kill limit-breaching containers via `ContainerExitEvent` (arch §17.4,
  `ContainersMonitorImpl`). *(supersedes R-NFR-9)*
- **NFR-C-10 — Single status-updater thread.**
  The NM heartbeat loop must run on the single "Node Status Updater" thread
  (`NodeStatusUpdaterImpl`), and NM shutdown must `join()` it (with timeout) so the heartbeat loop
  never outlives the daemon (arch §17.4, `NodeStatusUpdaterImpl`). *(supersedes R-NFR-10)*
- **NFR-C-11 — Expiry via events only.**
  Every `AbstractLivelinessMonitor` subclass (`AMLivelinessMonitor`, `NMLivelinessMonitor`,
  `AMFinishingMonitor`, `ContainerAllocationExpirer`) must run its own checker thread and fire
  expiry events on the dispatcher — monitors must never mutate state-machine state directly (arch
  §17.3, `AbstractLivelinessMonitor`). *(supersedes R-NFR-11)*
- **NFR-C-12 — Shutdown ordering.**
  `CompositeService` must stop children in reverse registration order (dispatcher last among
  children); `ResourceManager.serviceStop()` must stop in the order web app → delegation-token
  fetcher → configuration provider → children → `transitionToStandby(false)`; NM shutdown must
  quiesce `NodeStatusUpdaterImpl` as the last-started contact point (arch §17.6, `CompositeService`,
  `ResourceManager.serviceStop`). *(supersedes R-NFR-12)*
- **NFR-C-13 — Timeline flush ordering.**
  `TimelineCollector` flushes must stay serialized per collector (single-thread pool +
  `synchronized(writer)`), retry failures with `writeRetryInterval`, and preserve the
  `DiscardOldestPolicy` semantics — a stalled writer means data loss, not unbounded queue growth
  (arch §17.5, `TimelineCollector`). *(supersedes R-NFR-13)*

### 2.2 Security (NFR-S)

- **NFR-S-1 — Per-daemon Kerberos identity.**
  RM, NM, WebAppProxy, TimelineService, Router and GPG must each log in with their configured
  principal/keytab (`yarn.resourcemanager.principal`, `yarn.nodemanager.principal`, `yarn.web-
  proxy.principal`/`.keytab`, `yarn.timeline-service.principal`, router/GPG equivalents);
  `WebAppProxyServer.doSecureLogin()` must use `SecurityUtil.login`, and the proxy must be a
  separate Kerberos principal from the RM (arch §18.1, `YarnConfiguration`, `WebAppProxyServer`).
  *(supersedes R-NFR-14)*
- **NFR-S-2 — NM token validation.**
  `ContainerManagerImpl` must validate NMToken and container tokens (`NMTokenSecretManagerInNM`) on
  every `ContainerManagementProtocol` request — start, stop, and status — before any container work
  happens; failing requests must be rejected without side effects (arch §18.2,
  `ContainerManagerImpl`). *(supersedes R-NFR-15)*
- **NFR-S-3 — AMRMToken enforcement and rolling.**
  Every `ApplicationMasterProtocol` call must present a valid AMRMToken (`AMRMTokenSecretManager`);
  the master key must be rolled by `MasterKeyRoller` with old keys kept valid for current attempts
  (arch §18.2, `AMRMTokenSecretManager`). *(supersedes R-NFR-16)*
- **NFR-S-4 — Credential passing and renewal.**
  A submitted application's tokens must reach the AM container as a serialized
  `org.apache.hadoop.security.Credentials` inside `ContainerLaunchContext`'s token buffer (with
  `getTokensConf()` for credential-provider settings); `DelegationTokenRenewer` must renew the app's
  delegation tokens for the application lifetime via the per-app renewer pool, and its cancel thread
  must handle expired tokens (arch §18.2/§18.3, `AMLauncher`, `DelegationTokenRenewer`).
  *(supersedes R-NFR-17)*
- **NFR-S-5 — ACL enforcement.**
  When `yarn.acl.enable` is true, every client operation must pass
  `ApplicationACLsManager.checkAccess` (or the scheduler-specific
  `CapacityQueueACLsManager`/`FairQueueACLsManager`), admin operations must pass `yarn.admin.acl`
  via `AdminService`/`ClientRMService`, and `WebAppProxyServlet` must enforce `VIEW_APP` before
  proxying (arch §18.4, `ApplicationACLsManager`). *(supersedes R-NFR-18)*
- **NFR-S-6 — Container user isolation.**
  With `LinuxContainerExecutor` in secure mode, containers must execute under the submitting user's
  identity via the setuid container-executor binary, which validates `container-executor.cfg`
  ownership/permissions itself; in non-secure mode all containers must run as
  `yarn.nodemanager.linux-container-executor.nonsecure-mode.local-user`, bounded by `.nonsecure-
  mode.limit-users` and `.nonsecure-mode.user-pattern` (arch §18.5, `LinuxContainerExecutor`,
  `PrivilegedOperationExecutor`). *(supersedes R-NFR-19)*
- **NFR-S-7 — cGroups version discipline.**
  cGroups handlers must only use controllers valid for the configured version (`CGroupController`:
  v1-only NET_CLS/BLKIO/CPUACCT/FREEZER/DEVICES, v2-only IO; CPU/CPUSET/MEMORY in both); v2 must
  stay disabled unless `yarn.nodemanager.linux-container-executor.cgroups-v2.enabled` is set, and
  device access must be delegated to the container runtime or the GPU/FPGA plugins, not a dedicated
  devices handler (arch §18.6, `CGroupsHandler`). *(supersedes R-NFR-20)*
- **NFR-S-8 — Web authentication filters.**
  RM/NM web UIs must authenticate through `RMAuthenticationFilter` (+ initializer) with SPNEGO and
  delegation-token fallback, using the configured `webapp.spnego-principal` / `spnego-keytab-file`
  keys; ATS v2 collector and reader REST endpoints must authenticate through
  `TimelineAuthenticationFilter` and `TimelineReaderAuthenticationFilter` respectively (arch
  §18.1/§18.7, `RMAuthenticationFilter`).
- **NFR-S-9 — Container-token signing and distribution.**
  `RMContainerTokenSecretManager` must sign the container token embedded in every `Container` record
  and distribute master keys to NMs over the `ResourceTracker` channel; `NMTokenSecretManagerInRM`
  must issue the per-node NM tokens that authenticate `ContainerManagementProtocol` calls (arch
  §18.2, `RMContainerTokenSecretManager`, `NMTokenSecretManagerInRM`).

### 2.3 Logging and auditability (NFR-L)

- **NFR-L-1 — RM audit records.**
  `RMAuditLogger` must emit exactly one tab-separated `key=value` audit record (with
  `SUCCESS`/`FAILURE` markers) per state-changing client operation — submit, kill, move, fail-
  attempt, and container allocation/launch — naming caller UGI and the full app/attempt/container
  identifier chain; read operations (`GET_APP_STATE`, `GET_APP_REPORT`, `GET_CONTAINERS`, …) must
  remain auditable via their existing constants (arch §19.1, `RMAuditLogger`). *(supersedes
  R-NFR-21)*
- **NFR-L-2 — NM and Router audit records.**
  `NMAuditLogger` must emit the same format of record for container start/finish from
  `ContainerManagerImpl` and `ContainerImpl`; `RouterAuditLogger` must audit forwarded client calls
  through `RouterClientRMService` (arch §19.1, `NMAuditLogger`, `RouterAuditLogger`).
- **NFR-L-3 — Log aggregation contract.**
  Finished applications' container logs must be aggregated through the configured
  `LogAggregationFileController` (TFile or indexed-ifile, selected by
  `LogAggregationFileControllerFactory`, honouring `ContainerLogAggregationPolicy`); each aggregated
  file must be readable per (container, application) with that controller's reader; and
  `NMLogAggregationStatusTracker` must report aggregation status back to the RM for every finished
  app. A PR touching aggregation must preserve both shipped controller implementations and the
  factory selection mechanism (arch §19.2, `LogAggregationFileController`,
  `NMLogAggregationStatusTracker`). *(supersedes R-NFR-22)*
- **NFR-L-4 — Metrics registration.**
  Queue-level and cluster-level counters must remain registered through hadoop-common
  `DefaultMetricsSystem` in the `yarn` metrics2 context (`QueueMetrics`, `ClusterMetrics`,
  `ContainerMetrics`), and RM must keep initializing the `JvmMetrics` singleton for process metrics
  (arch §19.3, `QueueMetrics`, `DefaultMetricsSystem`).
- **NFR-L-5 — Timeline as audit trail.**
  App/attempt lifecycle transitions must keep being written as timeline entities
  (`RMApplicationHistoryWriter`) and AM-reported events/metrics as per-application entities
  (`AppLevelTimelineCollector`), queryable via the reader REST API, independent of the audit log
  (arch §19.4, `RMApplicationHistoryWriter`).

### 2.4 Integration (NFR-I)

- **NFR-I-1 — Endpoint defaults.**
  Protocol endpoints must remain configurable through the `yarn.resourcemanager.*` /
  `yarn.nodemanager.*` address keys with the documented defaults — client 8032, scheduler 8030,
  resource-tracker 8031, admin 8033, RM web 8088, NM localizer 8040, NM web 8042, ATS 10200/8188,
  Router 8050/8089, WebAppProxy 9099; a PR changing a protocol binding must not move the default
  port (arch §20.1, `YarnConfiguration`). *(supersedes R-NFR-23)*
- **NFR-I-2 — Runtime selection is NM-side.**
  `YARN_CONTAINER_RUNTIME_TYPE` must select among `DefaultLinuxContainerRuntime`,
  `DockerLinuxContainerRuntime`, `RuncContainerRuntime`, `JavaSandboxLinuxContainerRuntime` via
  `DelegatingLinuxContainerRuntime`, executed through the setuid container-executor path; the RM
  must never be involved in runtime selection (arch §18.5/§20.2, `DelegatingLinuxContainerRuntime`).
  *(supersedes R-NFR-24)*
- **NFR-I-3 — Registry-based discovery.**
  Long-running YARN services should publish endpoints to the ZooKeeper-backed registry so peers can
  discover them without direct configuration; the YARN side must go through the `RegistryOperations`
  API (implementation in hadoop-common's hadoop-registry module, including `RegistrySecurity` for ZK
  ACLs/SASL) (arch §20.2, `RegistryOperations`). *(supersedes R-NFR-25)*
- **NFR-I-4 — Configuration source of truth.**
  Every `yarn.*` property key, default, and deprecation must be declared in `YarnConfiguration`
  (hadoop-yarn-api); a PR introducing a new config key must declare it there, and config-name
  compatibility checks in review use that file (arch §20.3, `YarnConfiguration`).
- **NFR-I-5 — Wire format and enforcement fallback.**
  The four core protocols plus `ClientSCMProtocol` and `CsiAdaptorProtocol` must remain protobuf-
  based RPC surfaces wired through `YarnRPC`/`HadoopYarnProtoRPC` with `impl.pb.service` server
  wrappers and `impl.pb.client` proxies (arch §3/§4, `HadoopYarnProtoRPC`); and the NM must keep
  working when cGroups are unavailable by falling back to process-tree enforcement
  (`ContainersMonitorImpl` + `ResourceCalculatorProcessTree`) (arch §20.2, `ContainersMonitorImpl`).

---

## 3. PR-review checklists

Use these per-area checklists when reviewing a diff; each item cites the
requirement IDs that decide it.

### 3.1 API / protocol changes

- [ ] Are record/protobuf changes wire-compatible, with the API module still free of server logic? (FR-9, NFR-I-5)
- [ ] Are the four core protocol contracts intact, including `ContainerUpdateRequest`? (FR-1–FR-4)
- [ ] Do hierarchical IDs and the `Resource` model still join correctly across state machines? (FR-5, FR-6)
- [ ] Is a new config key declared in `YarnConfiguration` with its default? (NFR-I-4)

### 3.2 ResourceManager / scheduler

- [ ] Does scheduler state get mutated only on the dispatcher thread — no internal locks, no RPC-thread mutation? (NFR-C-1, NFR-C-2, NFR-C-6)
- [ ] Do multi-node placements go through the commit protocol with reservations? (FR-19)
- [ ] Are app/attempt/container state machines extended without breaking documented states? (FR-11–FR-13, FR-26, FR-34)
- [ ] Do liveness/expiry paths act only via events, and does thread death fail fast? (NFR-C-4, NFR-C-11, FR-27–FR-29)
- [ ] Does recovery still replay apps and reacquire containers on restart? (FR-12, FR-16, FR-43)

### 3.3 NodeManager / localization

- [ ] Are tokens validated on every `ContainerManagementProtocol` call before container work? (NFR-S-2, NFR-S-9)
- [ ] Does localization preserve the public/private thread model and disk bookkeeping? (NFR-C-8, FR-35, FR-36)
- [ ] Is exactly one launcher task per container preserved, including retry and recovery paths? (NFR-C-7, FR-37)
- [ ] Are memory-limit breaches still fatal to the container, with diagnostics? (FR-39, NFR-C-9)
- [ ] Does the heartbeat loop stay on its single thread, with correct shutdown join? (NFR-C-10, FR-30, FR-32)

### 3.4 Security

- [ ] Are principals/keytabs respected per daemon, including the proxy's separate principal? (NFR-S-1)
- [ ] Do ACL checks (app, queue, admin, proxy VIEW_APP) still gate every operation when enabled? (NFR-S-5, FR-52)
- [ ] Do tokens reach containers as serialized Credentials, with renewal for the app lifetime? (NFR-S-4, NFR-S-9)
- [ ] Does container execution preserve user isolation via the setuid binary? (NFR-S-6, NFR-I-2)
- [ ] Are cGroups controller/version rules respected? (NFR-S-7, NFR-I-5)

### 3.5 Logging / audit

- [ ] Does every state-changing operation produce exactly one audit record with the identifier chain? (NFR-L-1, NFR-L-2)
- [ ] Is log aggregation still pluggable, readable per container, and status-tracked? (NFR-L-3, FR-41)
- [ ] Are metrics still registered in the `yarn` metrics2 context? (NFR-L-4)
- [ ] Are lifecycle transitions still written to the timeline as an audit trail? (NFR-L-5, FR-49)

### 3.6 Auxiliary daemons (AHS/Timeline, Router/GPG, proxy, SCM)

- [ ] Are collector flushes still serialized per collector with the documented back-pressure semantics? (NFR-C-13, FR-47)
- [ ] Does the Router stay a stateless interceptor-chain proxy with audit logging and metrics? (FR-50, NFR-L-2)
- [ ] Does the GPG remain control-plane-only (no container moves)? (FR-51)
- [ ] Does the proxy keep ACL checks, attempt-aware URLs, and history fallback? (FR-52, FR-53)
- [ ] Are shared-cache uploads still checksum-deduplicated with LRU eviction? (FR-54)
- [ ] Do port defaults and endpoint keys remain unchanged? (NFR-I-1)

---

## References

- Source architecture notes:
  `notes/architecture/hadoop-yarn-architecture.md` — §3 protocols, §4 common,
  §5 clients, §7 ResourceManager, §8 NodeManager, §9 lifecycle, §10 AHS,
  §11 TimelineService v2, §12 Router/GPG, §13 WebAppProxy,
  §14 SharedCacheManager, §15 registry/CSI/applications, §17 Concurrency,
  §18 Security, §19 Logging, §20 Integration, §21 NFR candidates.
- Source tree grounding: `hadoop-yarn-project/hadoop-yarn/` in this checkout —
  every class name cited above was verified there by the architecture analysis.
- Superseded source: arch §21 "Non-functional requirement candidates" items
  R-NFR-1 through R-NFR-25, mapped in the derivation section and marked
  *(supersedes R-NFR-n)* on each inheriting requirement.
