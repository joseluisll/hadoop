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
"""Lexical extraction of type declarations and constant fields from Java.

Only what the scanner needs is modelled: nested type structure (so that
``HdfsClientConfigKeys.Failover`` is a distinct scope from its enclosing
interface) and ``public static final`` primitive/String fields.

Two Hadoop-specific details drive the design:

* ``HdfsClientConfigKeys`` is an *interface*, so its fields carry no explicit
  modifiers yet are implicitly ``public static final``.  A naive
  "public static final" match extracts nothing from it.
* ``TestConfigurationFieldsBase`` uses ``Class#getDeclaredFields``, so fields
  of a nested type belong to that nested type alone and are only compared when
  the nested type is listed explicitly.  Field ownership is tracked per scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .javalex import LexedSource, lex

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+(static\s+)?([\w.*]+)\s*;", re.MULTILINE)
TYPE_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
ANNOTATION_RE = re.compile(r"^\s*@\s*[\w.]+\s*(?:\([^()]*\))?\s*")

_MODIFIERS = (
    "public", "protected", "private", "static", "final", "transient",
    "volatile", "synchronized", "native", "abstract", "strictfp", "default",
)
_SCALAR_TYPES = ("String", "int", "long", "short", "boolean", "float", "double", "byte", "char")

FIELD_RE = re.compile(
    r"^\s*(?P<mods>(?:(?:" + "|".join(_MODIFIERS) + r")\s+)*)"
    r"(?P<type>" + "|".join(_SCALAR_TYPES) + r")\s+"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*"
    r"(?:=\s*(?P<init>.*?))?\s*$",
    re.DOTALL,
)


@dataclass
class TypeDecl:
    name: str
    kind: str
    qname: str
    line: int
    body_start: int
    body_end: int
    supertypes: List[str] = field(default_factory=list)
    parent: Optional["TypeDecl"] = None
    fields: Dict[str, "FieldDecl"] = field(default_factory=dict)

    @property
    def is_interface(self) -> bool:
        return self.kind == "interface"


@dataclass
class FieldDecl:
    name: str
    java_type: str
    init_expr: Optional[str]
    line: int
    owner_qname: str
    annotations: List[str]
    public_static_final: bool
    source_path: str
    #: Raw modifier text.  Visibility separates a supported knob from internal
    #: plumbing: dfs.ha.tail-edits.max-txns-per-lock is `public static final`,
    #: while SnapshotManager's keys are package-private.
    modifiers: str = ""
    #: Comment immediately above the declaration.  SnapshotManager introduces
    #: its keys with "The following are private configurations" - an explicit
    #: statement that they must not be documented.
    doc: str = ""

    @property
    def visibility(self) -> str:
        for keyword in ("public", "protected", "private"):
            if re.search(r"\b" + keyword + r"\b", self.modifiers):
                return keyword
        return "package-private"

    @property
    def is_default_name(self) -> bool:
        """Mirrors ``TestConfigurationFieldsBase#isFieldADefaultValue``."""
        return self.name.startswith("DEFAULT_") or self.name.endswith("_DEFAULT")

    @property
    def deprecated(self) -> bool:
        return any(a.lstrip("@").strip().split("(")[0].endswith("Deprecated")
                   for a in self.annotations)


@dataclass
class JavaFile:
    path: str
    package: str
    imports: List[str]
    lexed: LexedSource
    types: Dict[str, TypeDecl]
    #: ``import static a.b.C.FIELD`` / ``a.b.C.*`` - how HDFS code refers to
    #: key constants by bare name (``DFS_HA_NAMENODES_KEY_PREFIX + "." + nsId``).
    static_imports: List[str] = field(default_factory=list)

    def type_by_simple_name(self, name: str) -> Optional[TypeDecl]:
        for qname, decl in self.types.items():
            if decl.name == name:
                return decl
        return None


