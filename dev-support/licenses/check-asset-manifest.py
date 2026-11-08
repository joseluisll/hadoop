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
"""Per-push source-tree licence gates (requirements 7 stage B, 48, 53).

1. R7 stage B: every path-style entry in manifest-assets.txt must resolve
   to at least one file or directory in the SOURCE TREE.
2. R48: every path the source-release LICENSE.txt names (its bundled
   third-party section, including "For <path>:" text headers) must resolve
   in the source tree, and every path-style entry of manifest-assets.txt
   must be covered by LICENSE.txt — what ships in the binary is also in the
   source release.
3. R53 (licenses-binary part of R10): every text in licenses-binary/ must
   belong to a component LICENSE-binary still lists. LICENSE-<slug>.txt is
   tied to LICENSE-binary by its slug (case-insensitive, whole word) or by the
   token recorded for it in licenses-binary-aliases; a text with no listed
   component, or an alias row with no text, fails. Stale texts otherwise
   ship in the tarball for components that are gone.

The checks below describe gate 1; gates 2 and 3 reuse its path resolution.

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

A node_modules entry names a directory npm creates at build time; it
resolves when the package.json next to it exists.

Usage: check-asset-manifest.py [repo-root] [manifest-assets.txt]
Defaults: repo root two levels up from this script; manifest next to this
script. Exit 0 when every gate passes; exit 1 listing every failure (fail
closed: a missing LICENSE.txt, LICENSE-binary, licenses-binary/ or aliases
file is a failure too).
"""

import fnmatch
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(SCRIPT_DIR, "manifest-assets.txt")
ALIASES = os.path.join(SCRIPT_DIR, "licenses-binary-aliases")

# a LICENSE.txt line naming a bundled path: "hadoop-x/..." or "For hadoop-x/...:"
LICENSE_TXT_PATH = re.compile(r"^(?:For )?(hadoop-[\w.-]+/\S+?):?$")

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


def strip_note(entry):
    """Drop a trailing parenthetical note from a path-style entry."""
    note = re.search(r"\s+\([^()]*\)\s*$", entry)
    return entry[: note.start()] if note else entry


def match_count(entry, repo_root):
    """Number of source-tree files/dirs the path-style entry resolves to."""
    total = 0
    for pattern in expand_braces(strip_note(entry)):
        full = os.path.join(repo_root, pattern)
        if os.path.exists(full):  # bare file or directory
            total += 1
            continue
        if os.path.basename(full) == "node_modules":
            # created by npm at build time: its package.json must exist
            if os.path.isfile(os.path.join(os.path.dirname(full), "package.json")):
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


def license_txt_paths(license_txt):
    """(lineno, path) for every bundled path LICENSE.txt names."""
    if not os.path.isfile(license_txt):
        sys.exit(f"FAIL: cannot read {license_txt}")
    with open(license_txt, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next(
        (i for i, l in enumerate(lines) if l.startswith("This product bundles")),
        None,
    )
    if start is None:
        sys.exit(f"FAIL: no bundled third-party section in {license_txt}")
    out = []
    for i in range(start, len(lines)):
        m = LICENSE_TXT_PATH.match(lines[i].strip())
        if m:
            out.append((i + 1, m.group(1)))
    if not out:
        sys.exit(f"FAIL: no bundled paths parsed from {license_txt}")
    return out


def covered(path, license_paths):
    """True when LICENSE.txt names the path or a directory above it."""
    return any(path == lp or path.startswith(lp.rstrip("/") + "/")
               for lp in license_paths)


def check_license_txt(repo_root, manifest_paths):
    """R48: LICENSE.txt paths resolve; manifest paths are covered by it."""
    failures = []
    license_txt = os.path.join(repo_root, "LICENSE.txt")
    entries = license_txt_paths(license_txt)
    expanded = set()
    for lineno, path in entries:
        if match_count(path, repo_root) == 0:
            failures.append(f"LICENSE.txt:{lineno} names a path that does "
                            f"not exist: {path}")
        expanded.update(expand_braces(path))
    for section, entry in manifest_paths:
        for path in expand_braces(strip_note(entry.strip())):
            if not covered(path, expanded):
                failures.append(f"[{section}] {path} ships in the binary "
                                "(manifest-assets.txt) but LICENSE.txt does "
                                "not list it")
    print(f"LICENSE.txt: {len(entries)} bundled paths checked, "
          f"{len(manifest_paths)} manifest paths checked for coverage")
    return failures


def check_licenses_binary(repo_root, aliases_path):
    """R53: every licenses-binary/ text belongs to a listed component."""
    failures = []
    manifest_file = os.path.join(repo_root, "LICENSE-binary")
    texts_dir = os.path.join(repo_root, "licenses-binary")
    if not os.path.isfile(manifest_file):
        sys.exit(f"FAIL: cannot read {manifest_file}")
    if not os.path.isdir(texts_dir):
        sys.exit(f"FAIL: no licenses-binary/ directory in {repo_root}")
    if not os.path.isfile(aliases_path):
        sys.exit(f"FAIL: cannot read {aliases_path}")
    with open(manifest_file, encoding="utf-8") as fh:
        manifest = fh.read().lower()
    aliases = {}
    with open(aliases_path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "\t" not in line:
                sys.exit(f"FAIL: malformed line {lineno} in {aliases_path} "
                         f"(expected slug<TAB>token): {line!r}")
            slug, token = line.split("\t", 1)
            if slug in aliases:
                sys.exit(f"FAIL: duplicate slug {slug!r} in {aliases_path}")
            aliases[slug] = token.strip()
    slugs = sorted(
        name[len("LICENSE-"):-len(".txt")]
        for name in os.listdir(texts_dir)
        if name.startswith("LICENSE-") and name.endswith(".txt")
    )
    if not slugs:
        sys.exit(f"FAIL: no LICENSE-*.txt texts in {texts_dir}")
    for slug in slugs:
        token = aliases.get(slug, slug)
        # whole-word: a short slug (go, asm, tree) must not match inside
        # another word of the licence prose ("goodwill")
        word = r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])"
        if not re.search(word, manifest):
            failures.append(
                f"licenses-binary/LICENSE-{slug}.txt: no component in "
                f"LICENSE-binary matches {token!r} — delete the stale text, "
                "or record the listed component's name in "
                "licenses-binary-aliases")
    for slug in sorted(set(aliases) - set(slugs)):
        failures.append(f"licenses-binary-aliases: {slug!r} has no "
                        f"licenses-binary/LICENSE-{slug}.txt — drop the row")
    print(f"licenses-binary: {len(slugs)} texts checked against LICENSE-binary "
          f"({len(aliases)} by alias)")
    return failures


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
    failed = False

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
        failed = True
    else:
        print("asset manifest gate passed: every path-style entry resolves")

    for name, problems in (
        ("LICENSE.txt gate (R48)", check_license_txt(repo_root, path_entries)),
        ("licenses-binary gate (R53)", check_licenses_binary(repo_root, ALIASES)),
    ):
        if problems:
            print(f"FAIL: {name}: {len(problems)} problem(s):", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            failed = True
        else:
            print(f"{name} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
