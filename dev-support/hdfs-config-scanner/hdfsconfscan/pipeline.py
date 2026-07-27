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
"""The M1-M5 process as a runnable pipeline.

    python scan.py pipeline                       # analyse, then run the real tests
    python scan.py pipeline --skip-maven          # analysis only, ~30 seconds
    python scan.py pipeline --apply --java-only   # also write the ready batches

Which stages need a human:

* **M1, M2** - none. They read the tree and validate themselves.
* **M3** - none to *run*, but its output is partly blocked: properties with no
  Javadoc and no guide text get a TODO instead of an invented description, and
  those batches cannot be upstreamed until someone writes the text.
* **M4** - two things. It only writes with an explicit ``--apply`` (it edits
  tracked Hadoop files), and it only touches batches whose descriptions all
  exist. Placement inside each xml is a judgement call, so anchors are declared
  in ``PLACEMENTS`` rather than guessed.

* **M5** - a JDK and Maven. It runs Hadoop's real TestHdfsConfigFields and
  TestRBFConfigFields, which is what turns the oracle's prediction into a
  result. It runs by default; ``--skip-maven`` drops back to analysis only.

Every applied batch is verified immediately: the oracle must still pass, and a
batch that breaks it is rolled back rather than left half-applied.  M5 then
checks the same thing for real.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import assess, callsites, context as context_mod, inventory, mvntest, oracle, report
from .context import ScanContext
from .registry import MODULES, MODULES_BY_KEY


@dataclass
class Placement:
    """Where a batch's properties belong, and in which file."""
    module: str
    anchor: str
    #: Per-key anchor overrides, for properties that belong beside a sibling.
    key_anchors: Dict[str, str] = field(default_factory=dict)


#: Insertion points chosen so each property lands beside its relatives - the
#: allow-list keys next to dfs.trustedchannel.resolver.class, whose resolver
#: implementations they configure. Reviewers read diffs in context, and an
#: alphabetical dump at the end of the file reads as noise.
PLACEMENTS: Dict[str, Placement] = {
    "datatransfer-allowlists": Placement("hdfs", "dfs.trustedchannel.resolver.class"),
    "webhdfs-oauth2": Placement("hdfs", "dfs.webhdfs.oauth2.access.token.provider"),
    "ha-tail-edits": Placement("hdfs", "dfs.ha.tail-edits.in-progress"),
    "namenode-misc": Placement("hdfs", "dfs.namenode.edits.dir"),
    "client-misc": Placement("hdfs", "dfs.client.read.shortcircuit"),
    "nfs-gateway": Placement("hdfs", "nfs.exports.allowed.hosts"),
    "httpfs": Placement("httpfs", "httpfs.buffer.size"),
    "rbf-router": Placement(
        "rbf", "dfs.federation.router.store.driver.class",
        key_anchors={
            "dfs.federation.router.store.driver.file.directory":
                "dfs.federation.router.store.driver.file.async.threads",
            "dfs.federation.router.store.driver.fs.path":
                "dfs.federation.router.store.driver.fs.async.threads",
        }),
    "rbf-sql-secret-manager": Placement("rbf", "dfs.federation.router.secret.manager.class"),
    "rbf-state-store-mysql": Placement("rbf", "dfs.federation.router.store.driver.class"),
    "rbf-zk-secret-manager": Placement("rbf", "dfs.federation.router.store.driver.zk.address"),
}


@dataclass
class StageResult:
    name: str
    title: str
    ok: bool = True
    lines: List[str] = field(default_factory=list)
    #: Things a human must supply before the pipeline can go further.
    blocked: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    #: What the stage computed - oracle results, the inventory, assessment
    #: stats.  Carried so that the individual commands can render the same
    #: computation more verbosely instead of recomputing it their own way,
    #: which is how the runner and the step-by-step commands would drift.
    payload: object = None

    def say(self, text: str) -> None:
        self.lines.append(text)


# --------------------------------------------------------------------- stages

def stage_m1(ctx: ScanContext) -> StageResult:
    """Static extraction, validated against Hadoop's own comparison tests."""
    result = StageResult("M1", "static extraction (E1-E5)")
    outcomes = []
    result.payload = outcomes
    for spec in MODULES:
        if not spec.has_comparison_test:
            continue
        outcome = oracle.run_module(ctx, spec)
        outcomes.append(outcome)
        result.say(f"oracle {spec.key}: {'PASS' if outcome.ok else 'FAIL'} "
                   f"({outcome.compared_config_count} constants vs "
                   f"{outcome.compared_xml_count} xml properties compared)")
        if not outcome.ok:
            result.ok = False
            for key in outcome.missing_in_xml[:10]:
                result.say(f"    constant not in xml: {key}")
            for key in outcome.missing_in_config[:10]:
                result.say(f"    xml property with no constant: {key}")
    return result


