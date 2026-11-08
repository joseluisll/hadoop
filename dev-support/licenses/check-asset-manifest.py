#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to you under the Apache License, Version 2.0
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
"""R7 stage B gate: every path-style entry in manifest-assets.txt must
resolve to at least one file or directory in the SOURCE TREE.

The curated non-jar asset manifest (manifest-assets.txt, "section<TAB>line")
feeds the R40 generator; a stale path in it silently puts a listed-yet-absent
entry into LICENSE-binary (and hides assets that shipped in its place — the
d3-3.5.17 -> d3-v4.1.1 class). This gate fails closed on any entry that no
longer resolves, so the curation cannot rot.

Entry kinds:
- path-style: contains a filesystem path (relative to the repo root).
  Braces expand ({a,b} and {a|b} both mean alternation), trailing globs
  (*, dir/*) glob, a trailing parenthetical note is stripped. An entry
  matches if ANY expanded form resolves to an existing file or directory.
- package-style: "name vX.Y" / "name X.Y" npm-style lines (e.g.
  "leveldb v1.13", "atlaskit/... 1.7.4") have no source-tree path; they
  are skipped here and validated by the archive-side asset gate instead.

Usage: check-asset-manifest.py [repo-root] [manifest-assets.txt]
Defaults: repo root = CWD if it looks like one, else two levels up from
this script; manifest next to this script. Exit 0 when every path-style
entry resolves; exit 1 listing the zero-match entries (fail closed).
"""

import fnmatch
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(SCRIPT_DIR, "manifest-assets.txt")

# "name 1.2.3" / "name v1.2.3" (optionally scoped "org/name 1.2.3") —
# a package coordinates line, not a filesystem path.
PACKAGE_STYLE = re.compile(r"^\S+( \S+)? v?[0-9][\w.:-]*$")


def expand_braces(pattern):
    """Expand the outermost {a,b} / {a|b} group into separate patterns."""
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    depth = 0
    for i in range(start, len(pattern)):
        if pattern[i] == "{":
            depth += 1
        elif pattern[i] == "}":
            depth -= 1
            if depth == 0:
                inner = pattern[start + 1 : i]
                prefix, suffix = pattern[:start], pattern[i + 1 :]
                out = []
                for alt in re.split(r"[,|]", inner):
                    if alt == "":
                        continue
                    out.extend(expand_braces(prefix + alt + suffix))
                return out or [pattern]
    # unbalanced brace: treat literally
    return [pattern]


def parse_entries(manifest_path):
    """Yield (section, raw_line) for every non-comment entry."""
    if not os.path.isfile(manifest_path) or os.path.getsize(manifest_path) == 0:
        sys.exit(f"FAIL: cannot read curated asset manifest ({manifest_path})")
    with open(manifest_path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                sys.exit(
                    f"FAIL: malformed line {lineno} in {manifest_path} "
                    f"(expected section<TAB>line): {line!r}"
                )
            section, entry = line.split("\t", 1)
            yield section, entry


def match_count(entry, repo_root):
    """Number of source-tree files/dirs the path-style entry resolves to."""
    note = re.search(r"\s+\([^()]*\)\s*$", entry)
    if note:
        entry = entry[: note.start()]
    total = 0
    for pattern in expand_braces(entry):
        full = os.path.join(repo_root, pattern)
        if os.path.exists(full):  # bare file or directory
            total += 1
            continue
        if any(ch in pattern for ch in "*?["):
            # glob is rooted: /abs/dir/*.js must still match files under it
            base, tail = os.path.split(full)
            if os.path.isdir(base):
                total += sum(
                    1 for name in os.listdir(base) if fnmatch.fnmatch(name, tail)
                )
    return total


def main():
    args = sys.argv[1:]
    manifest = DEFAULT_MANIFEST
    repo_root = None
    for arg in args:
        if arg.endswith("manifest-assets.txt"):
            manifest = arg
        elif repo_root is None:
            repo_root = arg
    if repo_root is None:
        repo_root = os.path.abspath(
            os.path.join(SCRIPT_DIR, os.pardir, os.pardir)
        )
    if not os.path.isdir(repo_root):
        sys.exit(f"FAIL: repo root does not exist: {repo_root}")

    path_entries = []
    package_entries = 0
    for section, entry in parse_entries(manifest):
        if PACKAGE_STYLE.match(entry.strip()):
            package_entries += 1
        else:
            path_entries.append((section, entry))

    if not path_entries and package_entries == 0:
        sys.exit(f"FAIL: no entries parsed from {manifest}")

    unresolved = []
    for section, entry in path_entries:
        n = match_count(entry.strip(), repo_root)
        if n == 0:
            unresolved.append((section, entry))

    print(
        f"asset manifest: {len(path_entries)} path-style entries checked, "
        f"{package_entries} package-style entries skipped "
        "(package-style entries are validated by the archive asset gate)"
    )
    if unresolved:
        print(
            f"FAIL: {len(unresolved)} curated asset entries resolve to "
            f"nothing in the source tree ({repo_root}) — prune or fix them "
            "(a stale entry hides the asset that shipped in its place):",
            file=sys.stderr,
        )
        for section, entry in unresolved:
            print(f"  [{section}] {entry}", file=sys.stderr)
        sys.exit(1)
    print("asset manifest gate passed: every path-style entry resolves")


if __name__ == "__main__":
    main()
