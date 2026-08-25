# Downstream evidence harness — proposal

Sub-task of HADOOP-19912 (Upgrade to Jetty 12.0). Covers HADOOP-19970, HADOOP-19971
and HADOOP-19972. Target 3.6.0.

Status: **proposal**. No harness code written yet.

## What this is

A script we run ourselves, outside the Hadoop tree and outside any CI. It takes
Hadoop refs, installs each into an isolated local Maven repository, and runs a
ladder of checks — from API signatures up to downstream test suites — reporting
the *difference* between refs rather than the raw result.

What goes on the issues is the report it produces. The script is a means to that
report and stays ours; reviewers are asked to weigh the evidence, not to adopt a
tool.

Two things depart from the issue as written:

1. It runs **three refs, not two** — last release, trunk, and the candidate —
   because the servlet coordinate has already moved once on trunk and a
   trunk-relative delta cannot see it.
2. The cheap downstream probe detects **duplicate classes in the resolved
   closure** rather than exclusions that stopped matching. The latter is full of
   years-old staleness; the former is the failure that actually bites.

## Why three refs

The servlet API coordinate moves twice between the last release and this change.
A trunk-versus-candidate comparison spans only the second move.

| Ref | Servlet artifact | `javax/servlet` classes |
| --- | --- | --- |
| Hadoop 3.3.6, 3.4.1 (released) | `javax.servlet:javax.servlet-api` | 79 |
| trunk today (pre-Jetty) | `jakarta.servlet:jakarta.servlet-api` 4.0.4 | 85 |
| trunk + HADOOP-19972 | `org.eclipse.jetty.toolchain:jetty-servlet-api` | 85 |

All three ship `javax/servlet/Servlet.class`, so Maven cannot tell them apart and
a downstream exclusion naming one silently ceases to apply when Hadoop switches
to another.

Ozone is the worked example. `hadoop-hdds/hadoop-dependency-client/pom.xml`
excludes `javax.servlet:javax.servlet-api` and `javax.servlet.jsp:*` from Hadoop
and declares its own servlet API. That exclusion already stopped matching on
trunk, before any Jetty work — so a two-ref run reports "no change" for the
project with the deepest exposure, and a reader concludes it is safe.

The report therefore carries two delta columns:

- **trunk → candidate** — "did this change break anyone", which is what a
  reviewer of HADOOP-19972 needs. This one gates the exit status.
- **release → candidate** — "will 3.6.0 break anyone", which is what the
  ecosystem needs and which no trunk-relative testing can produce. Reported, not
  gated: findings here are not this change's fault.

## The checks

Seven rungs, cheapest first, so a finding stops the run before the expensive ones
execute. Rungs 1–5 need no downstream compiler. Rungs 3–7 run on all three refs.

| # | Rung | Cost | What it does |
| --- | --- | --- | --- |
| 1 | API signatures | ~1 min per jar pair | A local copy of `checkcompatibility.py`, filtered to Public and LimitedPrivate, plus `--keep-internal` — which the in-tree version omits, so it silently skips every `impl` and `internal` package. |
| 2 | Shaded-client invariants | free | Run the existing `hadoop-client-check-invariants` modules on each ref. They already enforce `banDuplicateClasses` and `banTransitiveDependencies`. |
| 3 | Dependency-closure delta | ~10 min | `dependency:list` across every module, normalised and diffed. Turns HADOOP-19970's "the JSP API leaves ~85 classpaths" into a checked number. Baseline defaults to `git merge-base`, not trunk tip, so unrelated commits do not show up as findings. |
| 4 | Downstream closure composition | ~5 min per project | For each candidate at its pinned ref, resolve the effective closure against each Hadoop ref — resolution only, no compilation — and report artifacts contributing duplicate classes, plus exclusions that matched on one ref and not the next. This is where HADOOP-19972 shows up. |
| 5 | Synthetic consumer | ~2 min | A small project built and run against each ref: extends `HttpServer2`, installs an out-of-tree `SignerSecretProvider`, calls `CertificateUtil`. No candidate project ships an out-of-tree `SignerSecretProvider`, so this is the only rung that exercises HADOOP-19971's bridge. |
| 6 | Downstream compile | 1–3 h per project (estimate) | Each candidate built against each ref's repository, Hadoop version pinned to the same string throughout so the only difference is which repository is visible. Catches a Private class the ecosystem uses anyway. |
| 7 | Downstream tests | 2–6 h per project (estimate) | The downstream modules that touch HTTP, not the whole suite. Compared per test, never by exit code, and any test failing on one ref only is re-run on both before it is reported. The only rung that tests binary compatibility. |

Estimates on rungs 6 and 7 are unmeasured guesses.

## What gets built

A small private repository of our own, kept off any Hadoop branch so the trees
under review stay clean. Nothing here is proposed as a Hadoop patch.

