# Apache Hadoop "Common" — Requirements for PR Review

**As-of:** apache/trunk commit `c815ec8e1e9` (2026-11-14). Sections may drift from later trunk; check staleness before trusting (see the hadoop-pr-arch-requirements skill).

**Status:** DRAFT
**Date:** 2026-11-14
**Source doc:** `notes/architecture/hadoop-common-architecture.md` (1000 lines, source-grounded)
**Scope of source:** `hadoop-common-project/` (hadoop-annotations, hadoop-auth,
hadoop-auth-examples, hadoop-common, hadoop-kms, hadoop-minikdc, hadoop-nfs, hadoop-registry)

## Scope and derivation method

Every numbered item below is a single reviewable rule: a reviewer reading a proposed
diff must be able to state "this satisfies / violates FR-7" without further derivation.

- **Functional requirements (FR-x)** derive from the per-module/per-subcomponent behaviour descriptions (arch
  §2–§10, §16), ordered by the architecture document's structure; each cites the arch section and the key
  class that grounds it.
- **Non-functional requirements** are converted from the arch doc's dedicated sections: §11 Concurrency →
  NFR-C, §12 Security → NFR-S, §13 Logging and auditability → NFR-L, §14 Integration points → NFR-I.
- **No invented behaviour.** Only statements present in the architecture doc or directly verifiable in
  `hadoop-common-project/` source are included; defaults quoted in NFR-I-4 are verified in source per arch
  §14.
- **Supersession mapping:** arch §15's candidates R-NFR-1 … R-NFR-20 are mapped to and superseded by:
  R-NFR-1→NFR-C-2, R-NFR-2→NFR-C-3, R-NFR-3→NFR-C-4, R-NFR-4→NFR-C-5, R-NFR-5→NFR-C-6, R-NFR-6→NFR-C-7,
  R-NFR-7→NFR-C-8, R-NFR-8→NFR-C-9, R-NFR-9→NFR-S-7, R-NFR-10→NFR-S-9, R-NFR-11→NFR-S-5, R-NFR-12→NFR-S-6,
  R-NFR-13→NFR-S-11, R-NFR-14→NFR-C-13, R-NFR-15→NFR-C-11, R-NFR-16→NFR-C-10, R-NFR-17→NFR-C-12,
  R-NFR-18→NFR-L-2, R-NFR-19→NFR-L-3, R-NFR-20→NFR-L-6 + NFR-I-3.

## 1. Functional requirements

### 1.1 Module: hadoop-annotations (arch §2)

- **FR-1 — API-stability vocabulary only.** `hadoop-annotations` must contain only compile-time annotation
  definitions (`InterfaceAudience` `@Public`/`@Private`/`@LimitedPrivate`, `InterfaceStability`
  `@Stable`/`@Evolving`/`@Unstable`, `VisibleForTesting`) with no runtime behaviour and near-zero
  dependencies. (arch §2)

### 1.2 Module: hadoop-auth (arch §3)

- **FR-2 — Signed-cookie filter flow with pluggable handlers.** A request reaching
  `AuthenticationFilter.doFilter` must be authenticated from the signed `AuthenticationToken` cookie
  (verified via `Signer.verify`) when valid and unexpired; otherwise the configured `AuthenticationHandler`
  (pseudo, SPNEGO Kerberos, AltKerberos, JWT redirect, LDAP, or multi-scheme) must run the auth dance (e.g.
  SPNEGO `WWW-Authenticate: Negotiate` challenge, JWT redirect) and the resulting token must be signed and
  set as a cookie before the request proceeds. (arch §3, AuthenticationFilter)

- **FR-3 — Secret provider for token signing.** Token signing must go through `Signer` +
  `SignerSecretProvider` (`FileSignerSecretProvider`, `RandomSignerSecretProvider`, or
  `ZKSignerSecretProvider`); the ZK provider must share and roll the secret cluster-wide via ZooKeeper.
  (arch §3, SignerSecretProvider)

### 1.3 hadoop-common/conf — Configuration (arch §5)

- **FR-4 — Layered resource loading, last resource wins.** `Configuration.loadResources` must walk the
  resource list (defaults `core-default.xml`, user `core-site.xml`, programmatic adds) filling only unset
  keys, so the last resource defining a key wins; typed getters (`getInt`, `getTimeDuration`,
  `getStorageSize`, `getClass`, `getInstances`) must parse via `StorageSize`/`StorageUnit` ("512m"). (arch
  §5 conf, Configuration)

- **FR-5 — Invalidation on mutation.** Any `set*` call or `reloadConfiguration()` must invalidate the
  materialized values; the next get must re-run the resource walk. (arch §5 conf, Configuration)

- **FR-6 — Wiring new instances via Configurable.** `Configuration.getClass(..., Configuration)` must wire a
  newly created instance back into its owner through `Configurable.setConf`. (arch §5 conf, Configurable)

- **FR-7 — Hot reconfiguration restricted to the white-list.** `ReconfigurableBase` must re-evaluate only its
  changeable-property white-list and invoke `reconfigurePropertyImpl` on the owning service; the subclass
  decides whether the new value applies in place or requires restart. (arch §5 conf, ReconfigurableBase)

### 1.4 hadoop-common/fs — FileSystem API (arch §5)

