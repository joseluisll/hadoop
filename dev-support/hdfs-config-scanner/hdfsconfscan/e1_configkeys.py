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
"""E1 - configuration keys declared as constants in ConfigKeys classes.

Reproduces ``TestConfigurationFieldsBase#extractMemberVariablesFromConfiguration\
Fields`` and its default-value counterpart, but lexically and with the
provenance (file, line, constant name) that the reflection-based original
discards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .javamodel import FieldDecl
from .semantics import (
    default_constant_candidates,
    is_default_field_name,
    is_partial_property,
    is_valid_property_name,
)
from .symbols import UNRESOLVED, SymbolTable, java_str


@dataclass
class KeyRecord:
    key: str
    constant: str
    owner: str
    path: str
    line: int
    deprecated: bool = False
    default_constant: Optional[str] = None
    default_value: Optional[str] = None


@dataclass
class ConfigKeysExtract:
    keys: Dict[str, KeyRecord] = field(default_factory=dict)
    defaults: Dict[str, str] = field(default_factory=dict)
    default_fields: Dict[str, FieldDecl] = field(default_factory=dict)
    #: Constants that look like key fragments (``dfs.client.``) - dynamic
    #: pattern candidates rather than properties in their own right.
    partial: List[KeyRecord] = field(default_factory=list)
    #: String constants whose value could not be folded.
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    #: Resolved String constants rejected by the base test's name pattern.
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    missing_classes: List[str] = field(default_factory=list)

    def constants_by_name(self) -> Dict[str, KeyRecord]:
        return {rec.constant: rec for rec in self.keys.values()}


def extract(symtab: SymbolTable, class_qnames: List[str]) -> ConfigKeysExtract:
    """Extract key constants and default constants from the listed classes."""
    result = ConfigKeysExtract()

    for qname in class_qnames:
        decl = symtab.load_class(qname)
        if decl is None:
            result.missing_classes.append(qname)
            continue

        for fdecl in decl.fields.values():
            if not fdecl.public_static_final:
                continue

            if is_default_field_name(fdecl.name):
                value = symtab.value_of_field(fdecl)
                if value is not UNRESOLVED:
                    result.defaults.setdefault(fdecl.name, java_str(value))
                    result.default_fields.setdefault(fdecl.name, fdecl)
                continue

            # Only String constants can name a property.
            if fdecl.java_type != "String":
                continue

            value = symtab.value_of_field(fdecl)
            if value is UNRESOLVED or not isinstance(value, str):
                result.unresolved.append({
                    "constant": fdecl.name,
                    "owner": fdecl.owner_qname,
                    "expr": fdecl.init_expr,
                    "path": fdecl.source_path,
                    "line": fdecl.line,
                })
                continue

            record = KeyRecord(
                key=value,
                constant=fdecl.name,
                owner=fdecl.owner_qname,
                path=fdecl.source_path,
                line=fdecl.line,
                deprecated=fdecl.deprecated,
            )

            if is_partial_property(value):
                result.partial.append(record)
                continue
            if not is_valid_property_name(value):
                result.rejected.append({
                    "constant": fdecl.name,
                    "owner": fdecl.owner_qname,
                    "value": value,
                    "path": fdecl.source_path,
                    "line": fdecl.line,
                })
                continue

            # First declaration of a value wins, as in the base test.
            result.keys.setdefault(value, record)

    _attach_defaults(result)
    return result


def _attach_defaults(result: ConfigKeysExtract) -> None:
    """Pair each key with its default constant using the base test's rules."""
    for record in result.keys.values():
        for candidate in default_constant_candidates(record.constant):
            if candidate in result.defaults:
                record.default_constant = candidate
                record.default_value = result.defaults[candidate]
                break
