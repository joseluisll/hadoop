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

# HADOOP-19972: options for the seven elective behaviour changes

Jetty 9.4.58 → Jetty 12.1.12 (ee8, `javax.servlet`). PR apache/hadoop#8704,
stacked on #8699 (HADOOP-19970).

The PR's rule is *no behaviour change unless Jetty 12 forces it and the
community approves*. Part 2 of the 1 September "Phase C approach review"
listed seven changes that Jetty 12 did not force. This document takes each
one in turn and asks four questions. What exactly changed? What would it take
to keep it? Can it be reverted on Jetty 12? Is there a narrower option? It
ends with a recommendation and the commit order to carry it out.

The goal agreed for this work is **the smallest possible behaviour change
from trunk**. Where a revert is possible and cheap, it has been prototyped on
branch `jetty12-behaviour-options` (on top of `jetty-phase-c` 056c5623), one
commit per change, with focused tests.

## 0. Baseline and evidence

* **Branch under review:** `jetty-phase-c` at 056c5623. Citations
  `file:line` refer to that commit unless marked otherwise.
* **Trunk:** `apache/hadoop` `trunk` at 90f0d1da. For every file this
  document discusses, trunk is identical to the branch's base (7806a24f); the
  one commit trunk has gained since (HDFS-17981, NFS) touches none of them.
* **Jetty facts** come from the source jars on Maven Central, not memory:
  `jetty-ee8-nested`, `jetty-ee8-servlet`, `jetty-server` and `jetty-http`
  12.1.12, and `jetty-server`, `jetty-http` and `jetty-util`
  9.4.58.v20250814. Paths below such as `ee8/nested/Response.java:678` are
  inside those jars.

### Forced facts every option has to live with

| # | Fact | Evidence |
|---|------|----------|
| F1 | **Jetty 12 never sends a custom reason phrase, not even through `setStatusWithReason`.** ee8's `setStatus(int,String)` discards the message. `setStatusWithReason` stores it, but the nested channel passes only the status to the core response, and the core builds the status line with a null reason. This is stronger than the review's bytecode finding, which covered `setStatus(int,String)` only. | `ee8/nested/Response.java:678-680`, `:682-689`; `ee8/nested/HttpChannel.java:848` (`coreResponse.setStatus(response.getStatus())`); `server/internal/HttpChannelState.java:1589-1590` (`new MetaData.Response(_status, null, …)`) |
| F2 | **Both versions write an error page for GET, POST and HEAD only.** For any other method the error goes out with no body, on 9.4 and on 12 alike. So on 9.4 a refused PUT or DELETE carried its detail **only** in the reason phrase. | 9.4: `ErrorHandler.java:79-88`, `HttpChannel.java:528`. 12: `ee8/nested/ErrorHandler.java:73-81`, `ee8/nested/HttpChannel.java:499` |
| F3 | **On trunk exactly four call sites put a custom phrase on the wire**, because 9.4's `setStatus(int,String)` delegates to `setStatusWithReason` (9.4 `Response.java:736-739`). Plain `sendError(code, msg)` has not set the phrase since 9.4.21. | trunk `AuthenticationFilter.java:633`, `RestCsrfPreventionFilter.java:276`, `KMSAuthenticationFilter.java:123`, `ImageServlet.java:707` (a `git grep` of trunk main code for `setStatusWithReason` and two-argument `setStatus`) |
| F4 | **`sendError` on a committed response throws `IllegalStateException` in both versions.** The state machine is the same. | 9.4 `HttpChannelState.java:914-915`; 12 `ee8/nested/HttpChannelState.java:809-810` |
| F5 | **9.4 rejected no ambiguous or suspicious URI at all.** `HttpConnectionFactory` defaults to `HttpCompliance.RFC7230`, which excludes every `NO_AMBIGUOUS_*` section. `URIUtil.decodePath` rejects only malformed `%` escapes. Jetty 12.1's `UriCompliance.DEFAULT` allows **no** violation. | 9.4 `HttpConnectionFactory.java:53`, `HttpCompliance.java:144-151`, `URIUtil.java:394,491`; 12 `UriCompliance.java:195,207` |
| F6 | **Jetty 12's `StatisticsHandler` records times in nanoseconds** (9.4 recorded milliseconds) and has **no async counters** anywhere in core or ee8. | 12 `StatisticsHandler.java:79,105` (`NanoTime.since`), attribute docs "(in ns)"; 9.4 `StatisticsHandler.java:108,174,190` (`currentTimeMillis`); `grep -r getAsync` over the 12.1.12 sources: nothing |
| F7 | **Jetty 12 refuses to start a context whose base resource is not readable. A null base resource is accepted.** | 12 `server/handler/ContextHandler.java:890-894` |

## Summary

