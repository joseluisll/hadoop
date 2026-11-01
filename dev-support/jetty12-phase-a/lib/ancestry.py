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

"""Check that the candidate is built on the baseline's trunk, and say what it lacks.

Usage:
  ancestry.py --baseline REF --candidate REF [--ignore GLOB ...] [--out DIR]

The candidate must contain every baseline commit that changes the code the
harness compares. When it does not, the candidate was built on an older trunk
than the baseline and the comparison reports those commits' changes as
differences caused by the patch. The run stops instead, naming the commits the
candidate lacks.

A baseline commit counts as missing when it changes at least one file outside
the ignored paths and its change is not already in the candidate's tree: the
candidate lacks the commit, or has its content from a merge or cherry-pick.
Either way the comparison sees the same file. Ignored paths default to the
harness and .github/, whose changes only the fork's commits make.

What the candidate has that the baseline does not is not reported here: a
candidate commit the baseline lacks is the patch, or a PR branch (compare with
compare_plan.py).

Writes DIR/ancestry.json and DIR/ancestry.md (DIR defaults to the current
directory). Exits 0 when every baseline commit's change is in the candidate,
1 when some are missing (the run must stop), 2 on a usage or git error.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gitrefs import changed_blobs, git, rev_parse, tree_blobs  # noqa: E402

# Ignored for every commit, relative to the repository root.
IGNORED = ["dev-support/jetty12-phase-a/", ".github/"]


def missing_commits(baseline, candidate, ignored):
    """(baseline commits the candidate does not contain as ancestors, baseline
    commits whose change to a non-ignored path the candidate does not have,
    oldest first)."""
    head = tree_blobs(candidate)
    ancestors = (git("rev-list", "--reverse", candidate + ".." + baseline) or "").split()
    out = []
    for commit in ancestors:
        leaves = changed_blobs(commit, ignored)
        if leaves is None:
            sys.exit(f"cannot read the change of {commit}")
        missing = {p: b for p, b in leaves.items() if head.get(p) != b}
        if not missing:
            continue
        out.append({
            "commit": commit,
            "subject": git("log", "-1", "--format=%s", commit).strip(),
            "author_date": git("log", "-1", "--format=%aI", commit).strip(),
            "files": sorted(missing),
        })
    return len(ancestors), out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--ignore", action="append", default=[],
                    help="path prefix ignored for every commit, added to the defaults")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    baseline, candidate = rev_parse(args.baseline), rev_parse(args.candidate)
    if not baseline or not candidate:
        sys.exit(f"cannot resolve {args.baseline if not baseline else args.candidate} to a commit")
    ignored = IGNORED + args.ignore

    count, missing = missing_commits(baseline, candidate, ignored)
    verdict = "MISSING" if missing else "CONTAINED"
    result = {
        "verdict": verdict,
        "baseline": {"ref": args.baseline, "commit": baseline},
        "candidate": {"ref": args.candidate, "commit": candidate},
        "ignored": ignored,
        "baseline_commits_not_in_candidate": count,
        "missing": missing,
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "ancestry.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(args.out, "ancestry.md"), "w", encoding="utf-8") as f:
        f.write(markdown(result))
    print(f"ancestry: {verdict} ({len(missing)} baseline commit(s) whose change the candidate "
          f"lacks)")
    for m in missing:
        print(f"  {m['commit'][:11]} {m['subject'][:70]}")
        for p in m["files"]:
            print(f"      {p}")
    return 0 if verdict == "CONTAINED" else 1


def markdown(result):
    """The check as a report section."""
    out = ["## The candidate contains the baseline's commits\n",
           f"- Baseline: `{result['baseline']['ref']}` "
           f"({result['baseline']['commit'][:11]})",
           f"- Candidate: `{result['candidate']['ref']}` "
           f"({result['candidate']['commit'][:11]})",
           f"- Ignored paths: {', '.join(f'`{g}`' for g in result['ignored'])}\n"]
    if result["missing"]:
        out.append(f"Verdict: **MISSING**: the candidate lacks {len(result['missing'])} "
                   "baseline commit(s). Built on an older trunk than the baseline, it "
                   "would report their changes as differences caused by the patch. "
                   "Rebase or merge the baseline into the candidate and run again.\n")
        out.append("| Commit | Subject | Files the candidate lacks |")
        out.append("|---|---|---|")
        for m in result["missing"]:
            files = "<br>".join(f"`{p}`" for p in m["files"])
            out.append(f"| `{m['commit'][:11]}` | {m['subject']} | {files} |")
        out.append("")
    else:
        out.append(f"Verdict: **CONTAINED**: the candidate has every change made by the "
                   f"{result['baseline_commits_not_in_candidate']} baseline commit(s) it "
                   "does not contain as ancestors.\n")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
