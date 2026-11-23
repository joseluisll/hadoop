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
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compare_plan import PR_ORDER  # noqa: E402
E2E = os.path.join(HERE, "compare_e2e.py")
UNIT = os.path.join(HERE, "compare_unit.py")
PLAN = os.path.join(HERE, "compare_plan.py")
DOWNSTREAM = os.path.join(HERE, "compare_downstream.py")
DOWNSTREAM_CLASSES = os.path.join(HERE, "downstream_classes.py")
ANCESTRY = os.path.join(HERE, "ancestry.py")
REPORT = os.path.join(HERE, "report.py")
ATTRIBUTION = os.path.join(HERE, "attribution.py")
ARTIFACT = os.path.join(HERE, "artifact_diff.py")
API_COMPAT = os.path.join(HERE, "api_compat.py")


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


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
        classload=None, logscan=None, env=None, arch="simple"):
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
    r = run(E2E, "--expected", expected, "--out", out, "--arch", arch,
            os.path.join(base, "baseline"), os.path.join(base, "candidate"), env=env)
    result = read_result(case, os.path.join(out, f"e2e-compare-{arch}.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))
    return result


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


def downstream(tmp, case, baseline, candidate, verdict, rc, smoke=None, rules=""):
    base = os.path.join(tmp, "downstream", case)
    for side, deps in (("baseline", baseline), ("candidate", candidate)):
        write_text(os.path.join(base, side, "dependencies.tsv"), deps)
        if smoke and side in smoke:
            write_text(os.path.join(base, side, "smoke.tsv"), smoke[side])
    expected = os.path.join(base, "expected.txt")
    write_text(expected, rules)
    out = os.path.join(base, "out")
    r = run(DOWNSTREAM, "--expected", expected, "--out", out,
            os.path.join(base, "baseline"), os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "downstream-compare.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))


def downstream_classes(tmp, case, jars, repo=None):
    """Run downstream_classes.py on a synthetic project classpath. jars is a
    list of (group, artifact, version, {class: [methods]}) in classpath order."""
    repo = repo or os.path.join(tmp, "m2", case)
    project = os.path.join(tmp, "projects", case)
    cp = []
    for group, artifact, version, classes in jars:
        path = os.path.join(repo, "cached", *group.split("."), artifact, version,
                            f"{artifact}-{version}.jar")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for cls, methods in classes.items():
                z.writestr(cls + ".class", class_bytes(cls, methods))
        cp.append(path)
    write_text(os.path.join(project, "plain", "hadoop-common", "target", "jetty12-cp.txt"),
               os.pathsep.join(cp))
    r = run(DOWNSTREAM_CLASSES, project, repo)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


def artifact_diff(tmp, case, baseline, candidate, verdict, rc, rules="",
                  repo=None, baseline_ref=None, candidate_ref=None, env=None):
    base = os.path.join(tmp, "artifact", case)
    for side, dist in (("baseline", baseline), ("candidate", candidate)):
        results = os.path.join(base, side)
        os.makedirs(os.path.join(results, "build"), exist_ok=True)
        os.makedirs(os.path.join(results, "classpath"), exist_ok=True)
        write_text(os.path.join(results, "build", "dist-path.txt"), dist + "\n")
        write_text(os.path.join(results, "build", "dependencies.tsv"), "")
    expected = os.path.join(base, "expected.txt")
    write_text(expected, rules)
    out = os.path.join(base, "out")
    args = ["--expected", expected, "--out", out]
    if repo:
        args += ["--repo", repo, "--baseline-ref", baseline_ref,
                 "--candidate-ref", candidate_ref]
    args += [os.path.join(base, "baseline"), os.path.join(base, "candidate")]
    r = run(ARTIFACT, *args, env=env)
    result = read_result(case, os.path.join(out, "artifact-diff.json"), r)
    expect(case, (result["summary"]["unexpected"] == 0, r.returncode),
           (verdict == "PASS", rc))
    return result


def class_bytes(name, methods):
    """A minimal valid class file: one public class with public methods."""
    cp = []

    def utf(s):
        cp.append((1, s.encode()))
        return len(cp)

    def cls(s):
        i = utf(s)
        cp.append((7, i))
        return len(cp)

    this_i = cls(name)
    super_i = cls("java/lang/Object")
    code_i = utf("Code")
    entries = [(0x0001, utf(m), utf("()V")) for m in methods]
    out = struct.pack(">IHHH", 0xCAFEBABE, 0, 52, len(cp) + 1)
    for tag, data in cp:
        if tag == 1:
            out += struct.pack(">BH", 1, len(data)) + data
        elif tag == 7:
            out += struct.pack(">BH", 7, data)
    out += struct.pack(">HHHH", 0x0001, this_i, super_i, 0)
    out += struct.pack(">H", 0)   # fields
    out += struct.pack(">H", len(entries))
    for flags, mn, md in entries:
        out += struct.pack(">HHHH", flags, mn, md, 1)
        out += struct.pack(">HI", code_i, 0)   # empty Code attribute
    out += struct.pack(">H", 0)   # class attributes
    return out


def api_compat(tmp, case, baseline_jars, candidate_jars, verdict, rc, rules="",
               added=None):
    base = os.path.join(tmp, "api", case)
    for side, jars in (("baseline", baseline_jars), ("candidate", candidate_jars)):
        results = os.path.join(base, side)
        dist = os.path.join(results, "dist")
        os.makedirs(os.path.join(dist, "share", "lib"), exist_ok=True)
        os.makedirs(os.path.join(results, "build"), exist_ok=True)
        for jar, classes in jars.items():
            with zipfile.ZipFile(os.path.join(dist, "share", "lib", jar), "w") as z:
                for cls, data in classes.items():
                    z.writestr(cls + ".class", data)
        write_text(os.path.join(results, "build", "dist-path.txt"), dist + "\n")
    expected = os.path.join(base, "expected.txt")
    write_text(expected, rules)
    out = os.path.join(base, "out")
    r = run(API_COMPAT, "--expected", expected, "--out", out,
            os.path.join(base, "baseline"), os.path.join(base, "candidate"))
    result = read_result(case, os.path.join(out, "api-compat.json"), r)
    expect(case, (result["verdict"], r.returncode), (verdict, rc))
    if added is not None:
        expect(f"{case}: added_api", result.get("added_api"), added)
    return result


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


def report(tmp, case, checks, overall, rc, broken=False, same_commit=False, extra=None):
    results = os.path.join(tmp, "report", case)
    cmp_dir = os.path.join(results, "compare")
    os.makedirs(cmp_dir)
    if broken:
        write_text(os.path.join(results, "candidate", "build", "broken.txt"), "case test\n")
    if same_commit:
        for side in ("baseline", "candidate"):
            write_text(os.path.join(results, side, "build", "commit-subject.txt"),
                       "the same commit\n")
    for name, verdict in checks.items():
        write_json(os.path.join(cmp_dir, name),
                   {"verdict": verdict, **(extra or {}).get(name, {})})
    r = run(REPORT, results)
    lines = [line for line in r.stdout.splitlines() if line.startswith("overall: ")]
    assert lines, f"{case}: no 'overall:' line in stdout; stderr:\n{r.stderr.strip()}"
    expect(case, (lines[0].split()[1], r.returncode), (overall, rc))
    return read_text(os.path.join(cmp_dir, "report.md"))


RULE_FILES = ("expected-differences.txt", "expected-api-differences.txt",
              "expected-downstream-differences.txt")
ALL_TREES = ([f"ticket-{i}" for i in range(1, len(PR_ORDER) + 1)]
             + [f"prefix-{k}" for k in range(2, min(5, len(PR_ORDER)) + 1)])


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
        problems = list(result.get("problems", [])) + [
            p for t in result["trees"] for p in t["problems"]]
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
        # T39: a probe answer recorded by value shows both values in the DIFF.
        result = e2e(tmp, "e2e a JSON value difference shows both values",
                     [observation("probe", "probe-base",
                                  body={"json": {"mapping": {"match": "EXACT"}}})],
                     [observation("probe", "probe-base",
                                  body={"json": {"mapping": {"match": None}}})],
                     "FAIL", 1)
        detail = [r["detail"] for r in result["rows"] if r["key"] == "probe:probe-base"][0]
        expect("e2e a JSON value difference shows both values: detail",
               ('"EXACT"' in detail, "null" in detail), (True, True))
        # T52: the detail names every differing field with both values.
        result = e2e(tmp, "e2e a DIFF names every differing field",
                     [observation("comp", "one", a=1, b=2, c=3)],
                     [observation("comp", "one", a=10, b=20, c=30)], "FAIL", 1)
        detail = [r["detail"] for r in result["rows"] if r["key"] == "comp:one"][0]
        expect("e2e a DIFF names every differing field: detail",
               ("/a: 1 vs 10" in detail, "/b: 2 vs 20" in detail,
                "/c: 3 vs 30" in detail), (True, True, True))
        many = {f"k{i}": i for i in range(12)}
        result = e2e(tmp, "e2e a DIFF with twelve fields names ten and counts two",
                     [observation("comp", "one", **many)],
                     [observation("comp", "one", **{k: v + 100 for k, v in many.items()})],
                     "FAIL", 1)
        detail = [r["detail"] for r in result["rows"] if r["key"] == "comp:one"][0]
        expect("e2e a DIFF with twelve fields names ten and counts two",
               (detail.count(" vs "), detail.endswith("; ... and 2 more")), (10, True))

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
        # T37: a rule limited to some architectures applies only there, and is
        # not reported as unused elsewhere.
        result = e2e(tmp, "e2e an @arch rule does not match in another architecture",
                     [observation("comp", "one", status=200)],
                     [observation("comp", "one", status=500)], "FAIL", 1,
                     rules="obs comp:one  # expected @arch=secure\n")
        expect("e2e an @arch rule is not unused in another architecture",
               result["unused_rules"], [])
        e2e(tmp, "e2e an @arch rule matches in its architecture",
            [observation("comp", "one", status=200)],
            [observation("comp", "one", status=500)], "PASS", 0,
            rules="obs comp:one  # expected @arch=secure\n", arch="secure")

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
        # T14: container types are collected as daemons (R95); a class from a
        # different jar fails unless a classjar rule accepts it.
        e2e(tmp, "e2e a container type's class from another jar without a rule FAILs",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            classload={"baseline": {"map": {"org.example.Foo": "lib/jetty-foo.jar"}},
                       "candidate": {"map": {"org.example.Foo": "lib/jetty-bar.jar"}}})
        e2e(tmp, "e2e a container type's class from another jar with a rule PASSes",
            [observation("comp", "one")], [observation("comp", "one")], "PASS", 0,
            classload={"baseline": {"map": {"org.example.Foo": "lib/jetty-foo.jar"}},
                       "candidate": {"map": {"org.example.Foo": "lib/jetty-bar.jar"}}},
            rules="classjar map:org\\.example\\.Foo  # expected\n")
        # T44: the per-run application id, container id and filecache number of
        # a container's job.jar are masked before two paths are compared.
        job_jar = ("/w/%s/nm-local/usercache/u/appcache/application_%s_0001/"
                   "container_%s_0001_01_000002/filecache/%s/job.jar/job.jar")
        e2e(tmp, "e2e the same job.jar under two application ids is not a move",
            [observation("comp", "one")], [observation("comp", "one")], "PASS", 0,
            classload={"baseline": {"map": {"org.example.Foo":
                                            job_jar % ("baseline", "111", "111", "10")}},
                       "candidate": {"map": {"org.example.Foo":
                                             job_jar % ("candidate", "222", "222", "33")}}})
        e2e(tmp, "e2e a job.jar with another name is still a move",
            [observation("comp", "one")], [observation("comp", "one")], "FAIL", 1,
            classload={"baseline": {"map": {"org.example.Foo":
                                            job_jar % ("baseline", "111", "111", "10")}},
                       "candidate": {"map": {"org.example.Foo":
                                             (job_jar % ("candidate", "222", "222", "33"))
                                             .replace("job.jar/job.jar", "other.jar/other.jar")}}})
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
        # T26: a smoke step ok on the baseline and failing on the candidate
        # FAILs; a changed servlet version is a difference a rule accepts.
        deps = "simple/hadoop-common\tg:a:jar:1.0:compile\n"
        downstream(tmp, "downstream a smoke regression FAILs", deps, deps, "FAIL", 1,
                   smoke={"baseline": "plain\thadoop-common\thttpserver2\tok\t3.1\t"
                                      "javax.servlet-api-3.1.0.jar\t\n",
                          "candidate": "plain\thadoop-common\thttpserver2\tfail\t\t\tboom\n"})
        downstream(tmp, "downstream a smoke change with a rule PASSes", deps, deps, "PASS", 0,
                   smoke={"baseline": "plain\thadoop-common\thttpserver2\tok\t3.1\t"
                                      "javax.servlet-api-3.1.0.jar\t\n",
                          "candidate": "plain\thadoop-common\thttpserver2\tok\t4.0\t"
                                       "jetty-servlet-api-4.0.9.jar\t\n"},
                   rules="downstream-smoke-changed plain/hadoop-common\\|httpserver2  # expected\n")

        # T27: the duplicate's winner is the first jar in classpath order, and
        # a winner missing a public method of another copy is reported.
        rows = downstream_classes(tmp, "t27", [
            ("g", "a", "1", {"C": ["m"]}),
            ("g", "b", "1", {"C": ["m", "n"]}),
        ])
        expect("downstream_classes T27 the winner is the first jar in classpath order",
               rows[0][4], "g:a:1")
        expect("downstream_classes T27 a winner missing a public method is reported",
               ("winner lacks" in rows[0][5], rows[0][6]), (True, "breaking"))
        # The same on the two real servlet jars, when they are on this machine.
        javax = ("/home/jllopez/.m2/repository/javax/servlet/javax.servlet-api/3.1.0/"
                 "javax.servlet-api-3.1.0.jar")
        jetty = ("/home/jllopez/.m2/repository/org/eclipse/jetty/toolchain/"
                 "jetty-servlet-api/4.0.9/jetty-servlet-api-4.0.9.jar")
        if os.path.exists(javax) and os.path.exists(jetty):
            repo = os.path.join(tmp, "m2", "t27-real")
            cp = []
            for jar in (javax, jetty):
                dest = os.path.join(repo, "cached",
                                    os.path.relpath(jar, "/home/jllopez/.m2/repository"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                os.symlink(jar, dest)
                cp.append(dest)
            project = os.path.join(tmp, "projects", "t27-real")
            write_text(os.path.join(project, "plain", "hadoop-common", "target",
                                    "jetty12-cp.txt"), os.pathsep.join(cp))
            r = run(DOWNSTREAM_CLASSES, project, repo)
            assert r.returncode == 0, r.stderr
            http = [line.split("\t") for line in r.stdout.splitlines()
                    if line.split("\t")[1] == "javax.servlet.http"]
            expect("downstream_classes T27 the real 3.1.0 jar wins over 4.0.9",
                   http[0][4], "javax.servlet:javax.servlet-api:3.1.0")
            expect("downstream_classes T27 the real winner lacks 4.0.9 members",
                   "winner lacks" in http[0][5], True)

        # T12: POMs between two git refs. The distributions are empty, so only
        # the POM comparison contributes differences.
        poms = new_repo(tmp, "poms")
        dist = os.path.join(tmp, "artifact", "dist")
        os.makedirs(dist)
        pom = (
            '<?xml version="1.0"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            '  <groupId>org.example</groupId>\n'
            '  <artifactId>parent</artifactId>\n'
            '  <version>1.0</version>\n'
            '  <dependencies>\n'
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>dep</artifactId><version>1.0</version></dependency>\n'
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>no-version</artifactId></dependency>\n'
            '  </dependencies>\n'
            '  <dependencyManagement><dependencies>\n'
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>managed</artifactId><version>1.0</version></dependency>\n'
            '  </dependencies></dependencyManagement>\n'
            '</project>\n'
        )
        commit(poms, "pom.xml", pom, "base")
        base = rev(poms)
        artifact_diff(tmp, "artifact T12 self-compare reports nothing",
                      dist, dist, "PASS", 0, repo=poms, baseline_ref=base,
                      candidate_ref=base)
        commit(poms, "pom.xml", pom.replace(
            "<artifactId>dep</artifactId><version>1.0</version>",
            "<artifactId>dep</artifactId><version>1.0</version>"
            "<scope>provided</scope>"), "scope")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 a dependency change FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 a dependency change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-changed .*\\|org\\.example:dep  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>no-version</artifactId></dependency>\n',
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>no-version</artifactId></dependency>\n'
            '    <dependency><groupId>org.example</groupId>'
            '<artifactId>new</artifactId><version>1.0</version></dependency>\n'), "added")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 an added dependency FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 an added dependency with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-added .*\\|org\\.example:new  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            "<artifactId>managed</artifactId><version>1.0</version>",
            "<artifactId>managed</artifactId><version>2.0</version>"), "managed")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 a managed version change FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 a managed version change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-managed-changed .*\\|org\\.example:managed  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            "</project>",
            "<parent><groupId>org.example</groupId><artifactId>p</artifactId>"
            "<version>2.0</version></parent></project>"), "parent")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 a parent change FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 a parent change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-parent-changed .*\\|parent  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            "    <dependency><groupId>org.example</groupId>"
            "<artifactId>dep</artifactId><version>1.0</version></dependency>\n", ""),
            "removed")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 a removed dependency FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 a removed dependency with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-removed .*\\|org\\.example:dep  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace("</project>", ""), "unparseable")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 a POM that cannot be parsed FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            "<artifactId>dep</artifactId><version>1.0</version></dependency>",
            "<artifactId>dep</artifactId><version>1.0</version>"
            "<optional>true</optional></dependency>"), "optional")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 an optional change FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 an optional change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-changed .*\\|org\\.example:dep  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)
        commit(poms, "pom.xml", pom.replace(
            "<artifactId>dep</artifactId><version>1.0</version></dependency>",
            "<artifactId>dep</artifactId><version>1.0</version><exclusions>"
            "<exclusion><groupId>org.example</groupId>"
            "<artifactId>excluded</artifactId></exclusion></exclusions></dependency>"),
            "exclusion")
        candidate = rev(poms)
        artifact_diff(tmp, "artifact T12 an exclusion change FAILs",
                      dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                      candidate_ref=candidate)
        artifact_diff(tmp, "artifact T12 an exclusion change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-changed .*\\|org\\.example:dep  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)

        # T40: a direct dependency's declared version is compared; a dependency
        # with no <version> (managed elsewhere) still compares equal.
        commit(poms, "pom.xml", pom.replace(
            "<artifactId>dep</artifactId><version>1.0</version>",
            "<artifactId>dep</artifactId><version>1.1</version>"), "version")
        candidate = rev(poms)
        result = artifact_diff(tmp, "artifact T40 a dependency version change FAILs",
                               dist, dist, "FAIL", 1, repo=poms, baseline_ref=base,
                               candidate_ref=candidate)
        expect("artifact T40 only the versioned dependency changes",
               [d["subject"] for d in result["differences"]
                if d["kind"] == "pom-dependency-changed"],
               ["org.example:parent|org.example:dep"])
        expect("artifact T40 the version is in the detail",
               "version=1.0" in result["differences"][0]["detail"]
               and "version=1.1" in result["differences"][0]["detail"], True)
        artifact_diff(tmp, "artifact T40 a dependency version change with a rule PASSes",
                      dist, dist, "PASS", 0,
                      rules="pom-dependency-changed .*\\|org\\.example:dep  # expected\n",
                      repo=poms, baseline_ref=base, candidate_ref=candidate)

        # T41: the detail must be the same bytes under any hash seed.
        det = new_repo(tmp, "deterministic")
        dep = ('    <dependency><groupId>org.example</groupId>'
               '<artifactId>dep</artifactId><version>1.0</version>'
               '<exclusions><exclusion><groupId>org.example</groupId>'
               '<artifactId>a</artifactId></exclusion>'
               '<exclusion><groupId>org.example</groupId>'
               '<artifactId>b</artifactId></exclusion></exclusions></dependency>\n')
        det_pom = ('<?xml version="1.0"?>\n'
                   '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
                   '  <groupId>org.example</groupId>\n'
                   '  <artifactId>parent</artifactId>\n'
                   '  <version>1.0</version>\n'
                   '  <dependencies>\n' + dep + '  </dependencies>\n</project>\n')
        commit(det, "pom.xml", det_pom, "base")
        det_base = rev(det)
        commit(det, "pom.xml", det_pom.replace(
            "</exclusions></dependency>",
            "<exclusion><groupId>org.example</groupId>"
            "<artifactId>c</artifactId></exclusion></exclusions></dependency>"), "exclusions")
        det_candidate = rev(det)
        details = [artifact_diff(
                       tmp, f"artifact T41 deterministic detail (seed {seed})",
                       dist, dist, "FAIL", 1, repo=det, baseline_ref=det_base,
                       candidate_ref=det_candidate, env={"PYTHONHASHSEED": seed}
                   )["differences"][0]["detail"]
                   for seed in ("1", "2")]
        expect("artifact T41 the detail is the same under two hash seeds",
               details[0], details[1])

        # T15: LICENSE-binary and NOTICE-binary consistency.
        def dist_with(name, jars, lic, notice="", jar_notices=None):
            d = os.path.join(tmp, "artifact", "dist-" + name)
            os.makedirs(os.path.join(d, "share", "lib"), exist_ok=True)
            for jar in jars:
                path = os.path.join(d, "share", "lib", jar)
                if jar_notices and jar in jar_notices:
                    with zipfile.ZipFile(path, "w") as z:
                        z.writestr("META-INF/NOTICE.txt", jar_notices[jar])
                else:
                    write_text(path, "")
            write_text(os.path.join(d, "LICENSE-binary"), lic)
            write_text(os.path.join(d, "NOTICE-binary"), notice)
            return d
        b = dist_with("b", ["foo.jar"], "foo.jar\n")
        c = dist_with("c", ["foo.jar", "bar.jar"], "foo.jar\n")
        artifact_diff(tmp, "artifact T15 a candidate-only missing jar FAILs",
                      b, c, "FAIL", 1)
        artifact_diff(tmp, "artifact T15 a candidate-only missing jar with a rule PASSes",
                      b, c, "PASS", 0,
                      rules="license-jar-missing bar\\.jar  # expected\n"
                            "dist-file-added share/lib/bar\\.jar  # the jar is new\n")
        b2 = dist_with("b2", ["foo.jar"], "foo.jar\n")
        c2 = dist_with("c2", ["foo.jar"], "foo.jar\nbar.jar\n")
        artifact_diff(tmp, "artifact T15 a candidate-only stale entry FAILs",
                      b2, c2, "FAIL", 1)
        artifact_diff(tmp, "artifact T15 a candidate-only stale entry with a rule PASSes",
                      b2, c2, "PASS", 0,
                      rules="license-entry-stale bar\\.jar  # expected\n"
                            "dist-file-changed LICENSE-binary  # the entry was added\n")
        b3 = dist_with("b3", ["foo.jar"], "")
        c3 = dist_with("c3", ["foo.jar"], "")
        artifact_diff(tmp, "artifact T15 a mismatch on both sides does not fail",
                      b3, c3, "PASS", 0)
        # A new candidate jar that ships its own META-INF/NOTICE must be
        # named in NOTICE-binary by artifactId or project name.
        b4 = dist_with("b4", ["foo.jar"], "foo.jar\n")
        c4 = dist_with("c4", ["foo.jar", "widget.jar"], "foo.jar\nwidget.jar\n",
                       jar_notices={"widget.jar": "Widget Project\n"})
        artifact_diff(tmp, "artifact T15 a new jar's NOTICE not in NOTICE-binary FAILs",
                      b4, c4, "FAIL", 1)
        artifact_diff(tmp, "artifact T15 a new jar's NOTICE not in NOTICE-binary with a rule PASSes",
                      b4, c4, "PASS", 0,
                      rules="notice-missing widget\\.jar  # expected\n"
                            "dist-file-added share/lib/widget\\.jar  # the jar is new\n"
                            "dist-file-changed LICENSE-binary  # the entry was added\n")
        c5 = dist_with("c5", ["foo.jar", "widget.jar"], "foo.jar\nwidget.jar\n",
                       notice="Widget Project\n",
                       jar_notices={"widget.jar": "Widget Project\n"})
        artifact_diff(tmp, "artifact T15 a new jar's NOTICE named in NOTICE-binary PASSes",
                      b4, c5, "PASS", 0,
                      rules="dist-file-added share/lib/widget\\.jar  # the jar is new\n"
                            "dist-file-changed LICENSE-binary  # the entry was added\n"
                            "dist-file-changed NOTICE-binary  # the entry was added\n")

        # T50: an artifact bundled in a shaded client jar counts as shipped.
        def bundled_dist(name, lic):
            d = os.path.join(tmp, "artifact", "dist-" + name)
            client = os.path.join(d, "share", "hadoop", "client")
            os.makedirs(client)
            with zipfile.ZipFile(os.path.join(client, "hadoop-client-x.jar"), "w") as z:
                # The shaded jar's own coordinate is Hadoop's, so it is skipped
                # as a jar file; the bundled ones are what the check must see.
                z.writestr("META-INF/maven/org.apache.hadoop/hadoop-client-x/pom.properties",
                           "groupId=org.apache.hadoop\nartifactId=hadoop-client-x\nversion=1\n")
                z.writestr("META-INF/maven/g/a/pom.properties",
                           "groupId=g\nartifactId=a\nversion=1\n")
                z.writestr("META-INF/maven/g/b/pom.properties",
                           "groupId=g\nartifactId=b\nversion=1\n")
            write_text(os.path.join(d, "LICENSE-binary"), lic)
            write_text(os.path.join(d, "NOTICE-binary"), "")
            return d
        b50 = bundled_dist("b50", "g:a:1\n")
        c50 = bundled_dist("c50", "g:a:1\n")
        result = artifact_diff(tmp, "artifact T50 a bundled artifact is not stale",
                               b50, c50, "PASS", 0)
        expect("artifact T50 a bundled artifact is not stale: no stale entry",
               [x["subject"] for x in result["differences"]
                if x["kind"] == "license-entry-stale"], [])
        expect("artifact T50 an unlisted bundled artifact is missing",
               [x["subject"] for x in result["differences"]
                if x["kind"] == "license-jar-missing"], ["g:b:1"])

        # T23: a replaced third-party jar's added public types and members are
        # listed, and the verdict does not change.
        old = {"old-1.0.jar": {"A": class_bytes("A", ["m"])}}
        new = {"old-2.0.jar": {"A": class_bytes("A", ["m", "n"]),
                               "B": class_bytes("B", ["m"])}}
        result = api_compat(tmp, "api T23 added types and members are listed",
                            old, new, "PASS", 0)
        expect("api T23 added types", result["added_api"][0]["types"], ["B"])
        expect("api T23 added members", result["added_api"][0]["members"], ["A#n()V"])

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
        # T45: a self-comparison (R68) is a gate on the baseline.
        text = report(tmp, "report a self-comparison that passes writes PASS",
                      all_pass, "PASS", 0, same_commit=True)
        expect("report a self-comparison that passes writes PASS: line",
               "Harness check: **PASS**" in text, True)
        text = report(tmp, "report a self-comparison with a FAIL check writes FAIL",
                      {**all_pass, "artifact-diff.json": "FAIL"}, "FAIL", 1,
                      same_commit=True)
        expect("report a self-comparison with a FAIL check names it",
               "Harness check: **FAIL**: *Artifacts and dependencies* did not pass" in text,
               True)
        # T54: the gate also fails on an unexpected one-side class, even with
        # CLASSONLY_FAIL off, and names it.
        text = report(tmp, "report a self-comparison with an unexpected one-side class FAILs",
                      all_pass, "PASS", 0, same_commit=True,
                      extra={"e2e-compare-simple.json": {"one_side_classes": [
                          {"daemon": "nn", "side": "candidate",
                           "class": "org.example.Foo", "expected": False, "reason": None}]}})
        expect("report a self-comparison with an unexpected one-side class FAILs: line",
               ("Harness check: **FAIL**" in text, "org.example.Foo" in text), (True, True))
        text = report(tmp, "report a self-comparison with only expected one-side classes PASSes",
                      all_pass, "PASS", 0, same_commit=True,
                      extra={"e2e-compare-simple.json": {"one_side_classes": [
                          {"daemon": "nn", "side": "candidate",
                           "class": "org.example.Foo", "expected": True,
                           "reason": "expected"}]}})
        expect("report a self-comparison with only expected one-side classes PASSes: line",
               "Harness check: **PASS**" in text, True)
        text = report(tmp, "report a normal run writes no self-comparison line",
                      all_pass, "PASS", 0)
        expect("report a normal run writes no self-comparison line",
               "Harness check" in text, False)
        text = report(tmp, "report a broken candidate keeps its own line",
                      caught, "FAIL", 0, broken=True)
        expect("report a broken candidate keeps its own line",
               "Harness check: **PASS**: the artifacts" in text, True)

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
                             {t: matched_tree() for t in ALL_TREES},
                             "PASS", 0, rules={"expected-differences.txt": rule})
        expect("attribution all trees matched: no problems",
               [p for t in result["trees"] for p in t["problems"]], [])
        # T48: a ticket tree from the second ticket on applies one ticket
        # without its merge predecessors, a state that never ships, so an
        # UNEXPECTED difference there is an interaction and does not fail it.
        # ticket-1 is also prefix-1, and every prefix tree is shippable.
        interaction = {"artifact-diff.json": artifact_json(
                           unexpected=1,
                           diffs=[{"kind": "pom-dependency-changed",
                                   "subject": "a|org.example:x",
                                   "status": "UNEXPECTED"}]),
                       "api-compat.json": api_json(),
                       "downstream-compare.json": downstream_json()}
        own_rule = {"expected-differences.txt":
                    "dist-file-added org/example/.*  # HADOOP-20014 changes this\n"}
        result = attribution(tmp, "attribution an UNEXPECTED difference in ticket-2 "
                             "is an interaction",
                             {**{t: matched_tree() for t in ALL_TREES},
                              "ticket-2": interaction}, "PASS", 0, rules=own_rule)
        tree = [t for t in result["trees"] if t["tree"] == "ticket-2"][0]
        expect("attribution an UNEXPECTED difference in ticket-2 is an interaction: "
               "listed", tree["interactions"],
               ["artifact-diff: UNEXPECTED pom-dependency-changed a|org.example:x"])
        expect("attribution an UNEXPECTED difference in ticket-2 is an interaction: "
               "no problems", tree["problems"], [])
        attribution(tmp, "attribution an UNEXPECTED difference in ticket-1 FAILs",
                    {**{t: matched_tree() for t in ALL_TREES},
                     "ticket-1": interaction}, "FAIL", 1,
                    contains="UNEXPECTED pom-dependency-changed a|org.example:x")
        attribution(tmp, "attribution an UNEXPECTED difference in prefix-2 FAILs",
                    {**{t: matched_tree() for t in ALL_TREES},
                     "prefix-2": interaction}, "FAIL", 1,
                    contains="UNEXPECTED pom-dependency-changed a|org.example:x")
        attribution(tmp, "attribution an unused own-ticket rule in ticket-2 FAILs",
                    {**{t: matched_tree() for t in ALL_TREES},
                     "ticket-2": {"artifact-diff.json": artifact_json(
                         unused=["line 1: dist-file-added org/example/.*"]),
                         "api-compat.json": api_json(),
                         "downstream-compare.json": downstream_json()}},
                    "FAIL", 1, rules=own_rule,
                    contains="HADOOP-20014 rule unused in its own tree")
        # T47: a tree whose job failed leaves no directory; it is expected from
        # PR_ORDER, named, and fails the run.
        missing = [t for t in ALL_TREES if t != "prefix-3"]
        result = attribution(tmp, "attribution a missing tree FAILs",
                             {t: matched_tree() for t in missing}, "FAIL", 1,
                             contains="missing tree prefix-3")
        expect("attribution a missing tree FAILs: named",
               any("prefix-3" in p for p in result.get("problems", [])), True)
    print("test_comparators: ok")


if __name__ == "__main__":
    main()
