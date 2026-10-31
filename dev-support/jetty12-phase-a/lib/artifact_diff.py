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

"""Compare what the baseline and candidate builds ship.

Usage:
  artifact_diff.py --expected expected-differences.txt --out DIR \\
      BASELINE_RESULTS CANDIDATE_RESULTS

Each *_RESULTS directory is a side's results directory holding
build/dist-path.txt, build/dependencies.tsv and classpath/<command>.txt
(written by artifact-diff.sh).

Four comparisons, each difference matched against the allowlist:
  dist-file-removed / dist-file-added   files in the binary distribution
  jar-entry-removed / -added / -changed entries of jars present on both sides
                                        (by CRC; build metadata ignored)
  class-removed / class-added           classes visible on each command's
                                        classpath (hadoop, hdfs, yarn, mapred)
  class-source-changed                  the jar a class is first loaded from
  dep-removed / dep-added               every module's resolved dependencies

Writes DIR/artifact-diff.json and DIR/artifact-diff.md. Exits 1 when any
difference is not in the allowlist.
"""

import argparse
import collections
import hashlib
import io
import json
import os
import re
import sys
import zipfile

# Entries that differ between any two builds of the same source.
VOLATILE_ENTRY = re.compile(
    r"(^META-INF/MANIFEST\.MF$"
    r"|^META-INF/maven/.*/pom\.(xml|properties)$"
    r"|^META-INF/DEPENDENCIES$"
    r"|-version-info\.properties$"
    r"|^httpfs\.properties$"  # build time, user and revision
    r"|^META-INF/.*\.SF$|^META-INF/.*\.RSA$|^META-INF/.*\.DSA$)")
# Files in the distribution that differ between any two builds.
VOLATILE_FILE = re.compile(r"(\.pid$|/logs/|-version-info\.properties$)")
ARCHIVE = (".jar", ".war")


class Allowlist:
    """Lines of '<kind> <regex>  # reason'. Both are regexes; each matches the
    whole kind or subject (a kind such as 'dep-(removed|added)' covers two).
    The reason starts at a '#' with whitespace on both sides (or at the start
    of the line), so a regex may contain '#', as API subjects do
    ('Class#method')."""

    COMMENT = re.compile(r"(^|\s)#(\s|$)")

    def __init__(self, path):
        self.rules = []
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                m = self.COMMENT.search(line)
                body, reason = (line[:m.start()], line[m.end():]) if m else (line, "")
                body = body.strip()
                if not body:
                    continue
                kind, _, regex = body.partition(" ")
                self.rules.append({"kind": kind, "kind_re": re.compile(kind),
                                   "regex": re.compile(regex.strip()),
                                   "pattern": regex.strip(), "reason": reason.strip(),
                                   "line": n, "hits": 0})

    def match(self, kind, subject):
        for r in self.rules:
            if r["kind_re"].fullmatch(kind) and r["regex"].fullmatch(subject):
                r["hits"] += 1
                return r
        return None


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dist_files(root):
    files = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if not VOLATILE_FILE.search("/" + rel) and not os.path.islink(full):
                files[rel] = full
    return files


def jar_entries(path):
    """{entry name: crc} for non-directory, non-volatile entries. A jar nested
    in the archive (a WAR's WEB-INF/lib) is summed over its own non-volatile
    entries, so its build metadata does not count as a change."""
    try:
        with zipfile.ZipFile(path) as z:
            out = {}
            for i in z.infolist():
                if i.is_dir() or VOLATILE_ENTRY.search(i.filename):
                    continue
                out[i.filename] = i.CRC
                if i.filename.endswith(".jar"):
                    try:
                        with zipfile.ZipFile(io.BytesIO(z.read(i))) as nested:
                            h = hashlib.sha256()
                            for n in sorted(nested.infolist(), key=lambda e: e.filename):
                                if not n.is_dir() and not VOLATILE_ENTRY.search(n.filename):
                                    h.update(f"{n.filename}\0{n.CRC}\n".encode())
                            out[i.filename] = h.hexdigest()
                    except zipfile.BadZipFile:
                        pass
            return out
    except zipfile.BadZipFile:
        return None


def jar_classes(path):
    try:
        with zipfile.ZipFile(path) as z:
            return [n[:-6].replace("/", ".") for n in z.namelist()
                    if n.endswith(".class") and not n.startswith("META-INF/")
                    and n != "module-info.class"]
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError):
        return []


def classpath_view(cp_file, dist_root):
    """{class: first jar providing it (path relative to the dist)}"""
    first = {}
    with open(cp_file, encoding="utf-8") as f:
        entries = [e for e in f.read().strip().split(":") if e]
    for e in entries:
        if not e.endswith(ARCHIVE) or not os.path.isfile(e):
            continue
        rel = os.path.relpath(e, dist_root)
        for c in jar_classes(e):
            first.setdefault(c, rel)
    return first