- **FR-8 — Per-(URI, user) cached instances.** `FileSystem.get(URI, Configuration)` must compute a `Cache.Key`
  from URI (scheme+authority) + current UGI (+ unique flag), consult `FileSystem.CACHE`, and on a miss
  create the filesystem by reading `fs.<scheme>.impl` from the `Configuration` and reflectively
  instantiating it — one shared client per (URI, user) per JVM. (arch §5 fs, FileSystem.Cache)

- **FR-9 — Per-user teardown.** `FileSystem.closeAll(UserGroupInformation)` must close all cached instances
  belonging to one user, invoked by the `ClientFinalizer` hook at UGI logout. (arch §5 fs + §11.2)

- **FR-10 — Checksum verification on the local stack.** `ChecksumFileSystem` must open the sibling `.checksum`
  file (`getChecksumFile`), verify CRCs per chunk in `readChunk`, and throw `ChecksumException` on mismatch;
  on write, `FSOutputSummer` computes CRCs and `close` writes the sidecar. (arch §5 fs, ChecksumFileSystem)

- **FR-11 — Globbing walks the real tree.** `globStatus` must expand patterns through `Globber`/`GlobExpander`
  by walking the real tree via `listStatus` — filtering must not fabricate paths client-side. (arch §5 fs,
  Globber)

- **FR-12 — Two API stacks and stream capabilities.** The `FileSystem` (cached) and
  `AbstractFileSystem`/`FileContext` (non-cached, scheme-explicit per `FsConstants`) stacks must both be
  supported, with `FilterFs`/`FilterFileSystem` decorators and `FileSystemLinkResolver`/`FSLinkResolver`
  retry loops; `FSDataInputStream` must wrap `Seekable`, `PositionedReadable`, `CanSetReadahead`,
  `CanUnbuffer`, and `FSDataOutputStream` must be built via `FSDataOutputStreamBuilder`. (arch §5 fs)

### 1.5 hadoop-common/ipc — RPC framework (arch §5)

- **FR-13 — Client call lifecycle.** The protobuf proxy `Invoker` (`ProtobufRpcEngine2`) must validate the
  `RpcController`+`Message` args, wrap the request (`constructRpcRequest`), obtain/create the `Connection`
  for the `ConnectionId` (`setupIOstreams` negotiates connection header + SASL), register the `Client.Call`,
  and park the caller until the connection's run loop matches the response by call id — returning the value
  or the unwrapped `RemoteException`. (arch §5 ipc, Client)

- **FR-14 — Engine selection and version negotiation.** `RPC.getProxy`/`getServer` must select the engine by
  `RpcKind` (`ProtobufRpcEngine2` current; legacy `ProtobufRpcEngine`/`WritableRpcEngine`), with
  `ProtocolProxy`/`ProtocolSignature`/ `ProtocolInfo` negotiating protocol versions. (arch §5 ipc)

