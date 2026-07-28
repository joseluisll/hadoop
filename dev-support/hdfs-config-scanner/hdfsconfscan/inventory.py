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
"""Usage analysis and classification - the HDFS-11039 inventory.

Every extractor's evidence is joined per property and reduced to one status,
so the JIRA question ("which properties should be added to hdfs-default.xml?")
gets an answer with the reasoning attached rather than a bare list.

Classification never guesses silently: every entry carries the evidence that
produced its status, and anything the rules cannot settle is left as
NEEDS_REVIEW instead of being quietly filed away.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import callsites as callsites_mod
from . import e1_configkeys, e2_literals, e3_xml, e4_deprecations, e5_skiplists, e7_docs
from .context import ScanContext
from .registry import (
    DEPRECATION_SOURCES, DOC_ROOTS, MODULES, MODULES_BY_KEY, OTHER_XML_FILES,
)

# Statuses, ordered from "document it" to "leave it alone".
ACTIVE_UNDOCUMENTED = "ACTIVE_UNDOCUMENTED"
ACTIVE_DOCUMENTED = "ACTIVE_DOCUMENTED"
DOCUMENTED_ELSEWHERE = "DOCUMENTED_ELSEWHERE"
DYNAMIC_PATTERN = "DYNAMIC_PATTERN"
DEPRECATED_ALIAS = "DEPRECATED_ALIAS"
DEPRECATED_CONSTANT = "DEPRECATED_CONSTANT"
INTERNAL_SKIPLISTED = "INTERNAL_SKIPLISTED"
SKIPLISTED_CONTESTED = "SKIPLISTED_CONTESTED"
INTERNAL_PRIVATE = "INTERNAL_PRIVATE"
TEST_ONLY = "TEST_ONLY"
UNUSED = "UNUSED"
EXTERNAL = "EXTERNAL"
NEEDS_REVIEW = "NEEDS_REVIEW"

#: Phrases that declare intent in the source itself.
_PRIVATE_MARKERS = ("private configuration", "not intended for users",
                    "internal use", "for testing", "test only", "testing only")

#: Namespaces owned by other components.  HDFS code reads some of these - the
#: client checks mapreduce.task.attempt.id just to learn whether it is running
#: inside a MapReduce task - but documenting them in hdfs-default.xml would be
#: wrong even when no other default file lists them (that key is injected by
#: the MR framework at runtime, so it appears in no *-default.xml at all).
_FOREIGN_NAMESPACES = ("mapreduce.", "mapred.", "yarn.", "ssl.")


@dataclass
class Entry:
    key: str
    status: str = NEEDS_REVIEW
    module: str = ""
    documented_in: Optional[str] = None
    xml_value: Optional[str] = None
    constant: Optional[str] = None
    declared_at: Optional[str] = None
    visibility: str = ""
    declaring_comment: str = ""
    default_constant: Optional[str] = None
    default_value: Optional[str] = None
    default_conflict: Optional[str] = None
    read_main: int = 0
    read_test: int = 0
    write_main: int = 0
    write_test: int = 0
    literal_sites: int = 0
    native_sites: int = 0
    deprecated_to: Optional[str] = None
    #: True when the Java constant carries @Deprecated.  Usually means the
    #: constant moved class, not that the property is going away - kept as a
    #: column rather than a status for exactly that reason.
    deprecated_constant: bool = False
    skip_reason: Optional[str] = None
    #: @VisibleForTesting, or an INTERNAL_-prefixed constant name: the author
    #: stating that this knob is not a supported, documentable option.
    internal_marker: str = ""
    #: Mentions in the site guides (E7).  A property explained to admins in a
    #: guide but missing from the defaults file is the strongest documentation
    #: candidate there is.
    doc_mentions: int = 0
    doc_first_seen: Optional[str] = None
    #: Accessors used to read the key - the value type an xml entry must match
    #: (getBoolean -> boolean, getTimeDuration -> a duration, ...).
    accessors: str = ""
    #: Default supplied at the call site when there is no DEFAULT_ constant.
    #: Only ever a *folded* value.  The raw expression is kept separately
    #: because it is often a local variable - the client allow-list keys
    #: default to whatever the matching server key resolved to - and writing
    #: that variable's name into an xml <value> would be a fabricated default.
    call_site_default: Optional[str] = None
    call_site_default_expr: Optional[str] = None
    #: Qualified name of the type declaring the constant.  The runner needs it
    #: to work out which classes a documentation patch must add to
    #: configurationClasses, since the comparison test fails otherwise.
    declaring_class: Optional[str] = None
    evidence: List[str] = field(default_factory=list)

    @property
    def value_type(self) -> str:
        used = [a for a in self.accessors.split(",") if a]
        for accessor, kind in (
                ("getBoolean", "boolean"), ("getTimeDuration", "duration"),
                ("getStorageSize", "size"), ("getInt", "int"), ("getLong", "long"),
                ("getFloat", "float"), ("getDouble", "double"),
                ("getClasses", "class names"), ("getClass", "class name"),
                ("getStrings", "comma-separated list"),
                ("getTrimmedStrings", "comma-separated list"),
                ("getPassword", "credential"), ("getEnum", "enum")):
            if any(accessor == u for u in used):
                return kind
        return "string" if used else ""

    @property
    def reads(self) -> int:
        return self.read_main + self.read_test

    @property
    def recommendation(self) -> str:
        return {
            ACTIVE_UNDOCUMENTED: "Add to the module's *-default.xml with a description",
            ACTIVE_DOCUMENTED: "None - already documented",
            DOCUMENTED_ELSEWHERE: "None - owned by another default xml",
            DYNAMIC_PATTERN: "Document as a pattern, or leave with an example entry",
            DEPRECATED_ALIAS: "Do not document; deprecated alias",
            DEPRECATED_CONSTANT: "Do not document; constant is @Deprecated",
            INTERNAL_SKIPLISTED: "Do not document; already justified in the test skip list",
            SKIPLISTED_CONTESTED: "Re-vet: the skip list's stated reason is "
                                  "contradicted by the code evidence",
            INTERNAL_PRIVATE: "Do not document; declared private/internal in source",
            TEST_ONLY: "Do not document; only used by tests",
            UNUSED: "Investigate: declared but never read",
            EXTERNAL: "Not HDFS's to document; declared in another project",
            NEEDS_REVIEW: "Human review required",
        }[self.status]


@dataclass
class Inventory:
    entries: Dict[str, Entry] = field(default_factory=dict)
    patterns: Dict[str, List[callsites_mod.CallSite]] = field(default_factory=dict)
    dynamic_sites: List[callsites_mod.CallSite] = field(default_factory=list)
    not_a_property: List[callsites_mod.CallSite] = field(default_factory=list)
    unresolved_sites: List[callsites_mod.CallSite] = field(default_factory=list)
    duplicate_xml: Dict[str, List[str]] = field(default_factory=dict)
    e6_only_keys: Set[str] = field(default_factory=set)
    literal_regressions: List[str] = field(default_factory=list)

    @property
    def contradicted_skips(self) -> List[Entry]:
        """Skip-list entries whose stated reason the evidence contradicts.

        These are classified SKIPLISTED_CONTESTED by ``_classify``:
        TestHdfsConfigFields excludes properties as deprecated ("Fully
        deprecated properties?" - written with a question mark, and never
        resolved) or removed ("Removed by HDFS-6440"), yet each is still
        read by production code and none appears in a DeprecationDelta
        table, so they are live, undocumented properties being hidden from
        the comparison under a false premise.
        """
        return self.by_status(SKIPLISTED_CONTESTED)

    def by_status(self, status: str) -> List[Entry]:
        return sorted((e for e in self.entries.values() if e.status == status),
                      key=lambda e: e.key)

    def status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.entries.values():
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts


_DURATION_UNITS = {"ns": 1e-6, "us": 1e-3, "ms": 1.0, "s": 1e3,
                   "m": 6e4, "h": 3.6e6, "d": 8.64e7}
_SIZE_UNITS = {"b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3,
               "t": 1024 ** 4, "p": 1024 ** 5}


def _numeric_forms(text: str) -> Set[float]:
    """Every value a Hadoop config string could denote.

    ``5m`` is 300000 as a duration and 5242880 as a storage size, and the same
    file writes ``0.75f`` for 0.75.  Comparing the raw strings reports dozens of
    mismatches that are only formatting, which buries the handful that are real.
    """
    text = (text or "").strip()
    match = re.fullmatch(r"(-?[\d.]+)\s*([A-Za-z]{1,2})?", text)
    if not match:
        return set()
    try:
        number = float(match.group(1))
    except ValueError:
        return set()
    unit = (match.group(2) or "").lower()
    if not unit or unit in ("f", "d", "l"):
        return {number}
    forms = set()
    if unit in _DURATION_UNITS:
        forms.add(number * _DURATION_UNITS[unit])
    if unit in _SIZE_UNITS:
        forms.add(number * _SIZE_UNITS[unit])
    return forms


def values_agree(xml_value: Optional[str], code_value: Optional[str]) -> bool:
    if xml_value is None or code_value is None:
        return True
    xml_value, code_value = xml_value.strip(), code_value.strip()
    if xml_value == code_value:
        return True
    if "${" in xml_value:
        return True  # xml substitution, resolved at runtime
    xml_forms, code_forms = _numeric_forms(xml_value), _numeric_forms(code_value)
    return bool(xml_forms & code_forms)


def _internal_marker(declaring) -> str:
    """Author-stated signals that a key is not a supported, documentable knob."""
    for annotation in getattr(declaring, "annotations", []):
        if "VisibleForTesting" in annotation:
            return "@VisibleForTesting"
    if declaring.name.startswith("INTERNAL_"):
        return "INTERNAL_ constant name"
    return ""


def _module_for(key: str, path: Optional[str]) -> str:
    if path:
        normalised = os.path.normpath(path)
        for spec in MODULES:
            # Match on a path boundary: "hadoop-hdfs-project/hadoop-hdfs" is a
            # string prefix of "hadoop-hdfs-project/hadoop-hdfs-rbf", so a bare
            # substring test files every RBF property under hdfs.
            prefix = os.path.normpath(spec.module_path.replace("/", os.sep)) + os.sep
            if prefix in normalised:
                return spec.key
        # Declared in hadoop-common (or another project): HDFS reads it, but
        # documenting it is not HDFS-11039's business.
        if not os.path.normpath(path).startswith(os.path.normpath("hadoop-hdfs-project")):
            return "external"
    if key.startswith("dfs.federation.router") or key.startswith("dfs.router"):
        return "rbf"
    if key.startswith(("nfs.", "dfs.nfs")):
        return "nfs"
    if key.startswith("httpfs."):
        return "httpfs"
    return "hdfs"


def build(ctx: ScanContext) -> Inventory:
    inv = Inventory()
    module_paths = {spec.key: spec.module_path for spec in MODULES}
    all_classes: List[str] = []
    for spec in MODULES:
        all_classes.extend(spec.config_classes)

    keys = e1_configkeys.extract(ctx.symtab, all_classes)
    literals = e2_literals.extract(ctx.repo, module_paths)
    deprecations = e4_deprecations.extract(
        ctx.symtab, [ctx.path(p) for p in DEPRECATION_SOURCES], all_classes)
    sites = callsites_mod.scan(ctx.symtab, ctx.repo, module_paths, include_tests=True)
    docs = e7_docs.extract(ctx.repo, DOC_ROOTS)

    # ---------------------------------------------------------------- xml
    documented: Dict[str, str] = {}
    xml_values: Dict[str, Optional[str]] = {}
    xml_files = list(dict.fromkeys(
        [m.xml_path for m in MODULES if m.xml_path] + OTHER_XML_FILES))
    for relative in xml_files:
        path = ctx.path(relative)
        if not os.path.isfile(path):
            continue
        extract = e3_xml.extract(path)
        if extract.duplicates:
            inv.duplicate_xml[relative] = extract.duplicates
        for prop in extract.properties:
            documented.setdefault(prop.name, relative)
            xml_values[prop.name] = prop.value

    # ------------------------------------------------------------- skips
    skip_reasons: Dict[str, str] = {}
    skipped: Set[str] = set()
    for spec in MODULES:
        if not spec.test_path:
            continue
        skips = e5_skiplists.extract(ctx.symtab, ctx.path(spec.test_path))
        for entry in skips.entries:
            skipped.add(entry.value)
            if entry.reason:
                skip_reasons.setdefault(entry.value, entry.reason)

    deprecated_map = deprecations.replacement_of()
    deprecated_constants = deprecations.deprecated_constants()

    # ------------------------------------------------------- collect keys
    literal_by_key = literals.by_key()
    sites_by_key = sites.by_key()
    universe = set(keys.keys) | literals.whole_keys() | set(sites_by_key)

    # E2 scans production sources only, so the coverage comparison must too -
    # otherwise every test-only key looks like a literal the scanner missed.
    forward = set(keys.keys) | literals.whole_keys()
    production_sites: Dict[str, List[callsites_mod.CallSite]] = {}
    for key, site_list in sites_by_key.items():
        kept = [s for s in site_list if not s.in_test]
        if kept:
            production_sites[key] = kept
    inv.e6_only_keys = set(production_sites) - forward
    for key in sorted(inv.e6_only_keys):
        # A key spelled as a plain literal at a production call site should have
        # been found by E2; anything else is E6 doing what only E6 can.
        if any('"' in (s.expr or "") for s in production_sites[key]):
            inv.literal_regressions.append(key)

    for key in universe:
        entry = Entry(key=key)
        record = keys.keys.get(key)
        key_sites = sites_by_key.get(key, [])
        lit_records = literal_by_key.get(key, [])

        # Declaration provenance: registered constant first, else whatever the
        # call-site sweep resolved, else the literal.
        if record is not None:
            entry.constant = record.constant
            entry.declared_at = f"{os.path.relpath(record.path, ctx.repo)}:{record.line}"
            entry.default_constant = record.default_constant
            entry.default_value = record.default_value
            field_decl = ctx.symtab.types.get(record.owner, None)
            declaring = None
            if field_decl is not None:
                declaring = field_decl.fields.get(record.constant)
            if declaring is not None:
                entry.visibility = declaring.visibility
                entry.declaring_comment = declaring.doc
                entry.internal_marker = _internal_marker(declaring)
                entry.declaring_class = declaring.owner_qname
            entry.evidence.append("E1 constant")
        else:
            declaring = next((s.key_field for s in key_sites if s.key_field), None)
            if declaring is not None:
                entry.constant = declaring.name
                entry.declared_at = (
                    f"{os.path.relpath(declaring.source_path, ctx.repo)}:{declaring.line}")
                entry.visibility = declaring.visibility
                entry.declaring_comment = declaring.doc
                entry.internal_marker = _internal_marker(declaring)
                entry.declaring_class = declaring.owner_qname
                entry.evidence.append("E6 constant outside registered classes")
            elif lit_records:
                first = lit_records[0]
                entry.declared_at = f"{os.path.relpath(first.path, ctx.repo)}:{first.line}"
                entry.evidence.append("E2 literal")

        entry.module = _module_for(key, entry.declared_at)
        entry.literal_sites = len(lit_records)
        entry.native_sites = sum(1 for r in lit_records if r.language == "native")

        entry.accessors = ",".join(sorted({s.accessor for s in key_sites if s.is_read}))
        entry.call_site_default = next(
            (s.inline_default_value for s in key_sites
             if s.is_read and s.inline_default_value is not None), None)
        entry.call_site_default_expr = next(
            (s.inline_default for s in key_sites if s.is_read and s.inline_default), None)

        for site in key_sites:
            if site.is_write:
                if site.in_test:
                    entry.write_test += 1
                else:
                    entry.write_main += 1
            else:
                if site.in_test:
                    entry.read_test += 1
                else:
                    entry.read_main += 1

        entry.documented_in = documented.get(key)
        entry.xml_value = xml_values.get(key)
        if entry.default_value is not None and entry.xml_value is not None:
            if entry.xml_value.strip() and not values_agree(entry.xml_value,
                                                            entry.default_value):
                entry.default_conflict = (
                    f"xml={entry.xml_value.strip()!r} vs "
                    f"{entry.default_constant}={entry.default_value.strip()!r}")

        if key in deprecated_map:
            entry.deprecated_to = ", ".join(deprecated_map[key]) or "(removed)"
        entry.deprecated_constant = key in deprecated_constants
        entry.skip_reason = skip_reasons.get(key)
        entry.doc_mentions = docs.count(key)
        first = docs.first(key)
        if first is not None:
            entry.doc_first_seen = (
                f"{os.path.relpath(first.path, ctx.repo)}:{first.line}")

        entry.status = _classify(entry, key, skipped, deprecated_map, deprecated_constants)
        inv.entries[key] = entry

    # -------------------------------------------------------- non-key sites
    for site in sites.of_resolution("pattern"):
        inv.patterns.setdefault(site.pattern or "?", []).append(site)
    inv.dynamic_sites = sites.of_resolution("dynamic")
    inv.not_a_property = sites.of_resolution("not-a-property")
    inv.unresolved_sites = sites.of_resolution("unresolved")
    return inv


def _skip_reason_contested(entry: Entry) -> bool:
    """Whether a skip-list reason makes a factual claim the evidence refutes.

    Skip reasons split into two kinds.  *Intent* claims ("Property not
    intended for users", "Purposely hidden") are the author's judgement; no
    scan can falsify them, so they are trusted as-is.  *Fact* claims assert
    something checkable: a reason ending in "?" is openly unsure, and one
    saying deprecated/removed predicts that the property appears in a
    DeprecationDelta table, carries a @Deprecated constant, or is no longer
    read.  When such a claim is contradicted on every count - the property
    is read by production code, maps to no delta, and has no deprecated
    constant - the entry needs a human decision, not silent burial.
    """
    reason = (entry.skip_reason or "").strip()
    low = reason.lower()
    claims_fact = low.endswith("?") or "deprecat" in low or "removed" in low
    if not claims_fact:
        return False
    if entry.deprecated_to or entry.deprecated_constant:
        return False  # the deprecation claim holds up
    return entry.read_main > 0 and not entry.documented_in


def _classify(entry: Entry, key: str, skipped: Set[str],
              deprecated_map: Dict[str, List[str]], deprecated_constants) -> str:
    """Assign one status.  Order matters: earlier rules are stronger evidence.

    Documentation status is decided before any "should we document it?"
    reasoning, because those signals are moot once a property is documented.
    In particular a ``@Deprecated`` *constant* must not outrank documentation:
    DFSConfigKeys marks 73 constants deprecated purely because they moved to
    HdfsClientConfigKeys ("dfs.client.block.write confs are moved to
    HdfsClientConfigKeys.BlockWrite") while the properties themselves remain
    live and documented.
    """
    if key in deprecated_map:
        # A deprecated *name* still documented in an xml is a defect worth
        # surfacing, so this outranks the documentation check.
        entry.evidence.append("E4 DeprecationDelta")
        return DEPRECATED_ALIAS

    if entry.documented_in:
        spec = MODULES_BY_KEY.get(entry.module)
        owns = spec is not None and spec.documentation_xml == entry.documented_in
        entry.evidence.append(f"E3 documented in {os.path.basename(entry.documented_in)}")
        return ACTIVE_DOCUMENTED if owns else DOCUMENTED_ELSEWHERE

    # Undocumented from here on: decide whether it deserves documenting.
    if entry.module == "external":
        entry.evidence.append("declared outside hadoop-hdfs-project")
        return EXTERNAL
    if key.startswith(_FOREIGN_NAMESPACES):
        entry.evidence.append("namespace belongs to another component")
        return EXTERNAL

    if key in skipped:
        entry.evidence.append("E5 skip list")
        if _skip_reason_contested(entry):
            entry.evidence.append(
                f"skip reason {entry.skip_reason!r} contradicted: "
                f"{entry.read_main} production read(s), no DeprecationDelta, "
                "no @Deprecated constant")
            return SKIPLISTED_CONTESTED
        return INTERNAL_SKIPLISTED

    if key in deprecated_constants:
        entry.evidence.append("E4 @Deprecated constant, and undocumented")
        return DEPRECATED_CONSTANT

    comment = (entry.declaring_comment or "").lower()
    if any(marker in comment for marker in _PRIVATE_MARKERS):
        entry.evidence.append("declared under an internal/private comment")
        return INTERNAL_PRIVATE

    if entry.internal_marker:
        entry.evidence.append(f"declared {entry.internal_marker}")
        return INTERNAL_PRIVATE

    if key[:1].isupper():
        # Hadoop property names are lower-case dotted; a leading capital means
        # something else, e.g. FileSystemAccessService.created, an internal
        # service flag rather than a user-facing knob.
        entry.evidence.append("name does not follow Hadoop property conventions")
        return NEEDS_REVIEW

    writes = entry.write_main + entry.write_test
    # A declaration literal is not usage, so it does not count as production
    # evidence - only an actual read or write in main code does.
    production = entry.read_main + entry.write_main + entry.native_sites

    if entry.reads == 0 and writes == 0 and entry.literal_sites == 0:
        entry.evidence.append("no read, write or literal site found")
        return UNUSED
    if production == 0 and (entry.read_test or entry.write_test):
        entry.evidence.append("only referenced from tests")
        return TEST_ONLY
    if entry.reads == 0 and writes > 0:
        entry.evidence.append("only ever written, never read")
        return INTERNAL_PRIVATE
    if entry.read_main == 0 and entry.read_test > 0:
        entry.evidence.append("read only from tests")
        return TEST_ONLY
    if entry.visibility == "package-private" and entry.read_main > 0:
        entry.evidence.append("package-private declaration")
        return INTERNAL_PRIVATE
    if entry.read_main > 0 or entry.native_sites > 0:
        entry.evidence.append("read from production code, absent from every default xml")
        if entry.doc_mentions:
            entry.evidence.append(
                f"E7 explained in the site guides ({entry.doc_mentions} mention(s)) "
                "but missing from the defaults file")
        return ACTIVE_UNDOCUMENTED
    return NEEDS_REVIEW
