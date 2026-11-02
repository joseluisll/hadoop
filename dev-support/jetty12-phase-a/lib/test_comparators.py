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

"""Check that the comparison scripts write the verdict they are meant to.

Usage: test_comparators.py

Runs each comparator the way compare.sh does (``python3 -I <script> ...``) on
small synthetic inputs in a temporary directory, and fails unless the verdict
it writes, and its exit code where compare.sh reads it, is the expected one.
The git repository for the ancestry check is created in the temporary
directory; no build, cluster or Hadoop repository is touched.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
E2E = os.path.join(HERE, "compare_e2e.py")
UNIT = os.path.join(HERE, "compare_unit.py")
DOWNSTREAM = os.path.join(HERE, "compare_downstream.py")
ANCESTRY = os.path.join(HERE, "ancestry.py")
REPORT = os.path.join(HERE, "report.py")


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, "-I", script, *args],
                          cwd=cwd, capture_output=True, text=True, env=git_env())


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path, value):
    write_text(path, json.dumps(value))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_result(case, path, r):
    """The JSON a comparator wrote, or an assertion naming the case and the
    comparator's stderr when it crashed without writing one. A crash used to
    surface as a FileNotFoundError with no case name."""
    try:
        return read_json(path)
    except (OSError, ValueError) as e:
        raise AssertionError(
            f"{case}: no JSON result at {path} ({e}); stderr:\n{r.stderr.strip()}"
        ) from None


def expect(case, got, want):
    assert got == want, f"{case}: got {got!r}, expected {want!r}"
    print(f"ok: {case}")


def observation(component, ident, ok=True, **view):
    return json.dumps({"component": component, "id": ident, "ok": ok,
                       "obs": view, "problems": [] if ok else ["failed"]})


def e2e(tmp, case, baseline, candidate, verdict, rc, rules="", aborted=None,
        classload=None, logscan=None):
    base = os.path.join(tmp, "e2e", case)
    for side, lines in (("baseline", baseline), ("candidate", candidate)):
        os.makedirs(os.path.join(base, side))
        if lines is not None:
            write_text(os.path.join(base, side, "observations.jsonl"),
                       "".join(line + "\n" for line in lines))
        if aborted and side in aborted:
            write_text(os.path.join(base, side, "aborted.txt"), aborted[side])
        for daemon, classes in (classload or {}).get(side, {}).items():
            write_text(os.path.join(base, side, "classload", daemon + ".classes.tsv"),
                       "".join(f"{c}\t{j}\n" for c, j in classes.items()))
        if logscan and side in logscan:
            write_json(os.path.join(base, side, "logscan.json"), logscan[side])
    expected = os.path.join(base, "expected.txt")
    write_text(expected, rules)
    out = os.path.join(base, "out")
    r = run(E2E, "--expected", expected, "--out", out, "--arch", "simple",
            os.path.join(base, "baseline"), os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "e2e-compare-simple.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def surefire(tests):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuite>"]
    for classname, name, state in tests:
        if state == "pass":
            out.append(f'  <testcase classname="{classname}" name="{name}"/>')
        elif state == "fail":
            out.append(f'  <testcase classname="{classname}" name="{name}">'
                       "<failure/></testcase>")
        elif state == "flaky":
            out.append(f'  <testcase classname="{classname}" name="{name}">'
                       "<flakyFailure/></testcase>")
        else:
            out.append(f'  <testcase classname="{classname}" name="{name}">'
                       "<skipped/></testcase>")
    out.append("</testsuite>")
    return "\n".join(out) + "\n"


def unit(tmp, case, baseline, candidate, verdict, rc):
    base = os.path.join(tmp, "unit", case)
    for side, tests in (("baseline", baseline), ("candidate", candidate)):
        module = os.path.join(base, side, "moduleA")
        write_text(os.path.join(module, "TEST-moduleA.xml"), surefire(tests))
        write_text(os.path.join(module, "status"), "0 1\n")
    out = os.path.join(base, "out")
    r = run(UNIT, "--out", out, os.path.join(base, "baseline"),
            os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "unit-compare.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def downstream(tmp, case, baseline, candidate, verdict, rc):
    base = os.path.join(tmp, "downstream", case)
    for side, deps in (("baseline", baseline), ("candidate", candidate)):
        write_text(os.path.join(base, side, "dependencies.tsv"), deps)
    expected = os.path.join(base, "expected.txt")
    write_text(expected, "")
    out = os.path.join(base, "out")
    r = run(DOWNSTREAM, "--expected", expected, "--out", out,
            os.path.join(base, "baseline"), os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "downstream-compare.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def git_env():
    """The environment for git commands: no GIT_* variable inherited from the
    caller (GIT_DIR, GIT_INDEX_FILE and the like would point at another
    repository) and no hooks, which a user's configuration could install."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo, *args):
    subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null", *args],
                   check=True, capture_output=True, text=True, env=git_env())