| # | Change (introducing commit) | Recommendation | Prototype on `jetty12-behaviour-options` |
|---|---|---|---|
| 1 | CSRF refusal → JSON envelope (14622fec, 6bfd173e) | **Revert** to `sendError`, marked for any-method body | 9485322a |
| 2 | `/topology` 200-truncated → 410 (efb2fe80) | **Revert**; propose as a separate JIRA | aba2b9da |
| 3 | RENEW refusal → JSON envelope (cae23348, 11565602) | **Revert** to trunk's throw | e27d587a |
| 4 | Error page for every method, webapp only (cae23348, 5c57e6e5) | **Narrow**: body only for errors whose phrase was lost; same on all contexts | b9136180 |
| 5 | `UriCompliance` with 3 violations allowed (e8c1b4a5, 590adb9c, 05230755) | **Keep** (strictly narrower than 9.4); fix comment; release-note it; optional config key | 73bb1b5f (comment only) |
| 6 | `/logs` dropped when log dir missing (cae23348) | **Revert** to 9.4 answers (403 non-admin / 404 admin) | 173fa546 |
| 7 | 5 async metrics deleted; `dispatched*` re-sourced (cae23348) | **Revert** the deletion (publish as 0); keep the re-sourcing; **fix nanosecond regression** | 82ac101e, f2a9c13d |

Two further problems turned up along the way; see §8.

* A **regression the review missed**: eight time metrics are published in
  nanoseconds under "(in ms)" descriptions. Fixed in f2a9c13d.
* `AuthenticationFilter`'s `setStatus(code, reason)` had been removed. It is
  now **restored**, which is harmless on Jetty 12 and keeps the phrase for
  other containers. Done in b9136180.

---

## 1. `RestCsrfPreventionFilter`: 400 HTML → 400 JSON envelope

**Where.** `RestCsrfPreventionFilter.java:274-290`, from 14622fec. The mocked
responses in `TestRestCsrfPreventionFilter` were changed in 14622fec and
6bfd173e.

**On the wire, compared with trunk (NameNode WebHDFS, CSRF enabled, header
missing).**

| | trunk (9.4) | `jetty-phase-c` |
|---|---|---|
| Status line | `400 Missing Required Header for CSRF Vulnerability Protection` | `400 Bad Request` (F1, forced) |
| GET/POST body | Jetty HTML error page containing the message, `text/html;charset=iso-8859-1` | `{"RemoteException":{"exception":"IOException","javaClassName":"java.io.IOException","message":"Missing Required Header…"}}`, `application/json` |
| PUT/DELETE body | none, `Content-Length: 0` (F2) | the same JSON envelope |
| DataNode (Netty `RestCsrfPreventionFilterHandler.java:148-151`) | `400 <message>`, no body | unchanged, so **the NameNode and the DataNode now disagree** |

**In the API.** `WebHdfsFileSystem.validateResponse` changes code path. On
trunk, `jsonParse` rejected `text/html`, and the client threw
`IOException("Unexpected HTTP response: code=400 … message=<phrase>")`. On
the branch the envelope parses and a `RemoteException` is rebuilt and
unwrapped into `IOException("Missing Required Header…")`. That is the same
type with a different message layout.

**Option A, keep.** This needs a JIRA incompatible-change flag and a release
note ("CSRF refusals from the NameNode and HttpFS are now JSON"). The Netty
handler would also have to emit the same envelope, otherwise one refusal has
two shapes. Browsers, which are the clients CSRF protection exists for, would
get JSON instead of an error page.

**Option B, revert.** Fully possible apart from the phrase (F1). The branch
already teaches readers to take the reason from the body: `WebHdfsFileSystem`
lines 520-541 and `HttpExceptionUtils.getResponseDetail`, from a5141ec9 and
1cad208f. So the JSON is no longer needed for new clients to see the message.
The one remaining gap is F2: a refused **PUT or DELETE** (for example WebHDFS
`MKDIRS`) has no body on Jetty 12, so the message would be lost entirely.
That is covered by the narrowed error handler of §4, which the filter asks for
by setting a request attribute. Result: the same body and content type as
trunk for every method, only without the phrase.

Trunk's Jetty-specific `setStatusWithReason` is replaced by the Servlet-API
`setStatus(code, message)`, which on 9.4 delegates to it (F3) and on Jetty 12
does nothing. That keeps the phrase in containers that still send one: Hive's
WebHCat loads this filter on Jetty 9.4 (see §9).

The revert breaks nothing outside the tests 14622fec/6bfd173e rewrote. Those
go back to trunk's assertion (`verify(res).sendError(400, EXPECTED_MESSAGE)`),
plus checks for `setStatus` and the marker.

**Narrower middle.** The one suggested in the review — change readers, not
the server — is exactly Option B plus the §4 marker.

**Cross-version clients.**

