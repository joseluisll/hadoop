# Hadoop Tools & Cloud Storage Connectors — Requirements

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

**Status:** DRAFT — 2026-11-14
**Source doc:** `notes/architecture/hadoop-tools-cloud-architecture.md`
**Grounding:** `hadoop-cloud-storage-project/` and `hadoop-tools/` in this tree; every class, config key and constant below was read off the source doc and spot-verified against the source tree.

---

## Scope and derivation method

Covers the `hadoop-cloud-storage-project` object-store connectors and the `hadoop-tools`
aggregation (S3A, ABFS, ADL Gen1, Aliyun OSS, GCS, BOS, COS, TOS, OBS, DistCp, HAR, streaming/pipes,
minor utilities), so a reviewer reading a PR diff can say "this satisfies / violates FR-7" without
re-deriving intent from the architecture document. Out of scope: HDFS, YARN, MapReduce core, and the
Kafka client library (hadoop-kafka ships only a Metrics2 sink).

- **Derivation.** Each requirement comes from a named architecture-doc section (`arch §n[.m]`) plus the key class(es) embodying it. Nothing is invented: if a statement is neither in the arch doc nor verifiable in the source tree, it is not a requirement.
- **ID scheme.** `FR-x` functional; `NFR-C-x` concurrency; `NFR-S-x` security; `NFR-L-x` logging;
  `NFR-I-x` integration. Numbering runs per document and is stable — do not renumber.
- **NFR-candidate mapping.** arch §8 lists 20 candidates (`R-NFR-1`…`R-NFR-20`), all mapped (and
  superseded) by the NFR IDs in §2.5; where they disagree, this document wins.

## 1. Functional requirements

### 1.1 Shared connector contract

- **FR-1 — Scheme binding.** Every object-store connector must expose its `FileSystem` implementation
  through the `fs.<scheme>.impl` config key with the exact classes of the binding table:
  `s3a://`→`org.apache.hadoop.fs.s3a.S3AFileSystem`, `gs://`→`org.apache.hadoop.fs.gs.GoogleHadoopFileSystem`,
  `abfs://`/`abfss://`→`AzureBlobFileSystem`/`SecureAzureBlobFileSystem`, `adl://`→`AdlFileSystem`,
  `oss://`→`AliyunOSSFileSystem`, `obs://`→`OBSFileSystem`, `cosn://`→`CosNFileSystem`,
  `bos://`→`BaiduBosFileSystem`, `tos://`→`org.apache.hadoop.fs.tosfs.TosFileSystem`,
  `har://`→`org.apache.hadoop.fs.HarFileSystem` (arch §1.2, core-default.xml binding table).
- **FR-2 — AbstractFileSystem binding.** Each connector must also provide the FileContext
  `AbstractFileSystem` binding via `fs.AbstractFileSystem.<scheme>.impl` (`S3A`, `Gs`, `Abfs`/`Abfss`,
  `Adl`, `OSS`, `OBS`, `CosN`, `BOS`, `TosFS`, `HarFs`); flat-store bindings are `DelegateToFileSystem`
  subclasses that simply wrap the corresponding `FileSystem` (arch §1.1, §1.2).
- **FR-3 — ServiceLoader discovery and lookup order.** A connector shipping
  `META-INF/services/org.apache.hadoop.fs.FileSystem` must be discoverable without config entries;
  scheme resolution must keep the two-layer order `FileSystem.getFileSystemClass(scheme, conf)`:
  `fs.<scheme>.impl` config key first, then the ServiceLoader-discovered `SERVICE_FILE_SYSTEMS` map
  (arch §1.2, `FileSystem.loadFileSystems()`).
- **FR-4 — Deferred object visibility.** Output streams on flat object stores
  (`S3ADataBlocks`, `OBSDataBlocks`, `OSSDataBlocks`, `BosBlockBuffer`, `CosNOutputStream`) must
  buffer locally and upload via multipart PUT so that a visible object appears only at close/commit
  time — a PR must not make partially written objects visible to readers (arch §1.1).
- **FR-5 — Rename emulation with typed failures.** Directory-renaming on flat stores must remain
  list-source-prefix → copy objects → delete originals, and failures must surface as the
  connector's typed exceptions (`RenameFailedException` in OBS, S3A and Aliyun trees;
  `FileConflictException` in OBS) rather than silent partial success (arch §1.1, §1.5).

### 1.2 S3A — hadoop-aws (deepest)

- **FR-6 — S3AFileSystem entry-point contracts.** `S3AFileSystem` must continue to implement
  `StreamCapabilities`, `AWSPolicyProvider`, `DelegationTokenProvider`, `IOStatisticsSource`,
  `AuditSpanSource<AuditSpanS3A>`, `ActiveThreadSpanSource<AuditSpanS3A>` and `StoreContextFactory`;
  removal of any of these interfaces is a breaking API change (arch §2.1).
- **FR-7 — Store-mediated S3 access.** All S3 interactions must funnel through the `S3AStore`
  interface (implemented by `impl.S3AStoreImpl`, assembled via `S3AStoreBuilder`) exposing
  `StoreContext`, `RequestFactory`, read/write capacity acquisition, statistics contexts and
  operation counters; direct SDK calls from filesystem-level code are a review-blocking regression
  (arch §2.1, `S3AStore`, `StoreContext`).
- **FR-8 — Read path.** Reads must be lazy positioned range reads with read-ahead via
  `S3AInputStream`, selected by `S3AInputPolicy` (normal/random/fadvise), with the optional
  `prefetch/` stack (`S3APrefetchingInputStream`, `S3ARemoteInputStream`,
  `S3ABlockManager`/`S3ACachingBlockManager`) for asynchronous block prefetch; vectored reads go
  through `VectoredIOContext` (arch §2.1).
