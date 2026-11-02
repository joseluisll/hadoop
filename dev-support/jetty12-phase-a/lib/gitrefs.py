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

"""What ancestry.py and compare_plan.py read from git.

Ignored paths are relative to the repository root, so the two checks mean the
same run from the harness directory or the root. Either module is run with
'python3 -I', which does not add this directory to the path.
"""

import subprocess


def git(*args, binary=False):
    """git's output, or None when git fails."""
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout if binary else r.stdout.decode("utf-8", "surrogateescape")


def rev_parse(rev):
    out = git("rev-parse", "--verify", "--quiet", rev + "^{commit}")
    return out.strip() if out else None


def tree_blobs(rev):
    """{path: blob id} of a commit's tree."""
    blobs = {}
    for entry in (git("ls-tree", "-r", "-z", "--full-tree", rev, binary=True) or b"").split(b"\0"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            blobs[path.decode("utf-8", "surrogateescape")] = meta.split()[2].decode()
    return blobs


def changed_blobs(commit, ignored):
    """{path: blob id} a commit leaves in place of its first parent's, without
    the ignored paths. One diff-tree call instead of walking both trees; a
    merge commit counts against its first parent, as a rebase would replay it."""
    args = ["git", "diff-tree", "-r", "-z", "--no-commit-id", "--no-renames", "--root",
            "--diff-merges=first-parent", commit, "--", ":(top)"]
    args += [f":(top,exclude){g}" for g in ignored]
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        return None
    entries = [e for e in r.stdout.split(b"\0") if e]
    out = {}
    for meta, path in zip(entries[0::2], entries[1::2]):
        blob = meta.split()[3].decode()
        # A deleted path has no blob to look for in the candidate's tree.
        out[path.decode("utf-8", "surrogateescape")] = blob if blob.strip("0") else None
    return out


def changed_paths(rev_from, rev_to, ignored):
    """Paths changed between two commits, without the ignored ones."""
    out = git("diff", "--name-only", "--no-renames", rev_from, rev_to,
              "--", ":(top)", *[f":(top,exclude){g}" for g in ignored])
    return set((out or "").split())


def patch_ids(diff):
    """{patch id: commit} of a 'git log -p' or 'git diff' text; a diff with no
    commit line is keyed to None. --stable ignores line numbers and
    whitespace, so a change merged onto a later trunk keeps its id."""
    r = subprocess.run(["git", "patch-id", "--stable"], input=diff or b"",
                       capture_output=True)
    out = {}
    for line in r.stdout.decode().splitlines():
        pid, commit = line.split()
        out[pid] = None if commit.strip("0") == "" else commit
    return out
