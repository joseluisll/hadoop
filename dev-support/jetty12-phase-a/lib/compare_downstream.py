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

"""Compare what downstream Maven projects resolve from each side.

Usage:
  compare_downstream.py --expected expected-downstream-differences.txt \\
      --out DIR BASELINE_DOWNSTREAM CANDIDATE_DOWNSTREAM

Each *_DOWNSTREAM directory is a side's results/<side>/downstream, holding
dependencies.tsv (written by downstream-deps.sh): one line per resolved
dependency, "<scenario>/<hadoop artifact><TAB><group:artifact:type
[:classifier]:version:scope>", and duplicates.tsv (lib/downstream_classes.py):
the packages whose classes more than one jar provides on a project's
classpath. Kinds, matched against the allowlist (whose regexes match the
whole subject):
  downstream-dep-removed / -added   <project>|<coordinates>
  downstream-dep-changed            <project>|<group:artifact:type[:classifier]>:
                                    <old version:scope> -> <new version:scope>
  downstream-dup-removed / -added   <project>|<package>|<group:artifact,...>
                                    a set of jars providing the same classes
                                    (which copy loads depends on classpath order)

Writes DIR/downstream-compare.json and .md; nothing when neither side has
results (the run did not resolve them). Exits 1 on an unexpected difference
or when only one side has results.
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from artifact_diff import Allowlist  # noqa: E402


def read(path):
    """{project|group:artifact:type[:classifier]: version:scope}, or None."""
    f = os.path.join(path, "dependencies.tsv")
    if not os.path.exists(f):
        return None
    deps = {}
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            project, coord = line.rstrip("\n").split("\t")
            parts = coord.split(":")
            deps[f"{project}|{':'.join(parts[:-2])}"] = ":".join(parts[-2:])
    return deps


def read_duplicates(path):
    """{project|package|jars: number of classes}, or None for a side that has no
    duplicates.tsv (run before downstream-deps.sh recorded classpaths)."""
    f = os.path.join(path, "duplicates.tsv")
    if not os.path.exists(f):
        return None
    out = {}
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                project, package, jars, count = line.rstrip("\n").split("\t")
                out[f"{project}|{package}|{jars}"] = int(count)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    a = ap.parse_args()
    b, c = read(a.baseline), read(a.candidate)
    if b is None and c is None:
        print("downstream: no results on either side")
        return 0
    os.makedirs(a.out, exist_ok=True)
    if b is None or c is None:
        missing = "baseline" if b is None else "candidate"
        result = {"verdict": "NOT RUN", "reason": f"no downstream results for the {missing}"}
        write(a.out, result, [], [])
        print(f"downstream: {result['reason']}")
        return 1
    allow = Allowlist(a.expected)
    diffs = []

    def record(kind, subject, detail=None):
        rule = allow.match(kind, subject)
        diffs.append({"kind": kind, "subject": subject, "detail": detail,
                      "status": "EXPECTED" if rule else "UNEXPECTED",
                      "reason": rule["reason"] if rule else None,
                      "rule_line": rule["line"] if rule else None})

    for key in sorted(b.keys() | c.keys()):
        if key not in c:
            record("downstream-dep-removed", f"{key}:{b[key]}")
        elif key not in b:
            record("downstream-dep-added", f"{key}:{c[key]}")
        elif b[key] != c[key]:
            record("downstream-dep-changed", f"{key}:{b[key]} -> {c[key]}")
    db, dc = read_duplicates(a.baseline), read_duplicates(a.candidate)
    if db is not None and dc is not None:
        for key in sorted(db.keys() - dc.keys()):
            record("downstream-dup-removed", key, f"{db[key]} classes")
        for key in sorted(dc.keys() - db.keys()):
            record("downstream-dup-added", key, f"{dc[key]} classes")
    unexpected = [d for d in diffs if d["status"] == "UNEXPECTED"]
    result = {
        "verdict": "FAIL" if unexpected else "PASS",
        "summary": {
            "projects": len({k.split("|")[0] for k in b.keys() | c.keys()}),
            "resolved": {"baseline": len(b), "candidate": len(c)},
            "duplicates": None if db is None or dc is None else
            {"baseline": len(db), "candidate": len(dc),
             "by_scenario": duplicate_summary(db, dc)},
            "differences": len(diffs), "unexpected": len(unexpected),
        },
    }
    unused = [f"line {r['line']}: {r['kind']} {r['pattern']}" for r in allow.rules if r["hits"] == 0]
    write(a.out, result, diffs, unused)
    print(f"downstream: {len(diffs)} differences, {len(unexpected)} unexpected")
    return 1 if unexpected else 0


def duplicate_summary(db, dc):
    """{scenario: [baseline projects with duplicates, candidate ones, total packages b, c]}"""
    out = collections.defaultdict(lambda: [set(), set(), 0, 0])
    for side, d in ((0, db), (1, dc)):
        for key in d:
            project = key.split("|")[0]
            s = out[project.split("/")[0]]
            s[side].add(project)
            s[2 + side] += 1
    return {k: [len(v[0]), len(v[1]), v[2], v[3]] for k, v in sorted(out.items())}


def write(out, result, diffs, unused):
    with open(os.path.join(out, "downstream-compare.json"), "w", encoding="utf-8") as f:
        json.dump({**result, "differences": diffs, "unused_rules": unused}, f, indent=1)
    with open(os.path.join(out, "downstream-compare.md"), "w", encoding="utf-8") as f:
        f.write("## Downstream dependencies\n\n")
        if "summary" not in result:
            f.write(f"Verdict: **{result['verdict']}**: {result['reason']}.\n\n")
            return
        s = result["summary"]
        f.write(f"Verdict: **{result['verdict']}**. What downstream Maven projects resolve "
                f"from the Hadoop artifacts ({s['projects']} small projects; see "
                f"downstream-deps.sh): baseline {s['resolved']['baseline']}, candidate "
                f"{s['resolved']['candidate']} resolved dependencies; differences "
                f"{s['differences']}, **unexpected: {s['unexpected']}**.\n\n")
        dup = s.get("duplicates")
        if dup is None:
            f.write("Classes provided by more than one jar: not recorded on both sides.\n\n")
        else:
            f.write("Classes provided by more than one jar on a project's classpath (which "
                    "copy loads depends on classpath order; downstream-dup-* below):\n\n"
                    "| Scenario | Projects with duplicates (baseline / candidate) | "
                    "Package and jar sets (baseline / candidate) |\n|---|---|---|\n")
            for scenario, (pb, pc, kb, kc) in dup["by_scenario"].items():
                f.write(f"| {scenario} | {pb} / {pc} | {kb} / {kc} |\n")
            f.write("\n")
        if unused:
            f.write("Allowlist rules that matched nothing (expected change did not "
                    "happen; check why):\n\n")
            f.writelines(f"- `{r}`\n" for r in unused)
            f.write("\n")
        by = collections.defaultdict(list)
        for d in diffs:
            by[d["status"]].append(d)
        for status in ("UNEXPECTED", "EXPECTED"):
            if not by[status]:
                continue
            f.write(f"### {status.title()} differences ({len(by[status])})\n\n")
            f.write("| Kind | Subject | Detail | Reason |\n|---|---|---|---|\n")
            for d in by[status]:
                subject = d["subject"].replace("|", "\\|")
                f.write(f"| {d['kind']} | `{subject}` | {d.get('detail') or ''} | "
                        f"{d['reason'] or ''} |\n")
            f.write("\n")


if __name__ == "__main__":
    sys.exit(main())
