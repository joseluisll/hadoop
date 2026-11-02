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

"""Line up the unit test results of the two sides, test by test.

Usage: compare_unit.py --out DIR [--expected RULES] BASELINE_UNIT CANDIDATE_UNIT

Each *_UNIT directory holds one sub-directory per module with the surefire /
failsafe TEST-*.xml reports and a "status" file (maven exit code, seconds).

A test is pass, flaky (failed, then passed on re-run), fail, or skipped.
The candidate passes when no test that passed (or was flaky) on the
baseline fails on the candidate, no test that ran on the baseline is
missing or skipped on the candidate, and no module's Maven run failed on
the candidate when the baseline's succeeded. A module whose Maven run
failed on both sides is listed without failing.

A test that exists only on the candidate (one the patch adds) is listed with
its result; one that fails there fails the run unless a 'candidate-only-fail
<module>|<test>' rule in RULES accepts it (a known flake, T20).
"""

import argparse
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from allowlist import Allowlist  # noqa: E402


def read_module(path):
    tests = {}
    for f in sorted(glob.glob(os.path.join(path, "TEST-*.xml"))):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            tests[f"{os.path.basename(f)}#<unparseable report>"] = "fail"
            continue
        for tc in root.iter("testcase"):
            key = f"{tc.get('classname')}#{tc.get('name')}"
            tags = {child.tag for child in tc}
            if tags & {"failure", "error"}:
                state = "fail"
            elif "skipped" in tags:
                state = "skipped"
            elif tags & {"flakyFailure", "flakyError"}:
                state = "flaky"
            else:
                state = "pass"
            # Re-runs can list a test twice; the worst outcome wins.
            order = ["pass", "skipped", "flaky", "fail"]
            if key not in tests or order.index(state) > order.index(tests[key]):
                tests[key] = state
    status = None
    sf = os.path.join(path, "status")
    if os.path.exists(sf):
        with open(sf, encoding="utf-8") as fh:
            rc, secs = fh.read().split()
            status = {"maven_exit": int(rc), "seconds": int(secs)}
    return tests, status


# Modules with no tests whose build itself is the check (maven-enforcer rules
# on the shaded client jars): they pass when Maven succeeded on both sides.
CHECK_ONLY_MODULES = ("hadoop-client-modules/hadoop-client-check-invariants",
                      "hadoop-client-modules/hadoop-client-check-test-invariants")


