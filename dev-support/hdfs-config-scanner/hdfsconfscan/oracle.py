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
"""The self-validation oracle - M1's exit criterion.

``TestHdfsConfigFields`` and ``TestRBFConfigFields`` run with both error modes
enabled and pass on trunk.  That is an externally maintained ground truth: once
the declared skip lists are applied, the constants and the XML agree exactly,
in both directions.

So the scanner must reproduce a zero diff.  Any surplus or missing key is a
defect in *this* tool, not a finding about Hadoop - which is what makes the
later, genuinely new results (literal keys, unused keys, undocumented modules)
trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from . import e1_configkeys, e3_xml, e5_skiplists
from .context import ScanContext
from .registry import ModuleSpec
from .semantics import apply_skips


@dataclass
class OracleResult:
    module_key: str
    xml_path: str
    config_key_count: int = 0
    xml_key_count: int = 0
    compared_config_count: int = 0
    compared_xml_count: int = 0
    missing_in_xml: List[str] = field(default_factory=list)
    missing_in_config: List[str] = field(default_factory=list)
    unresolved_constants: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_skips: List[Dict[str, Any]] = field(default_factory=list)
    missing_classes: List[str] = field(default_factory=list)
    duplicate_xml_properties: List[str] = field(default_factory=list)
    skip_counts: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (not self.missing_in_xml
                and not self.missing_in_config
                and not self.unresolved_skips
                and not self.missing_classes)


def run_module(ctx: ScanContext, spec: ModuleSpec) -> OracleResult:
    if not spec.has_comparison_test or not spec.xml_path or not spec.test_path:
        raise ValueError(f"module {spec.key} has no comparison test to validate against")

    # Take the class list from the test itself so that editing the test - which
    # any documentation patch may need to do - is immediately reflected here.
    classes = e5_skiplists.extract_config_classes(ctx.symtab, ctx.path(spec.test_path))
    keys = e1_configkeys.extract(ctx.symtab, classes or spec.config_classes)
    xml = e3_xml.extract(ctx.path(spec.xml_path))
    skips = e5_skiplists.extract(ctx.symtab, ctx.path(spec.test_path))

    compared_config = apply_skips(keys.keys.keys(), skips.config_props, skips.config_prefixes)
    compared_xml = apply_skips(set(xml.names), skips.xml_props, skips.xml_prefixes)

    return OracleResult(
        module_key=spec.key,
        xml_path=spec.xml_path,
        config_key_count=len(keys.keys),
        xml_key_count=len(set(xml.names)),
        compared_config_count=len(compared_config),
        compared_xml_count=len(compared_xml),
        missing_in_xml=sorted(compared_config - compared_xml),
        missing_in_config=sorted(compared_xml - compared_config),
        unresolved_constants=keys.unresolved,
        unresolved_skips=skips.unresolved,
        missing_classes=keys.missing_classes,
        duplicate_xml_properties=xml.duplicates,
        skip_counts={
            "configurationPropsToSkipCompare": len(skips.config_props),
            "configurationPrefixToSkipCompare": len(skips.config_prefixes),
            "xmlPropsToSkipCompare": len(skips.xml_props),
            "xmlPrefixToSkipCompare": len(skips.xml_prefixes),
        },
    )


def format_result(result: OracleResult) -> str:
    lines = []
    status = "PASS" if result.ok else "FAIL"
    lines.append(f"[{status}] {result.module_key}: {result.xml_path}")
    lines.append(f"  constants (E1): {result.config_key_count} keys"
                 f"  ->  compared: {result.compared_config_count}")
    lines.append(f"  xml       (E3): {result.xml_key_count} properties"
                 f"  ->  compared: {result.compared_xml_count}")
    skip_summary = ", ".join(f"{name.replace('ToSkipCompare', '')}={count}"
                             for name, count in result.skip_counts.items())
    lines.append(f"  skips     (E5): {skip_summary}")

    if result.missing_in_xml:
        lines.append(f"  ERROR constants not found in xml ({len(result.missing_in_xml)}) - "
                     "the Java test would have failed on these, so the scanner is wrong:")
        lines.extend(f"      {key}" for key in result.missing_in_xml[:40])
    if result.missing_in_config:
        lines.append(f"  ERROR xml properties not found in constants "
                     f"({len(result.missing_in_config)}) - scanner is wrong:")
        lines.extend(f"      {key}" for key in result.missing_in_config[:40])
    if result.missing_classes:
        lines.append(f"  ERROR config classes not found: {', '.join(result.missing_classes)}")
    if result.unresolved_skips:
        lines.append(f"  ERROR unresolved skip-list entries ({len(result.unresolved_skips)}):")
        lines.extend(f"      {entry['expr']} ({entry['line']})"
                     for entry in result.unresolved_skips[:20])

    if result.unresolved_constants:
        lines.append(f"  note: {len(result.unresolved_constants)} String constants could not be "
                     "folded (reported for review, not a failure):")
        for entry in result.unresolved_constants[:10]:
            lines.append(f"      {entry['owner'].split('.')[-1]}.{entry['constant']} = "
                         f"{entry['expr']}")
    if result.duplicate_xml_properties:
        lines.append(f"  note: {len(result.duplicate_xml_properties)} properties are defined more "
                     f"than once in the xml: {', '.join(result.duplicate_xml_properties)}")
    return "\n".join(lines)
