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
"""Command line entry point for the HDFS configuration scanner.

    python scan.py oracle              validate the scanner against the tests
    python scan.py keys --module hdfs  dump extracted key constants (E1)
    python scan.py literals            dump literal keys found in sources (E2)
    python scan.py xml --module hdfs   dump documented properties (E3)
    python scan.py deprecations        dump deprecated names (E4)
    python scan.py skips --module hdfs dump skip lists with their reasons (E5)
    python scan.py summary             extractor totals and the raw gap
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hdfsconfscan import (  # noqa: E402
    assess, callsites, context, dossier, e1_configkeys, e2_literals, e3_xml,
    e4_deprecations, e5_skiplists, inventory, mvntest, oracle, pipeline, report,
)
from hdfsconfscan.registry import (  # noqa: E402
    DEPRECATION_SOURCES, MODULES, MODULES_BY_KEY, OTHER_XML_FILES,
)

DEFAULT_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _module(name: str):
    if name not in MODULES_BY_KEY:
        raise SystemExit(f"unknown module '{name}'; choose from "
                         f"{', '.join(sorted(MODULES_BY_KEY))}")
    return MODULES_BY_KEY[name]


def cmd_oracle(args) -> int:
    """Step M1, rendered per module.

    Runs pipeline.stage_m1 rather than its own loop, so `scan.py oracle` and
    `scan.py pipeline` can never disagree about whether M1 passed.
    """
    ctx = context.build(args.repo)
    stage = pipeline.stage_m1(ctx)
    results = stage.payload or []
    if args.module:
        wanted = _module(args.module).key
        results = [r for r in results if r.module_key == wanted]
    failures = 0
    for result in results:
        print(oracle.format_result(result))
        print()
        if not result.ok:
            failures += 1
    if failures:
        print(f"{failures} module(s) failed self-validation - fix the scanner before "
              f"trusting its output.")
    else:
        print("Self-validation passed: extraction reproduces the Java tests exactly.")
    return 1 if failures else 0


def cmd_keys(args) -> int:
    ctx = context.build(args.repo)
    spec = _module(args.module)
    extract = e1_configkeys.extract(ctx.symtab, spec.config_classes)
    if args.json:
        payload = {
            "keys": {key: vars(record) for key, record in extract.keys.items()},
            "partial": [vars(record) for record in extract.partial],
            "unresolved": extract.unresolved,
            "rejected": extract.rejected,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for key in sorted(extract.keys):
        record = extract.keys[key]
        default = f" = {record.default_value}" if record.default_constant else ""
        flag = " [deprecated]" if record.deprecated else ""
        print(f"{key}{default}{flag}")
        print(f"    {record.owner.split('.')[-1]}.{record.constant} "
              f"({os.path.relpath(record.path, ctx.repo)}:{record.line})")
    print(f"\n{len(extract.keys)} keys, {len(extract.partial)} partial constants, "
          f"{len(extract.unresolved)} unresolved, {len(extract.rejected)} rejected")
    return 0


def cmd_xml(args) -> int:
    ctx = context.build(args.repo)
    spec = _module(args.module)
    if not spec.xml_path:
        raise SystemExit(f"module '{spec.key}' has no default xml file")
    extract = e3_xml.extract(ctx.path(spec.xml_path))
    for prop in extract.properties:
        marker = " (empty)" if prop.empty_value else ""
        print(f"{prop.name}{marker}  [{os.path.basename(prop.path)}:{prop.line}]")
    print(f"\n{len(extract.properties)} properties, "
          f"{len(extract.duplicates)} duplicated: {', '.join(extract.duplicates)}")
    return 0


def cmd_skips(args) -> int:
    ctx = context.build(args.repo)
    spec = _module(args.module)
    if not spec.test_path:
        raise SystemExit(f"module '{spec.key}' has no comparison test")
    skips = e5_skiplists.extract(ctx.symtab, ctx.path(spec.test_path))
    for entry in skips.entries:
        print(f"{entry.target:34s} {entry.value}")
        if entry.reason:
            print(f"{'':34s}   reason: {entry.reason}")
    print(f"\n{len(skips.entries)} entries, {len(skips.unresolved)} unresolved")
    return 0


def _all_documented(ctx):
    """Every property documented in any default xml, mapped to its file."""
    documented = {}
    paths = [m.xml_path for m in MODULES if m.xml_path] + OTHER_XML_FILES
    for relative in paths:
        path = ctx.path(relative)
        if not os.path.isfile(path):
            continue
        for prop in e3_xml.extract(path).properties:
            documented.setdefault(prop.name, relative)
    return documented


def _module_paths():
    return {spec.key: spec.module_path for spec in MODULES}


def cmd_literals(args) -> int:
    ctx = context.build(args.repo)
    extract = e2_literals.extract(ctx.repo, _module_paths(), include_tests=args.include_tests)
    grouped = extract.by_key()
    for key in sorted(grouped):
        records = grouped[key]
        sites = ", ".join(sorted({r.module for r in records}))
        accessors = sorted({r.accessor for r in records if r.accessor})
        detail = f" via {', '.join(accessors)}" if accessors else ""
        print(f"{key}  [{len(records)} site(s); {sites}]{detail}")
        if args.verbose:
            for record in records:
                print(f"    {os.path.relpath(record.path, ctx.repo)}:{record.line}"
                      + (f"  default={record.inline_default}" if record.inline_default else ""))
    print(f"\n{len(grouped)} distinct literal keys across {len(extract.records)} sites")
    return 0


def cmd_deprecations(args) -> int:
    ctx = context.build(args.repo)
    spec = MODULES_BY_KEY["hdfs"]
    classes = list(spec.config_classes) + MODULES_BY_KEY["nfs"].config_classes
    extract = e4_deprecations.extract(
        ctx.symtab, [ctx.path(p) for p in DEPRECATION_SOURCES], classes)
    for record in extract.records:
        if record.kind == "DeprecationDelta":
            print(f"{record.old_key}  ->  {', '.join(record.new_keys) or '(removed)'}")
        else:
            print(f"{record.old_key}  [@Deprecated {record.constant}]")
    print(f"\n{len(extract.old_keys())} deprecated aliases, "
          f"{len(extract.deprecated_constants())} @Deprecated constants, "
          f"{len(extract.unresolved)} unresolved")
    return 0


def _source_line(cache, path: str, line: int) -> str:
    if path not in cache:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                cache[path] = handle.readlines()
        except OSError:
            cache[path] = []
    lines = cache[path]
    return lines[line - 1] if 0 < line <= len(lines) else ""


def cmd_verify(args) -> int:
    """Check that every extracted record points at real evidence.

    The oracle proves the *key sets* are right; this proves each record's
    provenance is right, so a reviewer following a file:line always lands on
    the declaration being claimed.
    """
    ctx = context.build(args.repo)
    cache = {}
    problems = []
    checked = 0

    all_classes = []
    for spec in MODULES:
        all_classes.extend(spec.config_classes)
    keys = e1_configkeys.extract(ctx.symtab, all_classes)
    for record in keys.keys.values():
        checked += 1
        text = _source_line(cache, record.path, record.line)
        if record.constant not in text:
            problems.append(f"E1 {record.key}: constant {record.constant} not at "
                            f"{os.path.relpath(record.path, ctx.repo)}:{record.line}")

    literals = e2_literals.extract(ctx.repo, _module_paths())
    for record in literals.records:
        checked += 1
        text = _source_line(cache, record.path, record.line)
        if record.key not in text:
            problems.append(f"E2 {record.key}: literal not at "
                            f"{os.path.relpath(record.path, ctx.repo)}:{record.line}")

    for spec in MODULES:
        if not spec.xml_path:
            continue
        path = ctx.path(spec.xml_path)
        if not os.path.isfile(path):
            continue
        for prop in e3_xml.extract(path).properties:
            checked += 1
            text = _source_line(cache, prop.path, prop.line)
            if prop.name not in text:
                problems.append(f"E3 {prop.name}: name not at "
                                f"{os.path.basename(prop.path)}:{prop.line}")

    print(f"Provenance check: {checked} records, {len(problems)} mismatched")
    for problem in problems[:40]:
        print(f"  {problem}")
    if not problems:
        print("Every record's file:line contains the declaration it claims.")
    return 1 if problems else 0


def cmd_summary(args) -> int:
    ctx = context.build(args.repo)
    documented = _all_documented(ctx)

    all_classes = []
    for spec in MODULES:
        all_classes.extend(spec.config_classes)
    keys = e1_configkeys.extract(ctx.symtab, all_classes)
    literals = e2_literals.extract(ctx.repo, _module_paths())
    deprecations = e4_deprecations.extract(
        ctx.symtab, [ctx.path(p) for p in DEPRECATION_SOURCES], all_classes)

    literal_keys = literals.whole_keys()
    constant_keys = set(keys.keys)
    deprecated = deprecations.old_keys() | set(deprecations.deprecated_constants())

    print("Extractor totals")
    print(f"  E1 constants     : {len(constant_keys)} keys "
          f"({len(keys.partial)} partial, {len(keys.unresolved)} unresolved)")
    print(f"  E2 literals      : {len(literal_keys)} distinct keys "
          f"in {len(literals.records)} sites "
          f"({len(literals.fragment_only_keys())} concat fragments excluded)")
    print(f"  E3 documented    : {len(documented)} properties across "
          f"{len(set(documented.values()))} xml files")
    print(f"  E4 deprecated    : {len(deprecated)} names")
    print()

    undocumented_constants = sorted(constant_keys - set(documented))
    literal_only = sorted(literal_keys - constant_keys)
    literal_only_undocumented = [k for k in literal_only if k not in documented]
    literal_undoc_active = [k for k in literal_only_undocumented if k not in deprecated]

    print("Raw gap (classification happens in M2)")
    print(f"  constants not in any xml            : {len(undocumented_constants)}")
    print(f"  literal-only keys (not constants)   : {len(literal_only)}")
    print(f"  ... of those, in no xml             : {len(literal_only_undocumented)}")
    print(f"  ... and not a known deprecated name : {len(literal_undoc_active)}")
    print()
    print("Candidates for hdfs-default.xml (undocumented, not deprecated, not a constant):")
    grouped = literals.by_key()
    for key in literal_undoc_active:
        record = grouped[key][0]
        print(f"  {key}")
        print(f"      {os.path.relpath(record.path, ctx.repo)}:{record.line}"
              + (f"  ({record.accessor})" if record.accessor else ""))
    return 0


def cmd_sweep(args) -> int:
    """E6: account for every configuration accessor call site."""
    ctx = context.build(args.repo)
    sites = callsites.scan(ctx.symtab, ctx.repo, _module_paths(), include_tests=False)
    counts = {}
    for site in sites.sites:
        counts[site.resolution] = counts.get(site.resolution, 0) + 1

    print(f"Accessor call sites in production code: {len(sites.sites)}")
    for name in ("exact", "pattern", "dynamic", "not-a-property", "unresolved"):
        print(f"  {name:16s} {counts.get(name, 0)}")
    print()

    families = sorted({s.pattern for s in sites.of_resolution("pattern") if s.pattern})
    print(f"Dynamic key families ({len(families)}) - not enumerable by any forward scan:")
    for prefix in families:
        print(f"  {prefix}")
    print()

    dynamic = sites.of_resolution("dynamic")
    print(f"Worklist: {len(dynamic)} sites compute their key at runtime")
    if args.verbose:
        for site in dynamic:
            print(f"  {site.expr[:60]:62s} {os.path.relpath(site.path, ctx.repo)}:{site.line}")

    suspicious = sites.of_resolution("not-a-property")
    if suspicious:
        print()
        print(f"Suspicious ({len(suspicious)}): key argument resolved to a non-property")
        for site in suspicious:
            print(f"  {site.expr} = {site.resolved_value!r} via {site.accessor}")
            print(f"      {os.path.relpath(site.path, ctx.repo)}:{site.line}")

    unresolved = sites.of_resolution("unresolved")
    print()
    if unresolved:
        print(f"FAIL {len(unresolved)} call sites could not be parsed:")
        for site in unresolved[:20]:
            print(f"  {site.expr[:70]}  {os.path.relpath(site.path, ctx.repo)}:{site.line}")
        return 1
    print("Every accessor call site is accounted for.")
    return 0


def cmd_inventory(args) -> int:
    """Step M2, rendered as a status breakdown (same computation as pipeline)."""
    ctx = context.build(args.repo)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    inv = pipeline.stage_m2(ctx, out_dir).payload
    csv_path = os.path.join(out_dir, "hdfs-config-inventory.csv")
    md_path = os.path.join(out_dir, "hdfs-config-inventory.md")

    counts = inv.status_counts()
    print(f"{sum(counts.values())} properties classified")
    for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status:24s} {count}")
    print()
    print(f"keys reachable only via the call-site sweep : {len(inv.e6_only_keys)}")
    print(f"plain-literal keys missed by E2 (must be 0) : {len(inv.literal_regressions)}")
    print(f"dynamic key families                        : {len(inv.patterns)}")
    print()
    print(f"wrote {os.path.relpath(csv_path, ctx.repo)}")
    print(f"wrote {os.path.relpath(md_path, ctx.repo)}")
    return 1 if inv.literal_regressions else 0


def cmd_mvntest(args) -> int:
    """Run Hadoop's real comparison tests through Maven."""
    ctx = context.build(args.repo)
    problem = mvntest.toolchain_problem()
    if problem:
        print(f"Cannot run the tests: {problem}")
        print("The oracle only predicts these tests; without a toolchain that "
              "prediction stays unverified.")
        return 1
    specs = [s for s in MODULES if s.has_comparison_test]
    if args.module:
        specs = [s for s in specs if s.key == args.module]
    failures = 0
    extra = mvntest.extra_args(java_only=args.java_only,
                               skip_native_win=args.skip_native_win,
                               mvn_arg=args.mvn_arg)
    for outcome in mvntest.run(ctx.repo, specs, build_deps=args.build_deps,
                               timeout=args.timeout, verbose=args.verbose,
                               extra_args=extra):
        print(f"{outcome.test_class}")
        print(f"    {outcome.summary}")
        for line in outcome.detail:
            print(f"        {line}")
        if not outcome.ok:
            failures += 1
    print()
    print("All comparison tests passed." if not failures
          else f"{failures} test class(es) did not pass.")
    return 1 if failures else 0


