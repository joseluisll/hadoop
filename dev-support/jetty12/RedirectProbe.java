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

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

import org.apache.hadoop.conf.Configuration;

/**
 * Focused probe for what reaches the wire when a servlet redirects. Hadoop
 * redirects through {@link HttpServletResponse#sendRedirect} in the YARN
 * proxy, AmIpFilter, the JWT login handler and WebServlet, so the shape of
 * the Location header is part of its contract with clients.
 */
public final class RedirectProbe {

  private static int port;

  private RedirectProbe() {
  }

  /** Redirects the way Hadoop's own code does. */
  public static class RedirectServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      String info = req.getPathInfo() == null ? "/" : req.getPathInfo();
      if (info.startsWith("/abs")) {
        // A context-absolute path: what ProxyUtils and Dispatcher pass.
        res.sendRedirect("/target/page");
      } else if (info.startsWith("/rel")) {
        res.sendRedirect("relative/page");
      } else if (info.startsWith("/full")) {
        res.sendRedirect("http://example.org:8088/target/page");
      } else if (info.startsWith("/query")) {
        res.sendRedirect("/target/page?a=b&c=d");
      } else if (info.startsWith("/encoded")) {
        res.sendRedirect("/target/a%20b/c%25d");
      } else if (info.startsWith("/dotdot")) {
        res.sendRedirect("/target/../climbed");
      } else {
        res.sendError(404);
      }
    }
  }

  public static void main(String[] args) throws Exception {
    Configuration conf = new Configuration();
    HttpServer2 server = new HttpServer2.Builder().setName("test")
        .addEndpoint(URI.create("http://localhost:0"))
        .setFindPort(true).setConf(conf).build();
    server.addServlet("redir", "/redir/*", RedirectServlet.class);
    server.start();
    port = server.getConnectorAddress(0).getPort();
    try {
      for (String p : new String[] {"abs", "rel", "full", "query", "encoded",
          "dotdot"}) {
        probe(p, "GET /redir/" + p + " HTTP/1.1\r\nHost: localhost:" + port
            + "\r\nConnection: close\r\n\r\n");
      }
      // The container's own redirects, for comparison.
      probe("context-no-slash", "GET /static HTTP/1.1\r\nHost: localhost:"
          + port + "\r\nConnection: close\r\n\r\n");
      probe("proxied-host", "GET /redir/abs HTTP/1.1\r\nHost: proxy.example:80"
          + "\r\nX-Forwarded-Host: outer.example\r\nConnection: close\r\n\r\n");
    } finally {
      server.stop();
    }
  }

  private static void probe(String name, String request) {
    System.out.println("=== REDIRECT " + name);
    Socket s = null;
    try {
      s = new Socket();
      s.connect(new InetSocketAddress("localhost", port), 5000);
      s.setSoTimeout(5000);
      s.getOutputStream().write(request.getBytes(StandardCharsets.ISO_8859_1));
      s.getOutputStream().flush();
      ByteArrayOutputStream bos = new ByteArrayOutputStream();
      byte[] buf = new byte[4096];
      InputStream in = s.getInputStream();
      int n;
      try {
        while ((n = in.read(buf)) > 0) {
          bos.write(buf, 0, n);
        }
      } catch (IOException e) {
        // report what arrived
      }
      String text = new String(bos.toByteArray(), StandardCharsets.ISO_8859_1);
      for (String line : text.split("\r\n")) {
        if (line.isEmpty()) {
          break;
        }
        if (line.startsWith("HTTP/") || line.toLowerCase().startsWith(
            "location:") || line.toLowerCase().startsWith("content-length:")) {
          System.out.println("  " + line.replace(":" + port, ":{PORT}"));
        }
      }
    } catch (Exception e) {
      System.out.println("  EXCEPTION " + e);
    } finally {
      if (s != null) {
        try {
          s.close();
        } catch (IOException ignored) {
          // nothing to do
        }
      }
    }
  }
}
