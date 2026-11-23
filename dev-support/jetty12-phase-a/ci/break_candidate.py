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

"""Break an unpacked candidate distribution on purpose, to check the harness.

Usage: break_candidate.py <distribution dir> <out file> (--case NAME | SPEC...)

Every comparison must then fail. What was changed is written to <out file>
(the report shows it). A spec that changes nothing is an error, so a case
that no longer applies cannot pass unnoticed.

Specs:
  rm:<glob>                          delete files; the glob is matched against
                                     the path relative to the distribution
                                     (* also crosses /)
  set:<jar glob>!<resource>!<name>=<value>
                                     change a property's value in an XML
                                     configuration resource inside the jars
  <glob>                             a jar file name anywhere under share/
                                     (same as rm:share/*/<glob>)
"""

import argparse
import fnmatch
import os
import re
import shutil
import sys
import tempfile
import zipfile

# Named cases, chosen by the run branch name jetty12-phase-a-<arch>-run-broken-<case>-<n>.
CASES = {
    # The only javax.annotation jar after HADOOP-20013: a dependency the patch
    # relies on goes missing.
    "annotation": ["rm:share/*/jakarta.annotation-api-*.jar"],
    # Every web server loses Jetty's HTTP classes: a massive failure.
    "jetty": ["rm:share/*/jetty-http-*.jar"],
    # One static file of the namenode UI disappears: a narrow failure that
    # most checks do not see.
    "static": ["rm:share/hadoop/hdfs/webapps/static/hadoop.css"],
    # A changed default and nothing missing: WebHDFS accepts only the user
    # "hdfs", so the harness user is rejected.
    "webhdfs-user": ["set:share/hadoop/hdfs/hadoop-hdfs-[0-9]*.jar!hdfs-default.xml!"
                     "dfs.webhdfs.user.provider.user.pattern=^hdfs$"],
}


def files(dist):
    for root, _, names in os.walk(dist):
        for n in names:
            yield os.path.relpath(os.path.join(root, n), dist)


def remove(dist, glob):
    done = []
    for rel in sorted(files(dist)):
        if fnmatch.fnmatchcase(rel, glob):
            os.remove(os.path.join(dist, rel))
            done.append(f"removed {rel}")
    return done


def set_property(dist, jar_glob, resource, name, value):
    prop = re.compile(r"(<name>\s*" + re.escape(name) + r"\s*</name>\s*<value>)(.*?)(</value>)",
                      re.S)
    done = []
    for rel in sorted(files(dist)):
        if not fnmatch.fnmatchcase(rel, jar_glob):
            continue
        path = os.path.join(dist, rel)
        with zipfile.ZipFile(path) as zin:
            if resource not in zin.namelist():
                continue
            text = zin.read(resource).decode("utf-8")
            old = prop.search(text)
            if not old:
                continue
            new_text = prop.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".jar")
            os.close(fd)
            with zipfile.ZipFile(tmp, "w") as zout:
                for info in zin.infolist():
                    data = new_text.encode("utf-8") if info.filename == resource \
                        else zin.read(info)
                    zout.writestr(info, data)
        shutil.move(tmp, path)
        done.append(f"set {name}={value} (was {old.group(2)}) in {rel}!{resource}")
    return done


def apply(dist, spec):
    if spec.startswith("rm:"):
        return remove(dist, spec[3:])
    if spec.startswith("set:"):
        jar_glob, resource, assignment = spec[4:].split("!", 2)
        name, _, value = assignment.partition("=")
        return set_property(dist, jar_glob, resource, name, value)
    return remove(dist, "share/*/" + spec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("out")
    ap.add_argument("--case", choices=sorted(CASES))
    ap.add_argument("specs", nargs="*")
    a = ap.parse_args()
    specs = CASES[a.case] if a.case else a.specs
    if not specs:
        ap.error("give --case or at least one spec")
    report = []
    for spec in specs:
        done = apply(a.dist, spec)
        if not done:
            sys.exit(f"break_candidate: '{spec}' changed nothing in {a.dist}")
        report += done
    with open(a.out, "w", encoding="utf-8") as f:
        f.write((f"case {a.case}\n" if a.case else "") + "\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
