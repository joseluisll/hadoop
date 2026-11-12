# Adoption proposal — automated license generation and verification, in two increments

How HADOOP-20078 ([https://issues.apache.org/jira/browse/HADOOP-20078](https://issues.apache.org/jira/browse/HADOOP-20078))
would be adopted in practice, from the point of view of the release
manager and the PMC. Two increments, both carried by GitHub Actions
workflows, each independently acceptable. The operator's view is in
`rm-runbook.md`; the evidence is in `README.md` and `deviations/`.

## Summary

- **Increment 1 — evidence and optional tooling, zero process change.**
  A set of opt-in, secret-free workflows any committer can run: verify a
  staged release candidate (signatures, checksums, license checks), and
  — optionally — produce an unsigned release-candidate bundle so the
  release manager does not need to maintain a build host for the heavy
  part. Nothing in the release procedure changes; the workflows only
  prepare and verify.
- **Increment 2 — the enforcement ask.** The same license check runs
  inside `create-release` on the RC build: the build fails unless the
  license files match the tarballs being voted on. The release manager's
  command line is unchanged; the RC carries two extra artifacts.

## The release-manager flow (increment 1, optional)

All workflows run on GitHub's infrastructure, produce public runs, and
hold no secrets. Every credential-bearing step stays exactly where
HowToRelease puts it today — with the release manager, offline.

### Producing a candidate bundle (optional convenience)

The RM (or any committer) dispatches the `build-rc-unsigned` workflow on
a release tag. It runs the same build process as `create-release`
(signing and staging deliberately omitted — the script supports this
mode), and then runs the license step on the tarballs it just built.
Two outcomes:

**Everything checks out (GREEN).** The run publishes a *ready-to-sign
bundle*:

- the binary and source tarballs, with SHA-512 checksum files;
- the THIRD-PARTY dependency report;
- the generated LICENSE-binary and licenses-binary/ texts;
- a short **offline checklist** for the RM — the exact remaining
  commands, in order: re-verify the checksums, sign each artifact with
  the release key (`gpg --detach-sign`), copy to the release directory,
  stage to the SVN dev location, close the Nexus staging repository,
  create and push the signed RC tag, and send the vote email (a draft is
  included, with the license-verification run linked).

The credentials begin where the run ends. Signing, staging, Nexus, and
tagging stay with the RM, on the RM's machine — precisely as in
HowToRelease today. What changes is that the RM no longer needs to
maintain a Docker build host for the multi-hour build, and never signs
license files that have not been verified against the archive.

**Something is wrong (RED).** The run publishes a *fix list* instead:
for every failed item — a shipped jar with no license statement, a stale
version, a listed component that ships nothing — it names the exact
entry and the small configuration file where the change belongs (a
dependency exception, an override, a text alias). The fix is a normal,
reviewed pull request to that configuration file; nobody edits the
license files by hand. Re-run the workflow; the bundle appears when the
fix list is empty.

### Verifying a staged candidate (the evidence workflow)

The `verify-rc` workflow downloads a staged RC from the dev staging
area, verifies the GPG signatures against the project's public KEYS
file and the SHA-512 checksums, re-runs the license checks on the
downloaded tarballs, and publishes a public summary. It needs no
credentials, so any voter or PMC member can trigger it — or read the
run linked from the vote email.

### Also available (optional, same spirit)

- a vote-email assembler (links, checksums, verification-run link, the
  lean-tarball note);
- release-document generation (CHANGELOG / RELEASENOTES drafts from the
  public JIRA) attached to the run;
- a pre-promotion completeness check (every artifact present, signed,
  checksummed, license-verified) before the final promotion.

All of these prepare work for the RM; none of them execute a
credential-bearing step.

## The adoption ask (increment 2)

Once the PMC is satisfied by what the verification shows, the same
license step is wired into `create-release` itself, on the RM's host:
after tarball assembly, before signing, the build fails unless the
license files match the archive — every shipped jar covered, nothing
listed that does not ship, the shipped texts matching the file, and the
committed file equal to the freshly generated one. Failure messages name
the exact entries (the same fix list as above).

The RM's procedure is otherwise unchanged: same host, same command, and
two artifacts (THIRD-PARTY.txt and the generated license files) join the
usual signature/checksum set, with one line added to the vote email.

The GHA verification workflow continues to exist unchanged: it is the
public, linkable evidence layer for the vote. The in-build step is
authoritative — it blocks the RC — while the workflow is advisory but
public; both run the same check with the same inputs, so they agree by
construction.

| Workflow | Increment 1 | Increment 2 |
|---|---|---|
| verify-rc | optional, public evidence | unchanged; same checks now also enforced in-build |
| build-rc-unsigned | optional convenience | unchanged; the RM's own signed build (with the hook) remains the official path |
| vote-email / docs / pre-promotion | optional conveniences | unchanged |

## Evolution: host-free RC production (optional, after increment 2)

If release managers find the build-host burden worth removing, the same
two workflows compose into a further step: the RC-build workflow produces
the candidate on GitHub's infrastructure (unsigned, unstaged, license
checks included), and `create-release` gains a mode that downloads that
bundle, re-verifies it locally — the checksums, and optionally the
license checks again, so the release manager relies on his own
verification, not on CI — then signs the artifacts and assembles the RC
directory. Signing, staging, Nexus and tagging stay with the release
manager, as today. In this shape the build workflow becomes the
producer and the verification workflow remains the downstream public
check: together they bracket the credential-bearing steps from both
sides, and a red build result stops the process before anything is
signed.

The one open question in this evolution is the Maven staging on Nexus:
today `--asfrelease` builds and stages the module jars in a single step,
while a workflow-produced build leaves the staging set either to a
lightweight local build kept for that purpose, or to the workflow
uploading its Maven repository for REST-based staging. Both are viable;
this is a decision for the release managers, and the plan is to
prototype the full chain on the project fork before proposing it.

## What this proposal does not ask

- **No change for developers.** License fixes are configuration changes
  in normal pull requests. A development-time check in the precommit
  pipeline (so contributors see license findings where they already
  look) is a natural follow-up, proposed separately — this proposal
  deliberately carries none of it.
- **NOTICE-binary stays hand-written.** It is curated prose; the checks
  verify its coverage but never generate it.
- **No build-infrastructure changes** (image caching, download retry)
  ride along; those are separate concerns with their own change path.

## Evidence (all reproducible from this package)

| Question | Answer | Where |
|---|---|---|
| Does the generated file describe the archive? | Exact: every shipped jar covered, every version the archive's own, nothing declared that does not ship | `deviations/like-for-like.txt` |
| How does it compare with the official 3.5.0 files? | 46 shipped jars unlisted → 0; 6 wrong group → 0; 10 stale versions → 0; 107 ship-nothing entries → 0 | `README.md`, `deviations/` |
| Does verification at RC time cover what ships? | No license file changed between the last RC and the final release in 3.4.3 or 3.5.0 (final tag == RC commit; analysis in the HADOOP-20078 description) | HADOOP-20078 |
| Can a jar be silently skipped? | No: unnameable jars and empty enumerations fail by design | enumeration records |
| Is the output stable? | Deterministic; synthetic test suites per tool | `dev-support/licenses/test-*` |
| Cost of adapting a release line | One recorded pass (8 texts + 8 exception rows for branch-3.5) | `dev-support/licenses/2026-11-09-*.md` |

## Status and sequencing

- The license system exists and has been validated end to end against
  the official 3.5.0 release artifacts; the checks run on every push and
  every distribution build on the feature branches (months of green CI).
- Increment 1's verification of the official 3.4.3 artifacts is planned
  as the second provenance set in this package (3.5.0 is done).
- The `build-rc-unsigned` flow has been demonstrated in equivalent form
  (release-shaped distribution builds with the full check suite on
  GitHub-hosted runners); the literal `create-release` invocation in
  that mode is the planned prototype on the project fork, on trunk.
- Building the aarch64 tarball on GitHub's arm64 runners is possible but
  not yet validated; the x86 flow is the core and arm builds remain an
  RM-side option as today.
- The runbook for the RM (`rm-runbook.md`) describes the day-of-release
  experience with the step adopted.

Increment 1 costs the project nothing and can be tried on the next RC —
or retroactively on any past release. Increment 2 is a decision for a
release cycle; the natural candidate is 3.6.0.
