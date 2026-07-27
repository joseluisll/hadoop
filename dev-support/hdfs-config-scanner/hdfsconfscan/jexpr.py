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
"""A small evaluator for Java compile-time constant expressions.

Enough of the language is supported to fold the initialisers that actually
appear in Hadoop's ConfigKeys classes::

    String PREFIX     = HdfsClientConfigKeys.PREFIX + "read.";
    String KEY        = PREFIX.substring(0, PREFIX.length() - 1);
    long   MINUTE     = 60 * MS_PER_SECOND;
    long   TIMEOUT    = TimeUnit.MINUTES.toMillis(5);

Anything outside that subset raises :class:`Unresolvable`, which callers report
for human review rather than silently dropping - an unresolved constant is a
potential missing property, so it must never be hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from .javalex import unescape_java_string


class Unresolvable(Exception):
    """Raised when an expression is not a foldable constant expression."""


MISSING = object()

TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<str>"(?:\\.|[^"\\])*")
    | (?P<chr>'(?:\\.|[^'\\])*')
    | (?P<num>0[xX][0-9a-fA-F_]+[lLfFdD]?|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?[lLfFdD]?)
    | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
    | (?P<op>>>>|<<|>>|[-+*/%()~|&^.,])
    """,
    re.VERBOSE,
)

CAST_RE = re.compile(r"\(\s*(?:int|long|short|byte|float|double|char)\s*\)\s*")

BUILTIN_CONSTANTS = {
    "true": True,
    "false": False,
    "null": None,
    "Integer.MAX_VALUE": 2 ** 31 - 1,
    "Integer.MIN_VALUE": -(2 ** 31),
    "Long.MAX_VALUE": 2 ** 63 - 1,
    "Long.MIN_VALUE": -(2 ** 63),
    "Short.MAX_VALUE": 2 ** 15 - 1,
    "Short.MIN_VALUE": -(2 ** 15),
    "Byte.MAX_VALUE": 2 ** 7 - 1,
    "Byte.MIN_VALUE": -(2 ** 7),
}

_TIME_UNIT_NANOS = {
    "NANOSECONDS": 1,
    "MICROSECONDS": 1000,
    "MILLISECONDS": 1000 ** 2,
    "SECONDS": 1000 ** 3,
    "MINUTES": 60 * 1000 ** 3,
    "HOURS": 3600 * 1000 ** 3,
    "DAYS": 86400 * 1000 ** 3,
}


@dataclass(frozen=True)
class TimeUnitValue:
    """``java.util.concurrent.TimeUnit`` constant, for ``toMillis``-style calls."""
    unit: str

    def convert(self, method: str, amount: int) -> int:
        if self.unit not in _TIME_UNIT_NANOS:
            raise Unresolvable()
        nanos = _TIME_UNIT_NANOS[self.unit] * amount
        divisor = {
            "toNanos": 1,
            "toMicros": 1000,
            "toMillis": 1000 ** 2,
            "toSeconds": 1000 ** 3,
            "toMinutes": 60 * 1000 ** 3,
            "toHours": 3600 * 1000 ** 3,
            "toDays": 86400 * 1000 ** 3,
        }.get(method)
        if divisor is None:
            raise Unresolvable()
        return nanos // divisor


