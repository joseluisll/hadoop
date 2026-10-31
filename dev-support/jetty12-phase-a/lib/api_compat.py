#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""API compatibility of every class that changes between the two sides.

Usage:
  api_compat.py --expected expected-api-differences.txt --out DIR \\
      [--max-class-version 61] BASELINE_RESULTS CANDIDATE_RESULTS

The artifact diff says which files and jar entries differ; this says what a
difference means for code built against the old ones: Hadoop's own jars, the
third-party jars on the Hadoop classpath (which are also what Maven consumers
of the non-shaded artifacts resolve) and the shaded client jars. A class is
compared when
  - a launcher (hadoop, hdfs, yarn, mapred, tools, ...) loads it from another
    jar, or the same jar with other bytes: what the daemons actually run;
  - a jar present on both sides has it with other bytes;
  - a jar is replaced by another one (removed and added with classes in
    common, e.g. a version or coordinate change): both copies.
For each pair of jars it also compares the JPMS module name and the highest
class-file version.

Kinds (subject "<old jar> -> <new jar>|<class>[#<member>]", or "<jar>|..."
when the jar is the same; jars relative to the distribution):
  breaking         api-class-made-invisible, api-class-kind-changed,
                   api-class-made-final, api-class-made-abstract,
                   api-superclass-changed, api-interface-removed,
                   api-member-removed, api-member-visibility-reduced,
                   api-member-static-changed, api-field-type-changed,
                   api-method-made-final
  implementor      api-abstract-method-added, api-method-made-abstract: code
                   that implements or extends the type no longer compiles
                   (already-compiled code works until the method is called)
  jpms             jar-module-name-changed (subject "<old> -> <new>")
  jre              jar-class-version-raised above --max-class-version
  info             jar-class-version-raised below it; additions are counted

Findings in relocated packages (org.apache.hadoop.shaded.*) or in classes
annotated @InterfaceAudience.Private are listed but do not fail the check.
Every other breaking, implementor, jpms or jre finding must match a rule in
the allowlist ('<kind> <regex>  # reason', regexes matching the whole kind and
subject). A reason should say where the impact is announced to users
('announced: <JIRA release note | PR | ...>'); rules saying 'announced: no',
or not saying it at all, are listed as accepted impacts nobody was told about.

Writes DIR/api-compat.json and .md. Exits 1 on an unexpected finding.
"""

import argparse
import collections
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from artifact_diff import ARCHIVE, Allowlist, dist_files  # noqa: E402
import classfile as cf  # noqa: E402

BLOCKING = ("breaking", "implementor", "jpms", "jre")
SEVERITY = {
    "api-class-made-invisible": "breaking", "api-class-kind-changed": "breaking",
    "api-class-made-final": "breaking", "api-class-made-abstract": "breaking",
    "api-superclass-changed": "breaking", "api-interface-removed": "breaking",
    "api-member-removed": "breaking", "api-member-visibility-reduced": "breaking",
    "api-member-static-changed": "breaking", "api-field-type-changed": "breaking",
    "api-method-made-final": "breaking",
    "api-abstract-method-added": "implementor", "api-method-made-abstract": "implementor",
    "jar-module-name-changed": "jpms",
}
PRIVATE_AUDIENCE = "org.apache.hadoop.classification.InterfaceAudience.Private"


def audience(rel):
    """Who sees a jar of the distribution."""
    name = os.path.basename(rel)
    if name.startswith("hadoop-client-api-"):
        return "hadoop-client-api users"
    if name.startswith("hadoop-client-runtime-"):
        return "hadoop-client-runtime users"
    if name.startswith("hadoop-client-minicluster-"):
        return "hadoop-client-minicluster users"
    if "/lib/" in rel:
        return "Hadoop classpath and Maven consumers of non-shaded artifacts (third-party jar)"
    return "Hadoop classpath and Maven consumers of non-shaded artifacts (Hadoop jar)"


class Jars:
    """Open jars of one side, by path relative to its distribution."""

    def __init__(self, root):
        self.root, self.open = root, {}

    def zip(self, rel):
        if rel not in self.open:
            try:
                self.open[rel] = zipfile.ZipFile(os.path.join(self.root, rel))
            except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError):
                self.open[rel] = None
        return self.open[rel]

    def entry(self, rel, cls):
        z = self.zip(rel)
        name = cls.replace(".", "/") + ".class"
        if z is None:
            return None
        try:
            return z.getinfo(name)
        except KeyError:
            return None

    def read(self, rel, cls):
        info = self.entry(rel, cls)
        return self.zip(rel).read(info) if info else None

    def classes(self, rel):
        z = self.zip(rel)
        if z is None:
            return {}
        return {n[:-6].replace("/", "."): i.CRC for n, i in ((i.filename, i) for i in z.infolist())
                if n.endswith(".class") and not n.startswith("META-INF/")
                and n != "module-info.class"}

    def max_class_version(self, rel):
        z, top = self.zip(rel), 0
        if z is None:
            return 0
        for i in z.infolist():
            if i.filename.endswith(".class") and not i.filename.startswith("META-INF/versions/"):
                head = z.open(i).read(8)
                if head[:4] == b"\xca\xfe\xba\xbe":
                    top = max(top, int.from_bytes(head[6:8], "big"))
        return top


def views(results, root):
    """{command: {class: jar relative to the dist}} from artifact-diff.sh's classpaths."""
    out = {}
    cp_dir = os.path.join(results, "classpath")
    if not os.path.isdir(cp_dir):
        return out
    for name in sorted(os.listdir(cp_dir)):
        if not name.endswith(".txt"):
            continue
        first = {}
        with open(os.path.join(cp_dir, name), encoding="utf-8") as f:
            entries = [e for e in f.read().strip().split(":") if e]
        for e in entries:
            if not e.endswith(ARCHIVE) or not os.path.isfile(e):
                continue
            rel = os.path.relpath(e, root)
            try:
                with zipfile.ZipFile(e) as z:
                    for n in z.namelist():
                        if n.endswith(".class") and not n.startswith("META-INF/") \
                                and n != "module-info.class":
                            first.setdefault(n[:-6].replace("/", "."), rel)
            except zipfile.BadZipFile:
                continue
        out[name[:-4]] = first
    return out


