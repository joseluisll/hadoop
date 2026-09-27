<!---
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License. See accompanying LICENSE file.
-->

# HADOOP-19972: a differential regression hunt against Jetty 9.4

Jetty 9.4.58 → Jetty 12.1.12 (ee8, `javax.servlet`). PR apache/hadoop#8704 at
`7aa23f04`, compared against its own base `7806a24f` (HADOOP-19970 on Jetty
9.4.58).

This is a second pair of eyes on the PR, not a restatement of it. The work
already recorded — the seven elective behaviour changes, the `F1`-`F7` forced
facts, 402 diffed live requests across a simple, a secure and an HA/federated
cluster — is taken as read. What follows is only what that record does not
already contain, plus the suspicions it let me rule out.

One regression is worth a commit. It comes with a one-line fix and a test,
both verified. Everything else is either a release-note item or a
confirmation.

Worth stating the review position this lands in, because it shapes how much
weight a second opinion should carry: the PR is still a draft, and as of
27 September it has had **no external review at all** — no assigned
reviewers, no submitted reviews, no inline comments, and only one substantive
comment, the author's own of 1 September asking for judgement on the
behaviour decisions. Nobody has answered it. So nothing below contradicts a
reviewer; it is the first outside reading of the change.

## 1. Method

The host available for this run had only JDK 21, where CI tests on 17, so
nothing here rests on a single-sided observation. Every measurement was taken
twice, from the same source, against the two Jetty versions:

* **PR head** `7aa23f04` — Jetty 12.1.12.
* **PR base** `7806a24f` — Jetty 9.4.58. This isolates HADOOP-19972 from
  HADOOP-19970 underneath it.

Two builds, two local Maven repositories, so the two sets of artifacts could
not mix.

The instrument is a probe that starts a real `HttpServer2` — the same
`Builder`, the same default `/logs` and `/static` contexts, the same global
filters — and sends **90 raw HTTP requests** over a socket, so the request
line, the header block and malformed input are all under test rather than
under a client library's control. An echo servlet reports back how the
container decoded each request: `getRequestURI`, `getServletPath`,
`getPathInfo`, `getQueryString`, the parameter map, the parsed cookies, the
body. Reports were normalised (dates, ports, session ids, Jetty version) and
diffed. A second, focused probe covers redirects: 8 requests.

Then 431 unit tests, chosen to include the classes CI does **not** run:
`.github/gha-tests/exclude-tests.txt` excludes 184 classes, several of them on
exactly the paths this PR changes.

Sources of truth for Jetty behaviour are the 12.1.12 and 9.4.58 class files in
the local repository, read with `javap`, not memory.

## 2. Regression: `sendRedirect` stops resolving the `Location` header

`HttpConfiguration.relativeRedirectAllowed` exists in both versions and
**defaults to `false` on Jetty 9.4 and `true` on Jetty 12**. `HttpServer2`
never sets it, so the default changes underneath it and every
`sendRedirect` in the tree now puts a bare path on the wire where it used to
put an absolute URI.

Measured, same servlet, same request, base on the left:

| `sendRedirect(...)` argument | 9.4 | 12 |
|---|---|---|
| `/target/page` | `http://localhost:PORT/target/page` | `/target/page` |
| `relative/page` | `http://localhost:PORT/redir/relative/page` | `/redir/relative/page` |
| `/target/page?a=b&c=d` | `http://localhost:PORT/target/page?a=b&c=d` | `/target/page?a=b&c=d` |
| `/target/a%20b/c%25d` | `http://localhost:PORT/target/a%20b/c%25d` | `/target/a%20b/c%25d` |
| `/target/../climbed` | `http://localhost:PORT/climbed` | `/climbed` |
| `/target/page`, `Host: proxy.example` | `http://proxy.example/target/page` | `/target/page` |
| `http://example.org:8088/target/page` | unchanged | unchanged |

Only an argument that is already absolute is unaffected.

**Where this reaches.** `sendRedirect` is how Hadoop redirects in
`ProxyUtils` and `WebAppProxyServlet` (the YARN web proxy), `AmIpFilter`, the
YARN webapp `Dispatcher`, `WebServlet` — the servlet serving `/static` and
`/logs`, which this PR touches — and `JWTRedirectAuthenticationHandler`, the
SSO login redirect.

**Why it matters beyond the letter of the spec.** A relative `Location` is
legal (RFC 7231 onwards) and browsers resolve it. The reason to care is that
Hadoop does not always use a browser: `WebHdfsFileSystem` reads a redirect
with

```java
url = new URL(conn.getHeaderField("Location"));
```