def cmd_step(args) -> int:
    """Run one step of the process, using the very same code the runner uses."""
    ctx = context.build(args.repo)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)

    if args.name == "M1":
        stages = [pipeline.stage_m1(ctx)]
    elif args.name == "M2":
        stages = [pipeline.stage_m2(ctx, out_dir)]
    elif args.name == "M3":
        inv = pipeline.stage_m2(ctx, out_dir).payload
        stages = [pipeline.stage_m3(ctx, inv, out_dir)]
    elif args.name == "M4":
        inv = pipeline.stage_m2(ctx, out_dir).payload
        stages = [pipeline.stage_m4(ctx, inv, args.apply)]
    else:
        stages = [pipeline.stage_m5(
            ctx, build_deps=args.build_deps, timeout=args.timeout,
            extra_args=mvntest.extra_args(java_only=args.java_only,
                                          skip_native_win=args.skip_native_win,
                                          mvn_arg=args.mvn_arg))]
    return _render_stages(stages, applied=args.apply)


def _render_stages(results, applied: bool) -> int:
    blocked, changed, failed = [], [], []
    for stage in results:
        print(f"[{stage.name}] {stage.title} - {'ok' if stage.ok else 'FAILED'}")
        for line in stage.lines:
            print(f"    {line}")
        print()
        blocked.extend(stage.blocked)
        changed.extend(stage.changed_files)
        if not stage.ok:
            failed.append(stage.name)

    if changed:
        print("Files changed:")
        for path in sorted(set(changed)):
            print(f"    {path}")
        print()
    if blocked:
        print("Needs a human:")
        for item in blocked:
            print(f"    - {item}")
        print()
    if not applied:
        # Deliberately not "nothing was written": M5 runs Maven, which fills
        # target/ directories.  No *source* file is touched without --apply.
        print("No source files were changed. Re-run with --apply to write the "
              "batches marked READY.")
    if failed:
        print(f"Stages failed: {', '.join(failed)}")
        return 1
    return 0