- **FR-9 — Write path.** Writes must use `S3ABlockOutputStream` + `S3ADataBlocks`
  (`DiskBlock`, `ByteBufferBlock`, `ArrayBlock`) with multipart upload through
  `WriteOperationHelper`/`WriteOperations` (arch §2.1).
- **FR-10 — Directory emulation and listings.** S3A must synthesize directory markers, track marker
  hygiene during deletes via `impl.DirMarkerTracker`, page prefix listings through
  `Listing`/`S3ListRequest`/`S3ListResult`, and carry metadata in `S3AFileStatus`/
  `S3ALocatedFileStatus` (arch §2.1).
- **FR-11 — Committer selection.** `S3ACommitterFactory` must select the `OutputCommitter`
  implementation by configured committer name, with `COMMITTER_NAME_MAGIC` resolving to
  `MagicS3GuardCommitterFactory`; a new committer must be reachable through this selection, not by
  bypassing the factory (arch §2.1).
- **FR-12 — Magic committer.** The magic committer (`commit/magic/MagicS3GuardCommitter`) must
  require the magic directory feature: task output under a `_magic/…` prefix is intercepted by the
  magic-commit trackers (`InMemoryMagicCommitTracker`, `S3MagicCommitTracker`,
  `MagicCommitTracker`) and turned into pending multipart uploads, and job commit completes those
  uploads in place — no data copied or renamed to the destination directory (arch §2.1,
  `MagicCommitIntegration`/`MagicCommitPaths`).
- **FR-13 — Staging committers and pending-set format.** Staging committers
  (`commit/staging/StagingCommitter`, subclasses `DirectoryStagingCommitter`,
  `PartitionedStagingCommitter`) must write task output to a local temporary directory, at
  task-commit upload each file without completing the final multipart operation and persist the
  pending commits in the `commit/files/` JSON pending-set format (`SinglePendingCommit`,
  `PendingSet`, `SuccessData`, `UploadEtag`), and at job-commit list and commit (or abort) all
  pending PUTs, honoring `ConflictResolution` modes (fail/replace/append/skip) (arch §2.1).

### 1.3 ABFS — hadoop-azure

- **FR-14 — Front-end/store split.** `AzureBlobFileSystem` (implements `IOStatisticsSource`) must
  delegate all store work to `AzureBlobFileSystemStore` (built via `AzureBlobFileSystemStoreBuilder`),
  with the `fs.azure.*` config surface parsed by `AbfsConfiguration` (arch §2.2).
- **FR-15 — Endpoint selection and URI forms.** Requests must go through `AbfsClient` subclasses —
  `AbfsDfsClient` for hierarchical-namespace accounts (ACLs, atomic renames) or `AbfsBlobClient` for
  the flat blob endpoint — selected by hierarchical-namespace support, never by a user-supplied key;
  schemes are `abfs://` (HTTP) and `abfss://` (TLS) with `Abfs`/`Abfss` FileContext bindings, and the
  account name is parsed from the authority up to the first dot (arch §2.2, §7.2, `AbfsClient`).
- **FR-16 — ABFS stream buffering.** Reads use `AbfsInputStream` read-ahead strategies
  (`AbfsAdaptiveInputStream`, `AbfsPrefetchInputStream`); writes use `AbfsOutputStream` buffering
  blocks (`AbfsBlobBlock`, `AbfsBlock`, `AbfsBlockStatus`) and flush on `hflush`/`hsync` only where
  the backend allows it (arch §2.2).

### 1.4 GCS — hadoop-gcp

- **FR-17 — Single-bucket rooting.** `GoogleHadoopFileSystem` is rooted in a single bucket for its
  lifetime: all Hadoop paths are relative to that bucket and no other bucket is ever touched —
  cross-bucket access is out of contract and a PR adding silent cross-bucket resolution violates
  this requirement (arch §1.4, §7.2).
- **FR-18 — GCS layering and configuration.** The store layer
  (`GoogleCloudStorage`/`GoogleCloudStorageFileSystem`, read/write channels adapted by
  `GoogleHadoopFSInputStream`/`GoogleHadoopOutputStream`) must sit beneath the front-end, with
  configuration/credentials in `GoogleHadoopFileSystemConfiguration`/`HadoopCredentialsConfiguration`
  and the `fs.gs.*` key family (`fs.gs.project.id`, `fs.gs.working.dir` default `/`,
  `fs.gs.block.size` 64 MB, `fs.gs.outputstream.buffer.size` 8 MB, `fs.gs.inputstream.fadvise`
  default `Fadvise.RANDOM`, plus in-place-seek limit, min-range-request size, gzip-encoding,
  rewrite chunk size, marker file pattern) (arch §1.4, §7.2).

### 1.5 Other object stores

- **FR-19 — Huawei OBS modes and SSE.** `OBSFileSystem` must distinguish POSIX-bucket access
  (`OBSPosixBucketUtils`) from object-bucket access (`OBSObjectBucketUtils`), support server-side
  encryption via `SseWrapper`, build its client through `OBSClientFactory`/
  `DefaultOBSClientFactory`, and surface rename conflicts as `RenameFailedException`/
  `FileConflictException` (arch §1.5).
- **FR-20 — Tencent COS SPI.** `CosNFileSystem` must delegate object work to the
  `NativeFileSystemStore` SPI (`CosNativeFileSystemStore`) with `CosNInputStream`/
  `CosNOutputStream` buffered range reads and block-buffered multipart writes (`BufferPool`),
  server-side copies via `CosNCopyFileTask`, and credentials via `auth/COSCredentialsProviderList`
  (arch §1.5).
- **FR-21 — TOS commit framework.** `TosFileSystem extends RawFileSystem` (FileContext binding
  `TosFS extends RawFS`) must keep its own commit framework (`commit/` — `Committer`,
  `CommitterFactory`, `MagicOutputStream`, `Pending`, `PendingSet`, `SuccessData`,
  `commit/mapred/Committer`) mirroring the S3A magic-committer design; changes to S3A commit
  semantics must be evaluated for the TOS mirror (arch §1.5).
