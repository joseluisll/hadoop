# Jetty 12 migration: compatibility testing and downstream implications

**HADOOP-19912** · covering HADOOP-19970 / 19971 / 19972

| | |
| --- | --- |
| Baseline under test | `jetty-phase-c` @ `91ccfd1f` (Jetty 12.0.37, ee8) |
| Candidate | `jetty12-relocation-applied` @ `6dcfd71a` (baseline + Jetty relocation) |
| Pre-migration reference | `trunk` @ `d57814e3` (Jetty 9.4.58) |
| Toolchain | JDK 21.0.10, Maven 3.9.15, japi-compliance-checker 1.8 |
| Evidence branch | `jetty12-downstream-compatibility` |

> **Status.** This work is stopped and is **not proposed for merge.** Phases A, B and C
> have since been reworked, so the relocation branch is parented on a commit that is no
> longer the tip of `jetty-phase-c`. The measurements and the failure modes remain valid;
> the patch itself needs redoing on the new phases. This document exists so the community
> can judge whether that is worth doing.

---

## 1. Summary

**For downstream consumers.** The Jetty 12 ee8 upgrade, as it stands without mitigation,
breaks four of the six ecosystem projects that could be tested. Three of them **compile
without a single warning and then fail at class-load time**. Exposure is not predictable
by reading a POM.

**For Hadoop.** The break can be eliminated inside Hadoop, without asking anything of
downstream projects, by relocating Jetty into a published `hadoop-shaded-jetty` artifact —
the pattern already used for Protobuf and Guava. This was built and tested: all 119 modules
compile, both client invariant checks pass, and 10,039 tests across 20 modules show zero
regressions against the baseline. It costs 74 files, a new published artifact, and one
`@InterfaceAudience.Private` signature change.

**What it does not fix.** Tez, whose problem is inheritance rather than resolution.
Tez needs a two-line change in Tez, and that change is correct regardless of what Hadoop
decides.

---

## 2. The compatibility problem

### 2.1 What breaks

Four projects confirmed broken by **real builds** against phase-c:

| Project | Jetty pin | Failure | Detected at |
| --- | --- | --- | --- |
| Tez 0.10.4 | *none* | `package org.eclipse.jetty.servlet does not exist` | compile |
| Ozone | 9.4.58 | `NoClassDefFoundError: org/eclipse/jetty/server/Deployable` | **runtime** |
| Hive 4.0.1 | 9.4.45 | same | **runtime** |
| Knox 2.0.0 | 9.4.48 | same, via `gateway-spi` | **runtime** |

Three of the four produce a **clean build** and fail only when Hadoop's HTTP stack is first
touched. A downstream project's green CI says nothing about whether it survives this.

### 2.2 Why it happens

Maven resolves one version per coordinate by **nearest wins**:

- The consumer declares `org.eclipse.jetty:jetty-server` at **depth 1**. It beats Hadoop's
  transitive Jetty 12 at depth 2+. The consumer gets **Jetty 9.4 core**.
- Hadoop's `org.eclipse.jetty.ee8:*` coordinates are **uncontested** — the consumer has
  never heard of them — so they arrive at **12.0.37**.

The resulting classpath carries Jetty 9.4 core *and* Jetty 12 ee8. The ee8 classes
reference `org.eclipse.jetty.server.Deployable`, which does not exist in 9.4.

**This rules out every POM-level mitigation.** No version, scope, `dependencyManagement`
entry or ordering choice in Hadoop's POMs outranks a consumer's direct declaration. That is
a property of Maven, not of this change.

### 2.3 Exposure is not readable from a POM

It is **not** "any project that pins Jetty 9":

- **Oozie** pins Jetty 9.3.27 and is **unaffected** — for Oozie the contested coordinates
  resolve to 12.0.37 *through Hadoop*, so the stack stays coherent.
- **HBase** and **Ranger** are unaffected because they have **zero** Jetty imports.

What decides it is whether the project's own Jetty declaration wins mediation for the core
artifacts *while* Hadoop's ee8 modules arrive transitively — a property of declaration depth
across the whole reactor.

