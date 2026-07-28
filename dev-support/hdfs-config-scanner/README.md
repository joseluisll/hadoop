<!--
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

# HDFS configuration scanner (HDFS-11039)

Builds a complete, evidence-backed inventory of HDFS configuration properties
and works out which of them belong in `hdfs-default.xml`.

[HDFS-11039](https://issues.apache.org/jira/browse/HDFS-11039) asks for
undocumented properties to be added to `hdfs-default.xml`. In 2018 a reviewer
asked *which* properties; the question was never answered. Answering it needs a
list nobody can produce by hand, which is what this tool generates.

Pure Python 3, standard library only. No Hadoop build required.

## Why not just extend the existing test

`TestHdfsConfigFields` (via `TestConfigurationFieldsBase`) already compares
`hdfs-default.xml` against `DFSConfigKeys` and `HdfsClientConfigKeys` by
reflection, and it passes on trunk. It is therefore structurally blind to
everything that is *not* a constant in the classes it is handed:

| Hiding place | Example |
| --- | --- |
| Keys spelled as literals elsewhere | `dfs.ha.tail-edits.max-txns-per-lock` in `EditLogTailer` |
| Modules with no comparison test | `NfsConfigKeys`, HttpFS |
| The skip lists themselves | entries commented `// Fully deprecated properties?` |
| Dynamic key families | `conf.getPropsWithPrefix("httpfs.proxyuser.")` |
| Keys owned by another file | `dfs.ha.fencing.*` in `core-default.xml` |
| Native readers | libhdfs++ and fuse-dfs read `dfs.*` from C/C++ |

## The oracle

Because `TestHdfsConfigFields` and `TestRBFConfigFields` run with both error
modes enabled and pass on trunk, they are an externally maintained ground
truth: once the declared skip lists are applied, constants and XML agree
exactly, in both directions.

So the scanner must reproduce a **zero diff**. Any surplus or missing key is a
bug in this tool, not a finding about Hadoop:

```bash
python scan.py oracle
```

Everything else the scanner reports is only as trustworthy as that check.

A second check covers provenance rather than key sets:

```bash
python scan.py verify
```

It re-reads every record's `file:line` and confirms the declaration really is
there, so a reviewer following a reference always lands on the right line.

## Running the process

Step by step, or all at once — **the same code either way**:

```bash
python scan.py step M1               # one step
python scan.py step M4 --apply
python scan.py pipeline              # M1 -> M4, analysis only
python scan.py pipeline --apply      # also write the batches that are ready
python scan.py pipeline --stop-after M2
```

Each step is defined exactly once, in `pipeline.py`. `scan.py step`, `scan.py
pipeline` and the individual commands (`oracle`, `inventory`, `assess`) all
invoke those same functions and differ only in how much of the result they
print — the stage carries its computed payload so a verbose renderer never has
to recompute anything its own way. Running the four steps individually and
running the pipeline produce byte-identical artifacts and the same findings;
only the point at which the "needs a human" list is printed differs, since a
single step reports its own blockers immediately while the pipeline collects
them at the end.

Each stage gates the next, and the run stops if one fails.

**Which stages need a human?**

| Stage | Input needed to run | Blocked afterwards by |
| --- | --- | --- |
| M1 static extraction | none | — |
| M2 call-site sweep + inventory | none | properties left `NEEDS_REVIEW` |
| M3 assessment | none | properties with no derivable description |
| M4 apply | **explicit `--apply`**, and an anchor in `PLACEMENTS` | batches that still contain a TODO |

So M1–M3 are fully automatic; the pipeline reports what a human owes it rather
than guessing. M4 is deliberately not automatic in two respects: it edits
tracked Hadoop files, so it stays read-only until you pass `--apply`; and it
refuses any batch containing a property whose description nobody has written.

Two safety properties matter more than the convenience:

* **Every applied batch is verified immediately** and rolled back if the oracle
  fails, so a run never leaves the tree half-patched. Adding a property to the
  xml *does* break `TestHdfsConfigFields` unless the declaring class is also
  added to `configurationClasses` — the runner derives those classes from the
  inventory and edits the test to match.
* **Re-running is idempotent.** Properties already present are skipped, so the
  pipeline is safe to run repeatedly as descriptions get written.

What the runner produces is a correct floor, not a ceiling: it emits the
Javadoc verbatim, and a reviewer may well write something better. The four
`dfs.datatransfer.client.*.file` entries in the current patch are hand-improved
to explain that they fall back to the matching server property — behaviour that
is visible in `setConf` but in no comment, so no generator could derive it.

## Commands

```bash
python scan.py assess                # M3: recommendations + ready-to-paste xml
python scan.py dossier               # evidence behind each candidate
python scan.py inventory             # the deliverable: classified CSV + Markdown
python scan.py sweep                 # E6: account for every accessor call site
python scan.py oracle                # validate against the Java tests
python scan.py verify                # check every record's file:line provenance
python scan.py summary               # extractor totals and the raw gap
python scan.py keys --module hdfs    # E1: key constants, with defaults
python scan.py literals -v           # E2: literal keys, with call sites
python scan.py xml --module hdfs     # E3: documented properties
python scan.py deprecations          # E4: deprecated aliases
python scan.py skips --module hdfs   # E5: skip lists with their reasons
python selftest.py                   # unit tests for the parsing internals
```

`--repo` points at a Hadoop checkout; it defaults to the enclosing one.

## Extractors

| | Source of truth | Module |
| --- | --- | --- |
| **E1** | `public static final String` constants in ConfigKeys classes | `e1_configkeys.py` |
| **E2** | String literals in Java and C/C++ sources | `e2_literals.py` |
| **E3** | `<property>` blocks in `*-default.xml` | `e3_xml.py` |
| **E4** | `DeprecationDelta` tables and `@Deprecated` constants | `e4_deprecations.py` |
| **E5** | Skip lists in the `Test*ConfigFields` subclasses | `e5_skiplists.py` |
| **E6** | Every `Configuration` accessor call site (inverse sweep) | `callsites.py` |
| **E7** | Property mentions in the site guides (enrichment only) | `e7_docs.py` |

E1–E5 work *forwards*: they find declarations and ask whether they are
documented. E6 works *backwards*: it enumerates every place configuration is
read or written and asks whether the key can be accounted for. Each role is
distinct and provable — of the keys only E6 reaches, **none** came from a plain
literal (which E2 would have caught); they all came from constants declared
outside the classes the Java tests know about.

Supporting modules: `javalex.py` (comment/string-aware views), `javamodel.py`
(type and field parsing), `jexpr.py` (constant folding), `symbols.py` (lazy
cross-file symbol table), `semantics.py` (the base test's filter rules),
`registry.py` (what to scan).

`semantics.py` reproduces `TestConfigurationFieldsBase`'s rules *including its
quirks* — the upstream `VALID_PROP_REGEX` contains a stray `%s` in a character
class, kept verbatim. The goal is to mirror what the test accepts, not what it
arguably meant to accept.

## Parsing notes

Hadoop's ConfigKeys sources need more than a regex:

* `HdfsClientConfigKeys` is an **interface**, so its fields carry no explicit
  modifiers yet are implicitly `public static final`.
* Constants are folded like the compiler would:
  `Read.ShortCircuit.KEY = PREFIX.substring(0, PREFIX.length() - 1)` resolves to
  `dfs.client.read.shortcircuit`.
* Names split across lines (`HdfsClientConfigKeys\n    .DFS_CHECKSUM_TYPE_KEY`)
  are one name.
* `getDeclaredFields` semantics: a nested type's fields belong to that type
  alone, so the class list must mirror the test's exactly.
* Comments are stripped before literal scanning — Javadoc mentions property
  names constantly, and a mention is not a declaration.
* `"dfs.some-policy" + ".suffix"` declares one key, not two; fragments are
  flagged rather than reported as phantom properties.
* Native tests do not live under `src/test`: `libhdfs-tests/` and
  `libhdfspp/tests/` sit under `src/main`, so test-only usage of keys like the
  deprecated `dfs.block.size` must not be counted as production usage.
* `*-default.xml` files carry commented-out example properties
  (`httpfs.proxyuser.#USER#.hosts`, `dfs.ha.namenodes`). Comments are blanked
  before line mapping, or every property after one gets the wrong line.

Anything that cannot be folded is reported as unresolved, never silently
dropped: an unresolved constant is a potentially missing property.

## Classification

`scan.py inventory` joins every extractor's evidence per property and reduces
it to one status. Order matters: author intent outranks usage counts, so a
`@VisibleForTesting` or package-private key is internal even when production
reads it. Nothing is guessed silently — each entry carries the evidence that
produced its status, and genuinely ambiguous keys become `NEEDS_REVIEW` rather
than being quietly filed away.

Signals that decide a status: deprecation registries, the tests' skip lists,
the declaring field's visibility, the comment above the declaration
(SnapshotManager's "The following are private configurations"),
`@VisibleForTesting`, an `INTERNAL_`-prefixed constant name, and read-versus-write
counts split across main and test sources.

One distinction matters more than it looks: **a `@Deprecated` constant does not
mean a deprecated property.** DFSConfigKeys marks 73 constants deprecated purely
because they moved to `HdfsClientConfigKeys`, while the properties stay live and
documented. Only a `DeprecationDelta` entry deprecates a property *name*, so
that is what drives `DEPRECATED_ALIAS`; the annotation is recorded as a column.

The skip lists get the same scepticism. A skip reason that states *intent*
("Property not intended for users", "Purposely hidden") is the author's
judgement and is trusted as-is (`INTERNAL_SKIPLISTED`). A reason that states a
checkable *fact* — it ends in a question mark, or claims the property is
deprecated or removed — is verified against the evidence, and when the
property is still read by production code, appears in no `DeprecationDelta`
table and carries no `@Deprecated` constant, the entry becomes
`SKIPLISTED_CONTESTED`: the claim is refuted, so a human must either document
the property or fix the skip-list comment. This is how
`dfs.ha.log-roll.rpc.timeout` ("Removed by HDFS-6440" — yet `EditLogTailer`
still reads it) and the "Fully deprecated properties?" group surface instead
of staying buried under a false premise.

## Proposed documentation

`scan.py assess` turns the candidates into per-property recommendations and a
ready-to-paste xml file, split into review batches by subsystem — reviewers know
those areas separately, and one patch of sixty properties does not get read.

Descriptions are **derived, never invented**: each comes from the Javadoc on the
declaring constant or from the site guide that already explains the property,
and the source is recorded beside it. Where neither exists the entry carries an
explicit TODO. A confidently wrong description in hdfs-default.xml is worse than
a missing one, because operators act on it — an early draft attached each field
the Javadoc of the field *above* it, which is precisely how that happens.

## Applying a patch

Adding a property to `hdfs-default.xml` is not enough on its own:
`TestHdfsConfigFields` runs with `errorIfMissingConfigProps = true`, so an xml
property whose constant is not in `configurationClasses` **fails the test**.
Each documentation batch therefore pairs an xml change with a test change.

The oracle checks both without building Hadoop — it reads `configurationClasses`
straight from the test file, so run it after every edit:

```bash
python scan.py oracle
```

## Status

M1 (static extraction), M2 (call-site analysis, classification, reporting),
M3 (assessment and proposed xml) and the first M4 patch (25 properties
documented) are complete, each closed with an audit of its own output. Every check passes: the oracle on both modules, `verify` with 0
provenance mismatches, `sweep` with 0 unaccounted call sites, and 51 unit tests.
1157 properties are classified; 58 are undocumented candidates, 32 of which
already have an evidence-backed description. Four batches (25 properties) have
no TODOs and are ready to upstream.

**HttpFS names are reconstructed.** It has no ConfigKeys class;
`FileSystemAccessService` declares `AUTHENTICATION_TYPE = "authentication.type"`
and reads it from a service-prefixed sub-`Configuration`. `BaseService#getPrefixedName`
yields `httpfs.<service>.<name>`, so the scanner rebuilds
`httpfs.hadoop.authentication.type` at the call site — matching httpfs-default.xml
exactly. E1 still lists no httpfs classes on purpose: extracting those constants
directly would publish bare suffixes as property names.

Next, M3 turns the inventory into per-key recommendations with proposed
`<description>` text, then M4 upstreams them in reviewable batches.
