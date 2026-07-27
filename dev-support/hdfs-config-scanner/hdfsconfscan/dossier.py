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
"""Evidence dossier for the documentation candidates.

Gathers everything a reviewer needs to write an accurate ``<description>``:
the declaring comment, the value type implied by the accessor, the default,
and the surrounding source lines.  The point is to make the description
*derivable from evidence* - an invented description in hdfs-default.xml is
worse than no entry at all, because administrators would rely on it.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .inventory import ACTIVE_UNDOCUMENTED, Entry, Inventory


def _source_window(path: str, line: int, before: int = 6, after: int = 3) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    start = max(0, line - 1 - before)
    end = min(len(lines), line + after)
    return [f"{n + 1:>6}  {lines[n].rstrip()}" for n in range(start, end)]


def _guide_window(path: str, line: int, before: int = 2, after: int = 2) -> List[str]:
    return _source_window(path, line, before, after)


def build(inv: Inventory, repo: str, status: str = ACTIVE_UNDOCUMENTED) -> str:
    entries = inv.by_status(status)
    by_module: Dict[str, List[Entry]] = {}
    for entry in entries:
        by_module.setdefault(entry.module, []).append(entry)

    out: List[str] = []
    out.append(f"# Evidence dossier - {status} ({len(entries)})")
    out.append("")
    out.append("Raw material for writing `<description>` text. Every claim in a "
               "description should be traceable to something below.")
    out.append("")

    for module in sorted(by_module):
        out.append(f"## Module: {module} ({len(by_module[module])})")
        out.append("")
        for entry in by_module[module]:
            out.append(f"### `{entry.key}`")
            out.append("")
            out.append(f"- constant: `{entry.constant or '(literal)'}`")
            out.append(f"- declared at: `{entry.declared_at or '-'}`")
            out.append(f"- visibility: {entry.visibility or '-'}")
            out.append(f"- value type (from accessor): {entry.value_type or '-'} "
                       f"[{entry.accessors or '-'}]")
            default = entry.default_value if entry.default_value is not None \
                else entry.call_site_default
            out.append(f"- default: `{default if default is not None else '(none found)'}`"
                       + (f"  (constant `{entry.default_constant}`)"
                          if entry.default_constant else "  (from call site)"))
            out.append(f"- reads in main: {entry.read_main}, native: {entry.native_sites}")
            if entry.declaring_comment:
                out.append(f"- declaring comment: {entry.declaring_comment!r}")
            if entry.doc_mentions:
                out.append(f"- **explained in a site guide** ({entry.doc_mentions} mention(s)): "
                           f"`{entry.doc_first_seen}`")
            out.append("")

            if entry.declared_at:
                path, _, line = entry.declared_at.rpartition(":")
                window = _source_window(os.path.join(repo, path), int(line))
                if window:
                    out.append("```java")
                    out.extend(window)
                    out.append("```")
                    out.append("")

            if entry.doc_first_seen:
                path, _, line = entry.doc_first_seen.rpartition(":")
                window = _guide_window(os.path.join(repo, path), int(line))
                if window:
                    out.append("Guide context:")
                    out.append("")
                    out.append("```")
                    out.extend(window)
                    out.append("```")
                    out.append("")
    return "\n".join(out) + "\n"