def cmd_pipeline(args) -> int:
    ctx = context.build(args.repo)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    results = pipeline.run(
        ctx, out_dir, apply_changes=args.apply, stop_after=args.stop_after,
        maven=not args.skip_maven, build_deps=args.build_deps,
        mvn_timeout=args.mvn_timeout,
        mvn_args=mvntest.extra_args(java_only=args.java_only,
                                    skip_native_win=args.skip_native_win,
                                    mvn_arg=args.mvn_arg))
    return _render_stages(results, applied=args.apply)


def cmd_assess(args) -> int:
    """Step M3 (same computation as pipeline)."""
    ctx = context.build(args.repo)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)
    inv = pipeline.stage_m2(ctx, out_dir).payload
    stats = pipeline.stage_m3(ctx, inv, out_dir).payload
    md_path = os.path.join(out_dir, "hdfs-11039-assessment.md")
    xml_path = os.path.join(out_dir, "hdfs-11039-proposed-additions.xml")
    print(f"{stats['total']} properties proposed for documentation "
          f"across {stats['batches']} review batches")
    print(f"  description derived from Javadoc or a site guide : {stats['described']}")
    print(f"  needs a description author (marked TODO)         : {stats['todo']}")
    print()
    print(f"wrote {os.path.relpath(md_path, ctx.repo)}")
    print(f"wrote {os.path.relpath(xml_path, ctx.repo)}")
    return 0


