/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.hadoop.security.token.delegation;

import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.doAnswer;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.Collections;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.curator.framework.recipes.shared.SharedCount;
import org.apache.curator.framework.recipes.shared.VersionedValue;
import org.apache.curator.test.TestingServer;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.security.token.Token;
import org.apache.hadoop.security.token.delegation.AbstractDelegationTokenSecretManager.DelegationTokenInformation;
import org.apache.hadoop.security.token.delegation.web.DelegationTokenIdentifier;
import org.apache.hadoop.security.token.delegation.web.DelegationTokenManager;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproductions of races in {@link ZKDelegationTokenSecretManager} between
 * secret manager instances that share ZooKeeper. Each test asserts the
 * correct behaviour, so it fails while the race is present.
 * <p>
 * The tests use real ZooKeeper and Curator. Mockito spies on the shared
 * counters only decide when an interleaving happens, so that a window that
 * is narrow in production is hit every time.
 */
@Timeout(120)
public class TestZKDelegationTokenSecretManagerRaces {

  private static final Logger LOG =
      LoggerFactory.getLogger(TestZKDelegationTokenSecretManagerRaces.class);
  private static final long DAY_IN_SECS = 86400;

  private TestingServer zkServer;
  private DelegationTokenManager tmA;
  private DelegationTokenManager tmB;

  @BeforeEach
  public void setup() throws Exception {
    zkServer = new TestingServer();
    zkServer.start();
  }

  @AfterEach
  public void tearDown() throws Exception {
    // Clear any interrupt a test left on this thread before stopping.
    Thread.interrupted();
    try {
      if (tmA != null) {
        tmA.destroy();
      }
    } finally {
      try {
        if (tmB != null) {
          tmB.destroy();
        }
      } finally {
        zkServer.close();
      }
    }
  }

  private Configuration conf() {
    Configuration conf = new Configuration();
    conf.setBoolean(DelegationTokenManager.ENABLE_ZK_KEY, true);
    conf.set(ZKDelegationTokenSecretManager.ZK_DTSM_ZK_CONNECTION_STRING,
        zkServer.getConnectString());
    conf.set(ZKDelegationTokenSecretManager.ZK_DTSM_ZNODE_WORKING_PATH,
        "testPath");
    conf.set(ZKDelegationTokenSecretManager.ZK_DTSM_ZK_AUTH_TYPE, "none");
    conf.setLong(ZKDelegationTokenSecretManager.ZK_DTSM_ZK_SHUTDOWN_TIMEOUT,
        100);
    conf.setLong(
        ZKDelegationTokenSecretManager.ZK_DTSM_ZK_CACHE_INIT_TIMEOUT, 10000);
    conf.setLong(DelegationTokenManager.UPDATE_INTERVAL, DAY_IN_SECS);
    conf.setLong(DelegationTokenManager.MAX_LIFETIME, DAY_IN_SECS);
    conf.setLong(DelegationTokenManager.RENEW_INTERVAL, DAY_IN_SECS);
    conf.setLong(DelegationTokenManager.REMOVAL_SCAN_INTERVAL, DAY_IN_SECS);
    return conf;
  }

  @SuppressWarnings("rawtypes")
  private static ZKDelegationTokenSecretManager zksm(DelegationTokenManager tm) {
    return (ZKDelegationTokenSecretManager) tm.getDelegationTokenSecretManager();
  }

  /** Start two instances and wait until both finished their first key roll. */
  private void startTwoManagers(Configuration conf) throws Exception {
    tmA = new DelegationTokenManager(conf, new Text("bla"));
    tmA.init();
    tmB = new DelegationTokenManager(conf, new Text("bla"));
    tmB.init();
    // Each instance creates a key in startThreads() and its ExpiredTokenRemover
    // rolls the key once as soon as it starts: 4 key ids in total. After that
    // the remover does not touch the key id counter for UPDATE_INTERVAL.
    GenericTestUtils.waitFor(() -> zksm(tmA).getCurrentKeyId() == 4
        && zksm(tmB).getCurrentKeyId() == 4, 50, 10000);
  }

  private static SharedCount spyCounter(ZKDelegationTokenSecretManager<?> sm,
      String fieldName) throws Exception {
    Field f = ZKDelegationTokenSecretManager.class.getDeclaredField(fieldName);
    f.setAccessible(true);
    SharedCount spy = Mockito.spy((SharedCount) f.get(sm));
    f.set(sm, spy);
    return spy;
  }