def _match_brace(struct: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(struct)):
        ch = struct[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(struct) - 1


def _supertypes(header: str) -> List[str]:
    names: List[str] = []
    for clause in ("extends", "implements"):
        m = re.search(clause + r"\s+([^{]*)", header)
        if not m:
            continue
        body = re.sub(r"<[^<>]*>", "", m.group(1))
        for part in body.split(","):
            part = part.strip().split()[0] if part.strip() else ""
            if part and part not in ("extends", "implements"):
                names.append(part)
    return names


def _iter_statements(struct: str, start: int, end: int):
    """Yield (start, end) spans of ``;``-terminated statements at brace depth 0.

    Nested blocks (method bodies, nested types, initialiser blocks) sit at
    depth > 0 and are skipped; the buffer resets when a block closes, which
    discards the block's header text.
    """
    depth = 0
    buf = start
    for i in range(start, end):
        ch = struct[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth <= 0:
                depth = 0
                buf = i + 1
        elif ch == ";" and depth == 0:
            yield buf, i
            buf = i + 1


def parse_file(path: str, text: Optional[str] = None) -> JavaFile:
    if text is None:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    lexed = lex(text, path)
    struct = lexed.struct
    code = lexed.code

    pkg_match = PACKAGE_RE.search(code)
    package = pkg_match.group(1) if pkg_match else ""
    imports = []
    static_imports = []
    for m in IMPORT_RE.finditer(code):
        (static_imports if m.group(1) else imports).append(m.group(2))

    # Discover type declarations and their bodies.
    raw_types: List[TypeDecl] = []
    for m in TYPE_RE.finditer(struct):
        brace = struct.find("{", m.end())
        if brace < 0:
            continue
        header = struct[m.end():brace]
        # A ';' before the body means this was not a type declaration body
        # (e.g. an annotation usage or a forward reference).
        if ";" in header:
            continue
        end = _match_brace(struct, brace)
        raw_types.append(TypeDecl(
            name=m.group(2),
            kind=m.group(1),
            qname="",
            line=lexed.line_of(m.start()),
            body_start=brace + 1,
            body_end=end,
            supertypes=_supertypes(code[m.end():brace]),
        ))

    # Establish nesting by containment, then qualified names.
    raw_types.sort(key=lambda t: t.body_start)
    for i, decl in enumerate(raw_types):
        parent = None
        for candidate in raw_types[:i]:
            if candidate.body_start < decl.body_start <= candidate.body_end:
                if parent is None or candidate.body_start > parent.body_start:
                    parent = candidate
        decl.parent = parent
    for decl in raw_types:
        chain = []
        node: Optional[TypeDecl] = decl
        while node is not None:
            chain.append(node.name)
            node = node.parent
        chain.reverse()
        decl.qname = ".".join(([package] if package else []) + chain)

    types = {decl.qname: decl for decl in raw_types}

    # Comments are looked up by the line they end on, so a declaration can
    # find the note written immediately above it.
    comment_by_end = {}
    for comment in lexed.comments:
        comment_by_end[comment.end_line] = comment.text

    def doc_above(line: int, window: int = 3) -> str:
        for offset in range(1, window + 1):
            text = comment_by_end.get(line - offset)
            if text:
                return text
        return ""

    # Extract fields per scope.
    for decl in raw_types:
        for span_start, span_end in _iter_statements(struct, decl.body_start, decl.body_end):
            stmt = code[span_start:span_end]
            if not stmt.strip():
                continue
            annotations: List[str] = []
            while True:
                am = ANNOTATION_RE.match(stmt)
                if not am:
                    break
                annotations.append(am.group(0).strip())
                stmt = stmt[am.end():]
            fm = FIELD_RE.match(stmt)
            if not fm:
                continue
            mods = fm.group("mods") or ""
            psf = decl.is_interface or all(
                re.search(r"\b" + kw + r"\b", mods) for kw in ("public", "static", "final"))
            name = fm.group("name")
            init = fm.group("init")
            # The statement buffer starts just after the previous ';', so it
            # opens with whitespace and possibly annotations.  Anchor the line
            # on the field name: that is where a reviewer following the
            # reference expects to land, and it is what `scan.py verify`
            # checks.
            stmt_offset = span_start + (span_end - span_start) - len(stmt)
            # The statement span opens just after the previous ';', which is on
            # the *previous* field's line.  Anchoring the comment lookup there
            # attaches each field the Javadoc of the field above it - which
            # would put a confidently wrong description into hdfs-default.xml.
            first_char = stmt_offset
            while first_char < span_end and code[first_char] in " \t\r\n":
                first_char += 1
            decl_line = lexed.line_of(first_char)
            decl.fields[name] = FieldDecl(
                name=name,
                java_type=fm.group("type"),
                init_expr=init.strip() if init else None,
                line=lexed.line_of(stmt_offset + fm.start("name")),
                owner_qname=decl.qname,
                annotations=annotations,
                public_static_final=bool(psf),
                source_path=path,
                modifiers=" ".join(mods.split()) or ("public static final"
                                                     if decl.is_interface else ""),
                doc=doc_above(decl_line),
            )

    return JavaFile(path=path, package=package, imports=imports, lexed=lexed, types=types,
                    static_imports=static_imports)
