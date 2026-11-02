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

"""Assemble results/compare/report.md from the comparisons.

Usage: report.py <results dir>

A run stopped by the ancestry check or the plan check (compare.sh) writes
only that section and no comparison; the report is then just the verdict.

A run whose candidate was broken on purpose (candidate/build/broken.txt,
R69) checks the harness: it exits 0 only when the breakage was caught where
every case is caught, the artifacts and every end-to-end architecture FAIL,
and the tree checks did not fail, which would stop the comparison before it
could catch anything.
"""

import json
import os
import sys


def read(path):
    return open(path, encoding="utf-8").read() if os.path.exists(path) else None


def verdict(path):
    if not os.path.exists(path):
        return "NOT RUN"
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if "verdict" in d:
        return d["verdict"]
    summary = d.get("summary")
    if summary is None:
        # Written by another tool, or a stub: a file without a verdict says
        # nothing about the comparison, so it must not stop the report.
        return "NOT RUN"
    return "PASS" if summary["unexpected"] == 0 else "FAIL"


def commit(results, side):
    p = os.path.join(results, side, "build", "commit-subject.txt")
    return read(p).strip() if os.path.exists(p) else "not built"


def harness_check(results):
    """Notes for runs that check the harness instead of the patch, and for
    builds reused from an earlier run of the same code."""
    notes = []
    for side in ("baseline", "candidate"):
        reused = os.path.join(results, side, "build", "reused-from.txt")
        if os.path.exists(reused):
            notes.append(f"- The {side} build was reused from an earlier build of the same code: "
                         f"`{read(reused).strip()}`")
    if notes:
        notes[-1] += "\n"
    if commit(results, "baseline") == commit(results, "candidate") != "not built":
        notes.append("**Harness check, baseline against itself**: both sides are the same "
                     "commit, so every difference below is noise.\n")
    broken = os.path.join(results, "candidate", "build", "broken.txt")
    if os.path.exists(broken):
        changes = "".join(f"\n- `{line}`" for line in read(broken).splitlines() if line.strip())
        notes.append("**Harness check, candidate deliberately broken**; the verdict must be "
                     f"FAIL. Changes made to its distribution:{changes}\n")
    return notes


def caught(verdicts):
    """Whether a deliberately broken candidate was caught: the artifact
    diff and every end-to-end architecture FAIL, and no tree check FAILs."""
    v = dict(verdicts)
    e2e = [x for n, x in verdicts if n.startswith("End-to-end")]
    return (v.get("Artifacts and dependencies") == "FAIL" and bool(e2e)
            and all(x == "FAIL" for x in e2e)
            and v.get("The candidate contains the baseline's commits") != "FAIL"
            and v.get("The candidate is the baseline plus the PR branches") != "FAIL")


def main(results):
    cmp_dir = os.path.join(results, "compare")
    archs = sorted(f[len("e2e-compare-"):-len(".json")] for f in os.listdir(cmp_dir)
                   if f.startswith("e2e-compare-") and f.endswith(".json")) \
        if os.path.isdir(cmp_dir) else []
    # The checks that the candidate is the baseline plus the PR branches run
    # first; a run they stop writes only their section.
    pre = [("The candidate contains the baseline's commits", "ancestry.json", "ancestry.md"),
           ("The candidate is the baseline plus the PR branches", "compare-plan.json",
            "compare-plan.md")]
    pre = [p for p in pre if os.path.exists(os.path.join(cmp_dir, p[1]))]
    parts = pre + [("Artifacts and dependencies", "artifact-diff.json", "artifact-diff.md"),
                   ("API compatibility", "api-compat.json", "api-compat.md")]
    parts += [(f"End-to-end: {a}", f"e2e-compare-{a}.json", f"e2e-compare-{a}.md") for a in archs]
    if not archs:
        parts.append(("End-to-end", "e2e-compare-none.json", "e2e-compare-none.md"))
    parts.append(("Unit and integration tests", "unit-compare.json", "unit-compare.md"))
    # Only runs that resolve downstream projects (the client unit suite) have it.
    if os.path.exists(os.path.join(cmp_dir, "downstream-compare.json")):
        parts.append(("Downstream dependencies", "downstream-compare.json",
                      "downstream-compare.md"))
    verdicts = [(name, verdict(os.path.join(cmp_dir, j))) for name, j, _ in parts]
    pre_failed = [n for n, v in verdicts[:len(pre)] if v == "FAIL"]
    overall = "PASS" if all(v == "PASS" for _, v in verdicts) else \
        ("INCOMPLETE" if all(v in ("PASS", "NOT RUN") for _, v in verdicts) else "FAIL")
    broken = os.path.exists(os.path.join(results, "candidate", "build", "broken.txt"))
    check = None
    if broken:
        check = "PASS" if caught(verdicts) else "FAIL"
    # The two trees are what they claim: the comparison below is of the patch.
    out = ["# Jetty 12 phase A: no functional change\n",
           f"- Baseline: `{commit(results, 'baseline')}`",
           f"- Candidate: `{commit(results, 'candidate')}`\n",
           *harness_check(results),
           f"Overall: **{overall}**\n"]
    if check:
        out.append(f"Harness check: **{check}**: the artifacts and every end-to-end "
                   "architecture must FAIL on the broken candidate, and the tree checks "
                   "must not.\n")
    if pre_failed:
        out.append("**The run stopped before comparing**: "
                   + " and ".join(f"*{n}*" for n in pre_failed)
                   + " did not pass, so the candidate is not the tree to test "
                     "(see the first sections). Fix that first: a difference "
                     "reported against it would not be the patch's.\n")
    out += ["| Check | Verdict |", "|---|---|"]
    out += [f"| {n} | {v} |" for n, v in verdicts]
    out.append("")
    impact = read(os.path.join(cmp_dir, "impact.md"))
    if impact:
        out.append(impact)
    for _, _, md in parts:
        text = read(os.path.join(cmp_dir, md))
        if text:
            out.append(text)
    with open(os.path.join(cmp_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"overall: {overall} ({', '.join(f'{n}: {v}' for n, v in verdicts)})")
    if check:
        print(f"harness check (broken candidate): {check}")
        return 0 if check == "PASS" else 1
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
