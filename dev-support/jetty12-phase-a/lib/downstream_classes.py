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
  <TAB><winner><TAB><gap>
Jars are named by coordinates without version, so a version change of one jar
does not count as a new duplicate, but a jar replaced by another does. Which
copy a class loads from then depends on classpath order: the duplicate-jar
case a release note may have to warn downstream projects about. The winner is
the first jar of the set in that order (T27); the gap says what public classes
or members it lacks that another copy has, when the jars are on disk.
"""

import collections
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_compat  # noqa: E402
import classfile as cf  # noqa: E402


def coordinate(jar, repo, with_version=False):
    """group:artifact[:classifier] of a jar in the (split) local repository,
    with its version when asked."""
    rel = os.path.relpath(jar, repo).split(os.sep)
    if len(rel) < 5 or rel[0] == "..":
        return os.path.basename(jar)
    parts = rel[1:]  # drop the split prefix: cached/, installed-<side>/
    artifact, version, name = parts[-3], parts[-2], parts[-1]
    group = ".".join(parts[:-3])
    classifier = name[len(f"{artifact}-{version}"):-len(".jar")].lstrip("-")
    if with_version:
        return f"{group}:{artifact}:{version}" + (f":{classifier}" if classifier else "")
    return f"{group}:{artifact}" + (f":{classifier}" if classifier else "")


def coordinates(jar, repo):
    return coordinate(jar, repo)


def classes(jar):
    try:
        with zipfile.ZipFile(jar) as z:
            return [n[:-6] for n in z.namelist()
                    if n.endswith(".class") and not n.startswith("META-INF/")
                    and not n.endswith("module-info.class")]
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError):
        return []


def public_api(jar):
    """{class: ClassInfo} for the public classes of a jar."""
    out = {}
    try:
        with zipfile.ZipFile(jar) as z:
            for n in z.namelist():
                if n.endswith(".class") and not n.startswith("META-INF/") \
                        and n != "module-info.class":
                    try:
                        info = cf.parse(z.read(n))
                    except (ValueError, TypeError):
                        continue
                    if info.visible:
                        out[info.name] = info
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError):
        pass
    return out


def winner_gap(winner, others):
    """(what the winner lacks that another copy provides, its severity).

    Reuses check 2's class-file comparison: a public class only another copy
    has, or a public member of one that the winner does not (T27)."""
    w = public_api(winner)
    resolver = api_compat.Resolver(api_compat.Jars(""), {})
    missing_classes, missing_members, severities = set(), set(), set()
    for other in others:
        for cls, info in public_api(other).items():
            if cls not in w:
                missing_classes.add(cls)
                severities.add("breaking")
                continue
            for kind, member, _ in api_compat.compare_class(info, w[cls], resolver, winner):
                if kind in ("api-member-removed", "api-member-visibility-reduced"):
                    missing_members.add(f"{cls}#{member}")
                    severities.add(api_compat.SEVERITY[kind])
    if not missing_classes and not missing_members:
        return "", ""
    parts = []
    if missing_classes:
        parts.append(f"{len(missing_classes)} public class(es)")
    if missing_members:
        parts.append(f"{len(missing_members)} public member(s)")
    severity = "implementor" if "implementor" in severities else "breaking"
    return "winner lacks " + " and ".join(parts) + " another copy has", severity


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
        for (package, coords), count in groups.items():
            wanted = set(coords.split(","))
            copies = [j for j in jars if coordinates(j, repo) in wanted]
            winner = copies[0] if copies else None
            gap, severity = winner_gap(winner, copies[1:]) if winner else ("", "")
            rows.append((module, package, coords, count,
                         coordinate(winner, repo, with_version=True) if winner else "",
                         gap, severity))
    for module, package, coords, count, winner, gap, severity in sorted(rows):
        print(f"{module}\t{package}\t{coords}\t{count}\t{winner}\t{gap}\t{severity}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