- **FR-15 — Server pipeline.** The server must process calls through `Listener` (accept) → NIO `Reader`
  threads (decode headers via `processConnectionContext`/ `processOneRpc`, build `Server.Call`s) → the
  single `CallQueueManager<Call>` → `Handler` workers (invoke through the engine's server translator) → a
  single `Responder` flushing replies. (arch §5 ipc, Server)

- **FR-16 — Call-queue scheduling modes.** The call queue must support a plain `LinkedBlockingQueue` default
  and a `FairCallQueue` + `DecayRpcScheduler` configuration that prioritizes small users under floods; the
  queue implementation may be swapped live via `swapQueue`. (arch §5 ipc, CallQueueManager)

- **FR-17 — Retry deduplication.** `RetryCache` must remember recent retriable calls by client+call id in a
  `LightWeightGSet` so a retried RPC returns the first response instead of re-executing the call. (arch §5
  ipc, RetryCache)

### 1.6 hadoop-common/security — UGI, Kerberos, authorization (arch §5)

- **FR-18 — UGI login and auto-renewal.** `UserGroupInformation.getLoginUser()` must build a JAAS `Subject`
  (`createLoginUser`) and, when a keytab is set, spawn an auto-renewal thread
  (`spawnAutoRenewalForUserTokenThread`). (arch §5 security, UGI)

- **FR-19 — Keytab re-login near TGT expiry.** `checkTGTAndReloginFromKeytab()` / `reloginFromKeytab()` must
  compare TGT expiry against the renew window and re-run the JAAS login (swapping the subject) when stale;
  daemons call it atop each RPC handler and clients before expensive operations. (arch §5 security, UGI)

- **FR-20 — doAs semantics.** `UserGroupInformation.doAs(PrivilegedExceptionAction)` must run the action
  inside `SubjectUtil.doAs` (JAAS `Subject.doAs`) and unwrap `PrivilegedActionException` causes back to the
  original checked exception. (arch §5 security, UGI)

- **FR-21 — Pluggable cached group mapping.** `Groups.getGroups(user)` must consult a cached host→groups map,
  falling back to the configured `GroupMappingServiceProvider` chain (`ShellBasedUnixGroupsMapping`,
  `JniBasedUnixGroupsMapping(WithFallback)`, `LdapGroupsMapping`, `RuleBasedLdapGroupsMapping`,
  `CompositeGroupsMapping`, netgroups via `JniBasedUnixGroupsNetgroupMapping` + `NetgroupCache`). (arch §5
  security, Groups)

- **FR-39 — ZK-backed shared delegation-token store.** When the ZK backend is enabled,
  `ZKDelegationTokenSecretManager` must persist delegation keys and token identifiers in ZooKeeper
  (`<zk-dt-secret-manager.znode.working.path>/ZKDTSMRoot`) so all instances of the service share one token
  state, mirror the znodes into `allKeys`/`currentTokens` through per-root `CuratorCache` listeners, and read
  the authoritative state from ZK on verify/renew/cancel. (arch §12.4)

### 1.7 hadoop-common/io — Writable serialization (arch §5)

- **FR-22 — Hand-written binary format and prefix comparison.** `Writable.write/ readFields` must use the
  hand-written binary format on `DataOutput`/`DataInput`; `Text.writeString` writes a varint length then raw
  UTF-8, `Text` must validate UTF-8 (`validateUTF8`) and support zero-copy compares via `BinaryComparable`;
  and `WritableComparator.get(Class)` must return a cached comparator able to compare record prefixes inside
  a byte array without deserializing. (arch §5 io, Text, WritableComparator)

- **FR-23 — SequenceFile block format.** `SequenceFile.Writer.append` must serialize key/value, compute
  checksums, and write sync markers every `SYNC_INTERVAL`; readers must seek by those markers;
  `MapFile`/`BloomMapFile` build on it. (arch §5 io, SequenceFile)

- **FR-24 — Pooled codecs.** Compression codecs (Gzip/Snappy/LZ4/Zstd) must be obtained from and returned to
  `CodecPool` free lists. (arch §5 io, CodecPool)

### 1.8 hadoop-common/metrics2 (arch §5)

- **FR-25 — Source → sink record flow with `@Metric` support.** Sources must register via
  `DefaultMetricsSystem.initialize`/`register`, be wrapped in a `MetricsSourceAdapter` by
  `MetricsSystemImpl`, sampled on a timer via `source.getMetrics(collector, all)`, and delivered through
  each sink's bounded `SinkQueue` to a dedicated sink thread calling `sink.putMetrics(record)`;
  `@Metric`-annotated fields must become in-place gauges/counters via
  `MetricsAnnotations`/`MetricsRegistry`. (arch §5 metrics2, MetricsSystemImpl)

### 1.9 hadoop-common/service — lifecycle and launcher (arch §5)

- **FR-26 — State machine.** Service state must follow the legal transitions `NOTINITED(0) → INITED(1) →
  STARTED(2) → STOPPED(3)` (terminal), plus stop from any state and reuse `STOPPED → NOTINITED`;
  `ServiceStateModel.enterState` must validate the transition, fire `LifecycleEvent`s, and throw
  `ServiceStateException` on an illegal request. `stop` must be idempotent. (arch §5 service,
  ServiceStateModel)

- **FR-27 — Composite ordering.** `CompositeService` must initialize children in add order; `addService` while
  the composite is STARTED must start the child immediately. (arch §5 service, CompositeService)

- **FR-28 — Daemon entry point.** `ServiceLauncher` must parse `LauncherArguments`, create the service, drive
  the lifecycle, install `ServiceShutdownHook`, `InterruptEscalator` (SIGTERM escalation to exit),
  `IrqHandler` and `HadoopUncaughtExceptionHandler`, mapping failures to `LauncherExitCodes`. (arch §5
  service + §11.9)

### 1.10 hadoop-common/net (arch §5)

- **FR-29 — Topology distances.** `NetworkTopology.getDistance(n1, n2)` must return the
  walk-to-common-ancestor costs (same node = 0, same rack = 2, same cluster = 4) on the
  `InnerNode`/`NodeBase` `/dc/rack/host` tree, and `chooseRandom(scope, excludedNodes)` must pick a random
  leaf under the scope honouring the exclude set. (arch §5 net, NetworkTopology)

- **FR-30 — Pluggable DNS-to-rack resolution.** `DNSToSwitchMapping.resolve(List)` must consult the cache
  (`CachedDNSToSwitchMapping`); script mapping must shell out per `topology.script.file.name`;
  `TableMapping` and `ScriptBasedMapping(WithDependency)` must remain available alternatives. (arch §5 net,
  DNSToSwitchMapping)

### 1.11 hadoop-common/util (+functional) and launcher (arch §5)

- **FR-31 — CLI argument pre-processing.** `ToolRunner`/`GenericOptionsParser` must pre-process the standard
  `-D`/`-conf`/`--files` arguments for every CLI built on `Tool`. (arch §5 util, GenericOptionsParser)

- **FR-32 — Shutdown hooks.** `ShutdownHookManager` must register exactly one JVM hook and submit hooks to a
  single-thread executor executed in priority order, each with its own timeout. (arch §11.7,
  ShutdownHookManager)

- **FR-33 — `hadoop jar` execution.** `RunJar` must unjar to a temp dir, build a `URLClassLoader` over the jar
  + `lib/`, and invoke the manifest `Main-Class`; the `bin/hadoop` script must set
  `HADOOP_CLASSNAME=org.apache.hadoop.util.RunJar` for jars and launch daemons via
  `org.apache.hadoop.service.launcher.ServiceLauncher`. (arch §5 launcher + §11.9, RunJar)

### 1.12 Module: hadoop-kms (arch §6)

- **FR-34 — KMS request chain.** A REST request must pass through `KMSAuthenticationFilter` (SPNEGO/cookie via
  hadoop-auth) → `KMSMDCFilter` (binds user/request to logs) → `KMS` (JAX-RS dispatch) →
  `KeyAuthorizationKeyProvider`, which checks `KMSACLs` for the operation type (GET/MANAGE/GENERATE…),
  performs the operation on the provider, and writes a `KMSAudit` record. (arch §6,
  KeyAuthorizationKeyProvider)

- **FR-35 — KMS client wiring.** Clients must obtain keys through `KeyProviderFactory` using
  `hadoop.security.key.provider.path` (scheme `kms://` → `KMSClientProvider` from `hadoop-common`'s
  `crypto/key/kms/client`). (arch §6 + §14)

### 1.13 Module: hadoop-minikdc (arch §7)

- **FR-36 — Test-only embedded KDC.** `MiniKdc` must start an in-process KDC (Apache Directory Server
  backend), create principals, and generate keytabs feeding `UserGroupInformation.loginUserFromKeytab`; no
  production code may depend on `hadoop-minikdc` (test scope only). (arch §7 + §10)

### 1.14 Module: hadoop-nfs (arch §8)

- **FR-37 — MOUNT and NFSv3 handling.** `MountdBase` must validate the mounting host against `NfsExports`
  (host/`AccessPrivilege` rules) and return a `FileHandle`; subsequent NFSv3 calls on `Nfs3Base`'s port must
  be XDR-decoded into `request.*` objects, dispatched through `Nfs3Interface`, and the `response.*`
  XDR-encoded back. The layer must remain stateless; filesystem-specific behaviour lives in
  `hadoop-hdfs-nfs`. (arch §8)

### 1.15 Module: hadoop-registry (arch §9)

- **FR-38 — Registry operations, ACLs and DNS.** A service must register by `mknode` + `bind(path,
  serviceRecord)` writing its JSON `ServiceRecord` (with `Endpoint` lists) under its user's ZK subtree
  (`/registry/users/<user>/<service>/…`); consumers must `resolve(path)`/`list(path)` through
  `CuratorService`'s retrying client; `RegistrySecurity` must set ZK SASL ACLs so only the owning principal
  writes its subtree; and the server-side DNS component must publish A/SRV records from registered records.
  (arch §9)

## 2. Non-functional requirements

### 2.1 Concurrency (arch §11)

- **NFR-C-1 — Configuration mutation atomicity.** All mutating/materializing methods of `Configuration`
  (`set`, `unset`, `setIfUnset`, `getProps`, `addResourceObject`, `reloadConfiguration`) must remain
  `synchronized` on the instance so a reader sees the old or the fully re-walked resource set — never a
  partial load; and `addDefaultResource`/`reloadExistingConfigurations` must remain `static synchronized` on
  `Configuration.class`, forcing every live configuration to reload. (arch §11.1)

- **NFR-C-2 — (supersedes R-NFR-1) Cache race resolution.** `FileSystem.get` must return the same instance for
  concurrent calls with identical (URI, user) keys; creation must happen outside the Cache lock but inside
  the `fs.creation.parallel.count` semaphore (default 64), with re-checks after acquiring the permit and
  after creation under the lock, and the losing racing creator must close its duplicate outside all locks
  (`fsToClose`, `discardedInstances`). Removing either re-check or the outside-lock close re-introduces a
  leak/deadlock. (arch §11.2, FileSystem.Cache.getInternal)

- **NFR-C-3 — (supersedes R-NFR-2) Cache and statistics monitor discipline.** Every lookup, insert, removal,
  and bulk close on `FileSystem.CACHE` must occur under `synchronized(this)` on the `Cache` object — no raw
  access to the plain-`HashMap` `map` outside the synchronized methods; per-scheme `Statistics` access
  (`getStatistics`/`getAllStatistics`/`clearStatistics`) must remain `static synchronized` with per-instance
  synchronization on increment; `deleteOnExit` bookkeeping must stay synchronized on the shared set. (arch
  §11.2, FileSystem.Cache)

- **NFR-C-4 — (supersedes R-NFR-3) FileSystem implementations must be thread-safe.** Because `CACHE` shares
  one instance per (URI, user), every `FileSystem` implementation must be safe for concurrent method calls
  by all threads of that user. (arch §11.2, FileSystem.Cache.Key)

- **NFR-C-5 — (supersedes R-NFR-4) Async call bound.** Client RPC must bound in-flight async calls to
  `ipc.client.asyncCalls.max` (default 100) via the `AtomicInteger asyncCallCounter` and fail the excess
  with `AsyncCallLimitExceededException` rather than queue indefinitely. (arch §11.3,
  Client.asyncCallCounter)

- **NFR-C-6 — (supersedes R-NFR-5) Bounded, hot-swappable call queue.** The server call queue must be bounded
  at handlerCount × `ipc.server.handler.queue.size` (default 100/handler), `put` may block with optional
  client backoff when full, and the queue must be replaceable at runtime via `RefreshCallQueueProtocol` →
  `CallQueueManager.swapQueue` without dropping in-flight calls. (arch §11.3, CallQueueManager)

- **NFR-C-7 — (supersedes R-NFR-6) Idle-connection reaping bounds.** The idle connection scanner must close
  connections idle longer than `ipc.client.connection.maxidletime` × 2, at most `ipc.client.kill.max` per
  scan, only after `ipc.client.idlethreshold` (default 4000) connections are open, and respect
  `ipc.server.max.connections` (default 0 = unlimited). (arch §11.3, Server.ConnectionManager)

- **NFR-C-8 — (supersedes R-NFR-7) Re-login atomicity and rate limit.** Kerberos re-login must hold
  `HadoopLoginContext.getSubjectLock()` so it is atomic against concurrent RPC handlers, SASL and SPNEGO
  code, and must not re-login more than once per `hadoop.kerberos.min.seconds.before.relogin` (default 60 s)
  via the volatile `User.lastLogin`. (arch §11.4, UserGroupInformation.relogin)

- **NFR-C-9 — (supersedes R-NFR-8) Group cache expiry.** Group lookups must be served from a cache expiring
  within 10 × `hadoop.security.groups.cache.secs` (default 300 s → hard cap 3000 s per entry), with an
  optional negative cache (`hadoop.security.groups.negative-cache.secs`, default 30 s) and optional
  background refresh pool (`hadoop.security.groups.cache.background.reload`, default false, `.threads`
  default 3); with background refresh off a slow backend blocks the calling RPC handler thread. (arch §11.4,
  Groups)

- **NFR-C-10 — (supersedes R-NFR-16) Shutdown cascade ordering and resilience.** `CompositeService.stop` must
  stop children in reverse order of start, and a child's stop failure must not abort the cascade
  (`ServiceOperations.stopQuietly` swallows stop failures). (arch §11.7, CompositeService)

- **NFR-C-11 — (supersedes R-NFR-15) Sampler must never block on sinks.** Metrics sampling must run on its own
  single daemon `Timer` thread (period = GCD of configured `*.period` values); when a sink's bounded
  `SinkQueue` is full, `enqueue` must fail and the record be dropped — a slow sink must never block the
  sampling thread. (arch §11.6, MetricsSystemImpl/SinkQueue)

- **NFR-C-12 — (supersedes R-NFR-17) Deterministic shutdown hooks.** JVM shutdown hooks must execute
  sequentially in priority order on a single-thread executor, each with its own timeout
  (`SERVICE_SHUTDOWN_TIMEOUT` for the FileSystem finalizer), and a timed-out hook must be cancelled without
  preventing later hooks. (arch §11.7, ShutdownHookManager.executeShutdown)

- **NFR-C-13 — (supersedes R-NFR-14) KMS hot reload and background threads.** `KMSACLs` must keep its ACL maps
  `volatile` and re-parse `kms-site.xml` on a single-thread scheduler every ~1 s (`RELOADER_SLEEP_MILLIS` =
  1000) so ACL changes take effect without restart; `KMSAudit` must emit audit records asynchronously on a
  single-thread daemon executor ("kms-audit_thread"), aggregating identical cache events over
  `hadoop.kms.audit.aggregation.window.ms` (default 10000 ms); `ValueQueue` background refill must use its
  fixed-size filler-thread pool with the synchronous path filling at least one value per the
  `SyncGenerationPolicy`. (arch §11.8, KMSACLs/KMSAudit)

- **NFR-C-14 — Service listener discipline.** `AbstractService.init/start/stop` must synchronize on
  `stateChangeLock` with the state in `ServiceStateModel`; listeners fire while holding the state-model
  lock, so listeners must be short and must not call back into the service, and
  `ServiceOperations.ServiceListeners` must copy the listener list outside the synchronized block before
  iterating. (arch §11.7, ServiceStateModel)

- **NFR-C-15 — Not-inherently-thread-safe utilities.** A `CodecPool` codec must be returned exactly once;
  `Text`/`DataOutputBuffer`/Writable objects are mutable single-threaded (sharing requires external
  synchronization); `LightWeightGSet`/`LightWeightCache` are not thread-safe — users (`ipc.RetryCache`,
  NameNode block management) must provide their own locking. A PR must not weaken these assumptions. (arch
  §11.5)

- **NFR-C-16 — ZK delegation-token startup load ordering.** `ZKDelegationTokenSecretManager.startThreads()`
  must not return while the in-memory mirror is incomplete or unordered: the initial cache population must be
  applied before the wait ends, later listener events and the initialized event must be applied in order on
  the Curator listener thread, and no thread may apply an older snapshot of a token after a newer change from
  a peer (cancel/renew during startup) has been applied. (arch §11.4, ZKDelegationTokenSecretManager)

### 2.2 Security (arch §12)

- **NFR-S-1 — RPC authentication selection.** `hadoop.security.authentication` (default `simple`) must select
  between unauthenticated and Kerberos RPC; with `kerberos`, servers must require a keytab login
  (`UserGroupInformation.loginUserFromKeytab`) and clients must use SASL GSSAPI
  (`SaslRpcServer.AuthMethod.KERBEROS`, mechanism "GSSAPI", code 81). (arch §12.1, SaslRpcServer)

- **NFR-S-2 — Wire protection levels.** `hadoop.rpc.protection` (default `authentication`; values
  `authentication`/`integrity`/`privacy`) must be resolved by `SaslPropertiesResolver` (replaceable via
  `hadoop.security.sasl.props.resolver.class`, e.g. `WhitelistBasedResolver`); `SaslRpcClient` must wrap the
  stream only when the negotiated QOP is above `auth`. (arch §12.1, SaslRpcClient/SaslPropertiesResolver)

- **NFR-S-3 — Delegation-token authentication (RPC and HTTP).** RPC delegation-token auth must use SASL DIGEST
  with the token identifier as username, verified server-side against the configured
  `SecretManager<TokenIdentifier>`; delegation tokens must use the `security/token/` machinery (`Token`,
  `TokenIdentifier`, `TokenSelector`, `TokenRenewer`, `SecretManager`;
  `AbstractDelegationTokenSecretManager` with ZK/SQL backends); the KMS kind is `kms-dt`
  (`KMSDelegationTokenIdentifier`); clients obtain/renew/cancel it via `DelegationTokenAuthenticatedURL`
  with renewer and `doAsUser` passed explicitly; and `fs/DelegationTokenRenewer` must auto-renew fs tokens
  held by the UGI. (arch §12.1 + §12.4, Server/KMSClientProvider)

- **NFR-S-4 — Centralized principal and login construction.** Service principals must be constructed through
  `SecurityUtil.getServerPrincipal` (`_HOST` substitution, optionally via
  `hadoop.security.dns.interface`/`hadoop.security.dns.nameserver`) — a PR touching principal parsing must
  go through `SecurityUtil`, not ad-hoc string edits; login material is keytab path + principal for
  `UserGroupInformation.loginUserFromKeytab`, ticket-cache renewal shells out to `kinit`
  (`hadoop.kerberos.kinit.command`, default `kinit`), and the test KDC is `hadoop-minikdc`'s `MiniKdc`.
  (arch §12.1 + §14, SecurityUtil)

- **NFR-S-5 — (supersedes R-NFR-11) HTTP signed-cookie validation.** HTTP authentication must validate the
  signed cookie against the configured `SignerSecretProvider` and must never accept a token past its expiry
  (`token.validity`, default 36000 s); pseudo (trust-`?user.name=`) auth must not be the configured
  `hadoop.http.authentication.type` on a production cluster. (arch §12.2, AuthenticationFilter.doFilter)

- **NFR-S-6 — (supersedes R-NFR-12) TLS configuration source and hot reload.** TLS configuration must come
  from `ssl-server.xml`/`ssl-client.xml` (or files named by
  `hadoop.ssl.server.conf`/`hadoop.ssl.client.conf`; keystore/truststore keys inside, plus
  `hadoop.ssl.require.client.cert`, `hadoop.ssl.hostname.verifier`, `hadoop.ssl.enabled.protocols`,
  `hadoop.ssl.keystores.factory.class` default `FileBasedKeyStoresFactory`), and the truststore must be
  hot-reloadable without restart (`ReloadingX509TrustManager`). (arch §12.3, SSLFactory)

- **NFR-S-7 — (supersedes R-NFR-9) Default-deny for unlisted protocols.** When `hadoop.security.authorization`
  (default false, read in `Server`'s constructor) is enabled, an unlisted protocol must always be denied
  ("Protocol ... is not known"), and every authorization allow/deny must be written to the
  `SecurityLogger.*` audit logger. (arch §12.5 + §13, ServiceAuthorizationManager.authorize)

- **NFR-S-8 — Service-authorization semantics and atomic refresh.** `ServiceAuthorizationManager.authorize`
  must enforce: in Kerberos mode the client principal equals the expected client principal
  (`SecurityUtil.getClientPrincipal`); the allow ACL `acls[0]` passes and the blocked ACL `acls[1]` does not
  match; the client IP is included by `hosts[0]` (`MachineList`) and not by `hosts[1]`. Policy source is
  `hadoop-policy.xml` (`-Dhadoop.policy.file` override) with fallbacks
  `security.service.authorization.default.acl[.blocked]` and `<key>.hosts`/ `<key>.blocked`; `refresh()`
  must atomically swap the `volatile IdentityHashMap` fields `protocolToAcls`/`protocolToMachineLists`, and
  `AccessControlList.isUserAllowed` must resolve groups through `Groups`. (arch §12.5)

- **NFR-S-9 — (supersedes R-NFR-10) Impersonation rules.** Impersonation must be denied unless the real user
  is listed in `hadoop.proxyuser.<superuser>.users`/`.groups` AND the client IP matches
  `hadoop.proxyuser.<superuser>.hosts` (`MachineList` — IP addresses, hostnames only via the resolver);
  enforcement must go through `ProxyUsers.authorize` with the configured `ImpersonationProvider`
  (`hadoop.security.impersonation.provider.class`, default `DefaultImpersonationProvider`), reloadable via
  `refreshSuperUserGroupsConfiguration` (volatile provider swap). (arch §12.6, ProxyUsers)

- **NFR-S-10 — Impersonation is not implicit.** Each RPC/HTTP endpoint must explicitly call the proxy-user
  check (`ProxyUsers.authorize`) — HDFS NameNode, YARN RM and KMS's `ProxyUserAuthenticationFilter` do; a
  new endpoint that accepts proxy users must wire the check (`ProxyUserAuthenticationFilterInitializer` for
  HTTP; `ProxyServers.refresh(conf)` records trusted proxy hosts). (arch §12.6)

- **NFR-S-11 — (supersedes R-NFR-13) KMS key ACLs.** KMS operation access must be governed by
  `hadoop.kms.acl.<TYPE>` and `hadoop.kms.blacklist.<TYPE>` for all nine `KMSACLs.Type` values (CREATE,
  DELETE, ROLLOVER, GET, GET_KEYS, GET_METADATA, SET_KEY_MATERIAL, GENERATE_EEK, DECRYPT_EEK — unset
  defaults to `*`, i.e. allow-all, so a hardened deployment must set every ACL explicitly), plus per-key
  ACLs (`default.key.acl.<OP>` + key-embedded ACLs) evaluated by
  `KeyAuthorizationKeyProvider.hasAccessToKey`, gated by `hadoop.kms.key.authorization.enable` (default
  true). (arch §12.8, KMSACLs)

- **NFR-S-12 — Group-mapping configuration.** `hadoop.security.group.mapping` must default to
  `JniBasedUnixGroupsMappingWithFallback` (falls back to `ShellBasedUnixGroupsMapping` when JNI is
  unavailable); shell mapping honours `hadoop.security.groups.shell.command.timeout` (default 0 = wait
  forever — an unbounded external dependency on the RPC handler path unless set). (arch §12.7)

### 2.3 Logging and auditability (arch §13)

- **NFR-L-1 — SLF4J only.** All modules must log through the SLF4J API (`org.slf4j.Logger`/`LoggerFactory`);
  no direct `java.util.logging` or console logging in `hadoop-common` main code (binding `slf4j-reload4j`;
  backend may be log4j2 via the `log4j-1.2-api` bridge). (arch §13)

- **NFR-L-2 — (supersedes R-NFR-18) Audit format compatibility.** Audit record formats are a compatibility
  surface: the KMS audit line format is explicitly frozen (`KMSAuditLogger` javadoc) and service-authz audit
  lines embed user + protocol (`Authorization successful/failed for <ugi> for protocol=<class>`); any change
  to these formats is a breaking change requiring review. (arch §13,
  ServiceAuthorizationManager.AUDITLOG/KMSAuditLogger)

- **NFR-L-3 — (supersedes R-NFR-19) RPC correlation data.** Every RPC request must carry correlation data
  retrievable at the server — `ipc.CallerContext` (`clientId`, `clientCallId`, `realUser`, `clientIp`, set
  via `CallerContext.setCurrent`, an `InheritableThreadLocal`) serialized onto every `Server.Call` — so a
  server-side log line can be traced to the originating client call. (arch §13, CallerContext/Server.Call)

- **NFR-L-4 — KMS request correlation.** `KMSMDCFilter` must put the authenticated user and request id into
  the SLF4J MDC for the duration of the request thread, so every log line of a KMS REST request carries the
  caller. (arch §13 + §11.8, KMSMDCFilter)

- **NFR-L-5 — Metrics complement logs.** The `rpc`, `decayrpcschedulerdetailed` metrics2 contexts (plus
  `JvmMetrics`/`JvmPauseMonitor` for servers such as KMS) must remain registered; queue and processing
  latency are observable only in metrics2, not logged — a PR removing these contexts removes the only
  latency observability. (arch §13, RpcMetrics/DecayRpcSchedulerDetailedMetrics)

- **NFR-L-6 — (supersedes R-NFR-20, redaction half) Sensitive config redaction.** Sensitive configuration
  values must be redacted from the `/conf` endpoint and config dumps by `ConfigRedactor`, and all
  instrumentation servlets (`/stacks`, `/logLevel`, `/jmx`, `/conf`) must require admin authentication when
  `hadoop.security.instrumentation.requires.admin` is true. (arch §13, ConfigRedactor)

- **NFR-L-7 — Checkable negative: no fs audit logging in common.** `FileSystem` operations themselves are not
  audit-logged in `hadoop-common` (fs audit logging is the HDFS NameNode's job; the fs package provides only
  the `fs/store/audit/AuditSpanSource`/`AuditSpan` span machinery). A PR must not claim or add fs-operation
  audit logging in `hadoop-common` as if it were existing behaviour. (arch §13)

### 2.4 Integration points (arch §14)

- **NFR-I-1 — RPC wire compatibility.** Hadoop IPC is a TCP protocol with the "hrpc" connection header,
  protocol-class negotiation, and optional SASL wrap (QOP), bounded by `ipc.maximum.data.length`; a PR must
  not change the header/format without a compatibility story — `RpcKind` and `ProtocolSignature` versioning
  are the contract. Bind address/port and handler count are always supplied by the owning daemon. (arch §14,
  Server/Client)

- **NFR-I-2 — HTTP endpoint surface and hadoop-auth contract.** Every `HttpServer2` must mount `/stacks`,
  `/logLevel`, `/jmx`, `/conf`; KMS serves its REST API on `hadoop.kms.http.port` (default 9600, overridable
  by the deprecated `KMS_HTTP_PORT` env var); hadoop-auth filters attach via
  `AuthenticationFilterInitializer` with the `hadoop.http.authentication.` prefix (`config.prefix`, `type`,
  `token.validity`, `cookie.domain`, `signer.secret.provider`), and custom handlers must implement
  `AuthenticationHandler` with cookies validating against the configured `SignerSecretProvider`. (arch §14,
  HttpServer2/KMSWebServer)

- **NFR-I-3 — (supersedes R-NFR-20, admin-gating half) Instrumentation admin ACLs.** Instrumentation servlets
  must enforce admin ACLs only when `hadoop.security.instrumentation.requires.admin` is true (default false
  in `core-default.xml`) — the gating behaviour must not change silently. (arch §14)

- **NFR-I-4 — core-default.xml defaults are a contract.** A PR must not change the shipped defaults of these
  `core-default.xml` keys (name = default, verified in source): `hadoop.security.authorization` (false),
  `hadoop.security.authentication` (simple), `hadoop.security.group.mapping`
  (JniBasedUnixGroupsMappingWithFallback), `hadoop.security.groups.cache.secs` (300),
  `hadoop.security.groups.negative-cache.secs` (30), `hadoop.security.groups.cache.background.reload`
  (false) / `.threads` (3), `hadoop.security.instrumentation.requires.admin` (false),
  `hadoop.rpc.protection` (authentication), `hadoop.kerberos.min.seconds.before.relogin` (60),
  `ipc.server.max.connections` (0), `ipc.server.read.threadpool.size` (1),
  `ipc.server.rpc.read.connection-queue.size` (100), `ipc.server.handler.queue.size` (100),
  `fs.automatic.close` (true), `fs.creation.parallel.count` (64), `ipc.client.asyncCalls.max` (100). (arch
  §14)

- **NFR-I-5 — KMS client endpoint dependency.** `KeyProviderFactory` wiring via
  `hadoop.security.key.provider.path` (scheme `kms://` → `KMSClientProvider`) depends on the KMS endpoint
  being reachable over HTTP(S) with hadoop-auth or `kms-dt` tokens; KMS config is `kms-site.xml` located via
  the `kms.config.dir` system property. (arch §14, KMSClientProvider/KMSConfiguration)

- **NFR-I-6 — External process and native dependencies must be declared.** JNI group mapping requires
  `libhadoop`; shell mapping requires a POSIX shell; `kinit` binary for ticket-cache renewal;
  `Shell`/`RunJar` assume POSIX (Windows has dedicated `WinUtils` paths); native codecs (Snappy/LZ4/Zstd)
  load via `NativeCodeLoader` and degrade or throw when absent — a PR adding a hard native dependency must
  state it. (arch §14)

- **NFR-I-7 — ZooKeeper integrations.** `ZKSignerSecretProvider` (hadoop-auth secret rollover),
  `ZKDelegationTokenSecretManager` (shared delegation tokens), and `hadoop-registry`'s Curator client (ZK
  paths under `/registry/users/...` with SASL-derived ACLs via `RegistrySecurity`) are the sanctioned
  ZooKeeper touchpoints; new ZK usage must fit one of these patterns. (arch §14)

- **NFR-I-8 — NFS surface.** `MountdBase` must listen on TCP/UDP for the MOUNT protocol and `Nfs3Base` on the
  NFS port; export access control is `NfsExports` (`AccessPrivilege` rules per client host); the gateway
  stays stateless. (arch §14)

## 3. PR-review checklists

When a diff touches an area, check the listed requirements (and cite them in review).

- **hadoop-annotations:** FR-1.
- **hadoop-auth (filter, handlers, Signer, secret providers):** FR-2, FR-3, NFR-S-5, NFR-I-2, NFR-I-7.
- **`org.apache.hadoop.conf`:** FR-4, FR-5, FR-6, FR-7, NFR-C-1, NFR-L-6.
- **`org.apache.hadoop.fs`:** FR-8, FR-9, FR-10, FR-11, FR-12, NFR-C-2, NFR-C-3, NFR-C-4, NFR-L-7, NFR-I-4.
- **`org.apache.hadoop.ipc` (Client, Server, call queues, RetryCache):** FR-13, FR-14, FR-15, FR-16, FR-17,
  NFR-C-5, NFR-C-6, NFR-C-7, NFR-L-3, NFR-I-1, NFR-I-4, NFR-S-3.
- **`org.apache.hadoop.security` (UGI, groups, SASL, authorize, tokens):** FR-18, FR-19, FR-20, FR-21, FR-39,
  NFR-C-8, NFR-C-9, NFR-C-16, NFR-S-1, NFR-S-2, NFR-S-3, NFR-S-4, NFR-S-7, NFR-S-8, NFR-S-9, NFR-S-10,
  NFR-S-12, NFR-L-2.
- **`org.apache.hadoop.io`:** FR-22, FR-23, FR-24, NFR-C-15.
- **`org.apache.hadoop.metrics2`:** FR-25, NFR-C-11, NFR-L-5.
- **`org.apache.hadoop.service` + launcher (`ServiceLauncher`, `ShutdownHookManager`, bin scripts,
  `RunJar`):** FR-26, FR-27, FR-28, FR-32, FR-33, NFR-C-10, NFR-C-12, NFR-C-14.
- **`org.apache.hadoop.net`:** FR-29, FR-30.
- **`org.apache.hadoop.util` (+functional):** FR-31, NFR-C-15, NFR-I-6.
- **hadoop-kms (server or client):** FR-34, FR-35, NFR-C-13, NFR-S-6, NFR-S-11, NFR-L-2, NFR-L-4, NFR-I-5.
- **hadoop-minikdc:** FR-36.
- **hadoop-nfs:** FR-37, NFR-I-8.
- **hadoop-registry:** FR-38, NFR-I-7.
- **TLS/SSL anywhere in the tree:** NFR-S-6.
- **Impersonation/proxy users:** NFR-S-9, NFR-S-10.
- **Any default value or config key change:** NFR-I-4, NFR-I-3.

## References

- Source architecture doc: `notes/architecture/hadoop-common-architecture.md`
  (sections cited as arch §n above).
- Source tree grounding: `hadoop-common-project/*/src/main/java/` (all class names in
  this document are real files there, per the architecture doc's depth-2 contract).
- Superseded candidate list: arch §15, R-NFR-1 … R-NFR-20 (mapping in "Scope and
  derivation method").
- Default values quoted in NFR-I-4 are verified in `core-default.xml` / source per
  arch §14.
