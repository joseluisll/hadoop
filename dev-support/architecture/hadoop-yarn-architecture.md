# Apache Hadoop YARN — Architecture Notes

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

Analysis depth: the YARN project (`hadoop-yarn-project/hadoop-yarn/`) plus its
first-level subcomponents. All class names below are taken from the actual
source tree of this checkout.

> **Document method.** This document follows the shared definition and method in
> [README.md](README.md) (*About these documents — definition and method*): a
> source-grounded orientation document pinned to the **As-of** trunk commit
> above, depth-2 scope, fixed section skeleton, merged-trunk state only.
> Updates land exclusively through dedicated arch/req review sessions;
> PR-review sessions record gaps as candidates in `notes/arch-req-candidates.md`
> instead of editing this file.

## Table of contents

1. [Overview](#1-overview)
2. [Module map](#2-module-map)
3. [hadoop-yarn-api — protocol interfaces and record model](#3-hadoop-yarn-api--protocol-interfaces-and-record-model)
4. [hadoop-yarn-common — configuration, service framework, RPC wiring](#4-hadoop-yarn-common--configuration-service-framework-rpc-wiring)
5. [hadoop-yarn-client — client-side libraries](#5-hadoop-yarn-client--client-side-libraries)
6. [hadoop-yarn-server/common — shared server plumbing](#6-hadoop-yarn-servercommon--shared-server-plumbing)
7. [ResourceManager](#7-resourcemanager)
8. [NodeManager](#8-nodemanager)
9. [Application lifecycle end-to-end](#9-application-lifecycle-end-to-end)
10. [ApplicationHistoryService](#10-applicationhistoryservice)
11. [TimelineService v2](#11-timelineservice-v2)
12. [Router and GlobalPolicyGenerator (federation)](#12-router-and-globalpolicygenerator-federation)
13. [WebAppProxy](#13-webappproxy)
14. [SharedCacheManager](#14-sharedcachemanager)
15. [hadoop-yarn-registry, hadoop-yarn-csi, and the applications modules](#15-hadoop-yarn-registry-hadoop-yarn-csi-and-the-applications-modules)
16. [Behaviour summary](#16-behaviour-summary)
17. [Concurrency](#17-concurrency)
18. [Security](#18-security)
19. [Logging and auditability](#19-logging-and-auditability)
20. [Integration points](#20-integration-points)
21. [Non-functional requirement candidates](#21-non-functional-requirement-candidates)

---

## 1. Overview

YARN ("Yet Another Resource Negotiator") is Hadoop's cluster resource manager.
It separates resource management from application logic: a per-cluster
**ResourceManager (RM)** owns scheduling, per-node **NodeManagers (NM)** own
container execution, and per-application **ApplicationMasters (AM)** — user
code — negotiate for resources. Everything YARN ships inside
`hadoop-yarn-project/hadoop-yarn/` is either the wire/record layer, the two
daemons plus their support services, or the auxiliary federation, history and
registry pieces.

The dominant runtime idiom is **event-driven state machines on an async
dispatcher**: almost every daemon component is an `AbstractService` registered
with a `Dispatcher` (`AsyncDispatcher` in hadoop-yarn-common), communicates via
typed events, and runs its lifecycle as a state-machine transition table.

## 2. Module map

| Module | Role |
|---|---|
| `hadoop-yarn-api` | Protocol interfaces (`ApplicationClientProtocol`, `ApplicationMasterProtocol`, `ResourceTracker`, `ContainerManagementProtocol`), record model, `YarnConfiguration` |
| `hadoop-yarn-common` | Config, `AsyncDispatcher`/service framework glue, protobuf RPC serialization, log aggregation helpers, security helpers |
| `hadoop-yarn-client` | `YarnClient`, `AMRMClient`, `NMClient` client libraries |
| `hadoop-yarn-server/*` | RM, NM, AHS, TimelineService v2 (+HBase/documentstore backends), Router, GPG, WebAppProxy, SharedCacheManager, timeline-pluginstorage, common |
| `hadoop-yarn-applications/*` | `distributedshell`, `unmanaged-am-launcher`, `services` (slider-style services API), `catalog` (docker webapp), `mawo` |
| `hadoop-yarn-csi` | CSI (Container Storage Interface) adaptor/client/translator plugins |
| `hadoop-yarn-registry` | Service-registry integration (ZK-backed) |
| `hadoop-yarn-ui/site/capacity-scheduler-ui` | Scheduler UI assets (one-liner: Angular-based queue visualisation embedded in the RM web UI) |

## 3. hadoop-yarn-api — protocol interfaces and record model

**Purpose.** Defines every public RPC surface and the immutable record objects
that travel over it. Both client libraries and the server daemons depend on
it; it is deliberately free of server logic.

**Protocols** (all in `org.apache.hadoop.yarn.api`):

- `ApplicationClientProtocol` — clients ↔ RM: submit/kill applications
  (`SubmitApplicationRequest`, `KillApplicationRequest`), query
  `ApplicationReport`, get `NewApplication`/`NewApplicationSubmissionContext`,
  delegation tokens, queue and node reports.
- `ApplicationMasterProtocol` — AM ↔ RM: `RegisterApplicationMasterRequest`,
  `AllocateRequest`/`AllocateResponse` (the heartbeat/allocate cycle),
  `FinishApplicationMasterRequest`. This is the allocation contract.
- `ResourceTracker` — NM ↔ RM: `RegisterNodeManagerRequest`,
  `NodeHeartbeatRequest` carrying `NodeStatus` (container statuses, kept
  containers, health), response hands back containers to launch/clean.
- `ContainerManagementProtocol` — AM/NM-client ↔ NM:
  `StartContainersRequest`, `StopContainersRequest`,
  `GetContainerStatusesRequest`, plus `ContainerUpdateRequest` for in-place
  resource changes.
- Also `ApplicationBaseProtocol`, `ApplicationHistoryProtocol`,
  `ClientSCMProtocol` (shared cache), `CsiAdaptorProtocol` (storage).

**Record model** (`org.apache.hadoop.yarn.api.records`): immutable POJOs with
protobuf-backed implementations in hadoop-yarn-common. Key types:

- `ApplicationId` = cluster timestamp + sequence; `ApplicationAttemptId`
  wraps it; `ContainerId` wraps an attempt plus container sequence. These
  hierarchical IDs are the join keys across every state machine.
- `Resource` — memory MB + vcores + custom resources (GPUs, FPGAs) via the
  `resource` package (`ResourceInformation`, `ResourceTypes`).
- `Container` — id, `NodeId`, `Resource`, priority, token
  (`ContainerToken`), `ExecutionType` (guaranteed/opportunistic).
- `ContainerLaunchContext` — commands, environment, `LocalResource` map
  (URLs + timestamps + sizes for localization), ACLs, tokens.
- `ApplicationSubmissionContext` — everything the client specifies at
  submit: name, queue, priority, AM resource request, AM container launch
  context, attempt fail-count limits, `ContainerRetryPolicy`.

**Behaviour.** The API is purely declarative: callers build request records,
the transport layer (protobuf in hadoop-yarn-common) serializes them. Version
compatibility is maintained at the protobuf level, so this module changes
slowly and conservatively.

## 4. hadoop-yarn-common — configuration, service framework, RPC wiring

**Purpose.** Shared runtime glue: configuration, the service/event framework,
RPC serialization, security and log-aggregation utilities.

Key pieces:

- `YarnConfiguration` (note: lives in **hadoop-yarn-api**,
  `org.apache.hadoop.yarn.conf`) — the central `Configuration` subclass; every
  `yarn.*` property key, default and deprecation is declared here. Both RM and
  NM construct their service graphs from it.
- **Service framework** (`org.apache.hadoop.yarn.service` in common, actually
  inherited from hadoop-common's `AbstractService`/`CompositeService`): YARN
  daemons are trees of `Service` objects with `INIT → STARTED → STOPPED`
  transitions; `CompositeService` composes them (see the `addService(...)`
  call chains in `ResourceManager` and `NodeManager`).
- **Event framework** (`org.apache.hadoop.yarn.event`): `Event`,
  `EventHandler<Event>`, `Dispatcher`, `AsyncDispatcher` (single background
  thread draining a `BlockingQueue`), `EventDispatcher`. Every state machine
  (`RMAppImpl`, `RMAppAttemptImpl`, `RMContainerImpl`, `ContainerImpl`,
  `RMNodeImpl`) registers as an event handler on a dispatcher.
- **RPC serialization wiring** (`org.apache.hadoop.yarn.ipc`): `YarnRPC`
  selects the protocol implementation; `HadoopYarnProtoRPC` wires the
  protobuf-backed pipeline. For each protocol there is a generated `*PB`
  interface plus hand-written server-side wrappers in
  `org.apache.hadoop.yarn.api.impl.pb.service` (e.g.
  `ContainerManagementProtocolPBServiceImpl`) and client-side
  `impl.pb.client` proxies that convert record objects ↔ protobuf messages.
- Log-aggregation helpers (`org.apache.hadoop.yarn.logaggregation`,
  e.g. `LogAGSConstants`, aggregation file readers/writers), security helpers
  (`ClientToAMTokenSecretManager`, ConfigurationProvider classes such as
  `LocalConfigurationProvider` / `FileSystemBasedConfigurationProvider`).

**Behaviour.** At daemon startup, services are constructed, `init(conf)` and
`start()`ed in composition order; `AsyncDispatcher.start()` begins pumping
events. Any RPC arriving is deserialized into a protocol record, usually
routed to a handler that converts it into an event posted to the relevant
state machine — so the wire path and the internal event path meet in thin
controller classes (`ClientRMService`, `ApplicationMasterService`,
`ResourceTrackerService`, `ContainerManagerImpl`).

## 5. hadoop-yarn-client — client-side libraries

- `YarnClient` / `impl.YarnClientImpl` — wraps `ApplicationClientProtocol`:
  submit, kill, poll `ApplicationReport`, queue/node administration.
  `YarnClientApplication` returns the `NewApplication` + submission context
  pair used before submit.
- `AMRMClient` / `impl.AMRMClientImpl` — the AM-side allocator loop: registers
  the AM, accumulates `ContainerRequest`s, and on each `allocate()` heartbeat
  sends asks and receives `Container`s, `ClusterAvailableResources` updates
  and `AMCommand`s (e.g. resync/reboot). `async` package provides
  `AMRMClientAsync` with a callback handler so user AM code is event-driven.
- `NMClient` / `impl.NMClientImpl` — starts/stops containers via
  `ContainerManagementProtocol`, managing NM token cache (`NMTokenCache`) per
  node. `NMClientAsync` wraps it with callbacks.

**Behaviour.** A hand-written AM typically: register with RM → add container
requests → loop on `AMRMClientAsync.allocate()` → for each granted container,
`NMClientAsync.startContainerAsync(launchContext)` → on completion, finish AM
with `FinalApplicationStatus`.

## 6. hadoop-yarn-server/common — shared server plumbing

`hadoop-yarn-server/hadoop-yarn-server-common` holds code used by both RM and
NM: `AMRMClientRelayer` and `AMHeartbeatRequestHandler` (used by the AMRMProxy
and federation), `api` protocol PB helpers, `webapp` util,
`federation` client façades, security token secret-manager interfaces, and the
`service` abstractions. The container-token and NM-token master keys, plus
record types such as node status, are shared here so RM and NM agree on the
heartbeat payload.

## 7. ResourceManager

Module: `hadoop-yarn-server-resourcemanager`. Entry class `ResourceManager`
extends `CompositeService`; its `serviceInit`/`serviceStart` wires (verified
from source `addService(...)` calls): `AdminService`, `ClientRMService`,
`ApplicationMasterService`, `ResourceTrackerService`,
`ApplicationMasterLauncher`, `NodesListManager`, `NMLivelinessMonitor`,
`AMLivelinessMonitor`, `AMFinishingMonitor`, `ContainerAllocationExpirer`,
`RMAppManager`, `DelegationTokenRenewer`, `RMSecretManagerService`, and an
`AsyncDispatcher`. Shared state lives in `RMContextImpl` (`RMContext`).

#### RMActiveServices and the active service graph

`RMActiveServices` (an inner `CompositeService` of `ResourceManager`,
declared in `ResourceManager.java`) is the graph of services that exist only
while the RM is ACTIVE; `createAndInitActiveServices()` builds it and
rebuilds it on each active/standby transition. `serviceInit` wires, in
registration order (verified in source): `RMSecretManagerService`,
`ContainerAllocationExpirer`, the two `AMLivelinessMonitor`s (expiry and
finishing), `RMAppLifetimeMonitor` (`rmapp/monitor/`, application-lifetime
expiry driven by `yarn.resourcemanager.application-timeouts.monitor.interval-ms`),
the node label manager (`RMNodeLabelsManager`), the node attributes manager,
`AllocationTagsManager`, `PlacementConstraintManagerService`,
`ResourceProfilesManager`, `MultiNodeSortingManager`, the optional
`RMDelegatedNodeLabelsUpdater`, the state store
(`RMStateStoreFactory.getStore(conf)` when `yarn.resourcemanager.recovery.enabled`
is true, otherwise `NullRMStateStore`), `NodesListManager`, the scheduler, the
`EventDispatcher` for `SchedulerEventType`, the app/attempt/node event
dispatchers, `NMLivelinessMonitor`, `ResourceTrackerService`, a
`JvmPauseMonitor`, the optional reservation system, `ApplicationMasterService`,
`RMAppManager`, `ClientRMService`, `ApplicationMasterLauncher`, and — in
secure mode only — `DelegationTokenRenewer`; conditionally also a federation
state-store service, `ProxyCAManager`, and the services-API
`SystemServiceManager`.

`RMActiveServices.serviceStart()` starts the state store first and runs
recovery (`checkVersion()`, `loadState()`, `recover(state)`) before the
children start, incrementing the epoch for work-preserving recovery; a
single-thread `ScheduledThreadPoolExecutor` daemon
("`EventQueueSizeMetricThread`") samples both the RM dispatcher and the
scheduler `EventDispatcher` every second and publishes
`rmEventQueueSize`/`schedulerEventQueueSize` gauges to `ClusterMetrics`.

### 7.1 Dispatcher / event bus

`org.apache.hadoop.yarn.event.AsyncDispatcher` (from hadoop-yarn-common) is
instantiated inside `ResourceManager`; each sub-state-machine registers a
handler for its event enum (`RMAppEvent`, `RMAppAttemptEvent`,
`RMNodeEvent`, `RMContainerEvent`, `AMLauncherEvent`, ...). One event = one
state-machine transition, processed serially. A fatal handler
(`RMCriticalThreadUncaughtExceptionHandler`, `RMFatalEvent`) transitions the
RM to standby/shutdown on internal corruption.

#### AsyncDispatcher mechanics and RM registration topology

The RM dispatcher thread is named "AsyncDispatcher event handler" by default
(`AsyncDispatcher` constructor; `setDispatcherName()` renames both the thread
and the queue-depth log line). `RMActiveServices` registers on the RM bus:
`SchedulerEventType` → an `EventDispatcher` (`schedulerDispatcher`, which
itself runs a second dedicated dispatch thread), `RMAppEventType` →
`ApplicationEventDispatcher`, `RMAppAttemptEventType` →
`ApplicationAttemptEventDispatcher`, `RMNodeEventType` → `NodeEventDispatcher`
(`static final` inner classes of `ResourceManager`); sub-services register
`RMContainerEventType`, `AMLauncherEventType`, `RMAppManagerEventType` and
`RMFatalEvent` handlers on the same bus. The `EventQueueSizeMetricThread`
described above reads queue depth through `AsyncDispatcher.getEventQueueSize()`.

#### RMFatalEvent path

`RMCriticalThreadUncaughtExceptionHandler` converts an uncaught exception on
a critical thread (dispatcher, `AsyncScheduleThread`s) into an
`RMFatalEvent`; `RMFatalEventDispatcher` (inner class of `ResourceManager`)
handles it by failing over or shutting down. `RMFatalEventType` covers
`STATE_STORE_FENCED`, `STATE_STORE_OP_FAILED`, `EMBEDDED_ELECTOR_FAILED`,
`TRANSITION_TO_ACTIVE_FAILED` and `CRITICAL_THREAD_CRASH` — state-store and
elector failures surface here rather than as silent errors.

### 7.2 ApplicationsManager / RMAppManager

`RMAppManager` handles client submissions arriving at `ClientRMService`
(`submitApplication`): validates the `ApplicationSubmissionContext`, creates
an `RMAppImpl`, registers it in `RMContext`, and posts `RMAppEventType.START`.
It also enforces max-app-completion limits and fires `RMAppManagerEvent`s for
completed-app cleanup. `ClientRMService` is the user-facing RPC surface;
`AdminService` the operator surface (refresh queues/nodes, transition to
standby).

#### RMAppManager internals

`RMAppManager` implements `EventHandler<RMAppManagerEvent>`. Its state
containers are the completed-app bookkeeping: `maxCompletedAppsInMemory` and
`maxCompletedAppsInStateStore` (the state-store cap is clamped to the
in-memory cap at init) plus a `LinkedList<ApplicationId> completedApps` and
its `completedAppsInStateStore` counter; on every finished app,
`checkAppNumCompletedLimit()` trims the oldest applications from memory and
asks the state store to remove the excess. `submitApplication` validates the
`ApplicationSubmissionContext`, checks the submit queue ACL, has
`RMStateStore` persist the new application and posts `RMAppEventType.START`;
failures audit through `RMAuditLogger`.

#### ClientRMService and AdminService

`ClientRMService` binds the `ApplicationClientProtocol` server from
`yarn.resourcemanager.address` in `serviceStart()`; submit/kill/move calls
are audited with `RMAuditLogger` (success and failure paths) and reservation
calls are delegated to the scheduler's reservation system.
`AdminService` (`CompositeService`) binds `RMAdminProtocol` from
`yarn.resourcemanager.admin.address`; every operation (`refreshQueues`,
`refreshNodes`, `refreshNodesResources`,
`refreshSuperUserGroupsConfiguration`, `transitionToActive`/
`transitionToStandby`, ...) passes `checkAcls(method)`/`checkAccess(method)`
against `yarn.admin.acl` before executing. The embedded elector services
(`ActiveStandbyElectorBasedElectorService`, `CuratorBasedElectorService`) and
the HA fencing path hang off it; elector failures reach the RM as
`RMFatalEvent`s.

#### ApplicationMasterService and the AMS processing chain

`ApplicationMasterService` (`AbstractService`) owns the
`ApplicationMasterProtocol` listener bound from
`yarn.resourcemanager.scheduler.address`. `allocate()` runs on RPC handler
threads and forwards to an `AMSProcessingChain` built around
`DefaultAMSProcessor` and extended with any processors listed in
`yarn.resourcemanager.application-master-service.processors` (e.g.
`VolumeAMSProcessor`, which also installs a `VolumeManager` in the RM
context). With opportunistic scheduling enabled, the service instance is
`OpportunisticContainerAllocatorAMService`, which additionally receives
`SchedulerEventType` node additions/updates/removals through its own
`EventDispatcher` registered on the RM bus.

### 7.3 RMApp / RMAppAttempt state machines

- `rmapp/RMAppImpl` — states (from `RMAppState`): `NEW, NEW_SAVING,
  SUBMITTED, ACCEPTED, RUNNING, FINAL_SAVING, FINISHING, FINISHED, FAILED,
  KILLING, KILLED`. `NEW_SAVING` writes submission context to the state
  store for recovery; `ACCEPTED` → attempt scheduling begins.
- `rmapp/attempt/RMAppAttemptImpl` — states (from `RMAppAttemptState`):
  `NEW, SUBMITTED, SCHEDULED, ALLOCATED, LAUNCHED, RUNNING, FINISHING,
  FINISHED, KILLED, FAILED` plus saving variants
  (`ALLOCATED_SAVING`, `LAUNCHED_UNMANAGED_SAVING`, `FINAL_SAVING`).
  `SCHEDULED` = AM container request outstanding; `ALLOCATED` = container
  granted; `LAUNCHED` = AM started on an NM; `RUNNING` = AM registered.
- Failure handling: on attempt failure `RMAppImpl` decides retry vs.
  fail based on `maxAppAttempts` (default 2) and the AM failure validity
  window; a `RMAppAttemptFailedEvent` may spawn a new attempt (new
  `ApplicationAttemptId`) or move the app to `FAILED`.

#### RMAppImpl internals

The state container is the `StateMachineFactory`-generated `stateMachine`;
thread safety comes from a `ReentrantReadWriteLock` (`readLock`/`writeLock`
fields): `handle()` takes the write lock around `doTransition`, report
construction takes the read lock. `RMAppImpl` composes `RMAppLogAggregation`
(log-aggregation coordination across attempts) and carries the
`ApplicationSubmissionContext` plus attempt bookkeeping; the `NEW_SAVING`
transition persists the submission context through `RMStateStore` before
processing `RMAppEventType.APP_NEW_SAVED`.

#### RMAppAttemptImpl internals

Same idiom — generated `stateMachine` guarded by a
`ReentrantReadWriteLock` — with fields `eventHandler` (the RM dispatcher's
handler) and `scheduler` (the `YarnScheduler`) so transitions can post
`SchedulerEvent`s (`AppAttemptAddedSchedulerEvent`,
`AppAttemptRemovedSchedulerEvent`) and launch the AM by posting
`AMLauncherEvent(AMLauncherEventType.LAUNCH)` to the RM bus, absorbing
`Allocation` results in return. The attempt holds the AM
`ContainerLaunchContext` and master-token containers; a granted AM container
is persisted via `ALLOCATED_SAVING` before `ApplicationMasterLauncher` is
asked to launch it, and the whole attempt is written to `RMStateStore`
(`STORE_APP_ATTEMPT`) at the saving transitions.

#### RMStateStore interaction

`RMStateStore` is itself an `AbstractService` with its **own** dispatcher
(`RMStateStoreEventType` transitions: `STORE_APP`, `UPDATE_APP`,
`STORE_APP_ATTEMPT`, `UPDATE_APP_ATTEMPT`, `REMOVE_APP`,
`REMOVE_APP_ATTEMPT`, `STORE_MASTERKEY`, `STORE_DELEGATION_TOKEN`,
`UPDATE_AMRM_TOKEN`, `STORE_RESERVATION`, `STORE_PROXY_CA_CERT`, `FENCED`,
...), so state-store writes execute off the RM main thread and completion
events (`RMStateStoreAppEvent`, `RMStateStoreAppAttemptEvent`, ...) are
posted back to the RM dispatcher. Implementations selected via
`yarn.resourcemanager.store.class` (`RMStateStoreFactory`):
`ZKRMStateStore`, `FileSystemRMStateStore`, `LeveldbRMStateStore`,
`MemoryRMStateStore` (tests), `NullRMStateStore` (recovery disabled).

### 7.4 Scheduler hierarchy

- `scheduler/AbstractYarnScheduler` — common base: tracks
  `SchedulerApplication` and `SchedulerNode` per app/node, maintains
  `ClusterNodeTracker`, and implements the container-allocation commit
  protocol (`scheduler/common/ResourceCommitRequest`,
  `ContainerAllocationProposal`, `AssignmentInformation`) used for
  multi-node, atomic placement decisions with reservation support.
- `scheduler/capacity/CapacityScheduler` — hierarchical queues
  (`CSQueue`, `AbstractParentQueue`, `AbstractLeafQueue`,
  `AbstractManagedParentQueue` for auto-created dynamic queues); capacity
  computed by pluggable calculators (`AbstractQueueCapacityCalculator`,
  `AbsoluteResourceCapacityCalculator`); users limits via
  `AbstractUsersManager`; preemption via the `PreemptableResourceScheduler`
  contract. Placement uses `AppPlacementAllocator` hierarchy (placement
  factorised under `scheduler/`).
- `scheduler/fair/FairScheduler` — `FSQueue`/`FSLeafQueue`/`FSParentQueue`,
  queues loaded from an allocations XML by `AllocationFileLoaderService`,
  `FSSchedulerNode`/`FSAppAttempt`, starvation-driven preemption
  (`FSStarvedApps`, `FSPreemptionThread`).
- Allocation results are handed to the AM as `Allocation` objects wrapped in
  `AllocateResponse` by `ApplicationMasterService` (with
  `DefaultAMSProcessor` and the optional
  `OpportunisticContainerAllocatorAMService` for opportunistic containers).

#### AbstractYarnScheduler shared state

`AbstractYarnScheduler` keeps `ClusterNodeTracker<N>` (the node list and
per-node `SchedulerNode` lookup) and per-application `SchedulerApplication`
maps; cluster-wide mutations that must be atomic with each other are guarded
by its own `ReentrantReadWriteLock` (`readLock`/`writeLock` fields with
documented write-lock usages), while allocation input arrives only as
`SchedulerEvent`s. Per-app state (`AppSchedulingInfo`) maps
`SchedulerRequestKey`s to `AppPlacementAllocator`s
(e.g. `SingleConstraintAppPlacementAllocator`). Multi-node placement commits
go through `scheduler/common/ResourceCommitRequest` and `tryCommit`.

#### CapacityScheduler internals

Queue tree: `CSQueue` → `ParentQueue`/`AbstractParentQueue` and
`LeafQueue`/`AbstractLeafQueue`; per-app `FiCaSchedulerApp` and per-node
`FiCaSchedulerNode` live under `scheduler/common/fica/`. Under async
scheduling, `AsyncSchedulingConfiguration` (inner class) spawns
`.maximum-threads` `AsyncScheduleThread`s (default 1) that loop `schedule()`
every `.scheduling-interval-ms` (default 5) under a
`.maximum-pending-backlogs` cap (default 100), with commit decisions applied
by the separate `ResourceCommitterService` thread — proposals and commits
run on different threads. Key rolling of other token types happens in the
security managers (section 7.7).

#### FairScheduler internals

`FairScheduler` composes `AllocationFileLoaderService` (`allocsLoader`,
which loads/reloads the allocations XML), `FSContext`, `QueueManager` (the
`FSQueue`/`FSLeafQueue`/`FSParentQueue` tree) and
`FSSchedulerNode`/`FSAppAttempt`. A dedicated `FSPreemptionThread` (extends
`Thread`) computes starved apps (`FSStarvedApps`) and issues preemption; it
is started in `serviceStart()` with an uncaught-exception handler
installed, and `serviceStop()` interrupts and `join(THREAD_JOIN_TIMEOUT_MS)`s
it so thread death is neither silent nor allowed to outlive the daemon.

### 7.5 Resource tracker

`ResourceTrackerService` implements the `ResourceTracker` protocol: NMs
register (`RegisterNodeManagerRequest` → `RMNodeStartedEvent`) and heartbeat
(`NodeHeartbeatRequest` → `RMNodeStatusEvent`). `rmnode/RMNodeImpl` is the RM's
mirror of a node — states include NEW → RUNNING → UNHEALTHY/DECOMMISSIONED/
LOST transitions; container status deltas are forwarded to the scheduler and
`RMContainerImpl` (`rmcontainer`, states `NEW, RESERVED, ALLOCATED, ACQUIRED,
RUNNING, COMPLETED, EXPIRED, RELEASED, KILLED`).

#### ResourceTrackerService request handling

`registerNodeManager` validates the registration (secret-manager state,
node labels/attributes), builds the `RMNodeImpl` and posts
`RMNodeStartedEvent`; `nodeHeartbeat` converts the incoming `NodeStatus`
into an `RMNodeStatusEvent`, updates `DecommissioningNodesWatcher` for
graceful-decommission progress, and returns a `NodeHeartbeatResponse`
carrying containers to launch/clean/signal and the next heartbeat interval.
All handling runs on `ResourceTracker` RPC handler threads — `RMNodeImpl`
mutation happens only via events on the RM dispatcher.

#### RMNodeImpl and RMContainerImpl state containers

`RMNodeImpl` guards its state with a `ReentrantReadWriteLock`
(`readLock`/`writeLock`) and buffers node updates in a
`ConcurrentLinkedQueue<UpdatedContainerInfo> nodeUpdateQueue` drained by
`StatusUpdateWhenHealthyTransition` per heartbeat; `DeactivateNodeTransition`
handles DECOMMISSION/LOST/UNHEALTHY deactivation. `RMContainerImpl` is the
per-container RM-side mirror (`readLock`/`writeLock` plus its
`stateMachine`); container state changes that affect scheduling are
forwarded as `RMContainerEvent`s and `SchedulerEvent`s.

### 7.6 Liveliness monitors and expiry

- `AMLivelinessMonitor` (`hadoop-yarn-common` `AbstractLivelinessMonitor`) —
  expiry threads that fire `RMAppAttemptEventType.EXPIRE` when an AM
  misses heartbeats; `AMFinishingMonitor` bounds the finishing state.
- `ContainerAllocationExpirer` — enforces the window between container
  allocation and the NM's launch acknowledgement; expired containers are
  marked `EXPIRED` in `RMContainerImpl` and released, protecting against
  leaked allocations.
- `NMLivelinessMonitor` — node heartbeats; expiry posts `RMNodeEvent`
  DECOMMISSION/LOST handling through `NodesListManager`.

#### AbstractLivelinessMonitor mechanics

Each monitor instance runs a single `PingChecker` thread (named
"Ping Checker for <service-name>", started in `serviceStart()`, interrupted
on stop). The tracked map is a plain `HashMap` guarded by `synchronized`
`register`/`receivedPing`/`unregister`/`resetTimer` methods; the checker
scans every `monitorInterval` (default `expireInterval/3`) and invokes the
subclass `expire()` for timed-out keys. The expiry callbacks post events and
never mutate state directly: `AMLivelinessMonitor` →
`RMAppAttemptEventType.EXPIRE` (interval
`yarn.resourcemanager.am.liveness-monitor.expiry-interval-ms`, default 15
min), `NMLivelinessMonitor` → `RMNodeEventType.EXPIRE` (interval
`yarn.resourcemanager.nm.liveness-monitor.expiry-interval-ms`, default 10
min), `ContainerAllocationExpirer` → `ContainerExpiredSchedulerEvent` on the
scheduler dispatcher (interval
`yarn.resourcemanager.rm.container-allocation.expiry-interval-ms`, default
10 min).

#### ApplicationMasterLauncher threading

`ApplicationMasterLauncher` holds a `BlockingQueue<Runnable> masterEvents`
drained by a `LauncherThread`; each `AMLauncherEvent` becomes an
`AMLauncher` `Runnable` submitted to `launcherPool`, a fixed
`ThreadPoolExecutor` of `yarn.resourcemanager.amlauncher.thread-count`
(default 50) threads named "ApplicationMasterLauncher #%d".
`AMLauncher.run()` calls `launch()` (builds the AM `ContainerLaunchContext`,
adds the AMRMToken, calls the target NM over `ContainerManagementProtocol`
via `NMProxy` with `yarn.resourcemanager.nodemanager-connect-retries`
applied) or `cleanup()` (on kill/fail). `serviceStop()` shuts the pool down.

### 7.7 Security and delegation tokens

`security/` holds `RMDelegationTokenSecretManager` (client delegation tokens,
with `DelegationTokenRenewer` renewing tokens on behalf of submitted apps),
`AMRMTokenSecretManager`, `NMTokenSecretManagerInRM`,
`RMContainerTokenSecretManager`, `ClientToAMTokenSecretManagerInRM`, and queue
ACL managers (`QueueACLsManager`, `CapacityQueueACLsManager`,
`FairQueueACLsManager`).

#### RMSecretManagerService and key rolling

`RMSecretManagerService` (a `CompositeService`) constructs and owns
`RMContainerTokenSecretManager`, `NMTokenSecretManagerInRM`,
`AMRMTokenSecretManager` and `ClientToAMTokenSecretManagerInRM`.
`AMRMTokenSecretManager` runs a `java.util.Timer` with two `TimerTask`s —
`MasterKeyRoller` (rolls the current AMRM master key every
`yarn.resourcemanager.am-rm-tokens.master-key-rolling-interval-secs`,
default 86400) and `NextKeyActivator` — both mutating key state under the
manager's `readWriteLock` write lock while token validation reads under the
read lock. `RMContainerTokenSecretManager` and `NMTokenSecretManagerInRM`
roll their keys the same way (`...container-tokens.master-key-rolling-interval-secs`
and the NM-token equivalent); the current master keys ride every NM
heartbeat.

#### DelegationTokenRenewer threading

`DelegationTokenRenewer` is added to the active services only when
`UserGroupInformation.isSecurityEnabled()`. Its executor
(`createNewThreadPoolService`) is a `ThreadPoolExecutor` sized from
`yarn.resourcemanager.delegation-token-renewer.thread-count` (default 50);
renewal work is submitted asynchronously via `DelegationTokenRenewerEvent`s
(with a `DelegationTokenRenewerPoolTracker` accounting in-flight work), and
a `DelegationTokenCancelThread` cancels expired tokens on its own thread.
Renewals therefore run on pool threads, never on the RM dispatcher.

## 8. NodeManager

Module: `hadoop-yarn-server-nodemanager`. Entry class `NodeManager`
(`CompositeService`): registers `DeletionService`, `NodeHealthChecker`,
`NodeResourceMonitor`, `ContainerManagerImpl`, `NMLogAggregationStatusTracker`,
web server, an `AsyncDispatcher`, and `NodeStatusUpdaterImpl` (the last
service started, so heartbeats begin only after everything else is up).

### 8.1 NodeStatusUpdater

`NodeStatusUpdaterImpl` opens the heartbeat loop to `ResourceTrackerService`:
on `NodeHeartbeatResponse` it receives actions — containers to launch, clean
up, signal — and dispatches them internally (`ContainersLauncherEvent`,
`CMgrCompletedContainersEvent`, `CMgrSignalContainersEvent`). It also reports
container completion statuses, the node's `Resource` (reconfigured or
Opportunistic/NM-resource updates via `NodeResourceMonitorImpl`), and health
check output from `NodeHealthChecker` (disk `DirectoryCollection` health,
health scripts). Losing the heartbeat loop (RM unreachable) triggers
shutdown-or-keep-running per `NodeManagerEvent`.

#### StatusUpdaterRunnable internals

The single "Node Status Updater" thread builds each `NodeStatus` from the
NM context (container statuses, `NodeHealthChecker` health report, node
labels/attributes handlers, `getRegisteringCollectors()` for ATS v2, the
current container-token and NM-token master keys and `tokenSequenceNo`),
optionally attaches `LogAggregationReport`s, and calls
`resourceTracker.nodeHeartbeat`. From the `NodeHeartbeatResponse` it applies
`getNextHeartBeatInterval()` (adaptive sleep), `updateMasterKeys()` (rolling
NM-token keys with `tokenSequenceNo` checks), `handleShutdownOrResyncCommand()`
(a REBOOT forces re-registration), removal of acked cleaned containers, and —
via events on the NM dispatcher — `CMgrCompletedContainersEvent`,
`CMgrCompletedAppsEvent` (with keep-alive tracking of apps to be cleaned),
`CMgrUpdateContainersEvent` and `CMgrSignalContainersEvent`; system
credentials for apps are pushed through
`context.getContainerManager().handleCredentialUpdate()`. Registration
failures retry inside `registerWithRM()` with backoff.

### 8.2 ContainerManagerImpl and container state machine

`containermanager/ContainerManagerImpl` implements `ContainerManagementProtocol`.
On `StartContainersRequest` it validates tokens (`NMTokenSecretManagerInNM`,
container tokens), authorizes the application, and initializes a
`ContainerImpl` state machine (`containermanager/container/ContainerImpl`).
States (from `ContainerState`): `NEW, LOCALIZING, LOCALIZATION_FAILED,
SCHEDULED, RUNNING, RELAUNCHING, REINITIALIZING,
REINITIALIZING_AWAITING_KILL, EXITED_WITH_SUCCESS, EXITED_WITH_FAILURE,
KILLING, CONTAINER_CLEANEDUP_AFTER_KILL, CONTAINER_RESOURCES_CLEANINGUP,
DONE, PAUSING, PAUSED, RESUMING`. Events include `ContainerInitEvent`,
`ContainerResourceLocalizedEvent`, `ContainerResourceFailedEvent`,
`ContainerExitEvent`, `ContainerKillEvent`, `ContainerReInitEvent`,
`ContainerPauseEvent` (pause/resume support for opportunistic upgrade flows).

#### ContainerImpl state machine and locking

`ContainerImpl` guards its state with a `ReentrantReadWriteLock`
(`readLock`/`writeLock` fields); transitions run on the NM dispatcher thread
that delivers `ContainerEvent`s. A `StartContainersRequest` is validated
(`NMTokenSecretManagerInNM` + container tokens, application ACLs, audited
via `NMAuditLogger`) before a `ContainerInitEvent` per container is posted;
localization moves the container to `SCHEDULED`, where
`ContainersLauncher` gets its launch task. Kill/reinitialize/pause/resume
arrive as `ContainerKillEvent`/`ContainerReInitEvent`/
`ContainerPauseEvent`/`ContainerResumeEvent` (also from `CMgr*` handling),
and exit statuses as `ContainerExitEvent`.

### 8.3 Localization service

`containermanager/localizer/ResourceLocalizationService` runs the download
phase between `LOCALIZING` and `SCHEDULED`: per-app and per-container
`LocalResourcesTrackerImpl` track `LocalizedResource` entries (states
DOWNLOADING → LOCALIZED / FAILED) driven by `LocalizerResourceRequestEvent`s;
`ContainerLocalizer` (a spawned JVM) fetches resources from remote FS or the
shared cache (`localizer/sharedcache`), respecting `LocalDirsHandlerService`
and `LocalCacheDirectoryManager` disk bookkeeping. `PublicLocalizer` handles
public visibility resources in parallel.

#### ResourceLocalizationService internals

A `CompositeService` holding per-app/per-public `LocalResourcesTrackerImpl`
trackers; each tracked `LocalizedResource` is itself a small state machine
(`INIT → DOWNLOADING → LOCALIZED/FAILED`). Public resources are downloaded
by the `PublicLocalizer` inner `Thread` handing work to the fixed
"PublicLocalizer #%d" pool (`createLocalizerExecutor`, size
`yarn.nodemanager.localizer.fetch.thread-count`); private resources run one
`LocalizerRunner` `Thread` per localizer id (user/application context),
spawning `ContainerLocalizer` downloaders. A single-thread
`HadoopScheduledThreadPoolExecutor` (`cacheCleanup`) schedules `CacheCleanup`
at `yarn.nodemanager.localizer.cache.cleanup.interval-ms` and deletion is
delegated to `DeletionService`; disk accounting per local directory is done
by `LocalCacheDirectoryManager`, and shared-cache fetches are delegated to
the `localizer/sharedcache` classes.

### 8.4 Launcher and executors

`containermanager/launcher/ContainersLauncher` dispatches per-container
`ContainerLaunch` (first run), `ContainerRelaunch` (retry per
`ContainerRetryPolicy` / `SlidingWindowRetryPolicy`), `RecoveredContainerLaunch`
and `RecoverPausedContainerLaunch` (NM restart recovery), or `ContainerCleanup`.
Executors under `containermanager/runtime` / top-level: `ContainerExecutor`
base, `DefaultContainerExecutor` (shell-based), `LinuxContainerExecutor`
(delegates to the setuid `container-executor` binary; supports Docker and
Java-based runtimes via `linux/` runtime classes, e.g. DockerLinuxContainer
runtime selection).

#### ContainersLauncher internals

`ContainersLauncher` is the `ContainersLauncherEventType` handler: each event
becomes a `ContainerLaunch`, `ContainerRelaunch`, `RecoveredContainerLaunch`,
`RecoverPausedContainerLaunch` or `ContainerCleanup` task submitted to the
`containerLauncher` cached thread pool; `serviceStop()` calls
`shutdownNow()`. `ContainerLaunch` materializes the launch script,
environment and tokens and invokes the configured `ContainerExecutor`
(`yarn.nodemanager.container-executor.class`); exit statuses come back as
`ContainerExitEvent`s and relaunches follow `ContainerRetryPolicy`/
`SlidingWindowRetryPolicy`.

#### Container execution plumbing

`DefaultContainerExecutor` (top-level `nodemanager/` package) runs shell
processes as the NM user; `LinuxContainerExecutor` funnels every privileged
operation through `PrivilegedOperationExecutor` and the setuid
container-executor binary (section 18.5), and selects the per-container
runtime (`DefaultLinuxContainerRuntime`, `DockerLinuxContainerRuntime`,
`RuncContainerRuntime`, `JavaSandboxLinuxContainerRuntime` via
`DelegatingLinuxContainerRuntime`) from `YARN_CONTAINER_RUNTIME_TYPE`.

### 8.5 Monitoring, aux services, log aggregation

- `containermanager/monitor/ContainersMonitorImpl` — polls process trees,
  enforces memory/virtual-memory limits (kill on breach → `ContainerExitEvent`
  with failure diagnostics), publishes per-container metrics.
- `containermanager/AuxServices` — pluggable `AuxiliaryService` lifecycle
  (shuffle handler, `PerNodeTimelineCollectorsAuxService` for ATS v2, AMRMProxy
  in some deployments); receives `AuxServicesEvent`s on app/container lifecycle
  so services can clean state.
- `logaggregation/` — `LogHandler` implementations: `NonAggregatingLogHandler`
  (retain local logs, delete on app finish) and the aggregating path
  (`LogAggregationService` + per-app `AppLogAggregatorImpl` uploading container
  logs to HDFS as TFile); `logaggregation/tracker/NMLogAggregationStatusTracker`
  reports aggregation status to the RM for the UI.

#### ContainersMonitorImpl threads

Three dedicated threads: `MonitoringThread` polls each running container's
process tree every `yarn.nodemanager.container-monitor.interval-ms`
(defaulting to `yarn.nodemanager.resource-monitor.interval-ms`) through the
configured `ResourceCalculatorPlugin`, kills containers that breach their
memory/virtual-memory limits (`ContainerExitEvent` with failure
diagnostics) and feeds `ContainerMetrics`; `LogMonitorThread` runs at
`yarn.nodemanager.container-log-monitor.interval-ms` and enforces the
`.dir-size-limit-bytes`/total-size limits; and, when cGroups
elastic-memory control is enabled, `CGroupElasticMemoryController` listens
for OOM events.

#### AuxServices lifecycle

`AuxServices` keeps its `serviceMap`/`serviceRecordMap`/`serviceMetaData` as
`Collections.synchronizedMap` instances and makes `serviceInit`/`serviceStart`
/`serviceStop` and manifest-driven replacement
(`maybeReadManifestFile`/`loadServices`/`maybeRemoveAuxService`)
`synchronized`, so aux-service reload is atomic with event handling.
`AuxServicesEvent`s (`APPLICATION_INIT`, `APPLICATION_STOP`,
`CONTAINER_INIT`, `CONTAINER_STOP`) are delivered to the registered
`AuxiliaryService` instances so they can create/clean per-app state (shuffle
data, ATS collector state, AMRMProxy proxies).

#### Log handling internals

`LogAggregationService` keeps a
`ConcurrentMap<ApplicationId, AppLogAggregator> appLogAggregators` and a
fixed `ExecutorService threadPool` of `getAggregatorThreadPoolSize(conf)`
threads; `serviceStop()` shuts the pool down and waits for in-flight
aggregators before finishing. `AppLogAggregatorImpl` runs as one pool task
per finished application and uploads logs through the
`LogAggregationFileController` SPI (section 19.2).
`NonAggregatingLogHandler` instead schedules delayed local log deletion on
its own `ScheduledThreadPoolExecutor`; `NMLogAggregationStatusTracker`
carries per-app aggregation status into the next heartbeat.

## 9. Application lifecycle end-to-end

The full loop across modules (all steps verified against the classes above):

1. **Submit** — client (`YarnClientImpl`) gets a new `ApplicationId`
   (`getNewApplication`), fills `ApplicationSubmissionContext`, calls
   `submitApplication` → `ClientRMService` → `RMAppManager` → new `RMAppImpl`
   (`NEW` → `NEW_SAVING` → `SUBMITTED` → `ACCEPTED`).
2. **AM container request** — `RMAppImpl` starts attempt 1
   (`RMAppAttemptImpl` `NEW`→`SUBMITTED`→`SCHEDULED`): an AM-resource
   `ContainerRequest` enters the scheduler.
3. **Allocate** — `CapacityScheduler` (or Fair) picks a `SchedulerNode`,
   creates `RMContainerImpl` (`NEW`→`RESERVED`?→`ALLOCATED`), the attempt
   moves to `ALLOCATED` (after `ALLOCATED_SAVING` persists it), and
   `AMLivelinessMonitor`/`ContainerAllocationExpirer` timers arm.
4. **AM start** — `ApplicationMasterLauncher`/`AMLauncher` builds the AM
   `ContainerLaunchContext` (including `AMRMToken`), sends it via
   `ContainerManagementProtocol` to the target NM (`LAUNCHED`), the AM
   registers (`ApplicationMasterService.registerApplicationMaster`) →
   `RUNNING`.
5. **Container grant** — the AM heartbeats `allocate()`; granted containers
   arrive as `Container` records (`ACQUIRED` in `RMContainerImpl`); the AM
   starts them through `NMClient` → `ContainerManagementProtocol` →
   `ContainerManagerImpl` → `ContainerImpl` (`NEW`→`LOCALIZING`→`SCHEDULED`
   →`RUNNING`) with `ResourceLocalizationService` then `ContainersLauncher`.
6. **Heartbeats** — NMs report status through `ResourceTrackerService` →
   `RMNodeImpl` → container completion events → `RMContainerImpl`
   `COMPLETED` → scheduler frees resources → AM sees updated
   `AllocateResponse` (completed container statuses).
7. **Finish** — AM calls `finishApplicationMaster` → attempt
   `RUNNING`→`FINISHING` (`FINAL_SAVING`)→`FINISHED`; app
   `RUNNING`→`FINAL_SAVING`→`FINISHING`→`FINISHED` with
   `FinalApplicationStatus`; logs aggregated; app cleaned up from
   `RMAppManager` completion lists.

**Failure handling:**

- *AM dies*: `AMLivelinessMonitor` expires the attempt
  (`RMAppAttemptEventType.EXPIRE`) →
  `RMAppAttemptImpl.FAILED`; `RMAppImpl` retries with a new attempt until
  `maxAppAttempts`; AM container restart reuses saved
  `ContainerLaunchContext` from the state store.
- *Container fails*: NM reports exit status (`ContainerExitStatus`) →
  `ContainerImpl` `EXITED_WITH_FAILURE` (+ possible relaunch per retry
  policy) → RM `RMContainerImpl.COMPLETED` → AM notified, decides on retry.
- *NM lost / unhealthy*: `NMLivelinessMonitor` expiry or unhealthy status →
  `RMNodeImpl` → all `RMContainer`s on the node killed (`KILLED`), containers
  rescheduled elsewhere; AM resubmits affected container requests.
- *RM restart*: recovery via the state store (`recovery/RMStateStore`
  implementations) replays apps/attempts (`RMAppRecoverEvent`) and, with
  work-preserving restart, reacquires containers from NMs
  (`RMContainerRecoverEvent`).

#### Submit path: client to RMAppManager

`YarnClientImpl` gets a `NewApplication` (`getNewApplication` — the RM
reserves an `ApplicationId`), fills the `ApplicationSubmissionContext`, and
`submitApplication` reaches `ClientRMService.submitApplication` (ACL +
`RMAuditLogger`), then `RMAppManager.submitApplication` (validation, state
store persist, `RMAppEventType.START`). Submission is asynchronous from the
client's point of view: the call returns after acceptance, and the client
follows progress by polling `ApplicationReport`.

#### Attempt allocation and AM launch

`RMAppAttemptImpl` posts the AM-resource request into the scheduler
(`SCHEDULED`); when the grant arrives, `AMContainerAllocatedTransition`
persists the attempt (`ALLOCATED_SAVING`) and posts
`AMLauncherEvent(AMLauncherEventType.LAUNCH)`. `ApplicationMasterLauncher`
queues it, an `AMLauncher` task in the launcher pool calls the target NM's
`ContainerManagementProtocol` (`startContainers`), and the AM's
`registerApplicationMaster` on `ApplicationMasterService` moves the attempt
to `RUNNING`; from then on `allocate()` heartbeats drive both progress and
liveness (`ApplicationMasterService` calls
`AMLivelinessMonitor.receivedPing` on every AM call).

#### AM runtime loop: AMRMClientAsync and NMClientAsync

User AMs are wired through `AMRMClientAsyncImpl` — a single
`HeartbeatThread` calls `AMRMClientImpl.allocate()` at the configured
interval and hands results to the `AbstractCallbackHandler` (containers
allocated/completed, shutdown, scheduler resync/reboot commands) on the
heartbeat thread. `NMClientAsyncImpl` dispatches start/stop/query events on
its dedicated event-dispatcher thread and runs the container operations on a
`ThreadPoolExecutor` over `NMClientImpl`, which manages the per-node
`NMTokenCache`; container start failures surface through the callback
handler so the AM can retry or finish.

#### Finish and cleanup

`finishApplicationMaster` (`FinalApplicationStatus`) puts the attempt through
`FINAL_SAVING` (state-store write) → `FINISHING` → `FINISHED`; the app
follows with `FINAL_SAVING`/`FINISHING`/`FINISHED`, `AMLauncherEventType`
CLEANUP events kill any surviving AM container, logs are aggregated on the
NM side, and `RMAppManager` trims the finished app from memory/state store
per its completion limits.

## 10. ApplicationHistoryService

Module `hadoop-yarn-server-applicationhistoryservice` (ATS v1).
`ApplicationHistoryServer` composes `ApplicationHistoryClientService` +
`ApplicationHistoryManagerImpl` over a pluggable
`ApplicationHistoryStore` — `FileSystemApplicationHistoryStore` (HDFS-backed,
`ApplicationHistoryWriter`/`ApplicationHistoryReader` interfaces) or
`MemoryApplicationHistoryStore` (tests). `ApplicationHistoryManagerOnTimelineStore`
adapts v1 APIs on top of a timeline store. AMs report their own history via
the `ApplicationHistoryProtocol` (historically through the
`AMApplicationMasterService` path). **Behaviour:** a write-through store lets
`ApplicationReport` survive RM state-store eviction; the AHS web UI serves
finished-app reports and logs.

#### ApplicationHistoryServer composition and store threading

`ApplicationHistoryServer` (`CompositeService`) registers, in order: a
secret-manager service, the `TimelineDataManager`, `ApplicationHistoryClientService`
(the `ApplicationHistoryProtocol` RPC service), the
`ApplicationHistoryManagerImpl`-style history manager service itself, and a
`JvmPauseMonitor`. The store SPI is `ApplicationHistoryStore` with
`FileSystemApplicationHistoryStore` (HDFS; writes go through per-writer
`synchronized` `HistoryFileWriter` streams keyed by `HistoryDataKey`),
`MemoryApplicationHistoryStore` (tests) and `NullApplicationHistoryStore`;
`ApplicationHistoryManagerOnTimelineStore` adapts the same reader/writer
interfaces onto a TimelineService v2 store. History writes are performed
inside `ApplicationHistoryManagerImpl` on the calling (RPC) thread — there
is no internal event bus in ATS v1.

## 11. TimelineService v2

Modules `hadoop-yarn-server-timelineservice` (core), `...-hbase`
(`hadoop-yarn-server-timelineservice-hbase-client` contains
`HBaseTimelineWriterImpl`/`HBaseTimelineReaderImpl`; reader/server war files
separate), `...-documentstore`
(`DocumentStoreTimelineWriterImpl`/`DocumentStoreTimelineReaderImpl` over
Mongo/Cosmos-style collections), `hadoop-yarn-server-timeline-pluginstorage`
(`TimelineWriter` plugin storage), and the RM-side collector wiring in
`ResourceManager` (`timelineCollectorManager`, `rmApplicationHistoryWriter`).

Key classes (core, `org.apache.hadoop.yarn.server.timelineservice`):

- `collector/TimelineCollector` — base entity collector;
  `AppLevelTimelineCollector(+WithAgg)` runs per application, either in-RM
  (single-node mode) or on the NM hosting the AM (ephemeral mode).
- `collector/TimelineCollectorManager` — manages collector lifecycle and
  REST (`TimelineCollectorWebService`); `NodeTimelineCollectorManager`
  is the NM-side manager exposed through the
  `PerNodeTimelineCollectorsAuxService` auxiliary service.
- `storage/TimelineWriter` / `storage/TimelineReader` — storage SPIs
  (`NoOpTimelineWriterImpl`/`NoOpTimelineReaderImpl` defaults;
  `OfflineAggregationWriter` for flow-activity aggregation;
  `TimelineSchemaCreator` for HBase table bootstrap; `TimelineStorageMonitor`
  liveness).
- `reader/` — query engines (entity, flow, app-id/level filtering).

**Behaviour:** AM/NM-side collectors buffer entity/metric writes and flush
them through the writer SPI to HBase or document store; readers serve REST
queries. The RM is wired as a `TimelineWriter` consumer for app-level
lifecycle data (`RMApplicationHistoryWriter` under `resourcemanager/ahs`).

#### Collector internals and flush path

`TimelineCollector` (`CompositeService`) buffers entities per collector and
flushes them on a `ThreadPoolExecutor(1, 1, 3, SECONDS)` with a
`DiscardOldestPolicy`; each flush runs `flushBufferedTimelineEntities()`
under `synchronized (writer)` and retries on failure sleeping
`writeRetryInterval` (section 17.5). `TimelineCollectorManager` owns the
per-app collector lifecycle and exposes `TimelineCollectorWebService`
(REST). On the NM side, `NodeTimelineCollectorManager` (started through the
`PerNodeTimelineCollectorsAuxService` auxiliary service) hosts ephemeral
collectors for AMs it localizes; on the RM side,
`RMTimelineCollectorManager` (`resourcemanager/timelineservice/`) hosts
single-node collectors and `RMApplicationHistoryWriter` converts
app/attempt/container lifecycle into timeline entities.

#### Reader and storage SPIs

`TimelineReaderServer` hosts the reader REST web services
(`TimelineReaderWebServices`) on top of `TimelineReaderManager` over the
`TimelineReader` SPI; storage is selected via `YarnConfiguration`
(`TimelineWriter`/`TimelineReader` classes: `HBaseTimelineWriterImpl`/
`HBaseTimelineReaderImpl` for HBase,
`DocumentStoreTimelineWriterImpl`/`DocumentStoreTimelineReaderImpl` for the
document store, `NoOpTimelineWriterImpl`/`NoOpTimelineReaderImpl` defaults),
`TimelineSchemaCreator` bootstraps HBase tables, `OfflineAggregationWriter`
handles flow-activity aggregation and `TimelineStorageMonitor` checks store
liveness.

## 12. Router and GlobalPolicyGenerator (federation)

Federation lets multiple RMs (sub-clusters) appear as one cluster. The
`hadoop-yarn-server/federation` client code lives in server-common; the two
daemons:

- **Router** (`hadoop-yarn-server-router`): `Router` / `RouterServer` hosts
  `RouterClientRMService` (`clientrm/`) — an `ApplicationClientProtocol`
  proxy built from an interceptor chain
  (`ClientRequestInterceptor` → `FederationClientInterceptor` →
  `DefaultClientRequestInterceptor`/`PassThroughClientRequestInterceptor`)
  that resolves the home sub-cluster for each app from the federation
  state store, then forwards. `rmadmin/` mirrors this for admin ops
  (`RMAdminRequestInterceptor` chain). `webapp/` serves the federation UI,
  `cleaner/` purges stale federation records, `RouterMetrics` counts
  forwarded calls. **Behaviour:** stateless REST/RPC proxy with audit
  logging; caching of sub-cluster info per `FederationClientInterceptor`
  implementation.
- **GlobalPolicyGenerator** (`hadoop-yarn-server-globalpolicygenerator`):
  `GlobalPolicyGenerator` + `GPGContextImpl`/`GPGPolicyFacade` run the
  federation `policygenerator` (weight/balance policies across
  sub-clusters), `subclustercleaner` (prune inactive sub-clusters), and
  `applicationcleaner` (clean finished federated applications).
  **Behaviour:** a periodic control-plane daemon that adjusts federation
  policy weights and hygiene; it issues RM admin calls rather than moving
  running containers.

#### Router internals

`Router` (`CompositeService`) adds `RouterClientRMService` (the
`ApplicationClientProtocol` proxy on `yarn.router.clientrm.address`) and
starts the router web app. `RouterClientRMService` keeps a per-user
`Map<String, RequestInterceptorChainWrapper> userPipelineMap` (an
LRU-bounded `Collections.synchronizedMap` cache) of
`ClientRequestInterceptor` pipelines built from the configured
`FederationClientInterceptor` class; each call resolves the sub-cluster
through the federation state store, forwards over the RM protocol and
audits through `RouterAuditLogger`/`RouterMetrics`. The `cleaner/` package
runs `SubClusterCleaner` (a `Runnable` that marks sub-clusters whose
heartbeat exceeds `ROUTER_SUBCLUSTER_EXPIRATION_TIME` as LOST);
`security/` and `webapp/` cover SPNEGO login and the federation UI.

#### GlobalPolicyGenerator internals

`GlobalPolicyGenerator` (`CompositeService`) builds its `GPGContextImpl`
(state-store facade via `FederationStateStoreFacade`, `GPGPolicyFacade`,
`FederationRegistryClient` for YARN-registry registration) and one
`ScheduledThreadPoolExecutor` of
`yarn.federation.gpg.scheduled.executor.threads` (default 10) from which
`serviceStart()` schedules three `Runnable`s at fixed rates:
`SubClusterCleaner` (`yarn.federation.gpg.subcluster.cleaner.interval-ms`),
the configured `ApplicationCleaner` (`yarn.federation.gpg.application.cleaner.class`,
default `DefaultApplicationCleaner`, at
`yarn.federation.gpg.application.cleaner.interval-ms`) and
`PolicyGenerator` (`yarn.federation.gpg.policy.generator.interval`, default
1 h), whose `GlobalPolicy` implementations
(`LoadBasedGlobalPolicy`, `UniformWeightedLocalityGlobalPolicy`,
`NoOpGlobalPolicy`) re-weight sub-cluster queue capacities through the
`GPGPolicyFacade`. `doSecureLogin()` performs the Kerberos login; metrics
run under `DefaultMetricsSystem` with `JvmMetrics.initSingleton("GPG", null)`.

## 13. WebAppProxy

Module `hadoop-yarn-server-web-proxy`. `WebAppProxyServer` runs
`WebAppProxy` hosting `WebAppProxyServlet`: it looks up an application's AM
web address via `AppReportFetcher` (`DefaultAppReportFetcher` talks to the
RM; `FedAppReportFetcher` resolves through the Router in federation), checks
the user's ACL (`ApplicationAccessType.VIEW_APP`), then reverse-proxies to
the AM UI, tracking AM restarts via `ProxyUriUtils` (attempt-id-aware URLs)
and `ProxyCA` for signing AM-provided certificates (AM RKMS/HTTPS am filter
support under `amfilter/`). **Behaviour:** if the AM restarts and changes
address, the proxy re-resolves and redirects; if the app is finished, it
falls back to AHS/timeline log URLs.

#### WebAppProxyServlet request path

`WebAppProxyServlet.doGet` extracts the application id from the
`ProxyUriUtils`-style URL, fetches the current app report through the
servlet-context-configured `AppReportFetcher` (`DefaultAppReportFetcher`
against the RM or `FedAppReportFetcher` through the Router), enforces
`ApplicationAccessType.VIEW_APP` before proxying, and follows redirects
when the AM moves. In secure deployments the servlet pulls the
servlet-context `ProxyCA` (`WebAppProxy.PROXY_CA` attribute) to sign
AM-provided certificates; when the app is finished it falls back to the
aggregated log URLs. `WebAppProxy`/`WebAppProxyServer` own the `HttpServer2`
proxy server, the `AppReportFetcher` instance and the `ProxyCA`.

## 14. SharedCacheManager

Module `hadoop-yarn-server-sharedcachemanager`. Implements
`ClientSCMProtocol`: clients upload resources once and reference them in
`LocalResource` (visibility `PUBLIC`, type `SHARED_CACHE` on the NM localizer
side). `ClientProtocolService`, `SharedCacheCleaner` (LRU-style eviction per
`LocalCacheCleaner` on the NM side) and checksum-based store integrity.
**Behaviour:** reduces localization bandwidth by deduplicating commonly used
resources (e.g. jars).

#### SharedCacheManager service composition and cleaners

`SharedCacheManager` (`CompositeService`) registers, in order: the
`SCMStore` service (the checksum-addressed metadata store SPI —
`InMemorySCMStore` by default under `store/`), `CleanerService` (a
`CompositeService` that starts the `AppChecker`/`RemoteAppChecker`
app-alive check as a dependent service and runs its `CleanerTask` on a
2-thread `ScheduledExecutorService` at the configured period in minutes),
`SharedCacheUploaderService` (the `SCMUploaderProtocol` surface for NMs
uploading resources), `ClientProtocolService` (the `ClientSCMProtocol`
surface for clients) and `SCMAdminProtocolService` (admin). On the NM side,
localization hits the shared cache through `localizer/sharedcache` and
eviction of local shared-cache files is done by `LocalCacheCleaner`
(section 8.3).

## 15. hadoop-yarn-registry, hadoop-yarn-csi, and the applications modules

- **hadoop-yarn-registry** — service registry API + ZooKeeper-based
  implementation (`org.apache.hadoop.registry.*`, sources packaged under
  `hadoop-yarn-registry`); apps and services publish endpoints for discovery
  by other components (used by slider-style `hadoop-yarn-services`).
- **hadoop-yarn-csi** — CSI support: `adaptor` (CsiAdaptorProtocol plugins
  translating K8s-CSI semantics for HDFS/Ozone drivers), `client`,
  `translator`, `utils` — lets YARN containers mount external volumes.
- **hadoop-yarn-applications**:
  - `distributedshell` — canonical example AM: `Client` (submits) +
    `ApplicationMaster` (uses `AMRMClientAsync`/`NMClientAsync`); also
    `PlacementSpec` for node-label/placement demos and a timeline plugin.
  - `unmanaged-am-launcher` — launches an AM outside YARN's control
    (AM already running, RM grants it a UAM path via `uam` classes in
    server-common).
  - `services` (`hadoop-yarn-services-core` + `hadoop-yarn-services-api`) —
    the "services" framework (ServiceManager AM, component orchestration,
    registry integration) that powers long-running services on YARN.
  - `catalog` — docker app catalog webapp + docker image definitions.
  - `mawo` (`hadoop-yarn-applications-mawo-core`) — "make applications
    work-order" example batch-orchestration app.
- **hadoop-yarn-ui/site/capacity-scheduler-ui** — one-liner: Angular-based
  capacity-scheduler visualisation shipped as the RM web UI queue page.

## 16. Behaviour summary

- **hadoop-yarn-api**: pure protocol + record contracts; the four core
  protocols (`ApplicationClientProtocol`, `ApplicationMasterProtocol`,
  `ResourceTracker`, `ContainerManagementProtocol`) define every runtime
  interaction; hierarchical IDs (`ApplicationId`→`ApplicationAttemptId`→
  `ContainerId`) and `Resource` model everything.
- **hadoop-yarn-common**: `YarnConfiguration` (declared in hadoop-yarn-api)
  + `CompositeService` service trees + `AsyncDispatcher` event buses +
  protobuf RPC (`YarnRPC`/`HadoopYarnProtoRPC`, `impl.pb.service` wrappers)
  are the shared runtime; every daemon is built from these three idioms.
- **hadoop-yarn-client**: `YarnClient` (submit/poll/kill), `AMRMClient(+Async)`
  (register/allocate heartbeat loop), `NMClient(+Async)` (start/stop
  containers); the reference AM loop is register → ask → allocate → launch →
  finish.
- **ResourceManager**: submission via `ClientRMService`/`RMAppManager` builds
  `RMAppImpl` (`NEW_SAVING`→`ACCEPTED`); per-attempt `RMAppAttemptImpl`
  (`SCHEDULED`→`ALLOCATED`→`LAUNCHED`→`RUNNING`) drives AM launch through
  `ApplicationMasterLauncher`; schedulers (`CapacityScheduler`/
  `FairScheduler` over `AbstractYarnScheduler`) grant containers tracked as
  `RMContainerImpl`; `ResourceTrackerService`+`RMNodeImpl` handle NM
  registration/heartbeats; `AMLivelinessMonitor`,
  `ContainerAllocationExpirer`, `NMLivelinessMonitor` enforce liveness;
  failure of AM/container/NM maps to attempt-retry / container-release /
  node-lost rescheduling respectively.
- **NodeManager**: `NodeStatusUpdaterImpl` heartbeats to the RM and applies
  returned actions; `ContainerManagerImpl` turns start-requests into
  `ContainerImpl` state machines (LOCALIZING→RUNNING→exited);
  `ResourceLocalizationService` fetches resources, `ContainersLauncher` +
  `ContainerExecutor` run them, `ContainersMonitorImpl` enforces limits,
  `AuxServices` and log aggregation hook app/container lifecycle; NM death is
  detected by the RM, NM restart recovers running containers from saved
  launch contexts.
- **End-to-end**: client submit → RM state machines → AM container → AM
  registers → allocate-loop grants containers → NM localizes/launches →
  heartbeat statuses flow back → finish/kill or fail/retry, with state-store
  recovery on RM restart.
- **ApplicationHistoryService**: v1 write-through history store
  (`FileSystemApplicationHistoryStore`) serving finished-app reports and
  logs after RM eviction.
- **TimelineService v2**: per-app collectors (`TimelineCollector`) managed
  RM-side or NM-side (`NodeTimelineCollectorManager` + aux service), flushed
  through `TimelineWriter` SPI to HBase (`HBaseTimelineWriterImpl`) or
  document store; REST readers for entity/flow queries.
- **Router/GPG**: Router = interceptor-chain REST/RPC proxy resolving each
  app's home sub-cluster; GPG = periodic federation policy and hygiene
  daemon; together they present many RMs as one YARN.
- **WebAppProxy**: ACL-checked, attempt-aware reverse proxy to AM UIs with
  fallback to history URLs and `ProxyCA` cert signing.
- **SharedCacheManager**: checksum-deduplicated public resource store
  referenced from `LocalResource`, cleaned by LRU policies.
- **registry/csi/applications**: endpoint discovery (ZK), external volume
  mounting (CSI adaptors), and reference AMs/frameworks (distributedshell,
  unmanaged-AM, services framework) that exercise the full client→RM→NM
  contract.

---

## 17. Concurrency

This section states the threading model each subcomponent actually implements
(all facts checked against source in this checkout). For requirement
derivation: "single-threaded" below means a contract that code must preserve
— a PR that adds blocking I/O or cross-thread mutation inside these paths is
an architecture violation.

### 17.1 The event-bus contract (AsyncDispatcher)

`org.apache.hadoop.yarn.event.AsyncDispatcher` (hadoop-yarn-common) is the one
concurrency primitive YARN is built on:

- A single `BlockingQueue<Event>` (default `LinkedBlockingQueue`) drained by
  **one** `eventHandlingThread` (thread name "AsyncDispatcher event handler").
  One event = one `EventHandler.handle()` call, processed strictly serially.
  The `ThreadPoolExecutor printEventDetailsExecutor` is diagnostic only (it
  prints stuck-event details); it never dispatches events.
- `serviceStart()` spawns the thread; `serviceStop()` sets `stopped`,
  interrupts the handler thread and (when `drainEventsOnStop` is set, the
  RM recovery path uses this) waits for the queue to drain first.
- Consequence: every state machine registered on a dispatcher
  (`RMAppImpl`, `RMAppAttemptImpl`, `RMNodeImpl`, `RMContainerImpl`,
  `ContainerImpl`, ...) must assume its transitions never interleave, and
  must never perform blocking I/O inside an event handler — a slow handler
  stalls the whole daemon's event flow.

Queues that exist (one `AsyncDispatcher` instance per queue, registered event
types observed in source):

| Daemon / component | Dispatcher registers (verified in source) |
|---|---|
| ResourceManager main dispatcher | `SchedulerEventType`, `NodesListManagerEventType`, `RMNodeEventType`, `RMAppEventType`, `RMAppAttemptEventType` (`ResourceManager.createDispatcher()` wiring, lines ~489–524); the RM's sub-services additionally register `RMContainerEventType`, `AMLauncherEventType`, `RMAppManagerEvent` and `RMFatalEvent` handlers on the same bus |
| NodeManager dispatcher | `ContainerManagerEventType` (registered on the `NodeManager` level dispatcher, `NodeManager` line ~472), plus `NodeManagerEvent`, `ContainersLauncherEventType`, `ContainerEventType`, `LocalizationEventType`, `LogHandlerEventType`, `AuxServicesEventType` on the same or component dispatchers per section 8 |
| RM (async scheduler mode) | separate `AsyncScheduleThread`s driven by `AsyncSchedulingConfiguration` (below), not by the main dispatcher |

### 17.2 ResourceManager scheduler concurrency

- **Default (synchronous) mode**: `CapacityScheduler.handle(SchedulerEventType)`
  runs **on the RM dispatcher's single event thread** — node updates
  (`NodeUpdateSchedulerEvent`), app adds/removes and releases are serialized
  with each other. `CapacityScheduler.java` contains **no `synchronized`
  blocks and no internal lock objects**: thread-safety is achieved purely by
  "everything mutates me from the dispatcher thread". Any PR that mutates
  scheduler state from an RPC handler thread must not exist — cross-thread
  input must be funnelled through events.
- The AM-facing `allocate()` calls in `ApplicationMasterService`/
  `DefaultAMSProcessor` run on **RPC handler threads**; they must only read
  scheduler state and post events/return previous allocations, never mutate
  queue structures directly.
- **Async mode** (`yarn.resourcemanager.scheduler.capacity.schedule-asynchronously.enable`,
  `CapacitySchedulerConfiguration.SCHEDULE_ASYNCHRONOUSLY_PREFIX`):
  - inner class `CapacityScheduler.AsyncSchedulingConfiguration` spawns N
    `AsyncScheduleThread`s (N = `.maximum-threads`, default 1) that loop with
    `.scheduling-interval-ms` (default 5 ms) and a `.maximum-pending-backlogs`
    cap;
  - a separate `CapacityScheduler.ResourceCommitterService` (extends
    `Thread`, line ~694) applies multi-node container-commit decisions, so
    proposals and commits run on different threads;
  - each `AsyncScheduleThread` installs `RMCriticalThreadUncaughtExceptionHandler`
    — an uncaught exception turns into `RMFatalEvent`, i.e. fail-fast, not
    silent thread death.
- Note: there is **no `rmAsyncScheduler` flag in trunk**; the async-scheduler
  switch is the capacity-scheduler `schedule-asynchronously.*` key family
  above. (The name `rmAsyncScheduler` appears nowhere in the source tree.)
- Key rolling: `AMRMTokenSecretManager` runs a `MasterKeyRoller` `TimerTask`;
  `DelegationTokenRenewer` runs a `renewerService` `ThreadPoolExecutor` plus a
  `DelegationTokenCancelThread`.

### 17.3 Liveliness/expiry threads

All expiry monitors extend `org.apache.hadoop.yarn.util.AbstractLivelinessMonitor`
(hadoop-yarn-common — not server-common in this checkout): each instance runs
its **own checker thread** ("Ping Checker for <name>") that scans a plain
`HashMap` guarded by `synchronized register/receivedPing/unregister` every
`monitorInterval` (default `expireInterval/3`) and invokes the subclass
`expire()` callback, which posts an expiry event on the dispatcher
(`AMLivelinessMonitor` → `RMAppAttemptEventType.EXPIRE`,
`NMLivelinessMonitor` → `RMNodeEventType.EXPIRE`,
`ContainerAllocationExpirer` → `ContainerExpiredSchedulerEvent` on the
scheduler dispatcher). Monitors must never act on state machine state
directly, only via events.

### 17.4 NodeManager concurrency

| Component | Model (verified) |
|---|---|
| `ContainersLauncher` | `ExecutorService containerLauncher = HadoopExecutors.newCachedThreadPool(...)` — one runnable per container (`ContainerLaunch`, `ContainerRelaunch`, `RecoveredContainerLaunch`, `RecoverPausedContainerLaunch`, `ContainerCleanup`); unbounded by design, bounded by running containers |
| `ResourceLocalizationService` | public path: `createLocalizerExecutor` builds a `newFixedThreadPool(yarn.nodemanager.localizer.fetch.thread-count, default 4)` named "PublicLocalizer #%d"; the inner class `PublicLocalizer` (declared inside `ResourceLocalizationService`, line ~864) extends `Thread` and hands downloads to that pool. Private path: one spawned `ContainerLocalizer` thread/JVM per (user, application). `cacheCleanup` is a `HadoopScheduledThreadPoolExecutor(1)` for cache-dir cleanup |
| `ContainersMonitorImpl` | three dedicated threads: inner `MonitoringThread` (process-tree polling), `LogMonitorThread` (log-dir size monitoring) and, with cGroups elastic-memory control enabled, `CGroupElasticMemoryController` (OOM listener) |
| `NodeStatusUpdaterImpl` | a single `Thread` named "Node Status Updater" running `StatusUpdaterRunnable`; `serviceStop()` `join()`s it (with timeout) so the heartbeat loop never outlives the daemon |
| `DeletionService` | `HadoopScheduledThreadPoolExecutor` (`sched`) executing delayed deletions |
| `NonAggregatingLogHandler` | `ScheduledThreadPoolExecutor` (`sched`) for delayed local log deletion |
| `LogAggregationService` | `ExecutorService threadPool = newFixedThreadPool(getAggregatorThreadPoolSize(conf))`; one `AppLogAggregatorImpl` task per application |

### 17.5 TimelineService v2 collector concurrency

`TimelineCollector` (core module) uses a `ThreadPoolExecutor(1, 1, 3, SECONDS)`
with a `DiscardOldestPolicy` — i.e. **single-threaded flushing with a
back-pressure policy that silently drops the oldest pending flush** when the
writer is slow. `flushBufferedTimelineEntities()` is executed under
`synchronized (writer)` and failures retry with `writeRetryInterval` sleeps.
Requirement-level consequence: entity writes to the backing store are
serialized per collector, and the discard policy means a stalled writer must
be treated as data loss, not queue growth.

### 17.6 Dispatcher shutdown ordering

- `CompositeService` stops children in **reverse registration order**; RM/NM
  register the dispatcher early, so services added after it are stopped first
  and the dispatcher drains last among children.
- `ResourceManager.serviceStop()` (verified order): stop `webApp`, stop the
  delegation-token `fetcher`, close `configurationProvider`, `super.serviceStop()`
  (children incl. dispatcher), close `zkManager`, then
  `transitionToStandby(false)` and set HA state `STOPPING`.
- `NodeManager` starts `NodeStatusUpdaterImpl` **last** (heartbeats only after
  all other services are up), so NM shutdown must also treat the status
  updater as the last-started/first-to-quiesce contact point.
- Any thread with an `RMCriticalThreadUncaughtExceptionHandler` (dispatcher
  thread, `AsyncScheduleThread`s) that dies fatally moves the RM to
  standby/shutdown via `RMFatalEvent` — daemon threads must never be allowed
  to fail silently.

---

## 18. Security

Class names verified against this checkout. Every item is enforceable and
therefore requirement-derivable.

### 18.1 Kerberos principals and keytabs (YarnConfiguration)

| Component | Principal key | Keytab key |
|---|---|---|
| ResourceManager | `yarn.resourcemanager.principal` (`RM_PRINCIPAL`) | `yarn.resourcemanager.keytab` (`RM_KEYTAB`) |
| NodeManager | `yarn.nodemanager.principal` (`NM_PRINCIPAL`) | `yarn.nodemanager.keytab` (`NM_KEYTAB`) |
| WebAppProxy | `yarn.web-proxy.principal` (`PROXY_PRINCIPAL`) | `yarn.web-proxy.keytab` (`PROXY_KEYTAB`) |
| TimelineService | `yarn.timeline-service.principal` (`TIMELINE_SERVICE_PRINCIPAL`) | `yarn.timeline-service.keytab` |
| Router / GPG | `yarn.router.kerberos.principal` / `yarn.federation.gpg.kerberos.principal` | corresponding `.keytab.file` keys (`ROUTER_KEYTAB`, `GPG_KEYTAB`) |
| Web SPNEGO | RM: `yarn.resourcemanager.webapp.spnego-principal`; NM: `yarn.nodemanager.webapp.spnego-principal` | `RM_WEBAPP_SPNEGO_KEYTAB_FILE_KEY` (`...webapp.spnego-keytab-file`), `NM_WEBAPP_SPNEGO_KEYTAB_FILE_KEY` |

- RM/NM web UIs authenticate through `RMAuthenticationFilter` +
  `RMAuthenticationFilterInitializer`
  (`org.apache.hadoop.yarn.server.security.http`, hadoop-yarn-server-common):
  Kerberos (SPNEGO) with delegation-token fallback for web calls.
- `WebAppProxyServer.doSecureLogin()` calls
  `SecurityUtil.login(conf, PROXY_KEYTAB, PROXY_PRINCIPAL, host)` — the proxy
  is a separate Kerberos principal from the RM by design.

### 18.2 Token infrastructure

Token identifiers live in `org.apache.hadoop.yarn.security` (hadoop-yarn-common):
`ContainerTokenIdentifier`, `NMTokenIdentifier`, `AMRMTokenIdentifier`.

Secret managers and their jobs (all verified to exist):

- `RMContainerTokenSecretManager` (RM) — signs container tokens embedded in
  every `Container` record; master key distributed to NMs over the
  `ResourceTracker` channel.
- `NMTokenSecretManagerInRM` (RM) / `NMTokenSecretManagerInNM`
  (`nodemanager/security/`) — the AM's per-node NM tokens that authenticate
  `ContainerManagementProtocol` calls.
- `AMRMTokenSecretManager` (RM) — validates `AMRMToken` on every
  `ApplicationMasterProtocol` call; `MasterKeyRoller` rolls the key and old
  keys stay valid for the current attempts.
- `ClientToAMTokenSecretManagerInRM` — tokens for client→AM calls.
- `RMDelegationTokenSecretManager` — client delegation tokens;
  `DelegationTokenRenewer` renews submitted apps' tokens on their behalf for
  the application lifetime (per-app renewer pool; instantiated only in
  secure mode by `RMActiveServices`, pool sized by
  `yarn.resourcemanager.delegation-token-renewer.thread-count`).
- NM side: `ContainerManagerImpl` validates `NMToken` + container token on
  every `StartContainersRequest`/`StopContainersRequest`/`GetContainerStatusesRequest`
  before any container work happens.

### 18.3 Credential passing at launch

- `ContainerLaunchContext` carries tokens as an opaque `ByteBuffer`
  (`getTokens()`/`setTokens()`) plus `getTokensConf()` for token-conf
  (credential-provider) settings — there is no `Credentials` field on the
  record; the bytes **are** a serialized `org.apache.hadoop.security.Credentials`.
- AM launch: `AMLauncher` (RM side) builds the AM container spec, deserializing
  the token buffer into a `Credentials` object (`AMLauncher.java` ~line 228)
  and adding the AMRMToken before sending via `ContainerManagementProtocol`.
- User containers: the AM serializes only the credentials that container
  needs into its `ContainerLaunchContext`; the NM merges/validates via
  `NMTokenSecretManagerInNM`. Delegation tokens the app depends on (e.g.
  HDFS) must have been renewed by `DelegationTokenRenewer` for the app
  duration.

### 18.4 YARN ACLs

- `ApplicationACLsManager` (`org.apache.hadoop.yarn.server.security`,
  hadoop-yarn-common) implements `checkAccess(UserGroupInformation, ApplicationAccessType, ...)`;
  `ApplicationAccessType` (`VIEW_APP`, `MODIFY_APP`) is an api-records enum,
  `QueueACL` likewise. ACL enablement is `yarn.acl.enable` (**default false**)
  and admin ACL `yarn.admin.acl` (**default `*`**) — enforced by `AdminService`
  and `ClientRMService`.
- Queue-level authorization: `QueueACLsManager` plus scheduler-specific
  implementations `CapacityQueueACLsManager`, `FairQueueACLsManager`,
  `GenericQueueACLsManager`; priority ACLs via `AppPriorityACLsManager`;
  reservation ACLs via `ReservationsACLsManager`,
  `CapacityReservationsACLsManager`, `FairReservationsACLsManager`
  (all under `resourcemanager/security/`).
- `WebAppProxyServlet` must check `ApplicationAccessType.VIEW_APP` (via the
  `AppReportFetcher` path) before reverse-proxying an AM UI — section 13.

### 18.5 LinuxContainerExecutor and the setuid binary

- `LinuxContainerExecutor` (top-level `nodemanager/` package) delegates all
  privileged work through `PrivilegedOperation`/`PrivilegedOperationExecutor`
  (`containermanager/linux/privileged/`) which execs the setuid
  **container-executor** binary built from
  `hadoop-yarn-server-nodemanager/src/main/native/container-executor/impl/container-executor.c`,
  configured by `conf/container-executor.cfg` (the binary validates the
  config file's ownership/permissions itself).
- Selected via `yarn.nodemanager.container-executor.class`
  (`NM_CONTAINER_EXECUTOR`); binary path
  `yarn.nodemanager.linux-container-executor.path`
  (`NM_LINUX_CONTAINER_EXECUTOR_PATH`).
- Non-secure mode: containers run as
  `yarn.nodemanager.linux-container-executor.nonsecure-mode.local-user`
  (bounded by `.nonsecure-mode.limit-users` and `.nonsecure-mode.user-pattern`);
  in secure mode the container **must** run as the submitting user — user
  isolation is the whole point of the setuid binary.
- Container runtime selection inside the executor: `YARN_CONTAINER_RUNTIME_TYPE`
  (`ContainerRuntimeConstants.ENV_CONTAINER_TYPE`) chooses between
  `DefaultLinuxContainerRuntime`, `DockerLinuxContainerRuntime`,
  `RuncContainerRuntime` and `JavaSandboxLinuxContainerRuntime`, wired through
  `DelegatingLinuxContainerRuntime`; `OCIContainerRuntime` is the shared
  OCI base class. Docker/runc isolation is therefore an NM-level
  (not RM-level) behaviour.

### 18.6 cGroups handling

- Handlers under `containermanager/linux/resources/`:
  `CGroupsHandler`/`CGroupsHandlerImpl` (cgroups v1) and `CGroupsV2HandlerImpl`
  (v2, off by default — `yarn.nodemanager.linux-container-executor.cgroups-v2.enabled`
  default false); memory: `CGroupsMemoryResourceHandlerImpl` /
  `CGroupsV2MemoryResourceHandlerImpl`; cpu: `CGroupsCpuResourceHandlerImpl` /
  `CGroupsV2CpuResourceHandlerImpl`; blkio: `CGroupsBlkioResourceHandlerImpl`.
  `AbstractCGroupsResourceCalculator`/`CGroupsResourceCalculator`/
  `CGroupsV2ResourceCalculator` read per-container usage.
- `CGroupsHandler.CGroupController` enum: v1-only `NET_CLS`, `BLKIO`,
  `CPUACCT`, `FREEZER`, `DEVICES`; v2-only `IO`; both `CPU`, `CPUSET`,
  `MEMORY`. There is **no** `CGroupsDevicesResourceHandlerImpl` in trunk —
  device access is delegated to the container runtime (e.g. Docker device
  flags) and to the GPU/FPGA plugins `GpuResourceHandlerImpl`/
  `FpgaResourceHandlerImpl` (with `GpuResourceAllocator`/
  `FpgaResourceAllocator`).
- Mount config keys: `yarn.nodemanager.linux-container-executor.cgroups.hierarchy`,
  `.cgroups.mount`, `.cgroups.mount-path`, `.cgroups-v2.mount-path`,
  `.cgroups.strict-resource-usage`, plus memory swappiness /
  soft-limit-percentage keys and cgroups delete delay/timeout keys.

### 18.7 TimelineService v2 auth

- Collector/reader REST endpoints authenticate via
  `TimelineAuthenticationFilter` + `TimelineAuthenticationFilterInitializer`
  (`org.apache.hadoop.yarn.server.timeline.security`, hadoop-yarn-server-common)
  for the collector and `TimelineReaderAuthenticationFilterInitializer`
  (`timelineservice/reader/security/`) for the reader — Kerberos/SPNEGO with
  delegation-token support, using `yarn.timeline-service.principal`/keytab.
- The collector web service binds
  `yarn.timeline-service.collector.webapp.address` (defaults to the reader
  webapp address, 8188).

---

## 19. Logging and auditability

### 19.1 Audit logs

- **`RMAuditLogger`** (`resourcemanager/RMAuditLogger.java`): SLF4J logger
  named for the class (typically routed to `resourcemanager-audit.log` by
  log4j config); record format is tab-separated `key=value` pairs
  (`KEY_VAL_SEPARATOR = '='`, `PAIR_SEPARATOR = '\t'`) with
  `SUCCESS`/`FAILURE` markers. Verified event constants in `AuditConstants`:
  `SUBMIT_APP_REQUEST`, `KILL_APP_REQUEST`, `FAIL_ATTEMPT_REQUEST`,
  `MOVE_APP_REQUEST`, `GET_APP_STATE`, `GET_APP_PRIORITY`, `GET_APP_QUEUE`,
  `GET_APP_ATTEMPTS`, `GET_APP_REPORT`, `GET_APP_ATTEMPT_REPORT`,
  `GET_CONTAINERS`, `GET_CONTAINER_REPORT`, `GET_QUEUE_INFO_REQUEST`, ...
  Call sites (verified): `ClientRMService`, `RMAppManager`, `RMAppImpl`,
  `ApplicationMasterService`, `DefaultAMSProcessor`, `AbstractYarnScheduler`,
  `FiCaSchedulerApp`/`FSAppAttempt` (container allocation/launch audit),
  `ReservationInputValidator`.
- **`NMAuditLogger`** (`nodemanager/NMAuditLogger.java`): same format;
  called from `ContainerManagerImpl` and `ContainerImpl` (container
  start/finish audit).
- **`RouterAuditLogger`** (router module): audits forwarded client calls
  through `RouterClientRMService`.
- Requirement framing: every state-changing client operation (submit, kill,
  move, fail-attempt, container allocation/launch) must produce exactly one
  audit record naming caller UGI, application/attempt/container IDs and the
  operation constant; read operations on app reports are auditable events
  too (the GET_* constants above exist for that purpose).

### 19.2 Log aggregation flow (verified classes)

1. App finishes → `ContainerManagerImpl` notifies the configured
   `LogHandler`: `NonAggregatingLogHandler` (retain + scheduled local delete)
   or `LogAggregationService`.
2. `LogAggregationService` submits an `AppLogAggregatorImpl` task to its fixed
   thread pool; the aggregator collects container logs (honouring
   `ContainerLogAggregationPolicy` for selective aggregation) and uploads
   them through the **`LogAggregationFileController` SPI** to the remote
   file system.
3. Two controller implementations ship:
   `LogAggregationTFileController` (writes the classic TFile-based
   `AggregatedLogFormat`) and `LogAggregationIndexedFileController`
   (indexed "ifile" format for faster per-container lookup); selection via
   `LogAggregationFileControllerFactory`.
4. `NMLogAggregationStatusTracker` reports per-app aggregation status to the
   RM so the RM UI can show whether logs have been aggregated.

Requirement framing: an aggregated log file must be readable per
(container, application) with the chosen controller's reader, and the RM must
be able to report aggregation status for every finished app.

### 19.3 Metrics

- `QueueMetrics` (`resourcemanager/scheduler/QueueMetrics.java`,
  `@Metrics(context="yarn")`) — per-queue and per-app counters; created via
  `DefaultMetricsSystem`.
- `ClusterMetrics` (RM) — cluster-level counters (apps submitted/running/
  failed, nodes, container allocations).
- `ContainerMetrics` (NM, `containermanager/monitor/`) — per-container metrics
  published by `ContainersMonitorImpl`.
- `JvmMetrics` from hadoop-common's metrics2: RM calls
  `JvmMetrics.initSingleton("ResourceManager", null)` (and re-attaches on
  transition), giving process/JVM metrics in the same metrics2 system.
- All YARN daemons register through hadoop-common `DefaultMetricsSystem`;
  the `yarn` metrics context is the filter key for sinks.

### 19.4 TimelineService as audit trail

- `RMApplicationHistoryWriter` (RM) writes app/attempt lifecycle events as
  timeline entities through the `TimelineWriter` SPI — a durable,
  queryable audit record of state-machine transitions independent of the
  audit log.
- `AppLevelTimelineCollector` buffers AM-reported events/metrics and flushes
  them (section 17.5) — the per-application audit stream for user-level
  activity, queryable via the reader REST API.

---

## 20. Integration points

### 20.1 Protocols and ports (all defaults from `YarnConfiguration`)

| Protocol / endpoint | Config key | Default | Bound by |
|---|---|---|---|
| `ApplicationClientProtocol` | `yarn.resourcemanager.address` (`RM_ADDRESS`) | 0.0.0.0:8032 | `ClientRMService` |
| `ApplicationMasterProtocol` | `yarn.resourcemanager.scheduler.address` (`RM_SCHEDULER_ADDRESS`) | 0.0.0.0:8030 | `ApplicationMasterService` |
| `ResourceTracker` | `yarn.resourcemanager.resource-tracker.address` (`RM_RESOURCE_TRACKER_ADDRESS`) | 0.0.0.0:8031 | `ResourceTrackerService` |
| RM admin (`RMAdminProtocol`) | `yarn.resourcemanager.admin.address` | 0.0.0.0:8033 | `AdminService` |
| RM web UI | `yarn.resourcemanager.webapp.address` | 0.0.0.0:8088 | RM web app |
| `ContainerManagementProtocol` | `yarn.nodemanager.address` (`NM_ADDRESS`) | 0.0.0.0:0 (ephemeral) | `ContainerManagerImpl` |
| NM localizer | `yarn.nodemanager.localizer.address` | 0.0.0.0:8040 | `ResourceLocalizationService` |
| NM web UI | `yarn.nodemanager.webapp.address` | 0.0.0.0:8042 | NM web app |
| AMRMProxy | (AMRM proxy prefix, `DEFAULT_AMRM_PROXY_PORT`) | 8049 | `AMRMProxy` auxiliary service |
| ATS (v1 AHS client service binds this too) | `yarn.timeline-service.address` | 0.0.0.0:10200 | `ApplicationHistoryClientService` / timeline reader |
| ATS web | `yarn.timeline-service.webapp.address` | 0.0.0.0:8188 | reader/collector web services (`yarn.timeline-service.collector.webapp.address` defaults to it) |
| Router `ApplicationClientProtocol` proxy | `yarn.router.clientrm.address` | 0.0.0.0:8050 | `RouterClientRMService` |
| Router web | (router webapp key) | 8089 | Router web app |
| WebAppProxy | `yarn.web-proxy.address` (`PROXY_ADDRESS`) | 0.0.0.0:9099 | `WebAppProxyServer` |

Wire format: all four core protocols are protobuf-based (section 3/4); the
`ClientSCMProtocol` (shared cache, `ClientProtocolService`) and
`CsiAdaptorProtocol` are additional RPC surfaces.

### 20.2 OS/runtime integrations

- **cGroups**: mounted/configured per section 18.6; the NM requires either
  the cgroups handler (`yarn.nodemanager.linux-container-executor.resources-handler.class`)
  or falls back to process-tree enforcement (`ContainersMonitorImpl` +
  `ResourceCalculatorProcessTree`).
- **Container runtimes**: Docker (`DockerLinuxContainerRuntime`), runc
  (`RuncContainerRuntime`), sandboxed Java (`JavaSandboxLinuxContainerRuntime`)
  — selected per container via the `YARN_CONTAINER_RUNTIME_TYPE`
  environment variable; all executed through the setuid
  container-executor binary path.
- **Devices**: GPU/FPGA exposure via `GpuResourceHandlerImpl`/
  `FpgaResourceHandlerImpl` (cgroups devices are not managed by a dedicated
  trunk handler — see 18.6); CSI volumes via the `hadoop-yarn-csi` adaptors
  (section 15).
- **Registry (ZooKeeper)**: in this checkout `hadoop-yarn-registry` is an
  empty shell module (pom.xml only); the implementation classes live in
  **`hadoop-common-project/hadoop-registry`** —
  `org.apache.hadoop.registry.client.api.RegistryOperations` /
  `RegistryOperationsFactory`, ZK binding under
  `org.apache.hadoop.registry.client.impl.zk` (incl. `RegistrySecurity` for
  ZK ACLs/sasl). YARN services (hadoop-yarn-services-core `registry` package)
  publish/read endpoints through this API for service discovery.

### 20.3 Configuration key families

- `yarn.resourcemanager.*` — address/keytab/principal, scheduler
  (`yarn.resourcemanager.scheduler.capacity.*` incl. the
  `schedule-asynchronously.*` keys), HA, delegation-token renewal,
  webapp SPNEGO keys.
- `yarn.nodemanager.*` — address/localizer/webapp, container-executor class
  and linux-container-executor keys (path, nonsecure-mode.*, resources-handler,
  cgroups.*), localizer fetch thread count, recovery (`yarn.nodemanager.recovery.enabled`),
  aux-services.
- `yarn.timeline-service.*` — enable, address, principal/keytab, collector
  reader/writer store class names.
- Depth-3 additions from the internal-structure sections:
  `yarn.resourcemanager.amlauncher.thread-count`,
  `yarn.resourcemanager.delegation-token-renewer.thread-count`,
  `yarn.resourcemanager.am-rm-tokens.master-key-rolling-interval-secs`,
  `yarn.resourcemanager.store.class`,
  `yarn.resourcemanager.application-master-service.processors`,
  `yarn.nodemanager.container-monitor.interval-ms`,
  `yarn.nodemanager.localizer.cache.cleanup.interval-ms`,
  the `yarn.federation.gpg.*` family (scheduled executor threads,
  subcluster/application cleaner intervals, policy generator interval).
- Every key above is declared with its default in `YarnConfiguration`
  (hadoop-yarn-api), which is the single source of truth for config-name
  compatibility checks in PR review.

---

## 21. Non-functional requirement candidates

Testable statements derived from the verified behaviour above. Each names its
enforcing classes; "must/never/should" reflects how the code behaves today
(must = enforced invariant, should = designed behaviour without hard
enforcement).

1. Every `RMAppImpl`/`RMAppAttemptImpl`/`RMNodeImpl`/`RMContainerImpl` state
   transition must execute serially on the RM `AsyncDispatcher`'s single
   handler thread; handlers must never block on I/O or remote calls.
2. `CapacityScheduler` must contain no internal locks: in the default mode
   all queue-tree mutation must happen on the RM dispatcher thread
   (`SchedulerEventType` handlers), and RPC threads
   (`ApplicationMasterService.allocate`) must never mutate scheduler state
   directly.
3. When `yarn.resourcemanager.scheduler.capacity.schedule-asynchronously.enable`
   is true, scheduling must be performed only by
   `CapacityScheduler.AsyncScheduleThread`s with commit decisions applied by
   `ResourceCommitterService`; the pending backlog must be capped at
   `.maximum-pending-backlogs`.
4. Any uncaught exception on the RM dispatcher thread or an
   `AsyncScheduleThread` must trigger `RMFatalEvent` and move the RM to
   standby/shutdown (`RMCriticalThreadUncaughtExceptionHandler`) — never
   silent thread death.
5. `AsyncDispatcher` must log event-queue size growth (it tracks
   `lastEventQueueSizeLogged`); a requirement candidate: queue depth above a
   configured threshold must be reported in daemon metrics/logs.
6. `ApplicationMasterService.allocate()` must complete in bounded time per
   heartbeat (dispatches work, returns prior allocations); it must never be
   executed on the scheduler dispatch thread.
7. Each running NM container must be owned by exactly one
   `ContainersLauncher` task at a time (cached thread pool; tasks:
   `ContainerLaunch`, `ContainerRelaunch`, `RecoveredContainerLaunch`,
   `ContainerCleanup`).
8. Public resource localization must use a fixed pool of
   `yarn.nodemanager.localizer.fetch.thread-count` (default 4) threads
   ("PublicLocalizer #%d", `ResourceLocalizationService.createLocalizerExecutor`);
   private localization must run one `ContainerLocalizer` per (user, app).
9. `ContainersMonitorImpl.MonitoringThread` must poll each running container's
   process tree at the configured interval and must kill (post
   `ContainerExitEvent`) any container exceeding its memory limits;
   `LogMonitorThread` must monitor log directory sizes.
10. The NM heartbeat loop must be the single "Node Status Updater" thread
    (`NodeStatusUpdaterImpl`); NM shutdown must `join()` it before the
    dispatcher stops.
11. Every liviness/expiry monitor (`AbstractLivelinessMonitor` subclasses:
    `AMLivelinessMonitor`, `NMLivelinessMonitor`, `AMFinishingMonitor`,
    `ContainerAllocationExpirer`) must run its own checker thread and fire
    expiry **events** on the dispatcher, never mutate state-machine state
    directly.
12. RM shutdown must stop, in order: web app, delegation-token fetcher,
    configuration provider, then all composite children (dispatcher last),
    then `transitionToStandby(false)` (`ResourceManager.serviceStop`).
13. `TimelineCollector` flushes must be serialized per collector
    (single-thread pool + `synchronized(writer)`); a failed flush must retry
    with `writeRetryInterval` and the `DiscardOldestPolicy` must be treated
    as acceptable data-loss under writer stall — a PR changing flush
    concurrency must preserve per-collector ordering.
14. RM, NM, WebAppProxy, TimelineService, Router and GPG must each log in
    with their configured principal/keytab (`yarn.resourcemanager.principal`,
    `yarn.nodemanager.principal`, `PROXY_PRINCIPAL`/`PROXY_KEYTAB`,
    `TIMELINE_SERVICE_PRINCIPAL`, router/GPG equivalents);
    `WebAppProxyServer.doSecureLogin` must use `SecurityUtil.login`.
15. `ContainerManagerImpl` must validate NMToken **and** container tokens on
    every `ContainerManagementProtocol` request before container work
    (`NMTokenSecretManagerInNM`); requests failing validation must be
    rejected without side effects.
16. `AMRMTokenSecretManager` must roll its master key (`MasterKeyRoller`) and
    must keep the previous key valid for existing attempts; every
    `ApplicationMasterProtocol` call must present a valid AMRMToken.
17. A submitted application's tokens must reach the AM container as a
    serialized `Credentials` inside `ContainerLaunchContext`'s token buffer
    (`AMLauncher` deserialization), and `DelegationTokenRenewer` must renew
    them for the application's lifetime.
18. When `yarn.acl.enable` is true, every client operation must pass
    `ApplicationACLsManager.checkAccess` (or the scheduler-specific
    `*QueueACLsManager`), and admin operations must pass `yarn.admin.acl`;
    `WebAppProxyServlet` must enforce `VIEW_APP` before proxying.
19. With `LinuxContainerExecutor`, containers must execute under the
    submitting user's identity via the setuid container-executor binary
    (`PrivilegedOperationExecutor`); the binary must validate
    `container-executor.cfg` permissions at startup. In non-secure mode all
    containers must run as `...nonsecure-mode.local-user`.
20. cGroups handlers must only use controllers valid for the configured
    version (`CGroupsHandler.CGroupController`: v1-only NET_CLS/BLKIO/
    CPUACCT/FREEZER/DEVICES, v2-only IO); v2 must stay disabled unless
    `yarn.nodemanager.linux-container-executor.cgroups-v2.enabled` is set.
21. `RMAuditLogger`/`NMAuditLogger` must emit one tab-separated `key=value`
    audit record per state-changing operation (submit/kill/move/fail-attempt;
    container start/finish) with SUCCESS/FAILURE and full identifier chain
    (app/attempt/container).
22. Finished applications' container logs must be aggregated through the
    configured `LogAggregationFileController` (TFile or indexed-ifile) and
    `NMLogAggregationStatusTracker` must report aggregation status back to
    the RM for every finished app.
23. Protocol endpoints must remain configurable through the
    `yarn.resourcemanager.*`/`yarn.nodemanager.*` address keys with the
    documented defaults (8032/8030/8031/8033, 8040/8042, 10200/8188,
    8050/8089, 9099); a PR changing a protocol binding must not move the
    default port.
24. `YARN_CONTAINER_RUNTIME_TYPE` must select among
    `DefaultLinuxContainerRuntime`, `DockerLinuxContainerRuntime`,
    `RuncContainerRuntime`, `JavaSandboxLinuxContainerRuntime` via
    `DelegatingLinuxContainerRuntime`; the RM must never be involved in
    runtime selection (it is purely an NM-side decision).
25. YARN long-running services should publish their endpoints to the
    ZooKeeper-backed registry (`org.apache.hadoop.registry.client.api.RegistryOperations`,
    hadoop-registry module) so peers can discover them without direct
    configuration.
