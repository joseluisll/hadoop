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
"""E7 - property mentions in the site guides.

These are mentions, not declarations, so they never add keys to the inventory.
They sharpen the recommendation: a property explained in a user-facing guide
but missing from `*-default.xml` is one an administrator is actively told to
set yet cannot discover from the defaults file - the strongest possible case
for documenting it.  The reverse is also useful, since a key nobody documents
anywhere is more likely to be internal.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List

from .semantics import is_partial_property, is_valid_property_name

KEY_PREFIXES = ("dfs.", "nfs.", "httpfs.", "hadoop.")

# Property names in Markdown appear inside backticks, in table cells, or bare.
_CANDIDATE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_%-]+)+")
_SKIP_DIRS = {"target", ".git"}


@dataclass
class DocMention:
    key: str
    path: str
    line: int


@dataclass
class DocsExtract:
    mentions: Dict[str, List[DocMention]] = field(default_factory=dict)

    def keys(self):
        return set(self.mentions)

    def count(self, key: str) -> int:
        return len(self.mentions.get(key, []))

    def first(self, key: str):
        found = self.mentions.get(key)
        return found[0] if found else None


def extract(repo: str, roots: List[str]) -> DocsExtract:
    result = DocsExtract()
    for relative in roots:
        root = os.path.join(repo, *relative.split("/"))
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                if not name.endswith((".md", ".md.vm")):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        text = handle.read()
                except OSError:
                    continue
                for match in _CANDIDATE_RE.finditer(text):
                    key = match.group().strip("`")
                    if not key.startswith(KEY_PREFIXES):
                        continue
                    if is_partial_property(key) or not is_valid_property_name(key):
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    result.mentions.setdefault(key, []).append(
                        DocMention(key=key, path=path, line=line))
    return result