- **FR-22 — Baidu BOS plumbing.** `BaiduBosFileSystem` must back onto
  `BosNativeFileSystemStore`/`HierarchyBosNativeFileSystemStore` over `BosClientProxy`, with
  pluggable BCE credentials under `credentials/` (`BceCredentialsProvider`, config- and env-based)
  and retry policies `BosRandomRetryPolicy`/`BosTryOnceThenFail` (arch §1.5).
- **FR-23 — Aliyun OSS read-ahead and copy rename.** `AliyunOSSFileSystem` must use background
  read-ahead (`AliyunOSSFileReaderTask`/`ReadBuffer`), block-buffered output (`OSSDataBlocks`,
  `AliyunOSSBlockOutputStream`), server-side copy for rename (`AliyunOSSCopyFileTask`), and
  publish output statistics (`OutputStreamStatistics`, `BlockOutputStreamStatistics`) (arch §2.4).
- **FR-24 — ADLS Gen1 maintenance mode.** `AdlFileSystem` (scheme `adl://`) stays a REST client with
  `AdlFsInputStream`/`AdlFsOutputStream`, Azure AD OAuth via `AzureADTokenProvider` adapters
  (`SdkTokenProviderAdapter`, `TokenProviderType`, keys in `AdlConfKeys`); ADLS Gen1 is in
  maintenance mode and ABFS is the successor — a PR must not extend Gen1 with new features presented
  as strategic (arch §2.3).

### 1.6 DistCp v2 — hadoop-distcp

- **FR-25 — Driver and option surface.** `DistCp extends Configured implements Tool` must parse
  options via `OptionsParser` into `DistCpOptions` from the verified `DistCpOptionSwitch` flag set
  (`-i`, `-p rbugpcaxte`, `-update`, `-delete`, `-m`, `-f`, `-atomic`, `-tmp`, `-log`, `-v`,
  `-strategy`, `-skipcrccheck`, `-overwrite`, `-append`, `-diff`/`-rdiff`, `-async`, `-blocksperchunk`,
  `-copybuffersize`, `-bandwidth`, `-filters`, `-direct`, `-xtrack`, `-numListstatusThreads`,
  `-useiterator`; `-filelimit`/`-sizelimit` deprecated), with config-key equivalents in
  `DistCpConstants` (e.g. `distcp.preserve.status` default `"-prbugpct"`, `distcp.max.maps`,
  `distcp.atomic.copy`) (arch §2.8, §7.3).
- **FR-26 — Copy listing, filters and snapshot diff.** The copy list must come from a `CopyListing`
  implementation (`SimpleCopyListing` recursive walk, `FileBasedCopyListing` explicit file list,
  `GlobbedCopyListing` glob expansion) filtered by `CopyFilter` implementations
  (`TrueCopyFilter`, `RegexCopyFilter`, `RegexpInConfigurationFilter`) driving `-filters`; the
  `-diff`/`-update` delta path must remain `DistCpSync` + `DiffInfo` snapshot-diff copying (arch
  §2.8, §7.3).
- **FR-27 — Splitting strategies.** With `-strategy uniformsize` (the default) `UniformSizeInputFormat`
  must produce static, size-balanced splits; with `-strategy dynamic` `DynamicInputFormat`
  (`DynamicInputChunk`, `DynamicRecordReader`) must split the copy list into small chunks on DFS that
  mappers claim and consume, so a slow mapper's slack is picked up by others (arch §2.8).
- **FR-28 — CopyCommitter duties.** `CopyCommitter extends FileOutputCommitter` must (1) clean the
  meta-folder, (2) preserve user/group/replication on copied directories (attribute preservation
  helpers in `DistCpUtils`), (3) atomically move the temporary work path to the final path when
  `-atomic`/`-tmp` was opted, (4) delete target files missing at source when `-delete` was opted
  (bookkeeping via `DeletedDirTracker`), and (5) clean partially copied files from failed attempts
  (arch §2.8, §4.5).

### 1.7 HAR — hadoop-archives

- **FR-29 — HAR on-disk format.** A `.har` must remain a directory containing `part-*` data files,
  the index `_index` (path → metadata, part file, offset, length) and `_masterindex` (segmented
  indirection over `_index`; its header carries the archive version); `HarFileSystem` resolves every
  inner `getFileStatus`/`open` into a positional read of a byte range inside the appropriate
  `part-*` file (arch §2.7, §7.4).
- **FR-30 — HAR read-only and inherited auth.** `HarFileSystem` must fail `create`, `rename` and
  `setOwner` (archives are immutable), and HAR must provide no authentication or authorization of
  its own — access control is entirely the host filesystem's (arch §2.7, §5.6).
- **FR-31 — Archive creation tool.** `HadoopArchives` (`hadoop-tools/hadoop-archives`,
  `org.apache.hadoop.tools.HadoopArchives implements Tool`) is the MapReduce job creating archives
  via `hadoop archive -archiveName foo.har -p <parent> <src>* <dest>`, keying its indexing
  mapper/reducer off source path hashes and writing parts sequentially (arch §2.7).

### 1.8 Streaming and pipes

- **FR-32 — Streaming stdio model.** hadoop-streaming must run arbitrary executables/scripts as
  mapper/reducer over stdio pipes: `HadoopStreaming`/`StreamJob` (Tool) build the `JobConf`,
  `PipeMapRed` with `PipeMapper`/`PipeReducer` spawn the subprocess and marshal records via
  configurable readers/writers (`StreamInputFormat`, `StreamBaseRecordReader`,
  `StreamXmlRecordReader` for XML, `KeyOnlyTextInputWriter`, `RawBytes*`/`TypedBytes*` adapters),
  and job context reaches the child via `Environment` (arch §2.10, §7.4).