| Path | What it is |
| --- | --- |
| `downstream-check` | Python 3. Drives the rungs, owns the three-ref logic and the flake protocol, writes the report. ~700 lines. |
| `projects/*.json` | One manifest per candidate: clone URL, pinned ref, the property naming the Hadoop version, build command, modules to test, build JDK, last-known-good date. Adding a project is a data change. |
| `consumer/` | The synthetic consumer of rung 5 — an ordinary Maven project depending on Hadoop from outside, which is the whole point of it. |
| `vendor/checkcompatibility.py` | A copy of the in-tree script with `--src-dir/--dst-dir` to reuse already-built trees, `--java-acc-dir` for offline use, and `--keep-internal` passed through. |
| `runs/<date>-<candidate>/` | One directory per run: the report, the raw rung output, and the environment record. These are the artefacts attached to the issues. |
| `README.md` | For us: how to run it, how to read two deltas rather than one, what a clean run does not mean. |

The `checkcompatibility.py` fixes are separable. Offline operation and
`--keep-internal` are real defects in a script Hadoop ships and documents. If they
prove useful here they are worth their own JIRA on their own merits — but nothing
in this work waits on that, and we run our copy meanwhile.

### Invocation

```
downstream-check \
    --release-ref rel/release-3.4.1 \
    --baseline    auto              # git merge-base(candidate, trunk)
    --candidate   HADOOP-19972 \
    --projects    hbase,ozone,tez,knox \
    --rungs       1-5               # 6,7 opt in explicitly
    --out         runs/2026-08-25-HADOOP-19972
```

Each ref becomes a `git worktree`, installed with
`-Dmaven.repo.local=<ref>/repo -Dmaven.repo.local.tail=<shared>`. The shared tail
holds everything that is not `org/apache/hadoop`; each ref's head holds only that
ref's Hadoop artifacts, and head wins over tail on identical coordinates. Between
refs, non-Hadoop artifacts pulled into a head are swept down into the tail so the
next one does not re-download the ecosystem.

### The evidence

Markdown to `report.md`: project, ref tested, outcome on each of the three Hadoop
refs, both deltas, and a diagnosis. A project that could not be tested gets a row
with the reason, never a missing row.

Because nobody else will run this, the report has to stand on its own. A reviewer
must be able to judge it — or reproduce it — from the page alone, so every run
records:

- **Exact refs and SHAs** for all three Hadoop trees and every downstream checkout.
- **The commands as executed**, verbatim, including Maven flags and repository paths.
- **The environment** — JDK, Maven and OS versions, and which JDK each downstream
  project used.
- **Raw output** for every rung, kept beside the report, so a claim can be traced
  to the log line behind it.
- **Failures unchanged.** A rung that failed on all three refs is reported as
  such rather than dropped; "this told us nothing, and here is why" is a result.

Non-zero exit when the trunk → candidate delta is worse — a convenience for us,
not a gate on anything.

## Candidates

Ranked by exposure to the surface at risk, read from each project's own POMs and
CI configuration. Shaded consumers cannot see Hadoop's internal coordinate
changes; unshaded ones can.

| Project | Consumes | Proposed use |
| --- | --- | --- |
| HBase | `hadoop-common`, `hadoop-auth`, `hadoop-hdfs`, `hadoop-minicluster` | Rungs 4–7. Unshaded, and the minicluster is where Jetty actually runs — the strongest HADOOP-19972 detector on the list. |
| Tez | `hadoop-common`, `hadoop-yarn-*`, `hadoop-yarn-server-web-proxy` | Rungs 4–7. Cheapest full-ladder run; do it first to shake out the harness. |
| Knox | `hadoop-common`, `hadoop-auth`, `hadoop-annotations` | Rungs 4–7. `hadoop-auth` is HADOOP-19971's surface. |
| Ozone | `hadoop-hdfs-client`, curated via `hadoop-dependency-client` | Rung 4 first. Embeds `HttpServer2` in `BaseHttpServer` and excludes the old servlet coordinate — its finding is already visible at resolution time. |
| Hive, Ranger, Atlas, Oozie | `hadoop-common` and friends, unshaded | Rung 4. Breadth at resolution level; build rungs only if time allows. |
| Spark | `hadoop-client-api`, `hadoop-client-runtime` | Rung 2 only. Shaded, so structurally blind to the servlet coordinate. A detector for HADOOP-19970, not 19972. |

## Alternatives