**Consequence for reviewers:** every cheap static check attempted during this work returned a
clean result for **every project that turned out to be broken**. Signature comparison,
classpath scanning and POM inspection are all blind to this. Only real downstream builds
found it.

### 2.4 All nine projects examined

| Project | Result | Basis |
| --- | --- | --- |
| Tez 0.10.4 | **breaks** (compile) | real build |
| Ozone | **breaks** (runtime) | real build + linkage probe |
| Hive 4.0.1 | **breaks** (runtime) | real build + linkage probe |
| Knox 2.0.0 | **breaks** (runtime) | real build + linkage probe |
| Oozie | unaffected | real build; `jetty-server` resolves to 12.0.37 |
| HBase | unaffected | 0 Jetty imports across 4,980 Java files |
| Ranger | unaffected | 0 Jetty imports across 1,347 Java files |
| Atlas | **untested** | fails identically on both refs — Jersey 1 already removed from trunk, unrelated to Jetty |
| Spark | **untested** | consumes shaded clients; the probe overstates exposure |

Nine projects is a sample, not proof. Since exposure depends on reactor-wide mediation,
**four confirmed breaks is a lower bound.**

---

## 3. What downstream consumers must do — *without* the relocation

This section applies if the ee8 migration ships as-is. The cost is very unevenly distributed.

### 3.1 Tez — genuinely two lines

Tez declares **no Jetty version**; it borrows Jetty from Hadoop's closure. Its entire Jetty
usage across 1,174 Java files is one class.

```diff
-import org.eclipse.jetty.servlet.DefaultServlet;
+import javax.servlet.http.HttpServlet;

-public class ProfileOutputServlet extends DefaultServlet {
+public class ProfileOutputServlet extends HttpServlet {
```

Verified safe by inspection: no `super.` call, no `getResource`, no `ResourceService`, no
`ContextHandler`, and `doGet` overrides completely. The class uses nothing a `DefaultServlet`
provides. Patch: `downstream-check/patches/tez-drop-jetty-DefaultServlet.patch`.

Tez could instead update the import to `org.eclipse.jetty.ee8.servlet.DefaultServlet`, but
that pins Tez to Jetty 12 for no benefit. Dropping the inheritance is strictly better.

### 3.2 Ozone, Hive, Knox — a Jetty 9→12 migration in their own code

Removing the Jetty 9 pin is a one-line POM edit, but it means **their own Jetty code now
compiles against Jetty 12**. Every Jetty import in each project was classified against the
actual 12.0.37 artifacts:

| Project | Package survives by name | Renamed to `ee8.*` | Absent from Jetty 12 |
| --- | ---: | ---: | ---: |
| Ozone | 28 | 20 | 2 |
| Hive | 94 | 22 | 7 |
| Knox | 128 | 92 | 6 |

**The middle column is mechanical** — `org.eclipse.jetty.servlet` → `org.eclipse.jetty.ee8.servlet`,
`.webapp` → `.ee8.webapp`, and for Knox all of `.websocket.servlet` / `.websocket.api` /
`.websocket.server` → `.ee8.websocket.*`.

**The right column is real work.** `org.eclipse.jetty.util.log` does not exist in Jetty 12
(removed in Jetty 10 in favour of slf4j) — Hive 2 imports, Knox 4. `org.eclipse.jetty.server.session`
is gone — Ozone 1, Knox 2. Hive's `rewrite.handler` (5) and Ozone's `proxy` (1) are not in the
artifacts this build resolves.

**The left column is the trap.** "Same package name" does **not** mean source-compatible.
`org.eclipse.jetty.server` kept its name but Jetty 12 rewrote it — `Handler`, `Request` and
`Response` are different types, `AbstractHandler` is gone, `HandlerWrapper` became
`Handler.Wrapper`. Knox has 59 imports there plus 28 in `server.handler`; Hive has 34. These
need reading, not replacing.

> **The counts above are a floor on the review effort, not a count of things that pass.**

Knox is the worst affected: 92 renames, 87 core-server imports needing API review, and its
WebSocket layer sits exactly where Jetty 12 changed the bootstrap contract —
`JettyWebSocketServlet` no longer self-initialises from `init()`, so every registration site
must call `JettyWebSocketServletContainerInitializer.configure()` explicitly.