def visibility(flags):
    return 2 if flags & cf.ACC_PUBLIC else 1 if flags & cf.ACC_PROTECTED else 0


class Resolver:
    """Finds a class of one side, to tell a member moved to a supertype from a removed one."""

    def __init__(self, jars, providers):
        self.jars, self.providers, self.cache = jars, providers, {}

    def get(self, cls, prefer=None):
        if cls in self.cache:
            return self.cache[cls]
        info = None
        for rel in ([prefer] if prefer else []) + [self.providers.get(cls)]:
            data = self.jars.read(rel, cls) if rel else None
            if data:
                info = cf.parse(data)
                break
        self.cache[cls] = info
        return info

    def inherits(self, info, key, is_field, jar):
        """True if a visible member keyed so is declared by a supertype of info."""
        seen, todo = set(), [info.super] + list(info.interfaces)
        while todo:
            name = todo.pop()
            if not name or name in seen or len(seen) > 64:
                continue
            seen.add(name)
            sup = self.get(name, prefer=jar)
            if sup is None:
                continue
            members = sup.fields if is_field else sup.methods
            if key in members:
                flags = members[key][0] if is_field else members[key]
                if visibility(flags) or sup.is_interface:
                    return True
            todo += [sup.super] + list(sup.interfaces)
        return False


