# ZKDelegationTokenSecretManager: races between instances, at startup and at shutdown

This branch (`zkdtsm-race-repro`) holds reproduction tests for concurrency
problems in `ZKDelegationTokenSecretManager`, and this report explains them.
The tests are evidence, not fixes: each one asserts the correct behaviour, so
it **fails** while the problem is present.

Prepared with AI assistance (Claude Code). Every result below comes from
running the tests listed here; nothing is inferred from code reading alone
unless it is marked *by inspection*.

## 1. Summary

| # | Problem | Where it lives | Status | Test |
|---|---|---|---|---|
| 1 | Two instances can get the same master key id | trunk | reproduced every run | `TestZKDelegationTokenSecretManagerRaces#testConcurrentKeyIdIncrementsReturnDistinctIds` |
| 2 | An interrupted key roll leaves the instance signing with a key that ZooKeeper does not have, or has with a different secret | trunk | reproduced every run | `...Races#testKeyRollInterruptedAfterCounterWrite`, `...Races#testKeyRollInterruptedDuringCounterWrite` |
| 3 | An interrupted sequence number reservation hands out a number a peer also hands out | trunk | reproduced every run | `...Races#testInterruptedSeqNumReservationDoesNotDuplicate` |
| 4 | Expiry deletes from ZooKeeper a token that a peer has just renewed | trunk | reproduced every run | `...Races#testExpiryDoesNotDeleteTokenRenewedByPeer` |
| 5 | A token cancelled by a peer while an instance starts is put back into that instance's memory and accepted by `verifyToken()` | introduced by HADOOP-19966 / [apache/hadoop#8688](https://github.com/apache/hadoop/pull/8688) | reproduced deterministically; 6 of 13 unforced runs on #8688, 0 of 13 on trunk | `TestZKDelegationTokenSecretManagerStartupRaces#testTokenCancelledDuringStartupStaysCancelled`, `TestZKDelegationTokenSecretManagerCancelDuringStartup` |
| 6 | A token renewed by a peer while an instance starts gets its old renew date back in that instance's memory | introduced by #8688 | reproduced deterministically | `...StartupRaces#testTokenRenewedDuringStartupKeepsNewRenewDate` |