* New client ↔ 9.4 server: `getResponseDetail` falls back to the phrase when
  the body is empty or HTML. Works either way.
* Old client ↔ Jetty 12 server: with **B** an old `WebHdfsFileSystem` reports
  `message=Bad Request`, because it reads only the phrase. The detail is lost,
  but that is forced by F1 and the type is unchanged. With **A** an old client
  gets the message back, because it parses JSON. **This is the one real
  argument for A.** It is weak: CSRF protection is off by default
  (`dfs.webhdfs.rest-csrf.enabled=false`), and a Java client configured for it
  always sends the header.

**Recommendation: B, prototyped as 9485322a.** Effort: small. Risk: low.

## 2. `NetworkTopologyServlet`: 200 truncated → 410 Gone

**Where.** `NetworkTopologyServlet.java:59-105` and
`RouterNetworkTopologyServlet.java:40-61`, from efb2fe80. That commit also
carries an **unrelated** hunk: the app-catalog `pom.xml`
(`hadoop-yarn-applications-catalog-webapp`) is moved back to Solr's HTTP/2
artifact names. The hunk belongs with 279a1b3b and must survive any revert.

**On the wire.** On trunk a dump that failed mid-way went out as `200 OK` with
a truncated body. A dump that failed before writing went out as `200` with no
body. Both happened because try-with-resources closes, and so commits, the
stream before the `catch` runs, after which `sendError` throws (F4). On the
branch the whole dump is buffered in heap, a failure is answered `410 Gone`
with the error page, and a success gains a `Content-Length`. **This is the
only one of the seven that changes a status code**, and efb2fe80's own
message says it is not a Jetty 12 regression.

**Option A, keep.** It should go through its own JIRA (an HDFS bug fix), with
a note on heap use for large topologies. In a Jetty upgrade it is out of
scope.

**Option B, revert.** Fully possible. Because of F4, trunk's code on Jetty 12
behaves exactly as trunk on 9.4. The revert removes
`testFailedDumpIsNotAnsweredAsSuccess`, which asserted the 410. The existing
`TestNetworkTopologyServlet` and `TestRouterNetworkTopologyServlet` cases are
unaffected.

**Narrower middle.** None worth having: the change is all-or-nothing.

**Downstream.** `/topology` is read by humans and scripts. A 410 where a 200
used to be is visible, so it should not ship unannounced. A client of either
version against a server of either version is otherwise unaffected.

**Recommendation: B, prototyped as aba2b9da, and re-propose efb2fe80 as a
separate HDFS JIRA.** Effort: trivial. Risk: none.

## 3. `DelegationTokenAuthenticationHandler` RENEW: 403 HTML → 403 JSON

**Where.** `DelegationTokenAuthenticationHandler.java:304-313`, from cae23348.
The assertions were changed in 11565602 (`TestWebDelegationToken`,
`assertRenewRefused`).

**On the wire.** On trunk, a failed renew threw `AuthenticationException`, and
`AuthenticationFilter` answered `403 <ex.toString()>` in the phrase (F3).
RENEW is a **PUT**, so there was no body (F2). On the branch it is
`403 Forbidden` with the JSON envelope. One `switch` now answers in three
shapes: `sendError` for a missing parameter, JSON for the proxy-user
authorization failure (already JSON on trunk, line 262), and now JSON for
renew.

**In the API.** `DelegationTokenAuthenticator` → `validateResponse`. On trunk
the caller got `IOException("HTTP status [403], message [<phrase>] …")`. On
the branch it gets the **typed** server exception, usually
`AccessControlException`. A caller that catches `AccessControlException`
separately now takes a different branch. Renewers such as YARN's
`DelegationTokenRenewer`, KMS clients and Oozie are the kind of code affected
(unverified per caller).

**Option A, keep.** This needs a JIRA incompatible flag and a release note
("token renewal failures are now typed"). The three shapes in the switch
should be made consistent.

**Option B, revert.** Fully possible. The error goes back through
`AuthenticationFilter`, which marks it (§4), so on every `HttpServer2`
context (KMS, HttpFS, NameNode, RM) the refusal carries its detail in the
error page even though it is a PUT. New clients read it through
`rewoundDetail`. The revert restores trunk's `contains("403")` assertions,
which pass. **Caveat:** `TestWebDelegationToken` runs the filter on a bare
Jetty `ServletContextHandler`, not `HttpServer2`. There, as for any downstream
that embeds `AuthenticationFilter` in its own Jetty 12 server, a PUT refusal
has no body and the detail is lost (F1 + F2). §4 discusses that.

**Narrower middle.** Keep an envelope but name `java.io.IOException` as the
class. Old clients would then get the message back without a change of type.
It still changes the content type, so it is not recommended under the minimal
rule.

**Cross-version clients.**

