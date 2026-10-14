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

"""Assemble results/compare/report.md from the three comparisons.

Usage: report.py <results dir>
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
    return "PASS" if d["summary"]["unexpected"] == 0 else "FAIL"


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


def main(results):
    cmp_dir = os.path.join(results, "compare")
    archs = sorted(f[len("e2e-compare-"):-len(".json")] for f in os.listdir(cmp_dir)
                   if f.startswith("e2e-compare-") and f.endswith(".json")) \
        if os.path.isdir(cmp_dir) else []
    parts = [("Artifacts and dependencies", "artifact-diff.json", "artifact-diff.md")]
    parts += [(f"End-to-end: {a}", f"e2e-compare-{a}.json", f"e2e-compare-{a}.md") for a in archs]
    if not archs:
        parts.append(("End-to-end", "e2e-compare-none.json", "e2e-compare-none.md"))
    parts.append(("Unit and integration tests", "unit-compare.json", "unit-compare.md"))
    # Only runs that resolve downstream projects (the client unit suite) have it.
    if os.path.exists(os.path.join(cmp_dir, "downstream-compare.json")):
        parts.append(("Downstream dependencies", "downstream-compare.json",
                      "downstream-compare.md"))
    verdicts = [(name, verdict(os.path.join(cmp_dir, j))) for name, j, _ in parts]
    overall = "PASS" if all(v == "PASS" for _, v in verdicts) else \
        ("INCOMPLETE" if all(v in ("PASS", "NOT RUN") for _, v in verdicts) else "FAIL")
    out = ["# Jetty 12 phase A: no functional change\n",
           f"- Baseline: `{commit(results, 'baseline')}`",
           f"- Candidate: `{commit(results, 'candidate')}`\n",
           *harness_check(results),
           f"Overall: **{overall}**\n",
           "| Check | Verdict |", "|---|---|"]
    out += [f"| {n} | {v} |" for n, v in verdicts]
    out.append("")
    for _, _, md in parts:
        text = read(os.path.join(cmp_dir, md))
        if text:
            out.append(text)
    with open(os.path.join(cmp_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"overall: {overall} ({', '.join(f'{n}: {v}' for n, v in verdicts)})")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
