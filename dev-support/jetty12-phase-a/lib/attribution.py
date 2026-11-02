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

"""Check the per-ticket and merge-order runs of the attribution workflow.

Usage: attribution.py [--rules DIR] <dir with one sub-directory per tree>

Each tree directory holds what attribution.sh wrote for it: artifact-diff.json,
api-compat.json and downstream-compare.json. In a ticket-<n> tree every rule
whose reason starts with the branch's ticket must have matched at least once;
in any tree nothing may be UNEXPECTED. The branches and their order come from
PR_ORDER in compare_plan.py. Writes attribution.json and attribution.md in the
given directory and exits 1 when a tree fails.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from allowlist import Allowlist  # noqa: E402
from compare_plan import PR_ORDER  # noqa: E402

# The comparison JSON and the rule file it was matched against. artifact-diff
# records its unused rules under summary; the other two at the top level.
COMPARISONS = (
    ("artifact-diff", "artifact-diff.json", "expected-differences.txt"),
    ("api-compat", "api-compat.json", "expected-api-differences.txt"),
    ("downstream", "downstream-compare.json", "expected-downstream-differences.txt"),
)


def ticket_of(branch):
    """The ticket a PR branch belongs to; jetty-phase-a is HADOOP-19970."""
    if branch.endswith("/jetty-phase-a"):
        return "HADOOP-19970"
    m = re.search(r"HADOOP-\d+", branch)
    return m.group(0) if m else None


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def unexpected(comparison, data):
    """The UNEXPECTED differences or findings a comparison recorded."""
    if not data:
        return []
    items = [d for key in ("differences", "findings")
             for d in data.get(key) or [] if d.get("status") == "UNEXPECTED"]
    n = (data.get("summary") or {}).get("unexpected")
    if n and not items:
        items = [{"kind": comparison, "subject": f"(summary says {n} unexpected)"}]
    return items


def unused(comparison, data):
    """The unused-rule strings a comparison recorded."""
    if not data:
        return []
    return (data.get("summary") or {}).get("unused_rules") or data.get("unused_rules") or []


def check_tree(name, path, rules_dir):
    problems = []
    data = {}
    for comparison, filename, _ in COMPARISONS:
        data[comparison] = load(os.path.join(path, filename))
        if data[comparison] is None:
            problems.append(f"missing {filename}")
        for d in unexpected(comparison, data[comparison]):
            problems.append(f"{comparison}: UNEXPECTED {d.get('kind')} {d.get('subject')}")
    ticket = None
    if name.startswith("ticket-"):
        try:
            branch = PR_ORDER[int(name.split("-", 1)[1]) - 1]
        except (ValueError, IndexError):
            problems.append(f"unknown tree name {name}")
        else:
            ticket = ticket_of(branch)
            if ticket is None:
                problems.append(f"no ticket in branch {branch}")
            else:
                for comparison, _, filename in COMPARISONS:
                    allow = Allowlist(os.path.join(rules_dir, filename))
                    unused_rules = set(unused(comparison, data[comparison]))
                    for r in allow.rules:
                        key = f"line {r['line']}: {r['kind']} {r['pattern']}"
                        if r["reason"].startswith(ticket) and key in unused_rules:
                            problems.append(
                                f"{comparison}: {ticket} rule unused in its own tree: {key}")
    elif not name.startswith("prefix-"):
        problems.append(f"unknown tree name {name}")
    return {"tree": name, "ticket": ticket,
            "verdict": "FAIL" if problems else "PASS", "problems": problems}


def markdown(result):
    out = ["## Attribution runs", "",
           f"Verdict: **{result['verdict']}** ({len(result['trees'])} trees).", ""]
    for p in result.get("problems", []):
        out.append(f"- {p}")
    if result.get("problems"):
        out.append("")
    for t in result["trees"]:
        ticket = f", {t['ticket']}" if t["ticket"] else ""
        out.append(f"### {t['tree']}{ticket}")
        out.append("")
        out.append(f"Verdict: **{t['verdict']}**.")
        out.append("")
        for p in t["problems"]:
            out.append(f"- {p}")
        if t["problems"]:
            out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rules", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="directory holding the three expected-differences files")
    ap.add_argument("trees", help="directory with one sub-directory per tree")
    args = ap.parse_args()

    trees = [check_tree(name, os.path.join(args.trees, name), args.rules)
             for name in sorted(os.listdir(args.trees))
             if os.path.isdir(os.path.join(args.trees, name))]
    if not trees:
        result = {"verdict": "FAIL", "trees": [],
                  "problems": [f"no tree directories in {args.trees}"]}
    else:
        failed = [t for t in trees if t["verdict"] != "PASS"]
        result = {"verdict": "FAIL" if failed else "PASS", "trees": trees}
    with open(os.path.join(args.trees, "attribution.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(args.trees, "attribution.md"), "w", encoding="utf-8") as f:
        f.write(markdown(result))
    print(f"attribution: {result['verdict']} ({len(trees)} trees)")
    for t in trees:
        print(f"  {t['tree']}: {t['verdict']}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
