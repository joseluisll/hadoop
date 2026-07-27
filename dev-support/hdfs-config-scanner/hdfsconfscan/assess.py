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
"""M3 - per-property recommendations with proposed xml.

Descriptions are *derived*, never invented.  Each one comes from the Javadoc on
the declaring constant or from the site guide that already explains the
property to administrators, and the source is recorded next to it.  Where
neither exists the entry is emitted with an explicit TODO instead of a
plausible-sounding sentence: a wrong description in hdfs-default.xml is worse
than a missing one, because operators would act on it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .inventory import ACTIVE_UNDOCUMENTED, Entry, Inventory

#: Review batches for upstreaming, keyed by prefix.  Reviewers know these
#: subsystems separately, so a patch per area gets read; one patch of 60 does not.
BATCHES: List[Tuple[str, str, str]] = [
    ("dfs.datatransfer.", "datatransfer-allowlists",
     "IP allow/deny lists for encrypted data transfer "
     "(WhitelistBasedTrustedChannelResolver / BlackListBasedTrustedChannelResolver)"),
    ("dfs.ha.tail-edits.", "ha-tail-edits", "Standby/observer edit-log tailing"),
    ("dfs.namenode.", "namenode-misc", "Assorted NameNode options"),
    ("dfs.client.", "client-misc", "Client-side options"),
    ("dfs.webhdfs.oauth2.", "webhdfs-oauth2",
     "WebHDFS OAuth2 credentials, already documented in WebHDFS.md"),
    ("dfs.federation.router.", "rbf-router", "Router-based federation"),
    ("sql-dt-secret-manager.", "rbf-sql-secret-manager",
     "SQL-backed delegation token secret manager"),
    ("state-store-mysql.", "rbf-state-store-mysql", "MySQL state store connection"),
    ("zk-dt-secret-manager.", "rbf-zk-secret-manager", "ZooKeeper secret manager"),
    ("nfs.", "nfs-gateway", "NFS gateway"),
    ("httpfs.", "httpfs", "HttpFS server"),
]

_TODO = ("TODO: no Javadoc or guide text exists for this property; a description "
         "must come from someone familiar with the subsystem.")


@dataclass
class Proposal:
    entry: Entry
    description: str
    description_source: str
    value: Optional[str]
    batch: str
    batch_title: str

    @property
    def needs_author(self) -> bool:
        return self.description_source == "none"


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    text = text.replace("`", "")
    # Markdown emphasis is meaningless inside an xml description; unwrap
    # it rather than dropping the words it emphasises.
    text = re.sub(r"\*+([^*]+)\*+", lambda m: m.group(1), text)
    text = re.sub(r"^[-*\s]+", "", text)
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if not text.endswith((".", "!", "?")):
        text += "."
    return text


def _from_guide(repo: str, doc_first_seen: Optional[str], key: str) -> str:
    """Pull the explanation out of a guide, including markdown table rows."""
    if not doc_first_seen:
        return ""
    path, _, line = doc_first_seen.rpartition(":")
    try:
        with open(os.path.join(repo, path), "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except (OSError, ValueError):
        return ""
    try:
        text = lines[int(line) - 1]
    except (IndexError, ValueError):
        return ""
    # Only a table row is trustworthy: it has a dedicated description column.
    # A bare line mentioning the key is as likely to be an xml example
    # (`<name>nfs.superuser</name>`) or mid-paragraph prose, and lifting that
    # into a <description> produces markup noise dressed up as documentation.
    if text.count("|") < 2:
        return ""
    cells = [c.strip() for c in text.strip().strip("|").split("|")]
    for index, cell in enumerate(cells):
        if key in cell and index + 1 < len(cells):
            candidate = _clean(cells[index + 1].replace("`", ""))
            if "<" in candidate or len(candidate) < 15 or key in candidate:
                return ""
            return candidate
    return ""


def _batch_for(key: str) -> Tuple[str, str]:
    for prefix, name, title in BATCHES:
        if key.startswith(prefix):
            return name, title
    return "other", "Uncategorised"


def build_proposals(inv: Inventory, repo: str) -> List[Proposal]:
    proposals: List[Proposal] = []
    for entry in inv.by_status(ACTIVE_UNDOCUMENTED):
        description = _clean(entry.declaring_comment)
        source = "javadoc" if description else "none"
        if not description:
            description = _from_guide(repo, entry.doc_first_seen, entry.key)
            source = "site guide" if description else "none"
        if not description:
            description = _TODO
        # Only folded values may become an xml <value>.  Where the default is
        # computed at runtime the entry gets an empty value and a comment
        # recording the expression, so a reviewer can decide what to write.
        value = entry.default_value
        if value is None:
            value = entry.call_site_default
        batch, title = _batch_for(entry.key)
        proposals.append(Proposal(entry=entry, description=description,
                                  description_source=source, value=value,
                                  batch=batch, batch_title=title))
    return proposals


def _xml_block(proposal: Proposal) -> List[str]:
    entry = proposal.entry
    value = proposal.value
    if (value is None or value.startswith(("get", "new "))
            or "(" in value or value.endswith(".class")):
        # Not something that can be written literally in xml: a computed value
        # (getServer().getConfigDir()) or a Java class literal
        # (KerberosDelegationTokenAuthenticator.class), which would need the
        # fully qualified name a reviewer must supply.
        value_text = ""
        expr = value or getattr(proposal.entry, "call_site_default_expr", None)
        # A bare local-variable name ("fixedFile") means nothing to an operator
        # reading the shipped file; only an expression that says something -
        # getServer().getConfigDir() - is worth a comment.
        if expr and not re.fullmatch(r"[A-Za-z_$][\w$]*", expr):
            note = f"    <!-- default in code: {expr} -->"
        else:
            note = ""
    else:
        value_text = value
        note = ""
    lines = ["  <property>", f"    <name>{entry.key}</name>",
             f"    <value>{value_text}</value>"]
    if note:
        lines.append(note)
    lines.append("    <description>")
    lines.append(f"      {proposal.description}")
    lines.append("    </description>")
    lines.append("  </property>")
    return lines


def write_assessment(inv: Inventory, repo: str, md_path: str, xml_path: str) -> Dict[str, int]:
    proposals = build_proposals(inv, repo)
    by_batch: Dict[str, List[Proposal]] = {}
    for proposal in proposals:
        by_batch.setdefault(proposal.batch, []).append(proposal)

    authored = sum(1 for p in proposals if not p.needs_author)
    todo = sum(1 for p in proposals if p.needs_author)

    out: List[str] = []
    out.append("# HDFS-11039 - assessment and proposed documentation")
    out.append("")
    out.append(f"{len(proposals)} properties are read by production HDFS code and appear in "
               "no `*-default.xml`. This is the answer to the question asked on the JIRA in "
               "December 2018.")
    out.append("")
    out.append(f"Of these, **{authored}** come with a description derived from the Javadoc on "
               f"the declaring constant or from a site guide that already explains the property "
               f"to administrators; **{todo}** have no such source and are marked TODO rather "
               "than given an invented description.")
    out.append("")
    out.append("Every row is traceable: the declaring file and line come from the scanner's "
               "verified provenance, and extraction is validated against Hadoop's own "
               "`TestHdfsConfigFields` / `TestRBFConfigFields`.")
    out.append("")

    out.append("## Review batches")
    out.append("")
    out.append("| Batch | Area | Properties | Need a description author |")
    out.append("| --- | --- | --- | --- |")
    for batch in sorted(by_batch):
        items = by_batch[batch]
        out.append(f"| `{batch}` | {items[0].batch_title} | {len(items)} | "
                   f"{sum(1 for p in items if p.needs_author)} |")
    out.append("")

    for batch in sorted(by_batch):
        items = sorted(by_batch[batch], key=lambda p: p.entry.key)
        out.append(f"## {batch} - {items[0].batch_title} ({len(items)})")
        out.append("")
        target = items[0].entry.module
        out.append(f"Target file: `{_target_xml(target)}`")
        out.append("")
        for proposal in items:
            entry = proposal.entry
            out.append(f"### `{entry.key}`")
            out.append("")
            out.append(f"- declared: `{entry.declared_at}` (`{entry.constant}`)")
            out.append(f"- type: {entry.value_type or 'string'}; "
                       f"default: `{proposal.value if proposal.value is not None else '(none)'}`"
                       + (f" - computed at runtime from `{entry.call_site_default_expr}`"
                          if proposal.value is None and entry.call_site_default_expr else ""))
            out.append(f"- reads in production: {entry.read_main}"
                       + (f", native: {entry.native_sites}" if entry.native_sites else ""))
            out.append(f"- description source: **{proposal.description_source}**"
                       + (f" (`{entry.doc_first_seen}`)"
                          if proposal.description_source == "site guide" else ""))
            out.append("")
            out.append("```xml")
            out.extend(_xml_block(proposal))
            out.append("```")
            out.append("")

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")

    # Ready-to-paste xml, grouped by the file it belongs in.
    xml_out: List[str] = ["<!-- Proposed additions for HDFS-11039.",
                          "     Generated by dev-support/hdfs-config-scanner.",
                          "     Entries marked TODO still need a description. -->"]
    by_target: Dict[str, List[Proposal]] = {}
    for proposal in proposals:
        by_target.setdefault(_target_xml(proposal.entry.module), []).append(proposal)
    for target in sorted(by_target):
        xml_out.append("")
        xml_out.append(f"<!-- ===== {target} ===== -->")
        for proposal in sorted(by_target[target], key=lambda p: p.entry.key):
            xml_out.append("")
            xml_out.extend(_xml_block(proposal))
    with open(xml_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(xml_out) + "\n")

    return {"total": len(proposals), "described": authored, "todo": todo,
            "batches": len(by_batch)}


def _target_xml(module: str) -> str:
    return {
        "rbf": "hadoop-hdfs-rbf/src/main/resources/hdfs-rbf-default.xml",
        "httpfs": "hadoop-hdfs-httpfs/src/main/resources/httpfs-default.xml",
    }.get(module, "hadoop-hdfs/src/main/resources/hdfs-default.xml")