def compare_class(old, new, resolver, new_jar):
    """[(kind, member or None, detail)] between two versions of a class."""
    out = []
    if not old.visible:
        return out  # not API before: nothing to break
    if not new.visible:
        return [("api-class-made-invisible", None, "public -> package-private")]
    if old.is_interface != new.is_interface or \
            bool(old.flags & cf.ACC_ANNOTATION) != bool(new.flags & cf.ACC_ANNOTATION) or \
            bool(old.flags & cf.ACC_ENUM) != bool(new.flags & cf.ACC_ENUM):
        out.append(("api-class-kind-changed", None, f"flags {old.flags:#06x} -> {new.flags:#06x}"))
    if not old.flags & cf.ACC_FINAL and new.flags & cf.ACC_FINAL:
        out.append(("api-class-made-final", None, "can no longer be extended"))
    if not old.is_interface and not old.flags & cf.ACC_ABSTRACT and new.flags & cf.ACC_ABSTRACT:
        out.append(("api-class-made-abstract", None, "can no longer be instantiated"))
    if old.super != new.super and not old.is_interface:
        out.append(("api-superclass-changed", None, f"{old.super} -> {new.super}"))
    for i in sorted(set(old.interfaces) - set(new.interfaces)):
        out.append(("api-interface-removed", None, i))
    extendable = not new.flags & cf.ACC_FINAL
    for name, (of, od) in sorted(old.fields.items()):
        if not visibility(of) and not old.is_interface:
            continue
        if name not in new.fields:
            if not resolver.inherits(new, name, True, new_jar):
                out.append(("api-member-removed", name, f"field {od}"))
            continue
        nf, nd = new.fields[name]
        if nd != od:
            out.append(("api-field-type-changed", name, f"{od} -> {nd}"))
        if visibility(nf) < visibility(of) and not new.is_interface:
            out.append(("api-member-visibility-reduced", name, "field"))
        if (of ^ nf) & cf.ACC_STATIC:
            out.append(("api-member-static-changed", name, "field"))
    for key, of in sorted(old.methods.items()):
        if not visibility(of) and not old.is_interface:
            continue
        if key not in new.methods:
            if not resolver.inherits(new, key, False, new_jar):
                out.append(("api-member-removed", key, "method"))
            continue
        nf = new.methods[key]
        if visibility(nf) < visibility(of) and not new.is_interface:
            out.append(("api-member-visibility-reduced", key, "method"))
        if (of ^ nf) & cf.ACC_STATIC:
            out.append(("api-member-static-changed", key, "method"))
        if extendable and not of & cf.ACC_FINAL and nf & cf.ACC_FINAL and not of & cf.ACC_STATIC:
            out.append(("api-method-made-final", key, "subclasses can no longer override it"))
        if not of & cf.ACC_ABSTRACT and nf & cf.ACC_ABSTRACT:
            out.append(("api-method-made-abstract", key, "implementors must now provide it"))
    abstract_type = new.is_interface or new.flags & cf.ACC_ABSTRACT
    for key in sorted(new.methods.keys() - old.methods.keys()):
        nf = new.methods[key]
        if abstract_type and extendable and nf & cf.ACC_ABSTRACT and visibility(nf | (
                cf.ACC_PUBLIC if new.is_interface else 0)):
            out.append(("api-abstract-method-added", key,
                        "code implementing or extending the type no longer compiles"))
    return out


