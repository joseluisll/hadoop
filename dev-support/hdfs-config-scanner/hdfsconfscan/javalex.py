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
"""Comment- and string-aware lexing of Java sources.

The scanner reads Java lexically; it never compiles it.  Each source file is
turned into three views of identical length, so an offset found in one view
slices correctly into any other:

``raw``     the original text.
``code``    comments replaced by spaces.  Property names are mentioned
            constantly in Javadoc, so literal scanning must not see comments.
``struct``  ``code`` with the *contents* of string and character literals
            replaced by ``x``.  Braces, semicolons and keywords inside a
            literal therefore cannot confuse structural scanning.

Newlines are preserved in every view, so line numbers stay exact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Comment:
    """A comment, kept for reasons/justifications rather than for parsing."""
    start_line: int
    end_line: int
    text: str
    block: bool


@dataclass
class LexedSource:
    path: str
    raw: str
    code: str
    struct: str
    comments: List[Comment]

    def line_of(self, offset: int) -> int:
        """1-based line number containing ``offset``."""
        return self.raw.count("\n", 0, offset) + 1


def _clean_block_comment(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"^\s*\*+\s?", "", line).rstrip())
    return "\n".join(line for line in lines).strip()


def lex(src: str, path: str = "<memory>") -> LexedSource:
    """Produce the raw/code/struct views plus the comment list."""
    n = len(src)
    code = list(src)
    struct = list(src)
    comments: List[Comment] = []
    i = 0
    line = 1

    def blank(start: int, end: int, views, filler: str = " ") -> None:
        for k in range(start, min(end, n)):
            if src[k] != "\n":
                for v in views:
                    v[k] = filler

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            i += 1
            continue

        # Line comment.
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = i
            while j < n and src[j] != "\n":
                j += 1
            comments.append(Comment(line, line, src[i + 2:j].strip(), False))
            blank(i, j, (code, struct))
            i = j
            continue

        # Block comment.
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            start_line = line
            j = i + 2
            while j < n - 1 and not (src[j] == "*" and src[j + 1] == "/"):
                if src[j] == "\n":
                    line += 1
                j += 1
            j = min(j + 2, n)
            comments.append(
                Comment(start_line, line, _clean_block_comment(src[i + 2:max(i + 2, j - 2)]), True))
            blank(i, j, (code, struct))
            i = j
            continue

        # Text block (Java 15+).
        if src.startswith('"""', i):
            j = i + 3
            while j < n and not src.startswith('"""', j):
                if src[j] == "\n":
                    line += 1
                j += 1
            end = min(j + 3, n)
            blank(i + 3, max(i + 3, end - 3), (struct,), "x")
            i = end
            continue

        # String / character literal: keep the text in ``code``, mask in ``struct``.
        if c in ('"', "'"):
            quote = c
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote or src[j] == "\n":
                    break
                j += 1
            blank(i + 1, j, (struct,), "x")
            if j < n and src[j] == "\n":
                # Unterminated literal; resync at the newline.
                i = j
                continue
            i = min(j + 1, n)
            continue

        i += 1

    return LexedSource(path, src, "".join(code), "".join(struct), comments)


_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
    "0": "\0", "\\": "\\", '"': '"', "'": "'", "s": " ",
}


def unescape_java_string(literal: str) -> str:
    """Convert a Java string literal (including quotes) to its runtime value."""
    if len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in ('"', "'"):
        literal = literal[1:-1]
    out = []
    i = 0
    n = len(literal)
    while i < n:
        ch = literal[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        esc = literal[i]
        if esc == "u":
            j = i + 1
            while j < n and literal[j] == "u":
                j += 1
            hex_digits = literal[j:j + 4]
            try:
                out.append(chr(int(hex_digits, 16)))
                i = j + 4
                continue
            except ValueError:
                out.append("u")
                i += 1
                continue
        if esc in _ESCAPES:
            out.append(_ESCAPES[esc])
            i += 1
            continue
        if esc.isdigit():
            j = i
            while j < n and j < i + 3 and literal[j].isdigit():
                j += 1
            try:
                out.append(chr(int(literal[i:j], 8)))
                i = j
                continue
            except ValueError:
                pass
        out.append(esc)
        i += 1
    return "".join(out)
