# Upstream dev-support findings vs the adoption proposal (T00033)

How the verified upstream facts bear on `adoption-proposal.md` and its
increment-1/2 framing. Inputs: the upstream trunk tree (verified
2026-11-12), the owner's two comments on apache/hadoop#8943
(2026-11-12 14:36Z and 17:46Z), and the T00031 HBase 2.5.16 audit
conclusion. Operator (RM/PMC) viewpoint; tooling internals stay in the
references.

## What upstream actually has (verified)

| Concern | Upstream today | Gap the proposal fills |
|---|---|---|
| Binary archive vs LICENSE-binary | **Nothing.** No tool enumerates a binary tarball or diffs it against the license file | The entire increment-2 check |
| Source headers | `apache-rat:check` in `create-release` and in `hadoop-vote.sh` | Unrelated to third-party binaries |
| LICENSE/NOTICE embedded in Hadoop's own jars | `verify-license-files` (HADOOP-13374, 2018) | Checks Hadoop's own jars only, never the third-party set |
| Shaded-pom headers | root-pom `license-maven-plugin` (`update-file-header`) | Not a verification step |
| Voter-side RC verification | `dev-support/hadoop-vote.sh` (HADOOP-18098, 2022): gpg signatures, sha512 checksums, RAT, build-from-source — verified live on trunk 2026-11-12; its own header tells operators what "may still [be verified] manually" | Binary license coverage is on the voter's manual list today |

Conclusion of the table: **the proposal's license step has no upstream
counterpart at all.** Increment 2 (create-release hook) and the
verify-rc evidence workflow both add something that does not exist in
any form — they are not replacing or duplicating anything upstream.

## The comparator question after the T00031 audit

The original talking point used HBase as the adoption precedent. The
T00031 audit conclusion changes its shape:

- **Still true (lineage):** hadoop-vote.sh is a port of hbase-vote.sh,
  which came from Apache Spark — RM *tooling* adoption across ASF
  projects is normal practice, and Hadoop already participated once.
- **Dead (comparator):** HBase's own binary LICENSE handling is
  nothing more than a manual process — the file is generated from POMs
  at build time, never verified against the shipped archive, and the
  audit surfaced a concrete drift defect (LICENSE.txt declares jQuery
  1.8.3 / jQuery Foundation; the shipped jquery.min.js is 3.7.1 /
  OpenJS). No ASF project automates this; **Hadoop would be first.**

Rewrite consequence: the proposal should claim lineage for *release
tooling adoption* but must not cite HBase as a license-computation
precedent. "First" is the stronger and now-verified claim.

## What the #8943 comments already proved

The owner's two comments on apache/hadoop#8943 landed increment-1-style
evidence on a live upstream PR before any proposal was posted: the
3.5.0-vs-trunk drift table (52/69 missing, 107/43 stale, 10/22 version
mismatches) and the unused-Netty dry-run scan (11 unreferenced modules
in hdfs/lib, +3 in the catalog WAR, identical on trunk). Reception:
pan3793 approved and merged the owner's PR #8940 on branch-3.5 the same
week and had asked the pruning question the data answered. Evidence
posted where committers already look drew engagement without any
process ask attached. This is the increment-1 adoption model working
as designed, and it argues for keeping "evidence first, enforcement
second" as the public sequencing.

## The design fork (owner decides)

**Option A — extend hadoop-vote.sh with the license driver.**
The license check becomes a fourth vote in the script voters already
run (signatures, checksums, RAT, build). Zero new CI surface, no
INFRA/policy question, continues the Spark→HBase→Hadoop port lineage,
and it puts the check exactly where the "verify manually" list admits
the gap. Costs: voter-side only, per-voter manual execution — no public
linkable run; the driver must run on the voter's machine (a Docker dist
build, or a lighter verify-only mode); the RED result is diagnostic
(staged artifacts are already signed — the fix is a new RC); and it is
an edit to a real upstream file, so it carries the same review burden
as any patch, just to a script rather than a workflow.

**Option B — the proposal as written (GHA verify-rc + increment-2
create-release hook).** Public, secretless, linkable evidence runs any
voter or PMC member can trigger; the in-build step is the enforcement.
Costs: new CI surface on apache infrastructure (the GHCR/packages
policy question, T00000, still open with INFRA) and a visibly new
workflow in the release path — the larger adoption ask.

**Option C — both, as a sequence.** A hadoop-vote.sh extension is the
cheap bridge that needs no INFRA answer; the GHA workflow remains the
public evidence layer, and the create-release hook is the end state.
The proposal's own "both run the same check with the same inputs, they
agree by construction" property extends naturally to a third surface.

Observation for the choice: the #8943 engagement happened because
evidence was public and in-context. Only Option B/C produce public,
linkable runs; Option A alone keeps verification private to each voter.

## Feed into the adoption-proposal rewrite

1. Add the verified upstream-gap table (this file) to the evidence
   section — it is the "what exists today" baseline the proposal
   previously asserted without citations.
2. Replace the HBase-comparator phrasing with the lineage + first-mover
   claim (T00031 conclusion).
3. Cite the #8943 comments as the first public increment-1 evidence.
4. Add the Option-A surface (hadoop-vote.sh extension) as an explicitly
   optional low-infra bridge — **owner pick 2026-11-12: Option C** (both,
   sequenced: hadoop-vote.sh extension as the cheap no-INFRA bridge, GHA
   verify-rc as the public evidence layer, create-release hook as the
   end state).
5. T00032 (Spark create-release lineage) remains open and can still
   strengthen the lineage paragraph; the rewrite does not block on it.
