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
"""Lazy symbol table over Java sources, with constant folding.

``TestConfigurationFieldsBase`` reads field values with ``Field#get``, i.e. the
*resolved* runtime value.  Reproducing that lexically means resolving names
across files and scopes:

    DFSConfigKeys.DFS_CLIENT_READ_SHORTCIRCUIT_KEY
        -> HdfsClientConfigKeys.Read.ShortCircuit.KEY
        -> PREFIX.substring(0, PREFIX.length() - 1)
        -> HdfsClientConfigKeys.PREFIX + "read." + "shortcircuit." trimmed
        -> "dfs.client.read.shortcircuit"

Classes are parsed on demand: an unknown ``Foo.BAR`` triggers a lookup of
``Foo.java`` through a filename index.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .javamodel import FieldDecl, JavaFile, TypeDecl, parse_file
from .jexpr import BUILTIN_CONSTANTS, TimeUnitValue, Unresolvable, evaluate, java_str

__all__ = ["FileIndex", "SymbolTable", "UNRESOLVED", "java_str"]

#: Sentinel for "this constant could not be folded".  Never conflated with
#: ``None``, which is the legitimate value of a ``null`` initialiser.
UNRESOLVED = object()

_SKIP_DIRS = {"target", ".git", "node_modules", "build"}
_WS_RE = re.compile(r"\s+")


class FileIndex:
    """Maps a Java simple type name to candidate source files."""

    def __init__(self, roots: Iterable[str]):
        self.by_simple: Dict[str, List[str]] = {}
        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for name in filenames:
                    if name.endswith(".java"):
                        self.by_simple.setdefault(name[:-5], []).append(
                            os.path.join(dirpath, name))

    def find(self, simple_name: str) -> List[str]:
        return self.by_simple.get(simple_name, [])


class SymbolTable:
    def __init__(self, index: FileIndex):
        self.index = index
        self.files: Dict[str, JavaFile] = {}
        self.types: Dict[str, TypeDecl] = {}
        self.by_simple: Dict[str, List[TypeDecl]] = {}
        self._file_of_type: Dict[str, JavaFile] = {}
        self._memo: Dict[Tuple[str, str], Any] = {}
        self._in_progress: Set[Tuple[str, str]] = set()

    # ---------------------------------------------------------------- loading

    def load_path(self, path: str) -> Optional[JavaFile]:
        path = os.path.abspath(path)
        if path in self.files:
            return self.files[path]
        try:
            jfile = parse_file(path)
        except (OSError, UnicodeDecodeError):
            return None
        self.files[path] = jfile
        for qname, decl in jfile.types.items():
            self.types.setdefault(qname, decl)
            self.by_simple.setdefault(decl.name, []).append(decl)
            self._file_of_type.setdefault(qname, jfile)
        return jfile

    def load_class(self, qname: str) -> Optional[TypeDecl]:
        if qname in self.types:
            return self.types[qname]
        for segment in qname.split("."):
            if segment[:1].isupper():
                for path in self.index.find(segment):
                    self.load_path(path)
                if qname in self.types:
                    return self.types[qname]
        return self.types.get(qname)

    # ------------------------------------------------------------- resolution

    def _file_for(self, decl: TypeDecl) -> Optional[JavaFile]:
        node = decl
        while node.parent is not None:
            node = node.parent
        return self._file_of_type.get(node.qname)

    def resolve_type(self, ref: str, scope: Optional[TypeDecl]) -> Optional[TypeDecl]:
        ref = _WS_RE.sub("", ref)
        if ref in self.types:
            return self.types[ref]

        candidates: List[str] = []
        if scope is not None:
            node: Optional[TypeDecl] = scope
            while node is not None:
                candidates.append(node.qname + "." + ref)
                node = node.parent
            jfile = self._file_for(scope)
            if jfile is not None:
                if jfile.package:
                    candidates.append(jfile.package + "." + ref)
                head = ref.split(".")[0]
                tail = ref[len(head):]
                for imp in jfile.imports:
                    if imp.endswith("." + head):
                        candidates.append(imp + tail)
                    elif imp.endswith(".*"):
                        candidates.append(imp[:-1] + ref)

        for candidate in candidates:
            if candidate in self.types:
                return self.types[candidate]
        for candidate in candidates:
            found = self.load_class(candidate)
            if found is not None:
                return found

        # Last resort: a uniquely named type anywhere in the indexed roots.
        head = ref.split(".")[0]
        tail = ref[len(head) + 1:] if "." in ref else ""
        decls = self.by_simple.get(head) or []
        if not decls:
            for path in self.index.find(head):
                self.load_path(path)
            decls = self.by_simple.get(head) or []
        for decl in decls:
            target = decl.qname + ("." + tail if tail else "")
            if target in self.types:
                return self.types[target]
        return None

    def _field_in_hierarchy(self, name: str, decl: TypeDecl,
                            seen: Optional[Set[str]] = None) -> Optional[FieldDecl]:
        seen = seen if seen is not None else set()
        if decl.qname in seen:
            return None
        seen.add(decl.qname)
        if name in decl.fields:
            return decl.fields[name]
        for super_ref in decl.supertypes:
            super_decl = self.resolve_type(super_ref, decl)
            if super_decl is not None:
                found = self._field_in_hierarchy(name, super_decl, seen)
                if found is not None:
                    return found
        return None

    def resolve_field(self, ref: str, scope: Optional[TypeDecl]) -> Optional[FieldDecl]:
        parts = _WS_RE.sub("", ref).split(".")
        if len(parts) == 1:
            node = scope
            while node is not None:
                found = self._field_in_hierarchy(parts[0], node)
                if found is not None:
                    return found
                node = node.parent
            return self._static_import_field(parts[0], scope)

        owner = self.resolve_type(".".join(parts[:-1]), scope)
        if owner is None:
            return None
        return self._field_in_hierarchy(parts[-1], owner)

    def _static_import_field(self, name: str,
                             scope: Optional[TypeDecl]) -> Optional[FieldDecl]:
        """Resolve a bare constant name brought in by ``import static``.

        HDFS routinely refers to key constants this way, e.g. NameNodeUtils
        builds ``DFS_HA_NAMENODES_KEY_PREFIX + "." + nsId`` with no qualifier.
        """
        if scope is None:
            return None
        jfile = self._file_for(scope)
        if jfile is None:
            return None
        for imported in jfile.static_imports:
            if imported.endswith(".*"):
                owner_ref = imported[:-2]
            elif imported.endswith("." + name):
                owner_ref = imported[:-(len(name) + 1)]
            else:
                continue
            owner = self.resolve_type(owner_ref, scope) or self.load_class(owner_ref)
            if owner is None:
                continue
            found = self._field_in_hierarchy(name, owner)
            if found is not None:
                return found
        return None

    # ------------------------------------------------------------- evaluation

    def value_of_field(self, decl: FieldDecl) -> Any:
        key = (decl.owner_qname, decl.name)
        if key in self._memo:
            return self._memo[key]
        if key in self._in_progress:
            return UNRESOLVED
        if decl.init_expr is None:
            self._memo[key] = UNRESOLVED
            return UNRESOLVED
        self._in_progress.add(key)
        try:
            value = self.eval_expr(decl.init_expr, self.types.get(decl.owner_qname))
        finally:
            self._in_progress.discard(key)
        self._memo[key] = value
        return value

    def eval_expr(self, expr: Optional[str], scope: Optional[TypeDecl]) -> Any:
        if expr is None:
            return UNRESOLVED

        def resolve_name(parts: List[str]) -> Any:
            joined = ".".join(parts)
            if joined in BUILTIN_CONSTANTS:
                return BUILTIN_CONSTANTS[joined]
            if len(parts) == 2 and parts[0] == "TimeUnit":
                return TimeUnitValue(parts[1])
            decl = self.resolve_field(joined, scope)
            if decl is None:
                raise Unresolvable()
            value = self.value_of_field(decl)
            if value is UNRESOLVED:
                raise Unresolvable()
            return value

        try:
            return evaluate(expr, resolve_name)
        except Unresolvable:
            return UNRESOLVED
        except RecursionError:
            return UNRESOLVED