| Option | Trade | Proposed call |
| --- | --- | --- |
| japicmp or Revapi for rung 1 | Maven-native, no Perl, no unpinned download — but the existing checker is documented in BUILDING.txt and completes hadoop-common in about a minute. | Not here. Worth its own JIRA. |
| A linkage checker over the resolved classpath | Finds "method present but the jar left the classpath" without running downstream tests. Overlaps rung 4 and goes further, at the cost of a new tool in the loop. | Reserve — the fallback if rung 7 proves unrunnable. |
| Swapping only the servlet coordinate on a 3.4.x branch | A one-line synthetic change that isolates a rung-4 finding to the coordinate rather than to Jetty, without porting anything. | Reserve. Diagnostic, not routine. |
| Version-stamping the refs instead of isolated repositories | Makes the refs differ in coordinates, weakening the delta, and `versions:set` across ~90 modules is slow. | Not proposed. |
| Running inside `dev-support/docker` | Pins the toolchain and supplies per-project JDKs; costs image build time. | Both — `--jdk-home` per manifest, Docker documented for multi-JDK runs. |
| Contributing the harness to Hadoop | Would make runs reproducible by others, but adds a reviewable script plus pinned ecosystem revisions to a tree that has to maintain them. | Not proposed. We run it; the report is what we contribute. |

## Order of work

| Step | Work | Produces |
| --- | --- | --- |
| A | Copy `checkcompatibility.py` into `vendor/` and fix it there; run rungs 1 and 2 by hand. | The API compliance report the issue asks for, on day one — useful even if everything after it slips. |
| B | Harness skeleton: worktrees, split-repo install, three-ref driver, report writer. Rung 3. | The closure delta for all three branches. |
| C | Rung 4 across every candidate; rung 5. | The duplicate-class findings on both deltas, and the only evidence HADOOP-19971 can get. |
| D | Rungs 6–7. Tez, then HBase, then Knox and Ozone. | The results table, including honest "could not be tested" rows. |
| E | Write up each run and attach it to HADOOP-19970, 19971 and 19972. | The deliverable. |

A through C are a day or two and depend on nothing — and that is where the
evidence concentrates, since all three phases' findings land before a downstream
compiler ever runs. D is unattended wall-clock. If HADOOP-19972 needs to move
before D finishes, A through C alone are a substantially better answer than the
current one.

## Scope and limits

- **Local only.** Not a precommit gate, not a Hadoop patch, not in anyone's CI.
  It is run deliberately, by us, before these changes merge.
- **The report is the contribution.** The script is a means to it and stays ours.
- **A sample, not coverage.** A handful of projects, and only the paths their own
  tests exercise. A clean run is evidence, not proof.
- **Nobody else can re-run it.** That makes the recorded refs, commands and
  environment part of the claim rather than housekeeping — an unreproducible
  assertion is worth little on a JIRA.
- **The release delta will surface things this change did not cause.** Those are
  release findings, and must not be read as objections to HADOOP-19972.
- **It will rot, and that is fine.** Pinned downstream refs go stale between runs.
  Manifests carry a last-known-good date; the cost lands on us, not the project.

## Open questions

- Is the third ref worth its cost, or is trunk → candidate enough for this issue
  and the release question a separate one?
- Are rungs 6 and 7 worth running for every candidate, or only where rung 4 has
  already flagged something?
- How much raw output belongs on the JIRA itself, and how much is a link to an
  archived run?
- Do the `checkcompatibility.py` fixes go upstream as their own issue, or stay in
  our copy?

## Amendments from the first run

Recorded here rather than edited into the proposal above, so the changes stay
visible. See `RUNBOOK.md` for the operational detail.

- **Two refs per comparison, not one per phase.** The branches stack, so
  `jetty-phase-c` carries all three JIRAs and a single baseline → phase-c
  comparison answers the question. Phases a and b are built only when there is
  a finding to attribute.
- **`git merge-base` is not enough to pick a baseline.** All three phase
  branches share a merge-base with trunk, but they also carry four commits
  unrelated to these JIRAs. When the noise matters — a dependency-closure delta
  — the baseline is the commit below the first Jetty commit (`2add9630`), not
  the merge-base.
- **Rung 1 reads the installed repositories**, not the built trees, so each
  ~2.6 GB tree can be deleted after installing.
- **Maven 3.9.15 is a hard prerequisite**, enforced by the root POM.

## Basis

Figures above were measured, not assumed:

- Released POMs on Maven Central for the servlet coordinates (3.3.6, 3.4.1) and
  `hadoop-project/pom.xml` for trunk.
- `javax/servlet` class counts read from `jakarta.servlet-api` 4.0.4,
  `javax.servlet-api` 3.1.0 and `jetty-servlet-api` 4.0.6.
- `japi-compliance-checker` 1.8 compared hadoop-common 3.4.0 against 3.4.1 in 58 s
  under JDK 21, with the annotation filter applied, reporting one High and two Low
  method problems.
- Maven 3.9 split local repository: with the same SNAPSHOT coordinates in both,
  the head repository wins over `maven.repo.local.tail`.
- Candidate consumption read from each project's published POM; Ozone's
  `BaseHttpServer`, `hadoop-dependency-client` exclusions and JDK 25 CI read from
  an Ozone checkout.
