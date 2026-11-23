/*
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

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.util.Collections;
import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ServletContext;
import javax.servlet.ServletException;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.http.HttpServer2;
import org.apache.hadoop.shaded.javax.ws.rs.GET;
import org.apache.hadoop.shaded.javax.ws.rs.Path;
import org.apache.hadoop.shaded.javax.ws.rs.core.Application;
import org.apache.hadoop.shaded.javax.ws.rs.core.Response;
import org.apache.hadoop.shaded.org.glassfish.jersey.server.ResourceConfig;
import org.apache.hadoop.shaded.org.glassfish.jersey.test.JerseyTest;
import org.apache.hadoop.yarn.server.MiniYARNCluster;

/**
 * T26: one small program a downstream project's classpath can compile and run.
 *
 * <p>Started as {@code java DownstreamSmoke <step>}, it runs one step and
 * prints {@code ok<TAB>servlet version<TAB>ServletContext jar<TAB>detail} or
 * {@code fail<TAB><TAB><TAB>reason}. downstream-deps.sh runs only the steps a
 * project's classpath supports and records the answer in smoke.tsv.
 *
 * <p>The source is compiled against the side's distribution, which has every
 * class it names, and run against the project's classpath: a step whose
 * classes are absent is never started.
 */
public class DownstreamSmoke {

  /** A servlet that reports the servlet version and where ServletContext came from. */
  public static class SmokeServlet extends HttpServlet {
    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp)
        throws IOException {
      ServletContext ctx = req.getServletContext();
      resp.setContentType("text/plain");
      resp.getWriter().write(ctx.getMajorVersion() + "." + ctx.getMinorVersion()
          + "\t" + jarName(ServletContext.class));
    }
  }

  /** The one filter the server needs, so the filter path is exercised too. */
  public static class SmokeFilter implements Filter {
    @Override
    public void init(FilterConfig config) {
    }

    @Override
    public void doFilter(ServletRequest req, ServletResponse resp, FilterChain chain)
        throws IOException, ServletException {
      chain.doFilter(req, resp);
    }

    @Override
    public void destroy() {
    }
  }

  /** One JerseyTest on the shaded client jars. */
  public static class SmokeJerseyTest extends JerseyTest {
    @Path("smoke")
    public static class Resource {
      @GET
      public String get() {
        return "ok";
      }
    }

    @Override
    protected Application configure() {
      return new ResourceConfig(Resource.class);
    }
  }

  /** Start an HttpServer2 with one filter and one servlet, and request it. */
  private static String[] httpserver2() throws Exception {
    HttpServer2 server = new HttpServer2.Builder()
        .setName("smoke")
        .addEndpoint(new URI("http://127.0.0.1:0"))
        .setConf(new Configuration())
        .build();
    server.addServlet("smoke", "/smoke", SmokeServlet.class);
    server.addFilter("smoke-filter", SmokeFilter.class.getName(), Collections.emptyMap());
    server.start();
    try {
      int port = server.getConnectorAddress(0).getPort();
      HttpURLConnection c = (HttpURLConnection)
          new URL("http://127.0.0.1:" + port + "/smoke").openConnection();
      c.setConnectTimeout(10000);
      c.setReadTimeout(10000);
      StringBuilder body = new StringBuilder();
      try (BufferedReader r = new BufferedReader(
          new InputStreamReader(c.getInputStream(), "UTF-8"))) {
        String line;
        while ((line = r.readLine()) != null) {
          body.append(line);
        }
      }
      String[] parts = body.toString().split("\t", -1);
      return new String[] {parts[0], parts.length > 1 ? parts[1] : "", ""};
    } finally {
      server.stop();
    }
  }

  /** Start and stop a MiniDFSCluster and a MiniYARNCluster. */
  private static String[] minicluster() throws Exception {
    Configuration conf = new Configuration();
    MiniDFSCluster dfs = new MiniDFSCluster.Builder(conf).numDataNodes(1).build();
    MiniYARNCluster yarn = new MiniYARNCluster("smoke", 1, 1, 1);
    try {
      yarn.init(conf);
      yarn.start();
    } finally {
      try {
        yarn.stop();
      } catch (Exception e) {
        // The cluster is already stopping; nothing to do.
      }
      dfs.shutdown();
    }
    return new String[] {"", "", ""};
  }

  /** Run one JerseyTest on the shaded client jars. */
  private static String[] jerseytest() throws Exception {
    SmokeJerseyTest test = new SmokeJerseyTest();
    test.setUp();
    try {
      Response r = test.target("smoke").request().get();
      String body = r.readEntity(String.class);
      if (!"ok".equals(body)) {
        throw new IllegalStateException("body " + body);
      }
    } finally {
      test.tearDown();
    }
    return new String[] {"", "", ""};
  }

  /** The jar or directory a class came from, by file name only. */
  private static String jarName(Class<?> clazz) {
    try {
      java.security.CodeSource cs = clazz.getProtectionDomain().getCodeSource();
      if (cs == null || cs.getLocation() == null) {
        return "unknown";
      }
      String path = cs.getLocation().getPath();
      int slash = path.lastIndexOf('/');
      return slash >= 0 ? path.substring(slash + 1) : path;
    } catch (Exception e) {
      return "unknown";
    }
  }

  public static void main(String[] args) {
    String step = args.length > 0 ? args[0] : "";
    try {
      String[] result;
      if ("httpserver2".equals(step)) {
        result = httpserver2();
      } else if ("minicluster".equals(step)) {
        result = minicluster();
      } else if ("jerseytest".equals(step)) {
        result = jerseytest();
      } else {
        throw new IllegalArgumentException("unknown step: " + step);
      }
      System.out.println("ok\t" + result[0] + "\t" + result[1] + "\t" + result[2]);
    } catch (Throwable t) {
      String msg = t.getClass().getSimpleName() + ": " + String.valueOf(t.getMessage());
      System.out.println("fail\t\t\t" + msg.replace('\t', ' ').replace('\n', ' '));
      System.exit(1);
    }
  }
}