### 3.3 A third option, untested

A project that depends on Hadoop but **never touches Hadoop's HTTP stack** could exclude
Jetty from its Hadoop dependencies and keep its own Jetty 9. Plausible for Hive and Knox,
which run their own servers. Impossible for Ozone, which embeds `HttpServer2`.

Reference counts for `HttpServer2`:

| Project | Java files referencing `HttpServer2` |
| --- | ---: |
| Ozone | 20 |
| Knox | 2 |
| Tez | 2 |
| Hive | 1 |
| Oozie | 0 |

**Hive and Knox are broken by Hadoop's transitive Jetty while barely embedding Hadoop's
server at all.** This is reasoning, not a result — it was not tested.

---

## 4. The relocation approach

Branch: **`jetty12-relocation-applied`** @ `6dcfd71a` (74 files, +406 / −432).

### 4.1 What it does

One new module, `hadoop-shaded-jetty`, publishes Jetty 12 ee8 pre-relocated under
`org.apache.hadoop.thirdparty.org.eclipse.jetty`, with a dependency-reduced POM so **no
`org.eclipse.jetty` coordinate reaches consumers**. Every consuming Hadoop module imports
from the relocated namespace.

Hadoop's Jetty and the consumer's Jetty then share neither a coordinate nor a package name.
There is nothing left for Maven to mediate, so the two implementations coexist as unrelated
libraries.

```xml
<artifactSet><includes>
  <include>org.eclipse.jetty:*</include>
  <include>org.eclipse.jetty.ee8:*</include>
  <include>org.eclipse.jetty.ee8.websocket:*</include>
  <include>org.eclipse.jetty.websocket:*</include>
</includes></artifactSet>          <!-- toolchain deliberately absent -->
<relocations><relocation>
  <pattern>org.eclipse.jetty</pattern>
  <shadedPattern>org.apache.hadoop.thirdparty.org.eclipse.jetty</shadedPattern>
</relocation></relocations>
```

### 4.2 The boundary that makes it work

`org.eclipse.jetty.toolchain` — the servlet API — is deliberately **neither bundled nor
relocated**. This is forced, not stylistic:

> **You cannot relocate a type your callers implement.** Downstream code writes
> `implements AuthenticationHandler` and `extends HttpServlet`. Rename those and no
> downstream class satisfies the clause. Relocation works for libraries you *call*; it fails
> for interfaces you *expose*.

The rule the design encodes: **the container is Hadoop's private business; the spec is the
public interface.** This is the same contract `TestDownstreamServletCompatibility` (added in
phase-c) already asserts at compile time — relocation makes it hold at runtime too.

### 4.3 Why not the alternatives

| Option | Verdict | Evidence |
| --- | --- | --- |
| Shade Jetty inside `hadoop-common` | **fails** | Works in isolation; fails three ways at reactor scale — `WebApps` handing an unshaded `WebAppContext` to a shaded server; websocket packages missing from the jar; `WebServer` needing a shaded context accepted by an unshaded API. **Relocation is all-or-nothing across interoperating modules.** |
| Different container (Tomcat, Undertow) | **worse** | `tomcat-embed-core` bundles **88 servlet-spec classes inside its own jar** — no coordinate to exclude, so it permanently collides with whatever downstream declares. Also removes the Jetty that Tez borrows, and is a rewrite of Hadoop's HTTP layer. |
| Mark Jetty `provided` / `optional` | **shifts cost** | No collision, but every project embedding `HttpServer2` must declare exact ee8 coordinates itself, failing at runtime if wrong. A larger downstream ask than a pin bump. |
| Split API from implementation | **unprototyped** | Genuinely attractive and complementary — would rescue Hive and Knox structurally. Would not help Ozone. Not built. |

---

## 5. Testing performed

### 5.1 Methodology

- **Two refs built identically into isolated local repositories** — `-Dmaven.repo.local` per
  ref plus a shared read-only `-Dmaven.repo.local.tail`. The only difference between them is
  the relocation patch.
