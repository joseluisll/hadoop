# Hadoop Tools & Cloud Storage Connectors — Architecture

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

This document covers two groupings of the Hadoop tree: the `hadoop-cloud-storage-project` family of object-store connectors, and
the `hadoop-tools` aggregation of side tools (cloud connectors S3A/ABFS, DistCp, HAR, and assorted MapReduce/YARN utilities). All
class names are taken directly from the source tree at `hadoop-cloud-storage-project/` and `hadoop-tools/`.

## Table of contents

1. [Cloud storage connectors (hadoop-cloud-storage-project)](#1-cloud-storage-connectors)
   - 1.1 [The shared connector contract](#11-the-shared-connector-contract)
   - 1.2 [Scheme binding reference](#12-scheme-binding-reference)
   - 1.3 [hadoop-cloud-storage (umbrella)](#13-hadoop-cloud-storage-umbrella)
   - 1.4 [GCS — hadoop-gcp](#14-gcs--hadoop-gcp)
   - 1.5 [BOS, COS, TOS, HuaweiCloud OBS (brief)](#15-bos-cos-tos-huaweicloud-obs-brief)
   - 1.6 [hadoop-cloud-storage-dist](#16-hadoop-cloud-storage-dist)
2. [Hadoop tools (hadoop-tools)](#2-hadoop-tools)
   - 2.1 [S3A — hadoop-aws (deep dive)](#21-s3a--hadoop-aws-deep-dive)
   - 2.2 [ABFS — hadoop-azure](#22-abfs--hadoop-azure)
   - 2.3 [ADLS Gen1 — hadoop-azure-datalake (brief)](#23-adls-gen1--hadoop-azure-datalake-brief)
   - 2.4 [Aliyun OSS — hadoop-aliyun (brief)](#24-aliyun-oss--hadoop-aliyun-brief)
   - 2.5 [OpenStack Swift — hadoop-openstack (brief)](#25-openstack-swift--hadoop-openstack-brief)
   - 2.6 [hadoop-kafka (brief)](#26-hadoop-kafka-brief)
   - 2.7 [HAR — hadoop-archives](#27-har--hadoop-archives)
   - 2.8 [DistCp v2 — hadoop-distcp](#28-distcp-v2--hadoop-distcp)
   - 2.9 [Job replay and benchmark tools](#29-job-replay-and-benchmark-tools)
   - 2.10 [Streaming and pipes](#210-streaming-and-pipes)
   - 2.11 [Small utilities (datajoin, extras, fs2img, federation-balance)](#211-small-utilities)
   - 2.12 [Miscellaneous tools (dynamometer, resourceestimator, benchmark, dist)](#212-miscellaneous-tools)
3. [Behaviour summary](#3-behaviour-summary)
4. [Concurrency](#4-concurrency)
5. [Security](#5-security)
6. [Logging and auditability](#6-logging-and-auditability)
7. [Integration points](#7-integration-points)
8. [Non-functional requirement candidates](#8-non-functional-requirement-candidates)
---

## 1. Cloud storage connectors

### 1.1 The shared connector contract

Every object-store connector implements the standard Hadoop `FileSystem` API (`org.apache.hadoop.fs.FileSystem`) on top of a flat
key/value object store. Because object stores have no real directories, renames are copy-and-delete and consistency is often
eventual, each connector layers directory emulation and retry logic over the store's REST API. A connector contributes up to three
binding artifacts:

- **A `FileSystem` implementation** bound to a URI scheme through `fs.<scheme>.impl` in `core-default.xml` (e.g. `fs.s3a.impl` →
  `org.apache.hadoop.fs.s3a.S3AFileSystem`, `fs.gs.impl` → `org.apache.hadoop.fs.gs.GoogleHadoopFileSystem`, `fs.obs.impl` →
  `org.apache.hadoop.fs.obs.OBSFileSystem`).
- **An `AbstractFileSystem` implementation** for the FileContext API, bound with `fs.AbstractFileSystem.<scheme>.impl` (e.g.
  `fs.AbstractFileSystem.s3a.impl` → `org.apache.hadoop.fs.s3a.S3A`). Most are tiny `DelegateToFileSystem` subclasses — `S3A`, `Gs`,
  `OBS`, `BOS`, `CosN` each just wrap the corresponding `FileSystem` instance.
- **A ServiceLoader declaration**: `org.apache.hadoop.fs.FileSystem` in hadoop-common scans `META-INF/services/org.apache.hadoop.fs.FileSystem` resources once per JVM (`FileSystem.loadFileSystems()` builds the static
  `SERVICE_FILE_SYSTEMS` map), so a connector shipping that service file is discoverable without config entries; connectors that
  omit it rely purely on the `fs.<scheme>.impl` keys. The S3A jar additionally ships `META-INF/services/org.apache.hadoop.fs.MultipartUploader` (`impl.S3AMultipartUploader`) and token service entries (`DtFetcher` →
  `S3ADtFetcher`, `TokenIdentifier`).

Common I/O behaviour: input streams read whole objects or range-GET with read-ahead buffering; output streams buffer locally
(`S3ADataBlocks`, `OBSDataBlocks`, `OSSDataBlocks`, `BosBlockBuffer`, `CosNOutputStream`) and upload via multipart PUT, so a
visible object appears only at close/commit time. Rename is emulated: list source prefix, copy objects, delete originals —
connector-specific failure classes exist (`RenameFailedException` appears in the OBS, S3A and Aliyun trees). Credentials resolve
through pluggable provider chains (`AWSCredentialProviderList`, `COSCredentialsProviderList`, hadoop-bos's `credentials/` package,
ABFS's `oauth2/` token providers, GCS's `HadoopCredentialsConfiguration`).

Delegation tokens: only a subset of stores implement them. The reference design is S3A's
`org.apache.hadoop.fs.s3a.auth.delegation.AbstractDelegationTokenBinding` with `S3ADelegationTokens` as the manager; ABFS has an
equivalent (`AbfsDelegationTokenManager`). The GCS, OBS, COS, BOS and TOS modules in this tree ship **no** delegation-token
binding.

### 1.2 Scheme binding reference

The table below is read off `core-default.xml` and the connector sources; it is the practical map a Java engineer needs when
resolving a `hadoop fs` URI to code.

| Scheme | `fs.<scheme>.impl` | `fs.AbstractFileSystem.<scheme>.impl` | Module |
|---|---|---|---|
| `s3a://` | `org.apache.hadoop.fs.s3a.S3AFileSystem` | `org.apache.hadoop.fs.s3a.S3A` | hadoop-aws |
| `gs://` | `org.apache.hadoop.fs.gs.GoogleHadoopFileSystem` | `org.apache.hadoop.fs.gs.Gs` | hadoop-gcp |
| `abfs://` / `abfss://` | `...azurebfs.AzureBlobFileSystem` / `...SecureAzureBlobFileSystem` | `...azurebfs.Abfs` / `Abfss` | hadoop-azure |
| `adl://` | `org.apache.hadoop.fs.adl.AdlFileSystem` | `org.apache.hadoop.fs.adl.Adl` | hadoop-azure-datalake |
| `oss://` | `org.apache.hadoop.fs.aliyun.oss.AliyunOSSFileSystem` | `org.apache.hadoop.fs.aliyun.oss.OSS` | hadoop-aliyun |
| `obs://` | `org.apache.hadoop.fs.obs.OBSFileSystem` | `org.apache.hadoop.fs.obs.OBS` | hadoop-huaweicloud |
| `cosn://` | `org.apache.hadoop.fs.cosn.CosNFileSystem` | `org.apache.hadoop.fs.cosn.CosN` | hadoop-cos |
| `bos://` | `org.apache.hadoop.fs.bos.BaiduBosFileSystem` | `org.apache.hadoop.fs.bos.BOS` | hadoop-bos |
| `tos://` | `org.apache.hadoop.fs.tosfs.TosFileSystem` | `org.apache.hadoop.fs.tosfs.TosFS` | hadoop-tos |
| `har://` | `org.apache.hadoop.fs.HarFileSystem` | `org.apache.hadoop.fs.HarFs` | hadoop-common |

Notes on the table:

- `fs.AbstractFileSystem.har.impl` is declared in hadoop-common because `HarFileSystem`/`HarFs` live there; the archive *creation*
  tool is what hadoop-archives contributes. - S3A, GCS, ABFS, ADL, OBS and HAR bindings are declared in `core-default.xml`; the
  cosn/bos/oss/tos connectors document their keys in their module (and test-contract) resources instead, relying on the user or a
  contract file to set them. - Two lookup layers apply: `FileSystem.getFileSystemClass(scheme, conf)` first consults the
  `fs.<scheme>.impl` config key, then falls back to the ServiceLoader-discovered `SERVICE_FILE_SYSTEMS` map. The store connectors
  here mostly use the config-key path; S3A's token and multipart-uploader extension points are the ones wired through
  META-INF/services.

### 1.3 hadoop-cloud-storage (umbrella)

No source code: the entire module is a single `pom.xml` (packaging `jar`, "Apache Hadoop Cloud Storage"). It declares the common
dependency set (hadoop-common plus shared cloud libraries) and serves as the dependency/aggregation artifact inherited by the
other cloud modules. All real code lives in the sibling per-store modules.

### 1.4 GCS — hadoop-gcp

Package `org.apache.hadoop.fs.gs`, scheme `gs://`.

- **`GoogleHadoopFileSystem`** (`extends FileSystem implements IOStatisticsSource`) is the Hadoop front-end. Per its Javadoc it is
  *rooted in a single bucket* at initialization: all Hadoop paths are relative to that bucket and no other bucket is ever touched,
  trading cross-bucket interoperability for straightforward `FileSystem` semantics (no bucket- naming constraints, files may live at
  root). The `AbstractFileSystem` counterpart is `Gs`, a `DelegateToFileSystem` delegating to a new `GoogleHadoopFileSystem`.
- **Store layer.** `GoogleCloudStorage` / `GoogleCloudStorageFileSystem` form the layer beneath the front-end;
  `GoogleCloudStorageClientReadChannel` and `GoogleCloudStorageClientWriteChannel` implement range reads and buffered writes over
  the GCS client, adapted to the Hadoop stream APIs by `GoogleHadoopFSInputStream` and `GoogleHadoopOutputStream`.
- **Configuration and credentials** live in `GoogleHadoopFileSystemConfiguration` and `HadoopCredentialsConfiguration`
  (service-account JSON keyfiles and other access-token provider modes).
- **Observability & errors.** `GcsStorageStatistics`/`GcsStatistics`/`GcsInstrumentation` publish per-operation statistics;
  `ApiErrorExtractor`/`ErrorTypeExtractor` translate HTTP/gRPC errors into Hadoop IOExceptions; `Fadvise`/`FileAccessPatternManager`
  tune read patterns. Metadata and paths are modelled by `FileInfo`/`StorageResourceId` and `StringPaths`/`UriPaths`.

At runtime a `gs://bucket/path` open performs a metadata lookup, then streams via the read channel with configurable read-ahead;
writes stage into the write channel and commit on close.

### 1.5 BOS, COS, TOS, HuaweiCloud OBS (brief)

- **hadoop-bos** (`fs.bos.impl`, package `org.apache.hadoop.fs.bos`): Baidu Object Storage. `BaiduBosFileSystem extends FileSystem`
  backed by `BosNativeFileSystemStore`/`HierarchyBosNativeFileSystemStore` over `BosClientProxy`/`BosClientProxyImpl`; streams
  `BosInputStream`/`BosOutputStream`/`BosBlockBuffer`; retry policies `BosRandomRetryPolicy` and `BosTryOnceThenFail`; credentials
  under `credentials/` (`BceCredentialsProvider`, config- and env-based providers); store exceptions under `exceptions/`
  (`BosHotObjectException`, `SessionTokenExpireException`, …). `BOS extends DelegateToFileSystem` is the FileContext binding.
- **hadoop-cos** (`fs.cosn.impl`, package `org.apache.hadoop.fs.cosn`): Tencent Cloud COS. `CosNFileSystem extends FileSystem`
  delegates object work to `CosNativeFileSystemStore` (the `NativeFileSystemStore` SPI), with `CosNInputStream`/`CosNOutputStream`
  doing buffered range reads and block-buffered multipart writes (`BufferPool`, `CosNFileReadTask`, `CosNCopyFileTask` for
  server-side copies). Credentials via `auth/COSCredentialsProviderList`.
- **hadoop-tos** (`fs.tos.impl`, package `org.apache.hadoop.fs.tosfs`): Volcengine TOS, the most feature-rich of the four. Besides
  `TosFileSystem extends RawFileSystem` (with `TosFS extends RawFS` as the `AbstractFileSystem` binding), it ships its own **commit
  framework** (`commit/` — `Committer`, `CommitterFactory`, `MagicOutputStream`, `Pending`, `PendingSet`, `SuccessData`, plus
  `commit/mapred/Committer`) that mirrors the S3A magic-committer design, alongside `object/`, `ops/` and `util/` support packages.
- **hadoop-huaweicloud** (`fs.obs.impl`, package `org.apache.hadoop.fs.obs`): Huawei OBS. `OBSFileSystem extends FileSystem` with
  `OBS.java` as the `AbstractFileSystem` delegate; streams `OBSInputStream`/`OBSBlockOutputStream` over `OBSDataBlocks`; client
  built through `OBSClientFactory`/`DefaultOBSClientFactory`. Distinguishes POSIX-bucket vs object-bucket access
  (`OBSPosixBucketUtils`, `OBSObjectBucketUtils`), supports server-side encryption (`SseWrapper`), and surfaces rename conflicts as
  `RenameFailedException`/`FileConflictException`.

### 1.6 hadoop-cloud-storage-dist

Distribution/aggregation module: assembles the connector jars above into the cloud-storage tarball published with a Hadoop
release. No Java code.

---

## 2. Hadoop tools

`hadoop-tools/pom.xml` aggregates 23 modules, from flagship cloud connectors to single-class utilities. The sub- sections go deep
on S3A, ABFS, HAR and DistCp, then cover the rest briefly.

### 2.1 S3A — hadoop-aws (deep dive)

Package `org.apache.hadoop.fs.s3a`, scheme `s3a://`; ~296 main classes — the largest connector in the tree.

**S3AFileSystem.** `public class S3AFileSystem extends FileSystem implements StreamCapabilities, AWSPolicyProvider,
DelegationTokenProvider, IOStatisticsSource, AuditSpanSource<AuditSpanS3A>, ActiveThreadSpanSource<AuditSpanS3A>,
StoreContextFactory` — the single entry point for every operation:

- **Initialization** builds the AWS S3 client (`S3ClientFactory`/`DefaultS3ClientFactory`), the credential chain
  (`AWSCredentialProviderList` over `SimpleAWSCredentialsProvider`, `TemporaryAWSCredentialsProvider`,
  `AssumedRoleCredentialProvider`, `IAMInstanceCredentialsProvider`, `SharedInstanceCredentialProvider`,
  `AnonymousAWSCredentialsProvider`, …), instrumentation (`S3AInstrumentation`, `S3AStorageStatistics`, `Statistic` enum) and the
  retry policy (`S3ARetryPolicy`, `Invoker`, `Retries`).
- **Store layer.** All S3 interactions funnel through the `S3AStore` interface (`S3AStore extends ClientManager, IOStatisticsSource,
  ObjectInputStreamFactory, PathCapabilities, Service`), implemented by `impl.S3AStoreImpl` and assembled with `S3AStoreBuilder`.
  `S3AStore` exposes `StoreContext` (bucket, URI, thresholds), `RequestFactory`, read/write capacity acquisition
  (`acquireReadCapacity`/`acquireWriteCapacity`), statistics contexts and operation counters.
- **Operations as objects.** The `impl/` package holds the store operations as first-class classes: `RenameOperation`,
  `DeleteOperation`, `BulkDeleteOperation`, `MkdirOperation`, `CopyFromLocalOperation`, `GetContentSummaryOperation`,
  `ListingOperationCallbacks`, `ChangeTracker`/`ChangeDetectionPolicy` (e-tag/versioned consistency checks on overwrite),
  `ChecksumSupport`, `S3AEncryption`/`EncryptionS3ClientFactory` and CSE operations (`CSES3AFileSystemOperations`), and
  `S3ExpressStorage` for S3 Express directories. `StoreContext`/`StoreContextBuilder` carry the shared configuration snapshot;
  `ClientManager`/`ClientManagerImpl` own S3 client lifecycles.
- **I/O.** `S3AInputStream` does lazy positioned range reads with read-ahead, selected by `S3AInputPolicy` (normal/random/fadvise).
  `S3ABlockOutputStream` + `S3ADataBlocks` buffer output locally (`DiskBlock`, `ByteBufferBlock`, `ArrayBlock`) and upload multipart
  via `WriteOperationHelper`/`WriteOperations`. The `prefetch/` package adds the newer prefetching reader stack —
  `S3APrefetchingInputStream`, `S3ARemoteInputStream`, `S3ABlockManager`/`S3ACachingBlockManager` — for asynchronous block-based
  prefetch. Vectored reads are supported (`VectoredIOContext`); `select/` holds the legacy S3-Select integration.
- **Directory emulation & listings.** S3A synthesizes directory markers; `impl.DirMarkerTracker` tracks marker hygiene during
  deletes, `Listing`/`S3ListRequest`/`S3ListResult` page through prefix listings, and `S3AFileStatus`/`S3ALocatedFileStatus` carry
  metadata.
- **Audit integration.** `audit/` (`AuditManagerS3A`, `OperationAuditor`, `AuditSpanS3A`, `AWSRequestAnalyzer`) lets an external
  auditor observe or reject S3 requests, with spans propagated from the calling thread (`ActiveThreadSpanSource`).
- **Retry & failure mapping.** AWS SDK exceptions are translated to typed Hadoop IOExceptions (`AWSS3IOException`,
  `AWSServiceThrottledException`, `AWSBadRequestException`, `RemoteFileChangedException`, `HttpChannelEOFException`, …) and retried
  per `S3ARetryPolicy` under `Invoker`.

**Commit protocol / magic & staging committers.** `commit/` implements MapReduce `OutputCommitter`s that make task commits safe
despite S3's lack of rename/atomicity. `AbstractS3ACommitter` is the base; `S3ACommitterFactory` selects an implementation by
configured committer name — including `COMMITTER_NAME_MAGIC` → `MagicS3GuardCommitterFactory`. `commit/files/`
(`SinglePendingCommit`, `PendingSet`, `SuccessData`, `UploadEtag`) defines the JSON "pending set" format persisted for the job
committer; `MagicCommitIntegration`/`MagicCommitPaths` detect `_magic` paths.

- **Magic committer** (`commit/magic/MagicS3GuardCommitter`): per its Javadoc, "a dedicated committer which requires the 'magic'
  directory feature of the S3A Filesystem to be enabled; it then uses paths for task and job attempts in magic paths, so as to
  ensure that the final output goes direct to the destination directory." Task output under a `_magic/…` prefix is intercepted by
  S3A (`InMemoryMagicCommitTracker`, `S3MagicCommitTracker`, `MagicCommitTracker`) and turned into pending multipart uploads; job
  commit completes those uploads in place — no data copied or renamed to the destination. Zero-copy and safe with multiple
  committers, at the cost of extra PUTs for tracking.
- **Staging committers** (`commit/staging/`): per the `StagingCommitter` Javadoc, based on the Netflix multipart committer work —
  tasks write to a **local temporary directory**; task-commit uploads each file *without* completing the final multipart operation
  and persists the pending commits; job-commit lists and commits (or aborts) all pending PUTs. Subclasses
  `DirectoryStagingCommitter` (cluster-wide temp dir) and `PartitionedStagingCommitter` (per-partition trees) with
  `ConflictResolution` modes (fail/replace/append/skip). Slower than magic (local disk + upload at commit) but usable when magic
  paths are not wanted.

**Delegation tokens.** `auth/delegation/` implements the store-side DT framework: `AbstractDelegationTokenBinding` is extended by
`SessionTokenBinding` (issues STS session credentials as the token), `RoleTokenBinding` (assumed-role) and
`FullCredentialsTokenBinding` (long-term credentials, mostly for testing), each with its own `AbstractS3ATokenIdentifier` subclass
(`SessionTokenIdentifier`, `RoleTokenIdentifier`, `FullCredentialsTokenIdentifier`). `S3ADelegationTokens` — "isolated from S3A
for control and testability" — manages binding selection and lifetime; its Javadoc stresses that the tokens are *not* used to
authenticate with AWS directly but carry credentials from which session/role credentials are requested on demand, and the design
is extensible to other auth mechanisms. `S3ADtFetcher` (declared in META-INF/services as a `DtFetcher`) obtains tokens on behalf
of submitting clients; `MarshalledCredentialBinding`/`MarshalledCredentials` serialize credentials into token identifiers;
`AWSPolicyProvider` ties in assumed-role policy scopes. `s3guard/` retains the (nearly retired) S3Guard consistency machinery
(`S3Guard`, `S3GuardTool`).

Runtime flow: `s3a://bucket/key` open → `StoreContext` lookup → prefetching or plain `S3AInputStream`; write → block- buffered
multipart upload through `S3ABlockOutputStream`, committed by the chosen output committer inside MapReduce/Spark jobs.

### 2.2 ABFS — hadoop-azure

Package `org.apache.hadoop.fs.azurebfs`, schemes `abfs://` and `abfss://` (TLS), bound in core-default via `fs.abfs.impl`,
`fs.AbstractFileSystem.abfs.impl` (class `Abfs`) and the `abfss` equivalents (`Abfss`, `SecureAzureBlobFileSystem`).

- **`AzureBlobFileSystem`** (`extends FileSystem implements IOStatisticsSource`) is the front-end; all store work is delegated to
  **`AzureBlobFileSystemStore`** (`implements Closeable, ListingSupport`), constructed through `AzureBlobFileSystemStoreBuilder`.
  `AbfsConfiguration` parses the `fs.azure.*` config surface.
- **`AbfsClient`** (`public abstract class AbfsClient implements Closeable`) is the raw HTTP client for the ABFS REST API, with two
  concrete subclasses: **`AbfsDfsClient`** (hierarchical-namespace / ADLS Gen2 endpoints: ACLs, atomic renames) and
  **`AbfsBlobClient`** (flat blob endpoint). Supporting services: `AbfsHttpOperation` and its JDK/Apache-client implementations,
  `AbfsClientThrottlingIntercept`/`AbfsClientThrottlingAnalyzer` (client-side throttling mitigation), `AbfsConnectionManager` and
  `AbfsManagedHttpClientContext` (connection pooling), `AbfsLease` (blob leases for atomic rename support).
- **Streams.** `AbfsInputStream` (abstract, `FSInputStream`, `CanUnbuffer`) with `AbfsAdaptiveInputStream` and
  `AbfsPrefetchInputStream` read-ahead strategies; `AbfsOutputStream` (`OutputStream`, `Syncable`) buffers writes as blocks
  (`AbfsBlobBlock`, `AbfsBlock`, `AbfsBlockStatus`) and flushes on `hflush`/`hsync` where the backend allows. Statistics via
  `AbfsInputStreamStatisticsImpl`, `AbfsOutputStreamStatisticsImpl`, `AbfsPerfTracker`.
- **Auth & tokens.** `oauth2/` holds the Azure AD flows (`AzureADAuthenticator`, `ClientCredsTokenProvider`, `MsiTokenProvider`,
  `UserPasswordTokenProvider`, `RefreshTokenBasedTokenProvider`, `WorkloadIdentityTokenProvider`, `CustomTokenProviderAdapter`),
  unified behind `AzureADTokenProvider`. Delegation tokens: `AbfsDelegationTokenManager` (`implements BoundDTExtension`) with
  `AbfsDelegationTokenIdentifier` and `ABFSKey`, plus `DtFetcher`/`TokenIdentifier`/`TokenRenewer` service entries. `Abfs` is the
  `DelegateToFileSystem` for FileContext.

Runtime: metadata operations hit the DFS endpoint when the account has a hierarchical namespace (atomic rename, ACL semantics),
else the blob endpoint (rename emulated); requests are signed per call (SAS/OAuth/shared-key) by the client layer.

### 2.3 ADLS Gen1 — hadoop-azure-datalake (brief)

Package `org.apache.hadoop.fs.adl`, scheme `adl://`. `AdlFileSystem` implements `FileSystem` over the Azure Data Lake Store REST
API with `AdlFsInputStream`/`AdlFsOutputStream`, `AdlFileStatus` and `AdlPermission` for metadata, and Azure AD OAuth tokens
supplied through `AzureADTokenProvider` adapters (`SdkTokenProviderAdapter`, `TokenProviderType`; config keys in `AdlConfKeys`:
client id/credential/refresh URL, MSI port, device-code, …). `Adl` is the FileContext binding. ADLS Gen1 is in maintenance mode
upstream; Gen2 (ABFS) is the successor.

### 2.4 Aliyun OSS — hadoop-aliyun (brief)

Package `org.apache.hadoop.fs.aliyun.oss`, bound via `fs.oss.impl` and the `OSS` `AbstractFileSystem` class. `AliyunOSSFileSystem
extends FileSystem` delegates to `AliyunOSSFileSystemStore`, with `AliyunOSSInputStream` (background read-ahead via
`AliyunOSSFileReaderTask`/`ReadBuffer`), block-buffered output (`OSSDataBlocks`, `AliyunOSSBlockOutputStream`), server-side copy
for rename (`AliyunOSSCopyFileTask`/`Context`) and statistics wrappers (`OutputStreamStatistics`, `BlockOutputStreamStatistics`).

### 2.5 OpenStack Swift — hadoop-openstack (brief)

**This module is empty.** The directory contains only a `pom.xml` whose description states: "This module used to contain code to
support integration with OpenStack. It has been deleted as unsupported; the JAR is still published so as to not break applications
which declare an explicit maven/ivy/SBT dependency on the module." No Swift `FileSystem` exists in the current tree.

### 2.6 hadoop-kafka (brief)

Not a filesystem: a single class, `org.apache.hadoop.metrics2.sink.KafkaSink`, a Metrics2 **sink** that pushes Hadoop (YARN/HDFS)
metrics to a Kafka topic. The module's only other code is its test `TestKafkaMetrics`.

### 2.7 HAR — hadoop-archives

Two cooperating pieces in different modules:

- **`HarFileSystem`** lives in hadoop-common (`org.apache.hadoop.fs.HarFileSystem`, with `HarFs` as the `AbstractFileSystem`
  binding; `fs.AbstractFileSystem.har.impl` is in core-default) and reads an existing archive **in place** as a read-only
  `FileSystem`.
- **`HadoopArchives`** (`hadoop-tools/hadoop-archives`, `org.apache.hadoop.tools.HadoopArchives implements Tool`) is the MapReduce
  job that **creates** archives via `hadoop archive -archiveName foo.har -p <parent> <src>* <dest>`.

**On-disk format** (from `HarFileSystem`'s Javadoc and code): a `.har` is a directory containing the archived file data as
`part-*` files plus two index files, `_masterindex` and `_index`. `_index` maps each archived file (path, metadata, part-file,
offset, length); `_masterindex` is a level of indirection over `_index` segments so lookups don't scan the whole index; the
archive version is read from the master-index header. `HadoopArchives` keys its indexing mapper/reducer off source path hashes and
writes the parts sequentially.

**Behaviour:** a `har://` URI resolves through the host filesystem; `HarFileSystem` parses the URI, opens `_masterindex`/`_index`,
and translates every `getFileStatus`/`open` on an inner path into a positional read of a byte range inside the appropriate
`part-*` file. Archives are immutable and read-only — `create`, `rename`, `setOwner` fail. `fs.har.impl.disable.cache`
(core-default) exists because archive instances cache per-host state.

### 2.8 DistCp v2 — hadoop-distcp

Package `org.apache.hadoop.tools` (+ `tools.mapred`, `tools.mapred.lib`, `tools.util`). DistCp v2 is a plain MapReduce job that
copies a file list.

- **Driver.** `DistCp extends Configured implements Tool`; per its Javadoc, `main()` "orchestrates the parsing of command-line
  parameters and the launch of the DistCp job", while programmatically a `DistCp` built from a `DistCpOptions` object is launched
  via `execute()` (and may be subclassed to fine-tune behaviour). `OptionsParser` builds `DistCpOptions` from `DistCpOptionSwitch`
  flags (update/overwrite/ignore-failures/atomic/sync-folders/blocks- per-map/…); `DistCpContext`/`DistCpConstants` carry runtime
  state.
- **Copy listing.** `CopyListing` is the abstract source of `CopyListingFileStatus` records; implementations: `SimpleCopyListing`
  (direct recursive walk), `FileBasedCopyListing` (explicit file list), `GlobbedCopyListing` (glob expansion). `CopyFilter`
  implementations (`TrueCopyFilter`, `RegexCopyFilter`, `RegexpInConfigurationFilter`) exclude paths; `DistCpSync` + `DiffInfo`
  implement the `-diff`/`-update` snapshot-diff optimization that copies only the delta between snapshots.
- **Map side.** `CopyMapper` ("Mapper class that executes the DistCp copy operation") maps each `CopyListingFileStatus` to a byte
  copy, performed by `RetriableFileCopyCommand` (with `CopyReadException` classification) and `RetriableDirectoryCreateCommand` via
  the generic `RetriableCommand` helper. `ThrottledInputStream` enforces bandwidth limits; `DistCpUtils` holds
  attribute-preservation helpers (permissions, replication, checksum comparison).
- **Splitting strategies.** Two `InputFormat`s choose how the copy list becomes map tasks. `UniformSizeInputFormat` "groups the
  contents into input-splits such that the total-number of bytes to be copied for each input split is uniform" — static,
  size-balanced splits. `DynamicInputFormat` (+ `DynamicInputChunk`, `DynamicInputChunkContext`, `DynamicRecordReader`) instead
  splits the copy-list into small chunks on DFS and creates empty "dynamic" splits that each consume as many chunks as they can, so
  a slow mapper doesn't slow the whole job (slack is picked up by others); the split-ratio tunes chunk sizes.
- **Commit side.** `CopyCommitter extends FileOutputCommitter`; per its Javadoc it (1) cleans the meta-folder (file-list workspace),
  (2) preserves user/group/replication on copied directories, (3) atomically moves data from the temporary work folder to the final
  path if atomic-commit was opted, (4) deletes target files missing at source when opted (`-delete`), and (5) cleans partially
  copied files from failed attempts. `CopyOutputFormat` wires the mapper/committer pair; `DeletedDirTracker` supports `-delete`
  bookkeeping; `tools/util/ProducerConsumer` and `WorkRequest*` provide parallel worker plumbing.

### 2.9 Job replay and benchmark tools

- **hadoop-rumen** — `org.apache.hadoop.tools.rumen`. Parses job-history logs into structured traces: `HadoopLogsAnalyzer` (Tool
  entry point), `JobHistoryParser`/`JobBuilder` and the `LoggedJob`/`LoggedTask` "Logged*" object model (JSON-serialized via
  `JsonObjectMapperParser`), `JobTraceReader` (reads a trace), `JobStoryProducer` and
  `ZombieJobProducer`/`ZombieJob`/`ZombieCluster` (replay a trace as job stories, with `ParsedHost`/`ClusterStory` for topology),
  plus statistical helpers (`RandomSeedGenerator`, `ResourceUsageMetrics`, CDF machinery). It is the *input library* consumed by
  Gridmix and SLS rather than an end-user tool.
- **hadoop-gridmix** — `org.apache.hadoop.mapred.gridmix`. The `Gridmix` Tool replays rumen traces against a live cluster:
  `JobFactory`/`SerialJobFactory` and `GridmixJobSubmissionPolicy` (REPLAY/SERIAL/STRESS pacing), `JobCreator` variants (load jobs
  or `SleepJob` dummy load), record generation (`ReadRecordFactory`, `IntermediateRecordFactory`, `RandomTextDataGenerator`),
  resource emulation plugins (`CumulativeCpuUsageEmulatorPlugin`, `TotalHeapUsageEmulatorPlugin`) and user resolution
  (`EchoUserResolver`); `ClusterSummarizer`/`ExecutionSummarizer` report metrics.
- **hadoop-sls** — `org.apache.hadoop.yarn.sls`. The **Scheduler Load Simulator**: `RMRunner` (entry point) drives a simulated YARN
  RM with real scheduler plugins `SLSCapacityScheduler`/`SLSFairScheduler` over `SchedulerWrapper` (+ `SLSSchedulerCommons`),
  simulated nodes/AMs (`NMRunner`, `NMSimulator`, `AMRunner`, `MockAMLauncher`, `ContainerSimulator`, `TaskRunner`) and a built-in
  web UI (`SLSWebApp`). Inputs are real rumen traces via `RumenToSLSConverter` or synthetic traces via
  `SynthTraceJobProducer`/`SynthJob`/`SynthUtils`; `SchedulerMetrics` variants (Fifo/Capacity/Fair) collect per-scheduler metrics.
- **hadoop-archive-logs** — `org.apache.hadoop.tools.HadoopArchiveLogs`: "moves Aggregated Log files into HAR archives using the
  HadoopArchives tool and the Distributed Shell via the HadoopArchiveLogsRunner" — the archive step runs as YARN distributed-shell
  containers (`HadoopArchiveLogsRunner`).
- **hadoop-resourceestimator** — `org.apache.hadoop.resourceestimator`. Recurring-pipeline resource prediction: `translator/` parses
  pipeline recurrences from logs, `skylinestore/` (`SkylineStore`, `HistorySkylineStore`, `PredictionSkylineStore` with validators
  and typed exceptions) persists and predicts resource skylines, `solver/` solves the resource-demand problem, and `service/`
  exposes it as a REST service.
- **hadoop-dynamometer** (brief) — HDFS **NameNode scale-testing** replay infrastructure
  (`org.apache.hadoop.hdfs.server.dynamometer`), four sub-modules: `blockgen` (`GenerateBlockImagesDriver`, `XMLParser`,
  `GenerateDNBlockInfosReducer` — turn an FSImage into block info for simulated DataNodes), `infra` (`Client`, `ApplicationMaster`,
  `SimulatedDataNodes`, `DynoResource`, `AMOptions` — launch a YARN application running the real NameNode with simulated DataNodes),
  `workload` (`VirtualInputFormat`, `VirtualInputSplit`, `CreateFileMapper` — replay workload against the simulated cluster) and
  `dist`.
- **hadoop-benchmark** — single Tool: `org.apache.hadoop.benchmark.VectoredReadBenchmark` (HDFS vectored-read throughput).
- **hadoop-compat-bench** — compatibility benchmark suites for HDFS (`HdfsCompatSuiteForShell`, `...ForTpcds`, `...ForAll`, plus
  per-feature suites: `HdfsCompatSnapshot`, `HdfsCompatStoragePolicy`, `HdfsCompatSymlink`, `HdfsCompatDirectory`,
  `HdfsCompatServer`, `HdfsCompatLocal`) used to compare behaviour across HDFS versions.
- **hadoop-tools-dist** — distribution module assembling all tools into the released `hadoop-tools` tarball; no source code.

### 2.10 Streaming and pipes

- **hadoop-streaming** (`org.apache.hadoop.streaming`): lets any executable or script act as mapper/reducer. `HadoopStreaming` is
  the `main()` entry; `StreamJob implements Tool` parses the `-mapper/-reducer/-input/-output/…` options, builds a `JobConf`
  (shipping a user jar via `JarBuilder` if asked) and runs the job. Data plumbing lives in `PipeMapRed` with
  `PipeMapper`/`PipeReducer` spawning the subprocess and marshalling records over stdin/stdout using configurable readers/writers
  (`StreamInputFormat`, `StreamBaseRecordReader`, `StreamXmlRecordReader` for XML, `KeyOnlyTextInputWriter`,
  `RawBytes*`/`TypedBytes*` adapters). The `typedbytes` classes (`Type`, `Record`, `TypedBytesInput`/`Output`,
  `BinaryRecordInput`/`Output`) define the typed-bytes wire format; `LoadTypedBytes`/`DumpTypedBytes` convert between typed bytes
  and HDFS data; `Environment` injects job context into the child process env. Note: streaming's process model is stdio pipes, not
  Hadoop Pipes.
- **hadoop-pipes**: the C++ MapReduce API. The module is a `pom`-packaging build wrapper whose `native/` profile compiles the C++
  library and examples (`HadoopPipes.cc`, headers `Pipes.hh`/`TemplateFactory.hh`, serialization in
  `SerialUtils.hh`/`SerialUtils.cc`, plus examples `wordcount-simple.cc`, `wordcount-part.cc`, `wordcount-nopipe.cc`, `sort.cc`).
  The Java-side plumbing lives in hadoop-mapreduce's `mapred.pipes`; this module ships the native C++ runtime and build wiring.

### 2.11 Small utilities

- **hadoop-datajoin** (`org.apache.hadoop.contrib.utils.join`): generic reduce-side join framework. `DataJoinJob` builds the job;
  users extend `DataJoinMapperBase` (tags each record with its source and group key) and `DataJoinReducerBase` (cross-product/merge
  of tagged records), with `TaggedMapOutput`, `ResetableIterator`/`ArrayListBackedIterator` and `JobBase`.
- **hadoop-extras**: legacy odds-and-ends: `GetGroups` (Tool printing resolved groups for users) and `DistCh` (bulk change of file
  ownership/permissions/replication via MapReduce, built on `DistTool`) — the old `org.apache.hadoop.tools` idiom DistCp grew from.
- **hadoop-fs2img** (`org.apache.hadoop.hdfs.server.namenode`): generates HDFS **FSImage** files from an arbitrary live filesystem —
  `FileSystemImage` (Tool) walks the tree via `FSTreeWalk`/`TreeWalk`/`TreePath`, maps files to blocks with `BlockResolver`
  implementations (`FixedBlockResolver`, `FixedBlockMultiReplicaResolver`, `NullBlockAliasMap`) and ownership via
  `UGIResolver`/`FsUGIResolver`/`SingleUGIResolver`, writing with `ImageWriter`. Used to fabricate realistic images for testing.
- **hadoop-federation-balance** (`org.apache.hadoop.tools.fedbalance`): Router-based federation data balancing. `FedBalance` (Tool):
  "balance data from src cluster to dst cluster with distcp — 1. move data from the source path to the destination path with distcp;
  2. delete the source path to trash." Executed as a resumable **procedure chain**: `BalanceProcedureScheduler` runs `BalanceJob`s
  made of `BalanceProcedure` steps — notably `DistCpProcedure` (diff-driven distcp until the difference drops under
  `DIFF_THRESHOLD`) and `TrashProcedure` (source deletion to trash, honouring `TrashOption`) — with journals (`BalanceJournal`,
  `BalanceJournalInfoHDFS`) so a migration survives restarts; options in
  `FedBalanceOptions`/`FedBalanceConfigs`/`FedBalanceContext`.

### 2.12 Miscellaneous tools

Every module in `hadoop-tools/pom.xml` — streaming, distcp, federation-balance, dynamometer, archives, archive-logs, rumen,
gridmix, datajoin, tools-dist, extras, pipes, openstack, sls, resourceestimator, azure, aws, kafka, azure- datalake, aliyun,
fs2img, benchmark, compat-bench — is covered above; nothing remains unlisted.

---

## 3. Behaviour summary

| Subcomponent | Runtime behaviour in one sentence |
|---|---|
| hadoop-cloud-storage | Empty-source umbrella: declares shared cloud deps; no runtime behaviour of its own. |
| hadoop-gcp (gs://) | Single-bucket-rooted `FileSystem` (`GoogleHadoopFileSystem` + `Gs` delegate) streaming via GCS read/write channels, with GCS statistics and error extraction. |
| hadoop-bos | Baidu BOS `FileSystem` (`BaiduBosFileSystem`) with buffered block I/O, pluggable BCE credentials and custom retry policies. |
| hadoop-cos (cosn://) | Tencent COS `FileSystem` (`CosNFileSystem`) over a `NativeFileSystemStore` SPI with block-buffered streams and server-side copy tasks. |
| hadoop-tos (tos://) | Volcengine TOS `RawFileSystem` subclass with its own magic-style commit framework (`commit/` package). |
| hadoop-huaweicloud (obs://) | Huawei OBS `FileSystem` with POSIX vs object bucket modes, block-buffered writes, SSE and rename-conflict failure types. |
| hadoop-cloud-storage-dist | Assembles the cloud connector jars into a distribution tarball. |
| hadoop-aws (s3a://) | Full-featured S3 `FileSystem`: `S3AStore`-mediated operations, block-buffered/prefetch I/O, magic & staging committers, STS/role delegation tokens, audit spans. |
| hadoop-azure (abfs://) | ABFS `FileSystem` delegating to `AzureBlobFileSystemStore`; `AbfsDfsClient` (namespace) or `AbfsBlobClient` (flat) endpoints; OAuth/DT support. |
| hadoop-azure-datalake (adl://) | ADLS Gen1 REST client with Azure AD OAuth token providers; maintenance mode. |
| hadoop-aliyun (oss://) | Aliyun OSS `FileSystem` with background read-ahead buffers and copy-based rename. |
| hadoop-openstack | Deleted source; empty jar retained for dependency compatibility only. |
| hadoop-kafka | Metrics2 sink streaming Hadoop metrics into Kafka; no filesystem. |
| hadoop-archives | MapReduce job (`HadoopArchives`) packing files into read-only `.har` (`_masterindex` + `_index` + `part-*`) read in place by `HarFileSystem`. |
| hadoop-distcp | MapReduce-driven parallel copy: option parsing → copy listing → uniform-size or dynamic splitting → `CopyMapper` copies → `CopyCommitter` finalizes (atomic move, `-delete`, attribute preservation). |
| hadoop-archive-logs | Moves aggregated YARN logs into HARs using HadoopArchives inside distributed-shell containers. |
| hadoop-rumen | Parses job-history logs into JSON traces and replayable `JobStory` producers (input library for Gridmix/SLS). |
| hadoop-gridmix | Replays rumen traces as load jobs (real or sleep-only) with configurable submission policy and resource emulation. |
| hadoop-sls | Simulates a YARN RM with real scheduler plugins (Capacity/Fair) fed by rumen or synthetic traces, with a web UI. |
| hadoop-streaming | Runs arbitrary executables/scripts as mapper/reducer via stdio pipes, with typed-bytes/raw-bytes/XML record marshalling. |
| hadoop-pipes | Native C++ MapReduce runtime and examples (`HadoopPipes.cc`), built under the module's native profile. |
| hadoop-datajoin | Reduce-side join framework: source-tagging mappers + join reducers driven by `DataJoinJob`. |
| hadoop-extras | Legacy tools: `GetGroups` and `DistCh` (bulk metadata changes). |
| hadoop-fs2img | Generates HDFS FSImages from a live filesystem (tree walk → block/UGI resolvers → image writer). |
| hadoop-federation-balance | Router-federation migration: diff-driven distcp + trash deletion as resumable, journaled balance procedures. |
| hadoop-dynamometer | Runs a real NameNode in YARN against simulated DataNodes built from blockgen FSImage data, replaying workloads — NN scale testing. |
| hadoop-resourceestimator | Learns resource-demand skylines of recurring pipelines from history and predicts/serves them via REST. |
| hadoop-benchmark | Single vectored-read throughput benchmark tool. |
| hadoop-compat-bench | Version-compatibility test suites for HDFS features (shell, TPC-DS, snapshots, storage policies, …). |
| hadoop-tools-dist | Assembles all tools into the release tarball. |

---

## 4. Concurrency

All statements in this section are testable invariants of the named classes. (Note: no class named
"AINodepool" or similar exists anywhere in `hadoop-aws`; the S3A thread model is the bounded/unbounded
pool pair described below.)

### 4.1 S3A thread model (`S3AFileSystem`, `Invoker`)

- `S3AFileSystem.initialize()` must build exactly two executors: a `BlockingThreadPoolExecutorService`
  (`org.apache.hadoop.util.BlockingThreadPoolExecutorService`) with active threads = `fs.s3a.threads.max`
  (`Constants.MAX_THREADS`) and queue capacity = `fs.s3a.threads.max + totalTasks + numPrefetchThreads`
  (pool name suffix `"-bounded"`), and a `ThreadPoolExecutor` with core = `fs.s3a.threads.max`,
  maximum = `Integer.MAX_VALUE`, an unbounded `LinkedBlockingQueue` and core-thread timeout enabled
  (suffix `"-unbounded"`). Both must use daemon thread factories.
- `fs.s3a.executor.capacity` (`Constants.EXECUTOR_CAPACITY`) must bound the `SemaphoredDelegatingExecutor`
  wrapped in an `ExecutorServiceFuturePool` when the active store factory declares
  `S3AStore.factoryRequirements().requiresFuturePool()`; the number of prefetch threads is taken from
  `factoryRequirements.sharedThreads()` and must be added to the bounded pool's waiting-queue capacity.
- Every S3 request path must execute under `Invoker` (retry wrapping with `S3ARetryPolicy` and the
  `Retries` annotation); SDK throttling failures must surface as `AWSServiceThrottledException`.
- `S3AFileSystem implements ActiveThreadSpanSource<AuditSpanS3A>`: an audit span activated on the caller's
  thread must be re-activated on whichever pool thread later executes the corresponding S3 request; an
  operation executed outside an active span must be rejectable by the auditor (see §6.1).
- Capacity: `S3AStore` must gate concurrent backend work through `acquireReadCapacity` /
  `acquireWriteCapacity`; readers/writers that cannot acquire capacity must block, never silently skip.

### 4.2 S3A output stream (`S3ABlockOutputStream`)

- The output stream must receive its `ListeningExecutorService` exclusively through
  `S3ABlockOutputStream.BlockOutputStreamBuilder.withExecutorService(...)`; part uploads and block
  recycling must run on that executor, never on the writing thread.
- Local buffering must go through `S3ADataBlocks` (`DiskBlock`, `ByteBufferBlock`, `ArrayBlock`): the
  writing thread must never block on a network upload while a free block exists, and the number of
  concurrently active blocks must be bounded by the configured block/buffer limits.
- A failed part upload must cancel/abort the whole multipart upload (`WriteOperationHelper`/
  `WriteOperations`) rather than leave orphan parts behind on the happy path of `close()`; on JVM crash,
  orphan parts are expected and must be reclaimable by the committer or S3 lifecycle rules.

### 4.3 S3A magic committer concurrency (`commit/magic`)

- The magic prefix is `CommitConstants.MAGIC = "__magic"`, and `MAGIC_PATH_PREFIX = MAGIC + "_" +
  JOB_ID_PREFIX` (i.e. `__magic_<jobid>...`); `MagicCommitPaths` must treat any path element starting
  with `MAGIC_PATH_PREFIX` as a magic path element and throw `IllegalArgumentException` (`E_NO_MAGIC_PATH_ELEMENT`)
  when the element cannot be located.
- Task attempts must write under per-job/per-attempt magic directories so that two concurrent task
  attempts of the same task never write the same tracking path; the `InMemoryMagicCommitTracker`/
  `S3MagicCommitTracker` pair must intercept PUTs to magic paths before they reach S3 as ordinary objects.
- Job commit completes pending multipart uploads in place; concurrent committers of *different* jobs are
  safe, but two writers committing the same final destination path must remain undefined (single-writer
  per destination is a caller responsibility — a requirement worth making explicit).

### 4.4 ABFS HTTP client and leases (`AbfsClient`, `AbfsLease`)

- `AbfsClient` (abstract) must remain the only REST entry point, with `AbfsDfsClient` (hierarchical
  namespace) and `AbfsBlobClient` (flat) as the only subclasses; HTTP execution goes through
  `AbfsHttpOperation` implementations (`AbfsJdkHttpOperation`, `AbfsApacheHttpClient`) on connections
  pooled by `AbfsConnectionManager` / `AbfsManagedHttpClientContext`.
- Client-side throttling mitigation must be applied by `AbfsClientThrottlingIntercept` +
  `AbfsClientThrottlingAnalyzer` before any request is retried blindly.
- `AbfsLease` acquires infinite leases for atomic rename support with
  `DEFAULT_LEASE_ACQUIRE_MAX_RETRIES = 7` and `DEFAULT_LEASE_ACQUIRE_RETRY_INTERVAL = 10` (seconds-scale
  retry interval), and must release the lease in `free()`; lease usage is enabled per directory through
  `fs.azure.infinite-lease.directories` (`FS_AZURE_INFINITE_LEASE_KEY`) and the lease worker pool is
  sized by `fs.azure.lease.threads` (`FS_AZURE_LEASE_THREADS`, default `0` — i.e. synchronous by default).
- Buffer sizes are validated in `AbfsConfiguration`: default read buffer 4 MB
  (`DEFAULT_READ_BUFFER_SIZE`), default write buffer 8 MB (`DEFAULT_WRITE_BUFFER_SIZE`, append-blob cap
  4 MB); `AbfsOutputStream` must never flush a block larger than the configured write buffer.

### 4.5 DistCp concurrency and atomic commit

- `-m` (`DistCpOptionSwitch.MAX_MAPS`, config `distcp.max.maps`) bounds the number of concurrent copy
  maps; with `-strategy dynamic` (`DynamicInputFormat`) mappers claim chunks from the shared
  `DynamicInputChunk` set on DFS, so a stalled mapper must not strand its files — another mapper picks up
  the remaining chunks; with `-strategy uniformsize` (`UniformSizeInputFormat`) split assignment is static
  and a lost map must be retried by the framework or the job fails.
- Copy listing concurrency is bounded by the `-numListstatusThreads` option (source listing fan-out) and
  the `ProducerConsumer`/`WorkRequest*` plumbing in `tools/util`.
- `-atomic` (config `distcp.atomic.copy`, `DistCpConstants.CONF_LABEL_ATOMIC_COPY`) with `-tmp` must give
  all-or-nothing semantics: `CopyCommitter` (a `FileOutputCommitter`) must (1) clean the meta-folder,
  (2) preserve attributes on directories, (3) atomically move the temporary work path to the final path,
  (4) apply `-delete`, and (5) delete partially copied files from failed attempts. Without `-atomic`,
  output appears incrementally and a failed job may leave a partial copy — this asymmetry must be
  documented in any requirements derived from DistCp.
- `-bandwidth` limits per-map throughput via `ThrottledInputStream`; the limit must be enforced per map,
  not per job.

### 4.6 HAR and the remaining connectors

- `HarFileSystem` must cache archive metadata per URI in `harMetaCache`
  (`Collections.synchronizedMap(new LruCache<URI, HarMetaData>(...))`, initialized in the synchronized
  `initializeMetadataCache`), so concurrent readers of the same `.har` share one parsed index; index files
  (`_masterindex`, `_index`) are re-read only on cache miss. Its data-stream methods (`read`, `skip`,
  `available`, `close`) are `synchronized` — a single `HarFileSystem` stream instance must never be used
  concurrently by two threads.
- Instance caching is disabled per `fs.har.impl.disable.cache` (core-default.xml); requirements must
  state whether archive instances may be shared within a JVM.
- GCS (`GoogleCloudStorageClientReadChannel`/`GoogleCloudStorageClientWriteChannel`), OBS
  (`OBSDataBlocks`), OSS (`OSSDataBlocks`), COS (`BufferPool`) and BOS (`BosBlockBuffer`) all follow the
  same contract as S3A §4.2: buffer locally, upload on a worker, make the object visible only at close.
- `KafkaSink` (hadoop-kafka) must be treated as a single-threaded metrics pusher; it introduces no
  filesystem concurrency semantics.

## 5. Security

### 5.1 S3A credential chain

- The chain is assembled by `CredentialProviderListFactory.createAWSCredentialProviderList(URI, Configuration)`
  from `fs.s3a.aws.credentials.provider` (`Constants.AWS_CREDENTIALS_PROVIDER`). When unset, the
  `STANDARD_AWS_PROVIDERS` list must be used **in this exact order**:
  `EnvironmentVariableCredentialsProvider` (AWS SDK v2), `IAMInstanceCredentialsProvider`,
  `SimpleAWSCredentialsProvider`, `TemporaryAWSCredentialsProvider`. A PR that reorders or drops these
  defaults is a breaking change.
- Hadoop-specific providers exist beside the SDK ones: `AssumedRoleCredentialProvider`
  (keys `fs.s3a.assumed.role.arn`, `fs.s3a.assumed.role.external.id`, `fs.s3a.assumed.role.session.name`),
  `ProfileAWSCredentialsProvider`, `MarshalledCredentialProvider` (tokens carrying marshalled
  credentials), and `AnonymousAWSCredentialsProvider` (in `org.apache.hadoop.fs.s3a`).
- Legacy v1 provider class names (`com.amazonaws.auth.*`) must continue to resolve through the
  v1→v2 map configured/extended by `fs.s3a.aws.credentials.provider.mapping`
  (`Constants.AWS_CREDENTIALS_PROVIDER_MAPPING`); `createAWSCredentialProviderList` enforces
  `E_FORBIDDEN_AWS_PROVIDER` ("AWS provider class cannot be used") for forbidden entries.
- Secret storage: per-bucket JCEKS paths via `fs.s3a.security.credential.provider.path`
  (`S3A_SECURITY_CREDENTIAL_PROVIDER_PATH`), prepended to the cluster-wide
  `hadoop.security.credential.provider.path`; STS session secrets via `fs.s3a.session.token`
  (`Constants.SESSION_TOKEN`). Secrets must never be emitted in exception messages or logs.

### 5.2 S3A delegation tokens (`auth/delegation`)

- Binding selection is the key `fs.s3a.delegation.token.binding`
  (`DelegationConstants.DELEGATION_TOKEN_BINDING`); the default is the empty string — **no token binding
  is active unless configured**. Built-in bindings: `SessionTokenBinding` (STS session credentials),
  `RoleTokenBinding` (assumed role), `FullCredentialsTokenBinding` (long-lived credentials; testing only),
  all extending `AbstractDelegationTokenBinding` and managed by `S3ADelegationTokens`.
- Token identifiers extend `AbstractS3ATokenIdentifier` (`SessionTokenIdentifier`,
  `RoleTokenIdentifier`, `FullCredentialsTokenIdentifier`) with token kinds prefixed
  `DelegationConstants.TOKEN_NAME_PREFIX = "S3ADelegationToken/"` (e.g. `"S3ADelegationToken/Session"`).
- `S3ADtFetcher` is registered as a `DtFetcher` in META-INF/services so MapReduce/Other frameworks fetch
  S3A tokens through the standard token-fetch SPI; `MarshalledCredentialBinding`/`MarshalledCredentials`
  serialize credentials into identifiers. The token must carry credentials from which session/role
  credentials are *requested on demand* — it is not itself an AWS signature.
- `EncryptionSecrets`/`EncryptionSecretOperations` (same package) propagate encryption secrets alongside
  delegation tokens so committers running on different hosts can decrypt/encrypt identically.

### 5.3 ABFS auth

- Shared-key auth: `fs.azure.account.key.<account>` (`ConfigurationKeys.FS_AZURE_ACCOUNT_KEY_PROPERTY_NAME`)
  with optional key-provider indirection `fs.azure.account.keyprovider` (`AZURE_KEY_ACCOUNT_KEYPROVIDER`).
- Auth type selection: `fs.azure.account.auth.type` (`FS_AZURE_ACCOUNT_AUTH_TYPE_PROPERTY_NAME`) and
  `fs.azure.account.oauth.provider.type` (`FS_AZURE_ACCOUNT_TOKEN_PROVIDER_TYPE_PROPERTY_NAME`).
- OAuth2 providers under `oauth2/`, all implementing `AccessTokenProvider` behind `AzureADTokenProvider`:
  `ClientCredsTokenProvider` (client id/secret/endpoint via `fs.azure.account.oauth2.client.id`,
  `.client.secret`, `.client.endpoint`), `MsiTokenProvider` (`.msi.tenant`, `.msi.endpoint`,
  `.msi.authority`), `UserPasswordTokenProvider` (`.user.name`, `.user.password`),
  `RefreshTokenBasedTokenProvider`, `WorkloadIdentityTokenProvider`, `CustomTokenProviderAdapter`.
- Delegation tokens: `AbfsDelegationTokenManager` (implements `BoundDTExtension`) with
  `AbfsDelegationTokenIdentifier`; `DtFetcher`/`TokenIdentifier`/`TokenRenewer` service entries are
  declared in the jar. A PR adding an OAuth flow must plug in through `AccessTokenProvider`, not bypass it.

### 5.4 GCS auth

- `HadoopCredentialsConfiguration` keys are built from `BASE_KEY_PREFIX = "google.cloud"` and also read
  under `fs.gs.*` prefixes (its `withPrefixes(keyPrefixes)` usage): `google.cloud.auth.type` /
  `fs.gs.auth.type` (default `AuthenticationType.COMPUTE_ENGINE`), service-account keyfile
  `.auth.service.account.json.keyfile`, plus `.auth.client.id`, `.auth.client.secret`,
  `.auth.refresh.token`, `.token.server.url`. `AUTHENTICATION_TYPE` values include
  `APPLICATION_DEFAULT`, `SERVICE_ACCOUNT_JSON_KEYFILE`, `UNAUTHENTICATED` and access-token modes.

### 5.5 Encryption (SSE/CSE)

- Algorithm selection is `fs.s3a.encryption.algorithm` with `S3AEncryptionMethods` values:
  `SSE_S3("AES256")`, `SSE_KMS`, `SSE_C`, `CSE_KMS`, `CSE_CUSTOM`, `DSSE_KMS`; key material in
  `fs.s3a.encryption.key`, context in `fs.s3a.encryption.context`; the legacy
  `fs.s3a.server-side-encryption.key` (`SERVER_SIDE_ENCRYPTION_KEY`) is deprecated. Client-side
  encryption is wired through `impl.EncryptionS3ClientFactory`/`CSES3AFileSystemOperations`
  (`S3_ENCRYPTION_CSE_CUSTOM_KEYRING_CLASS_NAME` selects a custom keyring class).

### 5.6 DistCp token forwarding, HAR, and kerberos across tools

- `CopyOutputFormat` must call `TokenCache.obtainTokensForNamenodes(context.getCredentials(), ...)` so the
  job's `Credentials` carry delegation tokens for both source and destination filesystems; S3A's
  `S3ADtFetcher` participates via the `DtFetcher` SPI. A DistCp run against a token-enabled store without
  a fetched token must fail at job submission, not mid-copy.
- HAR provides no authentication or authorization of its own: access control is entirely the host
  filesystem's. Any HAR requirement must be phrased as "inherit host FS auth".
- **No hadoop-tools module hard-requires Kerberos.** Rumen/SLS consume offline job-history logs; Gridmix
  submits as a target UGI (`EchoUserResolver.getTargetUgi` → `UserGroupInformation`), which on a secured
  cluster requires proxy-user configuration (`hadoop.proxyuser.*`); dynamometer's infra
  (`Client`/`ApplicationMaster`/`DynoInfraUtils`) launches a real NameNode under YARN and can target a
  secured cluster but contains no mandatory Kerberos path; streaming/pipes/datajoin inherit the MR job's
  UGI only.

## 6. Logging and auditability

### 6.1 S3A: metrics, IOStatistics, audit spans

- Metrics: `S3AInstrumentation` (a `MetricsSource`), `S3AStorageStatistics`, and the `Statistic` enum plus
  the `statistics/` package define the metrics surface. The cross-connector framework is
  `org.apache.hadoop.fs.statistics` in hadoop-common (`IOStatistics`, `IOStatisticsContext`,
  `IOStatisticsSnapshot`, `DurationTracker`/`DurationTrackerFactory`, `IOStatisticsLogging`,
  `BufferedIOStatisticsInputStream/OutputStream`); both `S3AFileSystem` and `AzureBlobFileSystem`
  implement `IOStatisticsSource`, and a PR must not remove an existing `Statistic`/IOStatistics symbol
  without a migration path.
- Audit: `audit/` provides `AuditManagerS3A`/`ActiveAuditManagerS3A`, the `OperationAuditor` SPI with
  implementations `LoggingAuditor` (log-file audit trail), `NoopAuditor`, and spans
  (`AuditSpanS3A`, `AbstractAuditSpanImpl`). Keys: `fs.s3a.audit.enabled`, `fs.s3a.audit.service.classname`,
  `fs.s3a.audit.request.handlers`, `fs.s3a.audit.execution.interceptors`,
  `fs.s3a.audit.reject.out.of.span.operations`, `fs.s3a.audit.referrer.enabled`,
  `fs.s3a.audit.referrer.filter` (all in `S3AAuditConstants`). With rejection enabled, any S3 request made
  outside an active span must be rejected — this is the testable hook for "every store op is attributable".
- Failures: SDK exceptions must map to typed Hadoop IOExceptions (`AWSS3IOException`,
  `AWSServiceThrottledException`, `AWSBadRequestException`, `RemoteFileChangedException`,
  `HttpChannelEOFException`), and change-detection (`ChangeTracker`/`ChangeDetectionPolicy`) must report
  overwrite-of-changed-object through `RemoteFileChangedException` rather than silent success.

### 6.2 Other connectors' observability

- ABFS: `AbfsPerfTracker` (round-trip perf sampling), `AbfsInputStreamStatisticsImpl`/
  `AbfsOutputStreamStatisticsImpl`, and `AbfsClientThrottlingAnalyzer` for throttle diagnostics.
- GCS: `GcsStorageStatistics`/`GcsStatistics`/`GcsInstrumentation` publish per-operation statistics;
  `ApiErrorExtractor`/`ErrorTypeExtractor` turn HTTP/gRPC failures into typed IOExceptions.
- DistCp: the MapReduce counters of `CopyMapper`/`CopyCommitter` plus the job report are the audit record;
  `-log <dir>` must persist per-file copy logs to the given DFS folder and `-v` toggles verbose reporting.
  Requirements on "copy auditability" should be phrased as counter/log obligations, not filesystem events.
- HAR and the flat listers (`Listing`/`S3ListRequest`) have **no audit hooks**: HAR logs nothing beyond
  standard FS logging, and listings are only visible through connector metrics. Do not derive "list was
  audited" requirements from HAR.
- `KafkaSink` is itself an egress path: metrics pushed to Kafka are externally readable, so metric
  redaction requirements apply to it.

## 7. Integration points

### 7.1 S3A

- Endpoint/region: `fs.s3a.endpoint` (`Constants.ENDPOINT`), `fs.s3a.endpoint.region`
  (`Constants.AWS_REGION`), STS region `fs.s3a.assumed.role.sts.endpoint.region`.
  `DefaultS3ClientFactory.configureEndpointAndRegion` must resolve the region in this order: explicit
  `fs.s3a.endpoint.region` → SDK region resolution chain (with a one-off warning) → region parsed from the
  endpoint. When both `fs.s3a.endpoint` and `fs.s3a.endpoint.region` are empty the AWS-default client is used.
- Addressing: `fs.s3a.path.style.access` (`Constants.PATH_STYLE_ACCESS`) toggles path-style vs
  virtual-hosted addressing; endpoint+path-style must be settable per bucket (fs.s3a.bucket.<bucket>....
  style overrides).
- Connection surface: `fs.s3a.connection.maximum` (`MAXIMUM_CONNECTIONS`), `fs.s3a.connection.ttl`
  (`CONNECTION_TTL`), `fs.s3a.connection.timeout` (`SOCKET_TIMEOUT`), `fs.s3a.ssl.channel.mode`
  (`SSL_CHANNEL_MODE`), `fs.s3a.proxy.ssl.enabled` (`PROXY_SECURED`).
- Extension points wired through META-INF/services: `FileSystem`, `MultipartUploader`
  (`impl.S3AMultipartUploader`), `DtFetcher` (`S3ADtFetcher`), `TokenIdentifier`.

### 7.2 ABFS, GCS and the minor stores

- ABFS URI forms: `abfs://` (HTTP) and `abfss://` (TLS); the account name is parsed from the config/
  authority (in `AbfsClient`: `abfsConfiguration.getAccountName()` up to the first dot). DFS vs blob
  endpoint selection is by hierarchical-namespace support, not a user key.
- GCS: `fs.gs.project.id`, `fs.gs.working.dir` (default `/`), `fs.gs.block.size` (64 MB),
  `fs.gs.outputstream.buffer.size` (8 MB), `fs.gs.inputstream.fadvise` (default `Fadvise.RANDOM`),
  `fs.gs.inputstream.inplace.seek.limit`, `fs.gs.inputstream.min.range.request.size`,
  `fs.gs.inputstream.support.gzip.encoding.enable`, `fs.gs.rewrite.max.chunk.size`,
  `fs.gs.marker.file.pattern`, `fs.gs.fadvise.request.track.count`. The FS is rooted in one bucket for
  its lifetime — cross-bucket access is out of contract.
- OBS/COS/BOS/TOS endpoints and credentials are documented per-module (`fs.obs.*`, `fs.cosn.*`,
  `fs.bos.*`, `fs.tos.*` families) rather than in core-default.xml.

### 7.3 DistCp option surface (verified flags in `DistCpOptionSwitch`)

`-i` (ignore failures), `-p` (preserve `rbugpcaxte`), `-update`, `-delete`, `-m` (max maps),
`-f` (file list), `-atomic`, `-tmp`, `-log`, `-v`, `-strategy` (default `uniformsize`), `-skipcrccheck`,
`-overwrite`, `-append`, `-diff`/`-rdiff`, `-async`, `-filelimit`/`-sizelimit` (deprecated),
`-blocksperchunk`, `-copybuffersize`, `-bandwidth` (MB/s per map), `-filters`, `-direct`, `-xtrack`,
`-numListstatusThreads`, `-useiterator`. Config-key equivalents live in `DistCpConstants`
(`distcp.preserve.status` default `"-prbugpct"`, `distcp.max.maps`, `distcp.copy.strategy`,
`distcp.ignore.failures`, `distcp.copy.overwrite`, `distcp.update.mod.time`, …). `DistCpSync` +
`DiffInfo` implement the `-diff`/`-update` snapshot-delta path; `CopyFilter` implementations
(`TrueCopyFilter`, `RegexCopyFilter`, `RegexpInConfigurationFilter`) drive `-filters`.

### 7.4 HAR layout and streaming/pipes wire formats

- HAR on-disk contract (from `HarFileSystem`): an archive is a directory containing `part-*` data files,
  the index `_index` (path → metadata, part file, offset, length) and `_masterindex` (segmented
  indirection over `_index`; its header carries the archive version). A PR touching the index must
  preserve both exact filenames and the version header, since older `HarFileSystem` versions read them.
- Streaming wire formats: stdio pipes between `PipeMapper`/`PipeReducer` and the subprocess, with record
  marshalling via `StreamBaseRecordReader`/`StreamXmlRecordReader` (XML) and the typedbytes format
  (`Type`, `Record`, `TypedBytesInput`/`Output`, `BinaryRecordInput`/`Output`; converters
  `LoadTypedBytes`/`DumpTypedBytes`); job context reaches the child via `Environment`. Hadoop Pipes uses
  its own C++ protocol (`HadoopPipes.cc`, serialization in `SerialUtils.hh/.cc`) — the two wire formats
  are unrelated and must not be conflated in requirements.

## 8. Non-functional requirement candidates

Each item below is phrased so it can be turned directly into a test/checklist row; subcomponent and key
class are named for diff-review targeting.

1. **S3A thread-pool invariants** — `S3AFileSystem` must expose exactly the bounded/unbounded executor
   pair of §4.1; `fs.s3a.threads.max` must bound *active* threads on the bounded pool, and pool growth
   beyond the configured maximum must queue, never spawn (`BlockingThreadPoolExecutorService` contract).
2. **S3A output backpressure** — `S3ABlockOutputStream` must block the writer when no free block exists
   and must never exceed the configured active-block/part limits; part uploads must be cancellable
   (`WriteOperationHelper.abortMultipart`-family) on `close()` failure.
3. **S3A span discipline** — with `fs.s3a.audit.reject.out.of.span.operations=true`, `AuditManagerS3A`
   must reject any S3 request executed without an active `AuditSpanS3A`, including requests from pooled
   threads (verifiable via `ActiveThreadSpanSource` span propagation tests).
4. **S3A credential-chain stability** — the default chain order of §5.1 must be preserved verbatim;
   removing `EnvironmentVariableCredentialsProvider` or `IAMInstanceCredentialsProvider` from
   `STANDARD_AWS_PROVIDERS` must fail review.
5. **S3A secret hygiene** — credentials and session tokens must never appear in `toString()`, logs, or
   exception text of `AWSCredentialProviderList`, `MarshalledCredentials`, or `S3AFileSystem`.
6. **S3A delegation-token lifetime** — `S3ADelegationTokens` must renew-bound tokens per the configured
   STS session duration (`DelegationConstants.DEFAULT_DELEGATION_TOKEN_DURATION` chain) and must fail
   closed (no anonymous fallback) when the bound binding cannot produce credentials.
7. **S3A encryption completeness** — every `S3AEncryptionMethods` value must be accepted by
   `S3AEncryption` and rejected with a clear error when its required key (`fs.s3a.encryption.key`) is
   missing for CSE/CSE-CUSTOM.
8. **S3A region resolution order** — `DefaultS3ClientFactory` must apply the endpoint/region order of
   §7.1 deterministically and warn exactly once when falling back to the SDK chain.
9. **Magic committer isolation** — task attempts must never share magic tracking paths
   (`MagicCommitPaths` + `MAGIC_PATH_PREFIX`), and job abort must complete-or-abort *all* pending uploads
   (`PendingSet`/`SinglePendingCommit`) with no orphaned multipart uploads left on successful job commit.
10. **ABFS throttling-first retry** — `AbfsClient` must run `AbfsClientThrottlingIntercept` before
    retrying; raw HTTP 429/500 storms must be visible through `AbfsClientThrottlingAnalyzer` counters.
11. **ABFS lease correctness** — when `fs.azure.infinite-lease.directories` covers a rename target,
    `AbfsLease` must acquire (≤7 retries) and always release in `free()`, including on exception paths;
    leaked leases must be detectable in tests.
12. **ABFS buffer bounds** — `AbfsOutputStream` must cap blocks at the configured write buffer
    (8 MB default; 4 MB for append-blob) and `AbfsAdaptiveInputStream`/`AbfsPrefetchInputStream` must cap
    read-ahead at the configured read buffer (4 MB default).
13. **IOStatistics continuity** — connector operations must publish through
    `org.apache.hadoop.fs.statistics` (`IOStatisticsContext` → snapshot), and any rename of a `Statistic`
    enum value or IOStatistics metric must be treated as a breaking API change.
14. **DistCp atomicity guarantee** — with `-atomic -tmp`, `CopyCommitter` must make the commit
    all-or-nothing at the final path and must clean partially copied files from failed attempts; without
    `-atomic`, partial-copy tolerance must be stated explicitly in requirements.
15. **DistCp listing concurrency bound** — `-numListstatusThreads` must bound concurrent source listing;
    unbounded listing fan-out (e.g. in `SimpleCopyListing`) must not be introduced.
16. **DistCp token completeness** — `CopyOutputFormat` must obtain tokens for every distinct source and
    destination filesystem (`TokenCache.obtainTokensForNamenodes`); a PR adding a new `CopyListing`
    implementation must not bypass the credentials path.
17. **HAR immutability and cache** — `HarFileSystem` must fail `create`/`rename`/`setOwner` and must
    serve concurrent readers through the synchronized `harMetaCache` without re-reading `_masterindex`/
    `_index` per lookup; honour `fs.har.impl.disable.cache`.
18. **Streaming record-format fidelity** — `PipeMapRed`/`PipeMapper` must round-trip typedbytes records
    (`TypedBytesInput`/`TypedBytesOutput`, `BinaryRecordInput`/`BinaryRecordOutput`) byte-for-byte;
    XML mode (`StreamXmlRecordReader`) must not split records mid-element.
19. **Metrics egress review** — `KafkaSink` and `S3AInstrumentation`/`S3AStorageStatistics` outputs must
    be treated as externally readable; new metrics must not embed usernames, URIs with credentials, or
    bucket names unless explicitly approved.
20. **Empty-module discipline** — `hadoop-openstack` (source deleted, jar retained) and the two no-source
    dist modules (`hadoop-cloud-storage`, `hadoop-tools-dist`) must stay source-free; PRs adding code
    there require a module-creation decision, not a patch review.
