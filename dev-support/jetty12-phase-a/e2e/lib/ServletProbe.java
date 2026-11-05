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

import java.io.IOException;
import java.lang.reflect.Method;
import java.net.URI;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.servlet.RequestDispatcher;
import javax.servlet.ServletContext;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.http.HttpServer2;

/**
 * R93 (T22) and R94 (T19): what a servlet sees at run time on one side's
 * classpath. Started as a single source file on that side's Hadoop classpath
 * ({@code java @args ServletProbe.java <port> [seconds]}), it serves a probe
 * servlet in an {@code HttpServer2} named "probe" (so {@code webapps/probe}
 * must be on the classpath) and answers as JSON.
 *
 * <p>Every Servlet 4.0 call goes through reflection: the source is compiled
 * against whichever servlet API comes first on the side's classpath, which
 * can be 3.1, and must compile and run on both sides. A missing class or
 * method is reported as the string "absent", never as a crash.
 */
public class ServletProbe {

  /** The first servlet, which reports what the context and request expose. */
  public static class ProbeServlet extends HttpServlet {
    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp)
        throws IOException, ServletException {
      String path = req.getPathInfo();
      if (path == null || path.isEmpty() || "/".equals(path)) {
        resp.setContentType("application/json");
        resp.getWriter().write(baseJson(req));
        return;
      }
      if ("/forward".equals(path)) {
        // A real forward: the target's response replaces this one, so the
        // forward mapping attribute is only visible in the target's answer.
        req.getRequestDispatcher("/target?mode=forward").forward(req, resp);
        return;
      }
      if ("/include".equals(path)) {
        // An include keeps this response; the target writes its answer into it.
        resp.setContentType("application/json");
        req.getRequestDispatcher("/target?mode=include").include(req, resp);
        return;
      }
      resp.sendError(HttpServletResponse.SC_NOT_FOUND);
    }
  }

  /** The second servlet, which reports the mapping attribute it was given. */
  public static class TargetServlet extends HttpServlet {
    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp)
        throws IOException {
      String mode = req.getParameter("mode");
      String attr = "forward".equals(mode)
          ? "javax.servlet.forward.mapping"
          : "javax.servlet.include.mapping";
      Object mapping = req.getAttribute(attr);
      resp.setContentType("application/json");
      resp.getWriter().write("{\"mode\":" + quote(mode == null ? "direct" : mode)
          + ",\"attribute\":" + quote(attr)
          + ",\"mapping\":" + mappingJson(mapping) + "}");
    }
  }

  /** The JSON answer for a GET on the probe servlet itself. */
  private static String baseJson(HttpServletRequest req) {
    ServletContext ctx = req.getServletContext();
    return "{\"servlet_api\":{\"major\":" + ctx.getMajorVersion()
        + ",\"minor\":" + ctx.getMinorVersion()
        + ",\"effective_major\":" + ctx.getEffectiveMajorVersion()
        + ",\"effective_minor\":" + ctx.getEffectiveMinorVersion() + "}"
        + ",\"http_servlet_jar\":" + quote(jarName(HttpServlet.class))
        + ",\"mapping\":" + mappingJson(reflect(req, HttpServletRequest.class,
            "getHttpServletMapping"))
        + ",\"new_push_builder\":" + pushBuilderJson(req) + "}";
  }

  /** "absent" when the method is missing, else "null" or "present". */
  private static String pushBuilderJson(HttpServletRequest req) {
    Object value = reflect(req, HttpServletRequest.class, "newPushBuilder");
    if ("absent".equals(value)) {
      return "\"absent\"";
    }
    return value == null ? "\"null\"" : "\"present\"";
  }

  /** A Servlet 4.0 HttpServletMapping as JSON, or "absent"/null. */
  private static String mappingJson(Object mapping) {
    if (mapping == null) {
      return "null";
    }
    if ("absent".equals(mapping)) {
      // reflect() reports a missing getHttpServletMapping() as this sentinel;
      // reflecting on the String would report every field as an error.
      return "\"absent\"";
    }
    Class<?> iface;
    try {
      iface = Class.forName("javax.servlet.http.HttpServletMapping");
    } catch (ClassNotFoundException e) {
      return "\"absent\"";
    }
    return "{\"match_value\":" + jsonValue(reflect(mapping, iface, "getMatchValue"))
        + ",\"pattern\":" + jsonValue(reflect(mapping, iface, "getPattern"))
        + ",\"servlet_name\":" + jsonValue(reflect(mapping, iface, "getServletName"))
        + ",\"match\":" + jsonValue(reflect(mapping, iface, "getMappingMatch")) + "}";
  }

  /**
   * Invoke a public method through its declaring interface, so a non-public
   * implementation class does not hide it. A missing method is "absent".
   */
  private static Object reflect(Object target, Class<?> iface, String name) {
    if (target == null) {
      return "absent";
    }
    try {
      Method method = iface.getMethod(name);
      return method.invoke(target);
    } catch (NoSuchMethodException e) {
      return "absent";
    } catch (Exception e) {
      return "error:" + e.getClass().getSimpleName();
    }
  }

  /** JSON scalar: booleans and numbers bare, everything else quoted. */
  private static String jsonValue(Object value) {
    if (value == null) {
      return "null";
    }
    if (value instanceof Boolean || value instanceof Number) {
      return String.valueOf(value);
    }
    return quote(String.valueOf(value));
  }

  /** A JSON string, with the characters a JSON parser treats specially. */
  private static String quote(String value) {
    StringBuilder out = new StringBuilder("\"");
    for (int i = 0; i < value.length(); i++) {
      char c = value.charAt(i);
      switch (c) {
        case '"': out.append("\\\""); break;
        case '\\': out.append("\\\\"); break;
        case '\n': out.append("\\n"); break;
        case '\r': out.append("\\r"); break;
        case '\t': out.append("\\t"); break;
        default:
          if (c < 0x20) {
            out.append(String.format("\\u%04x", (int) c));
          } else {
            out.append(c);
          }
      }
    }
    return out.append('"').toString();
  }

  /** The jar or directory HttpServlet came from, by file name only. */
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

  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("usage: ServletProbe <port> [seconds]");
      System.exit(2);
    }
    int port = Integer.parseInt(args[0]);
    int seconds = args.length > 1 ? Integer.parseInt(args[1]) : 120;

    // HttpServer2 finds its web application at webapps/<name> on the
    // classpath; the scenario and the local runs put webapps/probe there.
    HttpServer2 server = new HttpServer2.Builder()
        .setName("probe")
        .addEndpoint(new URI("http://127.0.0.1:" + port))
        .setConf(new Configuration())
        .build();
    server.addServlet("probe", "/probe/*", ProbeServlet.class);
    server.addServlet("target", "/target", TargetServlet.class);
    server.start();
    System.out.println("READY " + server.getConnectorAddress(0).getPort());
    System.out.flush();

    AtomicBoolean stopped = new AtomicBoolean(false);
    Runnable stop = () -> {
      if (stopped.compareAndSet(false, true)) {
        try {
          server.stop();
        } catch (Exception e) {
          // The server is already stopping; nothing to do.
        }
      }
    };
    Runtime.getRuntime().addShutdownHook(new Thread(stop));
    Thread.sleep(seconds * 1000L);
    stop.run();
  }
}