def checks_only(p):
    return p["module"].endswith(CHECK_ONLY_MODULES) and all(
        (p[side]["status"] or {}).get("maven_exit") == 0 for side in ("baseline", "candidate"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--expected", help="rules for failing candidate-only tests")
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    a = ap.parse_args()
    allow = Allowlist(a.expected) if a.expected else None

    modules = sorted({d for base in (a.baseline, a.candidate) if os.path.isdir(base)
                      for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))})
    per_module, regressions, missing, skipped, fixed, both_fail, flaky = [], [], [], [], [], [], []
    maven_failed_candidate, maven_failed_both = [], []
    candidate_only = []
    for m in modules:
        bt, bs = read_module(os.path.join(a.baseline, m))
        ct, cs = read_module(os.path.join(a.candidate, m))
        name = m.replace("__", "/")
        b_exit = (bs or {}).get("maven_exit")
        c_exit = (cs or {}).get("maven_exit")
        if c_exit not in (None, 0) and b_exit == 0:
            maven_failed_candidate.append(name)
        elif c_exit not in (None, 0) and b_exit not in (None, 0):
            maven_failed_both.append(name)
        for key in sorted(set(bt) | set(ct)):
            sb, sc = bt.get(key), ct.get(key)
            item = {"module": name, "test": key, "baseline": sb, "candidate": sc}
            if sb in ("pass", "flaky") and sc == "fail":
                regressions.append(item)
            elif sb is not None and sb != "skipped" and sc is None:
                missing.append(item)
            elif sb is not None and sb != "skipped" and sc == "skipped":
                skipped.append(item)
            elif sb == "fail" and sc in ("pass", "flaky"):
                fixed.append(item)
            elif sb == "fail" and sc == "fail":
                both_fail.append(item)
            elif sb is None and sc is not None:
                if sc == "fail":
                    rule = allow and allow.match("candidate-only-fail", f"{name}|{key}")
                    item["status"] = "EXPECTED" if rule else "UNEXPECTED"
                    item["reason"] = rule["reason"] if rule else ""
                candidate_only.append(item)
            if "flaky" in (sb, sc):
                flaky.append(item)
        count = lambda t, s: sum(v == s for v in t.values())  # noqa: E731
        per_module.append({
            "module": name,
            "baseline": {"tests": len(bt), "pass": count(bt, "pass"), "flaky": count(bt, "flaky"),
                         "fail": count(bt, "fail"), "skipped": count(bt, "skipped"),
                         "status": bs},
            "candidate": {"tests": len(ct), "pass": count(ct, "pass"), "flaky": count(ct, "flaky"),
                          "fail": count(ct, "fail"), "skipped": count(ct, "skipped"),
                          "status": cs},
        })
    not_run = [p["module"] for p in per_module
               if (p["candidate"]["tests"] == 0 or p["baseline"]["tests"] == 0)
               and not checks_only(p)]
    # A module with no test reports on a side (a suite pattern matching
    # nothing, or a build failure) compared nothing, so it cannot pass.
    candidate_only_failed = [i for i in candidate_only if i.get("status") == "UNEXPECTED"]
    verdict = "PASS" if not regressions and not missing and not skipped and not not_run \
        and not maven_failed_candidate and not candidate_only_failed and per_module else "FAIL"
    if not per_module:
        verdict = "NOT RUN"
    result = {"verdict": verdict, "modules": per_module, "regressions": regressions,
              "missing_on_candidate": missing, "skipped_on_candidate": skipped,
              "fixed": fixed, "both_fail": both_fail,
              "flaky": flaky, "modules_without_reports": not_run,
              "maven_failed_on_candidate": maven_failed_candidate,
              "maven_failed_on_both": maven_failed_both,
              "candidate_only": candidate_only,
              "candidate_only_failed": candidate_only_failed,
              "unused_rules": allow.unused() if allow else []}
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "unit-compare.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(a.out, "unit-compare.md"), "w", encoding="utf-8") as f:
        f.write("## Unit and integration tests\n\n")
        f.write(f"Verdict: **{verdict}**. Regressions: {len(regressions)}, tests missing on "
                f"the candidate: {len(missing)}, newly skipped on the candidate: "
                f"{len(skipped)}, failing on both: {len(both_fail)}, "
                f"fixed: {len(fixed)}, flaky: {len(flaky)}, Maven failed on the candidate: "
                f"{len(maven_failed_candidate)}, on both sides: {len(maven_failed_both)}, "
                f"only on the candidate: {len(candidate_only)} "
                f"({len(candidate_only_failed)} failing without a rule).\n\n")
        f.write("| Module | Baseline pass/flaky/fail/skip | Candidate pass/flaky/fail/skip |\n"
                "|---|---|---|\n")
        for p in per_module:
            b, c = p["baseline"], p["candidate"]
            f.write(f"| {p['module']} | {b['pass']}/{b['flaky']}/{b['fail']}/{b['skipped']} "
                    f"| {c['pass']}/{c['flaky']}/{c['fail']}/{c['skipped']} |\n")
        f.write("\n")
        for title, items in (("Regressions", regressions), ("Missing on the candidate", missing),
                             ("Newly skipped on the candidate", skipped),
                             ("Failing on both sides", both_fail), ("Fixed", fixed),
                             ("Flaky", flaky)):
            if items:
                f.write(f"### {title} ({len(items)})\n\n| Module | Test | Baseline | Candidate |\n"
                        "|---|---|---|---|\n")
                for i in items[:500]:
                    f.write(f"| {i['module']} | `{i['test']}` | {i['baseline']} | {i['candidate']} |\n")
                f.write("\n")
        if candidate_only:
            f.write(f"### Only on the candidate ({len(candidate_only)})\n\n"
                    "| Module | Test | Candidate | Rule |\n|---|---|---|---|\n")
            for i in candidate_only[:500]:
                rule = {"EXPECTED": f"accepted: {i.get('reason', '')}",
                        "UNEXPECTED": "**none: fails the run**"}.get(i.get("status"), "")
                f.write(f"| {i['module']} | `{i['test']}` | {i['candidate']} | {rule} |\n")
            f.write("\n")
        if allow and allow.unused():
            f.write("Rules that matched nothing: "
                    + "; ".join(f"`{u}`" for u in allow.unused()) + "\n\n")
        for title, names in (("Maven run failed on the candidate", maven_failed_candidate),
                             ("Maven run failed on both sides", maven_failed_both)):
            if names:
                f.write(f"### {title} ({len(names)})\n\n" + ", ".join(names) + "\n\n")
        if not_run:
            f.write("Modules with no test reports on a side (build or setup failure; see "
                    "results/<side>/unit/<module>/mvn.log): " + ", ".join(not_run) + "\n")
    print(f"unit comparison: {verdict}, {len(regressions)} regressions, {len(missing)} missing, "
          f"{len(skipped)} newly skipped, {len(candidate_only_failed)} failing only on the "
          f"candidate without a rule")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