which throws `MalformedURLException` on a relative value. WebHDFS itself is
**safe** — the NameNode builds its 307 through JAX-RS
`Response.temporaryRedirect(uri)` with a URI it constructs, and Jersey writes
that header directly, so the container's setting never touches it. I
confirmed that empirically: 153 WebHDFS and HttpFS tests pass, including the
full `TestFSMainOperationsWebHdfs` contract suite. But the idiom is Hadoop's
own, it is in shipped client code, and anything applying it to a
`sendRedirect` path now breaks.

**Why nothing caught it.** No test reads the header off the wire.
`TestAmFilter` installs a stub response that overrides `sendRedirect` and
records its *argument* (`TestAmFilter.java:365`), so the container never gets
a say. The PR's changes to `TestAmFilter`, `TestWebAppProxyServlet`,
`TestWebAppProxyServletFed` and `TestRouterWebAppProxy` are import migrations
only. And the live-cluster diffing did exercise redirects — "WebHDFS OPEN and
CREATE redirected to the DataNode" — but those are the JAX-RS 307s, the one
redirect shape the change cannot affect. The 402-request inventory in §10 of
the options document lists no redirect difference because none of the 402 was
a servlet `sendRedirect`.

**The fix.** Jetty 12 does not force this. The options document's rule is
*no behaviour change unless Jetty 12 forces it and the community approves*,
and the PR description's own version of it is "Where Jetty 12 would change
what a caller sees, trunk's answer is kept". On either reading this belongs
with the kept behaviours, set explicitly — exactly as the PR already does for
TLS renegotiation ("Set it either way: Jetty 9.4 and Jetty 12 disagree on the
default"). In `HttpServer2.Builder.build()`, beside
`setSendServerVersion(false)`:

```java
httpConfig.setRelativeRedirectAllowed(false);
```

Verified: with it, all six servlet redirects above are byte-identical to
9.4, the proxied-`Host` case included. A test that fails without it and
passes with it is in the patch (`TestHttpServer#testRedirectLocationIsAbsolute`);
without the fix it reports

```
Expecting: </echo?redirected=true>
to start with: <http://localhost:42689>
```

No configuration key is proposed: trunk had none, and the point is to keep
trunk's behaviour.

## 3. Release-note item: the context redirect became 301, and relative

A request for a context path without its trailing slash is answered by
Jetty's own `ContextHandler`, not by a servlet, and it changed in two ways at
once:

| | 9.4 | 12 |
|---|---|---|
| `GET /static` | `302 Found`, `Location: http://localhost:PORT/static/` | `301 Moved Permanently`, `Location: /static/` |

The status matters more than the shape here: a 301 is cacheable
indefinitely, so a browser or proxy that sees it once may never ask again.
`setRelativeRedirectAllowed(false)` does **not** fix this one — the core
handler bypasses the ee8 response path — and `ContextHandler` exposes no
setting for the status (only `setAllowNullPathInContext`, which decides
whether to redirect at all). So unlike §2 this is effectively forced, and
belongs in the release note rather than in a commit.

## 4. Smaller differences not in the record

None of these is a blocker; all five are absent from the options document,
from the 20 commit messages and from JIRA.

1. **`getPathTranslated()` returns `null` on every request**, where 9.4
   returned a path. This is a servlet-API contract change, not a Hadoop one:
   the only consumer in the tree is `DefaultPage.java:46`, a YARN debug page,
   which will render the row blank.
2. **A duplicate `Host` header is now refused.** 9.4 served the request and
   took the **second** `Host` for `getServerName()` and `getRequestURL()` —
   `Host: localhost:PORT` followed by `Host: other:1` produced
   `http://other:1/echo/a`. Jetty 12 answers 400. This is a security
   improvement and worth saying out loud, because request-smuggling and
   cache-poisoning work on exactly that ambiguity.
3. **An overlong UTF-8 sequence in a path is now refused.** `%C0%AF` reached
   the servlet on 9.4 as two characters (`À¯`); Jetty 12 answers
   400. Also an improvement.
4. **`Expect: 100-continue` now gets an interim `100 Continue`.** 9.4 sent
   only the final response. Spec-correct, and every mainstream client handles
   it, but it is a change on the wire for anything that does not.
5. **A 416 no longer carries a body.** On a range past the end of a
   913-byte file, 9.4 answered `416 Range Not Satisfiable` with
   `Accept-Ranges: bytes` and a **913-byte body**; Jetty 12 answers 416 with
   `Content-Length: 0`. Both send `Content-Range: bytes */913`. Jetty 12 is
   the more correct of the two. Ordinary range requests are identical: a
   `Range: bytes=0-3` gives `206 Partial Content`, `Content-Range: bytes
   0-3/913`, 4 bytes, on both.

## 5. One nit

`HttpExceptionUtils.isJson` uses `contentType.trim().toLowerCase()` with no
locale. Hadoop keeps `StringUtils.toLowerCase` — documented as "Converts all
of the characters in this String to lower case with `Locale.ENGLISH`" — for
this, and this same PR uses `StringUtils.toUpperCase` in
`HttpServer2.getUriCompliance`. On a JVM defaulting to a Turkish locale,
`APPLICATION/JSON` lowercases to a dotless `ı` and the check misses, which
degrades a readable `Forbidden` to a line of quoted JSON — the exact outcome
the method's own javadoc says it exists to avoid.

## 6. Already in the record — confirmed, and one of them quantified

Two items here are **not** new; the options document lists both in §10 as
accepted residual differences. Repeating them only because I measured them.

* **The duplicate `Date` header.** The options document has this right:
  error responses "now carry a `Date` header, twice, as trunk's 200s already
  did (Jetty's and `NoCacheFilter`'s)". The PR description's release-note
  bullet is weaker than its own analysis — it says only "a `Date` header on
  error responses", which reads as one header being added. Measured: **51 of
  90** responses on 9.4 and **59 of 90** on 12 carry two. So the duplication
  is pre-existing and the PR widens it to error responses rather than causing
  it; the release-note wording is worth aligning with the document. What
  neither says is that
  `Date` is a singleton field (RFC 9110 §5.5/§6.6.1) and a recipient may
  treat a message carrying two as malformed. The cause is one word in
  `NoCacheFilter.doFilter`: `addDateHeader("Date", now)` on a response Jetty
  has already dated, where `setDateHeader` was meant. That is a trunk bug and
  a separate JIRA, not this PR's to carry — but this PR is what makes it
  visible on error responses.
* **`Vary: Accept-Encoding` and `charset` on static responses** — recorded,
  and confirmed present.

## 7. Suspicions tested and cleared

Listed because a negative result costs the reviewer nothing to trust and
saves them the work.

* **The error handler does what the PR claims.** For `/err/404`, `/err/403`,
  `/err/500` over GET, POST, HEAD, PUT and DELETE, the responses are
  **byte-identical** between 9.4 and 12 — including no body at all for PUT
  and DELETE. `ReasonBodyErrorHandler` reproduces `F2` exactly.
* **Connector-level diagnostics are not lost.** 9.4 put them in the reason
  phrase — `400 Multiple Content-Lengths`, `400 No Host`, `400 Header
  Folding`, `505 Unknown Version`. Jetty 12 sends the canonical phrase but
  moves the text into the error page's `MESSAGE:` row, which is precisely
  what `HttpExceptionUtils.toPlainText` extracts. Nothing an operator needs
  disappears.
* **Cookies are safe, in both directions.** Parsing is identical for quoted
  values, `$Version`, and a realistic quoted `hadoop.auth` token. Generation
  is identical too; a value containing a space is refused by both, and Jetty
  12's `ComplianceViolationException` **extends
  `IllegalArgumentException`**, so an existing `catch` still catches it.
* **`DefaultServlet`'s init parameters still arrive.** ee8's
  `DefaultServlet` reads `gzip` and `dirAllowed` under the 9.4-era
  `org.eclipse.jetty.servlet.Default.` prefix — confirmed from the class
  file's constant pool. The comment in `HttpServer2` explaining that prefix
  is correct.
* **Every legitimate path and query decodes identically**: empty segments
  (`//a//b`), `%25`, `%5C`, `%00`, `%09`, `%0A`, `%7F`, `+`, UTF-8 (`%E2%82%AC`),
  path parameters, `;jsessionid=`, `?x=1;y=2`, `?x=%FF%FE`, `?flag`,
  form-encoded and chunked bodies, a chunked body with a trailer, keep-alive
  reuse, `OPTIONS *`, `TRACE`, an unknown method, HTTP/1.0. The three allowed
  `UriCompliance` violations restore 9.4 for exactly the cases Hadoop needs.
* **The metrics fixes are in the squashed head**, not just on the prototype
  branch: `TimeUnit.NANOSECONDS.toMillis` conversion and all five async
  metrics published as 0.
* **SNI host checking is unchanged** — `new SecureRequestCustomizer(sniHostCheckEnabled)`
  means the same thing in both versions.
* **All five Jetty-12 hazards raised on HADOOP-19912 (2026-08-02) are
  closed.** `jetty-util-ajax` is gone (only javadoc mentions remain, the code
  having moved to Jackson under HADOOP-19951); `setStatusWithReason` has no
  main-code call sites left; `SymlinkAllowedResourceAliasChecker` is
  constructed from `getCoreContextHandler()`; `@WebSocket` and friends come
  from `org.eclipse.jetty.ee8.websocket.api.annotations`; the minicluster pom
  carries its websocket artifacts.

## 8. Test results

431 tests, no failures, on the PR head. Five of the six classes below are in
CI's exclude list, so this is the first time they have run against this
change.

| suite | tests | in CI? |
|---|---|---|
| hadoop-common HTTP and filters, 22 classes | 122 | yes |
| `TestHttpFSWithHttpFSFileSystem` | 100 | **excluded** |
| `TestWebHdfsDataLocality`, `TestWebHdfsTimeouts`, `TestFSMainOperationsWebHdfs` | 89 | **excluded** |
| `TestFederationWebApp`, `TestRouterWebServicesREST` | 94 | **excluded** |
| `TestEditLogRace`, `TestTransferFsImage` | 14 | **excluded** |
| `TestWebApp` | 12 | **excluded** |

Two results worth pulling out:

* `TestSSLHttpServerMTLS` passes here. It is the class that failed the
  27 September GitHub Actions run, which supports reading that as a flake —
  as does HADOOP-19979, which rewrites that assertion.
* `TestRouterWebServicesREST` passes here (42 tests). It is the **only**
  failing test in the 26 September Yetus run — the one `-1` in an otherwise
  clean patch phase — and the PR does not say whether that failure is the
  patch's or pre-existing. Passing here, on the PR head, is evidence for the
  latter. It is also a CI-excluded class, so GitHub Actions never runs it and
  Yetus is the only place it appears.

With the §2 fix applied: `TestHttpServer` 41 including the new test, the
web-proxy suite 22 (`TestAmFilter`, `TestWebAppProxyServlet`,
`TestWebAppProxyServletFed`, `TestProxyUriUtils`), and a 65-test
hadoop-common HTTP re-run — all pass. Checkstyle reports **no new violation**
on either changed line range, which matters because the 26 September Yetus
run already carries two new checkstyle warnings; the fix adds none.

## 9. What this run does not cover

* **JDK 21, not 17.** The differential design means a Java-version artefact
  would have to appear on both sides to hide, but these are not CI results.
* **No native build**, so nothing needing `libhadoop` was exercised.
* **No live cluster, no Kerberos, no TLS beyond the unit tests.** The
  existing record is far stronger here, and this run does not touch it.
* **HTTP/1.1 only** — no HTTP/2, no HTTP/3.
* The probe drives `HttpServer2`. Servers that YARN builds through `WebApps`,
  and the NodeManager's WebSocket path, were covered only by their unit
  tests.

## 10. Suggested actions

1. **Take the one-line fix and its test** into the PR: `sendRedirect` is not
   a behaviour the PR set out to change, and the fix is the same shape as the
   renegotiation one already in it.
2. **Add §3 to the release note**: `/logs` and `/static` without a trailing
   slash now answer `301` with a relative `Location` instead of `302` with an
   absolute one.
3. **Add §4.2 and §4.3 to the release note as hardening**: a duplicate `Host`
   header and an overlong UTF-8 path are now refused.
4. **Move the release note onto the JIRA, and set the flag.** The text
   already exists, in the PR description's section "What still differs from
   trunk (for the release note; the reason phrase alone makes this
   Incompatible)" — but a PR body is not where a release note is published
   from. As of this writing HADOOP-19972, HADOOP-19970, HADOOP-19971 and
   HADOOP-19912 all have an empty `Release Note` field, no `Hadoop Flags`
   value (which is where "Incompatible change" is recorded) and no fix
   version. The PR has said it is incompatible; the JIRA has not.
5. **File the `NoCacheFilter` `Date` bug separately** (§6) — it predates this
   work.
6. **Consider the §5 nit** while the file is open.
7. **Consider a test that reads `Location` off the wire** wherever a redirect
   is part of a contract. The gap in §2 was not that the behaviour changed
   quietly; it was that nothing looked.

## 11. Reproducing this

The two probes are throwaway harnesses, not proposed tests. Each is a single
file with a `main`, dropped into
`hadoop-common-project/hadoop-common/src/test/java/org/apache/hadoop/http/`
and run against that module's test classpath, so the same file compiles on
both commits:

* `JettyProbe.java` — the 90 raw requests and the echo servlet.
* `RedirectProbe.java` — the 8 redirect requests behind §2 and §3.

```
./mvnw -q test-compile -pl hadoop-common-project/hadoop-common
./mvnw -q dependency:build-classpath -pl hadoop-common-project/hadoop-common \
    -Dmdep.outputFile=cp.txt -Dmdep.includeScope=test
cd hadoop-common-project/hadoop-common
java -cp "target/test-classes:target/classes:$(cat ../../cp.txt)" \
    org.apache.hadoop.http.JettyProbe > report.txt
```

Run that on `7aa23f04` and on `7806a24f`, normalise the port, drop the log
lines, and diff. Use a separate `-Dmaven.repo.local` for the second build, or
the two sets of `3.6.0-SNAPSHOT` artifacts will overwrite each other and the
comparison becomes meaningless.