def stage_m2(ctx: ScanContext, out_dir: str) -> StageResult:
    """Call-site sweep, usage analysis and the classified inventory."""
    result = StageResult("M2", "call-site sweep + inventory (E6)")
    module_paths = {spec.key: spec.module_path for spec in MODULES}
    sites = callsites.scan(ctx.symtab, ctx.repo, module_paths, include_tests=False)

    counts: Dict[str, int] = {}
    for site in sites.sites:
        counts[site.resolution] = counts.get(site.resolution, 0) + 1
    unresolved = counts.get("unresolved", 0)
    result.say(f"{len(sites.sites)} production call sites: "
               + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if unresolved:
        result.ok = False
        result.say(f"    {unresolved} call sites could not be parsed")

    inv = inventory.build(ctx)
    result.payload = inv
    if inv.literal_regressions:
        result.ok = False
        result.say(f"    {len(inv.literal_regressions)} plain-literal keys missed by E2")

    os.makedirs(out_dir, exist_ok=True)
    report.write_csv(inv, os.path.join(out_dir, "hdfs-config-inventory.csv"))
    report.write_markdown(inv, os.path.join(out_dir, "hdfs-config-inventory.md"), ctx.repo)
    counts_by_status = inv.status_counts()
    result.say(f"{sum(counts_by_status.values())} properties classified; "
               f"{counts_by_status.get(inventory.ACTIVE_UNDOCUMENTED, 0)} undocumented")
    if counts_by_status.get(inventory.NEEDS_REVIEW):
        result.blocked.append(
            f"{counts_by_status['NEEDS_REVIEW']} properties are NEEDS_REVIEW - a human "
            "must decide whether each is a real property")
    return result


def stage_m3(ctx: ScanContext, inv: inventory.Inventory, out_dir: str) -> StageResult:
    """Recommendations and proposed xml, with descriptions derived from evidence."""
    result = StageResult("M3", "assessment + proposed xml (E7)")
    md = os.path.join(out_dir, "hdfs-11039-assessment.md")
    xml = os.path.join(out_dir, "hdfs-11039-proposed-additions.xml")
    stats = assess.write_assessment(inv, ctx.repo, md, xml)
    result.payload = stats
    result.say(f"{stats['total']} candidates across {stats['batches']} batches; "
               f"{stats['described']} descriptions derived, {stats['todo']} TODO")
    if stats["todo"]:
        result.blocked.append(
            f"{stats['todo']} properties have no Javadoc and no guide text; a description "
            "must come from someone who knows the subsystem before their batch can ship")
    return result


def stage_m4(ctx: ScanContext, inv: inventory.Inventory, apply_changes: bool) -> StageResult:
    """Apply the batches that are ready, verifying each one immediately."""
    result = StageResult("M4", "apply documentation batches")
    proposals = assess.build_proposals(inv, ctx.repo)
    by_batch: Dict[str, List[assess.Proposal]] = {}
    for proposal in proposals:
        by_batch.setdefault(proposal.batch, []).append(proposal)

    if not by_batch:
        result.say("nothing left to apply - every candidate is documented")
        return result

    for batch in sorted(by_batch):
        items = by_batch[batch]
        todo = [p for p in items if p.needs_author]
        if todo:
            result.say(f"{batch}: SKIP - {len(todo)}/{len(items)} need a description author")
            result.blocked.append(f"{batch}: {len(todo)} descriptions to write")
            continue
        placement = PLACEMENTS.get(batch)
        if placement is None:
            result.say(f"{batch}: SKIP - no insertion point declared in PLACEMENTS")
            result.blocked.append(f"{batch}: choose where in the xml these belong")
            continue
        if not apply_changes:
            result.say(f"{batch}: READY - {len(items)} properties "
                       f"(dry run; pass --apply to write)")
            continue
        applied = _apply_batch(ctx, batch, items, placement, result)
        result.say(f"{batch}: {'APPLIED' if applied else 'ROLLED BACK'} "
                   f"({len(items)} properties)")
        if not applied:
            result.ok = False
    return result


def stage_m5(ctx: ScanContext, build_deps: bool = False, timeout: int = 3600,
             extra_args: Optional[List[str]] = None) -> StageResult:
    """Run Hadoop's real comparison tests.

    The oracle predicts these; this is the prediction being checked.  A missing
    JDK or Maven is reported as a failure to *verify*, never as a pass - the
    whole point is not to claim a green test that never ran.
    """
    result = StageResult("M5", "verify with Hadoop's own tests (maven)")
    problem = mvntest.toolchain_problem()
    if problem:
        result.ok = False
        result.say(f"cannot run the tests: {problem}")
        result.blocked.append(f"install the toolchain to verify for real: {problem}")
        return result

    specs = [spec for spec in MODULES if spec.has_comparison_test]
    outcomes = mvntest.run(ctx.repo, specs, build_deps=build_deps, timeout=timeout,
                           extra_args=extra_args)
    result.payload = outcomes
    for outcome in outcomes:
        result.say(f"{outcome.test_class.rsplit('.', 1)[-1]}: {outcome.summary}")
        for line in outcome.detail[:8]:
            result.say(f"    {line}")
        if not outcome.ok:
            result.ok = False
    return result


# ---------------------------------------------------------------- apply logic

def _restyle(block: str, indent: int) -> str:
    """hdfs-default.xml puts <property> at column 0; hdfs-rbf-default.xml at 2."""
    if indent == 2:
        return block
    return "\n".join(line[2:] if line.startswith("  ") else line
                     for line in block.splitlines())


def _insert_property(text: str, anchor: str, block: str) -> str:
    marker = f"<name>{anchor}</name>"
    index = text.index(marker)
    close = text.index("</property>", index) + len("</property>")
    return text[:close] + "\n\n" + block + text[close:]


def _add_classes_to_test(text: str, qnames: List[str]) -> str:
    """Add imports and extend configurationClasses.

    Required, not optional: the comparison test runs with
    errorIfMissingConfigProps = true, so a new xml property whose constant is
    not in this array fails the build.
    """
    for qname in sorted(set(qnames)):
        simple = qname.split(".")[-1]
        if f"import {qname};" not in text:
            imports = list(re.finditer(r"^import .*?;$", text, re.M))
            last = imports[-1]
            text = text[:last.end()] + f"\nimport {qname};" + text[last.end():]
        if re.search(rf"\b{re.escape(simple)}\.class\b", text):
            continue
        match = re.search(r"(configurationClasses\s*=\s*new\s+Class\s*\[\s*\]\s*\{)(.*?)(\}\s*;)",
                          text, re.S)
        if match is None:
            continue
        body = match.group(2).rstrip()
        text = (text[:match.start(2)] + body + f",\n        {simple}.class\n    "
                + text[match.end(2):])
    return text


def _apply_batch(ctx: ScanContext, batch: str, items: List[assess.Proposal],
                 placement: Placement, result: StageResult) -> bool:
    spec = MODULES_BY_KEY[placement.module]
    xml_rel = spec.documentation_xml or spec.xml_path
    xml_path = ctx.path(xml_rel)
    test_path = ctx.path(spec.test_path) if spec.test_path else None

    originals = {xml_path: _read(xml_path)}
    if test_path:
        originals[test_path] = _read(test_path)

    indent = 2 if placement.module == "rbf" else 0
    text = originals[xml_path]
    for proposal in sorted(items, key=lambda p: p.entry.key):
        key = proposal.entry.key
        if f"<name>{key}</name>" in text:
            continue  # already documented; keep the run idempotent
        anchor = placement.key_anchors.get(key, placement.anchor)
        block = _restyle("\n".join(assess._xml_block(proposal)), indent)
        try:
            text = _insert_property(text, anchor, block)
        except ValueError:
            result.say(f"    anchor {anchor!r} not found for {key}")
            _restore(originals)
            return False
    _write(xml_path, text)

    if test_path:
        classes = [p.entry.declaring_class for p in items if p.entry.declaring_class]
        if classes:
            _write(test_path, _add_classes_to_test(originals[test_path], classes))

    # The symbol table caches every file it parses, so re-checking through
    # `ctx` would read the test exactly as it was before the classes were
    # added and report a failure that is not real.  Verification uses a fresh
    # context that sees what is now on disk.
    outcome = None
    if spec.has_comparison_test:
        outcome = oracle.run_module(context_mod.build(ctx.repo), spec)
    if outcome is not None and not outcome.ok:
        result.say(f"    oracle failed after {batch}; rolling back")
        for key in (outcome.missing_in_config[:5] + outcome.missing_in_xml[:5]):
            result.say(f"      {key}")
        _restore(originals)
        return False

    result.changed_files.extend(os.path.relpath(p, ctx.repo) for p in originals)
    return True


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _restore(originals: Dict[str, str]) -> None:
    for path, text in originals.items():
        _write(path, text)


# ------------------------------------------------------------------- driver

def run(ctx: ScanContext, out_dir: str, apply_changes: bool = False,
        stop_after: Optional[str] = None, maven: bool = True,
        build_deps: bool = False, mvn_timeout: int = 3600,
        mvn_args: Optional[List[str]] = None) -> List[StageResult]:
    results: List[StageResult] = []

    m1 = stage_m1(ctx)
    results.append(m1)
    if not m1.ok or stop_after == "M1":
        return results

    m2 = stage_m2(ctx, out_dir)
    results.append(m2)
    if not m2.ok or stop_after == "M2":
        return results
    inv = m2.payload

    m3 = stage_m3(ctx, inv, out_dir)
    results.append(m3)
    if stop_after == "M3":
        return results

    results.append(stage_m4(ctx, inv, apply_changes))
    if stop_after == "M4":
        return results

    # M5 runs by default: a prediction that is never checked is the thing this
    # milestone exists to remove.  It can be turned off for a quick analysis
    # pass, since a cold Maven build is slow.
    if maven:
        results.append(stage_m5(ctx, build_deps=build_deps, timeout=mvn_timeout,
                                extra_args=mvn_args))
    return results