Problems 1 to 4 are pre-existing. Problems 5 and 6 do not occur on trunk,
because on trunk the startup load reads a cache that has not been filled yet
(the bug #8688 fixes); #8688 makes the startup load read the full cache, which
opens the race. A fix for 5 and 6 that keeps #8688's goal is described in
section 5 and passes the existing tests.

## 2. Versions tested

| Name in this report | Commit | What it is |
|---|---|---|
| trunk | `57f78d283ae1` | apache/hadoop trunk |
| #8688 | `ccf5b7fc2ac0` | head of apache/hadoop#8688 (Cheng Pan's four commits, unchanged) |
| stacked | `c4fba7b28044` | HADOOP-20011 (#8806) + #8688 + four follow-up commits answering the #8688 review |
| repro | this branch | stacked + the three test classes |

Environment: OpenJDK 21.0.12, Linux 6.18, Curator 5.2.0, ZooKeeper 3.8.6
(both from `hadoop-project/pom.xml`), ZooKeeper `TestingServer` in-process.

## 3. How the tests work

All tests use a real ZooKeeper server and real Curator clients, with two or
more secret manager instances sharing it, as in a KMS, HttpFS or Router
deployment. Where a race window is narrow, the test makes it happen every
time without changing any logic:

* **Mockito spies on the shared counters** (`keyIdSeqCounter`,
  `delTokSeqCounter`) decide *when* a peer acts or an interrupt arrives,
  then call the real Curator method.
* **A test subclass pauses the starting thread** in
  `processTokenAddOrUpdate()` while a real peer instance changes a token.
* **A `runSafe()` no-op is used as a barrier.** Curator 5.2.0 runs cache
  listener calls and `runSafe()` tasks in order on one single-threaded
  executor (`CuratorFrameworkImpl.makeRunSafeService()`), so once the no-op
  has run, every listener call queued before it has completed.

## 4. Problems in trunk (1 to 4)

### 4.1 Two instances can get the same master key id

`incrementCurrentKeyId()` increments the shared counter with a
compare-and-set, then returns `keyIdSeqCounter.getCount()`:

```java
incrSharedCount(keyIdSeqCounter, 1);
...
return keyIdSeqCounter.getCount();
```

`getCount()` returns the counter's locally cached value. In Curator 5.2.0,
`SharedValue.updateValue()` only ever moves that value forward, and the
counter's watch can deliver a peer's later increment before `getCount()` is
called. Both instances then use the same id.

Reproduced: instance A set the counter to 5, instance B then incremented it
to 6, A's watch delivered 6, and A returned 6. Both instances use master key
id 6. Both then store `DK_6`; the second write replaces the first key in
ZooKeeper, and tokens that other instances verify against it fail.

Fix: return the value this instance wrote, `incrSharedCount(...) + 1`.

### 4.2 An interrupted key roll

`stopThreads()` interrupts the `ExpiredTokenRemover`, which may be rolling the
master key. `incrementCurrentKeyId()` catches the `InterruptedException`,
sets the interrupt flag again, and returns the current id.
`updateCurrentKey()` then makes the new key current *before* storing it, and
the store fails on the interrupt. Two cases, both reproduced:

* interrupt after the counter write reached ZooKeeper: A's current key is id 5
  with a new secret, and ZooKeeper has **no** key 5;
* interrupt while the counter write waits for ZooKeeper: A's current key
  **reuses** id 4 with a new secret, and ZooKeeper holds a different secret
  under id 4.

In both cases tokens A signs afterwards cannot be renewed against the keys in
ZooKeeper (*by inspection*: renewal recomputes the password from
`getDelegationKey(id)`). Only an instance that is already stopping is
affected, so this is the least severe of the four. ZooKeeper's copy of the
key is **not** overwritten: the restored interrupt flag makes the store fail.

Fix: propagate the interrupt instead of returning an id, and only make the new
key current after it has been stored.

### 4.3 An interrupted sequence number reservation

When the local range of sequence numbers is used up,
`incrementDelegationTokenSeqNum()` reserves a new range from ZooKeeper. If the
thread is interrupted, it catches the `InterruptedException` and still returns
`++currentSeqNum`, a number outside any range it reserved. The comment says
only the expiry thread gets there, but `createPassword()` calls it from RPC
handler threads.

Reproduced with a batch size of 1: A handed out 2 while interrupted, and B
also handed out 2. Storing the second token then fails with `NodeExists`.

Fix: throw instead of returning a number.

### 4.4 Expiry deletes a token a peer has just renewed

The base class deletes expired tokens with `removeStoredToken(ident)`, which
calls `removeStoredToken(ident, false)` and does not check ZooKeeper first.
If a peer renewed the token and that update has not reached this instance
yet, the expiry scan still sees the old renew date and deletes the renewed
token. The RBF subclass guards against this (`checkAgainstZkBeforeDeletion`);
the base class, used by KMS and HttpFS, does not.

Reproduced: ZooKeeper showed the token renewed by B for another day, and A's
expiry path (`logExpireTokens()`, the call `removeExpiredToken()` makes after
choosing tokens) deleted it.

Fix: override `removeExpiredStoredToken()` to call
`removeStoredToken(ident, true)`.

## 5. Problems introduced by #8688 (5 and 6)

### 5.1 Cause

#8688 makes `startThreads()` wait for each `CuratorCache` to initialize and
then call `loadFromZKCache()`, which applies a snapshot of every cached node
**on the starting thread**. By then the cache listener is already active and
applies newer events **on Curator's `SafeNotifyService` thread**. The two are
not coordinated, so the starting thread can apply its older snapshot of a
node after the listener has applied a newer state:

```
starting thread                         listener thread
---------------                         ---------------
reads cached node DT_1 (valid)
                                        peer cancels DT_1
                                        NODE_DELETED -> currentTokens.remove(DT_1)
processTokenAddOrUpdate(old bytes)
  -> currentTokens.put(DT_1)            (nothing removes it again)
```

On trunk the same code runs, but `loadFromZKCache()` reads the cache straight
after `start()`, while it is still empty (the bug #8688 fixes), so the
listener applies every node in order and the result is correct.

### 5.2 Deterministic reproduction

`TestZKDelegationTokenSecretManagerStartupRaces` pauses the starting thread
just before it applies one token, lets a real peer cancel or renew that token,
waits until the restarted instance's cache and listener have handled the
change, then lets the starting thread continue.

| Test | Result on #8688 / stacked |
|---|---|
| `testTokenCancelledDuringStartupStaysCancelled` | fails: after startup the cancelled token is in memory, and `verifyToken()` **accepts it** |
| `testTokenRenewedDuringStartupKeepsNewRenewDate` | fails: memory holds the renew date from before the renewal (1.15 s older than the one in ZooKeeper) |

On trunk these two tests cannot reach their pause point (the starting thread
never applies a token), so they cannot compare the versions. The next test
does.

### 5.3 Same test, three versions

`TestZKDelegationTokenSecretManagerCancelDuringStartup` does not pause at any
point of `startThreads()`. A peer creates 300 tokens; then one thread starts a
new instance while another thread cancels all 300 through the peer. Once the
new instance has caught up, no token may be in its memory or pass
`verifyToken()`. The only timing aid is that the starting thread sleeps 2 ms
whenever it applies a token itself; it is the same on every version and does
nothing if the starting thread applies no tokens. The test file is identical
on all three versions.

| Version | Runs | Failed runs | Tokens applied by the starting thread | Cancelled tokens still accepted afterwards |
|---|---|---|---|---|
| trunk | 13 | **0** | 0 in every run | 0 in every run |
| #8688 (unchanged) | 13 | **6** | 170 to 209 | 1 to 3 in each failed run |
| stacked | 3 | 2 | 209 to 277 | 1 in each failed run |

The difference is the starting thread applying snapshots: it never does on
trunk, and does for most tokens on #8688. Every failing run left cancelled
tokens that the restarted instance still accepts.

### 5.4 Impact

A token cancelled while another instance is starting stays valid **on that
instance** until it is renewed or reaches its renew date, which is up to the
renew interval (one day by default). Cancelling is how a token is revoked, so
this weakens revocation for tokens cancelled around a restart. Because the
problem exists only in the unmerged #8688, no release is affected.

A token renewed while another instance starts keeps its old renew date on that
instance. Combined with 4.4, that instance can later delete the still-valid
token from ZooKeeper.

### 5.5 Fix, tested

Drop `loadFromZKCache()` and let the listener apply the initial nodes too:

* no `.afterInitialized()` on the key and token listeners;
* after `awaitCacheInitialized(...)`, only `syncTokenOwnerStats()` for the
  token cache.

The listener receives the initial nodes and every later change in order on one
thread, and `initialized()` after all initial nodes, so once the latch opens
memory is complete and no older snapshot can be applied afterwards. With this
change all 13 tests of `TestZKDelegationTokenSecretManager` pass, including
`testNodesLoadedAfterRestart`, which asserts that tokens are in memory as soon
as `startThreads()` returns. The tests in 5.2 then never reach their pause
point, because the starting thread no longer applies tokens; they show the
race in the current design but are not regression tests for the fix.

This replaces the `.afterInitialized()` follow-up on the stacked branch, which
assumes the snapshot load stays.

## 6. Also found, by inspection only

* **Two master keys per instance at startup.** `startThreads()` creates one
  key, and the `ExpiredTokenRemover` rolls another as soon as it starts (its
  last roll time starts at 0). Seen in the tests (key counter 4 after two
  instances start); wasteful but harmless.
* **A failed start leaves an instance that cannot be restarted.** With #8688 a
  failed start closes the instance's own Curator client, which cannot be
  started again. `ZKDelegationTokenSecretManagerImpl` (RBF) only logs a failed
  `startThreads()` in its constructor, so a Router would keep running with a
  stopped secret manager. Only reachable when a cache-init timeout is set.
* **RBF stop order.** `ZKDelegationTokenSecretManagerImpl.stopThreads()`
  closes the ZooKeeper client before shutting down its token-rebuild
  scheduler, and does not wait for it, so a rebuild can run against a closed
  client (its errors are ignored).
* **Calls during `stopThreads()`.** Nothing stops token operations while
  shutdown closes the counters and the client, so an in-flight call fails with
  a `RuntimeException` instead of a clean error.
* **Process exit on a ZooKeeper error during the expiry scan.** HADOOP-20010
  (on trunk) stops a failed store call from killing the process during
  shutdown, but while the instance is running a `RuntimeException` from
  `removeStoredToken()` still reaches `ExitUtil.terminate()`.

## 7. Running the tests

```
mvn -pl hadoop-common-project/hadoop-common -am install -DskipTests
cd hadoop-common-project/hadoop-common
mvn test -Dtest='TestZKDelegationTokenSecretManagerRaces,TestZKDelegationTokenSecretManagerStartupRaces,TestZKDelegationTokenSecretManagerCancelDuringStartup' \
    -Dmaven.test.failure.ignore=true
```

Each test logs what it observed (look for `INFO` lines from the test class in
`target/surefire-reports/*-output.txt`). Expected on this branch: every test
in `TestZKDelegationTokenSecretManagerRaces` and
`TestZKDelegationTokenSecretManagerStartupRaces` fails, and
`TestZKDelegationTokenSecretManagerCancelDuringStartup` fails in some runs.
To compare with trunk, copy `TestZKDelegationTokenSecretManagerCancelDuringStartup.java`
onto a trunk checkout; it uses only configuration keys that exist there.
