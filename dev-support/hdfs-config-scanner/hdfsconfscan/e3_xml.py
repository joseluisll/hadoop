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
"""E3 - properties documented in ``*-default.xml`` files.

``Configuration`` keeps the last definition of a repeated property, so a
duplicated ``<property>`` block is silently shadowed rather than reported.  The
duplicates are surfaced here because they are a real (if minor) documentation
defect worth fixing alongside HDFS-11039.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_NAME_RE = re.compile(r"<name>\s*([^<]*?)\s*</name>", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _blank_comments(text: str) -> str:
    """Replace comment bodies with spaces, preserving every offset and line.

    Commented-out ``<property>`` blocks are used as documentation examples -
    httpfs-default.xml carries ``httpfs.proxyuser.#USER#.hosts`` that way, and
    hdfs-default.xml does the same for ``dfs.ha.namenodes``.  ElementTree does
    not see them, so a naive scan pairs the wrong name with every property
    that follows.
    """
    return _COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


@dataclass
class XmlProperty:
    name: str
    value: Optional[str]
    description: str
    path: str
    line: int
    has_value_tag: bool
    is_final: bool = False

    @property
    def empty_value(self) -> bool:
        return self.value is not None and not self.value.strip()


@dataclass
class XmlExtract:
    path: str
    properties: List[XmlProperty] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)

    @property
    def names(self) -> List[str]:
        return [p.name for p in self.properties]

    def by_name(self) -> Dict[str, XmlProperty]:
        # Last definition wins, matching Configuration's load order.
        return {p.name: p for p in self.properties}


def extract(path: str) -> XmlExtract:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()

    # ElementTree does not expose line numbers; recover them by scanning the
    # <name> elements in document order, which matches the parsed order once
    # commented-out blocks are excluded.  The line recorded is that of the name
    # text, which may sit on its own line inside the tags.
    name_lines = [text.count("\n", 0, m.start(1)) + 1
                  for m in _NAME_RE.finditer(_blank_comments(text))]

    root = ET.fromstring(text)
    result = XmlExtract(path=path)

    for index, prop in enumerate(root.findall("property")):
        name_el = prop.find("name")
        if name_el is None or not (name_el.text or "").strip():
            continue
        value_el = prop.find("value")
        desc_el = prop.find("description")
        final_el = prop.find("final")
        result.properties.append(XmlProperty(
            name=(name_el.text or "").strip(),
            value=(value_el.text or "") if value_el is not None else None,
            description=" ".join((desc_el.text or "").split()) if desc_el is not None else "",
            path=path,
            line=name_lines[index] if index < len(name_lines) else 0,
            has_value_tag=value_el is not None,
            is_final=bool(final_el is not None and (final_el.text or "").strip() == "true"),
        ))

    counts = Counter(p.name for p in result.properties)
    result.duplicates = sorted(name for name, count in counts.items() if count > 1)
    return result