- **FR-33 — Typed-bytes wire format.** The typedbytes classes (`Type`, `Record`,
  `TypedBytesInput`/`TypedBytesOutput`, `BinaryRecordInput`/`BinaryRecordOutput`) define the
  typed-bytes wire format with converters `LoadTypedBytes`/`DumpTypedBytes` between typed bytes and
  HDFS data; the wire format must not be changed without a converter-compatible migration (arch
  §2.10, §7.4).

### 1.9 Minor tools

| ID | Tool / module | Checkable rule | Origin |
|---|---|---|---|
| **FR-34** | hadoop-datajoin | Reduce-side join must stay `DataJoinJob`-driven: `DataJoinMapperBase` tags each record with source + group key, `DataJoinReducerBase` merges tagged records (`TaggedMapOutput`, `ResetableIterator`). | arch §2.11 |
| **FR-35** | hadoop-extras | `GetGroups` prints resolved groups for users; `DistCh` performs bulk ownership/permission/replication changes via MapReduce built on `DistTool` — no new semantics beyond these two Tools. | arch §2.11 |
| **FR-36** | hadoop-fs2img + hadoop-dynamometer | FSImage-based test tooling: `FileSystemImage` generates HDFS FSImages from a live filesystem (`FSTreeWalk`, `BlockResolver` impls, `UGIResolver` impls, `ImageWriter`), and dynamometer launches a real NameNode under YARN against simulated DataNodes built by `blockgen` from FSImage data (`infra.Client`/`ApplicationMaster`/`SimulatedDataNodes`, workload replay via `VirtualInputFormat`). | arch §2.9, §2.11 |
| **FR-37** | hadoop-federation-balance | `FedBalance` must balance data as a resumable procedure chain run by `BalanceProcedureScheduler`: `DistCpProcedure` (diff-driven distcp until difference ≤ `DIFF_THRESHOLD`) then `TrashProcedure` (source deletion to trash), journaled via `BalanceJournal` so migration survives restarts. | arch §2.11 |
| **FR-38** | hadoop-rumen + gridmix + sls | Rumen is the trace input library (parses job-history logs into `LoggedJob` traces / `JobStory` producers); Gridmix replays traces (`REPLAY`/`SERIAL`/`STRESS` policies, `EchoUserResolver`) and SLS simulates a YARN RM with real scheduler plugins fed by rumen or synthetic traces — a PR changing rumen's trace format must be evaluated against its Gridmix/SLS consumers. | arch §2.9 |
| **FR-39** | hadoop-archive-logs | `HadoopArchiveLogs` moves aggregated YARN log files into HAR archives using `HadoopArchives` inside distributed-shell containers (`HadoopArchiveLogsRunner`). | arch §2.9 |
| **FR-40** | hadoop-resourceestimator, hadoop-benchmark, hadoop-compat-bench | resourceestimator exposes the recurring-pipeline skyline predictor as a REST `service/`; hadoop-benchmark ships only `VectoredReadBenchmark`; compat-bench ships only the HDFS version-compatibility suites (`HdfsCompatSuiteForShell`/`ForTpcds`/`ForAll` and per-feature suites) — PRs there must stay within the named surface. | arch §2.9 |

## 2. Non-functional requirements

### 2.1 Concurrency

- **NFR-C-1 — S3A thread-pool invariants.** `S3AFileSystem.initialize()` must build exactly two
  executors: a `BlockingThreadPoolExecutorService` with active threads = `fs.s3a.threads.max`
  (`Constants.MAX_THREADS`) and queue capacity = `fs.s3a.threads.max + totalTasks + numPrefetchThreads`
  (suffix `-bounded`), and a `ThreadPoolExecutor` with core = `fs.s3a.threads.max`, maximum =
  `Integer.MAX_VALUE`, an unbounded `LinkedBlockingQueue` and core-thread timeout enabled (suffix
  `-unbounded`), both with daemon thread factories; pool growth beyond the configured maximum must
  queue, never spawn. `fs.s3a.executor.capacity` must bound the `SemaphoredDelegatingExecutor` in
  the `ExecutorServiceFuturePool` when the store factory requires a future pool, and
  `factoryRequirements.sharedThreads()` must be added to the bounded pool's queue capacity.
  `S3AStore` must gate concurrent backend work via `acquireReadCapacity`/`acquireWriteCapacity`;
  readers/writers that cannot acquire capacity must block, never silently skip (arch §4.1,
  R-NFR-1).
- **NFR-C-2 — S3A output backpressure.** `S3ABlockOutputStream` must receive its
  `ListeningExecutorService` only through `BlockOutputStreamBuilder.withExecutorService(...)`; part
  uploads and block recycling must run on that executor, never on the writing thread; the writer
  must block when no free block exists and never exceed the configured active-block/part limits;
  a failed part upload must abort the whole multipart upload (`WriteOperationHelper` family) on the
  `close()` happy path, while JVM-crash orphans remain reclaimable by the committer or S3 lifecycle
  rules (arch §4.2, R-NFR-2).
- **NFR-C-3 — Magic committer isolation.** Task attempts must write under per-job/per-attempt magic
  directories so two concurrent attempts of the same task never share a tracking path;
  `MagicCommitPaths` must treat any path element starting with `CommitConstants.MAGIC = "__magic"`
  (prefix `MAGIC_PATH_PREFIX = MAGIC + "_" + JOB_ID_PREFIX`) as magic and throw
  `IllegalArgumentException` (`E_NO_MAGIC_PATH_ELEMENT`) when the element cannot be located; the
  tracker pair must intercept PUTs to magic paths before they reach S3 as ordinary objects; job
  abort must complete-or-abort *all* pending uploads (`PendingSet`/`SinglePendingCommit`) with no
  orphaned multipart uploads left after successful job commit; concurrent committers of different
  jobs are safe, and single-writer-per-destination remains a caller responsibility (arch §4.3,
  R-NFR-9).
