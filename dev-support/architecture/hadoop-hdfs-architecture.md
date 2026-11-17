# Apache HDFS Architecture (hadoop-hdfs-project)

<!--
SPDX-License-Identifier: Apache-2.0
-->

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

Orientation document for the HDFS modules in this checkout. All class names below
are real, verified against the source tree under
`hadoop-hdfs-project/` (trunk layout). Depth: the modules plus their first-level
subsystems (HDFS server internals are treated at the level of
`org.apache.hadoop.hdfs.server.*`).

## Table of contents

1. [Module map](#1-module-map)
2. `hadoop-hdfs` — the server
   - [2.1 NameNode: namespace, FSImage and FSEditLog](#21-namenode-namespace-fsimage-and-fseditlog)
   - [2.2 Block management (BlockManager, BlocksMap, HeartbeatManager)](#22-block-management)
   - [2.3 Leases and safemode](#23-leases-and-safemode)
   - [2.4 HA: active/standby, ZKFC, QuorumJournalManager, JournalNode](#24-ha-activestandby-zkfc-quorumjournalmanager-journalnode)
   - [2.5 NameNode RPC and HTTP](#25-namenode-rpc-and-http)
   - [2.6 SecondaryNameNode and checkpointing](#26-secondarynamenode-and-checkpointing)
   - [2.7 DataNode](#27-datanode)
   - [2.8 DataTransferProtocol and the write pipeline](#28-datatransferprotocol-and-the-write-pipeline)
   - [2.9 Other server subsystems (balancer, mover, sps, diskbalancer, aliasmap)](#29-other-server-subsystems)
3. `hadoop-hdfs-client` — DistributedFileSystem, DFSClient, read/write paths
   - [3.1 DistributedFileSystem](#31-distributedfilesystem)
   - [3.2 DFSClient](#32-dfsclient)
   - [3.3 Write path: DFSOutputStream and DataStreamer](#33-write-path-dfsoutputstream-and-datastreamer)
   - [3.4 Read path: DFSInputStream, short-circuit and hedged reads](#34-read-path-dfsinputstream-short-circuit-and-hedged-reads)
   - [3.5 ViewFS and HAR](#35-viewfs-and-har)
4. `hadoop-hdfs-rbf` — Router-Based Federation
   - [4.1 Router](#41-router)
   - [4.2 StateStore](#42-statestore)
   - [4.3 Federation resolution and admin](#43-federation-resolution-and-admin)
5. `hadoop-hdfs-httpfs` — WebHDFS REST gateway
6. `hadoop-hdfs-nfs` — NFS gateway
7. `hadoop-hdfs-native-client` — libhdfs
8. [Behaviour summary](#8-behaviour-summary)
9. [Concurrency](#9-concurrency)
10. [Security](#10-security)
11. [Logging and auditability](#11-logging-and-auditability)
12. [Integration points](#12-integration-points)
13. [Non-functional requirement candidates](#13-non-functional-requirement-candidates)

---

## 1. Module map

`hadoop-hdfs-project/` contains six modules (`pom.xml` aggregates them):

| Module | Role |
|---|---|
| `hadoop-hdfs` | The server: NameNode, DataNode, JournalNode, SecondaryNameNode, plus balancer/mover/EC tooling and the server-side protocol implementations. |
| `hadoop-hdfs-client` | The client library: `DistributedFileSystem`, `DFSClient`, `DFSInputStream`/`DFSOutputStream`, the `DataTransferProtocol` wire format, short-circuit shared-memory support, WebHDFS client. |
| `hadoop-hdfs-httpfs` | `HttpFSServer`: a REST (WebHDFS-semantics) gateway fronting HDFS over HTTP for clients outside the Hadoop network perimeter. |
| `hadoop-hdfs-native-client` | `libhdfs`: the JNI C library wrapping `hdfs.h` over the Java client (`hdfs.c`, `jclasses.c`, `jni_helper.c`). |
| `hadoop-hdfs-nfs` | NFSv3 gateway: presents an HDFS tree as an NFS mount, staging writes through `DFSClient`. |
| `hadoop-hdfs-rbf` | Router-Based Federation: a stateless (per-request) routing layer in front of multiple federated namespaces, backed by a `StateStore`. |

`hadoop-hdfs` divides its server code under `org.apache.hadoop.hdfs.server` into:
`namenode`, `datanode`, `blockmanagement` (NameNode-side block bookkeeping),
`common` (storage/`Storage`, `GenerationStamp`, `HdfsServerConstants`),
`protocol` (server-side extensions), `qjournal` (JournalNode), plus
`balancer`, `mover`, `sps`, `diskbalancer`, `aliasmap`, and `tools` (admin CLIs,
including `DFSZKFailoverController`).

---

## 2. `hadoop-hdfs` — the server

### 2.1 NameNode: namespace, FSImage and FSEditLog

**Purpose.** Holds the namespace (the directory tree and per-file block lists) and
per-file metadata (permissions, quotas, EC policy, encryption zones). All metadata
is authoritative only here; block *content* lives on DataNodes.

**Key classes** (`org.apache.hadoop.hdfs.server.namenode`):

- `NameNode` — lifecycle wrapper: config, `NameNodeHttpServer`, `NameNodeRpcServer`,
  and the `Namesystem` (an `FSNamesystem`). It is stateless with respect to
  namespace data; `FSNamesystem` holds the state.
- `FSNamesystem` — the central state object. Owns `FSDirectory`, `BlockManager`,
  `LeaseManager`, the edit log, and the `FSNamesystemLock` (a read/write lock;
  namespace mutations take the write lock, RPC reads the read lock).
- `FSDirectory` — in-memory namespace tree of `INode` objects plus an
  `INodeMap` (id → INode), `NameCache` for frequently used names, and the
  per-op helpers (`FSDirWriteFileOp`, `FSDirDeleteOp`, `FSDirRenameOp`,
  `FSDirStatAndListingOp`, ...): each namespace RPC is implemented as a static
  method on one of these, with `FSEditLog.log*` calls interleaved.
- `INode` hierarchy — `INodeDirectory`, `INodeFile` (holding
  `BlockInfo` array, `FileUnderConstructionFeature` while being written),
  `INodeSymlink`, `INodeReference` (snapshot/DST references), wrapped by
  `INodeWithAdditionalFields` for compact feature storage (`AclFeature`,
  `XAttrFeature`, `DirectoryWithQuotaFeature`).
- `FSImage` — persistence manager: loads/saves the fsimage file, rolls the edit
  log, and coordinates `NNStorage` (the storage directory abstraction handling
  VERSION files, `fsimage_*` / `edits_*` segment naming, and storage state
  inspection via `FSImageTransactionalStorageInspector` /
  `FSImagePreTransactionalStorageInspector`). `FSImageFormat` /
  `FSImageFormatProtobuf` (with `FSImageFormatPBINode`) define the binary
  format; `SaveNamespaceContext` drives a save.
- `FSEditLog` — the write-ahead log. Writes every namespace mutation through a
  `JournalSet` (an aggregation of `JournalManager`s — `FileJournalManager` for
  local `edits_*` files, `QuorumJournalManager` in HA). Ops are protobuf
  records (`FSEditLogOp`, `FSEditLogOpCodes`) with double buffering in
  `EditsDoubleBuffer`. `FSEditLogAsync` optionally makes edit logging
  asynchronous. Reading/loading is `FSEditLogLoader`, which also replays
  transaction ids and computes `ContentCounts`.
- `NNStorageRetentionManager` — purges old fsimages/edits past the configured
  retention once a newer checkpoint exists.

**Data structures.** The namespace is a heap-resident `INode` tree (not a btree);
block metadata is a map described in 2.2; edit log is an ordered sequence of
protobuf ops with monotonically increasing transaction ids.

**Runtime behaviour.** A mutation RPC (e.g. `create`) acquires the namesystem
write lock, mutates the `INode` tree via the `FSDir*Op`, then appends a
corresponding op to `FSEditLog`, which fans out to all journals (local files,
possibly a QJM quorum) and returns once the required number have synced. On
restart, `FSImage` loads the latest fsimage and replays the subsequent edit
segments through `FSEditLogLoader` to rebuild the tree before serving RPCs.

### 2.2 Block management

`org.apache.hadoop.hdfs.server.blockmanagement` — NameNode-side bookkeeping of
where every block replica lives, minus the namespace itself.

**Key classes:**

- `BlockManager` — the orchestrator. Holds `BlocksMap`, `DatanodeManager`,
  `HeartbeatManager`, `InvalidateBlocks`, `CorruptReplicasMap`,
  `PendingReconstructionBlocks`, `LowRedundancyBlocks`, `BlockStoragePolicySuite`,
  `CacheManager` cooperation, and `BlockManagerSafeMode`.
- `BlocksMap` — the core map from `Block` → `BlockInfo`, backed by
  `LightWeightGSet` sized to ~1/16 of heap. Each `BlockInfo` (or
  `BlockInfoStriped` for EC, `BlockInfoContiguous` for replicated) references
  its `BlockCollection` (the `INodeFile`) and its replica descriptors.
- `BlockInfo` / `BlockUnderConstructionFeature` — while a file is open, its
  blocks hold `ReplicaUnderConstruction` entries recording which DataNodes are
  expected to have a replica in progress.
- `DatanodeManager` — registry of DataNodes: `DatanodeDescriptor` (per-node
  replication queues, storage array of `DatanodeStorageInfo`), `Host2NodesMap`,
  topology resolution, decommissioning via `DatanodeAdminManager` and the
  `DatanodeAdmin*Monitor` classes.
- `HeartbeatManager` — tracks liveness; `heartbeatCheck()` marks dead nodes,
  and it computes `DatanodeStats` (capacity/usage).
- Placement: `BlockPlacementPolicy` with the default
  `BlockPlacementPolicyDefault` (writer-local + off-rack replica), plus
  `AvailableSpaceBlockPlacementPolicy`, `BlockPlacementPolicyRackFaultTolerant`,
  and upgrade-domain/node-group variants selected via `BlockPlacementPolicies`.
- Reconstruction: `UnderReplicatedBlocks` state is tracked by
  `LowRedundancyBlocks`; work items are `ReplicationWork`/`ErasureCodingWork`
  assembled in `BlockReconstructionWork` and scheduled by
  `computeDatanodeWork()`.
- `InvalidateBlocks` — per-datanode lists of blocks to delete (over-replicated,
  corrupt, or aborted writes).
- `BlockIdManager` — allocates legacy vs striped block ids
  (`SequentialBlockIdGenerator`).

**Runtime behaviour (replication monitoring and invalidation).**
Heartbeats and block reports (2.7) feed `BlockManager.processReport()`, which
diffs the reported replica set against `BlocksMap` and records stale/extra
replicas into `InvalidateBlocks` and missing replicas into
`LowRedundancyBlocks`. On each heartbeat cycle `computeDatanodeWork()` pops
reconstruction work and sends it as first-block commands in the next
heartbeat; DataNodes then copy via the inter-DataNode
`OP_TRANSFER_BLOCK` path. Invalidation commands ride the same channel. Blocks
reported corrupt go to `CorruptReplicasMap` and healthy replicas are
invalidated; when good replicas drop below policy, reconstruction is queued.
`BlockManagerSafeMode` gates reconstruction until enough block reports have
arrived after startup (`incrementSafeBlockCount`, `checkSafeMode`).

### 2.3 Leases and safemode

**Leases** (`LeaseManager` in `namenode`): every open-for-write file is owned
by a `Lease` keyed by client name, tracked in sorted renewal-time order and in
an inode-id → lease map. Clients renew periodically;
`FSNamesystem`'s lease monitor expires hard leases and, for files in pipeline
recovery, triggers `internalReleaseLease` so the last block is finalized or
abandoned. Closing the file (or client crash + expiry) removes the lease via
`removeLease`.

**Safemode**: on startup the NameNode is read-only until (a) a configured
fraction of blocks have at least the minimal number of live replicas — counted
per storage by `BlockManagerSafeMode` (`incrementSafeBlockCount`,
`blockTotal`/`blockSafe` accounting), and (b) operational criteria pass
(edit-log resources available via `NameNodeResourceChecker`/`NameNodeResourcePolicy`,
no low-disk storage dirs). Current trunk keeps startup-block accounting in
`BlockManagerSafeMode`, while `FSNamesystem` tracks `manualSafeMode` and
`resourceLowSafeMode` flags and exposes the `SafeMode` interface
(`isInSafeMode`, `isInStartupSafeMode`). Mutating RPCs fail with
`SafeModeException` via `FSNamesystem.checkNameNodeSafeMode()` until
`leaveSafeMode()`, triggered automatically or by `-safemode leave`.

### 2.4 HA: active/standby, ZKFC, QuorumJournalManager, JournalNode

**Packages**: `namenode.ha` (NameNode state machine), `qjournal.client` /
`qjournal.server` (QJM and JournalNode), `tools.DFSZKFailoverController`.

- `HAState` hierarchy — `ActiveState` and `StandbyState` driven through
  `HAContext` on the `NameNode`. The standby replays edits
  (`EditLogTailer` tails the shared log; `StandbyCheckpointer` performs
  checkpoints, see 2.6) but serves no namespace mutations and issues no block
  work for itself.
- `BootstrapStandby` initializes a new standby's storage from the active's
  fsimage via `TransferFsImage`.
- **QuorumJournalManager** (`qjournal.client.QuorumJournalManager`): the shared
  edit-log implementation for HA. It owns an `AsyncLoggerSet` of
  `IPCLoggerChannel`s, one per JournalNode; edits are sent in parallel and a
  `QuorumCall` requires a majority to acknowledge (`QuorumException`
  otherwise). Segment recovery during failover uses
  `SegmentRecoveryComparator` to `finalizeLogSegment`/`recoverUnfinalizedSegments`
  the latest segment consistently across journals. `QuorumOutputStream` and
  `EditsDoubleBuffer` mirror the local-file path.
- **JournalNode** (`qjournal.server.JournalNode`, `Journal`, `JNStorage`,
  `JournalNodeRpcServer`, `JournaledEditsCache`): persists edit segments to
  disk per nameservice/journal-id, rejects out-of-order writes
  (`NewerTxnIdException`), and serves edits back over its HTTP servlet
  (`GetJournalEditServlet`) to standbys and the `SecondaryNameNode`.
- **ZKFC** (`tools.DFSZKFailoverController`): per-NameNode daemon that holds an
  ephemeral znode for the active lock, health-checks its local NameNode, and
  on failure fences the old active (via RPC ACL and/or a configured fence
  method) before the standby transitions `StandbyState` → `ActiveState`.

**Failover sequence (runtime).** ZKFC of the active detects failure (or is
itself killed and its znode expires) → ZKFC fences the old active → standby's
ZKFC acquires the lock and calls `transitionToActive` → the new active
finalizes any unfinalized journal segment through QJM recovery, becomes
writable, and DataNodes' `BPOfferService` notices the new active (both
NameNodes are registered from startup; the DataNode switches which NN it sends
heartbeats/commands to) → clients re-resolve via
`org.apache.hadoop.hdfs.NameNodeProxies` failover proxy provider. The standby
is normally warm because `EditLogTailer` kept it within a few transactions.

### 2.5 NameNode RPC and HTTP

- `NameNodeRpcServer` implements `ClientProtocol`
  (hdfs-client `org.apache.hadoop.hdfs.protocol.ClientProtocol`:
  create/append/addBlock/complete, getBlockLocations, renames, listing, EC and
  snapshot ops), `DatanodeProtocol` (register, `sendHeartbeat`,
  `blockReport`, `incrementalBlockReport`, `blockReceivedAndDeleted`,
  error reports), `NamenodeProtocol` (SecondaryNameNode/CheckpointNode
  access), and admin/HA protocols. Server-side PB translation lives under
  `org.apache.hadoop.hdfs.protocolPB` in both hdfs and hdfs-client modules.
- `NameNodeHttpServer` hosts the web UI, `FsckServlet` (delegating to
  `NamenodeFsck`), `ImageServlet` (fsimage transfer for checkpoints),
  `StartupProgressServlet`, and the `IsNameNodeActiveServlet` used by
  routers/proxies. Security and token selection go through
  `HDFSPolicyProvider` and the `NameNode` token secret managers.

### 2.6 SecondaryNameNode and checkpointing

`SecondaryNameNode` (a separate role, *not* a hot standby): periodically
downloads the fsimage and the tail of the edit log from the active NameNode,
merges them in memory with `FSImage.loadFSImage` + `FSEditLogLoader`, and
uploads the new fsimage back (`TransferFsImage`), prompting the NameNode to
roll its edit log and adopt the checkpoint (a `CheckpointSignature`
handshake). This bounds edit-log replay time after restart. In an HA cluster
the equivalent job belongs to `ha.StandbyCheckpointer` running on the standby,
triggered by checkpoint interval/txn-count thresholds; `ha.EditLogTailer`
keeps the standby's namespace current between checkpoints. A related legacy
role is `BackupNode` (with `BackupImage`/`BackupJournalManager`), which
streams edits and keeps a full in-memory replica.

### 2.7 DataNode

`org.apache.hadoop.hdfs.server.datanode` — the storage worker. One per machine
(may serve multiple namespaces via multiple block pools).

**Key classes:**

- `DataNode` — the daemon: registers with all NameNodes of its configured
  nameservices, serves `ClientDatanodeProtocol` (block local path info for
  short-circuit reads, block recovery, checksums) and hosts the
  `DataXceiverServer` on the streaming port.
- `BPOfferService` + `BPServiceActor` — one actor per NameNode per block pool:
  registration loop, heartbeat loop (sends `sendHeartbeat`, executes returned
  commands: replication, invalidation, cache, `DNA_ERASURE_CODING_RECONSTRUCTION`),
  and periodic full block reports (with lease-gated throttling from
  `BlockReportLeaseManager` on the NN side). `BlockPoolManager` manages the
  set across namespace changes.
- `DataXceiver` — the streaming-protocol handler (implements the
  `DataTransferProtocol` receiver): `OP_READ_BLOCK` → `BlockSender`,
  `OP_WRITE_BLOCK` → `BlockReceiver`, plus transfer-block, block checksum,
  copy, and client-read-status ops.
- `BlockReceiver` — receives a stream of packets, verifies chunk checksums,
  writes via its `ReplicaInPipeline`, forwards to the next pipeline node, and
  emits per-packet acks back through the pipeline; `PacketResponder` thread
  finalizes on the last ack. `BlockRecoveryWorker` implements lease-recovery
  (`RecoveryInProgress`/RUR handling) when the NN asks for
  `recoverBlock`.
- Dataset: `fsdataset.FsDatasetImpl` (built by `FsDatasetFactory`) — manages
  volumes through `FsVolumeList` of `FsVolumeImpl`, each containing a
  `BlockPoolSlice` per namespace. `ReplicaMap` (per-volume, per-pool) maps
  `ExtendedBlock` → `ReplicaInfo` states: `FinalizedReplica`,
  `ReplicaBeingWritten`, `ReplicaWaitingToBeRecovered`,
  `ReplicaUnderRecovery` (and `ProvidedReplica` for external storage).
  `FsDatasetAsyncDiskService` offloads deletes/moves; `FsDatasetCache` +
  `MappableBlock*` implement persistent memory caching (`mmap`/PMem loaders);
  `RamDiskReplicaTracker` + `RamDiskAsyncLazyPersistService` implement
  lazy-persist writes from RAM disk to disk.
- Scanners: `BlockScanner` (dispatcher) with per-volume `VolumeScanner`
  verify block checksums in the background and report corrupt replicas to the
  NN (`ReportBadBlockAction`); `DirectoryScanner` reconciles the on-disk block
  directory tree against `ReplicaMap` and adds/removes replica records.
- `ShortCircuitRegistry` advertises shm slots enabling client-side
  zero-copy, OS-file-descriptor-passing reads.
- `IncrementalBlockReportManager` batches "block received/deleted" messages
  and ships them opportunistically instead of one RPC per block.

**Runtime behaviour.** Heartbeats every `dfs.heartbeat.interval` (default 3s)
carry load and capacity and return the NN's command queue; a full block report
runs on a configurable period, rebuilding the NN's view of that storage
(`BlockManager.processReport`). Writes arrive over the pipeline (2.8); reads
are served by `BlockSender` streaming packet-size chunks with checksum
verification. Dead volumes are reported via `Storage` error reporters and
excluded by `FsVolumeList`.

### 2.8 DataTransferProtocol and the write pipeline

`org.apache.hadoop.hdfs.protocol.datatransfer.DataTransferProtocol` (in
`hadoop-hdfs-client`, implemented by both sides) is the binary streaming
protocol between client ↔ DataNode and DataNode ↔ DataNode: `OP_READ_BLOCK`,
`OP_WRITE_BLOCK`, `OP_TRANSFER_BLOCK`, `OP_BLOCK_CHECKSUM`, `OP_COPY_BLOCK`,
`OP_REPLACE_BLOCK` and the `Status`/ack frames.

**End-to-end pipeline write flow** (`DFSOutputStream` + `DataStreamer` on the
client; `create` RPCs against `ClientProtocol`):

1. `DistributedFileSystem.create` → `DFSClient.create` → NameNode `create`
   (lease granted, file marked under construction).
2. Client fills a `DFSPacket` from its `write()` calls; `DataStreamer`
   (a daemon thread) queues packets (`dataQueue` → `ackQueue`).
3. When the first packet is ready, DataStreamer calls `addBlock` on the
   NameNode; `FSNamesystem.getAdditionalBlock` runs the placement policy and
   returns a `LocatedBlock` with the chosen DataNodes (pipeline of length
   = replication factor, or EC stripe targets).
4. DataStreamer opens the pipeline: `OP_WRITE_BLOCK` to the first DataNode;
   that DataNode's `BlockReceiver` streams on to node 2, and so on, then each
   node acks back up the chain.
5. DataStreamer moves the packet from `ackQueue` when the last node's ack
   arrives (`waitForAckedSeqno` blocks the writer until its seqno is acked).
   Heartbeat packets keep empty-pipeline acks flowing while the client is idle.
6. On `dfs.heartbeat.interval`-like boundaries (actually the block size), the
   client calls `addBlock` again to allocate the next block; the previous
   block is finalized on the pipeline.
7. `close()` flushes and acks remaining packets, calls `complete` on the
   NameNode; the NameNode finalizes the last block (committing its
   generation stamp and size) once all reported replicas agree — this is
   `BlockManager.commitOrCompleteLastBlock`.
8. Failure handling: a pipeline node dies → write/ack times out → DataStreamer
   calls `setupPipelineForAppendOrRecovery` → error propagation down the
   pipeline, removal of the dead node from `LocatedBlock`, and
   `triggerBlockReport`/pipeline recovery; the NN is told via
   `updatePipeline` (`FSDirWriteFileOp.updatePipelineForReplica`) so the block's
   `ReplicaUnderConstruction` list matches the new pipeline.

EC files use the same skeleton with `DFSStripedOutputStream` + `StripedDataStreamer`
(one streamer per cell/stripe writer) and erasure-coded packets.

### 2.9 Other server subsystems

- **Balancer** (`server.balancer`): `Balancer` + `Dispatcher` move blocks from
  over-utilized to under-utilized nodes using the DataNode-to-DataNode copy
  protocol, throttled by bandwidth (`dfs.datanode.balance.bandwidthPerSec`).
- **Mover** (`server.mover`) and **StoragePolicySatisfier** (`server.sps`):
  migrate block replicas between storage tiers to match the file's
  `BlockStoragePolicy`.
- **DiskBalancer** (`server.diskbalancer`, DataNode-side `DiskBalancer`):
  rebalance volumes within one node.
- **ViewFS/aliasmap** (`server.aliasmap`): in-memory/levelDB view of
  "provided" storage mappings used by `ProvidedStorageMap`/`ProvidedVolumeImpl`.

---

## 3. `hadoop-hdfs-client` — the client library

### 3.1 DistributedFileSystem

`org.apache.hadoop.hdfs.DistributedFileSystem` is the `FileSystem`
implementation users see. It wraps a `DFSClient`, translates Hadoop-common
`Path`/`FileStatus` calls into `ClientProtocol` RPCs, and adds HDFS-specific
ops: `setStoragePolicy`/`getStoragePolicy`, EC ops, snapshot ops, recovery,
`getAllStoragePolicies`, and the `HdfsDataInputStream`/`HdfsDataOutputStream`
wrappers around `DFSInputStream`/`DFSOutputStream`.

### 3.2 DFSClient

`DFSClient` owns client identity, configuration (`DFSConfigKeys`), the RPC
proxy to the NameNode (`NameNodeProxiesClient`), the `ClientContext` with
shared caches: `PeerCache` (reusable sockets to DataNodes),
`KeyProviderCache`, `DeadNodeDetector`, hedged-read metrics
(`DFSHedgedReadMetrics`), and short-circuit/shm plumbing
(`shortcircuit` package: `DomainSocketFactory`, `ShortCircuitCache`). It also
implements `getLinkTarget`, token renewal, and `DFSInotifyEventInputStream`
for edit-log event streaming.

### 3.3 Write path: DFSOutputStream and DataStreamer

Described end-to-end in 2.8. Class roles: `DFSOutputStream` buffers client
writes into `DFSPacket`s (checksummed chunks) and queues them;
`DataStreamer` allocates blocks, builds the pipeline, streams packets, and
tracks acks; append/recovery variants use
`setupPipelineForAppendOrRecovery`. Striped writes use
`DFSStripedOutputStream` with `StripedDataStreamer`s writing cells in
parallel across the EC target list.

### 3.4 Read path: DFSInputStream, short-circuit and hedged reads

- `DFSClient.open` → `DFSInputStream.openInfo()`: `getBlockLocations` fetches
  `LocatedBlocks` (block list + per-block `DatanodeInfo[]` sorted by
  proximity/topology).
- `read()` picks the closest replica: `chooseDataNode` walks the sorted
  location list, skipping dead/ignored nodes and re-sorting on failures
  (`DFSClient chooseDataNode` retries with backoff on `BlockReader` failures).
- `getBlockReader` selects a reader strategy (`ReaderStrategy`): short-circuit
  local reads via `BlockReaderLocal`/`BlockReaderLocalLegacy` (using
  `ClientDatanodeProtocol.getBlockLocalPathInfo` and shm slots), or a remote
  `RemoteBlockReader2` speaking `DataTransferProtocol` `OP_READ_BLOCK` to
  `BlockSender` on the DataNode.
- Hedged reads (when `dfs.client.hedged.read.*` is enabled and a read exceeds
  the threshold): `DFSInputStream` launches a second read against a *different*
  replica concurrently (`hedgedReadOps`/`hedgedReadOpsLoopNumForTesting`
  metrics in `DFSHedgedReadMetrics`) and uses whichever finishes first.
- `readBlockLength` probes the block's real length (used for the last block
  under construction); `DeadNodeDetector` blacklists unreachable DataNodes
  proactively. Corruption on read triggers `reportBadBlocks`.

### 3.5 ViewFS and HAR

`ViewFileSystem`/`InodeTree` and the HAR archive format live in
hadoop-common/hadoop-tools, not here; HDFS's only involvement is that
`ViewDistributedFileSystem` in this module lets ViewFS route into
`DistributedFileSystem` directly.

---

## 4. `hadoop-hdfs-rbf` — Router-Based Federation

### 4.1 Router

`org.apache.hadoop.hdfs.server.federation.router.Router` is a standalone
process (not a NameNode) that exposes the full NameNode RPC surface —
`RouterClientProtocol` (client protocol), `RouterRpcServer` (PB server),
`RouterRpcClient`/`ConnectionManager`/`ConnectionPool` (pooled RPC
connections to every subcluster), plus `RouterHttpServer` and
`RouterAdminServer` (federation administration: mount table add/remove/update,
`RouterQuotaManager`/`Quota` for namespace/quotas across subclusters).
`NamenodeHeartbeatService`/`NamenodeStatusReport` feed membership state;
`MountTableRefresherService` propagates mount-table updates to RBF caches.

### 4.2 StateStore

`server.federation.store.StateStoreService` is the Router's pluggable record
store (backends under `store.driver`: local file, ZooKeeper, SQL), exposing
typed `RecordStore`s cached in memory by `StateStoreCache` and refreshed by
`StateStoreCacheUpdateService` (`ConnectionMonitor` for driver health):
`MembershipStore` (subcluster/NameNode membership and capacity states),
`MountTableStore` (the path → subcluster mapping), and nameservice/quota
records. Records are protobuf under `store.records`.

### 4.3 Federation resolution and admin

- `resolver.MountTableResolver` implements both `ActiveNamenodeResolver`
  (for heartbeats) and `FileSubclusterResolver`: resolves a request path
  through the mount table into `PathLocation` → `RemoteLocation`(s);
  `MultipleDestinationMountTableResolver` supports fan-out mounts.
- `MembershipNamenodeResolver` orders live namenodes
  (`NamenodePriorityComparator`) so each RPC lands on the best subcluster
  namenode.
- Admin CLI: `hdfs dfsrouteradmin` (`RouterAdminServer` backend); the Router
  itself is started by `hdfs dfsrouter`. `DFSRouter` is the main class.

**Behaviour.** A client RPC hits the Router; the path is resolved against the
cached mount table; the Router forwards the call through a pooled connection
to the owning subcluster's active NameNode and relays the response — namespace
data still lives in the subclusters, the Router is stateless per request
except for the cached StateStore tables.

---

## 5. `hadoop-hdfs-httpfs` — WebHDFS REST gateway

`org.apache.hadoop.fs.http.server.HttpFSServer` (Jersey app booted by
`HttpFSServerWebApp`/`HttpFSServerWebServer`) exposes the WebHDFS REST API
(`/webhdfs/v1`) for clients that cannot run the Hadoop jars or reach the
NameNode RPC: `FSOperations` translates REST parameters into `FileSystem`
calls (against HDFS via `DistributedFileSystem` with a proxy-user
`UserGroupInformation`), `HttpFSParametersProvider` declares the parameter
types, `HttpFSAuthenticationFilter` handles Kerberos/delegation-token
authentication, and `CheckUploadContentTypeFilter`/`HttpFSExceptionProvider`
round out request validation. It is a stateless HTTP → RPC gateway: the HTTP
verbs map to NameNode and DataNode operations, with data PUT/GET streamed
through the gateway process.

---

## 6. `hadoop-hdfs-nfs` — NFS gateway

`org.apache.hadoop.hdfs.nfs.nfs3.RpcProgramNfs3` implements the NFSv3 protocol
served via portmap/mount from `PrivilegedNfsGatewayStarter`; `DFSClientCache`
maintains per-user `DFSClient`/`DFSInputStream` instances, `WriteManager` +
`OpenFileCtx`/`WriteCtx` stage (and reorder) client writes into HDFS through
the write path, committing them on `COMMIT`/`fsync`. It is a single-node NFS
server in front of HDFS — a POSIX convenience layer, not a cluster role —
and requires the gateway host to be configured as a proxy user.

---

## 7. `hadoop-hdfs-native-client` — libhdfs

The JNI C library (`src/main/native/libhdfs`: `hdfs.c`, `jclasses.c`,
`jni_helper.c`, headers in `include/hdfs.h`). It boots a JVM in-process and
forwards each `hdfs*` C call onto the Java client (the same `DistributedFileSystem`
/`DFSClient` machinery above), caching jclass/jmethodID handles for
reflection-free dispatch. Everything HDFS-specific — pipeline writes, hedged
reads, HA resolution — is inherited from the Java layer; the module adds only
the C API, thread attach/detach handling, and the build glue (CMake).

---

## 8. Behaviour summary

- **NameNode namespace (FSImage/FSEditLog/FSDirectory)**: in-memory `INode`
  tree; every mutation is applied under the namesystem write lock and then
  journaled to `FSEditLog` (local files or QJM quorum); restart = load latest
  fsimage + replay edits via `FSEditLogLoader`.
- **Block management**: `BlocksMap` (LightWeightGSet) is the truth of block →
  replica locations; heartbeats + block reports diff against it; redundancy
  gaps become `LowRedundancyBlocks` work issued as heartbeat commands;
  excess/corrupt replicas become `InvalidateBlocks` deletes.
- **Leases/safemode**: `LeaseManager` enforces single-writer and recovers
  abandoned files; startup safemode (block-threshold + resource checks in
  `BlockManagerSafeMode`/`FSNamesystem`) keeps the NameNode read-only until
  replication state is trustworthy.
- **HA**: shared edits via `QuorumJournalManager` majority writes to
  JournalNodes; standby tails edits (`EditLogTailer`) and checkpoints
  (`StandbyCheckpointer`); ZKFC elects and fences; failover = fence, acquire
  znode, QJM segment recovery, DataNodes re-target the new active.
- **NameNode RPC**: `NameNodeRpcServer` serves `ClientProtocol`/`DatanodeProtocol`
  (+ PB shims); HTTP server hosts UI, fsck, and fsimage transfer.
- **Checkpointing**: `SecondaryNameNode` (non-HA) or `StandbyCheckpointer`
  (HA) merges fsimage + edit tail and ships it back, bounding restart replay.
- **DataNode**: `BPOfferService`/`BPServiceActor` heartbeat (~3s) and block
  report loops per NameNode; `DataXceiver` serves reads (`BlockSender`) and
  pipeline writes (`BlockReceiver`); `FsDatasetImpl`/`FsVolumeImpl`/`ReplicaMap`
  manage replica lifecycle across volumes; `BlockScanner`/`DirectoryScanner`
  verify and reconcile; `IncrementalBlockReportManager` streams received/deleted
  events.
- **Write pipeline**: client buffers packets in `DFSOutputStream`, `DataStreamer`
  allocates blocks (`addBlock`), opens a replication pipeline over
  `DataTransferProtocol`, advances packets on acks, recovers pipelines on
  failure (`setupPipelineForAppendOrRecovery` + `updatePipeline`), and
  finalizes with `complete`.
- **Read path**: `DFSInputStream` sorts replicas by proximity, reads via
  short-circuit local or remote block readers, hedges slow reads to a second
  replica, and reports corrupt/dead nodes.
- **Client module**: `DistributedFileSystem` is the user-facing `FileSystem`
  over `DFSClient`; ViewFS/HAR are outside this module.
- **RBF**: Router resolves paths via the cached `MountTableStore` and proxies
  RPCs to the right subcluster's active NameNode; `StateStoreService`
  (file/ZK/SQL) is the backing record store; `dfsrouteradmin` manages mounts,
  quotas, and subcluster state.
- **HttpFS**: stateless WebHDFS REST gateway translating HTTP to
  `FileSystem`/NameNode calls with proxy-user auth.
- **NFS gateway**: NFSv3 server staging writes into HDFS through per-user
  `DFSClient`s (`WriteManager`/`OpenFileCtx`).
- **libhdfs**: thin JNI wrapper over the Java client; all HDFS behaviour is
  delegated to hadoop-hdfs-client.

---

## 9. Concurrency

All names in this section were checked against the trunk source at the paths
given. Each subsection states the concurrency contract a PR must preserve.

### 9.1 NameNode: the `FSNamesystem` global lock

- `FSNamesystemLock` (`server.namenode.FSNamesystemLock`) wraps a single
  `ReentrantReadWriteLock` (`coarseLock`) and mimics `ReadWriteLock` without
  implementing it. Fairness is configurable via
  `dfs.namenode.fslock.fair` (`DFS_NAMENODE_FSLOCK_FAIR_KEY`).
- Lock acquisition is mode-scoped through `org.apache.hadoop.hdfs.util.RwLockMode`
  (`GLOBAL` vs `BM`). Contract:
  - Namespace mutations take `writeLock(RwLockMode.GLOBAL)` (e.g.
    `FSNamesystem.recoverLease`). Mutating RPCs therefore serialize fully.
  - DataNode heartbeats (`FSNamesystem.handleHeartbeat`) take only
    `readLock(RwLockMode.BM)`, so heartbeats run concurrently with each other
    and with namespace *reads*, but not with namespace writes.
  - **Full block reports serialize against everything**:
    `BlockManager.processReport` calls `namesystem.writeLock(RwLockMode.GLOBAL)`
    for the whole report diff. A full block report blocks all namespace
    mutations until it completes.
- Long-hold diagnostics are built in: the lock tracks
  `longestReadLockHeldInfo` / `longestWriteLockHeldInfo`, `LongAdder`
  counters `numReadLockLongHold` / `numWriteLockLongHold`, and can emit a
  warning (with suppressible repeat rate) when a read lock is held too long.
  Lock metrics are exported under `<lockName>ReadLock` / `<lockName>WriteLock`.
- `FSEditLog.logSync()` is invoked *after* the write lock is released in some
  paths (e.g. `recoverLease` calls `getEditLog().logSync()` in its `finally`)
  so that sync latency does not extend lock hold time.

### 9.2 NameNode RPC handler threads

- `NameNodeRpcServer` creates one RPC server per endpoint: the client RPC
  (`dfs.namenode.rpc-address`), the service RPC
  (`dfs.namenode.servicerpc-address`, used by DataNodes/BackupNodes), and the
  lifeline RPC (`dfs.namenode.lifeline.rpc-address`).
- Handler counts: `dfs.namenode.handler.count` (default 10) for client RPCs,
  `dfs.namenode.service.handler.count` for the service RPC, and lifeline
  handlers derived from `dfs.namenode.lifeline.handler.ratio`. Handlers are
  plain daemon threads; a caller blocks (queues in the RPC layer) when all
  handlers are busy.
- Per-call sequence inside a handler: `checkOperation(OperationCategory.READ/
  WRITE/UNCHECKED)` gates against the HA state (standby/observer reject
  writes), then `getPermissionChecker()` builds an `FSPermissionChecker` for
  the remote user, then the op function under the appropriate lock mode.

### 9.3 BlockManager background threads and work multisets

- **`RedundancyMonitor`**: a single `Daemon` (`redundancyThread`, named
  `"RedundancyMonitor"`) running `BlockManager.RedundancyMonitor.run()`,
  which periodically calls `computeDatanodeWork()`. It is the only producer
  of replication/reconstruction work on the NameNode.
- Work is drawn from the `LowRedundancyBlocks` multiset (priority queues by
  replica deficit) and materialized as `ReplicationWork` or
  `ErasureCodingWork` (both extending `BlockReconstructionWork`). Per-iteration
  throughput is bounded by:
  - `dfs.namenode.replication.max-streams` (default 2) — max replication work
    per DataNode per iteration;
  - `dfs.namenode.replication.work.multiplier.per.iteration` (default 2) —
    cluster-wide multiplier on max-streams.
- **`PendingReconstructionMonitor`**: inner daemon of
  `PendingReconstructionBlocks` (`timerThread`); it re-scans
  pending-reconstruction entries after a timeout and times out replicas that
  never reported, keeping the multiset from growing unbounded.
- Reconstruction is delivered as first-block heartbeat commands
  (`DatanodeCommand`), not as a separate RPC; the DataNode's
  `BPServiceActor` executes them on its own thread.

### 9.4 DataNode concurrency

- **`FsDatasetImpl` locking**: synchronization goes through a
  `DataSetLockManager` implemented by
  `org.apache.hadoop.hdfs.server.common.DataNodeLockManager`, with
  hierarchical `LockLevel.BLOCK_POOL` and `LockLevel.DIR` read/write locks.
  Locks are acquired as `AutoCloseableLock` in try-with-resources (e.g.
  `lockManager.readLock(LockLevel.DIR, ...)` for scans,
  `writeLock(LockLevel.DIR, ...)` for replica mutation). A PR must take the
  right level: block-pool locks only exclude same-pool writers, dir locks
  exclude same-directory writers.
- **`DataXceiverServer` is thread-per-connection**: the accept loop spawns
  `new Daemon(datanode.threadGroup, DataXceiver.create(peer, datanode, this))`
  for every accepted peer. Concurrent xceivers are capped by
  `dfs.datanode.max.transfer.threads` (`DFS_DATANODE_MAX_RECEIVER_THREADS`,
  default 4096); when `curXceiverCount > maxXceiverCount` the server refuses
  the connection with an `IOException`. There is no thread pool reuse for
  xceivers (unlike the RPC handler model).
- **Pipeline acks**: each pipeline write runs one `PacketResponder` thread
  (inner class of `BlockReceiver`, implements `Runnable`) that consumes acks
  from downstream, forwards acks upstream, and finalizes the replica when
  `lastPacketInBlock` is acked. The writer thread (`BlockReceiver`) and the
  `PacketResponder` communicate through queues; both must be stopped during
  pipeline recovery.
- **`BPOfferService` / `BPServiceActor`**: one `BPServiceActor` thread per
  NameNode per block pool (registration + heartbeat + block-report loop), so
  a DataNode talking to two NameNodes runs two actors concurrently and
  independently. `IncrementalBlockReportManager` batches
  received/deleted events and flushes them opportunistically on the same
  actor thread.
- **Scanners**: `DirectoryScanner` runs on a schedule of
  `dfs.datanode.directoryscan.interval` (default 21600 s) with
  `dfs.datanode.directoryscan.threads` (default 1) worker threads, batching
  reconciliation (`dfs.datanode.reconcile.blocks.batch.size`,
  `dfs.datanode.reconcile.blocks.batch.interval`). `BlockScanner` dispatches
  per-volume `VolumeScanner` threads that verify block checksums in the
  background with throttling, reporting corrupt replicas to the NN via
  `ReportBadBlockAction`.
- Helper thread pools: `FsDatasetAsyncDiskService` (deletes/moves),
  `RamDiskAsyncLazyPersistService` (lazy persist writes), `FsDatasetCache`
  with `MappableBlock` loaders.

### 9.5 LeaseManager timeouts

- `LeaseManager` holds `softLimit` (`HdfsConstants.LEASE_SOFTLIMIT_PERIOD`)
  and `hardLimit` (from `dfs.namenode.lease-hard-limit-sec`,
  `DFS_LEASE_HARDLIMIT_KEY`), settable via `setLeasePeriod`.
- Its `Monitor` daemon (`shouldRunMonitor` flag) scans for expired leases;
  a lease whose `lastUpdate` exceeds `hardLimit` (`hardLimitExpired`) makes
  the inode eligible for `internalReleaseLease` → block recovery, even if the
  client is still alive but stalled. A PR must not assume lease expiry only
  happens after client death.

### 9.6 HA fence/failover concurrency

- `DFSZKFailoverController` (extends common `ZKFailoverController`) runs a
  `HealthMonitor` thread probing its local NameNode, and uses
  `ActiveStandbyElector` (hadoop-common) for the ZooKeeper ephemeral active
  lock. Election loss triggers fencing of the old active *before* the
  standby may transition.
- `transitionToActive` on the new active takes the namesystem write lock
  during state entry; the tailer is designed for this:
  `EditLogTailer` documents that it must take
  `writeLockInterruptibly(RwLockMode.GLOBAL)` because
  "the transitionToActive RPC takes the write lock before calling
  tailer.stop() — so if we're not interruptible, it will deadlock".
- Standby-side concurrency: `EditLogTailer` and `StandbyCheckpointer` run
  their own threads against the standby's `FSNamesystem` while RPC servers
  are up but rejecting writes (`StandbyException`).
- `FSEditLogAsync` uses a separate mutex from the edit-log sync thread
  specifically "to avoid possible deadlock when stopping the thread", and
  re-offers work to the monitor carefully to avoid deadlock with the sync
  thread.

### 9.7 Known deadlock hazards recorded in code comments

These are load-bearing invariants a refactor must keep:

1. `FSImageFormat` / `FSImageFormatProtobuf` use
   `unprotectedGetNamespaceInfo()` while saving because the save coordinator
   already holds the read lock; taking a second read lock from the saver
   thread risks the fairness-related deadlock documented as **HDFS-2223**
   under a fair lock.
2. `EditLogTailer` must use `writeLockInterruptibly` (see 9.6) — a plain
   write lock deadlocks against `transitionToActive`.
3. `ShortCircuitRegistry.createNewMemorySegment` "drops the registry lock to
   prevent deadlock" before registering the shm with the socket watcher
   (`RegisteredShm#handle` may fire concurrently).
4. `DataNode.shutdown()` "can only be called by the offerService thread.
   Otherwise, deadlock might occur" — shutdown is not reentrant from RPC
   threads.
5. `FSEditLogAsync` lock-ordering comments (separate mutex, monitor
   re-offer) as above.

---

## 10. Security

### 10.1 Kerberos principals (per role)

| Role | Config key (constant verified) |
|---|---|
| NameNode | `dfs.namenode.kerberos.principal` (alias `dfs.namenode.user.name.key`) |
| DataNode | `dfs.datanode.kerberos.principal` (alias `dfs.datanode.user.name.key`) |
| SecondaryNameNode | `dfs.secondary.namenode.kerberos.principal` |
| JournalNode | `dfs.journalnode.kerberos.principal` (+ `dfs.journalnode.kerberos.internal.spnego.principal` for its HTTP server) |
| Web UI / HttpFS SPNEGO | `dfs.web.authentication.kerberos.principal` |
| Balancer / Mover / SPS | `dfs.balancer.kerberos.principal`, `dfs.mover.kerberos.principal`, `dfs.sps.kerberos.principal` |

Global HTTP policy is `dfs.http.policy` (`DFS_HTTP_POLICY_KEY`, e.g.
`HTTP_ONLY` / `HTTPS_ONLY` / `HTTP_AND_HTTPS`), shared with WebHDFS
(`WebHdfsFileSystem` reads the same key).

### 10.2 SASL in the DataTransferProtocol

- Client side (`hadoop-hdfs-client`,
  `org.apache.hadoop.hdfs.protocol.datatransfer.sasl`):
  `SaslDataTransferClient`, `SaslParticipant`,
  `SaslResponseWithNegotiatedCipherOption`, `DataEncryptionKeyFactory`,
  `DataTransferSaslUtil`.
- Server side (`hadoop-hdfs`): `SaslDataTransferServer` and
  `InvalidMagicNumberException` (mismatched SASL handshake → rejection).
- Protection level is `dfs.data.transfer.protection` (`authentication`,
  `integrity`, `privacy`). When SASL is in play the
  `OP_READ_BLOCK`/`OP_WRITE_BLOCK` streams are negotiated through these
  classes before any block bytes flow.
- Note: trunk has SASL only for the *data transfer* path here; there is no
  separate `SaslRpcServer` in the HDFS modules (RPC SASL lives in
  hadoop-common's RPC layer).

### 10.3 Block access tokens

- Token definition: `org.apache.hadoop.hdfs.security.token.block.BlockTokenIdentifier`
  (in `hadoop-hdfs-client`); the NameNode-side secret manager is
  `BlockPoolTokenSecretManager` (in `hadoop-hdfs`,
  `security/token/block`), which multiplexes per-block-pool
  `BlockTokenSecretManager` instances.
- Enabled by `dfs.block.access.token.enable` (default **false** in trunk).
- Enforcement: the NameNode embeds tokens in `LocatedBlock`s (`getBlockLocations`,
  `addBlock`); the DataNode validates each `OP_READ_BLOCK`/`OP_WRITE_BLOCK`
  request against the token (block id, pool id, modes, expiry) before
  serving. Token verification failures surface as `InvalidToken` and are
  logged on the DataNode; there is **no** per-block-read audit log on the
  DataNode path (auditability of block access is via RPC-level audit on the
  NameNode, see §11).
- Lease/blocked-token plumbing: `DataTransferSaslUtil` ties SASL negotiation
  and token use together (`SaslDataTransferClient` sends the token when
  `dfs.block.access.token.enable` is on).

### 10.4 Delegation tokens

- NameNode side: `DelegationTokenSecretManager`
  (`server.namenode/security/token/delegation`), with keys
  `dfs.namenode.delegation.token.renew-interval` (default 1 day),
  `dfs.namenode.delegation.token.max-lifetime` (default 7 days),
  `dfs.namenode.delegation.token.always-use`.
- Client side: `DFSClient.Renewer extends TokenRenewer` (inner class of
  `DFSClient`) handles get/renew/cancel through `ClientProtocol`
  (`getDelegationToken`/`renewDelegationToken`/`cancelDelegationToken`).
- WebHDFS keeps its own renewal via `TokenAspect` (`TokenAspect.TokenManager
  extends TokenRenewer`, `WebHdfsFileSystem implements
  DelegationTokenRenewer.Renewable`).

### 10.5 HDFS permission model (enforcing classes)

- Enforcement entry point per RPC: `FSNamesystem.getPermissionChecker()`
  returns an `FSPermissionChecker`; checks go through
  `FSDirectory.checkPathAccess(pc, iip, FsAction)` and friends
  (`checkOwner`, `checkAncestorAccess`, …). Gated by `dfs.permissions.enabled`
  (`isPermissionEnabled`).
- INode storage: `FsPermission` bits on `INodeWithAdditionalFields` (user/
  group from `UserGroupInformation`), the sticky bit on directories
  (`INodeDirectory`), ACLs as `AclFeature`, extended attributes as
  `XAttrFeature`. Snapshot/append interplay is handled in
  `INodeReference`.
- Operation type tagging: `FSPermissionChecker.setOperationType(...)` is
  set per RPC for audit-context consistency.
- Admin bypass: superuser is configured via hadoop-common
  `hadoop.security.superuser.group` semantics evaluated inside
  `FSPermissionChecker` (not HDFS-specific config).

### 10.6 Encryption zones

- `EncryptionZoneManager` (NameNode) maintains the zone tree; file-level
  crypto metadata is `org.apache.hadoop.fs.FileEncryptionInfo` (in
  hadoop-common, serialized into `HdfsFileStatus` and `LocatedBlock`).
- Key providers are resolved client-side by `DFSClient` via
  `KeyProviderCache` (`getKeyProviderUri()` reads the configured provider
  URI, `dfs.encryption.key.provider.uri`); EDEKs are decrypted on the client
  (`DFSClient#create` path) — the NameNode never sees key material.
- A PR touching EZs must preserve the invariant: the NameNode stores only
  encrypted DEKs + `FileEncryptionInfo`; plaintext keys exist only on
  clients holding the KeyProvider.

### 10.7 Web, Router and HttpFS auth

- NameNode web UI / WebHDFS: SPNEGO with the
  `dfs.web.authentication.kerberos.principal` principal via
  `NameNodeHttpServer`; delegation tokens accepted as
  `DelegationTokenAuthenticatedURL` credentials.
- HttpFS: `HttpFSAuthenticationFilter` (Kerberos + delegation-token authn);
  operations run as a **proxy user** (`doAs` `UserGroupInformation` built in
  `FSOperations`), so HttpFS requires the gateway principal to be configured
  as a hadoop proxy user on the NameNode.
- Router (RBF): `RouterAdminServer` captures
  `UserGroupInformation.getCurrentUser().getShortUserName()` as
  `routerOwner` for mount-table ACLs; `RouterRpcServer` forwards the remote
  UGI to subclusters (proxy-user semantics again). StateStore backends
  (e.g. ZooKeeper) apply their own ACLs.
- NFS gateway: requires proxy-user configuration for the gateway principal
  (documented in §6 above).

---

## 11. Logging and auditability

### 11.1 NameNode audit log

- Every successful/failed client operation is recorded by
  `FSNamesystem.logAuditEvent(boolean succeeded, String cmd, String src[,
  String dst, ...])` (overloads add `UserGroupInformation` and remote IP via
  `NameNode.getRemoteUser()` / `Server.getRemoteIp()`).
- The sink is pluggable: `AuditLogger` interface with implementations
  `DefaultAuditLogger` (the standard log4j audit log) and `TopAuditLogger`
  (feeds the NNTop metrics). Selection via
  `dfs.namenode.audit.loggers` (`DFS_NAMENODE_AUDIT_LOGGERS_KEY`).
  `HdfsAuditLogger` is the base class carrying the
  `HdfsAuditLogger.AuditEvent` payload (caller, cmd, src, dst, permit
  counts).
- Audit events are emitted from the op layer (after permission checks), so a
  PR adding a new op must call the `logAuditEvent` path or its operation
  will be invisible to audit consumers.

### 11.2 Edit log as the durability log

- `FSEditLog` fans every namespace mutation out to a `JournalSet` of
  `JournalManager`s; records are `FSEditLogOp` protobufs with
  monotonically increasing txids. `EditsDoubleBuffer` provides the
  write/sync double buffering on every output stream.
- The sync contract is in `EditLogOutputStream`:
  `flushAndSync(boolean durable)` is the abstract durability point
  (`EditLogFileOutputStream` implements it with pre-allocation + force;
  `QuorumOutputStream` implements it as a QJM majority ack;
  `EditLogBackupOutputStream` forwards to a BackupNode). `flush()` without
  `durable` only moves buffered bytes to the OS.
- `FSEditLog.logSync()` blocks the caller until its txid has been
  `flushAndSync`ed on all required journals (`isSyncRunning` single-flight
  flag); `logSyncAll()` (comment at `FSEditLog` line ~614) waits for *all*
  written (not just current) edits — used before checkpoint/roll. A PR that
  adds an op must append it inside the write-locked section and rely on the
  existing `logEdit`/`logSync` pairing; skipping `logSync` after an
  exception is only allowed for `StandbyException` (see `recoverLease`).
- `FSEditLogAsync` optionally decouples append from sync (background sync
  thread), preserving the same on-disk ordering.

### 11.3 DataNode logs and metrics

- `DataNodeMetrics` (context `dfs`, name `DataNodeActivity`) exposes counters
  incl. `blocksRead`, `blocksWritten`, `volumeFailures`, heartbeat and
  block-report timers; `NameNodeMetrics` (`NameNodeActivity`) counts
  `createFileOps`, `filesCreated`, `filesAppended`, `getBlockLocations`,
  `getListingOps`, `deleteFileOps`, `fileInfoOps`, etc.
- Cluster-state metrics: `FSNamesystemMBean` (`getTotalLoad`, stale node
  counts via `getNumStaleNodes` on `DatanodeManager`), and
  `NameNodeMXBean.getLiveNodes()` (JSON map of live DataNodes incl. admin
  state and usage — this is the `numLiveNodes`-style view surfaced in JMX).
- JMX/MBeans registered in trunk: `NameNodeMXBean`, `NameNodeStatusMXBean`
  (HA state), `FSNamesystemMBean`, `BlockStatsMXBean`,
  `ReplicatedBlocksMBean`, `ECBlockGroupsMBean`, `SnapshotStatsMXBean`,
  `DataNodeMXBean`, `JournalNodeMXBean`, `BalancerMXBean`,
  `ExternalSPSMXBean`, `SecondaryNameNodeInfoMXBean`. Metrics contexts are
  `dfs` (via hadoop-metrics2); the DataNode also runs a periodic
  metrics-logger (`stopMetricsLogger()` in `shutdown`).
- Block-scanner findings are *not* only local logs: `VolumeScanner` reports
  corrupt replicas to the NameNode with `ReportBadBlockAction`, which lands
  in `CorruptReplicasMap` — i.e. corruption audit is a first-class NN state.

### 11.4 Block-token audit note

The NameNode audit log records authorization decisions on RPCs; block-token
*use* on the DataNode is verified in `DataXceiver` before any I/O and on
failure raises `InvalidToken` (logged, connection aborted). There is no
separate "block access" audit log in trunk; auditability of raw block reads
relies on DataNode INFO/WARN logs and metrics.

---

## 12. Integration points

### 12.1 Ports and addresses (config keys verified)

| Endpoint | Key | Default port |
|---|---|---|
| NameNode client RPC | `dfs.namenode.rpc-address` | 8020 (`DFS_NAMENODE_RPC_PORT_DEFAULT`) |
| NameNode service RPC | `dfs.namenode.servicerpc-address` | (unset by default; falls back to rpc-address) |
| NameNode lifeline RPC | `dfs.namenode.lifeline.rpc-address` | (unset by default) |
| NameNode HTTP | `dfs.namenode.http-address` | `DFS_NAMENODE_HTTP_PORT_DEFAULT` (9870) |
| NameNode HTTPS | `dfs.namenode.https-address` | `DFS_NAMENODE_HTTPS_PORT_DEFAULT` (9871) |
| DataNode data transfer | `dfs.datanode.address` | (see `DFS_DATANODE_ADDRESS_KEY`) |
| DataNode HTTP | `dfs.datanode.http.address` | (see `DFS_DATANODE_HTTP_ADDRESS_KEY`) |
| DataNode IPC | `dfs.datanode.ipc.address` | (see `DFS_DATANODE_IPC_ADDRESS_KEY`) |
| JournalNode RPC | `dfs.journalnode.rpc-address` | 8485 (`DFS_JOURNALNODE_RPC_PORT_DEFAULT`) |
| JournalNode HTTP | `dfs.journalnode.http-address` | 8480 (`DFS_JOURNALNODE_HTTP_PORT_DEFAULT`) |

IPC framing for all RPC endpoints is hadoop-common's RPC (protobuf, IPC
version headers); the *streaming* port (DataNode data transfer) speaks
`DataTransferProtocol`, not IPC.

### 12.2 Wire protocols (interface files verified)

- `ClientProtocol` (`hadoop-hdfs-client`,
  `org.apache.hadoop.hdfs.protocol`) — client ↔ NameNode; PB shim
  `ClientNamenodeProtocolTranslatorPB` (client) and
  `ClientNamenodeProtocolServerSideTranslatorPB` (server).
- `DatanodeProtocol` (`hadoop-hdfs`, `server.protocol`) — DataNode ↔ NameNode
  (register/heartbeat/blockReport/commands).
- `NamenodeProtocol` (`server.protocol`) — SecondaryNameNode/CheckpointNode
  ↔ NameNode (checkpoint/getBlockKeys).
- `ClientDatanodeProtocol` (`hadoop-hdfs-client`,
  `org.apache.hadoop.hdfs.protocol`) — client ↔ DataNode (short-circuit
  `getBlockLocalPathInfo`, `recoverBlock`, refresh).
- `InterDatanodeProtocol` (`server.protocol`) — DataNode ↔ DataNode
  (pipeline recovery: `initReplicaRecovery`/`updateReplicaUnderRecovery`).
- `JournalProtocol` (`server.protocol`) — BackupNode edit streaming.
- `QJournalProtocol` (`qjournal.protocol`) — NameNode (QJM client) ↔
  JournalNode (`isFormatted`, `journal`, `startLogSegment`,
  `finalizeLogSegment`, `getEditLogManifest`).
- `DataTransferProtocol` — the binary streaming protocol (see §2.8), spoken
  on the DataNode data-transfer port by client and peers.

### 12.3 ZooKeeper usage

- **ZKFC** (`tools.DFSZKFailoverController`): holds the HA active lock as an
  ephemeral znode through `ActiveStandbyElector` (hadoop-common
  `org.apache.hadoop.ha`), health-checks via `HealthMonitor`; fencing
  methods come from hadoop-common `dfs.ha.fencing.methods`.
- **RBF StateStore**: `StateStoreDriver` has a ZooKeeper driver
  (`store.driver.zk`) storing membership/mount-table records.
- HDFS itself (NN/DN) has no direct ZooKeeper dependency — ZK is confined
  to the failover controller and the RBF StateStore.

### 12.4 Standby and observer readers

- Trunk supports observer NameNodes: `NameNode.OBSERVER_STATE` is
  `new StandbyState(true)`; enabled by
  `dfs.namenode.observer.enabled` (`DFS_NAMENODE_OBSERVER_ENABLED_KEY`).
  Observers tail edits like standbys and may serve *reads*; consistency is
  the client's concern via `ObserverReadProxyProvider`
  (`hadoop-hdfs-client`, `namenode.ha`), including
  `RouterObserverReadProxyProvider` for RBF and
  `ObserverReadProxyProviderWithIPFailover`.
- Config keys: `dfs.ha.namenodes.<ns>`, `dfs.namenode.rpc-address.<ns>.<nn>`
  for each member; failover proxy provider via
  `dfs.client.failover.proxy.provider.<ns>`.

### 12.5 fsimage / editlog on-disk layout

- File names come from `NNStorage.NameNodeFile` (verified enum):
  `fsimage` (`IMAGE`), `fsimage.ckpt` (`IMAGE_NEW`), `edits`
  (`EDITS`), `edits_inprogress_<startTxId>` (`EDITS_INPROGRESS`),
  `seen_txid` (`SEEN_TXID`), plus legacy/tmp names (`fstime`,
  `fsimage_rollback`, `edits.new`, `edits_tmp`,
  `fsimage_legacy_oiv`).
- Transaction ids: `edits_<startTxId>_<endTxId>` finalized segments;
  `FSImageTransactionalStorageInspector` picks the newest consistent
  fsimage + segment chain at startup; `seen_txid` records the expected
  last txid so a half-written rollout is detected.
- JournalNode layout mirrors this per journal-id
  (`JNStorage`, `current/` segment files + `paxos` dir for segment-recovery
  state).

### 12.6 Key config keys referenced by the requirements below

`dfs.namenode.handler.count` (10), `dfs.namenode.service.handler.count`,
`dfs.namenode.lifeline.handler.ratio`, `dfs.namenode.fslock.fair`,
`dfs.namenode.replication.max-streams` (2),
`dfs.namenode.replication.work.multiplier.per.iteration` (2),
`dfs.namenode.lease-hard-limit-sec`,
`dfs.namenode.audit.loggers`, `dfs.namenode.delegation.token.*`,
`dfs.namenode.observer.enabled`, `dfs.datanode.max.transfer.threads` (4096),
`dfs.datanode.directoryscan.interval` (21600),
`dfs.datanode.directoryscan.threads` (1),
`dfs.datanode.ec.reconstruction.threads`, `dfs.block.access.token.enable`
(false), `dfs.data.transfer.protection`, `dfs.http.policy`,
`dfs.encryption.key.provider.uri`, `dfs.heartbeat.interval` (3).

---

## 13. Non-functional requirement candidates

Each statement is intended to be testable against a PR diff; the reference
class is the enforcement point.

1. **[NN concurrency]** Namespace mutations must serialize on the
   `FSNamesystem` write lock (`FSNamesystemLock`); a PR must not perform
   I/O (fsync, network) while holding it beyond the existing
   `logEdit`/`logSync` pattern. *Ref: `FSNamesystem`, `FSNamesystemLock`.*
2. **[NN concurrency]** Full block reports (`BlockManager.processReport`)
   must take the GLOBAL write lock; any change that holds the GLOBAL lock
   longer must preserve long-hold metrics (`longestWriteLockHeldInfo`)
   and the `RwLockMode` split (heartbeats take `BM` read lock only).
   *Ref: `BlockManager.processReport`, `FSNamesystem.handleHeartbeat`.*
3. **[NN concurrency]** Replication/reconstruction work must only be
   produced by the single `RedundancyMonitor` thread and bounded per
   iteration by `dfs.namenode.replication.max-streams` ×
   `work.multiplier.per.iteration`. *Ref: `BlockManager.RedundancyMonitor`,
   `computeDatanodeWork`.*
4. **[NN concurrency]** Pending-reconstruction entries must be timed out by
   `PendingReconstructionMonitor`; the multiset must never grow
   unbounded on silent DataNode failure. *Ref: `PendingReconstructionBlocks`.*
5. **[DN concurrency]** `FsDatasetImpl` replica mutations must hold the
   `DataNodeLockManager` lock at the correct level (`DIR` vs `BLOCK_POOL`)
   and use `AutoCloseableLock`; scans may take read locks only.
   *Ref: `FsDatasetImpl`, `DataNodeLockManager`.*
6. **[DN concurrency]** The data-transfer port must remain
   thread-per-connection (`DataXceiverServer`) with a hard cap of
   `dfs.datanode.max.transfer.threads` (4096 default); exceeding the cap
   must refuse the connection rather than queue. *Ref:
   `DataXceiverServer.run`.*
7. **[DN concurrency]** Every pipeline write must run exactly one
   `PacketResponder` thread that finalizes the replica only after the last
   ack (`lastPacketInBlock`); recovery must stop both the receiver and the
   responder. *Ref: `BlockReceiver`, `BlockReceiver.PacketResponder`.*
8. **[DN concurrency]** `DirectoryScanner` must run at
   `dfs.datanode.directoryscan.interval` (6h default) with
   `directoryscan.threads` workers and must reconcile the on-disk tree
   against `ReplicaMap` in bounded batches. *Ref: `DirectoryScanner`.*
9. **[Leases]** A hard-expired lease (`> dfs.namenode.lease-hard-limit-sec`)
   must trigger lease recovery (`internalReleaseLease`) even if the client
   later resumes; the client must then observe recovery rather than
   continue writing. *Ref: `LeaseManager.Monitor`, `LeaseManager.hardLimitExpired`.*
10. **[HA]** Failover must fence the old active before the standby
    transitions to active, and the tailer must use
    `writeLockInterruptibly` to avoid the documented
    transitionToActive deadlock. *Ref: `DFSZKFailoverController`,
    `EditLogTailer`.*
11. **[HA durability]** Every edit must be acknowledged only after
    `flushAndSync(durable)` on a majority of journals (`QuorumCall`
    majority) in HA, or on all configured journals in the local case.
    *Ref: `FSEditLog`, `EditLogOutputStream.flushAndSync`,
    `QuorumJournalManager`.*
12. **[Security — RPC]** NameNode/DataNode/JournalNode service principals
    must be configurable per role (`dfs.{namenode,datanode,journalnode}.kerberos.principal`)
    and the HTTP layer must honour `dfs.http.policy` +
    `dfs.web.authentication.kerberos.principal`. *Ref: `DFSConfigKeys`,
    `NameNodeHttpServer`.*
13. **[Security — data transfer]** When `dfs.data.transfer.protection` is
    set to anything above `authentication` or block tokens are enabled,
    block transfers must negotiate SASL (`SaslDataTransferClient`/`Server`)
    before any block bytes are sent, and must reject mismatched handshakes
    (`InvalidMagicNumberException`). *Ref: `datatransfer.sasl` package.*
14. **[Security — tokens]** Block tokens must be scoped per block pool via
    `BlockPoolTokenSecretManager`, verified on the DataNode before serving
    I/O, and gated by `dfs.block.access.token.enable`. *Ref:
    `BlockTokenIdentifier`, `BlockPoolTokenSecretManager`.*
15. **[Security — delegation tokens]** Delegation tokens must renew within
    `dfs.namenode.delegation.token.renew-interval` (1d default), never
    exceed `max-lifetime` (7d default), and be renewable/cancellable only
    through `DFSClient.Renewer` (owner or authenticated renewer).
    *Ref: `DelegationTokenSecretManager`, `DFSClient.Renewer`.*
16. **[Security — permissions]** Every mutating RPC must construct an
    `FSPermissionChecker` (`getPermissionChecker()`) and pass permission
    checks through `FSDirectory.check*` before touching the namespace;
    safemode must reject mutations with `SafeModeException`.
    *Ref: `FSNamesystem`, `FSPermissionChecker`.*
17. **[Security — encryption zones]** The NameNode must persist only
    encrypted DEKs (`FileEncryptionInfo`/XAttrs); plaintext key material
    must exist solely in the client-side `KeyProvider` (`KeyProviderCache`),
    and a PR must not route keys through NN RPCs or logs. *Ref:
    `EncryptionZoneManager`, `DFSClient.getKeyProvider`.*
18. **[Auditability]** Every client op (success or failure) must emit an
    audit event through `FSNamesystem.logAuditEvent` via the configured
    `AuditLogger` (`dfs.namenode.audit.loggers`); new ops are incomplete
    without an audit call. *Ref: `FSNamesystem.logAuditEvent`,
    `DefaultAuditLogger`.*
19. **[Auditability]** Edit-log durability must be observable: sync
    completion per txid via `FSEditLog.logSync`, and checkpoints must call
    `logSyncAll()` before rolling; segment names must carry
    start/end txids matching `NNStorage.NameNodeFile` naming. *Ref:
    `FSEditLog`, `NNStorage`.*
20. **[Observability]** DataNode/NameNode metrics must expose the existing
    counters (`blocksRead`, `blocksWritten`, `volumeFailures`,
    `createFileOps`, `getBlockLocations`, …) in context `dfs` and remain
    JMX-visible through the existing MBeans (`DataNodeMXBean`,
    `NameNodeMXBean.getLiveNodes()`, `FSNamesystemMBean`,
    `NameNodeStatusMXBean`). *Ref: `DataNodeMetrics`, `NameNodeMetrics`.*
21. **[Observability]** Corruption found by background verification must be
    reported to the NameNode (not only logged) and recorded in
    `CorruptReplicasMap`. *Ref: `VolumeScanner`, `ReportBadBlockAction`.*
22. **[Integration]** New RPCs must be added to both the PB service
    definition and the matching translator
    (`ClientNamenodeProtocolTranslatorPB` / server-side translator) and
    published through `HDFSPolicyProvider` so Kerberos ACLs cover them.
    *Ref: `protocolPB` package, `HDFSPolicyProvider`.*
23. **[Integration]** HA observer reads must never serve stale writes:
    observers (`OBSERVER_STATE`, `dfs.namenode.observer.enabled`) serve
    reads only, and clients must use `ObserverReadProxyProvider`-family
    providers to guarantee read-your-writes ordering. *Ref:
    `NameNode.OBSERVER_STATE`, `ObserverReadProxyProvider`.*
24. **[Integration]** On-disk metadata layout (fsimage/`edits_inprogress_`/
    `seen_txid` naming per `NNStorage.NameNodeFile`) must stay backward
    compatible or bump `LAYOUT_VERSION`; startup inspection
    (`FSImageTransactionalStorageInspector`) must fail closed on
    inconsistent txids. *Ref: `NNStorage`, `FSImage`.*
25. **[DN lifecycle]** `DataNode.shutdown()` must only be invoked from the
    offerService thread (per its deadlock contract); any new shutdown
    trigger must route through that thread or be made reentrant-safe.
    *Ref: `DataNode.shutdown`.*