def additions(old, new):
    if not new.visible:
        return 0
    return sum(1 for k in new.methods.keys() - old.methods.keys() if visibility(new.methods[k])) + \
        sum(1 for k in new.fields.keys() - old.fields.keys() if visibility(new.fields[k][0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-class-version", type=int, default=61,
                    help="highest class-file version Hadoop's users can run (61 = Java 17)")
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    a = ap.parse_args()

    def dist(results):
        with open(os.path.join(results, "build", "dist-path.txt"), encoding="utf-8") as f:
            return f.read().strip()

    b_root, c_root = dist(a.baseline), dist(a.candidate)
    jb, jc = Jars(b_root), Jars(c_root)
    vb, vc = views(a.baseline, b_root), views(a.candidate, c_root)
    pairs = collections.defaultdict(set)      # (old jar, new jar, class) -> commands
    jar_pairs = collections.defaultdict(set)  # (old jar, new jar) -> where seen

    # 1. What each launcher loads.
    for cmd in sorted(vb.keys() & vc.keys()):
        for cls in vb[cmd].keys() & vc[cmd].keys():
            ob, nc = vb[cmd][cls], vc[cmd][cls]
            if ob != nc:
                jar_pairs[(ob, nc)].add(f"classpath:{cmd}")
            eb, ec = jb.entry(ob, cls), jc.entry(nc, cls)
            if eb and ec and eb.CRC != ec.CRC:
                pairs[(ob, nc, cls)].add(cmd)

    # 2. Jars on both sides, and 3. jars replaced by others.
    fb = {r for r in dist_files(b_root) if r.endswith(".jar")}
    fc = {r for r in dist_files(c_root) if r.endswith(".jar")}
    for rel in sorted(fb & fc):
        cb, cc = jb.classes(rel), jc.classes(rel)
        for cls in cb.keys() & cc.keys():
            if cb[cls] != cc[cls]:
                pairs[(rel, rel, cls)].add("jar")
    removed, added = sorted(fb - fc), sorted(fc - fb)
    added_classes = {r: jc.classes(r) for r in added}
    for old in removed:
        cb = jb.classes(old)
        sharing = [n for n, cc in added_classes.items() if cb.keys() & cc.keys()]
        # A jar copied into several directories (common/lib, hdfs/lib, ...) is
        # replaced by the new jar in its own directory, not by every copy.
        same_dir = [n for n in sharing if os.path.dirname(n) == os.path.dirname(old)]
        for new in same_dir or sharing:
            jar_pairs[(old, new)].add("replaced")
            for cls in cb.keys() & added_classes[new].keys():
                if cb[cls] != added_classes[new][cls]:
                    pairs[(old, new, cls)].add("replaced jar")

    allow = Allowlist(a.expected)
    findings, seen = [], {}

    def record(kind, jars, rest, detail, severity, aud, scope, where):
        """jars: (old, new) relative paths. The subject names jars by file name,
        so copies of a jar in several directories make one finding; the
        directories are kept in 'locations'."""
        old, new = (os.path.basename(j) for j in jars)
        subject = (old if old == new else f"{old} -> {new}") + rest
        key = (kind, subject)
        if key in seen:
            f = seen[key]
            f["where"] = sorted(set(f["where"]) | set(where))
            f["locations"] = sorted(set(f["locations"]) | {" -> ".join(dict.fromkeys(jars))})
            return
        blocking = severity in BLOCKING and scope == "public"
        rule = allow.match(kind, subject) if blocking else None
        f = {
            "kind": kind, "subject": subject, "detail": detail, "severity": severity,
            "audience": aud, "scope": scope, "where": sorted(where),
            "locations": [" -> ".join(dict.fromkeys(jars))],
            "status": ("EXPECTED" if rule else "UNEXPECTED") if blocking else "INFO",
            "reason": rule["reason"] if rule else None,
            "rule_line": rule["line"] if rule else None,
        }
        seen[key] = f
        findings.append(f)

    # Jar-level facts for every pair of different jars.
    jar_facts = []
    for (old, new), where in sorted(jar_pairs.items()):
        mb, mc = cf.module_name(os.path.join(b_root, old)), cf.module_name(os.path.join(c_root, new))
        vb_max, vc_max = jb.max_class_version(old), jc.max_class_version(new)
        jar_facts.append({"old": old, "new": new, "where": sorted(where),
                          "module": [mb, mc], "class_version": [vb_max, vc_max]})
        if mb[0] != mc[0]:
            record("jar-module-name-changed", (old, new), "",
                   f"{mb[0]} ({mb[1]}) -> {mc[0]} ({mc[1]})", "jpms", audience(new), "public", where)
        if vc_max > vb_max:
            sev = "jre" if vc_max > a.max_class_version else "info"
            record("jar-class-version-raised", (old, new), "",
                   f"class-file version {vb_max} -> {vc_max} (Java {vb_max - 44} -> {vc_max - 44})",
                   sev, audience(new), "public", where)

    rb = Resolver(jb, {c: r for v in vb.values() for c, r in v.items()})
    rc = Resolver(jc, {c: r for v in vc.values() for c, r in v.items()})
    compared, added_members = 0, collections.Counter()
    for (old, new, cls), where in sorted(pairs.items()):
        db, dc = jb.read(old, cls), jc.read(new, cls)
        if not db or not dc:
            continue
        try:
            ob, nc = cf.parse(db), cf.parse(dc)
        except ValueError:
            continue
        rb.cache.setdefault(cls, ob)
        compared += 1
        scope = "relocated" if cls.startswith("org.apache.hadoop.shaded.") else \
            "private-audience" if PRIVATE_AUDIENCE in nc.annotations else "public"
        added_members[audience(new)] += additions(ob, nc)
        for kind, member, detail in compare_class(ob, nc, rc, new):
            rest = f"|{cls}" + (f"#{member}" if member else "")
            record(kind, (old, new), rest, detail, SEVERITY[kind], audience(new), scope, where)

    blocking = [f for f in findings if f["status"] != "INFO"]
    unexpected = [f for f in blocking if f["status"] == "UNEXPECTED"]
    unused = [f"line {r['line']}: {r['kind']} {r['pattern']}" for r in allow.rules if r["hits"] == 0]
    result = {
        "verdict": "FAIL" if unexpected else "PASS",
        "summary": {"classes_compared": compared, "jar_pairs": len(jar_facts),
                    "findings": len(findings), "blocking": len(blocking),
                    "unexpected": len(unexpected),
                    "public_members_added": dict(added_members)},
        "findings": findings, "jars": jar_facts, "unused_rules": unused,
    }
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "api-compat.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    write_md(os.path.join(a.out, "api-compat.md"), result, a.max_class_version)
    print(f"api compatibility: {compared} classes compared, {len(findings)} findings, "
          f"{len(unexpected)} unexpected")
    return 1 if unexpected else 0


def announced(reason):
    m = re.search(r"announced:\s*([^;]+)", reason or "", re.I)
    value = m.group(1).strip() if m else ""
    return None if not value or value.lower().startswith(("no", "not")) else value


def write_md(path, r, max_version):
    s = r["summary"]
    fs = r["findings"]
    lines = ["## API compatibility\n",
             f"Verdict: **{r['verdict']}**. Classes compared: {s['classes_compared']}; jar pairs: "
             f"{s['jar_pairs']}; findings: {s['findings']}, of which blocking {s['blocking']}, "
             f"**unexpected: {s['unexpected']}**. A class is compared when the launchers load it "
             "from another jar or with other bytes, or a jar on both sides or a replaced jar has it "
             f"with other bytes. Class-file versions above {max_version} need a newer Java than "
             "Hadoop's users run.\n"]
    by_aud = collections.defaultdict(collections.Counter)
    for f in fs:
        by_aud[f["audience"]][f["severity"] if f["scope"] == "public" else f["scope"]] += 1
    if by_aud:
        cols = ["breaking", "implementor", "jpms", "jre", "info", "relocated", "private-audience"]
        lines += ["### Impact by audience\n", "| Audience | " + " | ".join(cols) +
                  " | public members added |", "|---" * (len(cols) + 2) + "|"]
        for aud in sorted(by_aud.keys() | s["public_members_added"].keys()):
            lines.append(f"| {aud} | " + " | ".join(str(by_aud[aud][c] or "") for c in cols) +
                         f" | {s['public_members_added'].get(aud, 0)} |")
        lines.append("")
    for status, title in (("UNEXPECTED", "Unexpected: impacts no rule accepts"),
                          ("EXPECTED", "Accepted impacts")):
        rows = [f for f in fs if f["status"] == status]
        if not rows:
            continue
        lines += [f"### {title} ({len(rows)})\n",
                  "| Kind | Subject | Detail | Audience | Announced |", "|---|---|---|---|---|"]
        for f in rows:
            ann = "" if status == "UNEXPECTED" else (announced(f["reason"]) or "**no**")
            subject = f["subject"].replace("|", "\\|")
            lines.append(f"| {f['kind']} | `{subject}` | {f['detail']} | {f['audience']} | {ann} |")
        lines.append("")
    silent = [f for f in fs if f["status"] == "EXPECTED" and not announced(f["reason"])]
    if silent:
        lines += [f"**{len(silent)} accepted impacts are not announced anywhere** (their rules do "
                  "not say 'announced: <where>'): add them to the release note or the PR.\n"]
    info = [f for f in fs if f["status"] == "INFO"]
    if info:
        lines += [f"<details><summary>Not blocking ({len(info)}): relocated packages, "
                  "@InterfaceAudience.Private classes, older class-file versions</summary>\n",
                  "| Kind | Subject | Detail | Scope |", "|---|---|---|---|"]
        for f in info:
            subject = f["subject"].replace("|", "\\|")
            lines.append(f"| {f['kind']} | `{subject}` | {f['detail']} | {f['scope']} |")
        lines += ["", "</details>\n"]
    if r["jars"]:
        lines += ["<details><summary>Jar pairs compared</summary>\n",
                  "| Old jar | New jar | Module name | Class-file version | Seen as |",
                  "|---|---|---|---|---|"]
        for j in r["jars"]:
            mod = j["module"][0][0] if j["module"][0][0] == j["module"][1][0] else \
                f"{j['module'][0][0]} -> {j['module'][1][0]}"
            ver = j["class_version"]
            lines.append(f"| {j['old']} | {j['new']} | {mod} | {ver[0]} -> {ver[1]} | "
                         f"{', '.join(j['where'])} |")
        lines += ["", "</details>\n"]
    if r["unused_rules"]:
        lines += ["Allowlist rules that matched nothing:\n"] + [f"- `{u}`" for u in r["unused_rules"]] + [""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