- **NFR-C-4 — ABFS throttling-first retry.** `AbfsClient` must apply client-side throttling
  mitigation (`AbfsClientThrottlingIntercept` + `AbfsClientThrottlingAnalyzer`) before any request
  is retried blindly; raw HTTP 429/500 storms must be visible through the analyzer's counters (arch
  §4.4, R-NFR-10).
- **NFR-C-5 — ABFS lease correctness.** When `fs.azure.infinite-lease.directories`
  (`FS_AZURE_INFINITE_LEASE_KEY`) covers a rename target, `AbfsLease` must acquire infinite leases
  with at most `DEFAULT_LEASE_ACQUIRE_MAX_RETRIES = 7` retries at `DEFAULT_LEASE_ACQUIRE_RETRY_INTERVAL
  = 10`, always release in `free()` including on exception paths, with the lease worker pool sized
  by `fs.azure.lease.threads` (`FS_AZURE_LEASE_THREADS`, default `0` = synchronous); leaked leases
  must be detectable in tests (arch §4.4, R-NFR-11).
- **NFR-C-6 — ABFS buffer bounds.** `AbfsOutputStream` must never flush a block larger than the
  configured write buffer (`DEFAULT_WRITE_BUFFER_SIZE` 8 MB; append-blob cap 4 MB), and
  `AbfsAdaptiveInputStream`/`AbfsPrefetchInputStream` must cap read-ahead at the configured read
  buffer (`DEFAULT_READ_BUFFER_SIZE` 4 MB), both validated in `AbfsConfiguration` (arch §4.4,
  R-NFR-12).
- **NFR-C-7 — DistCp atomicity guarantee.** With `-atomic` (`distcp.atomic.copy`) and `-tmp`, the
  commit must be all-or-nothing at the final path and partially copied files from failed attempts
  must be cleaned; without `-atomic`, output appears incrementally and a failed job may leave a
  partial copy — this asymmetry must remain documented wherever DistCp semantics are stated (arch
  §4.5, R-NFR-14).
- **NFR-C-8 — DistCp concurrency bounds.** `-m` (`distcp.max.maps`) bounds concurrent copy maps;
  `-numListstatusThreads` must bound source-listing fan-out (unbounded listing, e.g. introduced in
  `SimpleCopyListing`, is a violation); with `-strategy dynamic` a stalled mapper must not strand
  its files — another mapper claims the remaining `DynamicInputChunk` set, whereas under
  `uniformsize` a lost map is retried by the framework or the job fails; `-bandwidth` must be
  enforced per map via `ThrottledInputStream`, not per job (arch §4.5, R-NFR-15).
- **NFR-C-9 — HAR metadata cache.** `HarFileSystem` must serve concurrent readers of the same
  `.har` through the synchronized `harMetaCache` (`Collections.synchronizedMap(new LruCache…)`,
  initialized in synchronized `initializeMetadataCache`) without re-reading `_masterindex`/`_index`
  per lookup; its data-stream methods (`read`, `skip`, `available`, `close`) are `synchronized`, so
  a single stream instance must never be used concurrently by two threads; instance caching is
  disabled per `fs.har.impl.disable.cache` (core-default) and must be honoured (arch §4.6,
  R-NFR-17).
- **NFR-C-10 — Minor-store buffered I/O contract.** GCS
  (`GoogleCloudStorageClientReadChannel`/`GoogleCloudStorageClientWriteChannel`), OBS
  (`OBSDataBlocks`), OSS (`OSSDataBlocks`), COS (`BufferPool`) and BOS (`BosBlockBuffer`) must
  follow the same contract as S3A §4.2: buffer locally, upload on a worker, make the object visible
  only at close (arch §4.6). `KafkaSink` remains a single-threaded metrics pusher and introduces no
  filesystem concurrency semantics (arch §4.6).

### 2.2 Security

- **NFR-S-1 — S3A credential-chain stability.** The default chain from
  `CredentialProviderListFactory.createAWSCredentialProviderList(URI, Configuration)` when
  `fs.s3a.aws.credentials.provider` is unset must remain exactly `STANDARD_AWS_PROVIDERS` in this
  order: `EnvironmentVariableCredentialsProvider` (AWS SDK v2),
  `IAMInstanceCredentialsProvider`, `SimpleAWSCredentialsProvider`,
  `TemporaryAWSCredentialsProvider` — reordering or dropping any of these is a breaking change.
  Legacy v1 `com.amazonaws.auth.*` class names must continue to resolve through the v1→v2 map
  configured by `fs.s3a.aws.credentials.provider.mapping`, and forbidden entries must be rejected
  with `E_FORBIDDEN_AWS_PROVIDER` ("AWS provider class cannot be used") (arch §5.1, R-NFR-4).
- **NFR-S-2 — Secret hygiene and storage.** Credentials and session tokens must never appear in
  `toString()`, logs, or exception text of `AWSCredentialProviderList`, `MarshalledCredentials`, or
  `S3AFileSystem`. Per-bucket JCEKS paths via `fs.s3a.security.credential.provider.path` must be
  prepended to the cluster-wide `hadoop.security.credential.provider.path`; STS session secrets
  ride in `fs.s3a.session.token` (`Constants.SESSION_TOKEN`) (arch §5.1, R-NFR-5).
- **NFR-S-3 — Delegation-token lifetime.** `S3ADelegationTokens` must renew-bound tokens per the
  configured STS session duration (`DelegationConstants.DEFAULT_DELEGATION_TOKEN_DURATION` chain)
  and must fail closed — no anonymous fallback — when the bound binding cannot produce credentials.
  Binding selection is `fs.s3a.delegation.token.binding` (`DELEGATION_TOKEN_BINDING`), default the
  empty string: no token binding is active unless configured (arch §5.2, R-NFR-6).
