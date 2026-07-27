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
"""E4 - deprecated property names.

Two machine-readable registries exist and both are mined here:

* ``DeprecationDelta`` tables (``HdfsConfiguration``, ``NfsConfiguration``),
  which map an old key onto its replacement(s).  A key found only in the
  literal scan is very often just an old alias listed here rather than an
  undocumented property.
* ``@Deprecated`` constants in the ConfigKeys classes - DFSConfigKeys alone
  carries 131 of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .symbols import UNRESOLVED, SymbolTable

_DELTA_RE = re.compile(r"new\s+DeprecationDelta\s*\(")


@dataclass
class DeprecationRecord:
    old_key: str
    new_keys: List[str]
    path: str
    line: int
    kind: str = "DeprecationDelta"
    constant: Optional[str] = None


@dataclass
class DeprecationExtract:
    records: List[DeprecationRecord] = field(default_factory=list)
    unresolved: List[Dict[str, object]] = field(default_factory=list)

    def old_keys(self):
        return {r.old_key for r in self.records if r.kind == "DeprecationDelta"}

    def replacement_of(self) -> Dict[str, List[str]]:
        return {r.old_key: r.new_keys for r in self.records if r.kind == "DeprecationDelta"}

    def deprecated_constants(self) -> Dict[str, DeprecationRecord]:
        return {r.old_key: r for r in self.records if r.kind == "@Deprecated"}


def _balanced_span(struct: str, open_paren: int) -> Optional[int]:
    depth = 0
    for index in range(open_paren, len(struct)):
        char = struct[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_args(struct: str, code: str, start: int, end: int) -> List[str]:
    args: List[str] = []
    depth = 0
    piece_start = start
    for index in range(start, end):
        char = struct[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(code[piece_start:index])
            piece_start = index + 1
    args.append(code[piece_start:end])
    return [a.strip() for a in args if a.strip()]


def extract_deltas(symtab: SymbolTable, path: str) -> DeprecationExtract:
    """Parse a ``DeprecationDelta`` registry such as HdfsConfiguration."""
    result = DeprecationExtract()
    jfile = symtab.load_path(path)
    if jfile is None:
        return result

    struct = jfile.lexed.struct
    code = jfile.lexed.code
    scope = next((d for d in jfile.types.values() if d.parent is None), None)

    for match in _DELTA_RE.finditer(struct):
        open_paren = struct.index("(", match.end() - 1)
        close_paren = _balanced_span(struct, open_paren)
        if close_paren is None:
            continue
        args = _split_args(struct, code, open_paren + 1, close_paren)
        if not args:
            continue
        line = jfile.lexed.line_of(match.start())

        values = []
        failed = False
        for arg in args:
            value = symtab.eval_expr(arg, scope)
            if value is UNRESOLVED or not isinstance(value, str):
                failed = True
                break
            values.append(value)
        if failed or not values:
            result.unresolved.append(
                {"expr": " ".join(" ".join(args).split()), "line": line, "path": path})
            continue

        result.records.append(DeprecationRecord(
            old_key=values[0], new_keys=values[1:], path=path, line=line))
    return result


def extract_deprecated_constants(symtab: SymbolTable,
                                 class_qnames: List[str]) -> DeprecationExtract:
    """Collect ``@Deprecated`` String constants from ConfigKeys classes."""
    result = DeprecationExtract()
    for qname in class_qnames:
        decl = symtab.load_class(qname)
        if decl is None:
            continue
        for fdecl in decl.fields.values():
            if not (fdecl.deprecated and fdecl.public_static_final):
                continue
            if fdecl.java_type != "String":
                continue
            value = symtab.value_of_field(fdecl)
            if value is UNRESOLVED or not isinstance(value, str):
                continue
            result.records.append(DeprecationRecord(
                old_key=value, new_keys=[], path=fdecl.source_path, line=fdecl.line,
                kind="@Deprecated", constant=fdecl.name))
    return result


def extract(symtab: SymbolTable, delta_paths: List[str],
            class_qnames: List[str]) -> DeprecationExtract:
    combined = DeprecationExtract()
    for path in delta_paths:
        part = extract_deltas(symtab, path)
        combined.records.extend(part.records)
        combined.unresolved.extend(part.unresolved)
    annotated = extract_deprecated_constants(symtab, class_qnames)
    combined.records.extend(annotated.records)
    return combined
