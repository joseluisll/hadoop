# Apache HDFS Requirements (hadoop-hdfs-project)

<!--
SPDX-License-Identifier: Apache-2.0
-->

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

**Status:** DRAFT
**Date:** 2026-11-14
**Source doc:** `notes/architecture/hadoop-hdfs-architecture.md` (trunk, verified against
the source tree under `hadoop-hdfs-project/`)

---

## Scope and derivation method

This document turns the HDFS architecture orientation document into checkable
requirements for PR review. A reviewer reading a proposed diff must be able to
say "this satisfies/violates FR-7" — every requirement below is a single,
falsifiable rule with a stable ID and a citation to the architecture section
(`arch §n[.m]`) plus the key class that enforces it.

- **Scope:** the six modules of `hadoop-hdfs-project` (`hadoop-hdfs`,
  `hadoop-hdfs-client`, `hadoop-hdfs-rbf`, `hadoop-hdfs-httpfs`,
  `hadoop-hdfs-nfs`, `hadoop-hdfs-native-client`) and their first-level
  subsystems under `org.apache.hadoop.hdfs.server.*`.
- **Derivation:** functional requirements (FR-x) come from arch §§2–8;
  non-functional requirements from §9 (concurrency → `NFR-C-x`), §10
  (security → `NFR-S-x`), §11 (logging → `NFR-L-x`), §12 (integration →
  `NFR-I-x`).