- **NFR-S-4 — S3A encryption completeness.** Every `S3AEncryptionMethods` value
  (`SSE_S3("AES256")`, `SSE_KMS`, `SSE_C`, `CSE_KMS`, `CSE_CUSTOM`, `DSSE_KMS`; algorithm key
  `fs.s3a.encryption.algorithm`, key material `fs.s3a.encryption.key`, context
  `fs.s3a.encryption.context`; legacy `fs.s3a.server-side-encryption.key` deprecated) must be
  accepted by `S3AEncryption` and rejected with a clear error when its required key is missing for
  CSE/CSE-CUSTOM; client-side encryption goes through
  `impl.EncryptionS3ClientFactory`/`CSES3AFileSystemOperations` (arch §5.5, R-NFR-7).
- **NFR-S-5 — DistCp token completeness.** `CopyOutputFormat` must call
  `TokenCache.obtainTokensForNamenodes(context.getCredentials(), ...)` so the job's `Credentials`
  carry delegation tokens for every distinct source and destination filesystem (S3A participates
  via the `S3ADtFetcher` `DtFetcher` SPI); a DistCp run against a token-enabled store without a
  fetched token must fail at job submission, not mid-copy, and a new `CopyListing` implementation
  must not bypass the credentials path (arch §5.6, R-NFR-16).
- **NFR-S-6 — ABFS auth surface.** Shared-key auth uses `fs.azure.account.key.<account>` with
  optional `fs.azure.account.keyprovider` indirection; auth type selection via
  `fs.azure.account.auth.type` and `fs.azure.account.oauth.provider.type`; all OAuth2 flows
  (`ClientCredsTokenProvider`, `MsiTokenProvider`, `UserPasswordTokenProvider`,
  `RefreshTokenBasedTokenProvider`, `WorkloadIdentityTokenProvider`, `CustomTokenProviderAdapter`)
  must implement `AccessTokenProvider` behind `AzureADTokenProvider` — a PR adding an OAuth flow
  must plug in through `AccessTokenProvider`, not bypass it. Delegation tokens remain
  `AbfsDelegationTokenManager` (implements `BoundDTExtension`) with `AbfsDelegationTokenIdentifier`
  and `DtFetcher`/`TokenIdentifier`/`TokenRenewer` service entries (arch §5.3).
- **NFR-S-7 — GCS auth.** `HadoopCredentialsConfiguration` keys must keep both the
  `google.cloud.*` (`BASE_KEY_PREFIX`) and `fs.gs.*` prefix readings: `google.cloud.auth.type` /
  `fs.gs.auth.type` (default `AuthenticationType.COMPUTE_ENGINE`), service-account JSON keyfile
  `.auth.service.account.json.keyfile`, plus `.auth.client.id`, `.auth.client.secret`,
  `.auth.refresh.token`, `.token.server.url`; `AUTHENTICATION_TYPE` values include
  `APPLICATION_DEFAULT`, `SERVICE_ACCOUNT_JSON_KEYFILE`, `UNAUTHENTICATED` and access-token modes
  (arch §5.4).
- **NFR-S-8 — S3A token identifiers and secrets propagation.** Token identifiers must extend
  `AbstractS3ATokenIdentifier` (`SessionTokenIdentifier`, `RoleTokenIdentifier`,
  `FullCredentialsTokenIdentifier`) with kinds prefixed
  `DelegationConstants.TOKEN_NAME_PREFIX = "S3ADelegationToken/"` (e.g.
  `"S3ADelegationToken/Session"`); the token must carry credentials from which session/role
  credentials are *requested on demand* — it is not itself an AWS signature;
  `MarshalledCredentialBinding`/`MarshalledCredentials` serialize credentials into identifiers, and
  `EncryptionSecrets`/`EncryptionSecretOperations` must propagate encryption secrets alongside
  delegation tokens so committers on different hosts encrypt/decrypt identically (arch §5.2).

### 2.3 Logging and auditability

- **NFR-L-1 — S3A span discipline.** With `fs.s3a.audit.reject.out.of.span.operations=true`,
  `AuditManagerS3A` must reject any S3 request executed without an active `AuditSpanS3A`, including
  requests from pooled threads (spans activated on the caller's thread must be re-activated on the
  pool thread via `ActiveThreadSpanSource`). The audit SPI (`OperationAuditor` with
  `LoggingAuditor`, `NoopAuditor`) and the `S3AAuditConstants` key surface (`fs.s3a.audit.enabled`,
  `.service.classname`, `.request.handlers`, `.execution.interceptors`, `.referrer.enabled`,
  `.referrer.filter`) must remain the only wiring points for new auditors (arch §4.1, §6.1,
  R-NFR-3).
- **NFR-L-2 — IOStatistics continuity.** Connector operations must publish through
  `org.apache.hadoop.fs.statistics` (`IOStatistics`, `IOStatisticsContext` → snapshot,
  `DurationTracker`/`DurationTrackerFactory`, `IOStatisticsLogging`,
  `BufferedIOStatisticsInputStream`/`OutputStream`); both `S3AFileSystem` and
  `AzureBlobFileSystem` implement `IOStatisticsSource`, and any rename of a `Statistic` enum value
  or IOStatistics metric must be treated as a breaking API change requiring a migration path (arch
  §6.1, R-NFR-13).
- **NFR-L-3 — Metrics egress redaction.** `KafkaSink` and the S3A metrics outputs
  (`S3AInstrumentation`, `S3AStorageStatistics`) are externally readable; new metrics must not
  embed usernames, URIs with credentials, or bucket names unless explicitly approved (arch §6.1,
  §6.2, R-NFR-19).
