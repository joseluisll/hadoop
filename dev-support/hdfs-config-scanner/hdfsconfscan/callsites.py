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
"""Configuration accessor call sites - the shared engine behind E6 and usage.

Everything else in the scanner works *forwards*: it finds declarations and asks
whether they are documented.  This module works *backwards*: it enumerates
every place configuration is actually read or written and asks whether we can
account for the key.  That inverse direction is what turns "we scanned a lot of
places" into "no configuration access is unaccounted for".

Each site resolves to one of:

``exact``       a fully folded property name
``pattern``     a constant prefix plus a runtime-computed tail
                (``conf.get(DFS_HA_NAMENODES + "." + nsId)``)
``dynamic``     the key is entirely computed at runtime
``unresolved``  neither - a worklist entry for a human

Only ``unresolved`` is a failure.  ``dynamic`` and ``pattern`` are real
findings: they are key *families* that no forward scan of literals or constants
can enumerate.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .e2_literals import ACCESSORS, is_test_path
from .javamodel import TypeDecl
from .jexpr import TimeUnitValue, Unresolvable, java_str, tokenize
from .semantics import (
    is_default_field_name, is_partial_property, is_valid_property_name,
)
from .symbols import UNRESOLVED, SymbolTable

#: Accessors whose argument selects a *family* of properties, not one property.
_FAMILY_ACCESSORS = {"getPropsWithPrefix", "getValByRegex"}

#: Receivers that are a Configuration even though we cannot type them.
_CONF_RECEIVER_CALLS = (
    "getConf", "getConfiguration", "getServiceConfig", "getConfig",
)
_CONF_RECEIVER_NAMES = {"conf", "config", "configuration", "hdfsConf", "hdfsConfig"}

_CONF_TYPE_RE = re.compile(r"\b([A-Z]\w*Configuration|Configuration)\s+(\w+)\s*[;=,)]")
_ACCESSOR_ALTERNATION = "|".join(sorted(ACCESSORS, key=len, reverse=True))
_CALL_RE = re.compile(
    r"(?P<recv>[A-Za-z_$][\w$]*(?:\s*\(\s*\))?)\s*\.\s*"
    r"(?P<acc>" + _ACCESSOR_ALTERNATION + r")\s*\(",
)

#: Helper functions that take the Configuration as their *first* argument and
#: the property name as a later one, e.g. BlockScanner's
#: ``getUnitTestLong(conf, INTERNAL_..._MS, ..._DEFAULT)``.  Without this the
#: read is invisible and the property looks test-only.
_INDIRECT_RE = re.compile(r"\b(?P<helper>[a-z][\w$]*)\s*\(\s*(?P<conf>[A-Za-z_$][\w$]*)\s*,")

#: HttpFS composes names at runtime; see BaseService#getPrefixedName.
#: getServiceConfig() holds keys with "httpfs.<servicePrefix>." trimmed off.
_HTTPFS_SERVER_PREFIX = "httpfs"


@dataclass
class CallSite:
    path: str
    line: int
    module: str
    accessor: str
    receiver: str
    expr: str
    resolution: str
    key: Optional[str] = None
    pattern: Optional[str] = None
    inline_default: Optional[str] = None
    #: The inline default folded to its value, when it is a constant
    #: expression - what an xml <value> would have to say.
    inline_default_value: Optional[str] = None
    in_test: bool = False
    reconstructed: bool = False
    #: Set when the argument folded to a string that is not a property name -
    #: kept so the report can show what was passed instead.
    resolved_value: Optional[str] = None
    #: The constant the key came from, when it was a name rather than a
    #: literal.  Carries provenance for keys declared outside the registered
    #: ConfigKeys classes, which only this sweep can reach.
    key_field: Optional[object] = None

    @property
    def is_write(self) -> bool:
        return self.accessor.startswith(("set", "unset"))

    @property
    def is_read(self) -> bool:
        return not self.is_write


@dataclass
class CallSiteExtract:
    sites: List[CallSite] = field(default_factory=list)

    def by_key(self) -> Dict[str, List[CallSite]]:
        grouped: Dict[str, List[CallSite]] = {}
        for site in self.sites:
            if site.key:
                grouped.setdefault(site.key, []).append(site)
        return grouped

    def of_resolution(self, resolution: str) -> List[CallSite]:
        return [s for s in self.sites if s.resolution == resolution]


def _match_paren(struct: str, open_idx: int) -> Optional[int]:
    depth = 0
    for index in range(open_idx, len(struct)):
        char = struct[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _first_argument(struct: str, code: str, open_idx: int) -> Tuple[Optional[str], Optional[str]]:
    """Return (first argument text, second argument text) of a call."""
    close = _match_paren(struct, open_idx)
    if close is None:
        return None, None
    depth = 0
    split = None
    for index in range(open_idx + 1, close):
        char = struct[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            split = index
            break
    if split is None:
        return code[open_idx + 1:close].strip(), None
    second_end = close
    depth = 0
    for index in range(split + 1, close):
        char = struct[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            second_end = index
            break
    return (code[open_idx + 1:split].strip(),
            " ".join(code[split + 1:second_end].split()) or None)


def _split_top_level_plus(expr: str) -> Optional[List[str]]:
    """Split a Java expression on ``+`` operators at paren depth zero."""
    try:
        tokens = tokenize(expr)
    except Unresolvable:
        return None
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for token in tokens:
        if token.kind == "op" and token.text == "(":
            depth += 1
        elif token.kind == "op" and token.text == ")":
            depth -= 1
        if token.kind == "op" and token.text == "+" and depth == 0:
            parts.append(" ".join(current))
            current = []
            continue
        current.append(token.text)
    parts.append(" ".join(current))
    return [p.strip() for p in parts]


def type_at_offset(types: Dict[str, TypeDecl], offset: int) -> Optional[TypeDecl]:
    """Innermost type whose body contains ``offset``."""
    best: Optional[TypeDecl] = None
    for decl in types.values():
        if decl.body_start <= offset <= decl.body_end:
            if best is None or decl.body_start > best.body_start:
                best = decl
    return best


class CallSiteScanner:
    def __init__(self, symtab: SymbolTable):
        self.symtab = symtab

    # ---------------------------------------------------------------- helpers

    def _service_prefix(self, scope: Optional[TypeDecl]) -> Optional[str]:
        """The ``PREFIX`` constant of an enclosing HttpFS service class."""
        node = scope
        while node is not None:
            fdecl = node.fields.get("PREFIX")
            if fdecl is not None:
                value = self.symtab.value_of_field(fdecl)
                if value is not UNRESOLVED and isinstance(value, str):
                    return value
            node = node.parent
        return None

    def _reconstruct_httpfs(self, receiver: str, key: str,
                            scope: Optional[TypeDecl]) -> Optional[str]:
        """Rebuild the real property name behind an HttpFS service lookup.

        ``BaseService#getPrefixedName`` yields ``httpfs.<service>.<name>`` and
        ``getServiceConfig()`` exposes those keys with the prefix trimmed, so a
        bare ``authentication.type`` read inside the ``hadoop`` service is
        really ``httpfs.hadoop.authentication.type``.
        """
        if receiver.rstrip("()") != "getServiceConfig":
            return None
        service = self._service_prefix(scope)
        if not service:
            return None
        return f"{_HTTPFS_SERVER_PREFIX}.{service}.{key}"

    def resolve_expression(self, expr: str, scope: Optional[TypeDecl]) -> Tuple[str, Optional[str]]:
        """Fold a key expression into (resolution, value)."""
        if not expr:
            return "unresolved", None

        value = self.symtab.eval_expr(expr, scope)
        if value is not UNRESOLVED and isinstance(value, str):
            return "exact", value

        parts = _split_top_level_plus(expr)
        if parts and len(parts) > 1:
            prefix = ""
            for part in parts:
                folded = self.symtab.eval_expr(part, scope)
                if folded is UNRESOLVED or not isinstance(folded, str):
                    break
                prefix += folded
            if prefix:
                return "pattern", prefix

        # Nothing folded.  If the expression is at least well-formed Java, the
        # key is genuinely computed at runtime - a finding about Hadoop, not a
        # failure of this tool.  "unresolved" is reserved for text we could not
        # even tokenise, which is always a scanner bug worth looking at.
        try:
            tokenize(expr)
        except Unresolvable:
            return "unresolved", None
        return "dynamic", None

    # ----------------------------------------------------------------- scan

    def scan_file(self, path: str, module: str) -> List[CallSite]:
        jfile = self.symtab.load_path(path)
        if jfile is None:
            return []
        code = jfile.lexed.code
        struct = jfile.lexed.struct
        in_test = is_test_path(path)

        conf_vars = {m.group(2) for m in _CONF_TYPE_RE.finditer(struct)}
        conf_vars |= _CONF_RECEIVER_NAMES

        sites: List[CallSite] = []
        for match in _CALL_RE.finditer(struct):
            receiver = re.sub(r"\s+", "", match.group("recv"))
            bare = receiver.rstrip("()")
            if bare not in conf_vars and bare not in _CONF_RECEIVER_CALLS:
                continue

            open_idx = match.end() - 1
            first, second = _first_argument(struct, code, open_idx)
            if first is None:
                continue

            offset = match.start()
            scope = type_at_offset(jfile.types, offset)
            resolution, value = self.resolve_expression(first, scope)

            accessor = match.group("acc")
            key_field = None
            if resolution == "exact" and '"' not in (first or ""):
                key_field = self.symtab.resolve_field(first, scope)
            key = value if resolution == "exact" else None
            pattern = value if resolution == "pattern" else None
            resolved_value = None
            reconstructed = False

            if key is not None:
                rebuilt = self._reconstruct_httpfs(receiver, key, scope)
                if rebuilt is not None:
                    key = rebuilt
                    reconstructed = True

                if key_field is not None and is_default_field_name(key_field.name):
                    # A *_DEFAULT constant passed where the property name goes.
                    # Two live instances in trunk: NameNode passes "30m" to
                    # getTimeDurationHelper, and DatanodeHttpServer passes a
                    # class name to getClasses, so its fallback never matches.
                    resolution, resolved_value, key = "not-a-property", key, None
                elif key.endswith(".xml"):
                    # A resource filename, not a property - Configuration takes
                    # both in places (addResource-style helpers).
                    resolution, resolved_value, key = "not-a-property", key, None
                elif accessor in _FAMILY_ACCESSORS or is_partial_property(key):
                    # getPropsWithPrefix/getValByRegex select a *family*, and a
                    # constant ending in '.' is a prefix, not a property.
                    resolution, pattern, key = "pattern", key, None
                elif not is_valid_property_name(key):
                    # Folded fine, but it is not a property name.  Real finding:
                    # NameNode passes DFS_..._COLLECT_INTERVAL_DEFAULT ("30m")
                    # where getTimeDurationHelper expects the property name.
                    resolution, resolved_value, key = "not-a-property", key, None

            default_value = None
            if second:
                folded = self.symtab.eval_expr(second, scope)
                if folded is not UNRESOLVED and not isinstance(folded, TimeUnitValue):
                    default_value = java_str(folded)

            sites.append(CallSite(
                path=path, line=jfile.lexed.line_of(offset), module=module,
                accessor=accessor, receiver=receiver,
                expr=" ".join((first or "").split()), resolution=resolution,
                key=key, pattern=pattern, inline_default=second,
                inline_default_value=default_value,
                in_test=in_test, reconstructed=reconstructed,
                resolved_value=resolved_value, key_field=key_field,
            ))

        seen = {(s.line, s.key) for s in sites if s.key}
        sites.extend(self._scan_indirect(jfile, module, conf_vars, in_test, seen))
        return sites

    def _scan_indirect(self, jfile, module: str, conf_vars, in_test: bool,
                       seen) -> List[CallSite]:
        """Find ``helper(conf, KEY, ...)`` reads that bypass the accessors.

        The helper may itself be named like an accessor when it is a static
        utility: ``DFSUtil.getPassword(conf, CONNECTION_PASSWORD)`` is skipped
        by the direct scan (``DFSUtil`` is not a Configuration) and would be
        missed here too if accessor names were excluded.  Duplicates are
        avoided by position instead, since the direct scan only fires when the
        *key* is the first argument, not the Configuration.
        """
        code = jfile.lexed.code
        struct = jfile.lexed.struct
        found: List[CallSite] = []
        for match in _INDIRECT_RE.finditer(struct):
            if match.group("conf") not in conf_vars:
                continue
            helper = match.group("helper")
            open_idx = struct.index("(", match.start())
            close = _match_paren(struct, open_idx)
            if close is None:
                continue
            args = []
            depth = 0
            start = open_idx + 1
            for index in range(open_idx + 1, close):
                char = struct[index]
                if char in "([{":
                    depth += 1
                elif char in ")]}":
                    depth -= 1
                elif char == "," and depth == 0:
                    args.append(code[start:index].strip())
                    start = index + 1
            args.append(code[start:close].strip())

            scope = type_at_offset(jfile.types, match.start())
            line = jfile.lexed.line_of(match.start())
            for arg in args[1:]:
                resolution, value = self.resolve_expression(arg, scope)
                if resolution != "exact" or not value:
                    continue
                if is_partial_property(value) or not is_valid_property_name(value):
                    continue
                if (line, value) in seen:
                    break
                seen.add((line, value))
                found.append(CallSite(
                    path=jfile.path, line=line, module=module,
                    accessor=helper, receiver=match.group("conf"), expr=arg,
                    resolution="exact", key=value, in_test=in_test,
                    key_field=self.symtab.resolve_field(arg, scope) if '"' not in arg else None,
                ))
                break  # only the first property-looking argument is the key
        return found


def scan(symtab: SymbolTable, repo: str, module_paths: Dict[str, str],
         include_tests: bool = True) -> CallSiteExtract:
    from .e2_literals import _iter_sources  # local import to avoid a cycle

    scanner = CallSiteScanner(symtab)
    result = CallSiteExtract()
    for module, relative in module_paths.items():
        root = os.path.join(repo, *relative.split("/"))
        if not os.path.isdir(root):
            continue
        for path in _iter_sources(root, (".java",)):
            if not include_tests and is_test_path(path):
                continue
            result.sites.extend(scanner.scan_file(path, module))
    return result
