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
package org.apache.hadoop.http;

import java.util.concurrent.TimeUnit;

import org.eclipse.jetty.server.handler.StatisticsHandler;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Jetty 9.4's StatisticsHandler recorded request and dispatch times in
 * milliseconds and Jetty 12's records them in nanoseconds. The metrics keep
 * the names and the "(in ms)" descriptions they always had, so every time
 * metric has to be converted on the way out.
 */
public class TestHttpServer2Metrics {

  private static final long MILLIS = 1234;
  private static final long NANOS = TimeUnit.MILLISECONDS.toNanos(MILLIS);

  @Test
  public void testTimesArePublishedInMilliseconds() {
    StatisticsHandler handler = mock(StatisticsHandler.class);
    when(handler.getRequestTimeMax()).thenReturn(NANOS);
    when(handler.getRequestTimeTotal()).thenReturn(NANOS);
    when(handler.getRequestTimeMean()).thenReturn((double) NANOS);
    when(handler.getRequestTimeStdDev()).thenReturn((double) NANOS);
    when(handler.getHandleTimeMax()).thenReturn(NANOS);
    when(handler.getHandleTimeTotal()).thenReturn(NANOS);
    when(handler.getHandleTimeMean()).thenReturn((double) NANOS);
    when(handler.getHandleTimeStdDev()).thenReturn((double) NANOS);

    HttpServer2Metrics metrics = new HttpServer2Metrics(handler, 0, null, 0, 0);

    assertThat(metrics.requestTimeMax()).isEqualTo(MILLIS);
    assertThat(metrics.requestTimeTotal()).isEqualTo(MILLIS);
    assertThat(metrics.requestTimeMean()).isCloseTo(MILLIS, within(1e-9));
    assertThat(metrics.requestTimeStdDev()).isCloseTo(MILLIS, within(1e-9));
    assertThat(metrics.dispatchedTimeMax()).isEqualTo(MILLIS);
    assertThat(metrics.dispatchedTimeTotal()).isEqualTo(MILLIS);
    assertThat(metrics.dispatchedTimeMean()).isCloseTo(MILLIS, within(1e-9));
    assertThat(metrics.dispatchedTimeStdDev()).isCloseTo(MILLIS, within(1e-9));
  }

  @Test
  public void testFractionalMillisecondsAreKeptForMeanAndStdDev() {
    StatisticsHandler handler = mock(StatisticsHandler.class);
    when(handler.getRequestTimeMean()).thenReturn(1_500_000.0);
    when(handler.getHandleTimeStdDev()).thenReturn(250_000.0);

    HttpServer2Metrics metrics = new HttpServer2Metrics(handler, 0, null, 0, 0);

    assertThat(metrics.requestTimeMean()).isCloseTo(1.5, within(1e-9));
    assertThat(metrics.dispatchedTimeStdDev()).isCloseTo(0.25, within(1e-9));
  }
}