  /**
   * Point 1: incrementCurrentKeyId() returns keyIdSeqCounter.getCount()
   * after its compare-and-set. If a peer increments the counter and this
   * instance's watch delivers the new value first, both instances return the
   * same key id.
   */
  @Test
  public void testConcurrentKeyIdIncrementsReturnDistinctIds()
      throws Exception {
    startTwoManagers(conf());
    ZKDelegationTokenSecretManager<?> smA = zksm(tmA);
    ZKDelegationTokenSecretManager<?> smB = zksm(tmB);

    SharedCount counterA = spyCounter(smA, "keyIdSeqCounter");
    AtomicBoolean interleave = new AtomicBoolean(true);
    AtomicInteger idFromB = new AtomicInteger(-1);
    doAnswer(invocation -> {
      boolean set = (Boolean) invocation.callRealMethod();
      if (set && interleave.compareAndSet(true, false)) {
        int valueSetByA = invocation.getArgument(1);
        LOG.info("A set the key id counter to {}", valueSetByA);
        // The peer increments right after A's successful write...
        idFromB.set(smB.incrementCurrentKeyId());
        LOG.info("B got key id {}", idFromB.get());
        // ...and A's watch delivers B's value before A reads the counter.
        GenericTestUtils.waitFor(
            () -> counterA.getCount() == idFromB.get(), 10, 10000);
      }
      return set;
    }).when(counterA).trySetCount(any(VersionedValue.class), anyInt());

    int idFromA = smA.incrementCurrentKeyId();
    LOG.info("A got key id {}", idFromA);
    assertNotEquals(idFromB.get(), idFromA,
        "Instances A and B were both given master key id " + idFromA);
  }

  /**
   * Point 2: stopThreads() interrupts the ExpiredTokenRemover, which may be
   * rolling the master key. incrementCurrentKeyId() swallows the interrupt
   * and re-sets the flag, and updateCurrentKey() then makes the new key
   * current before storing it, so the store fails on the interrupt and the
   * instance is left signing tokens with a key that is not in ZooKeeper.
   * <p>
   * This case delivers the interrupt after the counter write has reached
   * ZooKeeper, so the new key gets a fresh id.
   */
  @Test
  public void testKeyRollInterruptedAfterCounterWrite() throws Exception {
    runInterruptedKeyRoll(true);
  }

  /**
   * Point 2, with the interrupt delivered while the counter write is still
   * waiting for ZooKeeper (ZooKeeper throws InterruptedException from the
   * wait), so incrementCurrentKeyId() returns the id already in use.
   */
  @Test
  public void testKeyRollInterruptedDuringCounterWrite() throws Exception {
    runInterruptedKeyRoll(false);
  }

  private void runInterruptedKeyRoll(boolean afterWrite) throws Exception {
    startTwoManagers(conf());
    ZKDelegationTokenSecretManager<?> smA = zksm(tmA);
    DelegationKey before = currentKey(smA);
    LOG.info("A's current key before the roll: id {}", before.getKeyId());

    SharedCount counterA = spyCounter(smA, "keyIdSeqCounter");
    AtomicBoolean interruptOnce = new AtomicBoolean(true);
    doAnswer(invocation -> {
      if (!interruptOnce.compareAndSet(true, false)) {
        return invocation.callRealMethod();
      }
      if (afterWrite) {
        Object result = invocation.callRealMethod();
        Thread.currentThread().interrupt();
        return result;
      }
      throw new InterruptedException("interrupted waiting for ZooKeeper");
    }).when(counterA).trySetCount(any(VersionedValue.class), anyInt());

    try {
      smA.rollMasterKey();
      LOG.info("rollMasterKey() returned normally");
    } catch (IOException e) {
      LOG.info("rollMasterKey() failed: {}", e.toString());
    } finally {
      LOG.info("interrupt flag after the roll: {}", Thread.interrupted());
    }

    DelegationKey after = currentKey(smA);
    DelegationKey inZk = readKeyFromZk(smA, after.getKeyId());
    boolean newSecret =
        !Arrays.equals(before.getEncodedKey(), after.getEncodedKey());
    LOG.info("A's current key after the roll: id {}, new secret {}, "
        + "key counter {}; ZooKeeper has {} for that id",
        after.getKeyId(), newSecret, counterA.getCount(),
        inZk == null ? "no key"
            : Arrays.equals(inZk.getEncodedKey(), after.getEncodedKey())
                ? "the same secret" : "a different secret");

    if (inZk == null
        || !Arrays.equals(inZk.getEncodedKey(), after.getEncodedKey())) {
      fail("After an interrupted roll A's current key (id "
          + after.getKeyId() + ", " + (newSecret ? "new" : "old")
          + " secret) does not match ZooKeeper, which has "
          + (inZk == null ? "no key" : "a different secret")
          + " under that id: tokens A signs now cannot be renewed with the "
          + "key in ZooKeeper");
    }
  }