- **Mapping of arch §13:** the NFR candidates (`R-NFR-1` … `R-NFR-25`) are
  carried over and **superseded** by the IDs below (mapping table at the end
  of §2; none dropped). A few additional requirements (marked "derived from
  arch §…" without an R-NFR number) come from §§10.7, 11.4, 12.1–12.3.
- **No invented behaviour:** only statements derivable from the architecture
  doc or verifiable in this checkout's source are included.

ID conventions: `FR-x` functional, `NFR-C-x` concurrency, `NFR-S-x` security,
`NFR-L-x` logging/auditability, `NFR-I-x` integration.

---

## 1. Functional requirements

### 1.1 NameNode namespace, FSImage and FSEditLog (arch §2.1)

- **FR-1 — Namespace authority.** All namespace and per-file metadata
  (permissions, quotas, EC policy, encryption zones) must be authoritative
  only in the NameNode; block *content* must live only on DataNodes. (arch §2.1, `FSNamesystem`)
- **FR-2 — Mutation discipline.** A namespace-mutating RPC must acquire the
  namesystem write lock, mutate the `INode` tree via the per-op helper
  (`FSDir*Op`), and append a corresponding `FSEditLogOp` that fans out to all
  journals, returning only once the required number have synced. (arch §2.1, `FSNamesystem`, `FSDirWriteFileOp`, `FSEditLog`)
- **FR-3 — Restart recovery.** On restart the NameNode must load the latest
  fsimage and replay subsequent edit segments through `FSEditLogLoader` to
  rebuild the `INode` tree before serving RPCs. (arch §2.1, `FSImage`, `FSEditLogLoader`)
- **FR-4 — INode feature storage.** ACLs (`AclFeature`), XAttrs
  (`XAttrFeature`), quotas (`DirectoryWithQuotaFeature`), symlinks and
  snapshot references (`INodeReference`) must remain stored via
  `INodeWithAdditionalFields` / the `INode` hierarchy; a PR must not move
  these to ad-hoc side tables. (arch §2.1, `INodeWithAdditionalFields`)
- **FR-5 — Storage retention.** Old fsimages and edit segments must be purged
  by `NNStorageRetentionManager` only once a newer checkpoint exists. (arch §2.1, `NNStorageRetentionManager`)

- **FR-50 — INode-tree coherence.** Namespace lookups and mutations must go
  through `INodesInPath` (the INode array down the path); the id → INode
  `inodeMap` is coherent only while the namesystem lock is held ("Synchronized
  by dirLock"), and `markNameCacheInitialized()` must fire only once safemode
  population completes. (arch §2.1 "FSDirectory and the INode tree", `FSDirectory`, `INodesInPath`)
- **FR-51 — Save/roll pairing.** A namespace save (`FSImage.saveNamespace`)
  must run under a `SaveNamespaceContext`, serialize the tree via
  `FSImageFormatProtobuf`/`FSImageFormatPBINode` into `fsimage_<txId>`, promote
  it over the old image, and roll the edit log
  (`FSEditLog.startLogSegment`/`startLogSegmentAndWriteHeaderTxn`); a PR must
  not break the promote-and-roll pairing. (arch §2.1 "FSImage, NNStorage and the fsimage format", `FSImage`)
- **FR-52 — Namesystem service startup.** `FSNamesystem.startCommonServices`
  must start the BlockManager services, `LeaseManager.startMonitor()`, the
  `NameNodeResourceMonitor` daemon and `CacheManager.startMonitorThread()`;
  a new namesystem service must hook into this activation path, not into
  ad-hoc constructors. (arch §2.1 #### `FSNamesystem`, `FSNamesystem.startCommonServices`)
- **FR-53 — Per-op helper coverage.** Each namespace operation family (append,
  truncate, concat, ACL, XAttr, snapshot, EC, encryption zone, storage policy,
  …) must remain a static method on its own `FSDir*Op` helper with the
  `FSEditLog.log*` call interleaved; a new op must not mutate the namespace
  outside an `FSDir*Op`. (arch §2.1 "FSDirectory and the INode tree", `FSDirWriteFileOp`)

### 1.2 Block management (arch §2.2)

- **FR-6 — BlocksMap as truth.** The NameNode's record of block → replica
  locations must remain `BlocksMap` (block → `BlockInfo`/`BlockInfoStriped`,
  referencing the `BlockCollection` inode), backed by `LightWeightGSet`. (arch §2.2, `BlocksMap`)
- **FR-7 — Block report diffing.** `BlockManager.processReport()` must diff a
  DataNode's reported replica set against `BlocksMap`, recording extra/stale
  replicas in `InvalidateBlocks` and missing replicas in
  `LowRedundancyBlocks`. (arch §2.2, `BlockManager.processReport`)
- **FR-8 — Reconstruction delivery.** Reconstruction work computed by
  `computeDatanodeWork()` must be delivered as first-block commands in the
  next heartbeat (`DatanodeCommand`), with DataNodes copying via the
  inter-DataNode `OP_TRANSFER_BLOCK` path. (arch §2.2, §9.3, `BlockManager.computeDatanodeWork`)
- **FR-9 — Corrupt-replica handling.** Blocks reported corrupt must go to
  `CorruptReplicasMap`; healthy replicas of those blocks must be invalidated
  and reconstruction queued when good replicas drop below policy. (arch §2.2, `CorruptReplicasMap`, `InvalidateBlocks`)
- **FR-10 — Placement policy.** New replica placement must go through a
  `BlockPlacementPolicy` (default: writer-local + off-rack
  `BlockPlacementPolicyDefault`), selected via `BlockPlacementPolicies`; a PR
  must not hardcode placement outside the policy. (arch §2.2, `BlockPlacementPolicyDefault`)
- **FR-11 — Block id allocation.** Legacy vs striped block ids must be
  allocated through `BlockIdManager` (`SequentialBlockIdGenerator`), not
  ad-hoc. (arch §2.2, `BlockIdManager`)
- **FR-12 — Decommissioning.** Node decommissioning must be tracked and
  completed via `DatanodeAdminManager` and the `DatanodeAdmin*Monitor`
  classes, using per-node replication queues on `DatanodeDescriptor`. (arch §2.2, `DatanodeAdminManager`)
- **FR-13 — Safemode block accounting.** Startup safemode must count safe
  blocks per storage via `BlockManagerSafeMode`
  (`incrementSafeBlockCount`, `blockTotal`/`blockSafe`) and gate
  reconstruction until enough block reports have arrived. (arch §2.2, §2.3, `BlockManagerSafeMode`)

- **FR-54 — LocatedBlock assembly.** `getBlockLocations`/`addBlock` responses
  must be assembled by `LocatedBlockBuilder` (block tokens, storage IDs/types
  included); a PR must not hand-build `LocatedBlock`s outside it.
  (arch §2.2 "BlocksMap and block state", `LocatedBlockBuilder`)
- **FR-55 — Host registry sources.** DataNode host lists must be resolved
  through `HostFileManager`/`CombinedHostFileManager`/`HostConfigManager`,
  with stale/dead windows from `DatanodeManager.staleInterval`;
  decommissioning stays in `DatanodeAdminManager` with
  `DatanodeAdminDefaultMonitor`/`DatanodeAdminBackoffMonitor` monitor threads.
  (arch §2.2 "DatanodeManager and HeartbeatManager", `DatanodeManager`)
- **FR-56 — HeartbeatManager accounting.** `HeartbeatManager` must register
  live nodes, compute `DatanodeStats` (capacity/usage aggregation), and expire
  silent nodes via its inner `Monitor` daemon (`heartbeatCheck()`), triggering
  dead-node handling. (arch §2.2 "DatanodeManager and HeartbeatManager", `HeartbeatManager`)
- **FR-57 — Centralized caching.** Cache directives/pools must stay in
  `CacheManager` with `CacheReplicationMonitor` (started by
  `CacheManager.startMonitorThread()`) reconciling cached block sets and
  issuing `DNA_CACHE`/`DNA_UNCACHE` heartbeat commands.
  (arch §2.2 "Invalidation, corruption and caching", `CacheManager`, `CacheReplicationMonitor`)
- **FR-58 — Redundancy accounting.** Over-replication must be recorded in
  `ExcessRedundancyMap`, live-replica counting for deficit math must go
  through `NumberReplicas` (per state), and corrupt-report triage must produce
  `BlockToMarkCorrupt` entries into `CorruptReplicasMap`.
  (arch §2.2 "Invalidation, corruption and caching", `BlockManager`, `NumberReplicas`)

### 1.3 Leases and safemode (arch §2.3)

- **FR-14 — Single writer per file.** Every open-for-write file must be owned
  by exactly one `Lease` keyed by client name, tracked by `LeaseManager` in
  renewal-time order; concurrent writers to the same file must be rejected. (arch §2.3, `LeaseManager`)
- **FR-15 — Lease recovery.** On lease expiry (client crash or hard-limit
  timeout), the lease monitor must trigger `internalReleaseLease` so the last
  block is finalized or abandoned; closing the file must remove the lease via
  `removeLease`. (arch §2.3, `LeaseManager`, `FSNamesystem.internalReleaseLease`)
- **FR-16 — Safemode read-only.** While in safemode, mutating RPCs must fail
  with `SafeModeException` via `FSNamesystem.checkNameNodeSafeMode()` until
  `leaveSafeMode()` (automatic or `-safemode leave`); safemode entry must
  require both the block threshold and passing resource checks
  (`NameNodeResourceChecker`/`NameNodeResourcePolicy`). (arch §2.3, `FSNamesystem`, `NameNodeResourceChecker`)

### 1.4 HA: active/standby, ZKFC, QJM, JournalNode (arch §2.4, §2.6)

- **FR-17 — Standby behaviour.** A standby NameNode must replay edits
  (`EditLogTailer`) and checkpoint (`StandbyCheckpointer`) but serve no
  namespace mutations and issue no block work. (arch §2.4, `EditLogTailer`, `StandbyCheckpointer`)
- **FR-18 — Quorum edit writes.** In HA, every edit must be sent in parallel
  to all JournalNodes via `QuorumJournalManager`/`AsyncLoggerSet` and
  acknowledged only on a `QuorumCall` majority (`QuorumException` otherwise). (arch §2.4, `QuorumJournalManager`)
- **FR-19 — Segment recovery on failover.** During failover the new active
  must finalize/recover the latest journal segment consistently across all
  journals (`SegmentRecoveryComparator`,
  `finalizeLogSegment`/`recoverUnfinalizedSegments`). (arch §2.4, `QuorumJournalManager`)
- **FR-20 — ZKFC failover order.** Failover must follow the sequence:
  active's ZKFC detects failure → old active is fenced (RPC ACL and/or
  configured fence method) → standby's ZKFC acquires the ephemeral znode →
  `transitionToActive`. The new active becomes writable only after QJM
  segment recovery. (arch §2.4, `DFSZKFailoverController`, `ActiveStandbyElector`)
- **FR-21 — DataNode re-targeting.** DataNodes register with all NameNodes of
  their nameservices from startup (`BPOfferService`/`BPServiceActor`) and
  must switch heartbeats/commands to the new active after failover. (arch §2.4, §2.7, `BPOfferService`)
- **FR-22 — Standby bootstrap.** A new standby's storage must be initialized
  from the active's fsimage via `BootstrapStandby`/`TransferFsImage`. (arch §2.4, `BootstrapStandby`, `TransferFsImage`)
- **FR-23 — Checkpointing.** Checkpointing must merge fsimage + edit tail
  (`SecondaryNameNode` in non-HA via `NamenodeProtocol`, `StandbyCheckpointer`
  in HA), upload the new fsimage (`TransferFsImage`), and use the
  `CheckpointSignature` handshake to make the NameNode roll its edit log —
  bounding edit-log replay time after restart. (arch §2.6, `SecondaryNameNode`, `StandbyCheckpointer`)

- **FR-59 — HA state-machine serialization.** HA state entry/exit must
  serialize against namespace mutations (`HAState.setStateInternal` calls
  `context.writeLock()`), and `checkOperation(OperationCategory)` must reject
  writes on standby/observer with `StandbyException`.
  (arch §2.4 "NameNode HA state machine", `HAState`, `HAContext`)
- **FR-60 — JournalNode server contract.** Each journal-id must persist to
  `JNStorage` (`dfs.journalnode.edits.dir`; `current/` segments, `paxos/`
  recovery state), accept only epoch/current-txn-ordered writes
  (`NewerTxnIdException` otherwise), and serve segment reads to standbys and
  checkpointers via `GetJournalEditServlet`, with recent edits cached in
  `JournaledEditsCache`. (arch §2.4 "JournalNode (server)", `Journal`, `JNStorage`)
- **FR-61 — Tailer roll executor.** `EditLogTailer` must run its
  `EditLogTailerThread` plus a single-thread `rollEditsRpcExecutor` (bounded by
  `rollEditsTimeoutMs`) that asks the active to roll edits so the standby can
  tail closed segments. (arch §2.4 "Standby services: EditLogTailer and StandbyCheckpointer", `EditLogTailer`)
- **FR-62 — BackupNode role.** `BackupNode` (with
  `BackupImage`/`BackupJournalManager`) must receive edits streamed over
  `JournalProtocol`, keep a full in-memory namespace replica, and remain able
  to perform checkpoints for the active. (arch §2.6 "BackupNode", `BackupNode`, `BackupJournalManager`)

### 1.5 NameNode RPC and HTTP (arch §2.5)

- **FR-24 — RPC surface.** `NameNodeRpcServer` must serve `ClientProtocol`,
  `DatanodeProtocol`, `NamenodeProtocol`, and admin/HA protocols, with
  server-side PB translation in `org.apache.hadoop.hdfs.protocolPB`. (arch §2.5, `NameNodeRpcServer`)
- **FR-25 — NameNode HTTP endpoints.** The NameNode HTTP server must host the
  web UI, `FsckServlet` (→ `NamenodeFsck`), `ImageServlet` (fsimage transfer),
  `StartupProgressServlet`, and `IsNameNodeActiveServlet`; security/token
  selection goes through `HDFSPolicyProvider` and the token secret managers. (arch §2.5, `NameNodeHttpServer`)

- **FR-63 — RPC handler seam.** `NameNodeRpcServer` must keep the
  three-endpoint split (client / service / lifeline RPC servers) and the
  per-call handler sequence `checkOperation` → `getPermissionChecker()` → op
  under the appropriate lock mode → journal (`logSync`)/audit; a new RPC must
  enter through this seam. (arch §2.5 "NameNodeRpcServer", `NameNodeRpcServer`)

### 1.6 DataNode (arch §2.7)

- **FR-26 — Heartbeat loop.** Each `BPServiceActor` must send
  `sendHeartbeat` every `dfs.heartbeat.interval` (default 3 s) carrying load
  and capacity, execute returned commands (replication, invalidation, cache,
  `DNA_ERASURE_CODING_RECONSTRUCTION`), and run periodic full block reports
  (lease-gated by `BlockReportLeaseManager`). (arch §2.7, `BPServiceActor`)
- **FR-27 — Xceiver ops.** `DataXceiver` must handle `OP_READ_BLOCK`
  (→ `BlockSender`), `OP_WRITE_BLOCK` (→ `BlockReceiver`), plus
  transfer-block, block-checksum, copy, replace and client-read-status ops of
  `DataTransferProtocol`. (arch §2.7, §2.8, `DataXceiver`)
- **FR-28 — Replica lifecycle.** Replica state on the DataNode must be
  managed through `FsDatasetImpl`/`FsVolumeList`/`ReplicaMap` with the
  defined states (`FinalizedReplica`, `ReplicaBeingWritten`,
  `ReplicaWaitingToBeRecovered`, `ReplicaUnderRecovery`); dead volumes must
  be reported via the `Storage` error reporters and excluded by
  `FsVolumeList`. (arch §2.7, `FsDatasetImpl`, `ReplicaMap`)
- **FR-29 — Background verification.** `BlockScanner`/`VolumeScanner` must
  verify block checksums in the background and report corrupt replicas to the
  NameNode via `ReportBadBlockAction`; `DirectoryScanner` must reconcile the
  on-disk block directory tree against `ReplicaMap`. (arch §2.7, `VolumeScanner`, `DirectoryScanner`)
- **FR-30 — Short-circuit advertisement.** `ShortCircuitRegistry` must
  advertise shm slots enabling client-side zero-copy, fd-passing local reads. (arch §2.7, `ShortCircuitRegistry`)
- **FR-31 — Incremental reports.** Block-received/deleted messages must be
  batched by `IncrementalBlockReportManager` and shipped opportunistically,
  not one RPC per block. (arch §2.7, `IncrementalBlockReportManager`)
- **FR-32 — Block recovery on DN.** When the NameNode requests `recoverBlock`,
  `BlockRecoveryWorker` must perform lease recovery
  (`RecoveryInProgress`/RUR handling) via `InterDatanodeProtocol`. (arch §2.7, §12.2, `BlockRecoveryWorker`)

- **FR-64 — DataNode start/stop order.** Startup must parse and
  format/upgrade `StorageLocation`s via `DataStorage` before starting the IPC
  server (`initIpcServer`), the `DataXceiverServer`(s) and `BlockPoolManager`
  services; shutdown (`DataNode.shutdown()`, offerService thread only) must
  stop plugins first, kill the xceiver servers after `sendOOBToPeers`, then
  the scanners, DataNode-side `DiskBalancer`, HTTP server, volume/storage
  checkers and pause monitor, and finally the block pools and the dataset.
  (arch §2.7 "DataNode lifecycle", `DataNode`, `DataStorage`)
- **FR-65 — DataNode IPC surface.** The DataNode IPC port must serve
  `ClientDatanodeProtocol` (`initIpcServer`): short-circuit
  `getBlockLocalPathInfo`, block recovery and refresh ops.
  (arch §2.7 "DataXceiverServer, DataXceiver and BlockReceiver", `DataNode.initIpcServer`)
- **FR-66 — Dataset directory layout.** Replica directories per
  volume/block pool must stay `current/finalized`, `current/rbw`,
  `current/lazypersist` plus pool-level `tmp` (`DataStorage` `STORAGE_DIR_*`
  constants); startup re-scan must re-add replicas through the
  `addReplicaThreadPool` (`ForkJoinPool`). (arch §2.7 "Dataset and on-disk layout (FsDatasetImpl)", `FsDatasetImpl`, `BlockPoolSlice`)
- **FR-67 — Volume capacity accounting.** Per-volume capacity accounting must
  use `FSCachingGetSpaceUsed` honouring `dfs.datanode.du.reserved`; volume
  failures beyond `dfs.datanode.failed.volumes.tolerated` must fail the node;
  all dataset I/O must stay instrumented through `FileIoProvider`.
  (arch §2.7 "Dataset and on-disk layout (FsDatasetImpl)", `FsDatasetImpl`, `FileIoProvider`)
- **FR-68 — Dataset helper services.** `FsDatasetAsyncDiskService` (async
  deletes/moves), `RamDiskReplicaTracker` +
  `RamDiskAsyncLazyPersistService` (lazy-persist RAM-disk writes to disk) and
  `FsDatasetCache`/`MappableBlock` (persistent memory caching) must be
  preserved as the dataset helper services. (arch §2.7 "Dataset and on-disk layout (FsDatasetImpl)", `FsDatasetAsyncDiskService`, `RamDiskAsyncLazyPersistService`)

### 1.7 Write and read paths (arch §2.8, §3.3, §3.4)

- **FR-33 — Pipeline write flow.** A file write must proceed: `create` RPC
  (lease granted, file under construction) → `DFSPacket`s queued by
  `DataStreamer` (`dataQueue` → `ackQueue`) → `addBlock` returns a
  `LocatedBlock` from the placement policy → pipeline of `OP_WRITE_BLOCK`s →
  per-packet acks → `complete` finalizes the last block via
  `BlockManager.commitOrCompleteLastBlock` once all reported replicas agree. (arch §2.8, `DFSOutputStream`, `DataStreamer`)
- **FR-34 — Ack semantics.** A packet must be moved out of `ackQueue` only
  when the last pipeline node's ack arrives; `waitForAckedSeqno` must block
  the writer until its seqno is acked; heartbeat packets must keep empty
  pipelines acking while the client is idle. (arch §2.8, `DataStreamer`)
- **FR-35 — Pipeline recovery.** A datanode failure during pipeline write
  must trigger pipeline recovery via `setupPipelineForAppendOrRecovery`
  (error propagation, removal of the dead node from the `LocatedBlock`) and
  `updatePipeline` on the NameNode (`FSDirWriteFileOp.updatePipelineForReplica`)
  without losing the acknowledged bytes. (arch §2.8, `DataStreamer`, `FSDirWriteFileOp`)
- **FR-36 — EC writes.** Erasure-coded files must use the same write skeleton
  with `DFSStripedOutputStream` + one `StripedDataStreamer` per cell/stripe
  writer across the EC target list. (arch §2.8, §3.3, `DFSStripedOutputStream`)
- **FR-37 — Read path.** `DFSInputStream` must fetch `LocatedBlocks` via
  `getBlockLocations`, sort replicas by proximity/topology, pick the closest
  live replica (`chooseDataNode` skipping dead/ignored nodes, retrying with
  backoff on `BlockReader` failures), and trigger `reportBadBlocks` on
  corruption. (arch §3.4, `DFSInputStream`)
- **FR-38 — Short-circuit and hedged reads.** Local reads must use
  `BlockReaderLocal`/`BlockReaderLocalLegacy` via
  `ClientDatanodeProtocol.getBlockLocalPathInfo` and shm slots; when hedged
  reads are enabled and a read exceeds the threshold, a second read must be
  launched against a *different* replica concurrently and whichever finishes
  first wins (metrics in `DFSHedgedReadMetrics`). (arch §3.4, `BlockReaderLocal`, `DFSInputStream`)

- **FR-69 — Wire framing.** `DataTransferProtocol` streams must remain
  `Sender`/`Receiver` over `PacketHeader`-framed packets (offset, seqno,
  lastPacketInBlock, `Status`) with `DataChecksum`-verified chunks; the op set
  (READ/WRITE/TRANSFER/BLOCK_CHECKSUM/COPY/REPLACE plus ack frames) must not
  grow without updating both sides. (arch §2.8 "Wire format", `PacketHeader`, `Sender`)
- **FR-70 — Flush/hsync semantics.** `flush`/`hflush` must push the current
  packet; `hsync` (with `HdfsDataOutputStream.SyncFlag` variants) must
  additionally sync the pipeline; the last block must remain under
  construction until `close` → `complete`. (arch §3.3 "DFSOutputStream packet path", `DFSOutputStream`, `SyncFlag`)
- **FR-71 — Reader strategy chain.** Reader selection must go through
  `BlockReaderFactory`'s `ReaderStrategy` chain: short-circuit local
  (`BlockReaderLocal`/`BlockReaderLocalLegacy` via `getBlockLocalPathInfo`,
  shm zero-copy via `ShortCircuitShm`, gated by
  `dfs.client.read.shortcircuit` and `dfs.domain.socket.path`), remote
  `RemoteBlockReader2` (`OP_READ_BLOCK`), and pluggable `ExternalBlockReader`;
  a PR must not bypass the strategy chain. (arch §3.4 "Readers and short-circuit", `BlockReaderFactory`)

### 1.8 Client library (arch §3.1, §3.2, §3.5)

- **FR-39 — DistributedFileSystem surface.** `DistributedFileSystem` must
  wrap a `DFSClient`, translate `Path`/`FileStatus` calls into
  `ClientProtocol` RPCs, and expose HDFS-specific ops (storage policy, EC,
  snapshots, recovery, `getAllStoragePolicies`) through
  `HdfsDataInputStream`/`HdfsDataOutputStream` wrappers. (arch §3.1, `DistributedFileSystem`)
- **FR-40 — Client shared state.** `DFSClient`-level shared caches
  (`PeerCache`, `KeyProviderCache`, `DeadNodeDetector`, short-circuit
  plumbing in the `shortcircuit` package) and token renewal /
  `DFSInotifyEventInputStream` must remain per-`ClientContext`, not
  per-stream. (arch §3.2, `DFSClient`, `ClientContext`)
- **FR-41 — ViewFS boundary.** ViewFS/HAR logic stays outside this project;
  this module's involvement is limited to `ViewDistributedFileSystem`
  routing into `DistributedFileSystem`. (arch §3.5, `ViewDistributedFileSystem`)

### 1.9 Router-Based Federation (arch §4)

- **FR-42 — Router transparency.** The Router must expose the full NameNode
  RPC surface (`RouterClientProtocol`/`RouterRpcServer`), stay stateless per
  request (except cached StateStore tables), and forward each call through a
  pooled connection to the owning subcluster's active NameNode; namespace
  data must remain in the subclusters. (arch §4.1, §4.3, `RouterRpcServer`, `RouterRpcClient`)
- **FR-43 — Mount-table resolution.** Path resolution must go through
  `MountTableResolver` (`PathLocation` → `RemoteLocation`(s)); fan-out mounts
  via `MultipleDestinationMountTableResolver`; membership ordering via
  `NamenodePriorityComparator`. (arch §4.3, `MountTableResolver`)
- **FR-44 — StateStore backends.** The Router's record store must remain
  pluggable (file/ZooKeeper/SQL drivers) with `MembershipStore`,
  `MountTableStore` and quota records cached by `StateStoreCache` and
  refreshed by `StateStoreCacheUpdateService`. (arch §4.2, `StateStoreService`)
- **FR-45 — Mount-table propagation and admin.** Mount-table updates must
  propagate to RBF caches via `MountTableRefresherService`; administration
  (mounts, quotas, subcluster state) via `hdfs dfsrouteradmin`
  (`RouterAdminServer`). (arch §4.1, §4.3, `MountTableRefresherService`, `RouterAdminServer`)

- **FR-72 — Router service list.** The `Router` must remain a
  `CompositeService` whose startup list is `StateStoreService`,
  `RouterRpcServer`, `RouterAdminServer`, `RouterHttpServer`, one
  `NamenodeHeartbeatService` per configured namenode (emitting
  `NamenodeStatusReport`), `RouterHeartbeatService`, `RouterMetrics`
  (`RouterRpcMonitor`), `RouterQuotaUpdateService`, `RouterSafemodeService`
  and `MountTableRefresherService` (with `MountTableRefresherThread` workers);
  `DFSRouter` remains the main class. (arch §4.1 "Router services and lifecycle", `Router`, `DFSRouter`)
- **FR-73 — Router RPC dispatch.** Router invocations must be packaged as
  `RemoteMethod`s and dispatched by `RouterRpcClient` over pooled connections
  (`ConnectionPool`/`ConnectionManager`/`ConnectionContext`) to the target
  subcluster's active NameNode, with `RouterStateIdContext` carrying
  observer-read state IDs and `RouterPermissionChecker` mirroring the NN
  permission model. (arch §4.1 "RouterRpcServer and connection management", `RouterRpcClient`, `RouterRpcServer`)
- **FR-74 — StateStore record model.** StateStore records must remain protobuf
  (`StateStoreSerializerPBImpl`) under `store.records` — `BaseRecord`,
  `MembershipState`, `MountTable`, `RouterState`, `DisabledNameservice` —
  exposed as typed `RecordStore`s (`MembershipStore`, `MountTableStore`,
  `RouterStore`); drivers remain `StateStoreFileImpl`,
  `StateStoreZooKeeperImpl`, `StateStoreMySQLImpl` and
  `StateStoreFileSystemImpl`. (arch §4.2 "Drivers and record stores", `StateStoreService`)
- **FR-75 — StateStore health monitoring.** `StateStoreConnectionMonitorService`
  must watch driver health so Router RPCs fail over when the backing store is
  unreachable; record caches must keep being refreshed by
  `StateStoreCacheUpdateService`. (arch §4.2 "Caching and refresh", `StateStoreConnectionMonitorService`)

### 1.10 HttpFS (arch §5)

- **FR-46 — WebHDFS REST gateway.** `HttpFSServer` must expose the WebHDFS
  REST API at `/webhdfs/v1`, translate REST parameters into `FileSystem`
  calls via `FSOperations` as a proxy-user `UserGroupInformation`, with
  `HttpFSAuthenticationFilter` handling Kerberos/delegation-token auth and
  `CheckUploadContentTypeFilter` validating uploads. (arch §5, `HttpFSServer`, `FSOperations`)

- **FR-76 — HttpFS bootstrap and filter chain.** HttpFS must boot via
  `HttpFSServerWebServer`/`HttpFSServerWebApp` from `httpfs-default.xml`/
  `httpfs-site.xml` (bind host `httpfs.http.hostname`, port `httpfs.http.port`
  default 14000, TLS via `httpfs.ssl.enabled`) with the servlet filter chain
  `HttpFSAuthenticationFilter` → `CheckUploadContentTypeFilter` →
  `HttpFSExceptionProvider` preserved. (arch §5 "Server bootstrap and filters", `HttpFSServerWebServer`)

### 1.11 NFS gateway (arch §6)

- **FR-47 — NFSv3 staging.** `RpcProgramNfs3` must serve NFSv3 via
  portmap/mount, maintain per-user `DFSClient`s (`DFSClientCache`), and stage
  (and reorder) client writes through `WriteManager`/`OpenFileCtx`/`WriteCtx`,
  committing on `COMMIT`/fsync; the gateway host must be configured as a
  proxy user. (arch §6, `RpcProgramNfs3`, `WriteManager`)

- **FR-77 — NFS service registration.** The gateway must register
  `RpcProgramNfs3` (NFSv3) and `RpcProgramMountd` with the portmap (secure
  mode via `PrivilegedNfsGatewayStarter`), bound to the configured bind host
  (default `0.0.0.0`) on `nfs.server.port` (2049) and `nfs.mountd.port`
  (4242). (arch §6 "NFSv3 RPC program and services", `RpcProgramNfs3`, `RpcProgramMountd`)
- **FR-78 — NFS staging bounds.** Write staging must keep per-open-file state
  in `OpenFileCtx` entries bounded by `nfs.max.open.files` (default 256),
  reorder/flush per-write `WriteCtx` entries through the client write path,
  force the stable write on `COMMIT`, dump unwritable/stale contexts to
  `nfs.dump.dir` (default `/tmp/.hdfs-nfs`) via the `Dumper` daemon, and cut
  off idle streams after the stream timeout (`nfs.stream.timeout`, default
  10 minutes). (arch §6 "Write staging and commit", `WriteManager`, `OpenFileCtx`)
- **FR-79 — Per-user DFS clients.** `DFSClientCache` must keep per-user
  `DFSClient`s and their `DFSInputStream`s in bounded Guava caches (eviction/
  removal listeners, a JVM shutdown hook), so NFS identity maps onto
  `UserGroupInformation` identity — a shared user implies shared leases and
  clients. (arch §6 "Per-user DFS clients", `DFSClientCache`)

### 1.12 libhdfs (arch §7)

- **FR-48 — JNI delegation.** `libhdfs` must remain a thin JNI wrapper: every
  `hdfs*` C call forwards onto the Java client (`DistributedFileSystem`/
  `DFSClient`), with jclass/jmethodID caching, thread attach/detach handling,
  and CMake build glue; no HDFS behaviour may be reimplemented in C. (arch §7, `hdfs.c`, `jni_helper.c`)


### 1.13 Other server subsystems (arch §2.9)

- **FR-80 — Balancer transport.** Balancer block moves must go
  DataNode-to-DataNode over `OP_COPY_BLOCK`/`OP_REPLACE_BLOCK` via
  `Dispatcher`, throttled by `dfs.datanode.balance.bandwidthPerSec`, with runs
  parameterized through the CLI and `BalancerMXBean`.
  (arch §2.9 "Balancer", `Dispatcher`, `BalancerMXBean`)
- **FR-81 — Tier migration ownership.** Storage-tier migration must stay in
  `Mover` (`server.mover`) and `StoragePolicySatisfier` (`server.sps`, with
  the external-SPS variant in `server.namenode.sps` and shared pieces in
  `server.common.sps`) tracking unsatisfied files (`ExternalSPSMXBean` in
  external mode) and issuing movement work on their own thread(s).
  (arch §2.9 "Mover and StoragePolicySatisfier", `StoragePolicySatisfier`)
- **FR-82 — DiskBalancer scope.** The DataNode-side `DiskBalancer` must
  execute volume-to-volume copies within one node from a resumable, throttled
  plan; the plan model and `DiskBalancerCLI` remain in `server.diskbalancer`
  and `tools`. (arch §2.9 "DiskBalancer", `DiskBalancer`, `DiskBalancerCLI`)
- **FR-83 — Aliasmap-only provided storage.** Provided (external) block
  storage must be surfaced only via the aliasmap path: `InMemoryAliasMap`
  (LevelDB-backed) served by `InMemoryLevelDBAliasMapServer` over
  `InMemoryAliasMapProtocol`, consumed by the NameNode's
  `ProvidedStorageMap` and the DataNode's `ProvidedReplica`.
  (arch §2.9 "Aliasmap (provided storage)", `InMemoryAliasMap`, `ProvidedStorageMap`)

---

## 2. Non-functional requirements

### 2.1 Concurrency (arch §9)

- **NFR-C-1 — Namesystem lock discipline.** Namespace mutations must
  serialize on the `FSNamesystem` write lock (`FSNamesystemLock`, fair only if
  `dfs.namenode.fslock.fair`); a PR must not perform I/O (fsync, network)
  while holding it beyond the existing `logEdit`/`logSync` pattern —
  `logSync()` after lock release (as in `recoverLease`) is the model. (arch §9.1, `FSNamesystemLock`) ⟵ supersedes R-NFR-1
- **NFR-C-2 — Lock modes.** Full block reports (`processReport`) must take
  the GLOBAL write lock; DataNode heartbeats must take only
  `readLock(RwLockMode.BM)`; long-hold diagnostics
  (`longestReadLockHeldInfo`/`longestWriteLockHeldInfo`, `LongAdder`
  counters, lock metrics `<lockName>ReadLock`/`<lockName>WriteLock`) must be
  preserved by any change to lock usage.
  (arch §9.1, `BlockManager.processReport`, `FSNamesystem.handleHeartbeat`) ⟵ supersedes R-NFR-2
- **NFR-C-3 — Single work producer.** Replication/reconstruction work must be
  produced only by the single `RedundancyMonitor` thread, drawn from
  `LowRedundancyBlocks` priority queues, and bounded per iteration by
  `dfs.namenode.replication.max-streams` (2) ×
  `dfs.namenode.replication.work.multiplier.per.iteration` (2). (arch §9.3, `BlockManager.RedundancyMonitor`) ⟵ supersedes R-NFR-3
- **NFR-C-4 — Pending-reconstruction bound.** `PendingReconstructionMonitor`
  must time out pending-reconstruction entries after their timeout so the
  multiset never grows unbounded on silent DataNode failure. (arch §9.3, `PendingReconstructionBlocks`) ⟵ supersedes R-NFR-4
- **NFR-C-5 — Dataset lock levels.** `FsDatasetImpl` replica mutations must
  hold the `DataNodeLockManager` lock at the correct level (`BLOCK_POOL` vs
  `DIR`) via `AutoCloseableLock` try-with-resources; scans may take read
  locks only. Block-pool locks exclude only same-pool writers; dir locks only
  same-directory writers. (arch §9.4, `FsDatasetImpl`, `DataNodeLockManager`) ⟵ supersedes R-NFR-5
- **NFR-C-6 — Xceiver thread model.** The data-transfer port must remain
  thread-per-connection (`DataXceiverServer` spawns one `Daemon` per accepted
  peer, no pool reuse); when `curXceiverCount > maxXceiverCount`
  (`dfs.datanode.max.transfer.threads`, default 4096) the server must refuse
  the connection with an `IOException` rather than queue it. (arch §9.4, `DataXceiverServer`) ⟵ supersedes R-NFR-6
- **NFR-C-7 — Packet responder invariant.** Every pipeline write must run
  exactly one `PacketResponder` thread that finalizes the replica only after
  the last ack (`lastPacketInBlock`); pipeline recovery must stop both the
  receiver and the responder. (arch §9.4, `BlockReceiver`, `BlockReceiver.PacketResponder`) ⟵ supersedes R-NFR-7
- **NFR-C-8 — Scanner bounds.** `DirectoryScanner` must run at
  `dfs.datanode.directoryscan.interval` (21600 s default) with
  `dfs.datanode.directoryscan.threads` (1) workers, reconciling in bounded
  batches (`dfs.datanode.reconcile.blocks.batch.size`/`interval`); per-volume
  `VolumeScanner` threads must remain throttled. (arch §9.4, `DirectoryScanner`, `BlockScanner`) ⟵ supersedes R-NFR-8
- **NFR-C-9 — Hard lease expiry.** A lease whose `lastUpdate` exceeds
  `hardLimit` (`dfs.namenode.lease-hard-limit-sec`) must trigger lease
  recovery (`internalReleaseLease`) even if the client is still alive but
  stalled; the client must then observe recovery rather than continue
  writing. A PR must not assume lease expiry happens only after client death.
  (arch §9.5, `LeaseManager.Monitor`, `hardLimitExpired`) ⟵ supersedes R-NFR-9
- **NFR-C-10 — HA transition ordering.** Election loss must fence the old
  active *before* the standby transitions; `transitionToActive` takes the
  namesystem write lock during state entry, so `EditLogTailer` must use
  `writeLockInterruptibly(RwLockMode.GLOBAL)` — a plain write lock deadlocks
  against `transitionToActive`. (arch §9.6, `DFSZKFailoverController`, `EditLogTailer`) ⟵ supersedes R-NFR-10
- **NFR-C-11 — Documented deadlock hazards.** The five recorded hazards are
  load-bearing invariants a PR must preserve: (a) `FSImageFormat`/
  `FSImageFormatProtobuf` savers must use `unprotectedGetNamespaceInfo()`
  (HDFS-2223 fair-lock deadlock); (b) tailer interruptible write lock
  (NFR-C-10); (c) `ShortCircuitRegistry.createNewMemorySegment` drops the
  registry lock before registering shm with the socket watcher; (d)
  `DataNode.shutdown()` only from the offerService thread; (e)
  `FSEditLogAsync`'s separate mutex and careful monitor re-offer.
  (arch §9.7, `FSImageFormat`, `ShortCircuitRegistry`, `DataNode.shutdown`,
  `FSEditLogAsync`) ⟵ supersedes R-NFR-25 (item d)

- **NFR-C-13 — Async edit-log queue bound.** `FSEditLogAsync` must keep
  appends/syncs on its background thread only while
  `dfs.namenode.edits.asynclogging` is enabled (default true), with the
  pending queue bounded by
  `dfs.namenode.edits.asynclogging.pending.queue.size` (4096); on-disk
  ordering must be preserved and the separate-mutex lock-ordering contract
  (NFR-C-11e) kept intact. (arch §2.1 "FSEditLog and journaling", §11.2, `FSEditLogAsync`)
- **NFR-C-14 — Client streaming-thread model.** There must be one
  `DataStreamer` daemon per open file and one `ResponseProcessor` daemon per
  in-flight block; the writer thread must block only in `waitForAckedSeqno`
  and must perform no pipeline I/O beyond packet filling.
  (arch §9.4 "Client library concurrency", §2.8 "Client-side streaming threads", `DataStreamer`, `ResponseProcessor`)
- **NFR-C-15 — Client shared-thread hygiene.** `LeaseRenewer` must keep one
  shared, lazy-started renewal daemon per user across all `DFSClient`s;
  `PeerCache`/`ShortCircuitCache` remain shared via `ClientContext`;
  `DeadNodeDetector` probes asynchronously on its own threads; hedged reads
  must stay on the bounded `hedgedRead-<n>` pool
  (`dfs.client.hedged.read.threadpool.size`, default 0 = disabled; trigger
  `dfs.client.hedged.read.threshold.millis`, default 500).
  (arch §9.4 "Client library concurrency", §3.4 "Hedged reads and dead-node detection", `LeaseRenewer`, `DFSInputStream`)

### 2.2 Security (arch §10)

- **NFR-S-1 — Per-role Kerberos principals.** NameNode, DataNode,
  SecondaryNameNode, JournalNode, web-UI/HttpFS SPNEGO, and balancer/mover/
  SPS principals must remain configurable per role
  (`dfs.{namenode,datanode,journalnode,...}.kerberos.principal`); the HTTP
  layer must honour `dfs.http.policy` (HTTP_ONLY/HTTPS_ONLY/HTTP_AND_HTTPS)
  and `dfs.web.authentication.kerberos.principal`. (arch §10.1, `DFSConfigKeys`, `NameNodeHttpServer`) ⟵ supersedes R-NFR-12
- **NFR-S-2 — Data-transfer SASL.** When `dfs.data.transfer.protection` is
  `integrity`/`privacy` or block tokens are enabled, block transfers must
  negotiate SASL (`SaslDataTransferClient`/`SaslDataTransferServer`) before
  any block bytes flow, and mismatched handshakes must be rejected
  (`InvalidMagicNumberException`). (arch §10.2, `datatransfer.sasl` package) ⟵ supersedes R-NFR-13
- **NFR-S-3 — Block access tokens.** Block tokens (`BlockTokenIdentifier`)
  must be scoped per block pool via `BlockPoolTokenSecretManager`, embedded
  by the NameNode in `LocatedBlock`s, and validated on the DataNode (block
  id, pool id, modes, expiry) before serving any `OP_READ_BLOCK`/
  `OP_WRITE_BLOCK`; gated by `dfs.block.access.token.enable` (default false).
  (arch §10.3, `BlockPoolTokenSecretManager`, `DataXceiver`) ⟵ supersedes R-NFR-14
- **NFR-S-4 — Delegation tokens.** Delegation tokens must renew within
  `dfs.namenode.delegation.token.renew-interval` (1 d default), never exceed
  `dfs.namenode.delegation.token.max-lifetime` (7 d default), and be
  renewable/cancellable only through `DFSClient.Renewer` (owner or
  authenticated renewer); WebHDFS renews via `TokenAspect`.
  (arch §10.4, `DelegationTokenSecretManager`, `DFSClient.Renewer`) ⟵ supersedes R-NFR-15
- **NFR-S-5 — Permission checks.** Every RPC must construct an
  `FSPermissionChecker` (`getPermissionChecker()`, with
  `setOperationType` per call) and pass `FSDirectory.check*` checks before
  touching the namespace, gated by `dfs.permissions.enabled`; safemode must
  reject mutations with `SafeModeException` (see FR-16); superuser bypass
  follows hadoop-common `hadoop.security.superuser.group` semantics inside
  `FSPermissionChecker`. (arch §10.5, `FSPermissionChecker`, `FSDirectory`) ⟵ supersedes R-NFR-16
- **NFR-S-6 — Encryption zones.** The NameNode must persist only encrypted
  DEKs + `FileEncryptionInfo` (in `HdfsFileStatus`/`LocatedBlock`); plaintext
  key material must exist solely in client-side `KeyProvider`s
  (`KeyProviderCache`, `dfs.encryption.key.provider.uri`), decrypted on the
  client in the `DFSClient#create` path. A PR must not route keys through NN
  RPCs or logs. (arch §10.6, `EncryptionZoneManager`) ⟵ supersedes R-NFR-17
- **NFR-S-7 — Gateway proxy users.** HttpFS operations must run as a proxy
  user (`doAs` UGI in `FSOperations`), the Router must forward the remote UGI
  to subclusters with proxy-user semantics, and the NFS gateway requires
  proxy-user configuration for its principal; the gateway principals must be
  configured as hadoop proxy users on the NameNode. (arch §10.7, §5, §6, `FSOperations`, `RouterRpcServer`)

- **NFR-S-8 — HttpFS auth ordering.** HttpFS authentication must remain in
  `HttpFSAuthenticationFilter` (Kerberos/SPNEGO plus delegation tokens) ahead
  of the proxy-user `FSOperations` execution; authorization must happen as
  the end user inside the `doAs` `UserGroupInformation`, and the gateway
  principal must remain a configured hadoop proxy user on the NameNode.
  (arch §5 "FSOperations and proxy-user execution", §10.7, `FSOperations`, `HttpFSAuthenticationFilter`)

### 2.3 Logging and auditability (arch §11)

- **NFR-L-1 — NameNode audit log.** Every client operation (success or
  failure) must emit an audit event via `FSNamesystem.logAuditEvent` through
  the configured `AuditLogger`s (`dfs.namenode.audit.loggers`:
  `DefaultAuditLogger`, `TopAuditLogger`), emitted from the op layer after
  permission checks; a PR adding a new op is incomplete without an audit
  call. (arch §11.1, `FSNamesystem.logAuditEvent`, `HdfsAuditLogger`) ⟵ supersedes R-NFR-18
- **NFR-L-2 — Edit durability contract.** An edit must be acknowledged only
  after `EditLogOutputStream.flushAndSync(durable)` on a majority of journals
  in HA (`QuorumOutputStream` QJM majority ack) or on all configured journals
  in the local case (`EditLogFileOutputStream` pre-allocation + force);
  `flush()` without `durable` only moves buffered bytes to the OS.
  (arch §11.2, `FSEditLog`, `QuorumJournalManager`) ⟵ supersedes R-NFR-11
- **NFR-L-3 — Edit-log pairing rules.** A PR adding an edit-log op must
  append it inside the write-locked section using the existing
  `logEdit`/`logSync` pairing; skipping `logSync` after an exception is
  allowed only for `StandbyException` (per `recoverLease`); checkpoints/rolls
  must call `logSyncAll()`; segment names must carry start/end txids per
  `NNStorage.NameNodeFile` naming. (arch §11.2, §12.5, `FSEditLog`, `NNStorage`) ⟵ supersedes R-NFR-19
- **NFR-L-4 — Metrics surface.** NameNode/DataNode metrics must keep the
  existing counters (`blocksRead`, `blocksWritten`, `volumeFailures`,
  heartbeat/block-report timers, `createFileOps`, `getBlockLocations`, …) in
  metrics context `dfs` and remain JMX-visible through the existing MBeans
  (`NameNodeMXBean`, `NameNodeStatusMXBean`, `FSNamesystemMBean`,
  `BlockStatsMXBean`, `DataNodeMXBean`, `JournalNodeMXBean`, …).
  (arch §11.3, `DataNodeMetrics`, `NameNodeMetrics`) ⟵ supersedes R-NFR-20
- **NFR-L-5 — Corruption as first-class state.** Corruption found by
  background verification must be *reported to the NameNode* (via
  `ReportBadBlockAction`), not only logged, and recorded in
  `CorruptReplicasMap`. (arch §11.3, §2.7, `VolumeScanner`, `CorruptReplicasMap`) ⟵ supersedes R-NFR-21
- **NFR-L-6 — Block-token audit boundary.** Block-token *use* on the DataNode
  is verified in `DataXceiver` before I/O; failures raise `InvalidToken`
  (logged, connection aborted). There is no per-block-read audit log on the
  DataNode path — a PR must not claim block-read auditability beyond
  DataNode INFO/WARN logs and metrics, and must not silently remove this
  verification. (arch §11.4, §10.3, `DataXceiver`)

- **NFR-L-8 — Slow-node telemetry.** Slow-node telemetry (`SlowPeerTracker`,
  `SlowDiskTracker`) aggregated from DataNode reports must remain surfaced in
  the NameNode UI/JMX; a PR must not remove or silently disable it.
  (arch §2.2 "DatanodeManager and HeartbeatManager", `SlowPeerTracker`, `SlowDiskTracker`)

### 2.4 Integration (arch §12)

- **NFR-I-1 — RPC plumbing completeness.** A new RPC must be added to both
  the PB service definition and the matching translator
  (`ClientNamenodeProtocolTranslatorPB` / server-side translator) and
  published through `HDFSPolicyProvider` so Kerberos ACLs cover it.
  (arch §12.2, §2.5, `protocolPB`, `HDFSPolicyProvider`) ⟵ supersedes R-NFR-22
- **NFR-I-2 — Observer reads.** Observer NameNodes (`OBSERVER_STATE`,
  `dfs.namenode.observer.enabled`) must serve reads only; read-your-writes
  ordering is the client's concern via `ObserverReadProxyProvider`-family
  providers (`RouterObserverReadProxyProvider`,
  `ObserverReadProxyProviderWithIPFailover`) with
  `dfs.ha.namenodes.<ns>`/`dfs.client.failover.proxy.provider.<ns>` config.
  (arch §12.4, `NameNode.OBSERVER_STATE`) ⟵ supersedes R-NFR-23
- **NFR-I-3 — On-disk layout compatibility.** fsimage/`edits_inprogress_`/
  `seen_txid` naming per `NNStorage.NameNodeFile` must stay backward
  compatible or bump `LAYOUT_VERSION`; startup inspection
  (`FSImageTransactionalStorageInspector`) must fail closed on inconsistent
  txids (`seen_txid` mismatch detection preserved). (arch §12.5, `NNStorage`, `FSImage`) ⟵ supersedes R-NFR-24
- **NFR-I-4 — Endpoint keys and defaults.** RPC/HTTP endpoints must remain
  configurable under their keys with current defaults preserved: client RPC
  `dfs.namenode.rpc-address` (8020), HTTP 9870 / HTTPS 9871, JournalNode RPC
  8485 / HTTP 8480, service/lifeline RPC keys unset by default; the DataNode
  data-transfer port speaks `DataTransferProtocol`, not IPC. (arch §12.1, `DFSConfigKeys`, `DataXceiverServer`)
- **NFR-I-5 — Wire-protocol symmetry.** The eight protocols
  (`ClientProtocol`, `DatanodeProtocol`, `NamenodeProtocol`,
  `ClientDatanodeProtocol`, `InterDatanodeProtocol`, `JournalProtocol`,
  `QJournalProtocol`, `DataTransferProtocol`) must change on both client and
  server sides together; a PR altering one side without the other is a
  compatibility break. (arch §12.2, `protocolPB`, `datatransfer`)
- **NFR-I-6 — ZooKeeper confinement.** ZooKeeper usage must remain confined
  to the ZKFC (`ActiveStandbyElector` active lock, `HealthMonitor`,
  `dfs.ha.fencing.methods`) and the RBF StateStore ZK driver; NameNode and
  DataNode must gain no direct ZooKeeper dependency. (arch §12.3, `DFSZKFailoverController`, `StateStoreDriver`)

- **NFR-I-7 — Gateway/RBF endpoint keys.** Router, HttpFS and NFS endpoints
  must remain configurable under their keys with current defaults preserved:
  `dfs.federation.router.rpc-address` (default `0.0.0.0:8888`),
  `dfs.federation.router.admin-address` (8111),
  `dfs.federation.router.http-address`, `httpfs.http.port` (14000),
  `nfs.server.port` (2049), `nfs.mountd.port` (4242).
  (arch §12.1, §4.1, §5, §6, `RBFConfigKeys`, `NfsConfigKeys`, `HttpFSServerWebServer`)
- **NFR-I-8 — JournalNode on-disk layout.** The JournalNode layout must stay
  consistent per journal-id: `JNStorage` `current/` segment files named per
  the §12.5 conventions and `paxos/` segment-recovery state; a PR moving or
  renaming these must preserve segment-recovery compatibility
  (`recoverUnfinalizedSegments` across journals).
  (arch §12.5, §2.4 "JournalNode (server)", `JNStorage`)

### 2.5 Mapping of arch §13 R-NFR candidates

| arch §13 | This doc | Note |
|---|---|---|
| R-NFR-1…10 | NFR-C-1…C-10 | one-to-one; C-2 splits lock modes + long-hold metrics; C-8 adds VolumeScanner throttling |
| R-NFR-11 | NFR-L-2 | reclassified as durability/logging |
| R-NFR-12…17 | NFR-S-1…S-6 | one-to-one; S-3 adds enforcement points; S-4 adds WebHDFS TokenAspect; S-5 merged with FR-16 |
| R-NFR-18 | NFR-L-1 | unchanged |
| R-NFR-19 | NFR-L-3 | adds recoverLease/StandbyException rule |
| R-NFR-20, R-NFR-21 | NFR-L-4, NFR-L-5 | unchanged |
| R-NFR-22…24 | NFR-I-1…I-3 | one-to-one; I-2 adds config keys |
| R-NFR-25 | NFR-C-11 (d) | folded into deadlock-hazard list |

Additional requirements with no R-NFR number: FR-1–FR-48 (arch §§2–8,
including FR-13 safemode accounting from §2.2), NFR-S-7 (arch §10.7),
NFR-L-6 (arch §11.4), NFR-I-4…NFR-I-6 (arch §12.1–12.3); the depth-3
extension added FR-50–FR-83, NFR-C-13/14/15, NFR-S-8, NFR-L-8, NFR-I-7/8
(arch depth-3 #### sections), derived in the 2026-11-17 review session.

---

## 3. PR-review checklists

### 3.1 NameNode namespace, leases & safemode

- [ ] Mutation path unchanged: write lock → `FSDir*Op` → `logEdit`/`logSync` (FR-2, NFR-C-1, NFR-L-3)
- [ ] Restart still replays fsimage + edits (FR-3); no format/layout change without `LAYOUT_VERSION` (NFR-I-3)
- [ ] New metadata still carried in `INodeWithAdditionalFields` features, not side tables (FR-4)
- [ ] Audit event emitted for any new op (NFR-L-1)
- [ ] Single-writer lease invariant preserved (FR-14); hard-expiry triggers recovery even for live clients (NFR-C-9)
- [ ] Mutations rejected with `SafeModeException` in safemode; startup criteria unchanged (FR-16)
- [ ] Mutations rejected with `SafeModeException` in safemode; startup criteria unchanged (FR-16)
- [ ] INode-tree lookups still via `INodesInPath`; `inodeMap`/`nameCache` contracts kept (FR-50)
- [ ] Namespace save still `SaveNamespaceContext` → `FSImageFormatProtobuf` → promote → roll (FR-51)
- [ ] New namesystem services hooked in `startCommonServices`, not ad-hoc (FR-52)
- [ ] New namespace ops implemented as `FSDir*Op` with interleaved journaling (FR-53)
- [ ] Async edit logging keeps the bounded pending queue and on-disk ordering (NFR-C-13)

### 3.2 Block management

- [ ] Block reports still diff through `processReport` into `InvalidateBlocks`/`LowRedundancyBlocks` (FR-7)
- [ ] Reconstruction work only from `RedundancyMonitor`, bounded (NFR-C-3); delivered as heartbeat commands (FR-8)
- [ ] Corrupt replicas reach `CorruptReplicasMap`; healthy replicas invalidated (FR-9, NFR-L-5)
- [ ] Placement via `BlockPlacementPolicy`, not hardcoded (FR-10)
- [ ] Safemode accounting in `BlockManagerSafeMode` intact (FR-13)
- [ ] Safemode accounting in `BlockManagerSafeMode` intact (FR-13)
- [ ] `LocatedBlock`s still built only by `LocatedBlockBuilder` (FR-54)
- [ ] Host lists via host-file managers; stale/dead windows and decommission monitors kept (FR-55, FR-56)
- [ ] Cache directives/pools still reconciled by `CacheReplicationMonitor` with `DNA_CACHE`/`DNA_UNCACHE` (FR-57)
- [ ] Over-replication in `ExcessRedundancyMap`; deficit math via `NumberReplicas` (FR-58)
- [ ] Slow-peer/slow-disk telemetry still surfaced in NN UI/JMX (NFR-L-8)

### 3.3 HA / JournalNode / checkpointing

- [ ] Edits ack only on QJM majority / all local journals (FR-18, NFR-L-2)
- [ ] Failover order: fence → znode → transition → segment recovery (FR-19, FR-20, NFR-C-10)
- [ ] Tailer uses `writeLockInterruptibly`; no new locks against `transitionToActive` (NFR-C-10, NFR-C-11)
- [ ] DataNodes re-target the new active; clients re-resolve via failover proxy provider (FR-21, NFR-I-2)
- [ ] DataNodes re-target the new active; clients re-resolve via failover proxy provider (FR-21, NFR-I-2)
- [ ] HA transitions still take the write lock; standby/observer reject writes with `StandbyException` (FR-59)
- [ ] JournalNode still txn-ordered (`NewerTxnIdException`), `paxos/` recovery state and `GetJournalEditServlet` kept (FR-60, NFR-I-8)
- [ ] Tailer roll executor bounded by `rollEditsTimeoutMs`; `EditLogTailerThread` unchanged (FR-61)
- [ ] BackupNode edit streaming over `JournalProtocol` unaffected (FR-62)

### 3.4 DataNode

- [ ] Heartbeat/block-report loops per NN per pool unchanged (FR-26); IBRM batching kept (FR-31)
- [ ] Xceiver still thread-per-connection with hard cap, refusing rather than queueing (NFR-C-6)
- [ ] Dataset locks at correct `LockLevel`, `AutoCloseableLock` (NFR-C-5)
- [ ] One `PacketResponder` per pipeline write; recovery stops receiver + responder (NFR-C-7)
- [ ] Scanner findings reported to NN, not just logged (FR-29, NFR-L-5)
- [ ] `shutdown()` still only from offerService thread (NFR-C-11d)
- [ ] `shutdown()` still only from offerService thread (NFR-C-11d)
- [ ] Start/stop ordering kept: `DataStorage` format → IPC/xceiver/block pools; shutdown plugin-first with OOB (FR-64)
- [ ] IPC port still serves `ClientDatanodeProtocol` (short-circuit path info, recovery, refresh) (FR-65)
- [ ] On-disk replica directories (`finalized`/`rbw`/`lazypersist`/`tmp`) and startup re-scan pool kept (FR-66)
- [ ] Capacity accounting (`FSCachingGetSpaceUsed`, `du.reserved`, `failed.volumes.tolerated`, `FileIoProvider`) kept (FR-67)
- [ ] Dataset helpers intact: async disk service, lazy persist, `FsDatasetCache`/`MappableBlock` (FR-68)

### 3.5 Write / read path

- [ ] Packets acked only from the last pipeline node; `waitForAckedSeqno` semantics kept (FR-34)
- [ ] Pipeline failure → `setupPipelineForAppendOrRecovery` + `updatePipeline`, acknowledged bytes not lost (FR-35)
- [ ] EC writes still via `DFSStripedOutputStream`/`StripedDataStreamer` (FR-36)
- [ ] Read retry/backoff, dead-node skipping, `reportBadBlocks` on corruption (FR-37)
- [ ] Short-circuit/hedged read behaviour and metrics preserved (FR-38, NFR-L-4)
- [ ] Short-circuit/hedged read behaviour and metrics preserved (FR-38, NFR-L-4)
- [ ] Wire framing (`Sender`/`Receiver`, `PacketHeader`, `DataChecksum`) unchanged on both sides (FR-69)
- [ ] `hflush`/`hsync` (`SyncFlag`) semantics and under-construction tail kept (FR-70)
- [ ] Reader selection still via the `ReaderStrategy` chain incl. `ExternalBlockReader` (FR-71)
- [ ] One `DataStreamer` per file, one `ResponseProcessor` per block; writer blocks only in `waitForAckedSeqno` (NFR-C-14)
- [ ] `LeaseRenewer` one daemon per user; hedged-read pool bounds unchanged (NFR-C-15)

### 3.6 Client / RBF / gateways

- [ ] Client caches remain per-`ClientContext` (FR-40); ViewFS boundary kept (FR-41)
- [ ] Router stays stateless per request; resolution via mount table; StateStore drivers untouched in interface (FR-42–FR-44)
- [ ] Mount-table refresh propagation and `dfsrouteradmin` surface preserved (FR-45)
- [ ] HttpFS still proxy-user, auth filter unchanged (FR-46, NFR-S-7)
- [ ] NFS gateway staging/COMMIT semantics and proxy-user requirement kept (FR-47, NFR-S-7)
- [ ] libhdfs still pure delegation to the Java client (FR-48)
- [ ] libhdfs still pure delegation to the Java client (FR-48)
- [ ] Router service list / lifecycle unchanged; `DFSRouter` main class (FR-72)
- [ ] Router dispatch via `RemoteMethod` + pooled connections; state-ID context and permission checker kept (FR-73)
- [ ] StateStore protobuf record set and driver list untouched (FR-74); driver-health failover kept (FR-75)
- [ ] HttpFS bootstrap, filter chain and proxy-user ordering kept (FR-76, NFR-S-8)
- [ ] NFS portmap registration, staging bounds (`nfs.max.open.files`, dump dir, stream timeout) kept (FR-77, FR-78)
- [ ] Per-user `DFSClientCache` identity/eviction semantics kept (FR-79)
- [ ] Gateway/RBF endpoint keys and defaults unchanged (NFR-I-7)

### 3.7 Cross-cutting (concurrency, security, logging, integration)

- [ ] No fsync/network I/O under the namesystem write lock beyond the `logEdit`/`logSync` pattern (NFR-C-1)
- [ ] `RwLockMode` split preserved: heartbeats BM read, block reports GLOBAL write (NFR-C-2)
- [ ] Pending-reconstruction timeouts intact (NFR-C-4); `DirectoryScanner` schedule/batching unchanged (NFR-C-8)
- [ ] The five documented deadlock hazards re-checked (NFR-C-11)
- [ ] Principal/policy config keys untouched (NFR-S-1)
- [ ] SASL negotiated before block bytes when required; bad handshakes rejected (NFR-S-2)
- [ ] Block tokens still validated per pool on the DataNode before I/O (NFR-S-3)
- [ ] Delegation-token renew/lifetime bounds and renewer restrictions kept (NFR-S-4)
- [ ] `FSPermissionChecker` constructed per RPC; checks before namespace access (NFR-S-5)
- [ ] No key material through NN RPCs, logs, or fsimage (NFR-S-6)
- [ ] Audit call present for every new/changed op (NFR-L-1); no per-block-read audit claims (NFR-L-6)
- [ ] New edit ops use `logEdit`/`logSync` inside the write-locked section (NFR-L-3)
- [ ] Metrics counters and MBeans preserved (NFR-L-4)
- [ ] New RPCs: PB definition + both translators + `HDFSPolicyProvider` (NFR-I-1)
- [ ] Protocol changes made symmetrically on both sides (NFR-I-5)
- [ ] Ports/keys/defaults unchanged, or explicitly updated in both code and docs (NFR-I-4)
- [ ] No new direct ZooKeeper dependency in NN/DN (NFR-I-6)
- [ ] No new direct ZooKeeper dependency in NN/DN (NFR-I-6)
- [ ] Balancer/mover/SPS/DiskBalancer transports and ownership unchanged (FR-80–FR-82)
- [ ] Provided storage still only via the aliasmap path (FR-83)

---

## References

- `notes/architecture/hadoop-hdfs-architecture.md` — source document (§§1–13,
  including NFR candidates R-NFR-1…25 in §13).
- Source tree: `hadoop-hdfs-project/{hadoop-hdfs, hadoop-hdfs-client,
  hadoop-hdfs-rbf, hadoop-hdfs-httpfs, hadoop-hdfs-nfs,
  hadoop-hdfs-native-client}`.