* New client ↔ 9.4 server: the phrase is read. Fine either way.
* Old client ↔ Jetty 12 server: with B, `IOException("HTTP status [403],
  message [Forbidden]…")`. The type is kept and the detail lost (forced). With
  A, a typed exception with the detail.

**Recommendation: B, prototyped as e27d587a.** Effort: small. Risk: low.

## 4. `ErrorHandler`: an error page for every method

**Where.** `HttpServer2.java:809-824`, from cae23348. It became an
`ErrorPageErrorHandler` in 5c57e6e5.

**On the wire.** On trunk, PUT, DELETE, OPTIONS, TRACE and PATCH errors had no
body (F2). On the branch **every** such error in the webapp context gets the
HTML page, **and** is now dispatched to web.xml `<error-page>` mappings, which
9.4 never did for those methods. `/logs`, `/static` and other contexts keep
Jetty's default, so the webapp and the default contexts now differ where 9.4
was uniform.

**Why it is there.** It compensates for F1 on the call sites that relied on
the phrase. By F3 there are only four of those, and `ImageServlet` already
writes its own body (80cbf48f, reviewed as correct). So a global change is far
wider than the loss it compensates for.

**Option A, keep.** Release-note it ("error responses to non-GET methods now
carry an HTML body"), and install it on every context.

**Option B, revert to Jetty's default.** Possible, but it **creates** a
regression. A refused PUT or DELETE from `AuthenticationFilter`, the KMS
filter or the CSRF filter would then carry no detail at all: no phrase (F1)
and no body (F2). That includes WebHDFS `MKDIRS`/`DELETE` refusals, KMS key
deletion and token renew/cancel. Not recommended.

**Narrower middle (recommended).** Write the error page for another method
only where 9.4 had a custom phrase. The four trunk call sites (F3), reduced to
the three filters, mark their error with the request attribute
`AuthenticationFilter.ERROR_MESSAGE_FOR_ANY_METHOD_ATTRIBUTE`. HttpServer2's
`ReasonBodyErrorHandler` renders a marked error for any method. Every other
error is answered exactly as on 9.4: no body, no `Cache-Control`, and no
`<error-page>` dispatch for other methods. The handler goes on the webapp,
`/logs` and `/static`, because the authentication filter runs on all three.
The one visible difference from trunk is *marked PUT/DELETE refusals gain an
HTML body*, which stands in for the phrase they lost.

**Remaining gap.** Contexts that downstream code adds itself
(`HttpServer2.addContext`) and servers that downstream builds on bare Jetty 12
do not get the handler. For them a marked PUT refusal still has no body. If
the community wants to close that gap, a follow-up could make
`ReasonBodyErrorHandler` public, or install it from `addContext` when a
context has no error handler of its own.

**Downstream.** HTML bodies on 4xx responses to PUT or DELETE are only
additive: nothing that read `Content-Length: 0` as a signal is known
(unverified). Old clients ignore the body. New clients read it.

**Recommendation: middle, prototyped as b9136180.** Effort: small. Risk: low.

## 5. `UriCompliance`: three violations allowed

**Where.** `HttpServer2.java:555-580`. Empty segments came in e8c1b4a5, `%25`
in 590adb9c, and `%5C`/control characters in 05230755.

**What changed, compared with trunk.** By F5, 9.4 rejected nothing on these
grounds. Jetty 12.1's default rejects every violation. The branch allows
`AMBIGUOUS_EMPTY_SEGMENT`, `AMBIGUOUS_PATH_ENCODING` and
`SUSPICIOUS_PATH_CHARACTERS`. So **compared with trunk, Hadoop now
rejects**:

* `AMBIGUOUS_PATH_SEPARATOR` (`%2F`)
* `AMBIGUOUS_PATH_SEGMENT` (`%2E`, `%2E%2E`)
* `AMBIGUOUS_PATH_PARAMETER` (`..;`)
* `UTF16_ENCODINGS` (`%uXXXX`)
* `BAD_UTF8_ENCODING`, `TRUNCATED_UTF8_ENCODING`, `BAD_PERCENT_ENCODING`
* `ILLEGAL_PATH_CHARACTERS`
* `USER_INFO`
* `FRAGMENT` in a request path

Nothing that 9.4 rejected is now accepted. `SUSPICIOUS_PATH_CHARACTERS`
covers `\` **and** `%00`-`%1F` and `%7F` (12 `HttpURI.java:733-737`). The
branch comment justified it by `%5C` alone.

**Under SECURITY.md.** The defended boundary is privilege escalation across
an authenticated boundary in a Kerberos cluster, on a trusted network
perimeter.

* Path ambiguity matters when an authorization decision is made on a path
  that differs from the one the servlet acts on. Hadoop's
  `AuthenticationFilter` is mapped to `/*`, so ambiguity cannot bypass
  authentication. Path-scoped ACLs (`AdminAuthorizedServlet` on `/logs`,
  `/conf`, `/jmx`, and so on) are the relevant surface.
* The branch setting is **strictly narrower than trunk's**. It therefore
  cannot open anything trunk did not already expose, and it closes
  `%2F`/`%2E` ambiguity that trunk accepted.
* Re-admitting the encoded control characters restores trunk behaviour, so it
  is not a regression in the threat model.
* This analysis is from source. No reproducer was attempted, and none is
  claimed.

**Option A, keep (recommended).**

* Correct the comment. Done in 73bb1b5f, with no behaviour change.
* Release-note it: "Requests whose path contains `%2F`, `%2E` segments,
  `%uXXXX`, malformed UTF-8 or percent-encoding, user-info or a fragment are
  now rejected with 400 at the connector."
* Optionally add a documented key, for example
  `hadoop.http.uri.compliance.violations` (not prototyped). It would default
  to the three, and let an operator tighten the setting (drop
  `SUSPICIOUS_PATH_CHARACTERS` if no file names contain `\`) or loosen it (to
  Jetty's `LEGACY` for a client that sends `%2F`).
* Add a test that `%0A` is still accepted, or deliberately stop accepting it.
  Whichever is chosen should be a decision rather than a side effect.

**Option B, revert to 9.4.** `UriCompliance.LEGACY`, or `UNSAFE` plus
`AMBIGUOUS_PATH_PARAMETER`, comes closest. That would re-admit `%2F` and
`%2E` ambiguity for no functional gain, and `testAmbiguousPathsAreStillRejected`
(from 590adb9c) would fail. Not recommended. Whether the ee8 servlet layer
would even accept ambiguous URIs through `getPathInfo` under `LEGACY` is
**unverified**.

**Narrower middle.** Allow `%5C` but not control characters. Jetty offers no
finer switch than the whole violation, so this would need a
`HttpConfiguration.Customizer` that rejects encoded controls. That is
stricter than trunk, so it is a behaviour change of its own.

**Downstream.** A client that sends `%2F` in a WebHDFS path, or relies on
`..;`, now gets 400 from the connector with no body. Knox and other gateways
that re-encode paths are the most likely to notice; see §9.

**Recommendation: A (keep), plus a release note and an optional config key.**
Effort: small. Risk: low.

## 6. `/logs` dropped when `hadoop.log.dir` is missing

**Where.** `HttpServer2.java:1030-1039`, from cae23348.

**On the wire.** On trunk the context started on a missing directory, so an
admin got **404** and a non-admin got **403** (`AdminAuthorizedServlet` →
`hasAdministratorAccess`). On the branch the context is not created (F7), so
`/logs/*` falls through to the root webapp context. That means **404 for
everyone, with no ACL check**, and whatever the root webapp maps under
`/logs` answers instead. No test covered this.

**Option A, keep.** This needs a test, a release note, and an argument that
404-for-everyone leaks nothing.

**Option B, revert.** Possible with no loss. Keep the context, its filters and
its admin check, and leave only the base resource out, which F7 allows. A
small `MissingLogDirServlet` then runs `hasAdministratorAccess` and answers
404. The answers are exactly trunk's. A new test
(`testLogsWithMissingLogDirStillCheckAdminAccess`) covers admin → 404 and
non-admin → 403. It also sets up the `Groups` singleton the same way the
neighbouring test does, because an earlier version of it poisoned
`testAuthorizationOfDefaultServlets` when it ran first.

**Downstream.** Ozone and HBase-style embedders of `HttpServer2` get trunk
behaviour back.

**Recommendation: B, prototyped as 173fa546.** Effort: trivial. Risk: none.

## 7. `HttpServer2Metrics`

**Where.** `HttpServer2Metrics.java`, from cae23348.

**What changed.**

1. `asyncDispatches`, `asyncRequests`, `asyncRequestsWaiting`,
   `asyncRequestsWaitingMax` and `expires` were **deleted**. Jetty 12 has no
   counters to source them from (F6). The metric names vanish from JMX and
   from sinks.
2. `dispatched*` now reads `getHandleTotal/Active/ActiveMax/Time*`. Both
   versions time the initial dispatch from the request's start (9.4
   `StatisticsHandler.java:174`; 12 `:79`). For the synchronous servlets
   Hadoop serves, the numbers are therefore close to the 9.4 meaning. That
   equivalence is argued from the code, not measured.
3. **Regression, not in the review:** all eight `requestTime*` and
   `dispatchedTime*` metrics are now **nanoseconds** under "(in ms)"
   descriptions, because of F6. Dashboards and alerts on request latency read
   a value a million times too large.

**Option A, keep the deletion.** It needs a release note listing the five
names.

**Option B, revert.** The names can be restored, the values cannot. Publishing
them as `0` keeps every name resolvable. It is also *what 9.4 reported for
Hadoop's own daemons*: no Hadoop servlet starts an async request (a `git grep`
for `startAsync`, `AsyncContext`, `@Suspended` and `asyncSupported` over main
code finds none). An embedder that did use servlet async would read 0 where it
used to read a count. The descriptions say "always 0 since Jetty 12". The
nanosecond fix converts on the way out.

**Recommendation: B for the names (82ac101e), keep the `dispatched*`
re-sourcing, and fix the units (f2a9c13d).** Effort: trivial. Risk: none.
Covered by the new `TestHttpServer2Metrics`.

## 8. Other findings

* **Nanosecond metrics.** See §7. Fixed.
* **`AuthenticationFilter.setStatus(code, reason)` restored.** The branch had
  removed it as "forced". On Jetty 12 it is a no-op (F1). On any other
  container that still honours it — a downstream running hadoop-auth on
  Jetty 9.4, say — removing it silently drops the phrase. Keeping it makes
  the line identical to trunk. §9 shows this is not hypothetical: Hive,
  Ozone, Livy and Oozie all run this filter on Jetty 9.4. For the same reason
  the CSRF revert calls the Servlet-API `setStatus(code, message)` (§1).
* **Mis-scoped hunk in efb2fe80.** An app-catalog `pom.xml` change rides in
  the topology commit. If efb2fe80 is dropped upstream rather than reverted,
  the hunk must move to 279a1b3b.
* **The ErrorHandler lost `showStacks` parity on the default contexts.**
  Moot: the prototype leaves `/logs` and `/static` at Jetty's default
  (`showStacks=true` in both versions: 9.4 `ErrorHandler.java:70`, 12
  `ee8/nested/ErrorHandler.java:62`), exactly as trunk did.

## 9. Downstream impact

Researched by grepping shallow clones of the downstream repositories. Where
a checkout was sparse, absence claims cover only the server, client and KMS
code that was checked out. Commits:

| Project | Commit | Jetty / container | Hadoop |
|---|---|---|---|
| HBase | 63d06533 | Jetty 12 ee8, shaded | 3.4.3 |
| Hive | 2af70f7f | Jetty 9.4.57 | 3.4.2 |
| Spark | e985bd4b | Jetty 12.1 ee10 | 3.5.0 |
| Ozone | 71083257 | Jetty 9.4.58 | 3.4.3 |
| Knox | 7489115c | Jetty 12.0 ee10 | 3.4.1 |
| Ranger (sparse) | 5f88104f | Tomcat 9.0.120 | 3.4.2 |
| Oozie (sparse) | 8bdac8be | Jetty 9.4.44 | 2.8.5 |
| Livy (sparse) | 48a143a9 | Jetty 9.4.58 | 3.4.1 |

There are three ways a change here can reach a downstream:

* **(i)** a new Hadoop client talking to an old server;
* **(ii)** an old client talking to a Hadoop daemon on Jetty 12;
* **(iii)** Hadoop's server-side classes (`AuthenticationFilter`,
  `RestCsrfPreventionFilter`, `DelegationTokenAuthenticationFilter`) running
  inside a downstream's **own** container. A downstream picks this up by
  bumping `hadoop.version` alone. The review did not list this channel, and it
  turned out to be the one that matters.

**Findings.**

* **Nobody downstream reads a Hadoop daemon's reason phrase or matches its
  refusal strings.**
  * A search for "Anonymous requests are disallowed", "Invalid signature",
    "Missing Required Header", "non-matching renewer" and
    `getResponseMessage()` on Hadoop endpoints found only downstream copies of
    the filters, and code that reads the project's own server:
    * Ozone `InsightHttpUtils.java:91,111`
    * Hive `HiveServer2.java:1742`
    * Oozie `OozieClient.java:618`
    * Livy `LivyConnection.java:232`
  * Knox relays only the status code (`DefaultDispatch.java:194`), so Knox
    users never saw Hadoop's custom phrases anyway.
  * So (ii) has no concrete breakage from the forced phrase loss.
  * HBase already absorbed the same loss on its own Jetty 12 server by
    parsing the HTML error page (`LogLevel.java:280-284`,
    `LogLevelExceptionUtils.java:60-84`). That is precedent for §1 and §3
    Option B.
* **Channel (iii) is real.** Hadoop's `AuthenticationFilter` runs on
  Jetty 9.4 in:
  * Hive: the HS2 UI and WebHCat;
  * Ozone: its forked `HttpServer2`, Recon, S3G and the HttpFS gateway;
  * Livy and Oozie.

  On `jetty-phase-c` all of them would lose their 401/403 phrases just by
  upgrading the Hadoop jar. The restored `setStatus(code, reason)` (§8)
  prevents that.
* **`RestCsrfPreventionFilter` inside Hive WebHCat.**
  * WebHCat loads Hadoop's class by name (`shims/.../Utils.java:76-89`) and
    runs it on Jetty 9.4.57 (`templeton/Main.java:235,263-266`). It is
    opt-in: `templeton.xsrf.filter.enabled` defaults to false.
  * With trunk's Jetty-specific `setStatusWithReason` removed, WebHCat on 9.4
    would lose the phrase. A refused PUT or DELETE would carry no detail,
    because Jetty 9.4 does not know the marker attribute.
  * Fix: the CSRF revert also calls the Servlet-API `setStatus(code,
    message)`, as `AuthenticationFilter` does. It needs no Jetty import, 9.4
    honours it (F3), and it does nothing on Jetty 12.
* **The RENEW JSON (§3) would have reached** Ozone's HttpFS gateway
  (`HttpFSAuthenticationFilter.java:45`) and Ranger KMS
  (`KMSAuthenticationFilter.java:51`). Both extend Hadoop's
  `DelegationTokenAuthenticationFilter`. The revert removes this.
* **Metrics (§7).** No repository references Hadoop's `HttpServer2Metrics`
  names. Ozone forked the class and publishes four thread gauges only. Its
  Grafana dashboards query those. External dashboards such as Ambari and
  Cloudera Manager are UNVERIFIED.
* **`/logs`, `/static`, `/topology` (§2, §6).**
  * Knox proxies these pages from Hadoop UIs and passes statuses through.
    So a 410 from `/topology` would have reached Knox users; that change is
    now reverted.
  * Knox rewrites the `jetty-dir.css` link in the `/logs` listing. Jetty
    12.1.12 still emits that link (checked in `ResourceListing.class`).
* **`UriCompliance` (§5): the ecosystem chose differently.**
  * Knox sets `UriCompliance.LEGACY` and decodes ambiguous URIs "so that
    `%2F` paths reach WebHDFS/WEBHBASE backends" (`GatewayServer.java:493-502,
    924-929`).
  * HBase REST allows `%2F`, `%5C` and empty segments (`RESTServer.java:413-419`).
  * No downstream code was found emitting `%2F`, `%2E%2E`, `%5C` or `%25` in
    a WebHDFS or HttpFS path.
  * **Whether Knox forwards `%2F` to the NameNode still encoded is
    UNVERIFIED.** If it does, those requests get 400 on the branch. This is
    the strongest argument for the optional config key in §5.
* **A side effect of the forced reader change, not one of the seven.**
  `KMSClientProvider` now reads a 403's reason from the body (1cad208f).
  * Ranger KMS runs on Tomcat, which never sends a reason phrase. So trunk's
    check never matched a Ranger 403.
  * Ranger's error page does contain the message
    (`EmbeddedServer.java:257-264`). A new client therefore resets its token
    and retries once on "Anonymous requests are disallowed" or "Invalid
    signature" from Ranger KMS, where trunk failed immediately.
  * That is the behaviour the code was written for, but it is new, and it
    belongs in the release note. It was found from code and not run.

**UNVERIFIED.**

* Classpath conflicts when Ozone (a Jetty 9.4.58 BOM, starting Hadoop's
  MiniKMS in tests) or Hive (Jetty 9.4.57) take Hadoop's Jetty 12 ee8 jars.
  Nothing was built.
* How Knox rewrites HTML and JSON error bodies.
* External monitoring that uses Hadoop's metric names.

## 10. Overall recommendation

1. **Revert** 1 (CSRF), 2 (topology), 3 (RENEW) and 6 (`/logs`).
2. **Narrow** 4 (error bodies only where the phrase was lost, on every
   context).
3. **Keep and document** 5 (`UriCompliance`): fix the comment, add a release
   note, and optionally add a config key.
4. **Revert the deletion** in 7 and **fix the nanosecond regression**.

With these, what remains different from trunk on the wire is:

* **forced:** no custom reason phrase;
* **compensation for that:** marked PUT/DELETE refusals from the auth and
  CSRF filters carry an HTML body;
* **stricter URI parsing:** as listed in §5;
* **metrics:** the five async metrics read a constant 0.

Each of these needs a release note on the JIRA. It is worth flagging the
change **Incompatible** because of the reason phrase alone: every client that
read `getResponseMessage()` for detail is affected, whatever is done about the
seven.

### Commit order

On top of `jetty-phase-c` (056c5623), as prototyped:

| Order | Commit | Change |
|---|---|---|
| 1 | 173fa546 | `/logs` keeps the admin check (§6) |
| 2 | f2a9c13d | metric times back in ms (§7, regression) |
| 3 | 82ac101e | async metric names kept (§7) |
| 4 | b9136180 | narrowed error handler, marker, `setStatus` restored (§4). **Must precede 5 and 6**, which set the marker |
| 5 | 9485322a | CSRF back to `sendError`, plus Servlet-API `setStatus` for 9.4 containers (§1) |
| 6 | e27d587a | RENEW back to trunk (§3) |
| 7 | aba2b9da | topology back to trunk (§2) |
| 8 | 73bb1b5f | `UriCompliance` comment (§5) |
| 9 | (this document) | |

Before these go upstream, squash them into the commits they amend:

* 5 into 14622fec. Then 6bfd173e becomes empty and can be dropped.
* 6 into cae23348 and 11565602.
* 7 by dropping efb2fe80 and keeping its `pom.xml` hunk in 279a1b3b.
* 1, 3 and 4 into cae23348.
* 4 also into 5c57e6e5.

That would leave the PR's history without the elective changes ever
appearing.

## 11. Tests run

**Setup.** Maven 3.9.15 is the distribution pinned in
`.mvn/wrapper/maven-wrapper.properties`. `./mvnw` failed its SHA check
because Maven Central was rate-limiting (HTTP 429), so the zip was fetched
by hand, checked against the pinned `distributionSha256Sum` (it matched),
and run directly. JDK 21. Every run used
`-Dmaven.test.failure.ignore=false`, and results were read from the
`Tests run:` lines.

**Round 1**, on the eight prototype commits:

| Module | Tests | Result |
|---|---|---|
| hadoop-auth | TestAuthenticationFilter 28, TestKerberosAuthenticator 15, TestPseudoAuthenticator 7 | 50/50 pass |
| hadoop-common | TestHttpServer 37 (with the new `testLogsWithMissingLogDirStillCheckAdminAccess` and `testErrorBodyOnlyForMarkedErrorsOnOtherMethods`), TestHttpServer2Metrics 2 (new), TestRestCsrfPreventionFilter 10, TestWebDelegationToken 12, TestHttpExceptionUtils 18, TestDownstreamServletCompatibility 5, TestAuthenticationSessionCookie 2, TestHttpServerWebapps 2, TestServletFilter 2, TestGlobalFilter 1, TestHttpServerLogs 2, TestHttpCookieFlag 2 | 95/95 pass |
| hadoop-kms | TestKMS 34 (with the branch's `testKMSAuthFailureRetryOn403`), TestKMSAuthenticationFilter 1 | 35/35 pass |
| hadoop-hdfs | TestNetworkTopologyServlet 4, **TestWebHdfsWithRestCsrfPreventionFilter 32**, TestWebHdfsTokens 10 | 46/46 pass |
| hadoop-hdfs-rbf | TestRouterNetworkTopologyServlet (sync and async router RPC) 8 | 8/8 pass |

`TestWebHdfsWithRestCsrfPreventionFilter` is the end-to-end test that
motivated the JSON envelope. It failed six times before 14622fec. It passes
32/32 with the plain `sendError` revert. It exercises PUT, POST and DELETE
refusals through the NameNode and the DataNode, which confirms that the
readers from a5141ec9 and 1cad208f, plus the §4 marker, carry the message
without JSON.

**Round 2**, after the CSRF `setStatus` and `@InterfaceAudience.Private`
fixups were squashed in:

| Module | Tests | Result |
|---|---|---|
| hadoop-common | TestHttpServer 37, TestRestCsrfPreventionFilter 10, TestWebDelegationToken 12 | 59/59 pass |
| hadoop-hdfs | TestWebHdfsWithRestCsrfPreventionFilter 32 (against the freshly installed hadoop-common) | 32/32 pass |

Not run: the full module suites, the YARN web tests (`TestRMWithCSRFFilter`
and the like), and the HttpFS tests. The prototypes do not touch YARN or
HttpFS code, but both run `AuthenticationFilter`, so a full `hadoop-common`
and HttpFS run belongs in the PR's CI.

**One failure on the way, since fixed.** The first version of the `/logs`
test left the process-wide `Groups` singleton on the shell mapping when it
ran first. `testAuthorizationOfDefaultServlets` then failed (`userC`, an
admin only through `groupC`, got 403). The test now sets up
`MyGroupsProvider` the way its neighbour does.

## 12. Not verified

* Nothing here was probed on a live cluster. The claims are from source and
  from the unit and integration tests listed above.
* Whether the ee8 servlet layer passes ambiguous URIs under
  `UriCompliance.LEGACY` (§5 Option B).
* That `getHandleTime*` matches 9.4's dispatch time numerically for Hadoop's
  servlets (§7). It is argued from the code only.
* How individual token renewers react to a typed `AccessControlException`
  (§3). The point is moot once the revert is taken.
* Downstream findings marked UNVERIFIED in §9.
