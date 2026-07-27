# Plan: HDFS-11039 — ConfigurationScanner + hdfs-default.xml documentation audit

## Context

[HDFS-11039](https://issues.apache.org/jira/browse/HDFS-11039) ("Expose more configuration properties to hdfs-default.xml", open since 2016) asks that undocumented HDFS configuration properties be added to `hdfs-default.xml` so administrators can discover them. In 2018 a committer asked the reporter *which* properties should be added — that question was never answered. The goal of this work is to (1) build a **ConfigurationScanner** utility that produces the definitive, complete inventory of configuration properties across all HDFS subprojects, (2) classify every property (documented / undocumented / deprecated / unused / internal / dynamic / owned by another xml), and (3) drive curated documentation patches into `hdfs-default.xml` (and sibling files) from that inventory.

Repo: apache/hadoop trunk, shallow clone at commit `e55f979d`, local path `C:\dev\hadoop`.

## Codebase evidence (what exists, where the gaps are)

**Existing machinery.** Hadoop already ships a reflection-based comparison harness:

- `hadoop-common-project/hadoop-common/src/test/java/org/apache/hadoop/conf/TestConfigurationFieldsBase.java` — extracts `public static final String` fields from ConfigKeys classes (excluding `DEFAULT_*` / `*_DEFAULT` names), extracts `<name>/<value>` pairs from a default xml, diffs both directions, and cross-checks xml values against `DEFAULT_*` constants using 3 naming conventions. Key spec elements to reuse: `VALID_PROP_REGEX = ^[A-Za-z][A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$`, partial-key filter (values ending in `.`, `-`, `.xml`), skip sets (`configurationPropsToSkipCompare`, `xmlPropsToSkipCompare`, prefix variants).
- `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/tools/TestHdfsConfigFields.java` — hdfs-default.xml vs `DFSConfigKeys` + `HdfsClientConfigKeys` (+12 nested classes), **both error modes = true** → trunk is already clean for constants-vs-xml *modulo the skip lists*. Skip lists encode institutional knowledge, incl. an in-source admission of uncertainty: `// Fully deprecated properties?`.
- `hadoop-hdfs-project/hadoop-hdfs-rbf/.../TestRBFConfigFields.java` — same for hdfs-rbf-default.xml vs `RBFConfigKeys`, also strict.
- No equivalent test exists for **hadoop-hdfs-nfs** or **hadoop-hdfs-httpfs**.

**Because the existing tests are green, undocumented properties can only hide in five places (all verified locally):**

1. **Skip lists** in TestHdfsConfigFields (~30 entries; several marked "Fully deprecated properties?").
2. **String literals outside ConfigKeys classes** — measured: 705 distinct `dfs./nfs./httpfs.` literals in `hadoop-hdfs-project/*/src/main` java; **90 outside** the four ConfigKeys classes; **83 of those in no `*-default.xml`**. Mix of:
   - real undocumented keys: `dfs.block.scanner.cursor.save.interval.ms`, `dfs.ha.tail-edits.max-txns-per-lock`, `dfs.ha.tail-edits.qjm.rpc.max-txns`, `dfs.namenode.snapshot.deletion.ordered(.gc.period.ms)`, `dfs.namenode.snapshot.trashroot.enabled`, `dfs.namenode.audit.log.async`, `dfs.datatransfer.{client,server}.*` allow/deny-list keys, `dfs.webhdfs.oauth2.*`
   - deprecated old names (registered in `HdfsConfiguration.addDeprecatedKeys`, ~45 `DeprecationDelta`s)
   - example/false-positive strings (`dfs.namenode.rpc-address.nameservice1`)
3. **Whole modules without comparison tests**: NFS — `NfsConfigKeys` (95 lines) has **16 keys documented nowhere** (only 8 `nfs.*` keys are in hdfs-default.xml); `NfsConfiguration` registers **18** deprecations. HttpFS — `httpfs-default.xml` (337 lines) never compared; `httpfs.*` keys read in `HttpFSAuthenticationFilter`, `HttpFSServerWebApp`, etc.
4. **Dynamic/pattern keys**: `DFSUtil.addKeySuffixes` (4 call-site files) builds per-nameservice/per-namenode keys; prefix constants ending in `.` are filtered by the base test; only documentable as patterns (cf. existing `dfs.ha.namenodes` example entry).
5. **Keys owned by other xml files**: core-default.xml holds 4 `dfs.*` keys (`dfs.ha.fencing.*`, `dfs.client.ignore.namenode.default.kms.uri`); `hadoop-tools/hadoop-federation-balance/src/main/resources/hdfs-fedbalance-default.xml`; `TestCommonConfigurationFields` cross-skips dfs prefixes.

Deprecation sources to mine: `HdfsConfiguration.addDeprecatedKeys()`, `NfsConfiguration`, `HdfsClientConfigKeys.DeprecatedKeys`, `@Deprecated` annotations; `Configuration.dumpDeprecatedKeys()` already exists as a runtime dump utility.

Tooling precedent: `dev-support/bin/checkcompatibility.py` — Python tooling is accepted in dev-support.

## Recommended approach

**Standalone lexical ConfigurationScanner (Python, no build required) under `dev-support/hdfs-config-scanner/`, validated against the invariants guaranteed by the existing green reflection tests.**

Why not Java-reflection-first: reflection only sees constants in the listed classes — it provably misses the 83 undocumented literal keys; it needs a full Maven/protoc build (painful on Windows); and the green tests already answer the constants-vs-xml question. The scanner's marginal value is exactly what reflection cannot see. The base class's regex, partial-key rules, and default-naming conventions are reused as the spec.

### Scanner components

Each extractor emits records `{key, source_kind, file:line, default_if_known, notes}`:

- **E1 ConfigKeys parser** — parse `DFSConfigKeys`, `HdfsClientConfigKeys` (+nested classes per TestHdfsConfigFields list), `RBFConfigKeys`, `NfsConfigKeys`, HttpFS constants; resolve `"literal"`, `PREFIX + "suffix"`, and cross-class references with a small constant-resolution pass (iterate to fixpoint); capture `DEFAULT_*`/`*_DEFAULT` peers via the 3 conventions in `testXmlAgainstDefaultValuesInConfigurationClass`.
- **E2 Literal scanner** — all `src/main` java in hadoop-hdfs-project, two tiers: (a) targeted prefixes `dfs.|nfs.|httpfs.|hadoop.` (10 verified `hadoop.*`/`fs.*` keys are read in HDFS java, e.g. `hadoop.hdfs.configuration.version`); (b) any literal matching `VALID_PROP_REGEX` appearing as the key argument of a conf accessor (catches odd prefixes; call-site context filters false positives like metrics names). Captures call-site inline defaults (`conf.getX(key, inlineDefault)`). Also scans **all** C/C++ in hadoop-hdfs-native-client — verified read-sites: libhdfs++ reads `dfs.client.*`, `dfs.blocksize` and even deprecated `dfs.block.size`; fuse-dfs reads `hadoop.fuse.*`. (Web UI JS verified clean — reads config via JMX; shell scripts use env vars — out of scope by mechanism.)
- **E3 XML extractor** — `<name>/<value>` from hdfs-default.xml, hdfs-rbf-default.xml, httpfs-default.xml, core-default.xml, hdfs-fedbalance-default.xml.
- **E4 Deprecation extractor** — DeprecationDelta tables + `@Deprecated` constants + `DeprecatedKeys` class.
- **E5 Skip-list extractor** — parse skip sets and their comments from the Test*ConfigFields subclasses (institutional knowledge feed).
- **E6 Conf-access completeness sweep (inverse direction — the completeness proof)** — enumerate *every* `Configuration` accessor call site (`get*`, `set*`, `getTimeDuration`, `getPropsWithPrefix`, `getValByRegex`, …) in the subprojects; each must resolve to a known key, a resolvable constant expression, or be flagged `DYNAMIC/UNRESOLVED` for manual review. Verified need: 5 call sites use `getPropsWithPrefix`/`getValByRegex` and accept unbounded key *families* invisible to any literal scan — `HttpFSAuthenticationFilter.java:121` (`httpfs.proxyuser.*`), `HostRestrictingAuthorizationFilter.java:82` (fully dynamic prefix), `AuthFilterInitializer.java:46`, RBF Hikari passthrough ×2.
- **E7 Docs cross-referencer (optional enrichment)** — 28 files under `hadoop-hdfs/src/site/markdown` mention `dfs.*` keys; a key documented in a guide but absent from hdfs-default.xml strengthens the "add to xml" recommendation. Mentions, not definitions — feeds the assessment column only.
- **Validity filter** — reuse `VALID_PROP_REGEX`; keys ending `.`/`-` → DYNAMIC_PATTERN candidates.

**Usage analyzer** — shares one conf-accessor call-site enumerator with E6 (build it once; E6 consumes it for completeness, this for classification). Per key: count read-sites vs **write-sites**, across src/main vs src/test (constant identifier references + literal usages) → flags `UNUSED`, `TEST_ONLY`; set-only keys (e.g. `dfs.datanode.startup`, skip-listed as "not intended for users") are the mechanical signal for `INTERNAL`.

**Declaration-site signals (added after M1 spot-checks)** — two more mechanical inputs to the classifier, both observed in real findings:
- **Field visibility**: `dfs.ha.tail-edits.max-txns-per-lock` is `public static final` with a `_DEFAULT` peer (documentation candidate), whereas `dfs.namenode.snapshot.deletion.ordered` is package-private `static final` (internal). E1/E2 should record the declaring field's modifiers.
- **Declaring comment**: SnapshotManager declares its keys under `// The following are private configurations` — an explicit in-source statement that they must *not* be documented. Capture the comment above each declaration, as E5 already does for skip-list entries.

**Classifier** — one status per key: `ACTIVE_DOCUMENTED(which xml)` | `ACTIVE_UNDOCUMENTED` | `DEPRECATED_ALIAS(old→new)` | `DEPRECATED_UNUSED` | `INTERNAL_OR_TEST(skip-list reason)` | `DYNAMIC_PATTERN` | `DOCUMENTED_ELSEWHERE` | `DEAD` | `FALSE_POSITIVE(needs human confirm)`. Plus a default-value cross-check: DEFAULT constant vs xml `<value>` vs inline call-site default → `CONFLICT` flag (call-site defaults are coverage the base test does not have).

**Report generator** — one CSV + Markdown report, sorted by status, with per-key evidence (definition site, read sites, defaults). This is the complete list to attach to HDFS-11039 — it directly answers the 2018 committer question.

### Assessment and upstream phases

- **Phase A** — review `ACTIVE_UNDOCUMENTED` rows: add to hdfs-default.xml with `<description>` (or to the rbf/httpfs xml if owned there), or add to the skip list with a justified comment. Batch patches by area (snapshot, HA tail-edits, datatransfer allowlists, webhdfs oauth2, NFS, HttpFS) for reviewability.
- **Phase B** — close the NFS/HttpFS structural gap: document remaining `NfsConfigKeys` keys; optionally contribute `TestNfsConfigFields` / `TestHttpFSConfigFields` so the gap cannot reopen.
- **Phase C** — skip-list hygiene in TestHdfsConfigFields: resolve each "Fully deprecated properties?" entry (needs history: `git fetch --deepen` or GitHub blame — clone is shallow).
- Every xml addition must keep TestHdfsConfigFields/TestRBFConfigFields green — they are the regression harness.

### Verification

1. **Self-validation oracle**: E1-vs-E3 diff for hdfs-default.xml must reproduce exactly the skip-list entries (tests pass on trunk ⇒ any other diff is a scanner parsing bug). Same for RBF.
2. **E6 coverage + safety net**: at end of M2, every conf accessor call site is accounted for (resolved or explicitly flagged `DYNAMIC/UNRESOLVED`); and any *resolvable* key discovered only by E6 but missed by the E1/E2 forward scans is treated as an extractor bug — E6 thereby continuously validates E2's regex tiers.
3. Manual spot-check of ≥20 random keys at their definition sites.
3. Cross-validation: tiny Java program reflecting over released hadoop-hdfs/hadoop-hdfs-client jars from Maven Central (no Hadoop build) to verify constant resolution on a sample.
4. For xml patches: `mvn test -Dtest=TestHdfsConfigFields` (and RBF) in WSL2/Docker (`dev-support/docker`) or via PR CI (Yetus). The scanner itself never needs a build.

### Alternatives considered

- **Alt A — Java tool extending TestConfigurationFieldsBase into a report generator** (run via mvn): precise for constants but structurally blind to the 83 literal keys; requires full build. Rejected as primary; retained as spec source.
- **Alt C — reflection over published Maven Central jars**: no build, exact constant values, but pinned to released versions instead of trunk. Kept as sample cross-validation only.
- **Manual grep + curation**: not reproducible, cannot demonstrate completeness, rots immediately. Rejected.

## Critical files

- `hadoop-common-project/hadoop-common/src/test/java/org/apache/hadoop/conf/TestConfigurationFieldsBase.java` (extraction spec)
- `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/tools/TestHdfsConfigFields.java` (skip lists, regression harness)
- `hadoop-hdfs-project/hadoop-hdfs-rbf/src/test/java/org/apache/hadoop/hdfs/server/federation/router/TestRBFConfigFields.java`
- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/DFSConfigKeys.java` (2127 lines)
- `hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/client/HdfsClientConfigKeys.java` (564)
- `hadoop-hdfs-project/hadoop-hdfs-rbf/src/main/java/org/apache/hadoop/hdfs/server/federation/router/RBFConfigKeys.java` (477)
- `hadoop-hdfs-project/hadoop-hdfs-nfs/src/main/java/org/apache/hadoop/hdfs/nfs/conf/NfsConfigKeys.java` (95) + `NfsConfiguration.java`
- `hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/HdfsConfiguration.java` (deprecation registry)
- `hdfs-default.xml` (6763 lines), `hdfs-rbf-default.xml` (1055), `httpfs-default.xml` (337), `core-default.xml`

## Milestones

- **M1 — static extraction**: ✅ **COMPLETE** (delivered in `dev-support/hdfs-config-scanner/`, pure-Python 3 stdlib, no build required). All five static extractors implemented. Three checks all green: **oracle** (zero diff both directions for hdfs-default.xml and hdfs-rbf-default.xml; 635 compared keys each side for hdfs, 103 for rbf; all 17/11/3 skip-list entries resolved; 0 unresolved constants), **`scan.py verify`** (2138 records, 0 provenance mismatches — the mechanized form of the plan's "spot-check ≥20 keys"), and **17 hermetic unit tests**. Extractor totals: E1 778 constants, E2 570 literal keys / 573 sites, E3 1276 documented properties across 5 xml files, E4 146 deprecated names. Raw gap surfaced: 33 constants in no xml, 50 literal-only keys in no xml, 33 of those not deprecated.
  - Bugs the verifier/oracle caught and fixed: E1 line numbers anchored to the previous statement; E3 line mapping derailed by commented-out example properties; E2 counting native *test* sources (`libhdfs-tests/`, `libhdfspp/tests/` live under `src/main`) as production; phantom keys from concatenation fragments; core's own deprecation table (`Configuration.java`) unmined.
  - Closing audit of the extractors themselves (all four known-unknowns checked, no open gaps): **(a)** no multi-declarator fields exist in Hadoop's ConfigKeys, so that parser limitation is never exercised; **(b)** only 2 constants rejected by `VALID_PROP_REGEX`, both correctly (`'auxiliary-ports'` is a suffix whose composed key *was* extracted; `'default'` is an audit-logger name); **(c)** all 19 "partial" constants are genuine prefixes and correct dynamic-pattern candidates for M2 — two of them are exactly what `TestRBFConfigFields` skip-lists; **(d)** E2's accessor list was diffed against `Configuration`'s public API — 7 genuine property-keyed accessors were missing and 1 was a phantom, now fixed, with a selftest that fails if upstream adds an accessor that is neither scanned nor explicitly excluded. Impact of (d) on results: **none** (all 7 have zero call sites in HDFS) — the fix is preventive and matters for E6.
  - Known and accepted M1 limitation: **E2 and E4 have no oracle.** They are covered by provenance verification and unit tests, but their *completeness* is unprovable until E6's inverse sweep in M2 — which is precisely the reason E6 exists.
- **M2 — call-site analysis + inventory**: ✅ **COMPLETE**. Shared enumerator (`callsites.py`) powers E6 and the usage analyzer; classifier (`inventory.py`) + report (`report.py`) produce `out/hdfs-config-inventory.{csv,md}`. **All exit criteria met**: 1355 production call sites with **0 unresolved**; worklist of 107 runtime-computed sites and 11 dynamic families emitted; **1159 properties classified** — 681 ACTIVE_DOCUMENTED, 158 TEST_ONLY, 73 DEPRECATED_CONSTANT, 70 DOCUMENTED_ELSEWHERE, **63 ACTIVE_UNDOCUMENTED** (hdfs 25, nfs 14, rbf 13, httpfs 6, client 5), 58 DEPRECATED_ALIAS, 20 INTERNAL_SKIPLISTED, 17 EXTERNAL, 11 INTERNAL_PRIVATE, 8 NEEDS_REVIEW. M1's oracle still green; `verify` 2293 records / 0 mismatches; 29 unit tests.
  - **HttpFS reconstruction delivered**: `BaseService#getPrefixedName` yields `httpfs.<service>.<name>`, so a bare `authentication.type` read inside the `hadoop` service is rebuilt as `httpfs.hadoop.authentication.type` — matching httpfs-default.xml exactly. E1 still lists no httpfs classes on purpose.
  - **E6 validated the architecture**: 69 keys are reachable only via the call-site sweep, and **zero** came from a plain literal — every one came from a constant declared outside the classes the Java tests know about. E1 (registered constants), E2 (literals) and E6 (folded constants at call sites) each have a distinct, provable role.
  - Coverage/classification bugs found and fixed during M2: **`hadoop-hdfs-client` (307 sources) was absent from the module registry**, so client-only keys looked unused; static imports were unresolved (fixing it resolved ~293 more call sites); reads through helpers taking `(conf, KEY, default)` were invisible (e.g. `getUnitTestLong`); `hadoop-hdfs-project/hadoop-hdfs` is a string *prefix* of `hadoop-hdfs-rbf`, so every RBF property was attributed to hdfs; test-only writes masked production reads; prefix families (`getPropsWithPrefix`, keys ending in `.`) were misfiled as non-properties.
  - **Genuine Hadoop defects found, to report separately from HDFS-11039**: (a) `NameNode.java:2690` calls `getTimeDurationHelper(DFS_NAMENODE_SLOWPEER_COLLECT_INTERVAL_DEFAULT, ...)`, passing the default `"30m"` where the property *name* belongs; the same method uses the constants correctly seven lines earlier. Cosmetic (the name only surfaces in the parse-error message) but real, and unreachable by any forward scan. (b) `hdfs-default.xml` documents `nfs.allow.insecure.ports`, which `NfsConfiguration` deprecates in favour of `nfs.port.monitoring.disabled` — the documentation advertises a deprecated name. (c) 4 properties are defined twice across the default XMLs; `Configuration` silently keeps the last.
  - **Closing audit of M2 (mirrors the M1 audit; found and fixed 3 more defects)**: **(a) 73 live, documented properties were misclassified as `DEPRECATED_CONSTANT`** — DFSConfigKeys marks those constants `@Deprecated` only because they moved to HdfsClientConfigKeys ("dfs.client.block.write confs are moved to..."), which says nothing about the property. Documentation status now outranks constant-level deprecation, and `@Deprecated` survives as a CSV column instead of a status. **(b) `DFSUtil.getPassword(conf, KEY)` fell through both scans** — the direct scan skipped it (`DFSUtil` is not a Configuration) and the indirect scan skipped it because `getPassword` is also an accessor name; that hid `state-store-mysql.connection.password` in TEST_ONLY. **(c)** resource filenames (`hdfs-site.xml`) could enter the inventory through call sites, since only E1/E2 applied the partial-property filter. A systematic sweep of all 155 TEST_ONLY keys against production sources now leaves only `user.name` and `hflushtest.dat`, neither of which is an HDFS property. Final: **1158 classified, 65 ACTIVE_UNDOCUMENTED**, 31 unit tests.
- **M3 — assessment**: ✅ **COMPLETE**. E7 implemented (`e7_docs.py`) + `assess.py` producing `out/hdfs-11039-assessment.md` and `out/hdfs-11039-proposed-additions.xml`, plus `dossier.py` for the underlying evidence. **59 candidates across 12 review batches; 35 carry a description derived from Javadoc or a site guide, 24 are marked TODO** rather than given invented text. E7 found **9 candidates already explained to administrators in the site guides** yet absent from the defaults file — the strongest documentation case, and a source of authoritative wording.
  - Review pass demoted 6 candidates that are **not HDFS's to document**: `mapreduce.task.attempt.id` (MapReduce-owned, read only to detect MR context) and four `ssl.server.*` keys (owned by `ssl-server.xml`) now resolve as DOCUMENTED_ELSEWHERE after adding mapred-default.xml/yarn-default.xml/ssl-server.xml.example to the ownership list.
  - **Critical bug caught by reading the generated output**: descriptions were attaching each field the Javadoc of the field *above* it (the statement span opens just after the previous `;`, which sits on the previous field's line). `dfs.datatransfer.server.variablewhitelist.cache.secs` was about to be documented as "Path to the file containing subnets...". Fixed and regression-tested; the fix also corrected a misclassification (`dfs.namenode.snapshot.trashroot.enabled` is declared under FSNamesystem's `// The following are private configurations`, so it is internal, not a candidate).
  - **Third Hadoop defect found**, same family as the NameNode one and now detected by a general rule (a `*_DEFAULT` constant passed where a property name belongs): `DatanodeHttpServer.java:264` calls `getClasses(DFS_DATANODE_HTTPSERVER_FILTER_HANDLERS_DEFAULT)`, looking up a property named after the handler class, so the "hard coded class from the default configuration" fallback can never match.
  - **Closing audit of M3 (as for M1/M2; found 3 more defects)**: **(a)** mechanically re-verified *every* Javadoc-derived description against the source above its declaration — all 29 correct after the off-by-one fix. **(b)** Two site-guide descriptions were markup noise (`<name>nfs.aix.compatibility.mode.enabled</name>.` lifted from an xml *example* in the guide); guide text is now taken only from markdown table rows, which have a real description column, and is rejected if it contains markup, is too short, or merely repeats the key. **(c)** `mapreduce.task.attempt.id` was still being proposed for hdfs-default.xml: ownership by *declaration location* is not enough, because that key is injected by the MR framework at runtime and so appears in no `*-default.xml` at all — foreign namespaces (`mapreduce.`, `mapred.`, `yarn.`, `ssl.`) are now EXTERNAL by rule. Also fixed a markdown-emphasis regex that deleted the words it should have unwrapped. Final: **58 candidates, 11 batches, 32 evidence-backed descriptions, 26 TODO**, 37 unit tests, xml verified well-formed with no nested tags inside `<description>`.
  - **Ready to upstream now** (batches with zero TODOs, 25 properties): `datatransfer-allowlists` (16), `rbf-router` (4), `webhdfs-oauth2` (3), `ha-tail-edits` (2).
- **M4 — upstream patches**: ✅ **FIRST PATCH COMPLETE** on branch `HDFS-11039-document-config-properties` (uncommitted). **25 properties documented** across the four batches that needed no human-authored text: datatransfer allow/deny lists (16), webhdfs oauth2 (3), HA tail-edits (2), RBF router (4). Diff: +227/−2 over 4 files (hdfs-default.xml, hdfs-rbf-default.xml and the two comparison tests). Candidates fell 58 → 33; ACTIVE_DOCUMENTED 756 → 781. Both oracles green, 37 unit tests, provenance clean, both XMLs parse, longest added line 91 chars (checkstyle limit is 100).
  - **Key constraint discovered**: `TestHdfsConfigFields` runs with `errorIfMissingConfigProps = true`, so *adding a property to the xml fails the test* unless its constant is in `configurationClasses`. Every batch therefore needs a paired test change. The oracle reproduced that failure exactly before the test edit and went green after — the whole point of building it.
  - The oracle now **parses `configurationClasses` from the test file** instead of a hand-copied list in `registry.py`, so a test edit is immediately reflected and the two cannot drift.
  - **Defect caught in my own patch before it shipped**: the four `dfs.datatransfer.client.*.file` properties were written with `<value>fixedFile</value>` — the *name of a local variable*, because those keys default to whatever the matching server key resolved to (`conf.get(CLIENT_KEY, fixedFile)`). Root cause fixed (only *folded* values may become an xml `<value>`; raw expressions are kept separately and emitted as a comment), and the four blocks rewritten with an empty value and the fallback explained from the code.
  - **Remaining 33 properties are blocked on human input**: 26 have no Javadoc or guide text anywhere, concentrated in nfs-gateway (14, 10 TODO) and httpfs (6, all TODO). 7 of the 33 do have descriptions but sit inside batches that are otherwise TODO-blocked; splitting them out is possible if partial batches are acceptable to reviewers.
  - **Closing audit of M4 (as for M1/M2/M3): no defect in the patch itself**, but it exposed two areas the project had never examined systematically, both of which produced real findings — see "Findings not yet acted on" below. One more comment-attribution bug was fixed to get there: a comment heading a *group* of skip-list entries was attaching only to the first, which hid five of the six contradicted entries.

## Findings not yet acted on

Everything below is evidence-backed and reproducible from the tool; none of it is in the M4 patch.

**Documentation defects in the default xml files** (would be a natural second patch — no invented text required):
- **3 wrong default values**, where the xml states something the code does not: `dfs.datanode.directoryscan.throttle.limit.ms.per.sec` (xml `1000`, code `-1`), `dfs.federation.router.connection.pool-size` (xml `1`, code `64`), `dfs.namenode.backup.address` (xml `0.0.0.0:50100`, code `localhost:50100`). Surfaced by a check built in M2 whose output was never read; raw string comparison had buried them among 33 pure formatting differences (`5m` vs `300000`) until the comparison was made unit-aware.
- **6 properties excluded from `TestHdfsConfigFields` under a false premise.** The comment `// Fully deprecated properties?` — written with a question mark and never resolved — covers `dfs.corruptfilesreturned.max`, `dfs.datanode.non.local.lazy.persist`, `dfs.datanode.synconclose`, `dfs.metrics.session-id` (10 production reads), `dfs.namenode.replqueue.threshold-pct`, `dfs.namenode.tolerate.heartbeat.multiplier`. All six are still read by production code, none appears in any `DeprecationDelta` table, and none is documented. Resolving this was Phase C of the original plan.
- **4 properties defined twice** across the default xmls (3 in hdfs-default.xml — the `dfs.journalnode.kerberos.*` group — and 1 in hdfs-rbf-default.xml). `Configuration` silently keeps the last definition.
- **`nfs.allow.insecure.ports`** is documented in hdfs-default.xml although `NfsConfiguration` deprecates it in favour of `nfs.port.monitoring.disabled`.

**Hadoop code defects, each deserving its own JIRA** (found by the rule "a `*_DEFAULT` constant passed where a property name belongs"):
- `NameNode.java:2690` — `getTimeDurationHelper(DFS_NAMENODE_SLOWPEER_COLLECT_INTERVAL_DEFAULT, ...)` passes `"30m"` where the property name goes; the same method uses the constants correctly seven lines earlier. Cosmetic (the name only appears in a parse-error message) but real.
- `DatanodeHttpServer.java:264` — `getClasses(DFS_DATANODE_HTTPSERVER_FILTER_HANDLERS_DEFAULT)` looks up a property named after the handler class, so the "hard coded class from the default configuration" fallback can never match.

**Structural work still open:**
- 26 properties need a description from someone who knows the subsystem (nfs-gateway and httpfs dominate). Until then their batches cannot be upstreamed.
- No `TestNfsConfigFields` / `TestHttpFSConfigFields` exists, so those two modules still have no xml/constant enforcement — this is what would stop the gap reopening.
- 107 call sites compute their key at runtime and 34 dynamic key families exist; both are emitted as worklists and were never triaged, by design.
- 8 `NEEDS_REVIEW` properties remain genuine human judgement calls.

## Current state

*The milestone entries above are point-in-time records; each one's figures were
often revised by that milestone's own closing audit. The numbers here are the
current ones.*

**Classification today — 1157 properties:**

| Status | Count | |
| --- | ---: | --- |
| ACTIVE_DOCUMENTED | 781 | includes the 25 documented by the M4 patch |
| TEST_ONLY | 154 | |
| DOCUMENTED_ELSEWHERE | 77 | owned by core-default.xml and friends |
| DEPRECATED_ALIAS | 58 | |
| **ACTIVE_UNDOCUMENTED** | **33** | the remaining candidates; 26 need a description author |
| EXTERNAL | 21 | another component's namespace |
| INTERNAL_SKIPLISTED | 16 | 6 of these are excluded under a false premise (see above) |
| INTERNAL_PRIVATE | 9 | |
| NEEDS_REVIEW | 8 | |

- Branch `HDFS-11039-document-config-properties`, **uncommitted**: 4 modified Hadoop files (+227/−2). Nothing committed, nothing pushed.
- Untracked: `dev-support/hdfs-config-scanner/` (the tool, 37 unit tests) and `CONFIG_SCANNER_PLAN.md`.
- Verification, all green: `scan.py oracle` (both modules), `scan.py verify` (0 provenance mismatches), `scan.py sweep` (0 unaccounted call sites), `selftest.py` (37 tests).
- Generated deliverables in `dev-support/hdfs-config-scanner/out/`: the classified inventory (CSV + Markdown), the HDFS-11039 assessment, the proposed-additions xml, and the evidence dossier.
