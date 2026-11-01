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

"""Classes that more than one jar provides on each downstream project's classpath.

Usage: downstream_classes.py <projects dir> <local maven repository>

Reads every module's target/jetty12-cp.txt (dependency:build-classpath) and
prints one line per package and set of jars that provide the same classes:
  <module path><TAB><package><TAB><group:artifact[:classifier],...><TAB><classes>
Jars are named by coordinates without version, so a version change of one jar
does not count as a new duplicate, but a jar replaced by another does. Which
copy a class loads from then depends on classpath order: the duplicate-jar
case a release note may have to warn downstream projects about.
"""

import collections
import os
import sys
import zipfile


def coordinates(jar, repo):
    """group:artifact[:classifier] of a jar in the (split) local repository."""
    rel = os.path.relpath(jar, repo).split(os.sep)
    if len(rel) < 5 or rel[0] == "..":
        return os.path.basename(jar)
    parts = rel[1:]  # drop the split prefix: cached/, installed-<side>/
    artifact, version, name = parts[-3], parts[-2], parts[-1]
    group = ".".join(parts[:-3])
    classifier = name[len(f"{artifact}-{version}"):-len(".jar")].lstrip("-")
    return f"{group}:{artifact}" + (f":{classifier}" if classifier else "")


def classes(jar):
    try:
        with zipfile.ZipFile(jar) as z:
            return [n[:-6] for n in z.namelist()
                    if n.endswith(".class") and not n.startswith("META-INF/")
                    and not n.endswith("module-info.class")]
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError):
        return []


def main(root, repo):
    cache = {}
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "src")]
        if os.path.basename(dirpath) != "target" or "jetty12-cp.txt" not in filenames:
            continue
        module = os.path.relpath(os.path.dirname(dirpath), root)
        with open(os.path.join(dirpath, "jetty12-cp.txt"), encoding="utf-8") as f:
            jars = [j for j in f.read().strip().split(os.pathsep) if j.endswith(".jar")]
        providers = collections.defaultdict(set)
        for jar in jars:
            if jar not in cache:
                cache[jar] = (coordinates(jar, repo), classes(jar))
            coord, names = cache[jar]
            for n in names:
                providers[n].add(coord)
        groups = collections.Counter()
        for n, coords in providers.items():
            if len(coords) > 1:
                package = n.rsplit("/", 1)[0].replace("/", ".") if "/" in n else ""
                groups[(package, ",".join(sorted(coords)))] += 1
        rows += [(module, p, c, k) for (p, c), k in groups.items()]
    for module, package, coords, count in sorted(rows):
        print(f"{module}\t{package}\t{coords}\t{count}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
