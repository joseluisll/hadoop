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

"""What each daemon actually loaded, from -Xlog:class+load output.

  classload.py summarize <classload dir> <dist dir>
      Writes <daemon>.classes.tsv (class<TAB>jar) next to each <daemon>.log
      and prints a JSON summary: classes per daemon and per jar.

  classload.py compare <baseline e2e results> <candidate e2e results>
      Prints JSON: per daemon, classes loaded on one side only and classes
      loaded from a different jar. JDK classes and classes generated at run
      time (lambdas, proxies, accessors) are left out.
"""

import collections
import json
import os
import re
import sys

LINE = re.compile(r"\]\s(\S+) source: (.+)$")
GENERATED = re.compile(r"(\$\$Lambda|\$Proxy\d|^jdk\.internal\.reflect\.Generated|"
                       r"\$\$FastClassBy|\$\$EnhancerBy|ByteBuddy|\$MockitoMock|"
                       r"^com\.sun\.proxy\.|/0x)")
VERSION = re.compile(r"-\d[\w.\-]*(?=\.jar$)")
# Jars outside the distribution (staged test tools) keep absolute paths, which
# name the side: <WORKDIR>/baseline/tools/... vs <WORKDIR>/candidate/tools/...
SIDE_ROOT = re.compile(r"^.*/(baseline|candidate)(?=/)")


def side_relative(path):
    return SIDE_ROOT.sub("<side>", path)


def jar_of(source, dist):
    """Jar file name relative to the distribution, or None for JDK/generated."""
    s = source.strip()
    if s.startswith(("jrt:", "shared objects file")) or s.startswith("__"):
        return None
    s = re.sub(r"^jar:", "", s)
    s = s.split("!")[0]
    s = re.sub(r"^file:", "", s)
    if dist and s.startswith(dist):
        s = os.path.relpath(s, dist)
    return s


def summarize(cl_dir, dist):
    summary = {}
    for name in sorted(os.listdir(cl_dir)):
        if not name.endswith(".log"):
            continue
        daemon = name[:-4]
        classes = {}
        with open(os.path.join(cl_dir, name), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = LINE.search(line.rstrip("\n"))
                if not m or GENERATED.search(m.group(1)):
                    continue
                jar = jar_of(m.group(2), dist)
                if jar:
                    classes.setdefault(m.group(1), jar)
        with open(os.path.join(cl_dir, daemon + ".classes.tsv"), "w", encoding="utf-8") as out:
            for c in sorted(classes):
                out.write(f"{c}\t{classes[c]}\n")
        per_jar = collections.Counter(os.path.basename(j) for j in classes.values())
        summary[daemon] = {"classes": len(classes), "jars": dict(sorted(per_jar.items()))}
    return summary


def load_tsv(path):
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                c, _, j = line.rstrip("\n").partition("\t")
                out[c] = j
    return out


def compare(b_res, c_res):
    b_dir, c_dir = os.path.join(b_res, "classload"), os.path.join(c_res, "classload")
    daemons = sorted({n[:-12] for d in (b_dir, c_dir) if os.path.isdir(d)
                      for n in os.listdir(d) if n.endswith(".classes.tsv")})
    result = {}
    for d in daemons:
        b = load_tsv(os.path.join(b_dir, d + ".classes.tsv"))
        c = load_tsv(os.path.join(c_dir, d + ".classes.tsv"))
        moved = {k: [b[k], c[k]] for k in sorted(b.keys() & c.keys())
                 if VERSION.sub("", os.path.basename(b[k])) !=
                 VERSION.sub("", os.path.basename(c[k])) or
                 side_relative(os.path.dirname(b[k])) != side_relative(os.path.dirname(c[k]))}
        result[d] = {
            "baseline_classes": len(b), "candidate_classes": len(c),
            "only_baseline": sorted(b.keys() - c.keys()),
            "only_candidate": sorted(c.keys() - b.keys()),
            "different_jar": moved,
        }
    return result


def main():
    if sys.argv[1] == "summarize":
        print(json.dumps(summarize(sys.argv[2], os.path.realpath(sys.argv[3]) + "/"), indent=1))
    elif sys.argv[1] == "compare":
        print(json.dumps(compare(sys.argv[2], sys.argv[3]), indent=1))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