  private static DelegationKey currentKey(
      AbstractDelegationTokenSecretManager<?> sm) throws Exception {
    Field f = AbstractDelegationTokenSecretManager.class
        .getDeclaredField("currentKey");
    f.setAccessible(true);
    return (DelegationKey) f.get(sm);
  }

  private static DelegationKey readKeyFromZk(
      ZKDelegationTokenSecretManager<?> sm, int keyId) throws Exception {
    byte[] data;
    try {
      data = sm.zkClient.getData()
          .forPath("/ZKDTSMMasterKeyRoot/DK_" + keyId);
    } catch (org.apache.zookeeper.KeeperException.NoNodeException e) {
      return null;
    }
    DelegationKey key = new DelegationKey();
    key.readFields(new DataInputStream(new ByteArrayInputStream(data)));
    return key;
  }

  /**
   * Point 3: when the local range of sequence numbers is used up and the
   * thread is interrupted while reserving the next range,
   * incrementDelegationTokenSeqNum() swallows the interrupt and returns a
   * number outside any range it reserved, which a peer can also hand out.
   */
  @Test
  public void testInterruptedSeqNumReservationDoesNotDuplicate()
      throws Exception {
    Configuration conf = conf();
    conf.setInt(ZKDelegationTokenSecretManager.ZK_DTSM_TOKEN_SEQNUM_BATCH_SIZE,
        1);
    // A reserves sequence number 1 on startup, then B reserves 2.
    startTwoManagers(conf);
    ZKDelegationTokenSecretManager<?> smA = zksm(tmA);
    ZKDelegationTokenSecretManager<?> smB = zksm(tmB);

    int first = smA.incrementDelegationTokenSeqNum();
    LOG.info("A's sequence number from its reserved range: {}", first);

    // A's range is used up; the next call has to reserve a new one.
    int second;
    Thread.currentThread().interrupt();
    try {
      second = smA.incrementDelegationTokenSeqNum();
    } finally {
      LOG.info("interrupt flag after the call: {}", Thread.interrupted());
    }
    LOG.info("A's sequence number while interrupted: {}", second);

    int fromB = smB.incrementDelegationTokenSeqNum();
    LOG.info("B's sequence number: {}", fromB);
    assertNotEquals(fromB, second,
        "Instances A and B both handed out sequence number " + fromB);
  }

  /**
   * Point 4: ExpiredTokenRemover deletes a token that its local cache shows
   * as expired without checking ZooKeeper, so a token that a peer has just
   * renewed is deleted if the peer's update has not reached this instance
   * yet.
   */
  @SuppressWarnings({"unchecked", "rawtypes"})
  @Test
  public void testExpiryDoesNotDeleteTokenRenewedByPeer() throws Exception {
    startTwoManagers(conf());
    ZKDelegationTokenSecretManager smA = zksm(tmA);
    ZKDelegationTokenSecretManager smB = zksm(tmB);

    Token<DelegationTokenIdentifier> token =
        (Token<DelegationTokenIdentifier>) tmA.createToken(
            UserGroupInformation.getCurrentUser(), "foo");
    DelegationTokenIdentifier id = (DelegationTokenIdentifier)
        smA.decodeTokenIdentifier(token);

    // B renews the token, so in ZooKeeper it is valid for another day.
    tmB.renewToken(token, "foo");
    DelegationTokenInformation renewed = smB.getTokenInfoFromZK(id);
    assertNotNull(renewed);
    assertTrue(renewed.getRenewDate() > System.currentTimeMillis(),
        "the token should be renewed in ZooKeeper");

    // A's ExpiredTokenRemover chose the token from its local cache before
    // B's update arrived. This is the call removeExpiredToken() makes next.
    smA.logExpireTokens(Collections.singletonList(id));

    assertNotNull(smB.getTokenInfoFromZK(id, true),
        "A deleted from ZooKeeper a token that B had renewed");
  }
}
