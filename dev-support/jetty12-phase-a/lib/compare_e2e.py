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

"""Line up the end-to-end results of the two sides.

Usage: compare_e2e.py --expected FILE --out DIR --arch NAME BASELINE_E2E CANDIDATE_E2E

Every observation (component + id) is classified:
  MATCH          both sides met the expectation and the normalized views are equal
  DIFF           both met it, but the normalized views differ
  REGRESSION     baseline met it, candidate did not
  FIXED          candidate met it, baseline did not
  BOTH_FAIL      neither met it (an environment problem, or broken on both)
  MISSING        recorded on one side only

The candidate passes when there is no REGRESSION, no MISSING on the
candidate side, no DIFF outside the allowlist, no class loaded from a jar
outside the allowlist, and no new error in the logs.

Allowlist lines: '<kind> <regex>  # reason', kind one of
  obs        <component>:<id>
  classjar   <daemon>:<class>   (class loaded from a different jar)
  logscan    <source>:<message> (error message only seen on the candidate)
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "e2e", "lib"))
import classload  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from artifact_diff import Allowlist  # noqa: E402


def load_obs(path):
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[f"{r['component']}:{r['id']}"] = r
    return out


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def first_difference(a, b, path=""):
    """A short human-readable pointer to where two JSON values differ."""
    if type(a) is not type(b):
        return f"{path or '/'}: {json.dumps(a)[:120]} vs {json.dumps(b)[:120]}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}/{k}: only on candidate"
            if k not in b:
                return f"{path}/{k}: only on baseline"
            d = first_difference(a[k], b[k], f"{path}/{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} vs {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path or '/'}: {json.dumps(a)[:120]} vs {json.dumps(b)[:120]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arch", required=True)
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    a = ap.parse_args()
    allow = Allowlist(a.expected)

    b = load_obs(os.path.join(a.baseline, "observations.jsonl"))
    c = load_obs(os.path.join(a.candidate, "observations.jsonl"))
    rows = []
    for key in sorted(set(b) | set(c), key=lambda k: (k.split(":")[0], k)):
        rb, rc = b.get(key), c.get(key)
        comp = (rb or rc)["component"]
        if rb is None or rc is None:
            cls, detail = "MISSING", "only on " + ("candidate" if rb is None else "baseline")
        elif rb["ok"] and rc["ok"]:
            d = first_difference(rb["obs"], rc["obs"])
            cls, detail = ("MATCH", None) if d is None else ("DIFF", d)
        elif rb["ok"]:
            cls, detail = "REGRESSION", "; ".join(rc["problems"])
        elif rc["ok"]:
            cls, detail = "FIXED", "; ".join(rb["problems"])
        else:
            cls, detail = "BOTH_FAIL", "; ".join(rc["problems"])
        rule = allow.match("obs", key) if cls in ("DIFF", "REGRESSION", "MISSING") else None
        rows.append({"key": key, "component": comp, "class": cls, "detail": detail,
                     "expected": bool(rule), "reason": rule and rule["reason"]})

    # Class loading of each daemon.
    cl = classload.compare(a.baseline, a.candidate)
    jar_moves = []
    for daemon, r in cl.items():
        for cls_name, (jb, jc) in r["different_jar"].items():
            rule = allow.match("classjar", f"{daemon}:{cls_name}")
            jar_moves.append({"daemon": daemon, "class": cls_name, "baseline": jb,
                              "candidate": jc, "expected": bool(rule),
                              "reason": rule and rule["reason"]})

    # Errors in logs that only the candidate has.
    lb = load_json(os.path.join(a.baseline, "logscan.json"))
    lc = load_json(os.path.join(a.candidate, "logscan.json"))
    new_errors = []
    for src, msgs in lc.items():
        for msg, n in msgs.items():
            if msg not in lb.get(src, {}):
                rule = allow.match("logscan", f"{src}:{msg}")
                new_errors.append({"source": src, "message": msg, "count": n,
                                   "expected": bool(rule), "reason": rule and rule["reason"]})

    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    blocking = {
        "regressions": [r for r in rows if r["class"] == "REGRESSION" and not r["expected"]],
        "missing_on_candidate": [r for r in rows if r["class"] == "MISSING"
                                 and r["detail"] == "only on baseline" and not r["expected"]],
        "unexpected_diffs": [r for r in rows if r["class"] == "DIFF" and not r["expected"]],
        "unexpected_class_jars": [m for m in jar_moves if not m["expected"]],
        "new_log_errors": [e for e in new_errors if not e["expected"]],
    }
    verdict = "PASS" if not any(blocking.values()) else "FAIL"
    result = {
        "verdict": verdict, "counts": counts,
        "blocking": {k: len(v) for k, v in blocking.items()},
        "both_fail": [r for r in rows if r["class"] == "BOTH_FAIL"],
        "rows": rows, "class_jar_moves": jar_moves, "new_log_errors": new_errors,
        "classload": {d: {"baseline_classes": r["baseline_classes"],
                          "candidate_classes": r["candidate_classes"],
                          "only_baseline": len(r["only_baseline"]),
                          "only_candidate": len(r["only_candidate"]),
                          "different_jar": len(r["different_jar"])}
                      for d, r in cl.items()},
        "unused_rules": [f"line {r['line']}: {r['kind']} {r['pattern']}"
                         for r in allow.rules if r["hits"] == 0],
    }
    os.makedirs(a.out, exist_ok=True)
    result["arch"] = a.arch
    with open(os.path.join(a.out, f"e2e-compare-{a.arch}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(a.out, f"classload-compare-{a.arch}.json"), "w", encoding="utf-8") as f:
        json.dump(cl, f, indent=1)
    write_markdown(os.path.join(a.out, f"e2e-compare-{a.arch}.md"), result, blocking)
    print(f"e2e comparison ({a.arch}): {verdict} {counts}")
    return 0 if verdict == "PASS" else 1


def write_markdown(path, result, blocking):
    rows = result["rows"]
    comps = sorted({r["component"] for r in rows})
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"## End-to-end: {result['arch']} architecture\n\n")
        f.write(f"Verdict: **{result['verdict']}**. Observations: "
                + ", ".join(f"{k} {v}" for k, v in sorted(result["counts"].items())) + "\n\n")
        f.write("| Component | Observations | Match | Diff | Regression | Fixed | Both fail | Missing |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for comp in comps:
            rs = [r for r in rows if r["component"] == comp]
            n = {k: sum(r["class"] == k for r in rs) for k in
                 ("MATCH", "DIFF", "REGRESSION", "FIXED", "BOTH_FAIL", "MISSING")}
            f.write(f"| {comp} | {len(rs)} | {n['MATCH']} | {n['DIFF']} | {n['REGRESSION']} "
                    f"| {n['FIXED']} | {n['BOTH_FAIL']} | {n['MISSING']} |\n")
        f.write("\n")
        for title, key in (("Regressions", "regressions"),
                           ("Recorded on baseline only", "missing_on_candidate"),
                           ("Unexpected differences", "unexpected_diffs")):
            items = blocking[key]
            if items:
                f.write(f"### {title} ({len(items)})\n\n| Observation | Detail |\n|---|---|\n")
                for r in items:
                    f.write(f"| `{r['key']}` | {(r['detail'] or '').replace('|', '/')} |\n")
                f.write("\n")
        exp = [r for r in rows if r["expected"]]
        if exp:
            f.write(f"### Expected differences ({len(exp)})\n\n| Observation | Class | Reason |\n"
                    "|---|---|---|\n")
            for r in exp:
                f.write(f"| `{r['key']}` | {r['class']} | {r['reason']} |\n")
            f.write("\n")
        bf = result["both_fail"]
        if bf:
            f.write(f"### Failing on both sides ({len(bf)})\n\nNot caused by the patch; "
                    "usually the environment. Each needs a look before relying on the run.\n\n"
                    "| Observation | Problem |\n|---|---|\n")
            for r in bf:
                f.write(f"| `{r['key']}` | {(r['detail'] or '').replace('|', '/')} |\n")
            f.write("\n")
        f.write("### Classes loaded by each daemon\n\n| Daemon | Baseline | Candidate | "
                "Baseline only | Candidate only | Different jar |\n|---|---|---|---|---|---|\n")
        for d, r in sorted(result["classload"].items()):
            f.write(f"| {d} | {r['baseline_classes']} | {r['candidate_classes']} | "
                    f"{r['only_baseline']} | {r['only_candidate']} | {r['different_jar']} |\n")
        f.write("\nClasses loaded on one side only depend on timing and are listed in "
                "classload-compare-<arch>.json; a class loaded from a different jar must be in the "
                "allowlist.\n\n")
        moves = result["class_jar_moves"]
        if moves:
            f.write(f"<details><summary>Classes loaded from a different jar ({len(moves)})"
                    "</summary>\n\n| Daemon | Class | Baseline jar | Candidate jar | Expected |\n"
                    "|---|---|---|---|---|\n")
            for m in moves:
                f.write(f"| {m['daemon']} | `{m['class']}` | {m['baseline']} | {m['candidate']} "
                        f"| {m['reason'] or '**no**'} |\n")
            f.write("\n</details>\n\n")
        errs = result["new_log_errors"]
        f.write(f"### Log errors seen only on the candidate: {len(errs)}\n\n")
        for e in errs:
            f.write(f"- {e['source']}: `{e['message']}` x{e['count']}"
                    f"{' (expected: ' + e['reason'] + ')' if e['expected'] else ''}\n")
        if result["unused_rules"]:
            f.write("\nAllowlist rules that matched nothing:\n\n")
            for r in result["unused_rules"]:
                f.write(f"- `{r}`\n")


if __name__ == "__main__":
    sys.exit(main())