- **NFR-L-4 — Failure typing.** AWS SDK exceptions must map to typed Hadoop IOExceptions
  (`AWSS3IOException`, `AWSServiceThrottledException`, `AWSBadRequestException`,
  `RemoteFileChangedException`, `HttpChannelEOFException`) and be retried per `S3ARetryPolicy`
  under `Invoker`; change detection (`ChangeTracker`/`ChangeDetectionPolicy`) must report
  overwrite-of-changed-object through `RemoteFileChangedException` rather than silent success,
  with SDK throttling always surfacing as `AWSServiceThrottledException` (arch §2.1, §4.1, §6.1).
- **NFR-L-5 — Per-connector observability.** ABFS must keep `AbfsPerfTracker` round-trip sampling,
  `AbfsInputStreamStatisticsImpl`/`AbfsOutputStreamStatisticsImpl` and
  `AbfsClientThrottlingAnalyzer` diagnostics; GCS must keep `GcsStorageStatistics`/`GcsStatistics`/
  `GcsInstrumentation` per-operation statistics with `ApiErrorExtractor`/`ErrorTypeExtractor`
  translating HTTP/gRPC failures into typed IOExceptions (arch §6.2).
- **NFR-L-6 — DistCp audit record.** DistCp auditability must be phrased as counter/log
  obligations, not filesystem events: the MapReduce counters of `CopyMapper`/`CopyCommitter` plus
  the job report are the audit record, `-log <dir>` must persist per-file copy logs to the given
  DFS folder, and `-v` toggles verbose reporting (arch §6.2).

### 2.4 Integration points

- **NFR-I-1 — S3A region resolution order.** `DefaultS3ClientFactory.configureEndpointAndRegion`
  must resolve the region deterministically: explicit `fs.s3a.endpoint.region` (`Constants.AWS_REGION`)
  → SDK region resolution chain (with exactly one warning) → region parsed from the endpoint;
  when both `fs.s3a.endpoint` (`Constants.ENDPOINT`) and `fs.s3a.endpoint.region` are empty the
  AWS-default client is used (arch §7.1, R-NFR-8).