- **`-fae`** so a failing module does not stop the run; **`-Dsurefire.rerunFailingTestsCount=0`**
  so nothing is retried into passing.
- **Failing sets diffed by name, not by count.** Matching totals are weak evidence — two
  different tests can fail on the two refs and still total the same.
- **`target/classes` and `target/test-classes` deleted per module per ref.** Maven recompiles
  on changed *sources*, not changed *dependencies*; without this, stale classes link against
  jars that are gone and throw `NoSuchMethodError` that reads exactly like a regression.
- **Timed-out modules salvaged from surefire reports**, which record precisely which classes
  completed, rather than discarded.

**Scope:** the 27 testable modules the relocation patch touches. Modules the patch does not
touch cannot be affected by it.

### 5.2 Build-level gates

| Gate | Result |
| --- | --- |
| Compilation, all 119 modules | **passes** |
| `hadoop-client-check-invariants` | **passes** |
| `hadoop-client-check-test-invariants` | **passes** |
| `hadoop-shaded-jetty` contents | 2,051 classes, 3.9 MB, **0 unrelocated Jetty classes leaked** |

### 5.3 Module test suites — fully compared

Both refs ran the same tests; results identical in every row.

| Module | Tests | Failures | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| `hadoop-auth` | 192 | 0 | 0 | 0 |
| `hadoop-common` | 5,499 | 41 | 0 | 380 |
| `hadoop-yarn-common` | 540 | 0 | 1 | 7 |
| `hadoop-hdfs-httpfs` | 607 | 0 | 0 | 0 |
| `hadoop-kms` | 48 | 0 | 0 | 0 |
| `hadoop-yarn-server-web-proxy` | 54 | 0 | 0 | 0 |
| `hadoop-yarn-services-api` | 52 | 0 | 0 | 0 |
| `hadoop-yarn-server-applicationhistoryservice` | 209 | 0 | 0 | 0 |
| `hadoop-yarn-server-timelineservice` | 85 | 0 | 0 | 0 |
| `hadoop-yarn-server-router` | 580 | 1 | 2 | 2 |
| `hadoop-yarn-server-globalpolicygenerator` | 33 | 0 | 0 | 0 |
| `hadoop-yarn-server-common` | 553 | 0 | 0 | 11 |
| `hadoop-nfs` | 21 | 0 | 0 | 0 |
| `hadoop-hdfs-nfs` | 65 | 0 | 0 | 0 |
| `hadoop-sls` | 32 | 0 | 0 | 0 |
| `hadoop-resourceestimator` | 47 | 0 | 0 | 0 |
| `hadoop-mapreduce-client-app` | 427 | 0 | 0 | 0 |
| `hadoop-yarn-server-timelineservice-hbase-tests` | 104 | 0 | 0 | 0 |
| **Total** | **9,148** | | | |

The 41 `hadoop-common` failures and the `yarn-server-router` failures occur **identically on
both refs**. They are container artifacts — running as root (`TestFileUtil`, `TestDiskChecker`,
`TestFsShellCopy`, `TestLocalDirAllocator`), no native library (`TestNativeCodeLoader`), no
Kerberos (`TestWebDelegationToken`). The failing sets were diffed by name: **28 names on each
ref, none appearing on only one.**

### 5.4 Module test suites — partial, salvaged from timeouts

| Module | Classes both refs completed | Tests | Result |
| --- | ---: | ---: | --- |
| `hadoop-yarn-client` | 10 | 52 | no relocated-only failures; 2 classes fail on **both** |
| `hadoop-yarn-server-nodemanager` | 92 | 839 | no relocated-only failures; 1 flake |

Both hang on mini-cluster tests (`TestAMRMProxy`) on the **baseline** ref too, so the hang is
environmental. `nodemanager` shows 33–34 failures and 59–60 errors *on the baseline*; its
noise floor makes it a poor detector regardless.

**The one asymmetry, and why it is a flake.** `TestFederationInterceptor.testRecoverWithoutAMRMProxyHA`
failed *only on baseline* in one run and *only on relocated* in the next. A test that switches
sides between runs is not detecting a code difference, and the assertion
(`expected: <1> but was: <0>`, an HA recovery count) has no servlet container in its stack.