def read_deps(path):
    with open(path, encoding="utf-8") as f:
        return {line.rstrip("\n") for line in f if line.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    args = ap.parse_args()

    allow = Allowlist(args.expected)
    diffs = []

    def record(kind, subject, detail=None, severity="runtime"):
        rule = allow.match(kind, subject)
        diffs.append({
            "kind": kind, "subject": subject, "detail": detail, "severity": severity,
            "status": "EXPECTED" if rule else "UNEXPECTED",
            "reason": rule["reason"] if rule else None,
            "rule_line": rule["line"] if rule else None,
        })

    def side(path):
        with open(os.path.join(path, "build", "dist-path.txt"), encoding="utf-8") as f:
            return f.read().strip()

    b_dist, c_dist = side(args.baseline), side(args.candidate)

    # 1. Files in the distribution, and the contents of those on both sides.
    bf, cf = dist_files(b_dist), dist_files(c_dist)
    for rel in sorted(bf.keys() - cf.keys()):
        record("dist-file-removed", rel)
    for rel in sorted(cf.keys() - bf.keys()):
        record("dist-file-added", rel)
    identical_jars = 0
    compared_files = 0
    for rel in sorted(bf.keys() & cf.keys()):
        compared_files += 1
        b, c = bf[rel], cf[rel]
        if os.path.getsize(b) == os.path.getsize(c) and file_digest(b) == file_digest(c):
            if rel.endswith(ARCHIVE):
                identical_jars += 1
            continue
        if rel.endswith(ARCHIVE):
            be, ce = jar_entries(b), jar_entries(c)
            if be is not None and ce is not None:
                for e in sorted(be.keys() - ce.keys()):
                    record("jar-entry-removed", f"{rel}!{e}")
                for e in sorted(ce.keys() - be.keys()):
                    record("jar-entry-added", f"{rel}!{e}")
                for e in sorted(be.keys() & ce.keys()):
                    if be[e] != ce[e]:
                        record("jar-entry-changed", f"{rel}!{e}")
                if be == ce:
                    identical_jars += 1   # only build metadata differs
                continue
        record("dist-file-changed", rel)

    # 2. Classes visible to each launcher command, and where they load from.
    cp_dir_b = os.path.join(args.baseline, "classpath")
    cp_dir_c = os.path.join(args.candidate, "classpath")
    class_counts = {}
    for name in sorted(os.listdir(cp_dir_b)):
        if not name.endswith(".txt") or not os.path.exists(os.path.join(cp_dir_c, name)):
            continue
        cmd = name[:-4]
        bv = classpath_view(os.path.join(cp_dir_b, name), b_dist)
        cv = classpath_view(os.path.join(cp_dir_c, name), c_dist)
        class_counts[cmd] = {"baseline": len(bv), "candidate": len(cv)}
        for c in sorted(bv.keys() - cv.keys()):
            record("class-removed", f"{cmd}:{c}", bv[c])
        for c in sorted(cv.keys() - bv.keys()):
            record("class-added", f"{cmd}:{c}", cv[c])
        for c in sorted(bv.keys() & cv.keys()):
            if bv[c] != cv[c]:
                record("class-source-changed", f"{cmd}:{c}", f"{bv[c]} -> {cv[c]}")

    # 3. Resolved dependencies of every module.
    bd = read_deps(os.path.join(args.baseline, "build", "dependencies.tsv"))
    cd = read_deps(os.path.join(args.candidate, "build", "dependencies.tsv"))
    for kind, rows in (("dep-removed", bd - cd), ("dep-added", cd - bd)):
        for row in sorted(rows):
            module, coord = row.split("\t")
            sev = "test" if coord.endswith(":test") else "runtime"
            record(kind, f"{module}|{coord}", severity=sev)

    unexpected = [d for d in diffs if d["status"] == "UNEXPECTED"]
    summary = {
        "baseline_dist": b_dist, "candidate_dist": c_dist,
        "dist_files_compared": compared_files,
        "jars_identical_apart_from_build_metadata": identical_jars,
        "classes_visible": class_counts,
        "modules_compared": len({r.split("\t")[0] for r in bd | cd}),
        "differences": len(diffs), "unexpected": len(unexpected),
        "unused_rules": [f"line {r['line']}: {r['kind']} {r['pattern']}"
                         for r in allow.rules if r["hits"] == 0],
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "artifact-diff.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "differences": diffs}, f, indent=1)
    write_markdown(os.path.join(args.out, "artifact-diff.md"), summary, diffs)
    print(f"artifact diff: {len(diffs)} differences, {len(unexpected)} unexpected")
    return 1 if unexpected else 0


def write_markdown(path, summary, diffs):
    by_kind = collections.defaultdict(list)
    for d in diffs:
        by_kind[(d["status"], d["kind"])].append(d)
    with open(path, "w", encoding="utf-8") as f:
        f.write("## Artifacts and dependencies\n\n")
        f.write(f"- Distribution files compared: {summary['dist_files_compared']}\n")
        f.write(f"- Jars identical apart from build metadata: "
                f"{summary['jars_identical_apart_from_build_metadata']}\n")
        f.write(f"- Modules whose dependencies were compared: {summary['modules_compared']}\n")
        for cmd, n in summary["classes_visible"].items():
            f.write(f"- Classes on the `{cmd}` classpath: baseline {n['baseline']}, "
                    f"candidate {n['candidate']}\n")
        f.write(f"- Differences: {summary['differences']}, "
                f"**unexpected: {summary['unexpected']}**\n\n")
        if summary["unused_rules"]:
            f.write("Allowlist rules that matched nothing (expected change did not "
                    "happen; check why):\n\n")
            for r in summary["unused_rules"]:
                f.write(f"- `{r}`\n")
            f.write("\n")
        for status in ("UNEXPECTED", "EXPECTED"):
            kinds = sorted(k for s, k in by_kind if s == status)
            if not kinds:
                continue
            f.write(f"### {status.title()} differences\n\n")
            for kind in kinds:
                items = by_kind[(status, kind)]
                f.write(f"<details><summary>{kind}: {len(items)}</summary>\n\n")
                f.write("| Subject | Detail | Severity | Reason |\n|---|---|---|---|\n")
                for d in items[:2000]:
                    f.write(f"| `{d['subject']}` | {d['detail'] or ''} | {d['severity']} "
                            f"| {d['reason'] or ''} |\n")
                if len(items) > 2000:
                    f.write(f"| ... {len(items) - 2000} more in artifact-diff.json | | | |\n")
                f.write("\n</details>\n\n")


if __name__ == "__main__":
    sys.exit(main())
