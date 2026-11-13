# Releasing Hadoop with the automated license step — a runbook for the release manager

How the release procedure feels from the release manager's chair once
the license system from [HADOOP-20078](https://issues.apache.org/jira/browse/HADOOP-20078)
is adopted. Written as an operator's view; the technical detail lives in
the rest of this package and in `dev-support/licenses/` on the feature
branches.

**In one sentence:** one automated step runs inside the RC build, and the
RC carries two extra artifacts. Everything else in HowToRelease is
unchanged.

## Before the release: nothing

There is no license work for the release manager to schedule before a
release. The license files are maintained by ordinary development pull
requests: every push re-checks that the committed files are exactly what
the system would generate, so when RC day arrives the files are already
correct — or the tree is already red on the specific dependency that
introduced the gap, long before an RC is cut. There is no "license
sprint" before a release.

## Building the RC: one step runs itself

You run the RC build exactly as today (`create-release` on the docker
host, `--asfrelease`). Inside that build, after the tarballs are
assembled and before anything is signed or staged, the license step runs
on the exact tarballs being produced. It:

1. lists every jar the archive ships — including jars inside WARs — and
   resolves each to its Maven name (jars it cannot name fail the build;
   they are never silently skipped);
2. collects the dependency report (THIRD-PARTY.txt: every dependency
   with its license names and versions, from an opt-in Maven profile);
3. generates LICENSE-binary and the `licenses-binary/` text directory
   from those two lists and the version-controlled license-text store;
4. verifies, and fails the build unless: every shipped jar is covered by
   the license file; everything listed actually ships (or is inside a
   shaded jar, or has a recorded reason); nothing excluded from the
   build still ships; the shipped texts match the license file; and the
   committed file equals the freshly generated one — so a hand-edited or
   stale license file cannot ride into an RC.

The step runs offline against the already-built tarballs; it does not
change the build, the artifacts, or any developer workflow.

## When the step fails

The failure message names the exact entries. The fix is never editing
the license files by hand: it is a small change in a reviewed
configuration file (a dependency exception, an override, a text alias),
normally made in the pull request that introduced the dependency. Then
re-run the build.

The cost of this is bounded and recorded. Adapting the system to the
whole branch-3.5 release line took one pass: 8 license texts for
components that no longer ship, and 8 exception entries reconciled —
each backed by archive evidence (see the
`dev-support/licenses/2026-11-09-*.md` records on the branch). The
checks also flag configuration that no longer matches anything, so
stale configuration gets removed instead of piling up between releases.

## Publishing the RC: two extra artifacts

The verified RC now carries, alongside the usual
tarball/signature/checksum set:

- **THIRD-PARTY.txt** — every shipped dependency with its license and
  version;
- the **generated LICENSE-binary** and **licenses-binary/** that match
  the tarball exactly.

Copy them into the staging directory next to the other artifacts and add
one line to the vote email pointing at them. Any voter can then check
the license claim against the archive instead of trusting a file someone
last edited months before the release — a one-command verification
rather than an audit.

## The vote and after: nothing new

The vote itself is unchanged (72 hours, dev@, same process). After it
passes there is no further license work: the files were generated from,
and verified against, the tarballs being voted on, so what was verified
is exactly what gets promoted.

This matches observed practice in the project's own history: in both
recent releases the final release commit is the last RC commit, byte for
byte — no license file changed between "voted on" and "shipped"
(3.4.3 and 3.5.0, verified from the final release tags; the analysis is
recorded in the HADOOP-20078 description).

## Maintenance releases later

The next RC build re-verifies everything from scratch. A dependency
added since the last release fails the build until it is listed, and the
build says what to add. A component removed stops being listed at the
next generation. The license files cannot silently fall behind the
archive again.

If the project wants to trim what ships, the same archive build also
writes an informational unused-jar report: per jar, who references it
and which module pom declares it (on 3.5.0: 26 artifacts nothing
references). It never fails a build and is not part of the RC step;
dropping a jar stays a normal, reviewed dependency change.

## What this rests on (evidence)

The claim above is only as good as the system behind it. The evidence,
all reproducible from this package:

| Question | Answer | Where |
|---|---|---|
| Does the generated file describe the archive? | Exact: every shipped jar covered, every version the archive's own, nothing declared that does not ship | `deviations/like-for-like.txt` |
| How does it compare with the official 3.5.0 files? | 46 shipped jars unlisted → 0; 6 wrong group → 0; 10 stale versions → 0; 107 ship-nothing entries → 0 | `README.md`, `deviations/` |
| Can drift slip in after verification? | No: continuous checks on every push and every dist build keep the committed file equal to the generated one; all failures are loud and name their entries | `dev-support/licenses/` gate records |
| Is the output stable? | Deterministic for the same inputs; synthetic test suites cover each tool's passing and failing paths | `dev-support/licenses/test-*` |
| Can a jar be silently skipped? | No: unnameable jars and empty enumerations fail the build by design | enumeration records |
| Does verification at RC time cover what ships? | Yes: no license file changed between the last RC and the final release in 3.4.3 or 3.5.0 (final tag == RC commit; analysis in the HADOOP-20078 description) | HADOOP-20078 |
| What does adoption cost per release line? | One recorded curation pass (8 texts + 8 exception rows for branch-3.5) | `dev-support/licenses/2026-11-09-*.md` |

## Status

- The step exists and has been validated end to end against the official
  3.5.0 release artifacts (see `README.md`).
- A prototype on the project fork reproduces the RM flow — build RC,
  step runs inside, artifacts ready for staging and the vote — see
  HADOOP-20078 for the proposal and prototype links.
- NOTICE-binary stays hand-written: it is curated prose. The step checks
  its coverage (every attribution-required component is mentioned,
  covered by a component text, or carries a recorded justification) but
  never generates it.