def cmd_dossier(args) -> int:
    ctx = context.build(args.repo)
    inv = inventory.build(ctx)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"dossier-{args.status.lower().replace('_', '-')}.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(dossier.build(inv, ctx.repo, args.status))
    print(f"wrote {os.path.relpath(path, ctx.repo)} "
          f"({len(inv.by_status(args.status))} entries)")
    return 0


def main(argv=None) -> int:
    # --repo is declared on a parent parser so it is accepted both before and
    # after the subcommand.  Operators reach for `pipeline --repo ...` first,
    # and argparse would otherwise reject it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=DEFAULT_REPO,
                        help="path to the Hadoop checkout (default: inferred)")

    parser = argparse.ArgumentParser(description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_oracle = sub.add_parser(parents=[common], name="oracle", help="validate the scanner against the Java tests")
    p_oracle.add_argument("--module", help="limit to one module")
    p_oracle.set_defaults(func=cmd_oracle)

    p_keys = sub.add_parser(parents=[common], name="keys", help="dump key constants (E1)")
    p_keys.add_argument("--module", default="hdfs")
    p_keys.add_argument("--json", action="store_true")
    p_keys.set_defaults(func=cmd_keys)

    p_xml = sub.add_parser(parents=[common], name="xml", help="dump documented properties (E3)")
    p_xml.add_argument("--module", default="hdfs")
    p_xml.set_defaults(func=cmd_xml)

    p_skips = sub.add_parser(parents=[common], name="skips", help="dump skip lists with reasons (E5)")
    p_skips.add_argument("--module", default="hdfs")
    p_skips.set_defaults(func=cmd_skips)

    p_lit = sub.add_parser(parents=[common], name="literals", help="dump literal keys found in sources (E2)")
    p_lit.add_argument("--include-tests", action="store_true")
    p_lit.add_argument("-v", "--verbose", action="store_true", help="show every site")
    p_lit.set_defaults(func=cmd_literals)

    p_dep = sub.add_parser(parents=[common], name="deprecations", help="dump deprecated names (E4)")
    p_dep.set_defaults(func=cmd_deprecations)

    p_sum = sub.add_parser(parents=[common], name="summary", help="extractor totals and the raw gap")
    p_sum.set_defaults(func=cmd_summary)

    p_ver = sub.add_parser(parents=[common], name="verify", help="check every record's file:line provenance")
    p_ver.set_defaults(func=cmd_verify)

    p_sweep = sub.add_parser(parents=[common], name="sweep", help="E6: account for every accessor call site")
    p_sweep.add_argument("-v", "--verbose", action="store_true")
    p_sweep.set_defaults(func=cmd_sweep)

    p_inv = sub.add_parser(parents=[common], name="inventory", help="build the classified inventory (CSV + Markdown)")
    p_inv.add_argument("--out", help="output directory (default: ./out)")
    p_inv.set_defaults(func=cmd_inventory)

    p_step = sub.add_parser(parents=[common], name="step", help="run one step (M1..M4) of the process")
    p_step.add_argument("name", choices=["M1", "M2", "M3", "M4", "M5"])
    p_step.add_argument("--apply", action="store_true", help="M4 only: write to the repo")
    p_step.add_argument("--build-deps", action="store_true",
                        help="M5 only: also build dependency modules (mvn -am); slow")
    p_step.add_argument("--timeout", type=int, default=3600,
                        help="M5 only: seconds to allow maven (default 3600)")
    p_step.add_argument("--java-only", action="store_true",
                        help="M5 only: skip Hadoop's native and shell-test builds")
    p_step.add_argument("--skip-native-win", action="store_true",
                        help="M5 only: skip just the winutils build")
    p_step.add_argument("--mvn-arg", action="append",
                        help="M5 only: extra argument passed to maven; repeatable")
    p_step.add_argument("--out", help="output directory (default: ./out)")
    p_step.set_defaults(func=cmd_step)

    p_mvn = sub.add_parser(parents=[common], name="mvntest",
                           help="run Hadoop's real comparison tests via maven")
    p_mvn.add_argument("--module", choices=["hdfs", "rbf"])
    p_mvn.add_argument("--build-deps", action="store_true",
                       help="also build dependency modules (mvn -am); slow but needed "
                            "on a fresh checkout")
    p_mvn.add_argument("--timeout", type=int, default=3600)
    p_mvn.add_argument("--java-only", action="store_true",
                       help="skip Hadoop's native (winutils) and bats shell-test builds; "
                            "neither affects the configuration tests")
    p_mvn.add_argument("--skip-native-win", action="store_true",
                       help="skip only the winutils build")
    p_mvn.add_argument("--mvn-arg", action="append",
                       help="extra argument passed straight to maven; repeatable")
    p_mvn.add_argument("-v", "--verbose", action="store_true")
    p_mvn.set_defaults(func=cmd_mvntest)

    p_pipe = sub.add_parser(parents=[common], name="pipeline", help="run the whole M1-M4 process")
    p_pipe.add_argument("--apply", action="store_true",
                        help="let M4 write to the repo (default: analyse only)")
    p_pipe.add_argument("--skip-maven", action="store_true",
                        help="do not run Hadoop's real tests (M5); analysis only")
    p_pipe.add_argument("--build-deps", action="store_true",
                        help="M5: also build dependency modules (-am); needed on a "
                             "fresh checkout")
    p_pipe.add_argument("--java-only", action="store_true",
                        help="M5: skip Hadoop's native and shell-test builds")
    p_pipe.add_argument("--skip-native-win", action="store_true",
                        help="M5: skip just the winutils build")
    p_pipe.add_argument("--mvn-arg", action="append",
                        help="M5: extra argument passed to maven; repeatable")
    p_pipe.add_argument("--mvn-timeout", type=int, default=3600,
                        help="M5: seconds to allow maven (default 3600)")
    p_pipe.add_argument("--stop-after", choices=["M1", "M2", "M3", "M4"],
                        help="stop after the named stage")
    p_pipe.add_argument("--out", help="output directory (default: ./out)")
    p_pipe.set_defaults(func=cmd_pipeline)

    p_ass = sub.add_parser(parents=[common], name="assess", help="M3: recommendations + proposed xml")
    p_ass.add_argument("--out", help="output directory (default: ./out)")
    p_ass.set_defaults(func=cmd_assess)

    p_dos = sub.add_parser(parents=[common], name="dossier", help="evidence dossier for writing xml descriptions")
    p_dos.add_argument("--status", default="ACTIVE_UNDOCUMENTED")
    p_dos.add_argument("--out", help="output directory (default: ./out)")
    p_dos.set_defaults(func=cmd_dossier)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