- **NFR-I-2 — Streaming/pipes record fidelity.** `PipeMapRed`/`PipeMapper` must round-trip
  typedbytes records (`TypedBytesInput`/`TypedBytesOutput`, `BinaryRecordInput`/`BinaryRecordOutput`)
  byte-for-byte, and XML mode (`StreamXmlRecordReader`) must not split records mid-element. Hadoop
  Pipes uses its own C++ protocol (`HadoopPipes.cc`, serialization in `SerialUtils.hh/.cc`, native
  build under the module's `native/` profile) — the two wire formats are unrelated and must not be
  conflated in requirements or PRs (arch §2.10, §7.4, R-NFR-18).
- **NFR-I-3 — Empty-module discipline.** `hadoop-openstack` (source deleted, jar retained for
  dependency compatibility — no Swift `FileSystem` exists), `hadoop-cloud-storage` (single
  `pom.xml`, no source) and `hadoop-tools-dist` (assembly only) must stay source-free; PRs adding
  code there require a module-creation decision, not a patch review (arch §1.3, §1.6, §2.5,
  R-NFR-20).
- **NFR-I-4 — S3A connection and addressing surface.** `fs.s3a.path.style.access`
  (`Constants.PATH_STYLE_ACCESS`) must keep toggling path-style vs virtual-hosted addressing, with
  endpoint+path-style settable per bucket (`fs.s3a.bucket.<bucket>…` overrides); the connection
  keys `fs.s3a.connection.maximum` (`MAXIMUM_CONNECTIONS`), `fs.s3a.connection.ttl`
  (`CONNECTION_TTL`), `fs.s3a.connection.timeout` (`SOCKET_TIMEOUT`), `fs.s3a.ssl.channel.mode`
  (`SSL_CHANNEL_MODE`) and `fs.s3a.proxy.ssl.enabled` (`PROXY_SECURED`) must keep their meanings;
  STS region override remains `fs.s3a.assumed.role.sts.endpoint.region` (arch §7.1).
- **NFR-I-5 — S3A META-INF/services extension set.** The S3A jar must keep its ServiceLoader
  entries: `org.apache.hadoop.fs.FileSystem`, `org.apache.hadoop.fs.MultipartUploader`
  (`impl.S3AMultipartUploader`), `DtFetcher` (`S3ADtFetcher`) and `TokenIdentifier`; removing an
  entry breaks framework token fetch and upload extension (arch §1.1, §7.1).
- **NFR-I-6 — HAR index compatibility.** A PR touching the HAR index must preserve the exact
  filenames `_index` and `_masterindex` and the archive-version header in the master index, since
  older `HarFileSystem` versions read them; minor-store config families (`fs.obs.*`, `fs.cosn.*`,
  `fs.bos.*`, `fs.tos.*`) stay documented per module rather than in core-default.xml (arch §1.2,
  §7.2, §7.4).

### 2.5 Mapping from architecture NFR candidates

Every `R-NFR-n` item in arch §8 is mapped below and superseded by the requirement in this
document; on conflict, this document wins.

| arch candidate | Topic | This document |
|---|---|---|
| R-NFR-1 | S3A thread-pool invariants | NFR-C-1 |
| R-NFR-2 | S3A output backpressure | NFR-C-2 |
| R-NFR-3 | S3A span discipline | NFR-L-1 |
| R-NFR-4 | S3A credential-chain stability | NFR-S-1 |
| R-NFR-5 | S3A secret hygiene | NFR-S-2 |
| R-NFR-6 | S3A delegation-token lifetime | NFR-S-3 |
| R-NFR-7 | S3A encryption completeness | NFR-S-4 |
| R-NFR-8 | S3A region resolution order | NFR-I-1 |
| R-NFR-9 | Magic committer isolation | NFR-C-3 |
| R-NFR-10 | ABFS throttling-first retry | NFR-C-4 |
| R-NFR-11 | ABFS lease correctness | NFR-C-5 |
| R-NFR-12 | ABFS buffer bounds | NFR-C-6 |
| R-NFR-13 | IOStatistics continuity | NFR-L-2 |
| R-NFR-14 | DistCp atomicity guarantee | NFR-C-7 |
| R-NFR-15 | DistCp listing concurrency bound | NFR-C-8 |
| R-NFR-16 | DistCp token completeness | NFR-S-5 |
| R-NFR-17 | HAR immutability and cache | NFR-C-9 |
| R-NFR-18 | Streaming record-format fidelity | NFR-I-2 |
| R-NFR-19 | Metrics egress review | NFR-L-3 |
| R-NFR-20 | Empty-module discipline | NFR-I-3 |


## 3. PR-review checklists

### 3.1 Connector contract and scheme binding (any `s3a://`/`abfs://`/`gs://`/`oss://`/`obs://`/`cosn://`/`bos://`/`tos://`/`adl://` PR)

- [ ] Scheme bindings (impl + AbstractFileSystem) and ServiceLoader entries/lookup order intact (FR-1..FR-3, NFR-I-5).
- [ ] Output visibility still deferred to close/commit (FR-4, NFR-C-10); rename still emulated with typed failures (FR-5).
- [ ] No delegation-token dependency added for stores without a DT binding (GCS, OBS, COS, BOS, TOS — arch §1.1).

### 3.2 S3A

- [ ] Entry-point interfaces intact (FR-6); S3 interactions funnel through `S3AStore` (FR-7); read/write/listing contracts unchanged (FR-8..FR-10).
- [ ] Executor pair, capacity gating, future-pool bound (NFR-C-1) and backpressure (NFR-C-2) per §2.1.
- [ ] Committer changes route through `S3ACommitterFactory` (FR-11); magic/staging semantics per FR-12, FR-13, NFR-C-3.
- [ ] Credential chain order, v1 mapping, forbidden-provider rejection (NFR-S-1); no secrets in logs/toString (NFR-S-2); DT default-off and fail-closed lifetime (NFR-S-3); identifiers/prefix stable (NFR-S-8).
- [ ] Encryption completeness (NFR-S-4); region resolution (NFR-I-1); typed IOExceptions + `RemoteFileChangedException` (NFR-L-4); audit-span rejection testable (NFR-L-1); IOStatistics not renamed without migration (NFR-L-2).

### 3.3 ABFS and GCS

- [ ] DFS-vs-blob endpoint chosen by HNS support, not a user key (FR-15); `abfs`/`abfss` bindings intact (FR-1, FR-2); throttling-before-retry, lease and buffer bounds per NFR-C-4..NFR-C-6.
- [ ] New OAuth flows implement `AccessTokenProvider`; auth-type/provider-type keys unchanged (NFR-S-6).
- [ ] GCS single-bucket-rooted (FR-17); dual prefix reading (NFR-S-7) and statistics/error extractors preserved (NFR-L-5).

### 3.4 Other stores (OSS, OBS, COS, BOS, TOS, ADL)

- [ ] Buffered-I/O contract respected (NFR-C-10); OBS modes/SSE/conflicts (FR-19), COS SPI (FR-20), TOS commit mirror (FR-21), BOS plumbing (FR-22), OSS read-ahead/rename (FR-23), ADL maintenance-only (FR-24); no code added to `hadoop-openstack` or no-source dist modules (NFR-I-3).

### 3.5 DistCp

- [ ] `DistCpOptionSwitch` ↔ `DistCpConstants` mapping consistent; deprecated flags stay deprecated (FR-25); new `CopyListing`/`CopyFilter` implementations don't bypass credentials (NFR-S-5) or unbound listing threads (NFR-C-8); `-atomic -tmp` all-or-nothing and committer duties intact (NFR-C-7, FR-28); `-bandwidth` per map (NFR-C-8); audit via counters/`-log`/`-v` (NFR-L-6).

### 3.6 HAR and streaming/pipes

- [ ] `_index`/`_masterindex` names and version header preserved (FR-29, NFR-I-6); immutability + host-FS auth (FR-30); `fs.har.impl.disable.cache` honoured (NFR-C-9); creation command surface unchanged (FR-31); streaming stdio model/`Environment` unchanged (FR-32); typedbytes round-trip byte-for-byte, XML unsplit, Pipes not conflated (NFR-I-2, FR-33).

### 3.7 Minor tools

- [ ] Rumen trace-format changes checked against Gridmix/SLS consumers (FR-38); federation-balance chain resumable (FR-37); fs2img/dynamometer resolver SPIs kept (FR-36); auxiliary tools within named surface (FR-34, FR-35, FR-39, FR-40); new `KafkaSink`/S3A metrics redaction-reviewed (NFR-L-3).

## References

- `notes/architecture/hadoop-tools-cloud-architecture.md` — source document (§1 connectors, §2 tools, §4 concurrency, §5 security, §6 logging, §7 integration, §8 NFR candidates).
- `hadoop-cloud-storage-project/` and `hadoop-tools/` — module sources cited per requirement.
- `hadoop-common-project/hadoop-common/src/main/resources/core-default.xml` — scheme bindings (`fs.s3a.impl`, `fs.gs.impl`, `fs.abfs.impl`, `fs.adl.impl`, `fs.obs.impl`, `fs.har.impl`, …).
- Spot-verified constants (source tree, 2026-11-14): `CommitConstants.MAGIC = "__magic"` + `MAGIC_PATH_PREFIX`; `STANDARD_AWS_PROVIDERS` order; `AbfsLease` lease-retry defaults (7 / 10); `DelegationConstants.TOKEN_NAME_PREFIX = "S3ADelegationToken/"`; `HarFileSystem.harMetaCache`; `Constants.MAX_THREADS = "fs.s3a.threads.max"`.
