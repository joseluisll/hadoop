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

"""Replay an allowlist against the comparisons already written.

Usage: replay.py <compare dir> [<compare dir>...]

Each directory is what a comparison leaves in results/compare: one JSON per
comparison. A rule is replayed the way its comparison matches it, so a new or
edited rule can be tried against the latest report of every architecture
before it is committed (R66), without a build or a run. For each rule file it
lists the rules that matched nothing in any directory (the ones a run would
report as unused, R59) and the rules that matched in only some directories (a
pattern that misses an architecture's names: the first HADOOP-19970 classjar
rule's `[a-z]+` missed the numbered daemons, nn1 and rm1 among them). Exits 1
when a rule matched nothing anywhere.
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from allowlist import Allowlist  # noqa: E402


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def e2e_matches(allow, compare_dir):
    """Match every end-to-end rule the comparison would, in its order
    (lib/compare_e2e.py): 'obs' excuses a DIFF, a REGRESSION or a MISSING;
    'obsdiff' a DIFF; 'obsfield' a DIFF when every differing field matches; a
    class loaded from a different jar is 'classjar'; a class loaded on one side
    only is 'classonly'; an error only the candidate logs 'logscan'."""
    for path in sorted(glob.glob(os.path.join(compare_dir, "e2e-compare-*.json"))):
        d = load(path)
        if not d or "rows" not in d:
            continue  # NOT RUN: nothing was compared
        for r in d["rows"]:
            if r["class"] in ("DIFF", "REGRESSION", "MISSING"):
                if allow.match("obs", r["key"]):
                    continue
            if r["class"] != "DIFF":
                continue
            if allow.match("obsdiff", r["key"]):
                continue
            # Reports written before the comparison recorded 'fields' name the
            # first differing path in 'detail' ('<component>:<id>/headers/vary: ...').
            fields = r.get("fields")
            if fields is None:
                fields = [r["detail"].split(":", 1)[0]] if r.get("detail") else []
            for p in fields:
                allow.match("obsfield", r["key"] + p)
        for m in d.get("class_jar_moves", []):
            allow.match("classjar", f"{m['daemon']}:{m['class']}")
        # A report written before 'one_side_classes' was recorded has the same
        # lists in classload-compare-<arch>.json (only_baseline/only_candidate).
        one = d.get("one_side_classes")
        if one is None:
            cl = load(os.path.join(compare_dir, f"classload-compare-{d.get('arch', '')}.json"))
            one = [{"daemon": daemon, "side": side, "class": c}
                   for daemon, r in (cl or {}).items()
                   for side in ("baseline", "candidate")
                   for c in r.get(f"only_{side}", [])]
        for x in one:
            allow.match("classonly", f"{x['daemon']}:{x['class']}")
        for e in d.get("new_log_errors", []):
            allow.match("logscan", f"{e['source']}:{e['message']}")


def artifact_matches(allow, compare_dir):
    d = load(os.path.join(compare_dir, "artifact-diff.json"))
    for x in (d or {}).get("differences", []):
        allow.match(x["kind"], x["subject"])


def api_matches(allow, compare_dir):
    """An API finding is matched when it blocks: its status is not INFO."""
    d = load(os.path.join(compare_dir, "api-compat.json"))
    for f in (d or {}).get("findings", []):
        if f["status"] != "INFO":
            allow.match(f["kind"], f["subject"])


def downstream_matches(allow, compare_dir):
    d = load(os.path.join(compare_dir, "downstream-compare.json"))
    for x in (d or {}).get("differences", []):
        allow.match(x["kind"], x["subject"])


def unit_matches(allow, compare_dir):
    """Only a failing test that exists only on the candidate can be accepted."""
    d = load(os.path.join(compare_dir, "unit-compare.json"))
    for x in (d or {}).get("candidate_only", []):
        if x["candidate"] == "fail":
            allow.match("candidate-only-fail", f"{x['module']}|{x['test']}")


# Rule file, relative to the harness directory, and how its comparison matches
# its subjects. Check 4 (unit tests) accepts only failing candidate-only tests:
# a regression always fails.
RULE_FILES = {
    "expected-differences.txt": artifact_matches,
    "expected-api-differences.txt": api_matches,
    "e2e/expected-e2e-differences.txt": e2e_matches,
    "expected-downstream-differences.txt": downstream_matches,
    "expected-unit-differences.txt": unit_matches,
}
# Kinds a comparison added after these reports were written (T12's pom-*, T15's
# license-*). A report without them cannot say whether the rule would match, so
# replay lists it as not replayable instead of as a rule that matched nothing.
# Existing kinds replay exactly as before: a rule whose kind is present in a
# report but matched nothing still fails.
NEW_KINDS = ("pom-", "license-", "notice-")


def recorded_kinds(compare_dirs):
    """Every difference kind the comparisons in these directories recorded."""
    kinds = set()
    for d in compare_dirs:
        for path in glob.glob(os.path.join(d, "*.json")):
            try:
                data = load(path)
            except (OSError, ValueError):
                continue
            for x in (data or {}).get("differences", []):
                if isinstance(x, dict) and "kind" in x:
                    kinds.add(x["kind"])
            for f in (data or {}).get("findings", []):
                if isinstance(f, dict) and "kind" in f:
                    kinds.add(f["kind"])
    return kinds


def replay(harness_dir, compare_dirs):
    """{rule file: {line: [directories the rule matched in]}}."""
    result = {}
    for name, matches in RULE_FILES.items():
        allow = Allowlist(os.path.join(harness_dir, name))
        seen = {r["line"]: [] for r in allow.rules}
        for d in compare_dirs:
            allow.reset()
            matches(allow, d)
            for r in allow.rules:
                if r["hits"]:
                    seen[r["line"]].append(os.path.basename(os.path.normpath(d)))
        result[name] = [{"line": r["line"], "kind": r["kind"], "pattern": r["pattern"],
                         "dirs": seen[r["line"]]} for r in allow.rules]
    return result


def main(argv):
    if len(argv) < 2:
        print("usage: replay.py <compare dir> [<compare dir>...]", file=sys.stderr)
        return 2
    compare_dirs = argv[1:]
    missing = [d for d in compare_dirs if not os.path.isdir(d)]
    if missing:
        print(f"no such compare directory: {', '.join(missing)}", file=sys.stderr)
        return 2
    harness_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    present = recorded_kinds(compare_dirs)
    failed = False
    for name, rules in replay(harness_dir, compare_dirs).items():
        nowhere = [r for r in rules if not r["dirs"]]
        partial = [r for r in rules if r["dirs"] and len(r["dirs"]) < len(compare_dirs)]
        not_replayable = [r for r in nowhere if r["kind"].startswith(NEW_KINDS)
                          and r["kind"] not in present]
        unmatched = [r for r in nowhere if r not in not_replayable]
        print(f"{name}: {len(rules)} rule(s), {len(unmatched)} matched nothing, "
              f"{len(not_replayable)} not replayable, "
              f"{len(partial)} matched in some directories only")
        for r in unmatched:
            print(f"  line {r['line']}: {r['kind']} {r['pattern']}  (matched nothing)")
        for r in not_replayable:
            print(f"  line {r['line']}: {r['kind']} {r['pattern']}  "
                  f"(not replayable (no data in these reports))")
        for r in partial:
            print(f"  line {r['line']}: {r['kind']} {r['pattern']}  "
                  f"(matched in {', '.join(r['dirs'])})")
        failed = failed or bool(unmatched)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