### 5.5 Aggregate

**10,039 tests compared across 20 modules. Zero regressions.**

### 5.6 Downstream verification

A synthetic out-of-tree consumer pinning `jetty-server` 9.4.58 and taking `hadoop-common`
plus `hadoop-hdfs`:

| Built against | Jetty majors on its classpath | `HttpServer2` |
| --- | --- | --- |
| phase-c | **9.4 and 12.0** | `NoClassDefFoundError` |
| **relocation branch** | **9.4 only** | **loads** |

Also measured, on the servlet-API duplication axis — the relocation is a strict improvement
over trunk here, and phase-c already was:

| Ref | Jars carrying `javax/servlet/Servlet.class` |
| --- | --- |
| trunk | `javax.servlet-api-3.1.0` **and** `jakarta.servlet-api-4.0.4` |
| phase-c | `jetty-servlet-api-4.0.9` — **one** |

### 5.7 What was **not** tested

- **Three modules never ran:** `hadoop-yarn-server-resourcemanager`, `hadoop-hdfs`,
  `hadoop-mapreduce-client-jobclient`. They are the largest suites and the run environment
  was reclaimed before reaching them.
- **Three modules have no tests:** `hadoop-auth-examples`, `hadoop-client-runtime`,
  `hadoop-client-minicluster` (packaging / sample modules).
- **One module fails identically on both refs:** `hadoop-yarn-applications-catalog-webapp`
  (5 errors each — frontend build chain needs network).
- **Real downstream builds were run against phase-c, not against the relocation branch.**
  The downstream fix is evidenced by the synthetic consumer's classpath and linkage, not by
  rebuilding Ozone/Hive/Knox against the relocated artifacts.
- **No release-path leg.** Everything compares trunk-to-trunk. The question a downstream user
  actually faces is upgrading from a 3.4.x release, and the servlet coordinate also moved
  once before this change.

---

## 6. Implications for Hadoop itself

### 6.1 A reachable signature changes

`HttpServer2.webAppContext` the *field* is unreachable — final class, private constructor.
But there is a public accessor:

```java
public WebAppContext getWebAppContext(){
```

Under relocation its return type becomes `org.apache.hadoop.thirdparty.org.eclipse.jetty.ee8.webapp.WebAppContext`.
**Any downstream caller breaks at source and binary level.** Hadoop's own
`TestHttpFSServerWebServer` is such a caller, which is how it surfaced. `HttpServer2` is
`@InterfaceAudience.Private` and Hadoop accepted the same trade for Protobuf, but this
belongs in a release note rather than in a downstream stack trace.

### 6.2 A new published artifact

`hadoop-shaded-jetty` must be versioned, published and maintained. The engineering is done;
the release mechanics and governance were never addressed. Whether it lives in the main repo
or alongside `hadoop-thirdparty` is an open decision.

### 6.3 Two defects the approach hits — both invisible to compilation

Both share one shape, and it is the most transferable finding here:
**relocation breaks things that refer to Jetty by name in text rather than in bytecode.**

**Defect 1 — coordinate-based exclusions stop matching.** `hadoop-client-runtime` and
`hadoop-client-minicluster` exclude Jetty by groupId/artifactId. Once Jetty arrives as one
pre-relocated artifact those excludes match nothing and `BanDuplicateClasses` fails the
build. Fixed with two `<exclude>org.apache.hadoop:hadoop-shaded-jetty</exclude>` lines.
*Generalisation:* audit every packaging rule naming Jetty by coordinate.

**Defect 2 — class names inside Jetty's own descriptors are not relocated.**
`maven-shade-plugin` rewrites class files and resource *paths*, but not class names inside
resource *content*. Jetty names classes as text in `webdefault-ee8.xml`, which **every
`WebAppContext` reads**:

```xml
<listener-class>org.eclipse.jetty.ee8.servlet.listener.IntrospectorCleaner</listener-class>
<servlet-class>org.eclipse.jetty.ee8.servlet.DefaultServlet</servlet-class>
<param-name>org.eclipse.jetty.session.SessionDomain</param-name>
```

