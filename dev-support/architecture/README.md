# About these documents — definition and method

<!--
SPDX-License-Identifier: Apache-2.0
-->

This file is the canonical record of what the component architecture documents in
this directory **are** and **how they are produced and maintained**. Every
`hadoop-<component>-architecture.md` here points to it from a *Document method*
header block; when this file and a per-doc block ever disagree, this file wins.
It records principles only — component content lives in the per-component docs.

## 1. Definition

Each `hadoop-<component>-architecture.md` is a **source-grounded orientation
document for one component area** of Apache Hadoop:

- **As-of pinning.** The header names the exact apache/trunk commit the document
  describes (`**As-of:**` line). The document describes **merged trunk state
  only** — never behaviour from an open PR or an unmerged fork branch.
- **Depth-2 scope.** The component's modules plus their first-level subsystems
  (e.g. HDFS server internals are treated at `org.apache.hadoop.hdfs.server.*`
  granularity). Deeper detail is added only when a dedicated review session
  decides a subcomponent needs it.
- **Fixed skeleton.** Module map → per-module behaviour sections → cross-cutting
  sections: Behaviour summary, Concurrency, Security, Logging and auditability,
  Integration points, Non-functional requirement candidates. New sections are
  appended at the end; the skeleton is not reordered.
- **Grounding rule.** Every class, field, thread, and config key named in a doc
  is verified against the source tree at the As-of commit. No invented names, no
  behaviour that is not derivable from source or from the architecture itself.

## 2. Production method

1. Read the component's module layout from the source tree (pom modules, package
   layout), not from memory.
2. Write per-subcomponent behaviour sections at depth 2.
3. Analyse every subcomponent along the four cross-cutting dimensions:
   - **Concurrency** — which lock protects what, thread pools, thread ownership,
     shutdown ordering.
   - **Security** — Kerberos/SASL/tokens/ACLs and the classes that enforce them.
   - **Logging and auditability** — audit log surfaces, diagnostic log points.
   - **Integration points** — ports, protocols, wire formats, config keys.
4. Collect **NFR candidates** per document (a numbered candidate list, cited to
   the source evidence that motivates each).
5. Verify the finished document against source: class names greppable in the
   checkout at the As-of commit, section headers intact, `wc -l` plausible.
   A full regeneration fans out one worker per document with a self-contained
   brief and verifies the on-disk files after the batch.

## 3. Derived artifacts

- The requirements documents (`dev-support/requirements/hadoop-<component>-requirements.md`)
  are **derived from** the architecture documents: one falsifiable rule per
  stable ID (`FR-n` functional, `NFR-C-n` concurrency, `NFR-S-n` security,
  `NFR-L-n` logging, `NFR-I-n` integration), each with a citation
  `(arch §x.y, KeyClass)` to the architecture section and the enforcing class.
- A requirement without an `(arch §…, Class)` citation is malformed.
- The architecture doc's NFR-candidate list is carried over and superseded by
  the requirement IDs (mapping table in the requirements doc; candidates are
  never silently dropped).

## 4. Update policy

- **Merged trunk only.** Day-to-day PR-review sessions NEVER edit these
  documents. A PR fix is a candidate until its PR merges to trunk.
- **Candidate parking.** When a PR reveals the architecture is wrong, or the
  docs are silent on a touched subcomponent, the review session records a
  candidate entry in `notes/arch-req-candidates.md` (component/doc, the gap,
  proposed arch bullet(s) and FR/NFR text grounded in source at the merge base,
  reserved next-free ID(s), and the TRIGGER — the PR plus its merge event).
  Reserved IDs stay reserved: next-free-ID calculations skip them.
- **Dedicated sessions only.** Only a dedicated arch/req review session lands
  candidates: re-verify each entry's text against the NEW trunk state (candidate
  text may describe the fix declaratively; the landed code may differ), patch
  the docs (arch bullets + derived FR/NFR + checklist row in one commit), update
  the As-of header if the described state moved, commit on the docs branch and
  push. Entries whose PR landed differently or closed unmerged are rewritten or
  dropped.

## 5. Staleness and ID stability

- **Staleness check before any use.** Compare the doc's As-of trunk sha against
  the PR's merge base (`git merge-base` / ancestor test on the TRUNK sha, never
  the docs-branch commit). Any trunk change in the touched area since the As-of
  commit means re-verify the section against source before relying on it.
- **IDs never renumber.** A superseded ID keeps a mapping note in the
  requirements doc; it is not deleted, so citations in old review comments stay
  resolvable. New requirements take the next free number in their category,
  global to the document, placed in the component's section even where that
  breaks numeric order within the file.

## 6. Commit discipline

- The documents live on the fork's docs branch (`feat/ARCH`); they are never
  committed to `trunk`, which must stay a clean apache/trunk mirror.
- After any doc edit: line-count and header-structure check, `git diff --stat`
  over both directories, one commit naming what drifted, pushed to the docs
  branch.
