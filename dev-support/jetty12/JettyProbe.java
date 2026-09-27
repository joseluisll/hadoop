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
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.TreeSet;

import javax.servlet.http.Cookie;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

import org.apache.hadoop.conf.Configuration;

/**
 * A behaviour probe for the container behind {@link HttpServer2}. Starts one
 * server, sends a fixed list of raw HTTP requests, and prints a normalised
 * report. Run it on two commits and diff the reports: every difference is a
 * behaviour change the container imposed.
 *
 * Not a test. It asserts nothing; it only records what the server did.
 */
public final class JettyProbe {

  private static int port;
  private static final int TIMEOUT_MS = 8000;

  private JettyProbe() {
  }

  /** Reports how the container decoded the request. */
  public static class EchoServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      res.setContentType("text/plain; charset=utf-8");
      PrintWriter w = res.getWriter();
      w.println("method=" + req.getMethod());
      w.println("protocol=" + req.getProtocol());
      w.println("scheme=" + req.getScheme());
      w.println("requestURI=" + esc(req.getRequestURI()));
      w.println("requestURL=" + esc(String.valueOf(req.getRequestURL())));
      w.println("contextPath=" + esc(req.getContextPath()));
      w.println("servletPath=" + esc(req.getServletPath()));
      w.println("pathInfo=" + esc(req.getPathInfo()));
      w.println("pathTranslated=" + (req.getPathTranslated() == null
          ? "null" : "non-null"));
      w.println("queryString=" + esc(req.getQueryString()));
      w.println("serverName=" + esc(req.getServerName()));
      w.println("serverPort=" + req.getServerPort());
      w.println("isSecure=" + req.isSecure());
      w.println("charEncoding=" + req.getCharacterEncoding());
      w.println("contentType=" + esc(req.getContentType()));
      w.println("contentLength=" + req.getContentLength());
      w.println("requestedSessionId=" + (req.getRequestedSessionId() == null
          ? "null" : "present"));
      // Parameters, name-sorted so the report is stable.
      TreeSet<String> names = new TreeSet<String>();
      Enumeration<String> pn = req.getParameterNames();
      while (pn != null && pn.hasMoreElements()) {
        names.add(pn.nextElement());
      }
      for (String n : names) {
        String[] vals = req.getParameterValues(n);
        List<String> escaped = new ArrayList<String>();
        for (String v : vals) {
          escaped.add(esc(v));
        }
        w.println("param[" + esc(n) + "]=" + escaped);
      }
      // A few headers that reveal parsing choices.
      for (String h : new String[] {"Host", "X-Foo", "Cookie", "Expect",
          "Transfer-Encoding", "Content-Length"}) {
        List<String> vals = new ArrayList<String>();
        Enumeration<String> hv = req.getHeaders(h);
        while (hv != null && hv.hasMoreElements()) {
          vals.add(esc(hv.nextElement()));
        }
        if (!vals.isEmpty()) {
          w.println("header[" + h + "]=" + vals);
        }
      }
      Cookie[] cookies = req.getCookies();
      if (cookies != null) {
        List<String> cs = new ArrayList<String>();
        for (Cookie c : cookies) {
          cs.add(esc(c.getName()) + "=" + esc(c.getValue()));
        }
        Collections.sort(cs);
        w.println("cookies=" + cs);
      }
      // Body, so chunked/Expect handling is visible.
      byte[] body = readAll(req.getInputStream());
      w.println("bodyLen=" + body.length);
      if (body.length > 0 && body.length <= 200) {
        w.println("body=" + esc(new String(body, StandardCharsets.UTF_8)));
      }
    }
  }

  /** sendError with a message, to show what reaches the wire per method. */
  public static class ErrorServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      String info = req.getPathInfo() == null ? "/500" : req.getPathInfo();
      int code = 500;
      try {
        code = Integer.parseInt(info.replace("/", ""));
      } catch (NumberFormatException ignored) {
        // keep 500
      }
      res.sendError(code, "probe-detail-for-" + code);
    }
  }

  /** setStatus(int, String): does a custom reason phrase survive? */
  public static class ReasonServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @SuppressWarnings("deprecation")
    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      res.setStatus(400, "probe-custom-reason");
      res.getWriter().println("reason-body");
    }
  }

  /** Cookie round-trip, including values a strict parser may reject. */
  public static class CookieServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      res.addCookie(new Cookie("plain", "value1"));
      try {
        Cookie c = new Cookie("spaced", "has space");
        res.addCookie(c);
        res.getWriter().println("spaced=added");
      } catch (RuntimeException e) {
        res.getWriter().println("spaced=rejected:" + e.getClass().getName());
      }
      try {
        Cookie c = new Cookie("commaed", "a,b");
        res.addCookie(c);
        res.getWriter().println("commaed=added");
      } catch (RuntimeException e) {
        res.getWriter().println("commaed=rejected:" + e.getClass().getName());
      }
      // Raw header: what Hadoop's AuthenticationFilter does for hadoop.auth.
      res.addHeader("Set-Cookie",
          "hadoop.auth=\"u=bob&p=bob&t=simple&e=123&s=sig\"; Path=/; HttpOnly");
    }
  }

  /** Flushes before erroring, to show committed-response handling. */
  public static class CommittedErrorServlet extends HttpServlet {
    private static final long serialVersionUID = 1L;

    @Override
    protected void service(HttpServletRequest req, HttpServletResponse res)
        throws IOException {
      res.setStatus(200);
      res.getWriter().println("first-part");
      res.flushBuffer();
      try {
        res.sendError(500, "after-commit");
        res.getWriter().println("no-exception");
      } catch (RuntimeException e) {
        // Recorded in the body; it is already committed so status cannot move.
        res.getWriter().println("sendError threw " + e.getClass().getName());
      }
    }
  }

  public static void main(String[] args) throws Exception {
    File logDir = Files.createTempDirectory("probe-logs").toFile();
    Files.write(new File(logDir, "probe.log").toPath(),
        "log-line\n".getBytes(StandardCharsets.UTF_8));
    System.setProperty("hadoop.log.dir", logDir.getAbsolutePath());

    Configuration conf = new Configuration();
    conf.setBoolean(CommonConfigurationKeysPublicShim.LOGS_ENABLED, true);

    HttpServer2 server = new HttpServer2.Builder().setName("test")
        .addEndpoint(URI.create("http://localhost:0"))
        .setFindPort(true).setConf(conf).build();
    server.addServlet("echo", "/echo/*", EchoServlet.class);
    server.addServlet("err", "/err/*", ErrorServlet.class);
    server.addServlet("reason", "/reason/*", ReasonServlet.class);
    server.addServlet("cookie", "/cookie/*", CookieServlet.class);
    server.addServlet("committed", "/committed/*", CommittedErrorServlet.class);
    server.start();
    port = server.getConnectorAddress(0).getPort();

    try {
      runProbes();
    } finally {
      server.stop();
    }
  }

  private static void runProbes() throws Exception {
    String h = "Host: localhost:" + port + "\r\n";

    // --- Path and URI handling -------------------------------------------
    probe("plain-get", "GET /echo/a HTTP/1.1\r\n" + h);
    probe("query", "GET /echo/a/b?x=1&y=2 HTTP/1.1\r\n" + h);
    probe("empty-segment", "GET /echo//a//b HTTP/1.1\r\n" + h);
    probe("trailing-slash", "GET /echo/a/ HTTP/1.1\r\n" + h);
    probe("encoded-percent", "GET /echo/a%25b HTTP/1.1\r\n" + h);
    probe("encoded-backslash", "GET /echo/a%5Cb HTTP/1.1\r\n" + h);
    probe("encoded-slash", "GET /echo/a%2Fb HTTP/1.1\r\n" + h);
    probe("double-encoded-slash", "GET /echo/a%252Fb HTTP/1.1\r\n" + h);
    probe("encoded-dotdot", "GET /echo/a%2E%2E%2Fb HTTP/1.1\r\n" + h);
    probe("literal-dotdot", "GET /echo/a/../b HTTP/1.1\r\n" + h);
    probe("escape-context", "GET /echo/../../etc/passwd HTTP/1.1\r\n" + h);
    probe("encoded-nul", "GET /echo/a%00b HTTP/1.1\r\n" + h);
    probe("encoded-tab", "GET /echo/a%09b HTTP/1.1\r\n" + h);
    probe("encoded-newline", "GET /echo/a%0Ab HTTP/1.1\r\n" + h);
    probe("encoded-del", "GET /echo/a%7Fb HTTP/1.1\r\n" + h);
    probe("encoded-semicolon", "GET /echo/a%3Bb HTTP/1.1\r\n" + h);
    probe("bad-percent-hex", "GET /echo/a%zzb HTTP/1.1\r\n" + h);
    probe("bare-percent", "GET /echo/a% HTTP/1.1\r\n" + h);
    probe("path-params", "GET /echo/a;p=1/b;q=2 HTTP/1.1\r\n" + h);
    probe("jsessionid-path", "GET /echo/a;jsessionid=NODE1 HTTP/1.1\r\n" + h);
    probe("plus-in-path", "GET /echo/a+b HTTP/1.1\r\n" + h);
    probe("utf8-encoded-path", "GET /echo/%E2%82%AC HTTP/1.1\r\n" + h);
    probe("utf8-overlong", "GET /echo/%C0%AF HTTP/1.1\r\n" + h);
    probe("query-semicolon", "GET /echo/a?x=1;y=2 HTTP/1.1\r\n" + h);
    probe("query-bad-utf8", "GET /echo/a?x=%FF%FE HTTP/1.1\r\n" + h);
    probe("query-plus", "GET /echo/a?x=a+b HTTP/1.1\r\n" + h);
    probe("query-no-value", "GET /echo/a?flag HTTP/1.1\r\n" + h);
    probe("query-encoded-amp", "GET /echo/a?x=1%26y=2 HTTP/1.1\r\n" + h);
    probe("long-url", "GET /echo/" + repeat("z", 8000) + " HTTP/1.1\r\n" + h);

    // --- Request line and version ---------------------------------------
    probe("no-host-1.1", "GET /echo/a HTTP/1.1\r\n");
    probe("dup-host", "GET /echo/a HTTP/1.1\r\n" + h + "Host: other:1\r\n");
    probe("absolute-form",
        "GET http://localhost:" + port + "/echo/a HTTP/1.1\r\n" + h);
    probe("options-star", "OPTIONS * HTTP/1.1\r\n" + h);
    probe("options-path", "OPTIONS /echo/a HTTP/1.1\r\n" + h);
    probe("trace", "TRACE /echo/a HTTP/1.1\r\n" + h);
    probe("unknown-method", "PROBE /echo/a HTTP/1.1\r\n" + h);
    probe("http10", "GET /echo/a HTTP/1.0\r\n");
    probe("http09-noversion", "GET /echo/a\r\n");
    probe("bad-version", "GET /echo/a HTTP/9.9\r\n" + h);
    probe("lowercase-method", "get /echo/a HTTP/1.1\r\n" + h);

    // --- Headers ---------------------------------------------------------
    probe("obs-fold",
        "GET /echo/a HTTP/1.1\r\n" + h + "X-Foo: one\r\n  two\r\n");
    probe("space-before-colon", "GET /echo/a HTTP/1.1\r\n" + h + "X-Foo : v\r\n");
    probe("no-colon", "GET /echo/a HTTP/1.1\r\n" + h + "X-Foo\r\n");
    probe("huge-header",
        "GET /echo/a HTTP/1.1\r\n" + h + "X-Foo: " + repeat("v", 16000)
            + "\r\n");
    probe("many-headers", "GET /echo/a HTTP/1.1\r\n" + h
        + repeat("X-Pad: p\r\n", 300));
    probe("cookie-parsing", "GET /echo/a HTTP/1.1\r\n" + h
        + "Cookie: a=1; b=\"quoted\"; c=plain\r\n");
    probe("cookie-version", "GET /echo/a HTTP/1.1\r\n" + h
        + "Cookie: $Version=1; a=1; $Path=/x\r\n");
    probe("cookie-hadoop-auth", "GET /echo/a HTTP/1.1\r\n" + h
        + "Cookie: hadoop.auth=\"u=bob&p=bob&t=simple&e=1&s=sig\"\r\n");

    // --- Bodies ----------------------------------------------------------
    probe("post-form", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Type: application/x-www-form-urlencoded\r\n"
        + "Content-Length: 11\r\n\r\nfoo=bar&x=1");
    probe("post-chunked", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Type: text/plain\r\n"
        + "Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n");
    probe("post-chunked-trailer", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Type: text/plain\r\n"
        + "Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\nX-T: 1\r\n\r\n");
    probe("expect-continue", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Type: text/plain\r\n"
        + "Expect: 100-continue\r\nContent-Length: 5\r\n\r\nhello");
    probe("cl-and-te", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Length: 5\r\nTransfer-Encoding: chunked\r\n\r\n"
        + "0\r\n\r\n");
    probe("negative-cl", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Length: -1\r\n\r\n");
    probe("dup-cl", "POST /echo/a HTTP/1.1\r\n" + h
        + "Content-Length: 5\r\nContent-Length: 6\r\n\r\nhello");

    // --- Errors and reasons ---------------------------------------------
    probe("err-404-get", "GET /err/404 HTTP/1.1\r\n" + h);
    probe("err-404-post", "POST /err/404 HTTP/1.1\r\n" + h
        + "Content-Length: 0\r\n");
    probe("err-404-head", "HEAD /err/404 HTTP/1.1\r\n" + h);
    probe("err-404-put", "PUT /err/404 HTTP/1.1\r\n" + h
        + "Content-Length: 0\r\n");
    probe("err-404-delete", "DELETE /err/404 HTTP/1.1\r\n" + h);
    probe("err-403-get", "GET /err/403 HTTP/1.1\r\n" + h);
    probe("err-500-get", "GET /err/500 HTTP/1.1\r\n" + h);
    probe("custom-reason", "GET /reason/x HTTP/1.1\r\n" + h);
    probe("committed-error", "GET /committed/x HTTP/1.1\r\n" + h);
    probe("no-such-servlet", "GET /nothing-here HTTP/1.1\r\n" + h);
    probe("no-such-context", "GET /nope/deep/path HTTP/1.1\r\n" + h);
    probe("method-not-allowed-static",
        "PUT /static/test.css HTTP/1.1\r\n" + h + "Content-Length: 0\r\n");

    // --- Cookies out -----------------------------------------------------
    probe("cookie-out", "GET /cookie/x HTTP/1.1\r\n" + h);

    // --- Static content --------------------------------------------------
    probe("static-file", "GET /static/test.css HTTP/1.1\r\n" + h);
    probe("static-dir", "GET /static/ HTTP/1.1\r\n" + h);
    probe("static-no-slash", "GET /static HTTP/1.1\r\n" + h);
    probe("static-missing", "GET /static/nope.css HTTP/1.1\r\n" + h);
    probe("static-escape", "GET /static/../web.xml HTTP/1.1\r\n" + h);
    probe("static-head", "HEAD /static/test.css HTTP/1.1\r\n" + h);
    probe("static-range", "GET /static/test.css HTTP/1.1\r\n" + h
        + "Range: bytes=0-3\r\n");
    probe("static-bad-range", "GET /static/test.css HTTP/1.1\r\n" + h
        + "Range: bytes=99999-100000\r\n");
    probe("static-ims-future", "GET /static/test.css HTTP/1.1\r\n" + h
        + "If-Modified-Since: Thu, 01 Jan 2099 00:00:00 GMT\r\n");
    probe("static-gzip-accept", "GET /static/test.css HTTP/1.1\r\n" + h
        + "Accept-Encoding: gzip\r\n");
    probe("static-options", "OPTIONS /static/test.css HTTP/1.1\r\n" + h);

    // --- Logs ------------------------------------------------------------
    probe("logs-dir", "GET /logs/ HTTP/1.1\r\n" + h);
    probe("logs-file", "GET /logs/probe.log HTTP/1.1\r\n" + h);
    probe("logs-missing", "GET /logs/nope.log HTTP/1.1\r\n" + h);
    probe("logs-post", "POST /logs/ HTTP/1.1\r\n" + h + "Content-Length: 0\r\n");
    probe("logs-escape", "GET /logs/../static/test.css HTTP/1.1\r\n" + h);

    // --- Built-in servlets ----------------------------------------------
    probe("conf", "GET /conf HTTP/1.1\r\n" + h);
    probe("jmx", "GET /jmx?qry=java.lang:type=Memory HTTP/1.1\r\n" + h);
    probe("stacks", "GET /stacks HTTP/1.1\r\n" + h);
    probe("loglevel", "GET /logLevel HTTP/1.1\r\n" + h);
    probe("metrics", "GET /metrics HTTP/1.1\r\n" + h);

    // --- Connection handling --------------------------------------------
    keepAliveProbe();
  }

  /** Two requests on one connection: is the connection reused? */
  private static void keepAliveProbe() {
    StringBuilder out = new StringBuilder();
    Socket s = null;
    try {
      s = new Socket();
      s.connect(new InetSocketAddress("localhost", port), TIMEOUT_MS);
      s.setSoTimeout(TIMEOUT_MS);
      OutputStream os = s.getOutputStream();
      String h = "Host: localhost:" + port + "\r\n";
      os.write(("GET /echo/one HTTP/1.1\r\n" + h + "\r\n")
          .getBytes(StandardCharsets.ISO_8859_1));
      os.flush();
      byte[] first = readSome(s.getInputStream());
      out.append("first-response-bytes=").append(first.length > 0)
          .append('\n');
      out.append(statusLineOf(first)).append('\n');
      os.write(("GET /echo/two HTTP/1.1\r\n" + h + "Connection: close\r\n\r\n")
          .getBytes(StandardCharsets.ISO_8859_1));
      os.flush();
      byte[] second = readSome(s.getInputStream());
      out.append("second-on-same-connection=").append(second.length > 0)
          .append('\n');
      out.append(statusLineOf(second)).append('\n');
    } catch (Exception e) {
      out.append("EXCEPTION ").append(e.getClass().getName()).append('\n');
    } finally {
      closeQuietly(s);
    }
    System.out.println("=== PROBE keep-alive");
    System.out.print(normalise(out.toString()));
    System.out.println();
  }

  private static void probe(String name, String request) {
    System.out.println("=== PROBE " + name);
    Socket s = null;
    try {
      s = new Socket();
      s.connect(new InetSocketAddress("localhost", port), TIMEOUT_MS);
      s.setSoTimeout(TIMEOUT_MS);
      String full = request;
      if (!full.endsWith("\r\n\r\n") && full.indexOf("\r\n\r\n") < 0) {
        full = full + "\r\n";
      }
      s.getOutputStream().write(full.getBytes(StandardCharsets.ISO_8859_1));
      s.getOutputStream().flush();
      byte[] resp = readAll(s.getInputStream());
      System.out.print(normalise(render(resp)));
    } catch (Exception e) {
      System.out.println("EXCEPTION " + e.getClass().getName() + ": "
          + normalise(String.valueOf(e.getMessage())));
    } finally {
      closeQuietly(s);
    }
    System.out.println();
  }

  /** Renders a response: status line, sorted headers, body summary. */
  private static String render(byte[] resp) {
    if (resp.length == 0) {
      return "NO RESPONSE (connection closed)\n";
    }
    String text = new String(resp, StandardCharsets.ISO_8859_1);
    int split = text.indexOf("\r\n\r\n");
    String head = split < 0 ? text : text.substring(0, split);
    String body = split < 0 ? "" : text.substring(split + 4);
    StringBuilder sb = new StringBuilder();
    String[] lines = head.split("\r\n");
    sb.append("status: ").append(lines.length > 0 ? lines[0] : "")
        .append('\n');
    // In received order, keeping duplicates: a repeated singleton field such
    // as Date is itself a finding, and sorting into a set would hide it.
    for (int i = 1; i < lines.length; i++) {
      sb.append("h: ").append(lines[i]).append('\n');
    }
    TreeSet<String> names = new TreeSet<String>();
    for (int i = 1; i < lines.length; i++) {
      int c = lines[i].indexOf(':');
      String n = c < 0 ? lines[i] : lines[i].substring(0, c);
      int count = 0;
      for (int j = 1; j < lines.length; j++) {
        if (lines[j].regionMatches(true, 0, n + ":", 0, n.length() + 1)) {
          count++;
        }
      }
      if (count > 1) {
        names.add(n + " x" + count);
      }
    }
    if (!names.isEmpty()) {
      sb.append("REPEATED-HEADERS: ").append(names).append('\n');
    }
    sb.append("bodyBytes: ").append(body.length()).append('\n');
    if (!body.isEmpty()) {
      String shown = body.length() > 600 ? body.substring(0, 600) + "...[cut]"
          : body;
      sb.append("body: ").append(esc(shown)).append('\n');
    }
    return sb.toString();
  }

  private static String statusLineOf(byte[] resp) {
    if (resp.length == 0) {
      return "status: (none)";
    }
    String text = new String(resp, StandardCharsets.ISO_8859_1);
    int nl = text.indexOf("\r\n");
    return "status: " + (nl < 0 ? text : text.substring(0, nl));
  }

  /**
   * Hides everything that changes run to run, so two reports differ only
   * where behaviour differs.
   */
  private static String normalise(String in) {
    String out = in;
    out = out.replace("localhost:" + port, "localhost:{PORT}");
    out = out.replace(":" + port, ":{PORT}");
    out = out.replaceAll("(?i)(h: date:).*", "$1 {DATE}");
    out = out.replaceAll("(?i)(h: last-modified:).*", "$1 {DATE}");
    out = out.replaceAll("(?i)(h: expires:).*", "$1 {DATE}");
    out = out.replaceAll("(?i)(h: etag:).*", "$1 {ETAG}");
    out = out.replaceAll("(?i)(h: server:).*", "$1 {SERVER}");
    out = out.replaceAll("JSESSIONID=[^;\\\\\"]*", "JSESSIONID={ID}");
    out = out.replaceAll("Powered by Jetty:// [0-9a-zA-Z.\\-]*",
        "Powered by Jetty:// {VERSION}");
    out = out.replaceAll("/probe-logs[0-9]*", "/probe-logs{N}");
    out = out.replaceAll("probe-logs[0-9]+", "probe-logs{N}");
    // Directory listings carry sizes and dates.
    out = out.replaceAll("[0-9]{4}-[0-9]{2}-[0-9]{2}", "{YMD}");
    return out;
  }

  private static String esc(String s) {
    if (s == null) {
      return "null";
    }
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '\r') {
        sb.append("\\r");
      } else if (c == '\n') {
        sb.append("\\n");
      } else if (c == '\t') {
        sb.append("\\t");
      } else if (c < 0x20 || c == 0x7f) {
        sb.append(String.format("\\x%02x", (int) c));
      } else if (c > 0x7e) {
        sb.append(String.format("\\u%04x", (int) c));
      } else {
        sb.append(c);
      }
    }
    return sb.toString();
  }

  private static byte[] readAll(InputStream in) throws IOException {
    ByteArrayOutputStream bos = new ByteArrayOutputStream();
    byte[] buf = new byte[8192];
    try {
      int n;
      while ((n = in.read(buf)) > 0) {
        bos.write(buf, 0, n);
        if (bos.size() > 300000) {
          break;
        }
      }
    } catch (IOException e) {
      // A timeout or reset ends the read; report what arrived.
    }
    return bos.toByteArray();
  }

  /** Reads one response's worth without waiting for EOF. */
  private static byte[] readSome(InputStream in) throws IOException {
    ByteArrayOutputStream bos = new ByteArrayOutputStream();
    byte[] buf = new byte[8192];
    try {
      int n = in.read(buf);
      if (n > 0) {
        bos.write(buf, 0, n);
      }
    } catch (IOException e) {
      // Report what arrived.
    }
    return bos.toByteArray();
  }

  private static void closeQuietly(Socket s) {
    if (s != null) {
      try {
        s.close();
      } catch (IOException ignored) {
        // nothing to do
      }
    }
  }

  private static String repeat(String s, int times) {
    StringBuilder sb = new StringBuilder(s.length() * times);
    for (int i = 0; i < times; i++) {
      sb.append(s);
    }
    return sb.toString();
  }

  /** Keeps the key name in one place without depending on its constant. */
  private static final class CommonConfigurationKeysPublicShim {
    private static final String LOGS_ENABLED = "hadoop.http.logs.enabled";

    private CommonConfigurationKeysPublicShim() {
    }
  }
}
