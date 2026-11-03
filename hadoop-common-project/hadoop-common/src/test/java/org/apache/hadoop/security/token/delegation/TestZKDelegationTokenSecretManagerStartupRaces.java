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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Predicate;

import org.apache.curator.framework.recipes.cache.ChildData;
import org.apache.curator.framework.recipes.cache.CuratorCacheBridge;
import org.apache.curator.test.TestingServer;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.security.token.SecretManager.InvalidToken;
import org.apache.hadoop.security.token.Token;
import org.apache.hadoop.security.token.delegation.AbstractDelegationTokenSecretManager.DelegationTokenInformation;
import org.apache.hadoop.security.token.delegation.web.DelegationTokenIdentifier;
import org.apache.hadoop.security.token.delegation.web.DelegationTokenManager;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproductions of races between the startup load of the token cache
 * (loadFromZKCache(), on the thread calling startThreads()) and the cache
 * listener (on Curator's SafeNotifyService thread). The loader applies a
 * snapshot of each node, so it can overwrite a newer state the listener has
 * already applied. Each test asserts the correct behaviour, so it fails
 * while the race is present.
 * <p>
 * The tests use real ZooKeeper and Curator. A test subclass only pauses the
 * startup thread before it applies one token, while a running peer instance
 * changes that token.
 */
@Timeout(120)
public class TestZKDelegationTokenSecretManagerStartupRaces {

  private static final Logger LOG = LoggerFactory.getLogger(
      TestZKDelegationTokenSecretManagerStartupRaces.class);
  private static final long DAY_IN_SECS = 86400;
  private static final Text KIND = new Text("bla");

  private TestingServer zkServer;
  private DelegationTokenManager peer;
  private PausingSecretManager restarted;

  @BeforeEach
  public void setup() throws Exception {
    zkServer = new TestingServer();
    zkServer.start();
  }

  @AfterEach
  public void tearDown() throws Exception {
    try {
      if (restarted != null && restarted.isRunning()) {
        restarted.stopThreads();
      }
    } finally {
      try {
        if (peer != null) {
          peer.destroy();
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
    conf.setLong(DelegationTokenManager.UPDATE_INTERVAL, DAY_IN_SECS);
    conf.setLong(DelegationTokenManager.MAX_LIFETIME, DAY_IN_SECS);
    // Below MAX_LIFETIME, so that a renewal moves the renew date.
    conf.setLong(DelegationTokenManager.RENEW_INTERVAL, 3600);
    conf.setLong(DelegationTokenManager.REMOVAL_SCAN_INTERVAL, DAY_IN_SECS);
    return conf;
  }

  /**
   * A secret manager that, on the thread running startThreads(), pauses
   * before applying the token with the given sequence number and runs an
   * action first.
   */
  private static class PausingSecretManager
      extends ZKDelegationTokenSecretManager<DelegationTokenIdentifier> {

    private volatile Thread startupThread;
    private volatile int targetSeq = -1;
    private volatile Runnable beforeApply;
    private final AtomicBoolean paused = new AtomicBoolean();

    PausingSecretManager(Configuration conf) {
      super(conf);
    }

    @Override
    public DelegationTokenIdentifier createIdentifier() {
      return new DelegationTokenIdentifier(KIND);
    }

    void startPausingAt(int seq, Runnable action) throws IOException {
      targetSeq = seq;
      beforeApply = action;
      startupThread = Thread.currentThread();
      startThreads();
    }

    boolean paused() {
      return paused.get();
    }

    @Override
    protected DelegationTokenIdentifier processTokenAddOrUpdate(byte[] data)
        throws IOException {
      if (Thread.currentThread() == startupThread) {
        DelegationTokenIdentifier id = createIdentifier();
        id.readFields(new DataInputStream(new ByteArrayInputStream(data)));
        if (id.getSequenceNumber() == targetSeq
            && paused.compareAndSet(false, true)) {
          LOG.info("Startup load paused before applying token {}", targetSeq);
          beforeApply.run();
          LOG.info("Startup load applies its snapshot of token {}", targetSeq);
        }
      }
      return super.processTokenAddOrUpdate(data);
    }

    /** This instance's cached copy of a token znode. */
    Optional<ChildData> cachedTokenNode(int seq) throws Exception {
      Field f = ZKDelegationTokenSecretManager.class
          .getDeclaredField("tokenCache");
      f.setAccessible(true);
      CuratorCacheBridge cache = (CuratorCacheBridge) f.get(this);
      return cache.get(ZK_DTSM_TOKENS_ROOT + "/DT_" + seq);
    }

    /**
     * Wait until this instance's cache satisfies the condition, then until
     * the listener calls queued so far have run: Curator runs listeners and
     * runSafe() tasks in order on one thread.
     */
    void awaitCacheAndListener(int seq, Predicate<Optional<ChildData>> cond)
        throws Exception {
      GenericTestUtils.waitFor(() -> {
        try {
          return cond.test(cachedTokenNode(seq));
        } catch (Exception e) {
          throw new RuntimeException(e);
        }
      }, 10, 10000);
      zkClient.runSafe(() -> { }).get();
    }
  }

  @SuppressWarnings("unchecked")
  private Token<DelegationTokenIdentifier> createTokenOnPeer()
      throws Exception {
    peer = new DelegationTokenManager(conf(), KIND);
    peer.init();
    return (Token<DelegationTokenIdentifier>) peer.createToken(
        UserGroupInformation.getCurrentUser(), "foo");
  }

  /**
   * A token cancelled by a peer while this instance is starting is put back
   * into this instance's memory by the startup load, so this instance keeps
   * accepting the cancelled token.
   */
  @Test
  public void testTokenCancelledDuringStartupStaysCancelled()
      throws Exception {
    Token<DelegationTokenIdentifier> token = createTokenOnPeer();
    DelegationTokenIdentifier id = new DelegationTokenIdentifier(KIND);
    id.readFields(new DataInputStream(
        new ByteArrayInputStream(token.getIdentifier())));
    int seq = id.getSequenceNumber();

    restarted = new PausingSecretManager(conf());
    restarted.startPausingAt(seq, () -> {
      try {
        peer.cancelToken(token,
            UserGroupInformation.getCurrentUser().getUserName());
        LOG.info("Peer cancelled token {}", seq);
        restarted.awaitCacheAndListener(seq, node -> !node.isPresent());
        LOG.info("This instance's cache and listener have seen the delete");
      } catch (Exception e) {
        throw new RuntimeException(e);
      }
    });
    assertTrue(restarted.paused(), "the startup load never reached the token");

    assertNull(restarted.getTokenInfoFromZK(id, true),
        "the token should be gone from ZooKeeper");
    boolean inMemory = restarted.getTokenInfoFromMemory(id) != null;
    boolean accepted;
    try {
      restarted.verifyToken(id, token.getPassword());
      accepted = true;
    } catch (InvalidToken e) {
      accepted = false;
    }
    LOG.info("After startup the cancelled token is in memory: {}; "
        + "verifyToken() accepts it: {}", inMemory, accepted);
    assertFalse(accepted, "this instance accepts a token cancelled while it"
        + " was starting (in memory: " + inMemory + ")");
    assertFalse(inMemory, "the cancelled token is back in memory");
  }

  /**
   * A token renewed by a peer while this instance is starting gets its old
   * renew date back from the startup load.
   */
  @Test
  public void testTokenRenewedDuringStartupKeepsNewRenewDate()
      throws Exception {
    Token<DelegationTokenIdentifier> token = createTokenOnPeer();
    DelegationTokenIdentifier id = new DelegationTokenIdentifier(KIND);
    id.readFields(new DataInputStream(
        new ByteArrayInputStream(token.getIdentifier())));
    int seq = id.getSequenceNumber();

    restarted = new PausingSecretManager(conf());
    restarted.startPausingAt(seq, () -> {
      try {
        int oldVersion = restarted.cachedTokenNode(seq).get()
            .getStat().getVersion();
        Thread.sleep(1100);
        peer.renewToken(token, "foo");
        LOG.info("Peer renewed token {}", seq);
        restarted.awaitCacheAndListener(seq, node -> node.isPresent()
            && node.get().getStat().getVersion() > oldVersion);
        LOG.info("This instance's cache and listener have seen the renewal");
      } catch (Exception e) {
        throw new RuntimeException(e);
      }
    });
    assertTrue(restarted.paused(), "the startup load never reached the token");

    DelegationTokenInformation inZk = restarted.getTokenInfoFromZK(id, true);
    DelegationTokenInformation inMemory = restarted.getTokenInfoFromMemory(id);
    LOG.info("renew date in ZooKeeper {}, in memory {}",
        inZk.getRenewDate(), inMemory.getRenewDate());
    assertEquals(inZk.getRenewDate(), inMemory.getRenewDate(),
        "the startup load restored the renew date from before the renewal");
  }
}
