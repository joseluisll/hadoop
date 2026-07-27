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
"""E5 - skip lists declared by the Test*ConfigFields subclasses.

Each entry records why a property is exempt from comparison, taken from the
comment above it.  That comment is the only place where the project's
accumulated judgement about these properties is written down, and some of it is
openly uncertain (``// Fully deprecated properties?``), which makes these
entries review candidates rather than settled facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .javamodel import parse_file
from .symbols import UNRESOLVED, SymbolTable

TARGETS = (
    "configurationPropsToSkipCompare",
    "configurationPrefixToSkipCompare",
    "xmlPropsToSkipCompare",
    "xmlPrefixToSkipCompare",
)

_SKIP_RE = re.compile(
    r"(?P<target>" + "|".join(TARGETS) + r")\s*\.\s*add\s*\(\s*(?P<arg>.*?)\s*\)\s*;",
    re.DOTALL,
)

_CLASSES_RE = re.compile(
    r"configurationClasses\s*=\s*new\s+Class\s*\[\s*\]\s*\{(?P<body>.*?)\}\s*;", re.DOTALL)
_CLASS_LITERAL_RE = re.compile(r"([A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*)\s*\.\s*class")


@dataclass
class SkipEntry:
    target: str
    value: str
    expr: str
    line: int
    reason: str


@dataclass
class SkipLists:
    path: str
    entries: List[SkipEntry] = field(default_factory=list)
    unresolved: List[Dict[str, object]] = field(default_factory=list)

    def _values(self, target: str) -> Set[str]:
        return {e.value for e in self.entries if e.target == target}

    @property
    def config_props(self) -> Set[str]:
        return self._values("configurationPropsToSkipCompare")

    @property
    def config_prefixes(self) -> Set[str]:
        return self._values("configurationPrefixToSkipCompare")

    @property
    def xml_props(self) -> Set[str]:
        return self._values("xmlPropsToSkipCompare")

    @property
    def xml_prefixes(self) -> Set[str]:
        return self._values("xmlPrefixToSkipCompare")

    def reason_for(self, value: str) -> str:
        for entry in self.entries:
            if entry.value == value and entry.reason:
                return entry.reason
        return ""


def extract(symtab: SymbolTable, test_path: str) -> SkipLists:
    jfile = symtab.load_path(test_path) or parse_file(test_path)
    scope = None
    for decl in jfile.types.values():
        if decl.parent is None:
            scope = decl
            break

    comments = sorted(jfile.lexed.comments, key=lambda c: c.start_line)
    result = SkipLists(path=test_path)

    for match in _SKIP_RE.finditer(jfile.lexed.code):
        line = jfile.lexed.line_of(match.start())
        expr = " ".join(match.group("arg").split())
        value = symtab.eval_expr(match.group("arg"), scope)
        if value is UNRESOLVED or not isinstance(value, str):
            result.unresolved.append({"expr": expr, "line": line, "path": test_path})
            continue
        result.entries.append(SkipEntry(
            target=match.group("target"),
            value=value,
            expr=expr,
            line=line,
            reason=_reason_above(comments, line),
        ))

    return result


def extract_config_classes(symtab: SymbolTable, test_path: str) -> List[str]:
    """The ``configurationClasses`` array the test actually compares against.

    Read from the test rather than kept in a list here, so that adding a class
    to the Java test immediately changes what the oracle checks.  A hand-copied
    list would drift, and the oracle's whole value is that it cannot.
    """
    jfile = symtab.load_path(test_path) or parse_file(test_path)
    scope = next((d for d in jfile.types.values() if d.parent is None), None)
    match = _CLASSES_RE.search(jfile.lexed.code)
    if match is None:
        return []

    qnames: List[str] = []
    for literal in _CLASS_LITERAL_RE.finditer(match.group("body")):
        ref = re.sub(r"\s+", "", literal.group(1))
        decl = symtab.resolve_type(ref, scope)
        qnames.append(decl.qname if decl is not None else ref)
    return qnames


def _reason_above(comments, line: int) -> str:
    """The comment that governs the entry at ``line``.

    A comment often heads a *group* of entries::

        // Fully deprecated properties?
        configurationPropsToSkipCompare.add("dfs.corruptfilesreturned.max");
        configurationPropsToSkipCompare.add("dfs.metrics.session-id");
        ...

    Only attaching it to the first entry loses the reason for the rest, and the
    reason is the whole point: it is where the project records *why* a property
    is exempt.  The nearest preceding comment therefore applies until another
    one replaces it, which is how a reader parses the file.
    """
    best: Optional[str] = None
    best_end = -1
    for comment in comments:
        if best_end < comment.end_line < line:
            best_end = comment.end_line
            best = comment.text
    return best or ""
