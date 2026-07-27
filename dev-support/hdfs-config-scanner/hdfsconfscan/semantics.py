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
"""Filter rules copied from ``TestConfigurationFieldsBase``.

These are reproduced deliberately, quirks included, because the scanner's
self-validation oracle depends on matching the Java behaviour exactly.  The
upstream pattern contains a stray ``%s`` inside the second character class::

    private static final String VALID_PROP_REGEX =
        "^[A-Za-z][A-Za-z0-9_-]+(\\\\.[A-Za-z%s0-9_-]+)+$";

It is kept verbatim rather than "fixed": the goal is to mirror what the test
accepts, not what it arguably meant to accept.
"""

from __future__ import annotations

import re
from typing import Iterable, Set

VALID_PROP_REGEX = r"^[A-Za-z][A-Za-z0-9_-]+(\.[A-Za-z%s0-9_-]+)+$"
VALID_PROP_PATTERN = re.compile(VALID_PROP_REGEX)

#: Suffixes that mark a constant as a fragment of a key rather than a key.
PARTIAL_SUFFIXES = (".xml", ".", "-")


def is_valid_property_name(value: str) -> bool:
    return bool(VALID_PROP_PATTERN.search(value))


def is_partial_property(value: str) -> bool:
    return value.endswith(PARTIAL_SUFFIXES)


def is_default_field_name(name: str) -> bool:
    """Mirrors ``TestConfigurationFieldsBase#isFieldADefaultValue``."""
    return name.startswith("DEFAULT_") or name.endswith("_DEFAULT")


def skipped(value: str, exact: Iterable[str], prefixes: Iterable[str]) -> bool:
    if value in set(exact):
        return True
    return any(value.startswith(prefix) for prefix in prefixes)


def apply_skips(values: Iterable[str], exact: Set[str], prefixes: Set[str]) -> Set[str]:
    return {v for v in values if not skipped(v, exact, prefixes)}


def default_constant_candidates(key_constant: str):
    """The three default-constant naming conventions the base test tries.

    Type 1 prepends ``DEFAULT_``; type 2 swaps a ``_KEY`` suffix for
    ``_DEFAULT``; type 3 appends ``_DEFAULT``.
    """
    candidates = ["DEFAULT_" + key_constant]
    if key_constant.endswith("_KEY"):
        candidates.append(key_constant[:-4] + "_DEFAULT")
    candidates.append(key_constant + "_DEFAULT")
    return candidates