def rev(repo, ref="HEAD"):
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=/dev/null",
                           "rev-parse", ref], check=True, capture_output=True,
                          text=True, env=git_env()).stdout.strip()


def new_repo(tmp, name):
    repo = os.path.join(tmp, "git", name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def commit(repo, path, text, message):
    write_text(os.path.join(repo, path), text)
    git(repo, "add", path)
    git(repo, "commit", "-m", message)


def ancestry(repo, case, baseline, candidate, verdict, rc):
    out = os.path.join(repo, "out", case)
    r = run(ANCESTRY, "--out", out, "--baseline", baseline,
            "--candidate", candidate, cwd=repo)
    result = read_result(case, os.path.join(out, "ancestry.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def report(tmp, case, checks, overall, rc):
    results = os.path.join(tmp, "report", case)
    cmp_dir = os.path.join(results, "compare")
    os.makedirs(cmp_dir)
    for name, verdict in checks.items():
        write_json(os.path.join(cmp_dir, name), {"verdict": verdict})
    r = run(REPORT, results)
    lines = [line for line in r.stdout.splitlines() if line.startswith("overall: ")]
    assert lines, f"{case}: no 'overall:' line in stdout; stderr:\n{r.stderr.strip()}"
    expect(case, (lines[0].split()[1], r.returncode), (overall, rc))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        e2e(tmp, "e2e identical observations PASS",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=200)], "PASS", 0)
        e2e(tmp, "e2e a differing observation FAILs",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=500)], "FAIL", 1)
        e2e(tmp, "e2e a missing observations file is NOT RUN",
            [observation("comp", "one")], None, "NOT RUN", 1)
        e2e(tmp, "e2e an empty observations file on both sides is NOT RUN",
            [], [], "NOT RUN", 1)
        e2e(tmp, "e2e an empty observations file on one side is NOT RUN",
            [], [observation("comp", "one")], "NOT RUN", 1)

        # Allowlist: a DIFF the rules excuse PASSes, a REGRESSION never does,
        # an obsfield rule must match every differing field and a rule's regex
        # must match the whole subject.
        e2e(tmp, "e2e a DIFF matched by an obs rule PASSes",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=500)], "PASS", 0,
            rules="obs comp:one  # expected status change\n")
        e2e(tmp, "e2e a DIFF matched by an obsdiff rule PASSes",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=500)], "PASS", 0,
            rules="obsdiff comp:one  # expected status change\n")
        e2e(tmp, "e2e an obsdiff rule does not excuse a REGRESSION",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", ok=False)], "FAIL", 1,
            rules="obsdiff comp:one  # only excuses a DIFF\n")
        e2e(tmp, "e2e an obsfield rule matching only some differing fields FAILs",
            [observation("comp", "one", status=200, vary="a")],
            [observation("comp", "one", status=200, vary="b", extra="c")], "FAIL", 1,
            rules="obsfield comp:one/extra  # only one of the two fields\n")
        e2e(tmp, "e2e obsfield rules matching every differing field PASS",
            [observation("comp", "one", status=200, vary="a")],
            [observation("comp", "one", status=200, vary="b", extra="c")], "PASS", 0,
            rules="obsfield comp:one/extra  # field added\n"
                  "obsfield comp:one/vary  # field changed\n")
        e2e(tmp, "e2e a rule matching only a prefix of the subject does not excuse a DIFF",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=500)], "FAIL", 1,
            rules="obs comp:on  # matches only the prefix\n")

        # E2E blocking checks: each one on its own fails the comparison.
        e2e(tmp, "e2e an observation only on the baseline FAILs",
            [observation("comp", "one")], [observation("comp", "two")], "FAIL", 1)
        e2e(tmp, "e2e candidate daemons not starting FAILs",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            aborted={"candidate": "namenode did not start\n"})
        e2e(tmp, "e2e baseline daemons not starting is NOT RUN",
            [observation("comp", "one")], [observation("comp", "one")], "NOT RUN", 1,
            aborted={"baseline": "namenode did not start\n"})
        e2e(tmp, "e2e a duplicate observation id FAILs",
            [observation("comp", "one")],
            [observation("comp", "one"), observation("comp", "one")], "FAIL", 1)
        e2e(tmp, "e2e a class loaded from a different jar FAILs",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            classload={"baseline": {"nn": {"org.example.Foo": "lib/jetty-foo.jar"}},
                       "candidate": {"nn": {"org.example.Foo": "lib/jetty-bar.jar"}}})
        e2e(tmp, "e2e a new log error on the candidate FAILs",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            logscan={"baseline": {}, "candidate": {"nn": {"NoClassDefFoundError: Foo": 1}}})

        unit(tmp, "unit tests passing on both sides PASS",
             [("C", "one", "pass")], [("C", "one", "pass")], "PASS", 0)
        unit(tmp, "unit pass on baseline and fail on candidate FAILs",
             [("C", "one", "pass")], [("C", "one", "fail")], "FAIL", 1)
        unit(tmp, "unit missing on candidate FAILs",
             [("C", "one", "pass"), ("C", "two", "pass")],
             [("C", "one", "pass")], "FAIL", 1)
        unit(tmp, "unit pass on baseline and skipped on candidate FAILs",
             [("C", "one", "pass")], [("C", "one", "skipped")], "FAIL", 1)
        unit(tmp, "unit flaky on baseline and fail on candidate FAILs",
             [("C", "one", "flaky")], [("C", "one", "fail")], "FAIL", 1)

        downstream(tmp, "downstream identical results PASS",
                   "simple/hadoop-common\tg:a:jar:1.0:compile\n",
                   "simple/hadoop-common\tg:a:jar:1.0:compile\n", "PASS", 0)
        downstream(tmp, "downstream an unmatched difference FAILs",
                   "simple/hadoop-common\tg:a:jar:1.0:compile\n",
                   "simple/hadoop-common\tg:a:jar:2.0:compile\n", "FAIL", 1)

        repo = new_repo(tmp, "contains")
        commit(repo, "a.txt", "a\n", "one")
        first = rev(repo)
        commit(repo, "b.txt", "b\n", "two")
        ancestry(repo, "ancestry candidate contains baseline PASSes",
                 first, rev(repo), "PASS", 0)

        repo = new_repo(tmp, "lacks")
        commit(repo, "root.txt", "root\n", "root")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "baseline")
        commit(repo, "base.txt", "base\n", "baseline change")
        baseline = rev(repo)
        git(repo, "checkout", "-q", "-b", "candidate", root)
        commit(repo, "cand.txt", "cand\n", "candidate change")
        ancestry(repo, "ancestry missing baseline commit FAILs",
                 baseline, rev(repo), "FAIL", 1)

        # A cherry-pick puts the baseline commit's content in the candidate
        # without the commit as an ancestor: the comparison sees the same
        # file, so it PASSes. A baseline commit changing only ignored paths
        # does not need to be in the candidate at all.
        repo = new_repo(tmp, "cherry")
        commit(repo, "root.txt", "root\n", "root")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "baseline")
        commit(repo, "base.txt", "base\n", "baseline change")
        baseline = rev(repo)
        git(repo, "checkout", "-q", "-b", "candidate", root)
        commit(repo, "base.txt", "base\n", "cherry-picked baseline change")
        ancestry(repo, "ancestry a cherry-picked baseline commit PASSes",
                 baseline, rev(repo), "PASS", 0)

        repo = new_repo(tmp, "ignored")
        commit(repo, "root.txt", "root\n", "root")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "baseline")
        commit(repo, "dev-support/jetty12-phase-a/harness.txt", "h\n",
               "harness change")
        baseline = rev(repo)
        git(repo, "checkout", "-q", "-b", "candidate", root)
        commit(repo, "cand.txt", "cand\n", "candidate change")
        ancestry(repo, "ancestry a baseline commit changing only ignored paths PASSes",
                 baseline, rev(repo), "PASS", 0)

        all_pass = {"ancestry.json": "PASS", "artifact-diff.json": "PASS",
                    "api-compat.json": "PASS", "e2e-compare-simple.json": "PASS",
                    "unit-compare.json": "PASS"}
        report(tmp, "report all checks PASS", all_pass, "PASS", 0)
        report(tmp, "report one check FAILs",
               {**all_pass, "artifact-diff.json": "FAIL"}, "FAIL", 1)
        report(tmp, "report one NOT RUN and the rest PASS is INCOMPLETE",
               {**all_pass, "e2e-compare-simple.json": "NOT RUN"}, "INCOMPLETE", 1)
    print("test_comparators: ok")


if __name__ == "__main__":
    main()