After relocation those classes exist only under the thirdparty prefix. Jetty gets
`ClassNotFoundException`, the context fails startup, and the webapp answers **HTTP 503**.
Any Hadoop service hosting a UI from a directory would have returned 503 in production.

Scope was measured, not guessed: of 40 resources in the jar still carrying unrelocated names,
36 are `META-INF/maven/**` build metadata and one is a GraalVM native-image config — none
read at runtime. Four are functional: `webdefault-ee8.xml` and three `configure_*.dtd`. Fixed
with a `maven-antrun` step after shade, excluding `org.eclipse.jetty.toolchain`.

> **This is the most important lesson in the document.** Defect 2 was caught by
> `TestApplicationHistoryServer.testHostedUIs` and by nothing else. Compilation of all 119
> modules, both invariant checks, and 6,231 tests across three modules all passed over it.
> **Shading is not verified by compiling, and barely by unit tests.** It needs a test that
> starts a real container and deploys a webapp.

Still unverified in the fix: the three `configure_*.dtd` rewrites were never exercised by any
test, and the 36 metadata files were left untouched by judgement rather than measurement.

### 6.4 A risk the relocation introduces

Relocation stops Hadoop contributing **any** unrelocated Jetty. **Oozie is green today
precisely because it takes `jetty-server` 12.0.37 through Hadoop.** Remove that and Oozie
falls back to its own 9.3.27 pin. Probably fine — its code targets 9.3 — but it was never
tested.

**Projects that currently get their Jetty *from* Hadoop are the population this fix could
disturb, and they are exactly the ones nobody thinks to check.**

### 6.5 What this means for a future ee9 / ee10 move

Relocation handles the **container** dimension permanently: ee9 and ee10 live under
`org.eclipse.jetty.*`, so the shade pattern already covers them and only the coordinates
change. Downstream would not observe an internal ee8→ee10 move at all.

It does **not** help with the **spec namespace**. Moving to ee9/ee10 means Hadoop's public
API moves to `jakarta.servlet`, breaking every downstream implementation of
`AuthenticationHandler`, `AuthenticationFilter`, `FilterInitializer`, `RestCsrfPreventionFilter`
and the rest at once. Relocation cannot touch that, because you cannot relocate a type your
callers implement. Phase-c already encodes this: `TestDownstreamServletCompatibility` exists
to fail on that day, deliberately.

`ee8` is therefore the correct choice and is not the cause of the break — `ee9`/`ee10` would
be strictly worse. What breaks here is Jetty 12 relocating *its own core* (`Deployable`,
`Handler.Singleton`), which no environment choice avoids.

**The timeline is set by Jetty's ee8 support horizon, not by this decision.** When Jetty
drops ee8, Hadoop is forced to jakarta whether or not it is ready. Worth confirming against
Jetty's published policy.

---

## 7. Implications for downstream consumers

| | Ship phase-c alone | Ship phase-c + relocation |
| --- | --- | --- |
| Ozone | Jetty 9→12 migration of its own code | **no change required** |
| Hive | Jetty 9→12 migration of its own code | **no change required** |
| Knox | Jetty 9→12 migration of its own code (largest: 92 renames + 87 core-API imports) | **no change required** |
| Tez | two lines | two lines (unchanged) |
| Oozie | no change | **untested** — loses its Jetty source, falls back to its own pin |
| HBase, Ranger | no change | no change |
| Anyone calling `HttpServer2.getWebAppContext()` | no change | signature change (`Private` API) |
| Anyone excluding Jetty from Hadoop by coordinate | exclusion still works | exclusion silently matches nothing |

**The asymmetry is the decision.** Shipping phase-c alone sends Tez a two-line patch and
sends three other projects a multi-week dependency migration they did not schedule — one
where their build stays green until it does not. The relocation moves all three to zero, at
the cost of one artifact and one `Private` signature.

### Release-note requirements either way

The failure mode must be named explicitly. A `NoClassDefFoundError` on
`org/eclipse/jetty/server/Deployable` **after a clean build** is not something a downstream
maintainer will diagnose quickly, and the claim that this work is invisible to downstream
projects is disproved by four real builds.