def java_str(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(value)
    return str(value)


@dataclass
class Token:
    kind: str
    text: str


def tokenize(expr: str) -> List[Token]:
    tokens: List[Token] = []
    pos = 0
    while pos < len(expr):
        match = TOKEN_RE.match(expr, pos)
        if match is None:
            raise Unresolvable()
        pos = match.end()
        if match.lastgroup != "ws":
            tokens.append(Token(match.lastgroup, match.group()))
    return tokens


def _number(text: str) -> Any:
    cleaned = text.replace("_", "").rstrip("lLfFdD")
    try:
        if cleaned[:2].lower() == "0x":
            return int(cleaned, 16)
        if "." in cleaned or "e" in cleaned.lower():
            return float(cleaned)
        if len(cleaned) > 1 and cleaned.startswith("0"):
            return int(cleaned, 8)
        return int(cleaned)
    except ValueError:
        raise Unresolvable()


def _apply_method(receiver: Any, method: str, args: List[Any]) -> Any:
    if isinstance(receiver, TimeUnitValue):
        if len(args) != 1 or not isinstance(args[0], int):
            raise Unresolvable()
        return receiver.convert(method, args[0])

    if isinstance(receiver, str):
        try:
            if method == "length" and not args:
                return len(receiver)
            if method == "substring" and len(args) == 1:
                return receiver[args[0]:]
            if method == "substring" and len(args) == 2:
                return receiver[args[0]:args[1]]
            if method == "toLowerCase" and not args:
                return receiver.lower()
            if method == "toUpperCase" and not args:
                return receiver.upper()
            if method == "trim" and not args:
                return receiver.strip()
            if method == "isEmpty" and not args:
                return not receiver
            if method == "concat" and len(args) == 1:
                return receiver + java_str(args[0])
            if method == "replace" and len(args) == 2:
                return receiver.replace(java_str(args[0]), java_str(args[1]))
            if method == "charAt" and len(args) == 1:
                return receiver[args[0]]
            if method == "indexOf" and len(args) == 1:
                return receiver.find(java_str(args[0]))
        except (IndexError, TypeError):
            raise Unresolvable()
    raise Unresolvable()


class Parser:
    """Recursive-descent parser over Java constant expressions.

    ``resolve_name`` is supplied by the caller: it maps a dotted name to a
    value, or raises :class:`Unresolvable`.
    """

    def __init__(self, tokens: List[Token], resolve_name: Callable[[List[str]], Any]):
        self.tokens = tokens
        self.pos = 0
        self.resolve_name = resolve_name

    # ------------------------------------------------------------- utilities

    def peek(self, offset: int = 0) -> Optional[Token]:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self) -> Token:
        token = self.peek()
        if token is None:
            raise Unresolvable()
        self.pos += 1
        return token

    def accept_op(self, *ops: str) -> Optional[str]:
        token = self.peek()
        if token is not None and token.kind == "op" and token.text in ops:
            self.pos += 1
            return token.text
        return None

    def expect_op(self, op: str) -> None:
        if self.accept_op(op) is None:
            raise Unresolvable()

    # -------------------------------------------------------------- grammar

    def parse(self) -> Any:
        value = self.expression()
        if self.peek() is not None:
            raise Unresolvable()
        return value

    def expression(self) -> Any:
        return self._binary(0)

    _LEVELS = (
        ("|",), ("^",), ("&",), ("<<", ">>", ">>>"), ("+", "-"), ("*", "/", "%"),
    )

    def _binary(self, level: int) -> Any:
        if level >= len(self._LEVELS):
            return self.unary()
        left = self._binary(level + 1)
        while True:
            op = self.accept_op(*self._LEVELS[level])
            if op is None:
                return left
            right = self._binary(level + 1)
            left = _combine(op, left, right)

    def unary(self) -> Any:
        op = self.accept_op("-", "+", "~")
        if op is None:
            return self.postfix()
        value = self.unary()
        if isinstance(value, str):
            raise Unresolvable()
        if op == "-":
            return -value
        if op == "~":
            return ~value
        return value

    def postfix(self) -> Any:
        value = self.primary()
        while self.peek() is not None and self.peek().kind == "op" and self.peek().text == ".":
            nxt = self.peek(1)
            if nxt is None or nxt.kind != "ident":
                raise Unresolvable()
            self.take()
            method = self.take().text
            args = self.arguments()
            value = _apply_method(value, method, args)
        return value

    def arguments(self) -> List[Any]:
        self.expect_op("(")
        args: List[Any] = []
        if self.accept_op(")") is not None:
            return args
        while True:
            args.append(self.expression())
            if self.accept_op(",") is not None:
                continue
            self.expect_op(")")
            return args

    def primary(self) -> Any:
        token = self.peek()
        if token is None:
            raise Unresolvable()
        if token.kind in ("str", "chr"):
            self.take()
            return unescape_java_string(token.text)
        if token.kind == "num":
            self.take()
            return _number(token.text)
        if token.kind == "op" and token.text == "(":
            self.take()
            value = self.expression()
            self.expect_op(")")
            return value
        if token.kind == "ident":
            return self.qualified_name()
        raise Unresolvable()

    def qualified_name(self) -> Any:
        parts = [self.take().text]
        while True:
            token = self.peek()
            if token is not None and token.kind == "op" and token.text == "(":
                # The trailing segment was a method name after all.
                method = parts.pop()
                args = self.arguments()
                if not parts:
                    raise Unresolvable()
                receiver = self.resolve_name(parts)
                return _apply_method(receiver, method, args)
            if (token is not None and token.kind == "op" and token.text == "."
                    and self.peek(1) is not None and self.peek(1).kind == "ident"):
                # Only continue the name while it still resolves to nothing yet;
                # resolution of the full chain happens once it ends.
                try:
                    value = self.resolve_name(parts)
                except Unresolvable:
                    self.take()
                    parts.append(self.take().text)
                    continue
                # The chain so far is a value; anything further is a method call
                # or field access on it, handled by postfix().
                return value
            return self.resolve_name(parts)


def _combine(op: str, left: Any, right: Any) -> Any:
    if op == "+":
        if isinstance(left, str) or isinstance(right, str):
            return java_str(left) + java_str(right)
        return left + right
    if isinstance(left, str) or isinstance(right, str):
        raise Unresolvable()
    if left is None or right is None or isinstance(left, bool) or isinstance(right, bool):
        raise Unresolvable()
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise Unresolvable()
        return int(left / right) if isinstance(left, int) and isinstance(right, int) else left / right
    if op == "%":
        return left % right
    if op == "<<":
        return left << right
    if op in (">>", ">>>"):
        return left >> right
    if op == "|":
        return left | right
    if op == "&":
        return left & right
    if op == "^":
        return left ^ right
    raise Unresolvable()


def evaluate(expr: str, resolve_name: Callable[[List[str]], Any]) -> Any:
    """Fold ``expr``; raises :class:`Unresolvable` if it is not constant."""
    if expr is None:
        raise Unresolvable()
    expr = CAST_RE.sub("", expr.strip())
    if not expr or "{" in expr or "?" in expr:
        raise Unresolvable()
    return Parser(tokenize(expr), resolve_name).parse()
