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
"""E2 - configuration keys written as string literals rather than constants.

This is where properties hide.  The Test*ConfigFields comparison only sees
constants declared in the classes it is given, so a key spelled inline is
invisible to it - and 83 such keys in HDFS appear in no ``*-default.xml``.

Two tiers are scanned:

* keys under a known prefix (``dfs.``, ``nfs.``, ``httpfs.``, ``hadoop.``);
* any literal passed as the key argument of a ``Configuration`` accessor,
  which catches unexpected prefixes without drowning in false positives.

Comments are removed before scanning: Javadoc mentions property names
constantly, and those mentions are documentation, not declarations.  Native
sources are scanned too - libhdfs++ and fuse-dfs read configuration directly.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .javalex import lex, unescape_java_string
from .semantics import is_partial_property, is_valid_property_name

KEY_PREFIXES = ("dfs.", "nfs.", "httpfs.", "hadoop.")

#: Configuration accessors whose first argument names a property.
#:
#: Kept explicit rather than derived, because not every String-keyed method on
#: Configuration takes a *property* name (see NON_PROPERTY_ACCESSORS).  The
#: list is checked against Configuration's real API by selftest.py, so a new
#: accessor added upstream fails the tests instead of silently going unscanned.
ACCESSORS = (
    "get", "getTrimmed", "getRaw", "getInt", "getInts", "getLong", "getLongBytes",
    "getFloat", "getDouble", "getBoolean", "getEnum", "getClass", "getClasses",
    "getClassByName", "getFile", "getPattern", "getStrings", "getTrimmedStrings",
    "getStringCollection", "getTrimmedStringCollection", "getTimeDuration",
    "getTimeDurations", "getTimeDurationHelper", "getStorageSize", "getSocketAddr",
    "getPassword", "getPasswordFromCredentialProviders", "getInstances",
    "getPropsWithPrefix", "getValByRegex", "getLocalPath", "getRange",
    "getPropertySources",
    "set", "setIfUnset", "setBoolean", "setBooleanIfUnset", "setInt", "setLong",
    "setFloat", "setDouble", "setStrings", "setEnum", "setClass", "setTimeDuration",
    "setSocketAddr", "setPattern", "setStorageSize", "unset",
)

#: String-keyed Configuration methods whose argument is *not* a property name:
#: a class name, or a resource/file name.  Excluded deliberately.
NON_PROPERTY_ACCESSORS = frozenset({
    "getClassByNameOrNull", "getConfResourceAsInputStream",
    "getConfResourceAsReader", "getResource",
})

_LITERAL_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
_ACCESSOR_RE = re.compile(
    r"\.\s*(?P<accessor>" + "|".join(sorted(ACCESSORS, key=len, reverse=True)) + r")"
    r"\s*\(\s*\"(?P<key>(?:\\.|[^\"\\])*)\"\s*(?P<rest>[,)])",
    re.DOTALL,
)

_JAVA_EXT = (".java",)
_NATIVE_EXT = (".c", ".cc", ".cpp", ".h", ".hpp")
_SKIP_DIRS = {"target", ".git", "node_modules", "build"}


@dataclass
class LiteralRecord:
    key: str
    path: str
    line: int
    language: str
    module: str
    accessor: Optional[str] = None
    inline_default: Optional[str] = None
    in_test: bool = False
    #: True when the literal is an operand of a ``+`` concatenation, i.e. a
    #: fragment of a longer key rather than a key in its own right.
    concat_fragment: bool = False

    @property
    def is_accessor_site(self) -> bool:
        return self.accessor is not None


@dataclass
class LiteralExtract:
    records: List[LiteralRecord] = field(default_factory=list)

    def by_key(self) -> Dict[str, List[LiteralRecord]]:
        grouped: Dict[str, List[LiteralRecord]] = {}
        for record in self.records:
            grouped.setdefault(record.key, []).append(record)
        return grouped

    def keys(self):
        return set(record.key for record in self.records)

    def whole_keys(self):
        """Keys seen at least once as a complete literal, not just a fragment."""
        return {r.key for r in self.records if not r.concat_fragment}

    def fragment_only_keys(self):
        return self.keys() - self.whole_keys()


def is_test_path(path: str) -> bool:
    """True for test sources in either the Java or the native layout.

    Java keeps tests under ``src/test/``, but the native client does not:
    ``src/main/native/libhdfs-tests/`` and ``libhdfspp/tests/`` are test code
    living under ``src/main``.  Missing that would present test-only usage of
    keys such as the deprecated ``dfs.block.size`` as production usage.
    """
    parts = os.path.normpath(path).split(os.sep)
    for component in parts[:-1]:
        lowered = component.lower()
        if lowered in ("test", "tests") or lowered.endswith(("-test", "-tests")):
            return True
    name = parts[-1]
    stem = name.rsplit(".", 1)[0]
    return (name.startswith(("Test", "test_"))
            or stem.endswith(("Test", "Tests")))


def _iter_sources(root: str, extensions):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(extensions):
                yield os.path.join(dirpath, name)


def _accepts(key: str) -> bool:
    if not key or is_partial_property(key):
        return False
    return is_valid_property_name(key)


def _is_concat_fragment(code: str, start: int, end: int) -> bool:
    """True when the literal spanning [start, end) is an operand of ``+``.

    ``"dfs.namenode.some-policy" + ".balanced-space-preference-fraction"``
    declares one key, not two; each half on its own would be a phantom
    property.
    """
    index = start - 1
    while index >= 0 and code[index] in " \t\r\n":
        index -= 1
    if index >= 0 and code[index] == "+":
        return True
    index = end
    while index < len(code) and code[index] in " \t\r\n":
        index += 1
    return index < len(code) and code[index] == "+"


def _inline_default(code: str, match: re.Match) -> Optional[str]:
    """Text of the second argument of an accessor call, when there is one."""
    if match.group("rest") != ",":
        return None
    start = match.end()
    depth = 0
    for index in range(start, min(start + 400, len(code))):
        char = code[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return " ".join(code[start:index].split()) or None
            depth -= 1
        elif char == "," and depth == 0:
            return " ".join(code[start:index].split()) or None
    return None


def scan_file(path: str, module: str, language: str) -> List[LiteralRecord]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return []

    lexed = lex(text, path)
    code = lexed.code
    in_test = is_test_path(path)
    records: List[LiteralRecord] = []
    seen: Dict[tuple, LiteralRecord] = {}

    # Tier B first: accessor call sites carry the most information.
    for match in _ACCESSOR_RE.finditer(code):
        key = unescape_java_string('"' + match.group("key") + '"')
        if not _accepts(key):
            continue
        line = lexed.line_of(match.start())
        record = LiteralRecord(
            key=key, path=path, line=line, language=language, module=module,
            accessor=match.group("accessor"),
            inline_default=_inline_default(code, match),
            in_test=in_test,
        )
        seen[(key, line)] = record
        records.append(record)

    # Tier A: any literal under a known configuration prefix.
    for match in _LITERAL_RE.finditer(code):
        key = unescape_java_string('"' + match.group(1) + '"')
        if not key.startswith(KEY_PREFIXES) or not _accepts(key):
            continue
        line = lexed.line_of(match.start())
        if (key, line) in seen:
            continue
        record = LiteralRecord(
            key=key, path=path, line=line, language=language, module=module,
            in_test=in_test,
            concat_fragment=_is_concat_fragment(code, match.start(), match.end()),
        )
        seen[(key, line)] = record
        records.append(record)

    return records


def extract(repo: str, module_paths: Dict[str, str], include_tests: bool = False) -> LiteralExtract:
    """Scan the given modules' sources for literal configuration keys."""
    result = LiteralExtract()
    for module, relative in module_paths.items():
        root = os.path.join(repo, *relative.split("/"))
        if not os.path.isdir(root):
            continue
        for path in _iter_sources(root, _JAVA_EXT + _NATIVE_EXT):
            if not include_tests and is_test_path(path):
                continue
            language = "java" if path.endswith(_JAVA_EXT) else "native"
            result.records.extend(scan_file(path, module, language))
    return result