---

## 8. Open questions

1. **Three module suites never ran** — `resourcemanager`, `hadoop-hdfs`,
   `mapreduce-client-jobclient`. A merge proposal needs them.
2. **Oozie regression check** — rebuild Oozie against the relocation branch. Cheap, and it is
   the one project the fix could plausibly disturb.
3. **Real downstream builds against the relocation branch** — Ozone, Hive and Knox were built
   against phase-c; the fix is evidenced by the synthetic consumer only.
4. **Release mechanics** for `hadoop-shaded-jetty`.
5. **A 3.4.x release-path leg**, since that is the upgrade downstream users actually perform.
6. **The API/implementation split** as a complementary change: Hive and Knox reference
   `HttpServer2` in 1 and 2 files, so a split would remove Jetty from most consumers' view
   entirely.

---

## 9. Reproducing this

1. **Rebase the concept, not the patch.** `downstream-check/experiments/hadoop-thirdparty-jetty.patch`
   (1,909 lines) targets phase-c at `91ccfd1f` and will not apply to reworked phases. The
   module POM in `downstream-check/experiments/hadoop-shaded-jetty.pom.xml` is the reusable
   artefact — it carries both fixes and the reasoning as comments.
2. **Build two refs into isolated repositories**, and verify the worktree actually checked out
   — a build run from the wrong directory installs mislabelled artifacts and logs nothing
   unusual. See `downstream-check/RUNBOOK.md`.
3. **Gate on a container-starting test first** — deploy a `WebAppContext` from a directory and
   fetch a page. This is the check that would have caught Defect 2 in minutes rather than
   after three modules of clean suites.
4. **Then run module suites** with per-module `target/` deletion, `-fae`, no reruns, and
   by-name failing-set diffs. Driver: `downstream-check/experiments/remaining-suites.sh`.
5. **Finally, real downstream builds** of Tez, Ozone, Hive and Knox against both refs. This is
   the only step that ever found a downstream break.

### Where things are

| Path | Contents |
| --- | --- |
| `downstream-check/runs/2026-08-25-phase-c.md` | Full raw evidence record, including retracted claims |
| `downstream-check/RUNBOOK.md` | Prerequisites and every harness trap hit |
| `downstream-check/experiments/` | The patch, the module POM, the suite drivers |
| `downstream-check/patches/` | The two-line Tez fix |
| `downstream-check/report/` | Findings report and handover report (HTML) |
| `downstream-check/consumer/` | Synthetic out-of-tree consumer used for linkage probes |
| `downstream-check/vendor/` | `checkcompatibility.py` with offline/exit-code fixes |

### Branches on the fork

| Branch | Contents |
| --- | --- |
| `jetty12-downstream-compatibility` | Evidence, runbook, reports, patches — 30 commits, all under `downstream-check/` |
| `jetty12-relocation-applied` | The relocation applied on `91ccfd1f` — 1 commit, 74 files |

---

## 10. Claims that did not survive checking

Recorded so none resurfaces as received wisdom.

| Claimed | Actually |
| --- | --- |
| Any project pinning Jetty 9 is exposed | Oozie pins 9.3.27 and is fine. Mediation decides, not the pin. |
| Shading `hadoop-common` alone is a workable route | Fails three ways at reactor scale. Relocation is all-or-nothing across interoperating modules. |
| `HttpServer2.webAppContext` is the downstream-reachable break | The *field* is unreachable; the public `getWebAppContext()` accessor is the real one. |
| HBase is the strongest detector to prioritise | Zero Jetty imports. It cannot detect this at all. |
| An Ozone-shaped probe POM proves the failure | The probe used 2 Hadoop artifacts and 2 exclusions; Ozone really uses 14 and 19. |
| Oozie could not be tested | A probe bug — `hadoop-tools` is a pom-only aggregator declared as a jar. |
| japi-compliance-checker 2.3 is the version to use | Deadlocks on larger jars (undrained stderr in its `open3` call). 1.8 does not. |

---

*Every number in this document is a difference between two refs built identically, minutes
apart, into isolated local repositories. A check failing the same way on both sides is
reported as telling us nothing.*
