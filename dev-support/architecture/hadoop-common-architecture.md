# Apache Hadoop "Common" — Architecture

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

A source-grounded tour of `hadoop-common-project/` for a Java engineer onboarding to the
Hadoop codebase. Depth 2: the modules of `hadoop-common-project/`, and inside
`hadoop-common` its first-level packages. All class names are real files under
`hadoop-common-project/*/src/main/java/`.

> **Document method.** This document follows the shared definition and method in
> [README.md](README.md) (*About these documents — definition and method*): a
> source-grounded orientation document pinned to the **As-of** trunk commit
> above, depth-2 scope, fixed section skeleton, merged-trunk state only.
> Updates land exclusively through dedicated arch/req review sessions;
> PR-review sessions record gaps as candidates in `notes/arch-req-candidates.md`
> instead of editing this file.

## Table of contents

1. [Overview and module layout](#1-overview-and-module-layout)
2. [Module: hadoop-annotations](#2-module-hadoop-annotations)
3. [Module: hadoop-auth](#3-module-hadoop-auth)
4. [Module: hadoop-auth-examples](#4-module-hadoop-auth-examples)
5. [Module: hadoop-common](#5-module-hadoop-common)
6. [Module: hadoop-kms](#6-module-hadoop-kms)
7. [Module: hadoop-minikdc](#7-module-hadoop-minikdc)
8. [Module: hadoop-nfs](#8-module-hadoop-nfs)
9. [Module: hadoop-registry](#9-module-hadoop-registry)
10. [Inter-module dependencies](#10-inter-module-dependencies)
11. [Concurrency](#11-concurrency)
12. [Security](#12-security)
13. [Logging and auditability](#13-logging-and-auditability)
14. [Integration points](#14-integration-points)
15. [Non-functional requirement candidates](#15-non-functional-requirement-candidates)
16. [Behaviour summary](#behaviour-summary)

## 1. Overview and module layout

`hadoop-common-project/` is the Hadoop layer *below* HDFS, YARN and MapReduce: shared
configuration, filesystem abstraction, serialization, RPC, security and lifecycle
machinery. The aggregator `pom.xml` lists eight modules:

| Module | What it is |
|---|---|
| `hadoop-annotations` | API-stability annotations only; near-zero dependencies |
| `hadoop-auth` | HTTP authentication framework (SPNEGO/Kerberos, JWT, pseudo) — not the RPC layer |
| `hadoop-auth-examples` | Servlet examples of `hadoop-auth` usage |
| `hadoop-common` | The core: conf, fs, ipc, io, security, service, metrics2, net, util |
| `hadoop-kms` | Web service front-end to the Hadoop KeyProvider API (encryption zones) |
| `hadoop-minikdc` | In-process MIT Kerberos KDC for testing Kerberized code |
| `hadoop-nfs` | NFSv3 gateway building blocks (XDR/oncrpc, mount, nfs3) |
| `hadoop-registry` | ZooKeeper/Curator service registry of `ServiceRecord`s |

`hadoop-common` also carries code out of scope here: `org.apache.hadoop.hdfs` client
plumbing, `ha`, `http` (HttpServer2), `crypto`, `tracing`, `log`, `jmx`, `tools`.

## 2. Module: hadoop-annotations

**Purpose:** compile-time annotation definitions with no runtime behaviour
(`org.apache.hadoop.classification`): `InterfaceAudience` (`@Public`, `@Private`,
`@LimitedPrivate("...")`), `InterfaceStability` (`@Stable`, `@Evolving`, `@Unstable`),
`VisibleForTesting`. Pure vocabulary consumed by tooling and reviewers — a `@Private`
marker is documentation, not enforcement. Root of the dependency graph: everything
imports it.

#### Package contents

One package, `org.apache.hadoop.classification`:

- `InterfaceAudience` — `@Public`, `@Private`, `@LimitedPrivate("...")` markers used
  by reviewers and release tooling to classify every public Java member.
- `InterfaceStability` — `@Stable`, `@Evolving`, `@Unstable` markers.
- `VisibleForTesting` — marks a declaration widened only for tests.
- `tools/` — javadoc doclets (`ExcludePrivateAnnotationsStandardDoclet`,
  `IncludePublicAnnotationsStandardDoclet`, `RootDocProcessor`,
  `StabilityOptions`) that filter generated javadoc by the markers above; the
  only executable code in the module.

No threads, locks or configuration of its own: the module is vocabulary plus
compile/javadoc-time tooling.

## 3. Module: hadoop-auth

**Purpose:** pluggable HTTP (servlet-filter) authentication, independent of the RPC/SASL
machinery in `hadoop-common`. Every HTTP endpoint (WebHDFS, RM UI, KMS) signs users in
via this module.

**Key classes:** `server/AuthenticationFilter` — the servlet `Filter`; validates a
signed `server/AuthenticationToken` cookie and delegates unknown requests to a
configured `server/AuthenticationHandler` — `PseudoAuthenticationHandler` (trusts
`?user.name=`, dev only), `KerberosAuthenticationHandler` (SPNEGO via GSS-API),
`AltKerberosAuthenticationHandler`, `JWTRedirectAuthenticationHandler`,
`LdapAuthenticationHandler`, `MultiSchemeAuthenticationHandler`. Client side:
`client/AuthenticatedURL` + `Authenticator`/`KerberosAuthenticator`/`PseudoAuthenticator`.
Token signing: `util/Signer` + `SignerSecretProvider` (`FileSignerSecretProvider`,
`RandomSignerSecretProvider`, `ZKSignerSecretProvider` with rollover — the ZK provider
shares the secret cluster-wide). `util/KerberosName`, `KerberosUtil` do Kerberos
name-rule translation (shared with `hadoop-common`'s `HadoopKerberosName`).

**Main data structures:** `AuthenticationToken extends AuthToken` (user, principal,
type, expiry, signature) in a cookie; `client/ConnectionConfigurator` for HTTPS tuning.

**Behaviour at runtime:** request → `doFilter` verifies the cookie (`Signer.verify`);
valid & unexpired → proceed with the user as a request attribute. Otherwise the handler
runs the auth dance (SPNEGO `WWW-Authenticate: Negotiate` challenge, or JWT redirect),
producing a token that is signed and set as a cookie. Wired into `HttpServer2` by
`hadoop-common`'s `AuthenticationFilterInitializer`.

#### server/ — the filter and handlers

- `AuthenticationFilter.doFilter` is the per-request entry point: the cookie is
  parsed into an `AuthenticationToken` (base `util/AuthToken`) and verified with
  the configured `Signer`; a valid, unexpired token is published as the
  `remoteUser` request attribute; anything else is delegated to the
  `AuthenticationHandler` instantiated at filter `init` from the `type`
  property. The handler's result is signed and written back as a cookie.
- Handlers: `PseudoAuthenticationHandler` (trusts `?user.name=`),
  `KerberosAuthenticationHandler` (SPNEGO — `init` loads the keytab into a
  `serverSubject` carrying the SPNEGO principals, and each challenge drives a
  per-request GSS context), `AltKerberosAuthenticationHandler`,
  `JWTRedirectAuthenticationHandler`, `LdapAuthenticationHandler`,
  `MultiSchemeAuthenticationHandler`, `CompositeAuthenticationHandler`;
  `AuthenticationHandlerUtil` holds shared checks.
- Threading: the filter is stateless per request; the only long-lived mutable
  state is the `SignerSecretProvider` created in `init` and destroyed in
  `destroy`.

#### client/ — client-side authenticators

`AuthenticatedURL` attaches a signed token to an `HttpURLConnection` through an
`Authenticator`: `KerberosAuthenticator` runs the SPNEGO dance directly over
GSS-API, `PseudoAuthenticator` appends `?user.name=`.
`ConnectionConfigurator` centralizes HTTPS tuning (trust/keystore) for those
connections.

#### util/ — signing and Kerberos helpers

`Signer` is the HMAC wrapper (`sign`/`verifyAndRestore`) over a
`SignerSecretProvider`; `RolloverSignerSecretProvider` is the base for the
providers that rotate secrets (`FileSignerSecretProvider`,
`RandomSignerSecretProvider`, `ZKSignerSecretProvider` via `ZookeeperClient`).
`KerberosName`/`KerberosUtil` implement `auth_to_local` name-rule translation;
`SubjectUtil` and `JaasConfiguration` build JAAS subjects programmatically;
`CertificateUtil` parses certificate chains.

## 4. Module: hadoop-auth-examples

Runnable servlet examples demonstrating each `hadoop-auth` handler and its client
counterpart. Documentation in code form; depends only on `hadoop-auth`.

#### Contents

Servlets under `org.apache.hadoop.security.authentication.examples`
(`WhoServlet`, `WhoClient`, `RequestLoggerFilter`) pair each server handler
with its client `Authenticator` behind an embedded web server. The module
exists to be run manually; nothing in the tree depends on it.

## 5. Module: hadoop-common

The heart of the project. Subsystems below in dependency order.

### org.apache.hadoop.conf — Configuration

**Purpose:** the universal key/value configuration object; every subsystem receives a
`Configuration` and reads its settings from it. **Key classes:** `Configuration`,
`Configured`/`Configurable`, `ReconfigurableBase` +
`ReconfigurationServlet` (hot-reloadable settings), `ConfServlet` (dump as JSON),
`ConfigRedactor` (hides sensitive keys), `StorageSize`/`StorageUnit` (parsing "512m").
**Main data structures:** a `java.util.Properties` of final values plus a `Resource`
list (names/URLs/files/classpath entries) that produced them; typed getters
(`getInt`, `getTimeDuration`, `getStorageSize`, `getClass`, `getInstances`).
**Behaviour at runtime:** `loadResources` walks the resource list — defaults
(`core-default.xml`), user XML (`core-site.xml`), programmatic adds — filling only
unset keys, so *last resource wins*. Any `set*` or `reloadConfiguration` invalidates
values; the next get re-runs the walk. `getClass(..., Configuration)` wires the new
instance back via `Configurable.setConf`. `ReconfigurableBase` re-evaluates a
white-list of changeable properties and invokes `reconfigurePropertyImpl` on the owner.

#### Resource loading

- A `Configuration` holds `resources: ArrayList<Resource>` — the private static
  class `Resource` wraps a name plus a file/URL/classpath object and the
  modified time it was read at. `loadResources` walks the list in add order;
  `loadResource` reads XML (or a plain/properties object resource) into a
  temporary `Properties` and only fills keys still unset, so the last resource
  wins and defaults added first are weakest.
- Mutable state: `properties` (the materialized view), `overlay` (values set
  programmatically, re-applied last on every re-walk so `set` survives
  reloads), and `finalParameters` (keys declared `<final>` that later `set`s
  must reject). `reloadConfiguration()` only clears `properties` and
  `finalParameters`; the walk is repeated lazily on the next get.

#### Typing, instantiation and tooling

- Typed getters (`getInt`, `getLong`, `getTimeDuration`, `getStorageSize`,
  `getClassByName`, `getInstances`) convert strings on read and cache resolved
  classes in `CACHE_CLASSES`; `Configurable`/`Configured` pass the instance
  into freshly created objects. `ConfigurationWithLogging` logs which resource
  supplied a value.
- `Reconfigurable`/`ReconfigurableBase` + `ReconfigurationException` +
  `ReconfigurationTaskStatus` implement hot reload of a white-listed property
  set; `ReconfigurationServlet` exposes it over HTTP; `ReconfigurationUtil`
  helps tests drive it.
- `ConfServlet` dumps configuration as JSON; `ConfigRedactor` redacts
  password-like keys from those dumps; `StorageSize`/`StorageUnit` parse human
  quantities.

### org.apache.hadoop.fs — abstract FileSystem API

**Purpose:** the `hdfs://`, `file://`, `s3a://`, ... abstraction: a `java.io.File`-like
API over any storage plus client-side utilities. **Key classes:** `FileSystem` —
abstract base extending `Configured` (`open`, `create`,
`append`, `mkdirs`, `rename`, `delete`, `listStatus`, `globStatus`, `getFileStatus`);
`AbstractFileSystem` / `FileContext` — the alternative URI-per-scheme API
(`FsConstants`) with `FileSystemLinkResolver`/`FSLinkResolver` retry loops;
`FilterFs`/`FilterFileSystem` decorate both; `FSDataInputStream` (wraps `Seekable`,
`PositionedReadable`, `CanSetReadahead`, `CanUnbuffer`) and `FSDataOutputStream`
(built via `FSDataOutputStreamBuilder`); local stack `local/RawLocalFs` →
`local/LocalFs` (checksummed) via `ChecksumFileSystem`/`FSInputChecker`/
`FSOutputSummer`; listing/metadata `Globber`, `GlobPattern`, `FileStatus`,
`BlockLocation`, `FsServerDefaults`, `ContentSummary`; `FsShell` (the `hadoop fs` CLI),
`ftp/FTPFileSystem`, `HarFileSystem`/`HarFs`, `DelegationTokenRenewer`.

**Main data structures:** `FileSystem.CACHE` — `Map<Key, FileSystem>`
(`map = new HashMap<>()`), `Key` = (URI scheme+authority, user UGI, unique flag);
per-class `Statistics` in a `Map<Class<? extends FileSystem>, Statistics>`.

**Behaviour at runtime:** `FileSystem.get(URI, Configuration)` computes a `Key` from
URI + current UGI and consults `CACHE`; a miss calls `createFileSystem`, which reads
`fs.<scheme>.impl` from `Configuration` and reflectively instantiates it — one shared
client per (URI, user) per JVM; `closeAll(ugi)` closes all for a user (a
`ClientFinalizer` runs it at UGI logout). `ChecksumFileSystem` wraps reads in a
`ChecksumFSInputChecker`: opens the sibling `.checksum` file (`getChecksumFile`), seeks
to `getChecksumFilePos(pos)` per chunk, verifies CRCs in `readChunk`, throws
`ChecksumException` on mismatch; on write `FSOutputSummer` computes CRCs and `close`
writes the sidecar. `globStatus` expands patterns through `Globber`/`GlobExpander`
walking the real tree via `listStatus`, so filtering is server-side. HDFS, S3A, ABFS
etc. all implement this SPI; `FileContext` is the non-cached, scheme-explicit
alternative.

#### Package layout

Sub-packages are thin: `impl/` and `local/` carry concrete filesystem and
shared helper implementations; `viewfs/` is the federation mount table;
`permission/` the POSIX-style permission and ACL model; `shell/` the CLI
command framework; `statistics/` and `store/` IO statistics and object-store
support (including `store/audit/` spans); `ftp/`, `sftp/`, `http/` additional
protocol clients; `protocolPB/` protobuf helpers; `crypto/` filesystem-level
encryption helpers.

#### The cache and the local stack

- `FileSystem.get(URI, conf)` builds a `Cache.Key` (URI scheme+authority, UGI,
  unique flag) and consults the static `CACHE`; concurrent creation is bounded
  by the `fs.creation.parallel.count` semaphore and racing losers close their
  duplicates (§11.2). Implementations are resolved from
  `fs.<scheme>.impl`/`fs.abstract.<scheme>.impl` and instantiated by
  reflection; `FilterFileSystem`/`FilterFs` decorate them.
- `closeAll()`/`closeAll(UserGroupInformation)` provide bulk and per-user
  teardown; the `ClientFinalizer` hook closes still-open filesystems at JVM
  exit and a UGI logout closes that user's instances. `DelegationTokenRenewer`
  (fs root) is a single renewal `Thread` for fs delegation tokens held by the
  logged-in UGI (§12.4).
- Local stack: `local/RawLocalFs` is the `AbstractFileSystem` view over
  `RawLocalFileSystem`; `local/LocalFs` adds checksumming — the same split as
  `RawLocalFileSystem` (uncached, unchecksummed) vs `LocalFileSystem` (a
  `ChecksumFileSystem` wrapper) at package root.

#### Checksums

- Read path: `ChecksumFileSystem` opens the sibling `.<name>.crc` sidecar
  (`getChecksumFile`), and `ChecksumFSInputChecker` verifies CRCs per chunk
  (`FSInputChecker` machinery), throwing `ChecksumException` on mismatch; a
  missing sidecar skips validation rather than failing.
- Write path: `FSOutputSummer` computes CRCs per `bytesPerChecksum`-sized chunk
  and `close` writes the sidecar. `BufferedFSInputStream`,
  `FSInputStream`/`FSDataInputStream` layer seekability, readahead
  (`CanSetReadahead`) and unbuffering (`CanUnbuffer`) on top.

#### viewfs — mount tables

`ViewFileSystem` (FileSystem API) and `ViewFs` (AbstractFileSystem API)
resolve URIs through an `InodeTree` built from `fs.viewfs.mounttable.*` keys
(`viewfs/Constants.CONFIG_VIEWFS_PREFIX`); internal nodes are
`ChRootedFileSystem`/`ChRootedFs` views over the target filesystem at a
sub-path; `RegexMountPoint` (with its interceptor chain) supports regex link
targets and `NflyFSystem` mirrors writes to several targets. Mount tables are
client configuration; `ConfigUtil` and `HCFSMountTableConfigLoader` load them.

#### permission, shell, statistics

- `permission/`: `FsPermission` (+`FsAction` bit sets, `FsCreateModes`), the
  ACL model (`AclEntry`, `AclEntryScope`, `AclEntryType`, `AclStatus`,
  `AclUtil`) and the CLI parsers (`ChmodParser`, `UmaskParser`,
  `PermissionParser`, `RawParser`) behind `PermissionStatus`.
- `shell/`: `Command` base class, `CommandFactory` registry of `FsCommand`
  subclasses (`Ls`, `Count`, `Delete`, `CopyCommands`, `MoveCommands`,
  `AclCommands`, `XAttrCommands`, `TouchCommands`, `SnapshotCommands`, the
  `find` package), `CommandFormat` option parsing and `PathData` (a `Path`
  plus its resolved `FileStatus`). `FsShell` dispatches user input through
  this framework.
- `statistics/`: `IOStatisticsContext` is a per-thread aggregator —
  `IOStatisticsContextIntegration.getCurrentIOStatisticsContext()` resolves the
  calling thread's context from a `WeakReferenceThreadMap` (not a
  `java.lang.ThreadLocal`); contexts merge into `IOStatisticsSnapshot`s and
  `IOStatisticsBinding` wires streams into them.

#### impl/ — shared client helpers

`impl/` carries machinery shared across filesystems: `FSBuilderSupport`
(behind `FSBuilder`), `FileSystemMultipartUploader` (the `MultipartUploader`
SPI with `PartHandle`/`UploadHandle`), `VectorIOBufferPool` (pooling for the
vectored-read API), `LeakReporter`, and `impl/prefetch/` — a block prefetch
cache (`BlockManager`, `CachingBlockManager`, `SingleFilePerBlockCache`,
`ResourcePool`/`BoundedResourcePool`, `ExecutorServiceFuturePool`, `Retryer`)
that performs background block fetches on its own executor pool for readers
that enable it.

#### Other clients and utilities

`ftp/FTPFileSystem` (+`FTPInputStream`, `FtpConfigKeys`),
`sftp/SFTPFileSystem` (+`SFTPConnectionPool`),
`http/AbstractHttpFileSystem` with `HttpFileSystem`/`HttpsFileSystem`,
archive `HarFileSystem`/`HarFs`, `Trash` + `TrashPolicy`/
`TrashPolicyDefault` (delete-to-trash semantics), `LocalDirAllocator`
(spread temp data over configured local dirs), `FileUtil`, `Stat`,
`VectoredReadUtils`, `FutureDataInputStreamBuilder` (async `openFile`),
`PathCapabilities`/`StreamCapabilities` feature probes, and
`CommonConfigurationKeys(Public)` for the shared keys.

### org.apache.hadoop.ipc — RPC framework

**Purpose:** the wire protocol + client/server machinery behind every inter-node call:
client↔NameNode, NameNode↔DataNode, RM↔NM. **Key classes:** `RPC` — facade
(`getProxy`/`getServer`, `RpcKind` engine selection);
engines `ProtobufRpcEngine2` (current) and legacy `ProtobufRpcEngine`/
`WritableRpcEngine`, all implementing `RpcEngine`; `ProtocolProxy`, `ProtocolSignature`,
`ProtocolInfo` negotiate versions; `Client` + `ClientCache` — client side, keyed by
`ConnectionId`; `Server` (`RPC.Server`) plus `CallQueueManager`, `FairCallQueue`,
`DecayRpcScheduler`, `WeightedRoundRobinMultiplexer` — server side and scheduling;
`RetryCache` dedups retried calls; `RefreshCallQueueProtocol`/`RefreshRegistry` for
live reconfiguration; `RpcWritable.Buffer`, `RpcInvocationHandler`; SASL hooks
(`security` provides `SaslRpcClient`/`SaslRpcServer`).

**Main data structures:** `Client.Call` (id, request, response buffer, done flag,
`RemoteException`); `Client.Connection extends Thread` with `calls: Hashtable<Integer, Call>`
(thread-safe by construction) and `shouldCloseConnection: AtomicBoolean`; server `Server.Call implements Schedulable`, the single
`CallQueueManager<Call>` hand-off, and `Listener`/`Reader`/`Responder`/`Handler`
thread pools tracked by `ConnectionManager`.

**Behaviour — client:** the protobuf proxy's `Invoker.invoke(Object proxy, Method, args)`
(`ProtobufRpcEngine2`) validates the `RpcController`+`Message` args, opens a tracing
span, wraps the request (`constructRpcRequest`), then
`client.call(rpcKind, request, remoteId, ...)` gets/creates a `Connection`
(`setupIOstreams` negotiates connection header + SASL), writes the request, registers
the `Call` and parks the caller until the connection's `run` loop (`waitForWork`)
matches the response by call id — value or unwrapped `RemoteException`. Asynchronous
calls (`ExternalCall`, `Client.isAsynchronousMode`) share the same connection and
are bounded by `ipc.client.asyncCalls.max` (§11.3).

**Behaviour — server:** `Listener` accepts; NIO `Reader` threads decode headers
(`processConnectionContext`, `processOneRpc`) and build `Server.Call`s;
`CallQueueManager.put` inserts into the active queue (plain `LinkedBlockingQueue` by
default, or `FairCallQueue` + `DecayRpcScheduler` priorities to protect small users
under floods — swapped live via `swapQueue`); `Handler` workers `take()` a call, invoke
the target through the engine's server translator
(`ProtobufRpcEngineCallback2`/`RpcWritable`), and `Responder` flushes replies.
`RetryCache` (a `LightWeightGSet` in `util`) remembers recent retriable calls by
client+call id so a retry returns the first response instead of re-executing.

#### Package layout

Root classes cover both endpoints (`Client`, `Server`, `RPC`); sub-packages
are thin: `internal/` (shaded-protobuf helpers), `metrics/` (`RpcMetrics`,
`RpcDetailedMetrics`, `RetryCacheMetrics`, `DecayRpcSchedulerDetailedMetrics`),
`protocolPB/` (client/server-side translators for the refresh protocols), and —
belonging to hadoop-common but consumed by hadoop-nfs — `oncrpc/` and
`portmap/`.

#### Client side — `Client`, `Connection`, `ConnectionId`

- `Client` is shared per `SocketFactory` through `ClientCache`
  (`Map<SocketFactory, Client>`).
- `Connection extends Thread` (named
  `IPC Client (<socketFactory.hashCode()>) connection to <addr>`) is created
  per `ConnectionId` (address, protocol, ticket, timeout). The first call runs
  `setupIOstreams` (synchronized: TCP connect, "hrpc" connection header,
  protocol negotiation, optional SASL wrap via `SaslRpcClient`) and then the
  connection thread owns the socket.
- A caller registers its `Client.Call` in `Connection.calls` and
  `sendRpcRequest` writes it to the socket; the connection `run` loop spins on
  `waitForWork()` → `receiveRpcResponse()`, matching responses to calls by id
  and completing the parked caller (§11.3 covers the concurrency model).
- Asynchronous mode: `isAsynchronousMode()`/`ExternalCall` let a caller
  collect the response later; `checkAsyncCall` bounds in-flight async calls at
  `ipc.client.asyncCalls.max` and throws `AsyncCallLimitExceededException`.

#### Server side — accept, process, respond

- `Listener` (one thread, "IPC Server listener on <port>") accepts sockets and
  hands them to `Reader` threads (count `ipc.server.read.threadpool.size`),
  each owning a NIO `readSelector` and a bounded pending-connection queue;
  readers decode the connection context and RPC headers (`processOneRpc`) and
  build `Server.Call`s.
- `CallQueueManager.put` is the single hand-off into the active queue;
  `Handler` threads ("IPC Server handler N on <port>") `take()` a call, run
  the engine's server-side translation (`ProtobufRpcEngineCallback2`,
  `RpcWritable`) into the actual protocol implementation, and serialize the
  response into a `ResponseBuffer`.
- `Responder` ("IPC Server Responder") is one thread with a NIO `Selector`;
  responses that do not flush immediately are deferred to it so `Handler`
  threads never block on a slow client.
- `ConnectionManager` tracks connections (idle scanner, per-user maps —
  §11.3); `RpcCall` extends `Server.Call` with the RPC-kind payload.

#### Scheduling and the call queue

`CallQueueManager` delegates to a pluggable `BlockingQueue<Call>`: the default
`LinkedBlockingQueue`, or `FairCallQueue` with `DecayRpcScheduler` (priority
by recent call volume, `WeightedRoundRobinMultiplexer` between queues,
`UserIdentityProvider` for identity) — swapped live via
`RefreshCallQueueProtocol`/`RefreshRegistry`. `RpcScheduler`/
`DefaultRpcScheduler`, `CostProvider`/`DefaultCostProvider`/
`WeightedTimeCostProvider` and `ProcessingDetails` compute and report per-call
cost; queue and processing latency flow into the `metrics/` MXBeans.

#### Deduplication and refresh hooks

- `RetryCache` stores `CacheEntry` in a `LightWeightGSet` keyed by clientId +
  callId; a retried call finds the entry and returns the recorded response
  instead of re-executing (entry state transitions synchronized, §11.3).
- The live-refresh surfaces (`RefreshCallQueueProtocol`,
  `GenericRefreshProtocol` + `RefreshHandler`/`RefreshResponse`) have their
  wire translators in `protocolPB/`; `CallerContext`/`ClientId` carry
  correlation data onto every call (§13).

#### oncrpc and portmap (used by hadoop-nfs)

`oncrpc/` implements the ONC-RPC wire format used by the NFS gateway: `XDR`
(encoding/decoding), `RpcCall`/`RpcReply`/`RpcAcceptedReply`/
`RpcDeniedReply`/`RpcMessage`/`RpcResponse`, `RpcProgram` (the dispatch
surface), the Netty-based servers `SimpleTcpServer`/`SimpleUdpServer` with
client counterparts (`SimpleTcpClient`, `SimpleUdpClient`), `RpcCallCache`
for duplicate-request detection, and `oncrpc/security/` (`Credentials`/
`CredentialsGSS`/`CredentialsSys`, the `Verifier` family, `SecurityHandler`).
`portmap/` implements the portmapper protocol (`Portmap`, `PortmapMapping`,
`RpcProgramPortmap`) so NFS services can register their ports.

### org.apache.hadoop.security — UGI, Kerberos, authorization

**Purpose:** identity (`UserGroupInformation`), staying logged in (Kerberos relogin),
groups, authorization, and RPC identity proof (SASL/token). **Key classes:**
`UserGroupInformation` (UGI), `User`, `Credentials` (delegation-token
map), `HadoopKerberosName`; `Groups` + `GroupMappingServiceProvider` implementations
(`ShellBasedUnixGroupsMapping`, `JniBasedUnixGroupsMapping(WithFallback)`,
`LdapGroupsMapping`, `RuleBasedLdapGroupsMapping`, `CompositeGroupsMapping`; netgroups
via `JniBasedUnixGroupsNetgroupMapping` + `NetgroupCache`); SASL plumbing
`SaslRpcClient`/`SaslRpcServer`, `SaslPropertiesResolver`, `WhitelistBasedResolver`,
`SaslPlainServer`, `SaslInputStream`/`SaslOutputStream`; authorization
`security/authorize/*` (`AccessControlList`, `AuthorizationProvider`),
`AccessControlException`; `SecurityUtil` (service-principal construction), `KDiag`.

**Main data structures:** a JAAS `Subject` per UGI (`User` principals, tokens);
`Credentials` token map; the login UGI plus thread-local current UGI; a cached
host→groups map in `Groups`.

**Behaviour at runtime:** `getLoginUser()` builds a `Subject` (`createLoginUser`) and,
when a keytab is set, spawns auto-renewal (`spawnAutoRenewalForUserTokenThread`).
`checkTGTAndReloginFromKeytab()` / `reloginFromKeytab()` compare TGT expiry against the
renew window and, if stale, re-run the JAAS login (synchronized against concurrent
threads), swapping the subject — daemons call it atop each RPC handler, clients before
expensive operations. `doAs(PrivilegedExceptionAction)` runs inside
`SubjectUtil.doAs(subject, action)` (JAAS `Subject.doAs`), unwrapping
`PrivilegedActionException` causes back to the original checked exception.
`FileSystem.get` keys its cache on UGI, so two users in one JVM get separate
`FileSystem` instances — per-user isolation. `Groups.getGroups(user)` consults a cached
map, falling back to the configured mapping chain.

#### Package layout

Root classes: identity (`UserGroupInformation`, `User`, `Credentials`,
`HadoopKerberosName`, `KerberosAuthException`), SASL (`SaslRpcClient`,
`SaslRpcServer` and friends), groups (`Groups` + mapping providers), glue
(`SecurityUtil`, `KDiag`, `KerberosInfo`/`SecurityInfo`/
`AnnotatedSecurityInfo` for annotation-driven protocol security data,
`AuthenticationFilterInitializer`, `HttpCrossOriginFilterInitializer`,
`RefreshUserMappingsProtocol`). Sub-packages: `token/` (+`delegation/`,
`web/`), `authorize/`, `authentication/server/`, `ssl/`, `alias/`,
`protocolPB/`.

#### UserGroupInformation and login

- A UGI wraps a JAAS `Subject` holding a `User` principal (authentication
  method, real user, volatile `lastLogin`) plus `Credentials` (token map) and
  token identifiers. `getCurrentUser()`/`getLoginUser()` resolve the
  thread-effective vs process-login identity; `doAs(PrivilegedExceptionAction)`
  runs under the subject and unwraps `PrivilegedActionException` causes.
- `loginUserFromKeytab` performs the JAAS login and
  `spawnAutoRenewalThreadForKeytab` submits a `KeytabRenewalRunnable` to the
  single-thread daemon executor ("TGT Renewer for <user>"); ticket-cache users
  get `TicketCacheRenewalRunnable` (shelling out to `kinit`). Re-login is
  serialized on `HadoopLoginContext.getSubjectLock()` and rate-limited by
  `hadoop.kerberos.min.seconds.before.relogin` (§11.4);
  `checkTGTAndReloginFromKeytab()`/`reloginFromKeytab()` are the hooks daemons
  call before using credentials.
- `createProxyUser`/`createRemoteUser` build the impersonation identities
  checked by `authorize/ProxyUsers` (§12.6).

#### Groups

`Groups` wraps a `GroupMappingServiceProvider` chain in a Guava `LoadingCache`
(expiry, negative cache and optional background-refresh pool — §11.4).
Providers: `ShellBasedUnixGroupsMapping`,
`JniBasedUnixGroupsMapping(WithFallback)`, `LdapGroupsMapping`,
`RuleBasedLdapGroupsMapping`, `CompositeGroupsMapping`, `NullGroupsMapping`;
netgroups via `JniBasedUnixGroupsNetgroupMapping` + `NetgroupCache`; ID
translation helpers `ShellBasedIdMapping`/`IdMappingServiceProvider`.

#### SASL and RPC identity

`SaslRpcServer`/`SaslRpcClient` negotiate GSSAPI/DIGEST/PLAIN per the
`hadoop.rpc.protection` QOP resolved by `SaslPropertiesResolver`
(`WhitelistBasedResolver`, `IngressPortBasedResolver` override per peer or
ingress port); `FastSaslClientFactory`/`FastSaslServerFactory` cache the
underlying factory lookups; `SaslInputStream`/`SaslOutputStream` wrap
negotiated streams; `SaslPlainServer`, `SaslMechanismFactory` and
`CustomizedCallbackHandler` complete the PLAIN path.

#### Tokens (security/token/)

- `Token`, `TokenIdentifier`, `TokenSelector`, `TokenRenewer`, `SecretManager`
  plus the fetch/renew CLI stack (`DtFetcher`, `DtUtilShell`,
  `DtFileOperations`, `DelegationTokenIssuer`).
- `delegation/` implements the standard delegation pattern:
  `AbstractDelegationTokenIdentifier`, `AbstractDelegationTokenSecretManager`
  (+`DelegationKey`), `AbstractDelegationTokenSelector`,
  `DelegationTokenLoadingCache` (a small Guava-backed cache), and the shared
  backends `ZKDelegationTokenSecretManager`/`SQLDelegationTokenSecretManager`.
  `startThreads` starts the background `ExpiredTokenRemover` daemon thread
  (`tokenRemoverThread`) that periodically drops expired tokens; `stopThreads`
  interrupts and joins it. `web/` carries the HTTP delegation-token filter
  plumbing (§12.2).

#### Authorization, credential providers, HTTP glue, SSL

- `authorize/`: `ServiceAuthorizationManager` (per-protocol ACLs + host lists
  from `hadoop-policy.xml`, §12.5), `PolicyProvider`/`Service` registration,
  `AccessControlList`, `ImpersonationProvider`/`DefaultImpersonationProvider` +
  `ProxyUsers`/`ProxyServers` (§12.6), and the admin RPC
  `RefreshAuthorizationPolicyProtocol` (translators in `protocolPB/`).
- `alias/`: the credential-provider API (`CredentialProvider`,
  `CredentialProviderFactory`, `CredentialShell`) with keystore backends
  (`JavaKeyStoreProvider`, `LocalJavaKeyStoreProvider`,
  `BouncyCastleFipsKeyStoreProvider`, `LocalBouncyCastleFipsKeyStoreProvider`,
  `UserProvider`).
- `authentication/server/`: `ProxyUserAuthenticationFilter` +
  `ProxyUserAuthenticationFilterInitializer` extend the hadoop-auth chain with
  proxy-user validation (§12.6).
- `ssl/`: `SSLFactory`, `KeyStoresFactory`/`FileBasedKeyStoresFactory`,
  `ReloadingX509TrustManager`/`ReloadingX509KeystoreManager`,
  `FileMonitoringTimerTask`, `SSLHostnameVerifier`,
  `DelegatingSSLSocketFactory` (§12.3).

### org.apache.hadoop.io — Writable serialization

**Purpose:** Hadoop's compact serialization + IO utilities — still used for block
data, sequence files, and the legacy WritableRpcEngine. **Key classes:** `Writable`
(`write`/`readFields` on `DataOutput`/`DataInput`), `WritableComparable<T>`,
`RawComparator`/`WritableComparator`, `WritableFactories`;
primitives `IntWritable`, `LongWritable`, `Text`, `BytesWritable`, `ArrayWritable`,
`MapWritable`, `NullWritable`, `ObjectWritable`, `GenericWritable`, varint
`VIntWritable`/`VLongWritable`, `MD5Hash`; files `SequenceFile`,
`MapFile`/`BloomMapFile`, buffers `DataOutputBuffer`/`DataInputBuffer`;
`Text extends BinaryComparable` (mutable UTF-8 byte array, `validateUTF8`); `compress/*`
(`CompressionCodec`s for Gzip/Snappy/LZ4/Zstd, pooled via `CodecPool`); `nativeio/*`
(`NativeIO`, `SecureIOUtils`).

**Main data structures:** length-prefixed byte arrays (`Text` stores `bytes`+`length`
in one buffer); `SequenceFile`'s writer metadata + block buffers; `CodecPool` free
lists.

**Behaviour at runtime:** `write/readFields` is a hand-written binary format —
`Text.writeString` writes a varint length then raw UTF-8; no schema, so
`ObjectWritable`/`WritableName` carry class names when types aren't static.
`WritableComparator.get(Class)` returns a cached comparator able to compare record
prefixes inside a byte array — the trick the MapReduce shuffle uses to sort without
deserializing. `SequenceFile.Writer.append` serializes key/value, computes checksums,
writes sync markers every `SYNC_INTERVAL`; readers seek by those markers.

#### Package layout

Root: the `Writable` vocabulary and primitives, `Text`, buffers,
`SequenceFile`/`MapFile`, `IOUtils`, `ReadaheadPool`. Sub-packages:
`compress/`, `file/tfile/`, `erasurecode/`, `nativeio/`, `retry/`,
`serializer/`, `wrappedio/`.

#### Writable core

- `Writable` (`write(DataOutput)` / `readFields(DataInput)`) is a hand-written
  binary format; `WritableComparable`, `RawComparator`/`WritableComparator`
  (cached, deserialization-free comparison of serialized bytes), and
  `WritableFactories`/`WritableName` for reflective creation. Primitives
  (`IntWritable`, `LongWritable`, `Text`, `BytesWritable`, ...), containers
  (`ArrayWritable`, `MapWritable`, `SortedMapWritable`, `EnumSetWritable`),
  varints (`VIntWritable`/`VLongWritable`), `MD5Hash`, `NullWritable`,
  `ObjectWritable`/`GenericWritable` for runtime-typed values.
- `Text extends BinaryComparable`: a mutable UTF-8 byte array with
  `validateUTF8`; `DataOutputBuffer`/`DataInputBuffer` are the reusable
  in-memory streams behind Writable IO.

#### Files and codecs

- `SequenceFile.Writer`/`Reader` — length-prefixed, checksummed,
  sync-markered key/value records; `MapFile`/`BloomMapFile`/`ArrayFile`/
  `SetFile` add sorted (and bloom-filtered) indexes on top;
  `file/tfile/TFile` (+`BCFile`) is the block-compressed, comparator-indexed
  variant (`TFileDumper` inspects it).
- `compress/`: `CompressionCodec` implementations (`DefaultCodec`,
  `GzipCodec`, `BZip2Codec`, `Lz4Codec`, `SnappyCodec`, `ZStandardCodec`,
  `DeflateCodec`, `PassthroughCodec`), `CompressionCodecFactory` (codec
  lookup by name/extension), splittable codecs (`SplitCompressionInputStream`),
  direct decompression (`DirectDecompressionCodec`), and `CodecPool` leasing
  pooled `Compressor`/`Decompressor`/checksum instances (`DoNotPool` opts
  out). Stream plumbing: `CompressionInputStream`/`CompressionOutputStream`
  and the block variants.

#### erasurecode, nativeio, retry, serializer

- `erasurecode/`: the raw-erasure coder framework — `ECSchema`, `ECBlock`/
  `ECBlockGroup`/`ECChunk`, `CodecRegistry`, `ErasureCodeNative` (native
  ISA-L loading) with `rawcoder/`, `coder/`, `grouper/` packages.
- `nativeio/`: `NativeIO` (POSIX/Windows syscalls — fstat, posix_fadvise, file
  ownership), `SecureIOUtils` (ownership-checked access), `Errno`,
  `SharedFileDescriptorFactory`.
- `retry/`: `RetryProxy` + `RetryInvocationHandler` wrap a protocol proxy with
  `RetryPolicy`/`RetryPolicies` (failover via `FailoverProxyProvider`/
  `DefaultFailoverProxyProvider`), honouring `Idempotent`/`AtMostOnce` method
  annotations and `AsyncCallHandler`.
- `serializer/`: `Serialization`/`SerializationFactory` +
  `WritableSerialization` (and `avro/`) give SequenceFile pluggable record
  formats; `wrappedio/WrappedIO` is the static facade over statistics-
  instrumented IO.

### org.apache.hadoop.metrics2 — metrics

**Purpose:** the "Metrics2" system — sources push records into a pluggable sink
pipeline (JMX, files, Graphite...). **Key classes:** API `MetricsSource`,
`MetricsRecord(Builder)`, `MetricsCollector`,
`MetricsTag`, `MetricsSink`, `MetricsSystem`; `lib/` (`MutableCounter`/`MutableGauge`
families, `MetricsRegistry`, `DefaultMetricsSystem`, `MetricsAnnotations` adapting
`@Metric` beans); `impl/` (`MetricsSystemImpl`, `MetricsSourceAdapter`,
`MetricsSinkAdapter`, `MetricsBuffer(Builder)`, `SinkQueue`, `MetricsConfig`);
`sink/` (`FileSink`, `GraphiteSink`, `RollingFileSystemSink`...).

**Main data structures:** `MetricsBuffer` (timestamped per-source records) flowing
source adapter → system → sink adapters; bounded blocking `SinkQueue` per sink;
`MetricsConfig` (a `*.sink.*`/`*.source.*`-prefixed tree).

**Behaviour at runtime:** sources register via `DefaultMetricsSystem.initialize`/
`register`; `MetricsSystemImpl` wraps each in a `MetricsSourceAdapter`. On a timer it
calls `source.getMetrics(collector, all)`, filters, and enqueues into each sink's
`SinkQueue`; a per-sink thread drains and calls `sink.putMetrics(record)` — slow sinks
never block the sampling thread (cost is dropped records). `@Metric` fields become
in-place gauges/counters.

#### Package layout

API (`MetricsSource`, `MetricsRecord`, `MetricsCollector`, `MetricsSink`,
`MetricsSystem`, `MetricsTag`, `MetricsFilter`), `annotation/` (`@Metric`,
`@Metrics`), `lib/` (mutable metric types + registry), `impl/` (the system),
`sink/`, `source/` (`JvmMetrics`), `filter/` (`RegexFilter`, `GlobFilter`),
`util/` (`MetricsCache`, `MBeans`, quantile estimators).

#### lib/ — metric builders

`MetricsRegistry` is the per-source registry of `MutableMetric`s;
`MutableCounter(Int/Long)`, `MutableGauge(Int/Long/Float)`, `MutableRate`,
`MutableStat`, `MutableQuantiles`, `MutableRollingAverages`,
`MutableRates(WithAggregation)` are updated in place by the owning code;
`MetricsAnnotations` + `MutableMetricsFactory` + `MetricsSourceBuilder` turn
`@Metric`-annotated beans into sources; `DefaultMetricsSystem`/
`DefaultMetricsFactory` are the static entry points daemons use.

#### impl/ — the sampling pipeline

- `MetricsSystemImpl` lifecycle (`init`/`start`/`stop`) parses `MetricsConfig`
  (the `*.sink.*`/`*.source.*` tree), wraps each source in a
  `MetricsSourceAdapter` (which may register an MBean via `util/MBeans`), and
  starts the sampling `Timer` (§11.6).
- Each sample: `MetricsCollectorImpl` collects records from all adapters into
  a `MetricsBuffer`; each `MetricsSinkAdapter` filters records (via
  `filter/` classes), enqueues into its bounded `SinkQueue` and drains it on
  its dedicated thread; `MetricsRecordImpl`/`MetricsRecordFiltered` and the
  `Metric*` classes are the immutable record types; `MBeanInfoBuilder`
  supports the JMX view.

#### sink/ and source/

Sinks shipped in-tree: `FileSink`, `RollingFileSystemSink`, `GraphiteSink`,
`StatsDSink`, `PrometheusMetricsSink`, plus the legacy `ganglia/` sinks.
`source/JvmMetrics` registers JVM heap/GC/thread gauges into the `jvm` context
for every daemon.

### org.apache.hadoop.service — lifecycle

**Purpose:** a uniform start/stop lifecycle for every long-lived component so
composition and shutdown are consistent. **Key classes:** `Service` (interface +
`Service.STATE`: `NOTINITED(0)`, `INITED(1)`,
`STARTED(2)`, `STOPPED(3)`), `AbstractService` (holds a `ServiceStateModel`),
`CompositeService` (ordered child list), `ServiceStateModel` (transition validator),
`ServiceOperations` (exception-safe stop/init helpers),
`ServiceStateChangeListener`/`LifecycleEvent`; `launcher/` (`ServiceLauncher` daemon
main, `LaunchableService`, `ServiceShutdownHook`, `InterruptEscalator`, `IrqHandler`,
`HadoopUncaughtExceptionHandler`, `LauncherExitCodes`).

**Main data structures:** a single volatile `state`; a listener list; the child list in
`CompositeService`.

**Behaviour — state machine:** legal transitions are `NOTINITED → INITED → STARTED →
STOPPED` (terminal), plus stop from any state and reuse `STOPPED → NOTINITED`.
`ServiceStateModel.enterState` checks `isValidStateTransition(current, proposed)`,
fires listeners with a `LifecycleEvent`, and throws `ServiceStateException` on illegal
requests; `ensureCurrentState` asserts before mutating. `stop` is idempotent;
`CompositeService.addService` during `STARTED` starts the child immediately;
`ServiceOperations.stopQuietly` swallows stop failures so shutdown cascades complete.

#### State machine and hooks

- `Service`/`AbstractService` hold a `ServiceStateModel` over a single volatile
  state; subclasses implement the three hooks `serviceInit(Configuration)`,
  `serviceStart()`, `serviceStop()`; `init`/`start`/`stop` synchronize on
  `stateChangeLock`, and `stop` is idempotent (§11.7).
- `ServiceStateModel.enterState` validates the transition (`NOTINITED →
  INITED → STARTED → STOPPED`, terminal stop, `STOPPED → NOTINITED` for
  reuse), fires `ServiceStateChangeListener`s with a `LifecycleEvent` and
  throws `ServiceStateException` on illegal requests;
  `LoggingStateChangeListener` logs transitions.

#### Composition and operations

- `CompositeService` keeps an ordered child list: `serviceInit`/`serviceStart`
  walk children in add order, `serviceStop` stops them in reverse order;
  `addService` on a STARTED composite starts the child immediately.
- `ServiceOperations` provides the exception-safe statics (`stop`,
  `stopQuietly`, `deploy`) used by both composite shutdown and the launcher,
  and owns the listener-list plumbing that copies listeners outside the lock
  (§11.7).

#### launcher/ — process entrypoints

`ServiceLauncher` is the `main()` daemons run: it parses arguments
(`LauncherArguments`), instantiates the service (honouring
`LaunchableService`/`AbstractLaunchableService` conventions such as
`bindArgs`/`execute`), drives `init`/`start`, then blocks in
`service.waitForServiceToStop(0)` (or runs `LaunchableService.execute()`) —
not `waitForCompletion`. It installs `ServiceShutdownHook` (registered with
the launcher's `SHUTDOWN_PRIORITY`), `InterruptEscalator` (escalates a second
SIGTERM/SIGINT to immediate exit), `IrqHandler` (signal dispatch) and
`HadoopUncaughtExceptionHandler` (any uncaught throwable terminates the
process with a `LauncherExitCodes` status).

### org.apache.hadoop.net — topology and DNS

**Purpose:** map hostnames/IPs to network racks for locality decisions, plus
socket/DNS utilities. **Key classes:** `NetworkTopology` (interface) + default
`InnerNode`/`InnerNodeImpl`/
`NodeBase` tree (`/dc/rack/host`), `NetworkTopologyWithNodeGroup` (extra level);
`DNSToSwitchMapping` + `AbstractDNSToSwitchMapping`, `CachedDNSToSwitchMapping`,
`TableMapping`, `ScriptBasedMapping(WithDependency)`, `DomainNameResolver(Factory)`,
`DNS`; `NetUtils` (host:port parsing, connect), `SocketIOWithTimeout`,
`SocketInputStream`/`SocketOutputStream`, `MachineList`.

**Main data structures:** the `InnerNode` trie (`children`, `numofleaves`); a
host→rack cache in `CachedDNSToSwitchMapping`.

**Behaviour at runtime:** `resolve(List<String>)` consults the cache; the script
wrapper shells out to `topology.script.file.name`. `NetworkTopology.add(Node)` inserts
by path; `getDistance(n1, n2)` walks to the common ancestor (same node = 0, same rack
= 2, same cluster = 4) — the costs HDFS placement/read selection use;
`chooseRandom(scope, excludedNodes)` picks a random leaf under a scope honouring the
exclude set (placement fallbacks).

#### Topology

- `Node`/`NodeBase` name a node by `/dc/rack/host` path; `InnerNode`/
  `InnerNodeImpl` are the internal tree nodes; `NetworkTopology` is the tree
  with `add`/`remove`, `getDistance` (same node 0, same rack 2, different rack
  same cluster 4) and `chooseRandom(scope, excludedNode)`;
  `NetworkTopologyWithNodeGroup` adds a `/dc/rack/nodegroup/host` level.
- `DNSToSwitchMapping` implementations resolve hostnames to racks:
  `CachedDNSToSwitchMapping` caches the wrapped mapping's results;
  `ScriptBasedMapping`(WithDependency) shells out to
  `topology.script.file.name`; `TableMapping` reads a static table;
  `AbstractDNSToSwitchMapping`/`DNSToSwitchMappingWithDependency` handle
  configuration wiring; `DomainNameResolver`/`DomainNameResolverFactory`/
  `DNSDomainNameResolver` resolve DNS names directly, and `DNS` exposes
  low-level host/address queries.

#### Sockets

`NetUtils` (address parsing, `connect` with timeouts, socket factory
instantiation), `StandardSocketFactory`, `SocksSocketFactory`,
`SocketIOWithTimeout` + `SocketInputStream`/`SocketOutputStream`/
`SocketInputWrapper` (selectable-timeout IO), `ConnectTimeoutException`, and
`MachineList` (the `*.hosts` list semantics).

#### net/unix

`DomainSocket` wraps AF_UNIX sockets (short-circuit reads); its
`DomainSocketWatcher` runs its own thread ("<path> DomainSocketWatcher")
polling connected sockets for closure and cleaning up.

### org.apache.hadoop.util and util.functional

**Purpose:** the toolbox: reflection, processes, disks, caching, sorting, shutdown
hooks, plus a modern functional IO layer.

**Key classes:** `ReflectionUtils`, `ClassUtil`, `FindClass`; `GenericOptionsParser` +
`Tool`/`ToolRunner` (the `-D`/`-conf`/`--files` arg pre-processing every CLI inherits);
`Shell`, `RunJar` (the `hadoop jar` main), `ProgramDriver`, `ExitUtil`, `SignalLogger`,
`ShutdownHookManager` (ordered JVM hooks); disk: `DiskChecker`, `DiskValidator(Factory)`,
`ReadWriteDiskValidator`, `AsyncDiskService`; data: `LightWeightGSet`/
`LightWeightCache`/`LightWeightResizableGSet` (backing NameNode blocks and
`ipc.RetryCache`), `IdentityHashStore`, `DirectBufferPool`, `ChunkedArrayList`,
`bloom/*`, `hash/*`, `QuickSort`/`HeapSort`/`IndexedSorter`, `StringInterner`;
runtime info: `SysInfoLinux`/`SysInfoWindows`, `GcTimeMonitor`, `JvmPauseMonitor`,
`Time`/`StopWatch`, `NativeCodeLoader`; `functional/` — `FunctionalIO`, `FutureIO`,
`TaskPool`, `CloseableTaskPoolSubmitter`, `RemoteIterators`, `LazyAtomicReference`, and
the `*RaisingIOE` interfaces wrapping checked exceptions for lambda-based fs code.

#### CLI, reflection, processes

- `GenericOptionsParser` + `Tool`/`ToolRunner` pre-process `-D`/`-conf`/
  `--files`-style options for every CLI; `ProgramDriver` dispatches
  sub-commands; `FindClass`/`ClassUtil`/`ReflectionUtils` locate and
  instantiate classes.
- `Shell` runs external commands (`Shell.ShellCommandExecutor`, timeout
  handling, Windows `WinUtils` checks); `RunJar` is the `hadoop jar` main
  (unjar, `URLClassLoader`, manifest `Main-Class`); `ExitUtil`/`SignalLogger`/
  `ShutdownHookManager` (ordered, single-executor hooks — §11.7)/
  `ShutdownThreadsHelper` cover process lifecycle; `Daemon`/`Timer` are the
  daemon-thread/timeout bases used across the tree.

#### Disks and space

`DiskChecker` (mkdir-with-permissions + verify), the pluggable
`DiskValidator`/`DiskValidatorFactory` (`BasicDiskValidator`,
`ReadWriteDiskValidator` with `ReadWriteDiskValidatorMetrics`),
`AsyncDiskService` (per-volume executor pools for async deletes/renames), and
`DF`/`DU`/`GetSpaceUsed`/`CachingGetSpaceUsed`/`DUHelper` for space
accounting; `HostsFileReader`/`MachineList` for host lists.

#### Data structures and hashing

`LightWeightGSet`/`LightWeightCache`/`LightWeightResizableGSet`/
`GSetByHashMap` (open-addressed maps behind NameNode block management and
`ipc.RetryCache`), `IdentityHashStore`, `DirectBufferPool`,
`ChunkedArrayList`, `IntrusiveCollection`, `WeakReferenceMap`; `bloom/`
(`BloomFilter`, `CountingBloomFilter`, `DynamicBloomFilter`,
`RetouchedBloomFilter`); `hash/` (`Hash`, `JenkinsHash`, `MurmurHash`);
`QuickSort`/`HeapSort`/`IndexedSorter`; CRC implementations (`PureJavaCrc32`,
`PureJavaCrc32C`, `NativeCrc32`, `CrcUtil`, `CrcComposer`), `DataChecksum`,
`LineReader`, `StringInterner`.

#### JVM/runtime and sub-packages

- Runtime: `GcTimeMonitor`, `JvmPauseMonitor`, `SysInfoLinux`/`SysInfoWindows`,
  `Time`/`StopWatch`, `NativeCodeLoader`/`NativeLibraryChecker`,
  `VersionInfo`, the `InstrumentedLock` family (locks that log slow
  acquisition), `SemaphoredDelegatingExecutor`, `AutoCloseableLock`.
- `concurrent/`: `HadoopExecutors`, `HadoopThreadPoolExecutor`,
  `HadoopScheduledThreadPoolExecutor`, `BlockingThreadPoolExecutorService`,
  `ExecutorHelper`, `AsyncGet`/`AsyncGetFuture`.
- `dynamic/`: `DynConstructors`/`DynMethods`/`BindingUtils` (reflection with
  better error reporting). `curator/`: `ZKCuratorManager`, the ZooKeeper
  client wrapper shared with hadoop-registry and the ZK token managers.
- `functional/`: `TaskPool`/`CloseableTaskPoolSubmitter`, `FutureIO`/
  `FunctionalIO`, `RemoteIterators`, `LazyAtomicReference`, and the
  `*RaisingIOE` functional interfaces wrapping checked exceptions.

### Shell/daemon launcher

`hadoop-common/src/main/bin/hadoop` (bash) sources `hadoop-config.sh` +
`hadoop-functions.sh` to assemble CLASSPATH/native path/JVM options; for
`hadoop jar` it sets `HADOOP_CLASSNAME=org.apache.hadoop.util.RunJar`, for daemons
(via `hadoop-daemon.sh`) it launches `org.apache.hadoop.service.launcher.ServiceLauncher`.
`RunJar` unjars to a temp dir, builds a `URLClassLoader` over the jar + `lib/`, and
invokes the manifest `Main-Class`. `ServiceLauncher` parses `LauncherArguments`,
creates the service, drives the `service` lifecycle, installs `ServiceShutdownHook`,
`InterruptEscalator` (SIGTERM escalation to exit), `IrqHandler` and
`HadoopUncaughtExceptionHandler`, mapping failures to `LauncherExitCodes`.

#### bin/ scripts

`bin/hadoop` sources `hadoop-common/src/main/bin/hadoop-config.sh` and
`hadoop-functions.sh` (env expansion, `HADOOP_OPTS` assembly, native library
path, classpath construction, daemon PID/log/secure-dir management) and then
either runs a class (`hadoop jar` sets `HADOOP_CLASSNAME=RunJar`) or execs the
daemon JVM.

#### ServiceLauncher

`ServiceLauncher` owns the main thread: launch → `init`/`start` → block until
stop (§11.9) → `System.exit` with a `LauncherExitCodes` status.

## 6. Module: hadoop-kms

**Purpose:** a standalone web service fronting the `KeyProvider` API so multiple
clients (HDFS encryption zones, Ozone) share keys backed by JavaKeyStoreProvider or
another backend. **Key classes** (`org.apache.hadoop.crypto.key.kms.server`):
`KMSWebApp` (context initializer), `KMS` (JAX-RS resource), `KMSWebServer`,
`KeyAuthorizationKeyProvider` (per-operation ACL checks), `KMSACLs` (key-ACL parsing +
user/group evaluation), `KMSAudit`/`KMSAuditLogger`/`SimpleKMSAuditLogger`,
`KMSAuthenticationFilter` (delegates to `hadoop-auth`), `KMSMDCFilter`,
`KMSExceptionsProvider`, `EagerKeyGeneratorKeyProviderCryptoExtension` (pre-generates
keys), `KMSConfiguration`.

**Behaviour at runtime:** REST request → `KMSAuthenticationFilter` (SPNEGO/cookie via
hadoop-auth) → `KMSMDCFilter` binds user/request to logs → `KMS` dispatches to
`KeyAuthorizationKeyProvider`, which checks `KMSACLs` for the operation type
(GET/MANAGE/GENERATE…), performs the operation on the provider, and writes a
`KMSAudit` record. Clients use `KMSClientProvider` from `hadoop-common`'s
`crypto/key/kms/client`.

#### Package contents (org.apache.hadoop.crypto.key.kms.server)

- Boot: `KMSWebApp` (a `ServletContextListener` building the shared
  `Configuration`, `KeyProvider`, `KMSACLs`, `KMSAudit`) and `KMSWebServer`
  (the HTTP listener on `hadoop.kms.http.port`, TLS via `SSLFactory`).
- Request path: `KMSAuthenticationFilter` (hadoop-auth) → `KMSMDCFilter`
  (user + request id into SLF4J MDC) → `KMS` (the single JAX-RS resource) →
  `KeyAuthorizationKeyProvider` (per-operation `KMSACLs` checks, §12.8) →
  underlying `KeyProvider`; failures translate through
  `KMSExceptionsProvider`; JSON plumbing via `KMSJSONReader`/`KMSJSONWriter`/
  `KMSServerJSONUtils`.
- Audit: `KMSAudit` (asynchronous single-thread scheduler with an aggregation
  window) writing through the pluggable `KMSAuditLogger` (default
  `SimpleKMSAuditLogger`).
- Key generation: `EagerKeyGeneratorKeyProviderCryptoExtension` pre-generates
  encrypted-key material through a `ValueQueue`; `KMSConfiguration` locates
  `kms-site.xml`.

## 7. Module: hadoop-minikdc

**Purpose:** an embedded MIT Kerberos KDC for tests — a real KDC inside the JVM so
Kerberized integration tests need no external KDC. `MiniKdc` starts an embedded KDC
(Apache Directory Server backend), creates principals and generates keytabs;
`KerberosSecurityTestcase` is the JUnit base that starts/stops MiniKdc per test. Tests
call `new MiniKdc(conf, workdir).start()`, then
`createPrincipal(keytab, "user", "nn/localhost")...`; keytabs feed
`UserGroupInformation.loginUserFromKeytab`. Test-only; no production code depends on it.

#### Contents

`MiniKdc` starts an embedded ApacheDS-backed KDC inside the test JVM (working
directory created under the supplied work dir, deleted on `stop`), allocates a
port, and `createPrincipal` writes real keytabs for generated principals;
`KerberosSecurityTestcase` is the JUnit base that starts/stops a `MiniKdc` per
test. The KDC runs its own network threads in-process; no production code
depends on the module.

## 8. Module: hadoop-nfs

**Purpose:** building blocks for NFS serving — the ONC-RPC/XDR runtime, MOUNT
protocol and NFSv3 — on which HDFS's `hadoop-hdfs-nfs` gateway is built. **Key
classes:** `mount/` — `MountdBase` (UDP/TCP MOUNT listener), `MountInterface`,
`MountEntry`, `MountResponse`; `nfs/` — `NfsExports` (export ACL parsing:
host/`AccessPrivilege` rules), `NfsTime`, `NfsFileType`; `nfs3/` — `Nfs3Base` (the
NFSv3 service), `Nfs3Interface`, `Nfs3Constant`, `FileHandle`, `Nfs3FileAttributes`,
and generated `request/`+`response/` messages.

**Behaviour at runtime:** a client mounts an export — `MountdBase` validates the host
against `NfsExports` and returns a `FileHandle`; subsequent NFSv3 calls arrive on
`Nfs3Base`'s port, are XDR-decoded into `request.*` objects, dispatched through
`Nfs3Interface` to the backend filesystem, and the `response.*` is encoded back.
Stateless by design; the filesystem-specific implementation lives in
`hadoop-hdfs-nfs`.

#### Package layout and the oncrpc dependency

Three packages: `mount/`, `nfs/`, `nfs3/` (with `request/` + `response/`
message trees under `nfs3`). The ONC-RPC runtime they build on — `XDR`,
`RpcCall`, `RpcProgram`, `SimpleTcpServer`/`SimpleUdpServer`, `RpcCallCache` —
lives in `hadoop-common`'s `oncrpc`/`portmap` packages (§5); hadoop-nfs is a
library over it, not its home.

#### mount/ and nfs/

`MountdBase` starts the TCP and UDP listeners (`SimpleTcpServer`/
`SimpleUdpServer`) over its `RpcProgram`, registers with the portmapper
(`PortmapMapping`), validates mount requests against `NfsExports` (host/
`AccessPrivilege` rules) and answers through `MountInterface`/
`MountResponse` with `MountEntry` results. `nfs/` holds the shared NFS data
model (`NfsTime`, `NfsFileType`, `AccessPrivilege`).

#### nfs3/

`Nfs3Base` starts the NFSv3 program on its port: `XDR` is decoded into
`nfs3/request/*` objects, dispatched through `Nfs3Interface` to the backend,
and `nfs3/response/*` encoded back. `FileHandle`, `Nfs3FileAttributes`,
`Nfs3Constant`, `Nfs3Status` are the protocol data types. The service
registers a `ShutdownHookManager` hook to stop the listeners and calls
`ExitUtil.terminate` on startup failure. All NFS state is per-request — the
gateway stays stateless; the filesystem implementation lives in
`hadoop-hdfs-nfs`.

## 9. Module: hadoop-registry

**Purpose:** a service registry for YARN services: `ServiceRecord`s persisted in a
ZooKeeper tree (via Apache Curator), with client ops, a DNS-publishing server, and a CLI.
**Key classes:** `client/api/` — `RegistryOperations` (mknode/bind/list/resolve),
`RegistryOperationsFactory`, `client/types/ServiceRecord` (with `Endpoint`s and
`ProtocolTypes`), `RegistryPathStatus`; `client/impl/` — `FSRegistryOperationsService`/
`RegistryOperationsClient` and the `client/impl/zk/` stack:
`RegistryOperationsService` (extends `hadoop-common`'s `CompositeService`),
`CuratorService` (Curator wrapper + retries), `RegistrySecurity` (ZK SASL/ACL
management), `JsonSerDeser`; plus `server/` and `cli/` (`RegistryCli`).

**Main data structures:** the ZK path tree (`/registry/users/<user>/<service>/…`);
`ServiceRecord` as JSON with `Endpoint` lists; ZK ACLs from SASL identities.
**Behaviour at runtime:** a service calls `registryOperations.mknode` +
`bind(path, serviceRecord)`, writing its JSON record under its user's subtree;
consumers `resolve(path)`/`list(path)` through `CuratorService`'s retrying client.
`RegistrySecurity` sets ZK SASL ACLs so only the owning principal writes its subtree;
the server-side DNS component publishes A/SRV records from those records.

#### client/ — API, types and the ZK implementation

- `api/`: `RegistryOperations` (mknode/bind/list/resolve/delete),
  `RegistryOperationsFactory`, `RegistryPathStatus`; `types/`:
  `ServiceRecord` (+ `Endpoint`/`ProtocolTypes`).
- `binding/`: `RegistryUtils` (path conventions `/registry/users/<user>/...`),
  `RegistryTypeUtils`, `RegistryPathUtils`, `JsonSerDeser` (JSON
  (de)serialization of records).
- `impl/`: `RegistryOperationsClient`/`FSRegistryOperationsService` front the
  real implementation in `impl/zk/`: `RegistryOperationsService` (a
  `CompositeService`), `CuratorService` (Curator client wrapper with retry
  policy and a `PathListener` for watch callbacks), `RegistrySecurity` (ZK
  SASL/ACL management), `BindingInformation`, `ZKPathDumper`.

#### server/ and cli/

`server/services/`: `MicroZookeeperService` (an in-process
`ZooKeeperServer`, configured via `MicroZookeeperServiceKeys`),
`RegistryAdminService`, `AddingCompositeService`. `server/dns/`:
`RegistryDNS` + `RegistryDNSServer` publish A/SRV records derived from
`ServiceRecord`s via the `ServiceRecordProcessor` family
(`ApplicationServiceRecordProcessor`, `ContainerServiceRecordProcessor`,
`RecordCreatorFactory`, `LookupTask`); `server/integration/` holds
`SelectByYarnPersistence`. `cli/`: `RegistryCli`, the `hadoop registry`
command line.

## 10. Inter-module dependencies

```
hadoop-annotations  ←  everything
hadoop-auth         ←  hadoop-kms, hadoop-auth-examples, hadoop-common (AuthenticationFilterInitializer)
hadoop-common       ←  hadoop-kms, hadoop-minikdc (test scope), hadoop-nfs, hadoop-registry
hadoop-nfs          →  hadoop-common (oncrpc, net)
hadoop-registry     →  hadoop-common (service, conf, security, util)
hadoop-kms          →  hadoop-common (crypto.key, fs, security) + hadoop-auth
```

Inside `hadoop-common`, the internal pull-weight is roughly: `conf` ← everything;
`util` ← everything; `io` ← `ipc`, `fs`, `security`; `security` ← `ipc` (SASL), `fs`
(UGI-keyed cache, token renewer); `metrics2` ← `ipc` (`DecayRpcScheduler` MXBeans),
`fs` (storage statistics); `net` ← `ipc` (`NetUtils`), `fs`, and HDFS placement.

## Behaviour summary

- **hadoop-annotations** — marker annotations only; the API-stability vocabulary.
- **hadoop-auth** — signed-cookie servlet authentication: filter + pluggable handlers
  (SPNEGO/pseudo/JWT/LDAP), HMAC `Signer` with file/ZK secret providers.
- **hadoop-auth-examples** — runnable reference wiring of the above.
- **hadoop-common/conf** — layered, lazily-reloaded `Properties` from a resource list;
  last-resource-wins; hot-reconfig via `ReconfigurableBase`.
- **hadoop-common/fs** — `FileSystem.get` returns a per-(URI,user) cached instance via
  `CACHE`; checksummed local IO verifies CRCs per chunk against a `.checksum` sidecar;
  `FileContext` is the non-cached scheme-explicit alternative; `FsShell` is the CLI.
- **hadoop-common/ipc** — dynamic proxy `Invoker` → `Client.Call` on a multiplexed
  SASL connection → server `CallQueueManager` (optionally `FairCallQueue` +
  `DecayRpcScheduler`) → `Handler` pool → `Responder`; `RetryCache` dedups retries.
- **hadoop-common/security** — UGI wraps JAAS `Subject.doAs`; keytab re-login via
  `checkTGTAndReloginFromKeytab` near TGT expiry; pluggable cached group mapping;
  SASL/token plumbing for IPC.
- **hadoop-common/io** — compact binary `Writable.write/readFields`; `Text` = UTF-8
  bytes + length (validated, zero-copy compares); `WritableComparator` caches
  deserialization-free comparators; `SequenceFile` = checksummed, sync-markered blocks.
- **hadoop-common/metrics2** — timer-sampled `MetricsSource`s produce records into
  per-sink bounded `SinkQueue`s drained by sink threads; `@Metric` fields become live
  gauges/counters.
- **hadoop-common/service** — strict `NOTINITED → INITED → STARTED → STOPPED` state
  machine validated by `ServiceStateModel`; `CompositeService` inits children forward,
  stops them in reverse; `ServiceLauncher` is the daemon entrypoint.
- **hadoop-common/net** — `InnerNode` rack tree with `getDistance` costs (0/2/4) and
  `chooseRandom(scope, excluded)`; hostname→rack via cached pluggable
  `DNSToSwitchMapping` (script- or table-based).
- **hadoop-common/util(+functional)** — `ToolRunner` arg handling, `LightWeightGSet`
  open-addressed sets, `ShutdownHookManager`, disk validators, `RunJar`, and the
  `*RaisingIOE`/`TaskPool` functional IO helpers.
- **shell/daemon launcher** — `bin/hadoop` → `ServiceLauncher` (lifecycle + signal
  escalation) or `RunJar` (jar classloader + manifest main).
- **hadoop-kms** — authenticated (hadoop-auth), ACL-checked, audited REST key service
  over a `KeyProvider`.
- **hadoop-minikdc** — in-process MIT KDC issuing real keytabs for tests.
- **hadoop-nfs** — XDR/ONC-RPC NFSv3 + MOUNT servers as an embeddable library; export
  ACLs via `NfsExports`.
- **hadoop-registry** — ZooKeeper/Curator service registry of JSON `ServiceRecord`s
  with SASL ACLs and optional DNS publishing.

## 11. Concurrency

Per-subcomponent statements grounded in the source; each is directly checkable
against the named class.

### 11.1 conf — `Configuration`

- All mutating and materializing methods of `Configuration` (`set`, `unset`,
  `setIfUnset`, `getProps`, `addResourceObject`, `reloadConfiguration`) are
  `synchronized` on the instance, so a reader either sees the old or the fully
  re-walked resource set — never a partial load. `getProps()` (`Configuration.java`,
  `protected synchronized Properties getProps()`) lazily materializes when
  `properties == null`; `reloadConfiguration()` only sets `properties = null` and
  clears `finalParameters`, deferring the re-walk to the next get.
- Static registration is `static synchronized` on `Configuration.class`:
  `addDefaultResource` and `Configuration.reloadExistingConfigurations` force every
  live configuration to re-run `reloadConfiguration`.
- The reflection class cache (`CACHE_CLASSES`) is a synchronized map;
  `getClassByName` synchronizes on `Configuration.class`.
- `ReconfigurableBase` re-evaluates its changeable-property white-list and calls
  `reconfigurePropertyImpl` on the owning service; the subclass decides whether the
  new value is applied in place or requires restart.

### 11.2 fs — `FileSystem` cache and statistics

- `FileSystem.CACHE` (static `Cache`, `FileSystem.java` line ~205) holds
  `Map<Key, FileSystem> map = new HashMap<>()` plus `Set<Key> toAutoClose`; every
  lookup, insert, removal (`remove`), and bulk close (`closeAll`, `closeAll(ugi)`)
  is `synchronized(this)` on the `Cache` object. The map is plain `HashMap`, so all
  accesses must go through these synchronized methods.
- `Cache.getInternal` checks the map under a short lock, then creates the
  `FileSystem` **outside** the lock but inside a `Semaphore creatorPermits` sized by
  `fs.creation.parallel.count` (`FS_CREATION_PARALLEL_COUNT`, default 64). A second
  cache check after acquiring the permit, and again after creation under the lock,
  handles racing creators: the loser closes its duplicate outside all locks
  (`fsToClose`) and increments the `AtomicLong discardedInstances` counter. A PR that
  removes either the post-wait re-check or the outside-lock close will re-introduce
  a leak/deadlock; this is an invariant to check in review.
- The `ClientFinalizer` shutdown hook is registered with `ShutdownHookManager` only
  when the map transitions empty → non-empty and shutdown is not already in
  progress; it runs `closeAll()` with a per-hook timeout
  (`SERVICE_SHUTDOWN_TIMEOUT`), and only when `fs.automatic.close` is true
  (default).
- `closeAll(UserGroupInformation ugi)` closes all cached instances belonging to one
  user — invoked by `ClientFinalizer` at UGI logout, giving per-user teardown.
- Per-scheme `Statistics` instances are guarded by synchronized methods
  (`getStatistics`, `getAllStatistics`, `clearStatistics` are `static synchronized`;
  each increment synchronizes on the `Statistics` instance) and keep per-thread
  accumulators.
- `deleteOnExit` bookkeeping is `synchronized` on the shared set.
- Consequence to state in requirements: `FileSystem.get` is thread-safe, but the
  returned instance is **shared by all threads of the same (URI, user)** — every
  `FileSystem` implementation must be safe for concurrent method calls.

### 11.3 ipc — `Client`, `Server`, call queue

- Client side (`Client.java`): one `Connection extends Thread` per
  `ConnectionId`; its call table is `Hashtable<Integer, Call> calls` (line 435 —
  safe for concurrent `put` from many caller threads while the connection thread
  iterates); close coordination via `AtomicBoolean shouldCloseConnection`
  (`compareAndSet` in `markClosed`) and `AtomicBoolean running`. `Call` completion
  (`Call.complete`) notifies the parked caller.
- Asynchronous calls are bounded per `Client` by `ipc.client.asyncCalls.max`
  (`IPC_CLIENT_ASYNC_CALLS_MAX`, default 100) via `AtomicInteger asyncCallCounter`;
  exceeding it throws `AsyncCallLimitExceededException`.
- `ClientCache` holds `Map<SocketFactory, Client>` in a synchronized HashMap: one
  `Client` per socket factory per JVM.
- Server side (`Server.java`): threads are —
  `Listener` ("IPC Server listener on <port>", single accept thread);
  `Reader` × `ipc.server.read.threadpool.size` (`IPC_SERVER_RPC_READ_THREADS`,
  default 1) each with a bounded pending-connection queue
  `ipc.server.rpc.read.connection-queue.size` (default 100); `Handler[]`
  ("IPC Server handler N on <port>", count supplied by the owning daemon, e.g.
  NameNode `ipc.<service>.handler.count`) that `take()` from the call queue;
  a single `Responder` ("IPC Server Responder") that flushes responses.
- `ConnectionManager` keeps connections in a `ConcurrentHashMap`-backed set with
  concurrency level `readThreads+2`, a per-user `ConcurrentHashMap`
  (`userToConnectionsMap`), and a daemon `Timer` "IPC Server idle connection
  scanner" that closes connections idle longer than
  `ipc.client.connection.maxidletime` × 2, at most `ipc.client.kill.max` per scan,
  after `ipc.client.idlethreshold` (default 4000) connections are open;
  `ipc.server.max.connections` (default 0) caps total connections.
- The call queue is the single `CallQueueManager<Call>` with capacity
  `handlerCount × ipc.server.handler.queue.size` (default 100 per handler); `put`
  blocks (with optional client backoff) when full. The queue implementation
  (`LinkedBlockingQueue` default, or `FairCallQueue` + `DecayRpcScheduler`) can be
  swapped at runtime via `RefreshCallQueueProtocol` → `CallQueueManager.swapQueue`.
- `RetryCache` (`ipc/RetryCache.java`) stores `CacheEntry` in a `LightWeightGSet`;
  entry state transitions (`completed`) are `synchronized` on the entry, so the
  retry-vs-first-execution race is resolved per entry.

- `Responder` is a single thread with its own NIO `Selector` (`Server.java`):
  when a response cannot be flushed to a client immediately, the handler
  defers the write to the responder instead of blocking; each `Reader` thread
  similarly owns a private `readSelector` over its registered connections.
  `Client`'s async-call accounting lives in the `AtomicInteger
  asyncCallCounter`, enforced in `checkAsyncCall`.

### 11.4 security — UGI, groups, SASL

- `UserGroupInformation` static initialization and login caching synchronize on
  `UserGroupInformation.class` (`initialize`, `getLoginUser`, and
  `Groups.getUserToGroupsMappingService` are `static synchronized`).
- Login/re-login serialization: `HadoopLoginContext.getSubjectLock()` returns the
  subject's `privateCredentials` set (or the context itself before the subject
  exists); `login()`, `logout()`, and `relogin()` all synchronize on that lock so a
  re-login is atomic against concurrent RPC handlers, SASL and SPNEGO code
  (`UserGroupInformation.relogin`, with the comment "ensure the relogin is atomic").
  Re-login is additionally rate-limited to one per
  `hadoop.kerberos.min.seconds.before.relogin` (`HADOOP_KERBEROS_MIN_SECONDS_BEFORE_RELOGIN`,
  default 60 s) via the volatile `User.lastLogin`.
- Auto-renewal: `spawnAutoRenewalThreadForKeytab()` /
  `spawnAutoRenewalThreadForUserCreds()` submit a
  `TicketCacheRenewalRunnable`/`KeytabRenewalRunnable` to a single-thread **daemon**
  executor named "TGT Renewer for <user>" (`executeAutoRenewalTask`); ticket-cache
  renewal shells out to `kinit` (`hadoop.kerberos.kinit.command`, default `kinit`).
- Token state: `addToken`/`addTokenIdentifier` and the credentials accessors are
  `synchronized` on the UGI instance or `synchronized(subject)`; `User`'s
  `authMethod`/`login`/`lastLogin` are volatile.
- Groups: values live in a Guava `LoadingCache` with
  `expireAfterWrite(10 × hadoop.security.groups.cache.secs)` (cache timeout default
  300 s → hard cap 3000 s per entry), an optional negative cache
  (`hadoop.security.groups.negative-cache.secs`, default 30 s), and an optional
  background refresh pool (`hadoop.security.groups.cache.background.reload`, default
  false; `hadoop.security.groups.cache.background.reload.threads`, default 3). With
  background refresh off, a slow group-mapping backend blocks the calling RPC
  handler thread.

### 11.5 io

- `CodecPool` leases compressors/decompressors/checksums from synchronized free
  lists; a codec must be returned to the pool exactly once (`CodecPool.returnCodec`).
- `Text`, `DataOutputBuffer` and Writable objects are mutable single-threaded
  objects; sharing a Writable between threads requires external synchronization.
- `LightWeightGSet`/`LightWeightCache` are **not** thread-safe by themselves; users
  (`ipc.RetryCache`, NameNode block management) must provide their own locking.

### 11.6 metrics2

- Sampling runs on a single `java.util.Timer` ("Timer for '<prefix>' metrics
  system", daemon) started by `MetricsSystemImpl.startTimer`; the period is the GCD
  of all configured `*.period` values (`periodMillis` variants supported for tests).
  Source `getMetrics(collector, all)` calls therefore happen on the timer thread and
  sources must not block.
- Each sink gets one dedicated daemon thread (`MetricsSinkAdapter.sinkThread`,
  named after the sink) draining a bounded, synchronized `SinkQueue<MetricsBuffer>`;
  when the queue is full, `enqueue` fails and the record is **dropped** — a slow
  sink never blocks the sampler.
- `MetricsSystemImpl.stop` cancels the timer, interrupts and joins the sink
  threads, and snapshots may be flushed synchronously (`inMockMode` / test paths).

### 11.7 service — lifecycle and shutdown ordering

- `AbstractService.init/start/stop` synchronize on `stateChangeLock`; the state
  itself lives in `ServiceStateModel` (`volatile STATE state`,
  `synchronized enterState`) which validates transitions and fires listeners, so
  listeners run while holding the state-model lock — listeners must be short and
  must not call back into the service.
- `ServiceOperations.ServiceListeners` copies the listener list outside the
  synchronized block before iterating, so a listener may add/remove listeners or
  start/stop services without deadlock.
- `CompositeService` initializes children in add order and stops them in **reverse
  order** (`CompositeService.stop`, "stop in reverse order of start");
  `addService` while the composite is STARTED starts the child immediately.
  `ServiceOperations.stopQuietly` swallows stop failures so a shutdown cascade
  completes.
- JVM shutdown: `ShutdownHookManager` registers exactly one JVM hook; hooks are
  submitted to a single-thread executor ("shutdown-hook-%01d") and executed in
  priority order, each with its own timeout (`SERVICE_SHUTDOWN_TIMEOUT` for the
  FileSystem finalizer), timed-out hooks cancelled. Shutdown ordering is therefore
  deterministic: hooks run sequentially, highest priority first.
- `ServiceLauncher` (launcher package) drives the lifecycle on the main thread and
  installs `InterruptEscalator` (SIGTERM escalation), `IrqHandler`, and
  `HadoopUncaughtExceptionHandler`.

### 11.8 kms

- `KMSAudit` uses a single-thread `ScheduledExecutorService` of daemon threads
  named "kms-audit_thread" (`KMSAudit.java`) and aggregates identical cache-related
  events over `hadoop.kms.audit.aggregation.window.ms` (default 10000 ms); audit
  emission is asynchronous with respect to request handling.
- `KMSACLs` keeps its ACL maps `volatile` and re-parses `kms-site.xml` from a
  single-thread `ScheduledExecutorService` every `RELOADER_SLEEP_MILLIS` = 1000 ms;
  ACL changes take effect within ~1 s without restart.
- `ValueQueue` (used by `EagerKeyGeneratorKeyProviderCryptoExtension` for
  pre-generated encrypted keys) runs a fixed-size `ThreadPoolExecutor`
  (`numFillerThreads`, threads named `org.apache.hadoop.crypto.key.kms.ValueQueue_thread`)
  for background refill; the synchronous path fills at least one value on the
  caller thread per the `SyncGenerationPolicy`.
- `KMSMDCFilter` binds the authenticated user and request id into the SLF4J MDC for
  the duration of the request thread; log correlation is thread-local.
- `KMSClientProvider` (client side) shares a `DelegationTokenAuthenticatedURL.Token`
  and an `SSLFactory` across calls; `LoadBalancingKMSClientProvider` fans out over
  multiple KMS URLs.

### 11.9 launcher and bin

- `ServiceLauncher` runs the service start on the main thread and blocks in
  `service.waitForServiceToStop(0)`; `HadoopUncaughtExceptionHandler` and `InterruptEscalator`
  guarantee process exit (`LauncherExitCodes`) even when the lifecycle fails
  mid-stop.
- `RunJar` builds a `URLClassLoader` per `hadoop jar` invocation; classloader state
  is JVM-global (first `hadoop jar` wins the process).

## 12. Security

### 12.1 RPC authentication — Kerberos / SASL

- `hadoop.security.authentication` (`HADOOP_SECURITY_AUTHENTICATION`, default
  `simple`) selects between unauthenticated and Kerberos RPC; with `kerberos`,
  servers require a keytab login (`UserGroupInformation.loginUserFromKeytab`) and
  clients use SASL GSSAPI — `SaslRpcServer.AuthMethod.KERBEROS` is SASL mechanism
  "GSSAPI" with code 81 (`SaslRpcServer.java`).
- Wire protection: `hadoop.rpc.protection` (`HADOOP_RPC_PROTECTION`, default
  `authentication`) — values `authentication`/`integrity`/`privacy` — is resolved
  by `SaslPropertiesResolver` (replaceable via
  `hadoop.security.sasl.props.resolver.class` / `HADOOP_SECURITY_SASL_PROPS_RESOLVER_CLASS`,
  e.g. `WhitelistBasedResolver`). `SaslRpcClient` wraps the stream only when the
  negotiated QOP is above `auth` (`SaslRpcClient.java`, `qop != null && !"auth".equals(qop)`).
- Delegation-token RPC authentication uses SASL DIGEST with the token identifier as
  username; the server verifies against the configured
  `SecretManager<TokenIdentifier>` (`Server.getAuthMethods` / `buildNegotiateResponse`
  advertise the enabled auth methods to the client).
- Principal construction is centralized in `SecurityUtil.getServerPrincipal`
  (`_HOST` substitution, optionally influenced by `hadoop.security.dns.interface` /
  `hadoop.security.dns.nameserver`); a PR touching principal parsing must go through
  `SecurityUtil`, not ad-hoc string edits.

### 12.2 HTTP authentication — hadoop-auth

- `AuthenticationFilterInitializer` wires `AuthenticationFilter` into every
  `HttpServer2` using properties prefixed `hadoop.http.authentication.` — the
  filter config key is `config.prefix` and per-property keys are `type`
  (`PseudoAuthenticationHandler.TYPE` = "simple", `KerberosAuthenticationHandler.TYPE` =
  "kerberos", or a custom handler class), `token.validity` (default 36000 s),
  `cookie.domain`, and `signer.secret.provider` (`file` default, `random`, `zk`).
- `PseudoAuthenticationHandler` trusts `?user.name=` — it must never be the
  configured `type` on a production cluster (the code documents this; a
  requirement-checker can grep the deployed config).
- Signed-cookie integrity comes from `util/Signer` + `SignerSecretProvider`;
  `ZKSignerSecretProvider` shares and rolls the secret cluster-wide via ZooKeeper.
- Delegation-token HTTP auth lives in
  `security/token/delegation/web/` (`DelegationTokenAuthenticationHandler`,
  `DelegationTokenAuthenticatedURL` used by `KMSClientProvider` and WebHDFS).

### 12.3 TLS

- `security/ssl/SSLFactory.java` — `Mode.CLIENT`/`Mode.SERVER`; config file
  selected by `hadoop.ssl.client.conf` / `hadoop.ssl.server.conf` (defaults
  `ssl-client.xml` / `ssl-server.xml`); keystore/truststore settings inside those
  files (`ssl.server.keystore.location`, `ssl.server.truststore.location`, ...),
  plus global keys `hadoop.ssl.require.client.cert`,
  `hadoop.ssl.hostname.verifier`, `hadoop.ssl.enabled.protocols`,
  `hadoop.ssl.keystores.factory.class` (default `FileBasedKeyStoresFactory`).
- `ReloadingX509TrustManager` (with `FileMonitoringTimerTask`) hot-reloads the
  truststore file, so trust changes apply without restart; hostname verification
  goes through `SSLHostnameVerifier` implementations.
- Consumers in this tree: `KMSWebServer` (server mode) and `KMSClientProvider`
  (client mode); the same factory is reused by HDFS/YARN HTTP layers.

### 12.4 Tokens

- Generic token machinery in `security/token/`: `Token`, `TokenIdentifier`,
  `TokenSelector`, `TokenRenewer`, `SecretManager`; delegation framework in
  `security/token/delegation/` (`AbstractDelegationTokenIdentifier`,
  `AbstractDelegationTokenSecretManager`, `DelegationKey`, plus
  `ZKDelegationTokenSecretManager`/`SQLDelegationTokenSecretManager` backends).
  Token kinds are `Text` constants — HDFS DTs, MR DTs, and the KMS kind
  `kms-dt` (`crypto/key/kms/KMSDelegationToken.java`,
  `KMSDelegationTokenIdentifier extends AbstractDelegationTokenIdentifier`).
- Fetch/renew/cancel tooling: `DelegationTokenIssuer`, `DtFetcher`, `DtUtilShell`,
  `DtFileOperations` (`hadoop fetchdt`); `fs/DelegationTokenRenewer.java` is a
  daemon `Thread` that auto-renews fs tokens held by the UGI.
- KMS clients obtain/renew the `kms-dt` token over HTTP with
  `DelegationTokenAuthenticatedURL` (renewer and `doAsUser` passed explicitly —
  `KMSClientProvider.java` renew/cancel methods).

### 12.5 Service-level authorization (RPC)

- Enabled by `hadoop.security.authorization` (`HADOOP_SECURITY_AUTHORIZATION`,
  default false; read in `Server`'s constructor as `this.authorize`); enforced in
  `security/authorize/ServiceAuthorizationManager.authorize(UserGroupInformation,
  Class<?> protocol, Configuration, InetAddress)`, called by `Server` before
  dispatch.
- Semantics (all in `authorize`): an unlisted protocol is always denied
  ("Protocol ... is not known"); in Kerberos mode the client's principal must equal
  the expected client principal derived from the protocol config
  (`SecurityUtil.getClientPrincipal`); the allow ACL `acls[0].isUserAllowed(user)`
  must pass and the blocked ACL `acls[1]` must not match; the client IP must be
  included by `hosts[0]` (`MachineList`) and not by `hosts[1]`. Every failure and
  success is written to the audit logger (see §13).
- Policy source: `hadoop-policy.xml` (override with system property
  `hadoop.policy.file`); per-protocol keys come from each `PolicyProvider`'s
  `Service` definitions; fallbacks are `security.service.authorization.default.acl`
  and `security.service.authorization.default.acl.blocked` plus `<key>.hosts`
  / `<key>.blocked` machine lists.
- `refresh()` re-parses the policy file and atomically swaps the
  `volatile IdentityHashMap` fields `protocolToAcls`/`protocolToMachineLists`
  (no locks needed — readers see either the old or the new map).
- `AccessControlList.isUserAllowed(ugi)` (`security/authorize/AccessControlList.java`)
  resolves groups through `Groups` (`groupsMapping` field), so ACL evaluation
  inherits the group-mapping cache behaviour of §11.4.

### 12.6 Impersonation (doAs / proxy users)

- `UserGroupInformation.createProxyUser(effectiveUser, realUser)` adds a `User`
  principal with `AuthenticationMethod.PROXY`; the JVM can also start as a proxy
  via the `HADOOP_PROXY_USER` environment variable or system property
  (`UserGroupInformation.java`, line ~735).
- Server-side enforcement is `ProxyUsers.authorize(ugi, remoteAddress)`
  (`security/authorize/ProxyUsers.java`), delegating to the
  `ImpersonationProvider` configured by
  `hadoop.security.impersonation.provider.class`
  (`HADOOP_SECURITY_IMPERSONATION_PROVIDER_CLASS`, default
  `DefaultImpersonationProvider`). Rules are
  `hadoop.proxyuser.<superuser>.users`, `hadoop.proxyuser.<superuser>.groups`, and
  `hadoop.proxyuser.<superuser>.hosts` (a `MachineList` — note it matches **IP
  addresses**, hostnames only via the resolver) evaluated in
  `DefaultImpersonationProvider.authorize`. Rules reload via
  `refreshSuperUserGroupsConfiguration`; the provider instance is a `volatile`
  field swapped on refresh. The check is **not** implicit — each RPC/HTTP endpoint
  must call it (HDFS NameNode, YARN RM, KMS's `ProxyUserAuthenticationFilter` do).
- `ProxyServers.refresh(conf)` records trusted proxy hosts
  (`hadoop.proxyserver.<host>`-style entries) so downstream servers know when a
  request was forwarded by a trusted proxy.
- HTTP proxy-user validation is wired by
  `ProxyUserAuthenticationFilterInitializer`
  (`security/authentication/server/`).

### 12.7 Group mapping

- `hadoop.security.group.mapping` (`CommonConfigurationKeysPublic`, default
  `org.apache.hadoop.security.JniBasedUnixGroupsMappingWithFallback`, which falls
  back to `ShellBasedUnixGroupsMapping` when JNI is unavailable); alternatives
  `LdapGroupsMapping`, `RuleBasedLdapGroupsMapping`, `CompositeGroupsMapping`,
  netgroups via `JniBasedUnixGroupsNetgroupMapping` + `NetgroupCache`.
- Shell mapping honours `hadoop.security.groups.shell.command.timeout` (default 0 =
  wait forever) — an unbounded external dependency on the RPC handler path unless
  set.

### 12.8 KMS authorization

- Operation ACLs: `KMSACLs.Type` = CREATE, DELETE, ROLLOVER, GET, GET_KEYS,
  GET_METADATA, SET_KEY_MATERIAL, GENERATE_EEK, DECRYPT_EEK
  (`KMSACLs.java`); each maps to `hadoop.kms.acl.<TYPE>` and
  `hadoop.kms.blacklist.<TYPE>` (default `*`, i.e. allow-all when unset — a
  hardened deployment must set every ACL explicitly).
- Per-key ACLs: `default.key.acl.<OP>` (`KMSConfiguration.DEFAULT_KEY_ACL_PREFIX`)
  plus key-embedded ACLs, evaluated by
  `KeyAuthorizationKeyProvider.hasAccessToKey(keyName, ugi, KeyOpType)` with
  `MANAGEMENT`/`ALL`/operation-specific checks, gated by
  `hadoop.kms.key.authorization.enable` (default true).
- HTTP auth for KMS is the hadoop-auth filter chain
  (`KMSAuthenticationFilter`), reusing §12.2 with the `hadoop.kms.authentication.*`
  prefix; `KMSMDCFilter` then binds the identity for auditing.

## 13. Logging and auditability

- Framework: all modules log through the SLF4J API
  (`org.slf4j.Logger`, `LoggerFactory`); `hadoop-common` ships binding
  `slf4j-reload4j` (`hadoop-common/pom.xml`), and `hadoop-project/pom.xml` manages
  log4j2 2.26.1 with the `log4j-1.2-api` bridge, so configuration is reload4j/log4j
  properties while the backend may be log4j2. There is no direct `java.util.logging`
  or console logging in `hadoop-common` main code.
- Audit logger #1 — RPC service authorization:
  `ServiceAuthorizationManager.AUDITLOG` =
  `SecurityLogger.org.apache.hadoop.security.authorize.ServiceAuthorizationManager`.
  Emits `Authorization successful for <ugi> for protocol=<class>` at INFO and
  `Authorization failed for <ugi> for protocol=<class>` / host-denial lines at WARN,
  both containing the UGI and the protocol class — sufficient to correlate a denial
  with the exact RPC interface.
- Audit logger #2 — KMS: logger name `kms-audit` (`KMSAudit.KMS_LOGGER_NAME`),
  written by pluggable `KMSAuditLogger` implementations
  (`hadoop.kms.audit.logger`, default `SimpleKMSAuditLogger` at INFO level). Events
  include the KMS operation (`KMSAudit` `OpStatus.OK`/`UNAUTHORIZED`/...), the user,
  the key name, and an aggregation window (10 s) for repeat cache events; the
  logger class contract mandates strict backwards compatibility of the line format
  (`KMSAuditLogger` javadoc warning).
- Correlation mechanisms:
  `ipc.CallerContext` (an `InheritableThreadLocal` set by the client via
  `CallerContext.setCurrent`, carrying `clientId`, `clientCallId`, `realUser`,
  `clientIp`) is serialized onto every `Server.Call` and retrievable server-side
  (`Server.Call.getCallerContext`) — the supported way to tie an RPC server log
  line back to the originating client call.
  For KMS, `KMSMDCFilter` puts the authenticated user and request id into the SLF4J
  MDC so every log line of a REST request carries the caller.
  For object stores, `fs/store/audit/AuditSpanSource`/`AuditSpan` provide
  span-based attribution of async fs operations.
- Metrics (metrics2) contexts registered by these modules: `rpc`
  (`ipc/metrics/RpcMetrics`, `RetryCacheMetrics`, `RpcDetailedMetrics`),
  `decayrpcschedulerdetailed` (`DecayRpcSchedulerDetailedMetrics`); servers (e.g.
  KMS via `KMSWebServer`) additionally register `JvmMetrics` and run
  `JvmPauseMonitor`. Metrics complement logs: queue and processing latency are
  only in metrics2, not logged.
- Dynamic level control: `org.apache.hadoop.log.LogLevel.Servlet` mounted at
  `/logLevel` by `HttpServer2`; configuration inspection at `/conf` via
  `ConfServlet` — sensitive keys redacted by `ConfigRedactor`
  (`hadoop.security.instrumentation.requires.admin` gates all instrumentation
  servlets).
- What is *not* audited in this tree (checkable negative): `FileSystem` operations
  themselves are not audit-logged in `hadoop-common` (fs audit logging is the
  HDFS NameNode's job); the common fs package only provides the span machinery.

Per-thread IO statistics add an fs attribution surface: `IOStatisticsContext`
(`fs/statistics/`, resolved via
`IOStatisticsContextIntegration.getCurrentIOStatisticsContext()` from a
`WeakReferenceThreadMap`, not a `java.lang.ThreadLocal`) attaches stream
counters to whichever thread performs the IO, complementing the span machinery
above.

## 14. Integration points

Everything below is externally observable and therefore testable.

- **RPC transport.** Hadoop IPC (`Server`/`Client`) is a TCP protocol with the
  "hrpc" connection header, protocol-class negotiation, and optional SASL wrap
  (QOP). Bind address/port and handler count are always supplied by the owning
  daemon (HDFS/YARN set their own `ipc.<x>.handler.count`); the shared limits are
  `ipc.server.max.connections` (default 0 = unlimited),
  `ipc.server.read.threadpool.size` (default 1),
  `ipc.server.handler.queue.size` (default 100/handler),
  `ipc.maximum.data.length` (`IPC_MAXIMUM_DATA_LENGTH`). A PR must not change the
  header/format without a compatibility story — `RpcKind` and
  `ProtocolSignature` versioning are the contract.
- **HTTP endpoints (`HttpServer2`).** Every HttpServer2 mounts `/stacks`,
  `/logLevel`, `/jmx`, `/conf`; KMS adds its REST API at
  `hadoop.kms.http.port` (default 9600, overridable by the deprecated
  `KMS_HTTP_PORT` env var — `KMSWebServer.java`). Instrumentation servlets enforce
  admin ACLs only when `hadoop.security.instrumentation.requires.admin` is true.
  `hadoop-auth` filters attach via `AuthenticationFilterInitializer`.
- **Kerberos principals.** Services construct principals with
  `SecurityUtil.getServerPrincipal(<principal-pattern>, hostname)`; the `_HOST`
  expansion can be influenced by `hadoop.security.dns.interface` /
  `hadoop.security.dns.nameserver`. Login material: keytab path + principal are
  passed to `UserGroupInformation.loginUserFromKeytab`; ticket-cache renewal
  shells out to `kinit` (`hadoop.kerberos.kinit.command`, default `kinit`);
  the KDC in tests is `hadoop-minikdc`'s `MiniKdc`.
- **Configuration files consumed.** `core-default.xml` (resource, from
  `hadoop-common`'s `src/main/resources`) then `core-site.xml`; plus
  `hadoop-policy.xml` (service authorization, overridable via
  `-Dhadoop.policy.file`), `ssl-server.xml` / `ssl-client.xml`
  (`hadoop.ssl.server.conf` / `hadoop.ssl.client.conf`), and for KMS
  `kms-site.xml` located via the `kms.config.dir` system property
  (`KMSConfiguration.getKMSConfDir`). `core-default.xml` keys a PR may not break
  (name = default, verified in source): `hadoop.security.authorization` (false),
  `hadoop.security.authentication` (simple),
  `hadoop.security.group.mapping` (JniBasedUnixGroupsMappingWithFallback),
  `hadoop.security.groups.cache.secs` (300),
  `hadoop.security.groups.negative-cache.secs` (30),
  `hadoop.security.groups.cache.background.reload` (false) / `.threads` (3),
  `hadoop.security.instrumentation.requires.admin` (false),
  `hadoop.rpc.protection` (authentication),
  `hadoop.kerberos.min.seconds.before.relogin` (60),
  `ipc.server.max.connections` (0),
  `ipc.server.read.threadpool.size` (1),
  `ipc.server.rpc.read.connection-queue.size` (100),
  `ipc.server.handler.queue.size` (100),
  `fs.automatic.close` (true),
  `fs.creation.parallel.count` (64),
  `ipc.client.asyncCalls.max` (100).
- **Hadoop-auth contract.** `hadoop.http.authentication.type` and friends are
  read by `AuthenticationFilter`; handler classes must implement
  `AuthenticationHandler` and the cookie must validate against the configured
  `SignerSecretProvider`.
- **KMS client.** `hadoop.security.key.provider.path`-style wiring via
  `KeyProviderFactory` (`hadoop.security.key.provider.path` →
  `KMSClientProvider` scheme `kms://`); client behaviour depends on the KMS
  endpoint (§6) being reachable over HTTP(S) with hadoop-auth or `kms-dt` tokens.
- **External processes / JVM-OS dependencies.** JNI group mapping requires
  `libhadoop` (`JniBasedUnixGroupsMapping(WithFallback)`); shell mapping requires
  a POSIX shell (`bash -c groups`); `kinit` binary for ticket-cache renewal;
  `Shell`/`RunJar` assume a POSIX OS (Windows has dedicated `WinUtils` paths);
  native codecs (Snappy/LZ4/Zstd) load via `NativeCodeLoader` and degrade or throw
  when absent — a PR that adds a hard native dependency must state it.
- **ZooKeeper.** `ZKSignerSecretProvider` (hadoop-auth secret rollover),
  `ZKDelegationTokenSecretManager` (shared delegation tokens), and
  `hadoop-registry`'s Curator client (ZK paths under `/registry/users/...` with
  SASL-derived ACLs via `RegistrySecurity`).
- **NFS (hadoop-nfs).** `MountdBase` listens on TCP/UDP for the MOUNT protocol and
  `Nfs3Base` on the NFS port; export access control is `NfsExports`
  (`AccessPrivilege` rules per client host). The gateway is stateless (§8).

## 15. Non-functional requirement candidates

Requirement-derivable statements for PR review; each cites its source class.

1. **R-NFR-1:** `FileSystem.get` must return the same instance for concurrent
   calls with identical (URI, user) keys, and a losing racing creator must close
   its duplicate outside all locks — `FileSystem.Cache.getInternal`
   (`fs.creation.parallel.count` semaphore, default 64).
2. **R-NFR-2:** All cache mutations (`FileSystem.CACHE`) must occur under the
   Cache object monitor; no raw `map` access may be added outside the synchronized
   methods (`FileSystem.Cache`).
3. **R-NFR-3:** A `FileSystem` implementation must be thread-safe for concurrent
   use by all threads of one user, because `CACHE` shares one instance per
   (URI, user) (`FileSystem.Cache.Key`).
4. **R-NFR-4:** Client RPC must bound in-flight async calls to
   `ipc.client.asyncCalls.max` (default 100) and fail the excess with
   `AsyncCallLimitExceededException` rather than queue indefinitely
   (`Client.asyncCallCounter`).
5. **R-NFR-5:** The RPC server call queue must be bounded at
   handlerCount × `ipc.server.handler.queue.size` (default 100/handler) and must
   be replaceable at runtime via `RefreshCallQueueProtocol` without dropping
   in-flight calls (`CallQueueManager.swapQueue`).
6. **R-NFR-6:** Idle RPC connections must be reaped by the connection scanner no
   faster than `ipc.client.connection.maxidletime` × 2 and at most
   `ipc.client.kill.max` per scan (`Server.ConnectionManager`).
7. **R-NFR-7:** Kerberos re-login must be atomic against concurrent credential
   users: `relogin()` must hold `HadoopLoginContext.getSubjectLock()` and must not
   re-login more than once per `hadoop.kerberos.min.seconds.before.relogin`
   (default 60 s) (`UserGroupInformation.relogin`).
8. **R-NFR-8:** Group lookups must be served from a cache expiring within 10 ×
   `hadoop.security.groups.cache.secs` (default 300 s) with an optional negative
   cache (`hadoop.security.groups.negative-cache.secs`, default 30 s)
   (`Groups`).
9. **R-NFR-9:** An unlisted protocol must always be denied when service-level
   authorization is enabled (`ServiceAuthorizationManager.authorize` —
   "Protocol ... is not known"), and every allow/deny must be logged to the
   `SecurityLogger.*` audit logger.
10. **R-NFR-10:** Impersonation must be denied unless the real user is listed in
    `hadoop.proxyuser.<user>.users`/`.groups` **and** the client IP matches
    `hadoop.proxyuser.<user>.hosts`; enforcement goes through
    `ProxyUsers.authorize` with the configured `ImpersonationProvider`
    (`DefaultImpersonationProvider`).
11. **R-NFR-11:** HTTP authentication must validate the signed cookie against the
    configured `SignerSecretProvider` and must never accept a token past its
    expiry (`AuthenticationFilter.doFilter`, `token.validity` default 36000 s);
    pseudo (trust-`?user.name`) auth must not be enabled in production configs.
12. **R-NFR-12:** TLS configuration must come from `ssl-server.xml`/`ssl-client.xml`
    (or files named by `hadoop.ssl.server.conf`/`hadoop.ssl.client.conf`) and the
    truststore must be hot-reloadable without restart
    (`ReloadingX509TrustManager`).
13. **R-NFR-13:** KMS operation access must be denied by default when the
    corresponding `hadoop.kms.acl.<TYPE>` is unset only if the wildcard default is
    overridden; a hardened deployment must set all nine
    `KMSACLs.Type` ACLs plus blacklists explicitly (`KMSACLs`).
14. **R-NFR-14:** KMS ACL changes must take effect without restart within the
    reloader period (1 s) via the volatile-map swap (`KMSACLs` scheduled reloader).
15. **R-NFR-15:** Metrics sampling must never block on a slow sink: a full sink
    queue drops records (`SinkQueue.enqueue` failure → dropped record) and the
    sampler runs on its own timer thread (`MetricsSystemImpl`).
16. **R-NFR-16:** Service stop must proceed in reverse initialization order for
    `CompositeService` children, and a child's stop failure must not abort the
    cascade (`CompositeService.stop`, `ServiceOperations.stopQuietly`).
17. **R-NFR-17:** JVM shutdown hooks must execute in priority order with a per-hook
    timeout, and a timed-out hook must be cancelled without preventing later hooks
    (`ShutdownHookManager.executeShutdown`).
18. **R-NFR-18:** Audit records must be backwards compatible: the KMS audit line
    format is explicitly frozen (`KMSAuditLogger` javadoc) and the service-authz
    audit lines embed user + protocol; any change to these formats is a breaking
    change requiring review.
19. **R-NFR-19:** Every RPC request must carry correlation data retrievable at the
    server (`CallerContext` with `clientId`/`clientCallId`, transmitted on
    `Server.Call`) so a server-side log line can be traced to the client call.
20. **R-NFR-20:** Sensitive configuration values must be redacted from the `/conf`
    endpoint and config dumps (`ConfigRedactor`), and instrumentation servlets must
    require admin authentication when
    `hadoop.security.instrumentation.requires.admin` is true.
