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
PLAN = os.path.join(HERE, "compare_plan.py")
DOWNSTREAM = os.path.join(HERE, "compare_downstream.py")
ANCESTRY = os.path.join(HERE, "ancestry.py")
REPORT = os.path.join(HERE, "report.py")
ATTRIBUTION = os.path.join(HERE, "attribution.py")


def run(script, *args, cwd=None, env=None):
    e = git_env()
    if env:
        e.update(env)
    return subprocess.run([sys.executable, "-I", script, *args],
                          cwd=cwd, capture_output=True, text=True, env=e)


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
        classload=None, logscan=None, env=None):
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
            os.path.join(base, "baseline"), os.path.join(base, "candidate"), env=env)
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


def unit(tmp, case, baseline, candidate, verdict, rc, baseline_exit=0, candidate_exit=0,
         keys=None, rules="", history=None):
    base = os.path.join(tmp, "unit", case)
    for side, tests, exit_code in (("baseline", baseline, baseline_exit),
                                   ("candidate", candidate, candidate_exit)):
        module = os.path.join(base, side, "moduleA")
        write_text(os.path.join(module, "TEST-moduleA.xml"), surefire(tests))
        write_text(os.path.join(module, "status"), f"{exit_code} 1\n")
    out = os.path.join(base, "out")
    write_text(os.path.join(base, "rules.txt"), rules)
    history_args = []
    for i, d in enumerate(history or []):
        hdir = os.path.join(base, "history", str(i))
        write_json(os.path.join(hdir, "unit-compare.json"), d)
        history_args += ["--history", hdir]
    r = run(UNIT, "--out", out, "--expected", os.path.join(base, "rules.txt"),
            *history_args, os.path.join(base, "baseline"), os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "unit-compare.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))
    for key, want in (keys or {}).items():
        expect(f"{case}: {key}", result.get(key), want)
    return result


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


def plan(repo, case, baseline, candidate, branches, verdict, rc):
    out = os.path.join(repo, "out", case)
    args = ["--baseline", baseline, "--candidate", candidate, "--out", out]
    for branch in branches:
        args += ["--branch", branch]
    r = run(PLAN, *args, cwd=repo)
    result = read_result(case, os.path.join(out, "compare-plan.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def report(tmp, case, checks, overall, rc, broken=False):
    results = os.path.join(tmp, "report", case)
    cmp_dir = os.path.join(results, "compare")
    os.makedirs(cmp_dir)
    if broken:
        write_text(os.path.join(results, "candidate", "build", "broken.txt"), "case test\n")
    for name, verdict in checks.items():
        write_json(os.path.join(cmp_dir, name), {"verdict": verdict})
    r = run(REPORT, results)
    lines = [line for line in r.stdout.splitlines() if line.startswith("overall: ")]
    assert lines, f"{case}: no 'overall:' line in stdout; stderr:\n{r.stderr.strip()}"
    expect(case, (lines[0].split()[1], r.returncode), (overall, rc))


RULE_FILES = ("expected-differences.txt", "expected-api-differences.txt",
              "expected-downstream-differences.txt")


def artifact_json(unexpected=0, unused=(), diffs=None):
    return {"summary": {"unexpected": unexpected, "unused_rules": list(unused)},
            "differences": list(diffs or [])}


def api_json(unexpected=0, unused=(), findings=None):
    return {"verdict": "FAIL" if unexpected else "PASS",
            "summary": {"unexpected": unexpected},
            "findings": list(findings or []), "unused_rules": list(unused)}


def downstream_json(unexpected=0, unused=(), diffs=None):
    return {"verdict": "FAIL" if unexpected else "PASS",
            "summary": {"unexpected": unexpected},
            "differences": list(diffs or []), "unused_rules": list(unused)}


def matched_tree():
    return {"artifact-diff.json": artifact_json(),
            "api-compat.json": api_json(),
            "downstream-compare.json": downstream_json()}


def attribution(tmp, case, trees, verdict, rc, rules=None, contains=None):
    base = os.path.join(tmp, "attribution", case)
    trees_dir = os.path.join(base, "trees")
    for name, files in trees.items():
        for filename, value in files.items():
            write_json(os.path.join(trees_dir, name, filename), value)
    rules_dir = os.path.join(base, "rules")
    for filename in RULE_FILES:
        write_text(os.path.join(rules_dir, filename), (rules or {}).get(filename, ""))
    r = run(ATTRIBUTION, "--rules", rules_dir, trees_dir)
    result = read_result(case, os.path.join(trees_dir, "attribution.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))
    if contains is not None:
        problems = [p for t in result["trees"] for p in t["problems"]]
        expect(f"{case}: reason", any(contains in p for p in problems), True)
    return result


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
        e2e(tmp, "e2e a baseline observations file with only a blank line is NOT RUN",
            [""], [observation("comp", "one")], "NOT RUN", 1)
        e2e(tmp, "e2e observations files with only a blank line are NOT RUN",
            [""], [""], "NOT RUN", 1)

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

        # T3: a class loaded on one side only is matched against a classonly
        # rule. Unexpected ones fail only with CLASSONLY_FAIL=true.
        one_side = {"baseline": {"nn": {"org.example.Foo": "lib/jetty-foo.jar"}},
                    "candidate": {"nn": {"org.example.Foo": "lib/jetty-foo.jar",
                                         "org.example.Bar": "lib/jetty-bar.jar"}}}
        e2e(tmp, "e2e a classonly rule accepting a one-side class PASSes",
            [observation("comp", "one")], [observation("comp", "one")], "PASS", 0,
            classload=one_side,
            rules="classonly nn:org\\.example\\.Bar  # expected\n")
        e2e(tmp, "e2e an unexpected one-side class does not fail with the switch off",
            [observation("comp", "one")], [observation("comp", "one")], "PASS", 0,
            classload=one_side)
        e2e(tmp, "e2e an unexpected one-side class fails with CLASSONLY_FAIL=true",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            classload=one_side, env={"CLASSONLY_FAIL": "true"})

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
        unit(tmp, "unit Maven failing on the candidate FAILs",
             [("C", "one", "pass")], [("C", "one", "pass")], "FAIL", 1,
             candidate_exit=1, keys={"maven_failed_on_candidate": ["moduleA"],
                                     "maven_failed_on_both": []})
        unit(tmp, "unit Maven failing on both sides PASSes",
             [("C", "one", "pass")], [("C", "one", "pass")], "PASS", 0,
             baseline_exit=1, candidate_exit=1,
             keys={"maven_failed_on_candidate": [], "maven_failed_on_both": ["moduleA"]})
        unit(tmp, "unit a candidate-only test passing PASSes",
             [("C", "one", "pass")], [("C", "one", "pass"), ("C", "new", "pass")], "PASS", 0)
        unit(tmp, "unit a candidate-only test failing FAILs",
             [("C", "one", "pass")], [("C", "one", "pass"), ("C", "new", "fail")], "FAIL", 1)
        unit(tmp, "unit a candidate-only failing test with a rule PASSes",
             [("C", "one", "pass")], [("C", "one", "pass"), ("C", "new", "fail")], "PASS", 0,
             rules="candidate-only-fail moduleA\\|C#new  # known flake\n",
             keys={"unused_rules": []})
        unit(tmp, "unit a rule does not accept a regression",
             [("C", "one", "pass")], [("C", "one", "fail")], "FAIL", 1,
             rules="candidate-only-fail moduleA\\|C#one  # known flake\n",
             keys={"unused_rules": ["line 1: candidate-only-fail moduleA\\|C#one"]})
        unit(tmp, "unit a regression reports its history",
             [("C", "one", "pass")], [("C", "one", "fail")], "FAIL", 1,
             history=[
                 {"flaky": [{"module": "moduleA", "test": "C#one",
                             "baseline": "flaky", "candidate": "pass"}]},
                 {"regressions": [{"module": "moduleA", "test": "C#one",
                                   "baseline": "pass", "candidate": "fail"}]},
             ],
             keys={"history": [{"module": "moduleA", "test": "C#one",
                                "baseline_runs": 1, "candidate_runs": 1, "runs": 2}]})
        unit(tmp, "unit no --history leaves the history empty",
             [("C", "one", "pass")], [("C", "one", "fail")], "FAIL", 1,
             keys={"history": []})

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

        repo = new_repo(tmp, "plan-delete")
        commit(repo, "file.txt", "one\n", "one")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "baseline", root)
        git(repo, "checkout", "-q", "-b", "branch", "baseline")
        git(repo, "rm", "-q", "file.txt")
        git(repo, "commit", "-q", "-m", "delete the file")
        git(repo, "checkout", "-q", "-b", "candidate", "baseline")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge the branch", "branch")
        plan(repo, "plan a branch that deletes a file and a candidate that lacks it PASSes",
             "baseline", rev(repo), ["branch"], "PASS", 0)
        commit(repo, "file.txt", "candidate\n", "keep the file")
        plan(repo, "plan a branch that deletes a file and a candidate that keeps it FAILs",
             "baseline", rev(repo), ["branch"], "FAIL", 1)

        repo = new_repo(tmp, "plan-change")
        commit(repo, "file.txt", "one\n", "one")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "baseline", root)
        git(repo, "checkout", "-q", "-b", "branch", "baseline")
        commit(repo, "file.txt", "two\n", "change the file")
        git(repo, "checkout", "-q", "-b", "candidate", "baseline")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge the branch", "branch")
        plan(repo, "plan a branch that changes a file and a candidate with that change PASSes",
             "baseline", rev(repo), ["branch"], "PASS", 0)

        repo = new_repo(tmp, "plan-landed")
        commit(repo, "a.txt", "a\n", "a")
        commit(repo, "b.txt", "b\n", "b")
        root = rev(repo)
        git(repo, "checkout", "-q", "-b", "landed", root)
        commit(repo, "a.txt", "a2\n", "landed change")
        git(repo, "checkout", "-q", "-b", "open", root)
        commit(repo, "b.txt", "b2\n", "open change")
        git(repo, "checkout", "-q", "-b", "baseline", root)
        commit(repo, "c.txt", "c\n", "a later trunk commit")
        git(repo, "merge", "-q", "--squash", "landed")
        git(repo, "commit", "-q", "-m", "squash of landed")
        git(repo, "checkout", "-q", "-b", "candidate", "baseline")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge open", "open")
        plan(repo, "plan a branch squashed into the baseline is landed and PASSes",
             "baseline", rev(repo), ["landed", "open"], "PASS", 0)
        out = read_json(os.path.join(repo, "out",
                                     "plan a branch squashed into the baseline is landed and PASSes",
                                     "compare-plan.json"))
        expect("plan names the squashed branch as landed",
               [x["ref"] for x in out["landed"]], ["landed"])
        git(repo, "checkout", "-q", "-b", "merged", root)
        commit(repo, "d.txt", "d\n", "merged change")
        git(repo, "checkout", "-q", "baseline")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge merged", "merged")
        git(repo, "checkout", "-q", "candidate")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge baseline", "baseline")
        plan(repo, "plan a branch merged into the baseline as commits PASSes",
             "baseline", rev(repo), ["landed", "merged", "open"], "PASS", 0)
        git(repo, "checkout", "-q", "-b", "partial", root)
        commit(repo, "e.txt", "e\n", "partial e")
        commit(repo, "f.txt", "f\n", "partial f")
        git(repo, "checkout", "-q", "baseline")
        git(repo, "cherry-pick", "partial~1")
        git(repo, "checkout", "-q", "candidate")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge baseline", "baseline")
        plan(repo, "plan a branch only partly in the baseline FAILs",
             "baseline", rev(repo), ["partial", "open"], "FAIL", 1)

        all_pass = {"ancestry.json": "PASS", "artifact-diff.json": "PASS",
                    "api-compat.json": "PASS", "e2e-compare-simple.json": "PASS",
                    "unit-compare.json": "PASS"}
        report(tmp, "report all checks PASS", all_pass, "PASS", 0)
        report(tmp, "report one check FAILs",
               {**all_pass, "artifact-diff.json": "FAIL"}, "FAIL", 1)
        report(tmp, "report one NOT RUN and the rest PASS is INCOMPLETE",
               {**all_pass, "e2e-compare-simple.json": "NOT RUN"}, "INCOMPLETE", 1)
        caught = {**all_pass, "artifact-diff.json": "FAIL", "e2e-compare-simple.json": "FAIL",
                  "e2e-compare-ha.json": "FAIL"}
        report(tmp, "report a broken candidate caught by artifacts and e2e exits 0",
               caught, "FAIL", 0, broken=True)
        report(tmp, "report a broken candidate one architecture misses exits 1",
               {**caught, "e2e-compare-ha.json": "PASS"}, "FAIL", 1, broken=True)
        report(tmp, "report a broken candidate whose e2e did not run exits 1",
               {**caught, "e2e-compare-simple.json": "NOT RUN"}, "FAIL", 1, broken=True)
        report(tmp, "report a broken candidate stopped by the ancestry check exits 1",
               {**caught, "ancestry.json": "FAIL"}, "FAIL", 1, broken=True)
        report(tmp, "report a broken candidate nothing catches exits 1",
               all_pass, "PASS", 1, broken=True)

        # T17: a ticket's rule must match in its own tree; nothing may be
        # UNEXPECTED in any tree.
        rule = "dist-file-added org/example/.*  # HADOOP-20012 changes this\n"
        attribution(tmp, "attribution a ticket rule unused in its own tree FAILs",
                    {"ticket-1": {
                        "artifact-diff.json": artifact_json(
                            unused=["line 1: dist-file-added org/example/.*"]),
                        "api-compat.json": api_json(),
                        "downstream-compare.json": downstream_json()}},
                    "FAIL", 1, rules={"expected-differences.txt": rule},
                    contains="HADOOP-20012 rule unused in its own tree")
        attribution(tmp, "attribution an UNEXPECTED difference in a prefix tree FAILs",
                    {"prefix-2": {
                        "artifact-diff.json": artifact_json(
                            unexpected=1,
                            diffs=[{"kind": "dist-file-added",
                                    "subject": "org/example/x",
                                    "status": "UNEXPECTED"}]),
                        "api-compat.json": api_json(),
                        "downstream-compare.json": downstream_json()}},
                    "FAIL", 1, contains="UNEXPECTED dist-file-added org/example/x")
        result = attribution(tmp, "attribution all trees matched PASS",
                             {"ticket-1": matched_tree(), "prefix-2": matched_tree()},
                             "PASS", 0, rules={"expected-differences.txt": rule})
        expect("attribution all trees matched: no problems",
               [p for t in result["trees"] for p in t["problems"]], [])
    print("test_comparators: ok")


if __name__ == "__main__":
    main()
