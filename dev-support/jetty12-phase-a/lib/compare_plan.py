#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Check that the candidate is the baseline plus the PR branches, and nothing else.

Usage:
  compare_plan.py --baseline REF --candidate REF [--branch REF ...] [--out DIR]

What is merged into trunk is the PR branches of the tickets, in the order the
owner merges them. The tested candidate is built by merging the same branches,
so its change against the baseline must be their combined change and no more.
When it is not, the tested tree is not what will be merged: a commit the
candidate lacks (an older trunk than the baseline, which ancestry.py checks)
or a change no branch makes. Either would be reported as a difference the
patch causes.

Per file changed by a branch, the candidate's blob must be the baseline's
blob with that branch's change applied. A file changed by one or several
branches is replayed in branch order as a three-way merge: the baseline blob
as ancestor, each branch's change for the file (its base blob to its tip blob)
merged on top with git merge-file. Paths ignored for every branch: the harness
and .github/ (only the baseline's fork commits change them).

Reported as differences:
  candidate-only   changed on the candidate, by no branch
  replay-differs   changed by one or several branches and the replay does not
                   give the candidate's blob
  missing          changed by a branch, not changed on the candidate

A branch already merged into the baseline is left out of the replay and listed
as landed: merged as commits (its tip is an ancestor of the baseline) or
squashed (a baseline commit since the branch's base has the branch's whole
change as its patch, by git patch-id). A branch only partly in the baseline is
not landed, and its files show as missing or replay-differs.

Two replay cases cannot be reproduced and are reported, never hidden:
  - a binary blob (LICENSE-binary, NOTICE-binary): git merge-file merges bytes
    as text. A branch's change to a binary blob is applied whole, so a later
    branch replaces an earlier one's change.
  - a conflict: the candidate resolved it by hand. NOTICE-binary's known case:
    HADOOP-20013 removes 'javax.annotation:javax.annotation-api' and
    jetty-phase-a removes 'javax.servlet:javax.servlet-api'; replaying either
    order keeps one line and drops the other, while the candidate drops both.
    That resolution is what both tickets intend. List it in NOTICE_REPLAY and
    the file stops being a difference; an entry for a path a branch changes
    counts as used even when the replay matches, and an entry for a path no
    branch changes is reported as unused.

The branches and their order come from PR_ORDER below; --branch arguments
replace them. IGNORED and NOTICE_REPLAY below are edited in place when a branch
changes them.
Writes DIR/compare-plan.json and DIR/compare-plan.md (DIR defaults to the
current directory) and prints the verdict. Exits 1 when the candidate is not
the plan, 2 on a usage or git error.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gitrefs import changed_paths, git, patch_ids, rev_parse, tree_blobs  # noqa: E402

# The branches merged into trunk, in the order they are merged. jetty-phase-a is
# HADOOP-19970 (PR #8699); the others are PRs #8890 to #8894. The order matters
# only for a file several branches change.
PR_ORDER = [
    "origin/HADOOP-20012-upstream",
    "origin/HADOOP-20014-upstream",
    "origin/HADOOP-20013-upstream",
    "origin/HADOOP-20015-upstream",
    "origin/HADOOP-20016-upstream",
    "origin/jetty-phase-a",
]

# Ignored for every branch, relative to the repository root.
IGNORED = ["dev-support/jetty12-phase-a/", ".github/"]

# A file whose branches' changes conflict and whose candidate blob is the
# resolution both tickets intend: lines to drop and lines to add.
NOTICE_REPLAY = {
    "NOTICE-binary": {"drop": [" * javax.servlet:javax.servlet-api",
                              " * javax.annotation:javax.annotation-api"],
                      "add": [" * jakarta.annotation:jakarta.annotation-api"]},
}


def blob(sha):
    """A blob's content; empty when the path does not exist (None)."""
    if not sha:
        return b""
    return git("cat-file", "blob", sha, binary=True) or b""


class Branch:
    """One PR branch: its base, its tree, and the files it changes."""

    def __init__(self, ref, baseline, ignored):
        self.ref = ref
        self.base = rev_parse(git("merge-base", baseline, ref).strip() or "")
        self.base_blobs = tree_blobs(self.base)
        self.blobs = tree_blobs(ref)
        self.paths = changed_paths(self.base, ref, ignored)

    def change(self, path):
        """The branch's change to a path as (ancestor blob, tip blob), or None
        when it does not change there. Either is None when the branch's base
        or tip lacks the file (added or deleted)."""
        anc = self.base_blobs.get(path)
        tip = self.blobs.get(path)
        if anc == tip:
            return None
        return anc, tip

    def landed(self, baseline):
        """The baseline commit that already has this branch's change, or None.
        A branch merged as commits changes nothing since its base, which is
        then its tip."""
        if not self.paths:
            return self.base if self.base == rev_parse(self.ref) else None
        paths = sorted(self.paths)
        mine = patch_ids(git("diff", "--binary", self.base, self.ref, "--", *paths,
                             binary=True))
        theirs = patch_ids(git("log", "-p", "--binary", "--format=commit %H",
                               f"{self.base}..{baseline}", "--", *paths, binary=True))
        return next((theirs[p] for p in mine if p in theirs), None)

def replay(baseline_blob, branches, path):
    """The baseline blob with each branch's change merged in order, and the
    branch names whose change conflicted or hit a binary blob. None when the
    replay deletes the file."""
    current = blob(baseline_blob)
    unresolved = []
    with tempfile.TemporaryDirectory() as tmp:
        names = [os.path.join(tmp, n) for n in ("replayed", "ancestor", "branch")]
        for b in branches:
            change = b.change(path)
            if change is None:
                # The branch does not change the file.
                continue
            anc, tip = change
            if not anc or not tip:
                # The branch adds or deletes the file: nothing to merge.
                current = blob(tip) if tip else None
                continue
            if current is None:
                # An earlier branch deleted the file; this change cannot be
                # merged onto nothing, so its tip is the replay.
                current = blob(tip)
                continue
            if b"\0" in current or b"\0" in blob(anc) or b"\0" in blob(tip):
                # git merge-file would merge bytes as text; a binary blob's
                # change is applied whole.
                unresolved.append(b.ref)
                current = blob(tip)
                continue
            with open(names[0], "wb") as f:
                f.write(current)
            with open(names[1], "wb") as f:
                f.write(blob(anc))
            with open(names[2], "wb") as f:
                f.write(blob(tip))
            r = subprocess.run(["git", "merge-file", "-p", "-L", "replayed", "-L", "baseline",
                                "-L", b.ref, *names], capture_output=True)
            if r.returncode != 0:
                unresolved.append(b.ref)
            current = r.stdout
    return current, unresolved


def resolved(content, spec):
    """Whether a blob is the intended resolution: every 'add' line present,
    no 'drop' line."""
    lines = content.decode("utf-8", "surrogateescape").splitlines()
    return (all(x in lines for x in spec.get("add", []))
            and not any(x in lines for x in spec.get("drop", [])))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--branch", action="append", default=[],
                    help="PR branch, in merge order; replaces the defaults")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    baseline, candidate = rev_parse(args.baseline), rev_parse(args.candidate)
    if not baseline or not candidate:
        sys.exit(f"cannot resolve {args.baseline if not baseline else args.candidate} to a commit")

    ignored, replays = IGNORED, NOTICE_REPLAY
    refs = args.branch or PR_ORDER

    branches = []
    for ref in refs:
        if not rev_parse(ref):
            sys.exit(f"cannot resolve branch {ref} to a commit")
        branches.append(Branch(ref, baseline, ignored))
    landed = []
    for b in list(branches):
        commit = b.landed(baseline)
        if commit:
            landed.append({"ref": b.ref, "commit": commit})
            branches.remove(b)

    base_blobs, cand_blobs = tree_blobs(baseline), tree_blobs(candidate)
    changed = changed_paths(baseline, candidate, ignored)
    owners = {}
    for b in branches:
        for p in b.paths:
            owners.setdefault(p, []).append(b)

    findings = []
    for path in sorted(owners.keys() - changed):
        findings.append({"kind": "missing", "path": path,
                         "detail": "changed by " + ", ".join(x.ref for x in owners[path])
                                   + " only"})
    for path in sorted(changed - owners.keys()):
        findings.append({"kind": "candidate-only", "path": path,
                         "detail": "changed on the candidate, by no PR branch"})
    replay_used = set()
    for path in sorted(changed & owners.keys()):
        want = cand_blobs.get(path)
        detail = "changed by " + ", ".join(x.ref for x in owners[path])
        replay_used.add(path)
        got, unresolved = replay(base_blobs.get(path), owners[path], path)
        if got is None and want is None:
            continue
        if want and got == blob(want):
            continue
        spec = replays.get(path)
        if spec and want and resolved(blob(want), spec):
            continue
        if unresolved:
            detail += "; replay conflicts in " + ", ".join(unresolved)
        findings.append({"kind": "replay-differs", "path": path, "detail": detail})

    unused_replays = sorted(set(replays) - replay_used)
    unused_branches = [b.ref for b in branches if not b.paths]
    verdict = "FAIL" if findings else "PASS"
    result = {
        "verdict": verdict,
        "baseline": {"ref": args.baseline, "commit": baseline},
        "candidate": {"ref": args.candidate, "commit": candidate},
        "branches": [{"ref": b.ref, "base": b.base, "files": len(b.paths)} for b in branches],
        "ignored": ignored,
        "files": {"candidate": len(changed),
                  "branches": len(owners),
                  "by_one_branch": sum(1 for v in owners.values() if len(v) == 1),
                  "by_several_branches": sum(1 for v in owners.values() if len(v) > 1)},
        "findings": findings,
        "landed": landed,
        "unused_replay_resolutions": unused_replays,
        "branches_without_changes": unused_branches,
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "compare-plan.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(args.out, "compare-plan.md"), "w", encoding="utf-8") as f:
        f.write(markdown(result))
    print(f"compare plan: {verdict} ({len(findings)} difference(s); "
          f"{result['files']['candidate']} candidate files, "
          f"{result['files']['branches']} PR files)")
    for x in findings:
        print(f"  {x['kind']}: {x['path']} ({x['detail']})")
    for r in unused_replays:
        print(f"  unused replay resolution: {r}")
    for r in unused_branches:
        print(f"  branch without changes: {r}")
    for x in landed:
        print(f"  landed in the baseline, not replayed: {x['ref']} ({x['commit'][:11]})")
    return 0 if verdict == "PASS" else 1


def markdown(result):
    """The comparison as a report section."""
    out = ["## The candidate is the baseline plus the PR branches\n",
           f"- Baseline: `{result['baseline']['ref']}` "
           f"({result['baseline']['commit'][:11]})",
           f"- Candidate: `{result['candidate']['ref']}` "
           f"({result['candidate']['commit'][:11]})",
           "- PR branches, in merge order:"]
    out += [f"  - `{b['ref']}` (base `{b['base'][:11]}`, {b['files']} file(s))"
            for b in result["branches"]]
    f = result["files"]
    out.append(f"\n{f['candidate']} file(s) changed on the candidate, "
               f"{f['branches']} by the branches ({f['by_one_branch']} by one, "
               f"{f['by_several_branches']} by several); ignored: "
               f"{', '.join(f'`{g}`' for g in result['ignored'])}.\n")
    out.append(f"Verdict: **{result['verdict']}**\n")
    if result["findings"]:
        out.append("| Kind | File | Detail |")
        out.append("|---|---|---|")
        out += [f"| {x['kind']} | `{x['path']}` | {x['detail']} |"
                for x in result["findings"]]
        out.append("")
        out.append("`candidate-only` is a change no PR branch makes; `missing` is a change "
                   "a branch makes that the candidate lacks; `replay-differs` is a file "
                   "one or several branches change whose replay does not give the "
                   "candidate's content (a hand-resolved conflict or a binary blob).\n")
    if result["unused_replay_resolutions"]:
        out.append("Replay resolutions listed but not needed: "
                   + ", ".join(f"`{r}`" for r in result["unused_replay_resolutions"]) + ".\n")
    if result["landed"]:
        out.append("Branches already in the baseline, not replayed: "
                   + ", ".join(f"`{x['ref']}` ({x['commit'][:11]})" for x in result["landed"])
                   + ". Remove them from `PR_BRANCHES` and `PR_ORDER`.\n")
    if result["branches_without_changes"]:
        out.append("Branches with no change outside the ignored paths: "
                   + ", ".join(f"`{r}`" for r in result["branches_without_changes"]) + ".\n")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
