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

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.curator.framework.recipes.cache.CuratorCacheBridge;
import org.apache.curator.test.TestingServer;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.security.token.SecretManager.InvalidToken;
import org.apache.hadoop.security.token.Token;
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
 * Tokens that a peer cancels while this instance is starting must not be
 * accepted by this instance once everything has settled.
 * <p>
 * The test does not pause at any particular point of startThreads(): a peer
 * cancels every token while this instance starts, and the test checks the
 * end state. The only timing aid is that the thread running startThreads()
 * sleeps 2 ms whenever it applies a token itself, which widens any window in
 * which the starting thread applies a token concurrently with the cache
 * listener. The same test runs unchanged against any version of the class.
 */
@Timeout(180)
public class TestZKDelegationTokenSecretManagerCancelDuringStartup {

  private static final Logger LOG = LoggerFactory.getLogger(
      TestZKDelegationTokenSecretManagerCancelDuringStartup.class);
  private static final long DAY_IN_SECS = 86400;
  private static final Text KIND = new Text("bla");
  private static final String STARTER = "starter";
  private static final int TOKENS = 300;

  private TestingServer zkServer;
  private DelegationTokenManager peer;
  private SlowStartSecretManager restarted;

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
    conf.setLong(DelegationTokenManager.RENEW_INTERVAL, DAY_IN_SECS);
    conf.setLong(DelegationTokenManager.REMOVAL_SCAN_INTERVAL, DAY_IN_SECS);
    return conf;
  }

  /** Slows down the thread running startThreads() when it applies a token. */
  private static class SlowStartSecretManager
      extends ZKDelegationTokenSecretManager<DelegationTokenIdentifier> {

    final AtomicInteger appliedByStarter = new AtomicInteger();

    SlowStartSecretManager(Configuration conf) {
      super(conf);
    }

    @Override
    public DelegationTokenIdentifier createIdentifier() {
      return new DelegationTokenIdentifier(KIND);
    }

    @Override
    protected DelegationTokenIdentifier processTokenAddOrUpdate(byte[] data)
        throws IOException {
      if (STARTER.equals(Thread.currentThread().getName())) {
        appliedByStarter.incrementAndGet();
        try {
          Thread.sleep(2);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
      return super.processTokenAddOrUpdate(data);
    }

    long tokensInCache() throws Exception {
      Field f = ZKDelegationTokenSecretManager.class
          .getDeclaredField("tokenCache");
      f.setAccessible(true);
      CuratorCacheBridge cache = (CuratorCacheBridge) f.get(this);
      return cache.stream()
          .filter(c -> !ZK_DTSM_TOKENS_ROOT.equals(c.getPath())).count();
    }
  }

  @SuppressWarnings("unchecked")
  @Test
  public void testTokensCancelledDuringStartupAreNotAccepted()
      throws Exception {
    peer = new DelegationTokenManager(conf(), KIND);
    peer.init();
    List<Token<DelegationTokenIdentifier>> tokens = new ArrayList<>();
    for (int i = 0; i < TOKENS; i++) {
      tokens.add((Token<DelegationTokenIdentifier>) peer.createToken(
          UserGroupInformation.getCurrentUser(), "foo"));
    }
    String owner = UserGroupInformation.getCurrentUser().getUserName();

    restarted = new SlowStartSecretManager(conf());
    CountDownLatch go = new CountDownLatch(1);
    AtomicReference<Throwable> failure = new AtomicReference<>();
    Thread starter = new Thread(() -> {
      try {
        go.await();
        restarted.startThreads();
      } catch (Throwable t) {
        failure.set(t);
      }
    }, STARTER);
    Thread canceller = new Thread(() -> {
      try {
        go.await();
        for (Token<DelegationTokenIdentifier> t : tokens) {
          peer.cancelToken(t, owner);
        }
      } catch (Throwable t) {
        failure.set(t);
      }
    }, "canceller");
    starter.start();
    canceller.start();
    go.countDown();
    starter.join();
    canceller.join();
    if (failure.get() != null) {
      throw new AssertionError(failure.get());
    }

    // Let this instance catch up: its cache shows every delete, and the
    // listener calls queued so far have run (Curator runs listeners and
    // runSafe() tasks in order on one thread).
    GenericTestUtils.waitFor(() -> {
      try {
        return restarted.tokensInCache() == 0;
      } catch (Exception e) {
        throw new RuntimeException(e);
      }
    }, 10, 30000);
    restarted.zkClient.runSafe(() -> { }).get();

    int inMemory = 0;
    int accepted = 0;
    for (Token<DelegationTokenIdentifier> t : tokens) {
      DelegationTokenIdentifier id = new DelegationTokenIdentifier(KIND);
      id.readFields(new DataInputStream(
          new ByteArrayInputStream(t.getIdentifier())));
      if (restarted.getTokenInfoFromMemory(id) != null) {
        inMemory++;
      }
      try {
        restarted.verifyToken(id, t.getPassword());
        accepted++;
      } catch (InvalidToken e) {
        // expected: the token was cancelled
      }
    }
    LOG.info("{} tokens cancelled during startup; the starting thread applied"
        + " {} tokens itself; afterwards {} are still in memory and {} are"
        + " accepted by verifyToken()", TOKENS,
        restarted.appliedByStarter.get(), inMemory, accepted);
    assertEquals(0, accepted, accepted + " of " + TOKENS
        + " cancelled tokens are still accepted by the restarted instance");
    assertEquals(0, inMemory, inMemory + " of " + TOKENS
        + " cancelled tokens are still in the restarted instance's memory");
  }
}
