# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Run Hadoop's real comparison tests through Maven.

The oracle *predicts* what TestHdfsConfigFields and TestRBFConfigFields will
say, which is fast and needs no toolchain - but a prediction is not a result.
This module runs the actual tests, so a documentation patch can be verified
rather than merely believed.

Results come from the surefire XML report, not from scraping stdout: the
report distinguishes a failed assertion from a module that never compiled,
and those need different responses from whoever is reading.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

#: Maven and a JDK are the only external requirements the scanner ever has.
_MAVEN_NAMES = ("mvn", "mvn.cmd", "mvn.bat")


@dataclass
class TestOutcome:
    module_key: str
    test_class: str
    ok: bool = False
    ran: bool = False
    tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    seconds: float = 0.0
    #: Why it did not run, or which assertions failed.
    message: str = ""
    detail: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.ran:
            return f"DID NOT RUN - {self.message}"
        state = "PASS" if self.ok else "FAIL"
        return (f"{state} {self.tests} tests, {self.failures} failures, "
                f"{self.errors} errors, {self.skipped} skipped "
                f"({self.seconds:.0f}s)")


def find_maven() -> Optional[str]:
    for name in _MAVEN_NAMES:
        found = shutil.which(name)
        if found:
            return found
    home = os.environ.get("MAVEN_HOME") or os.environ.get("M2_HOME")
    if home:
        for name in _MAVEN_NAMES:
            candidate = os.path.join(home, "bin", name)
            if os.path.isfile(candidate):
                return candidate
    return None


def find_java() -> Optional[str]:
    found = shutil.which("java")
    if found:
        return found
    home = os.environ.get("JAVA_HOME")
    if home:
        for name in ("java", "java.exe"):
            candidate = os.path.join(home, "bin", name)
            if os.path.isfile(candidate):
                return candidate
    return None


def toolchain_problem() -> Optional[str]:
    """A human-readable reason the tests cannot run, or None if they can."""
    if find_java() is None:
        return ("no JDK found - install one and set JAVA_HOME "
                "(Hadoop trunk needs Java 8 or later)")
    if find_maven() is None:
        return "no Maven found - install it or set MAVEN_HOME"
    return None


def test_class_of(test_path: str) -> str:
    """Derive the fully qualified test class from its source path."""
    normalised = test_path.replace("\\", "/")
    marker = "src/test/java/"
    index = normalised.find(marker)
    if index < 0:
        return os.path.basename(normalised).replace(".java", "")
    return normalised[index + len(marker):].replace(".java", "").replace("/", ".")


def _surefire_report(repo: str, module_path: str, test_class: str) -> Optional[str]:
    path = os.path.join(repo, *module_path.split("/"), "target", "surefire-reports",
                        f"TEST-{test_class}.xml")
    return path if os.path.isfile(path) else None


def _parse_surefire(path: str, outcome: TestOutcome) -> None:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        outcome.message = f"could not read the surefire report: {exc}"
        return
    outcome.ran = True
    outcome.tests = int(root.get("tests", 0))
    outcome.failures = int(root.get("failures", 0))
    outcome.errors = int(root.get("errors", 0))
    outcome.skipped = int(root.get("skipped", 0))
    outcome.seconds = float(root.get("time", 0) or 0)
    outcome.ok = outcome.failures == 0 and outcome.errors == 0 and outcome.tests > 0
    for case in root.findall("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is None:
                continue
            text = (node.get("message") or node.text or "").strip()
            outcome.detail.append(f"{case.get('name')}: {text.splitlines()[0][:300]}"
                                  if text else case.get("name", ""))


#: Hadoop's build does more than compile Java, and on a plain developer box
#: those extras fail long before any test runs:
#:
#:   native-win  compiles winutils.exe with Visual Studio
#:   shelltest   runs the bats shell-script suite through bash
#:
#: Neither has any bearing on the configuration comparison tests, so a run that
#: only wants those disables both.
JAVA_ONLY_PROFILES = ["-P", "!native-win,!shelltest"]

#: Kept as the narrower option for callers that only hit the winutils problem.
WINDOWS_SKIP_NATIVE = ["-P", "!native-win"]


def extra_args(java_only: bool = False, skip_native_win: bool = False,
               mvn_arg: Optional[List[str]] = None) -> List[str]:
    """Turn the command-line switches into Maven arguments.

    One function so that `mvntest`, `step M5` and `pipeline` cannot end up
    invoking Maven differently from one another.
    """
    args: List[str] = []
    if java_only:
        args.extend(JAVA_ONLY_PROFILES)
    elif skip_native_win:
        args.extend(WINDOWS_SKIP_NATIVE)
    args.extend(mvn_arg or [])
    return args


def run_module(repo: str, spec, build_deps: bool = False,
               timeout: int = 3600, verbose: bool = False,
               extra_args: Optional[List[str]] = None) -> TestOutcome:
    """Run one module's comparison test and report what Maven actually did."""
    test_class = test_class_of(spec.test_path)
    outcome = TestOutcome(module_key=spec.key, test_class=test_class)

    problem = toolchain_problem()
    if problem:
        outcome.message = problem
        return outcome

    report = _surefire_report(repo, spec.module_path, test_class)
    if report and os.path.isfile(report):
        os.remove(report)          # never report a stale result as a fresh one

    command = [find_maven(), "test",
               "-Dtest=" + test_class.rsplit(".", 1)[-1],
               "-DfailIfNoTests=false",
               "-pl", spec.module_path]
    if build_deps:
        command.append("-am")      # also build the modules this one depends on
    command.extend(extra_args or [])

    started = time.time()
    try:
        completed = subprocess.run(command, cwd=repo, timeout=timeout,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace")
    except subprocess.TimeoutExpired:
        outcome.message = f"maven did not finish within {timeout}s"
        return outcome
    except OSError as exc:
        outcome.message = f"could not start maven: {exc}"
        return outcome

    log = completed.stdout or ""
    report = _surefire_report(repo, spec.module_path, test_class)
    if report:
        _parse_surefire(report, outcome)
    else:
        # No report means the test never executed - almost always a compile or
        # dependency failure, which is a different problem from a red test.
        unresolved = ("Could not find artifact org.apache.hadoop" in log
                      or "Could not resolve dependencies" in log)
        if unresolved:
            # The sibling modules have never been installed locally, so Maven
            # goes looking for them on apache.snapshots and prints a wall of
            # resolution errors that says nothing about the real cause.
            outcome.message = ("the other Hadoop modules are not in your local Maven "
                               "repository - re-run with --build-deps (first run on a "
                               "fresh checkout always needs it)")
        else:
            outcome.message = (f"maven exited {completed.returncode} without producing a "
                               f"surefire report; the module probably did not build")
        outcome.detail = _interesting_lines(log)
    if outcome.seconds == 0.0:
        outcome.seconds = time.time() - started
    if verbose:
        outcome.detail.extend(log.splitlines()[-40:])
    return outcome


def _interesting_lines(log: str, limit: int = 15) -> List[str]:
    keep = []
    for line in log.splitlines():
        if any(marker in line for marker in ("[ERROR]", "BUILD FAILURE", "Caused by:",
                                             "Could not resolve", "COMPILATION ERROR")):
            keep.append(line.strip())
        if len(keep) >= limit:
            break
    return keep


def run(repo: str, specs, build_deps: bool = False, timeout: int = 3600,
        verbose: bool = False,
        extra_args: Optional[List[str]] = None) -> List[TestOutcome]:
    return [run_module(repo, spec, build_deps, timeout, verbose, extra_args)
            for spec in specs if spec.test_path]
