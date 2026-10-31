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

"""Who the change affects, from the results of every comparison.

Usage: impact.py <compare dir>

Reads artifact-diff.json, api-compat.json, downstream-compare.json and
e2e-compare-*.json from the compare directory and writes impact.md: for each
audience (daemons and applications on the Hadoop classpath, users of the
shaded client jars, Maven projects that depend on the non-shaded artifacts),
what changes for them, whether a rule accepts it, and whether that rule says
where users are told ('announced: <where>' in its reason). It has no verdict
of its own: the checks fail on what no rule accepts; this says what the
accepted changes mean, so the JIRA, the PR or the release note can say it.
"""

import collections
import glob
import json
import os
import re
import sys

CLIENT_JARS = ("hadoop-client-api", "hadoop-client-runtime", "hadoop-client-minicluster")


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def announced(reason):
    m = re.search(r"announced:\s*([^;]+)", reason or "", re.I)
    value = m.group(1).strip() if m else ""
    return None if not value or value.lower().startswith(("no", "not")) else value


def status_counts(items):
    c = collections.Counter()
    for d in items:
        if d.get("status") == "UNEXPECTED" or d.get("expected") is False:
            c["unexpected"] += 1
        elif announced(d.get("reason")):
            c["announced"] += 1
        else:
            c["accepted, not announced"] += 1
    return ", ".join(f"{n} {k}" for k, n in sorted(c.items())) or "none"


def client_jar(subject):
    for name in CLIENT_JARS:
        if f"/{name}-" in subject:
            return name
    return None


def main(cmp_dir):
    art = load(os.path.join(cmp_dir, "artifact-diff.json"))
    api = load(os.path.join(cmp_dir, "api-compat.json"))
    ds = load(os.path.join(cmp_dir, "downstream-compare.json"))
    e2e = {os.path.basename(p)[len("e2e-compare-"):-len(".json")]: load(p)
           for p in sorted(glob.glob(os.path.join(cmp_dir, "e2e-compare-*.json")))}
    out = ["## Impact on users\n",
           "What the accepted and unexpected differences mean for each audience. A rule "
           "accepts a difference; its reason should say where users are told "
           "(`announced: <where>`). Accepted but not announced means the JIRA, the PR or the "
           "release note should probably say it.\n"]
    api_f = (api or {}).get("findings", [])
    blocking = [f for f in api_f if f["status"] != "INFO"]

    # 1. Daemons and applications on the Hadoop classpath.
    out.append("### Daemons and applications on the Hadoop classpath\n")
    rows = []
    if art:
        diffs = art.get("differences", [])
        moves = collections.Counter()
        for d in diffs:
            if d["kind"] == "class-source-changed" and d.get("detail"):
                old, _, new = d["detail"].partition(" -> ")
                moves[(os.path.basename(old), os.path.basename(new))] += 1
        for (old, new), n in moves.most_common(10):
            rows.append(f"- Classes now loaded from `{new}` instead of `{old}`: {n} "
                        "(class and launcher pairs)")
        lib = [d for d in diffs if d["kind"].startswith("dist-file") and "/lib/" in d["subject"]]
        if lib:
            rows.append(f"- Third-party jars in the lib directories added or removed: {len(lib)} "
                        f"({status_counts(lib)})")
    third = [f for f in blocking if "third-party" in f["audience"]]
    hadoop = [f for f in blocking if "(Hadoop jar)" in f["audience"]]
    for label, items in (("Third-party API changes that break or constrain code built against "
                          "the old jars", third),
                         ("API changes in Hadoop's own jars", hadoop)):
        if items:
            kinds = collections.Counter(f["kind"] for f in items)
            rows.append(f"- {label}: {len(items)} ({', '.join(f'{n} {k}' for k, n in kinds.items())}; "
                        f"{status_counts(items)})")
    for arch, r in e2e.items():
        if not r or "rows" not in r:
            continue
        c = collections.Counter(x["class"] for x in r["rows"])
        moves = r.get("class_jar_moves", [])
        rows.append(f"- End to end ({arch}): {c.get('MATCH', 0)} observations match, "
                    f"{c.get('DIFF', 0)} differ, {c.get('REGRESSION', 0)} regressions; "
                    f"{len(moves)} classes loaded by the daemons from another jar")
    out += (rows or ["- No difference."]) + [""]

    # 2. Shaded client jars.
    out.append("### Users of the shaded client jars\n")
    rows = []
    if art:
        per = collections.defaultdict(list)
        for d in art.get("differences", []):
            j = client_jar(d["subject"])
            if j and d["kind"].startswith(("jar-entry", "class-")):
                per[j].append(d)
        for j in CLIENT_JARS:
            items = per.get(j, [])
            if not items:
                rows.append(f"- `{j}`: unchanged apart from build metadata")
                continue
            public = [d for d in items if "/shaded/" not in d["subject"]
                      and ".shaded." not in d["subject"]]
            kinds = collections.Counter(d["kind"] for d in items)
            rows.append(f"- `{j}`: {len(items)} entries changed "
                        f"({', '.join(f'{n} {k}' for k, n in sorted(kinds.items()))}); "
                        f"{len(public)} outside the relocated packages, i.e. visible API "
                        f"({status_counts(public) if public else 'none'})")
    for j in CLIENT_JARS:
        items = [f for f in blocking if f["audience"].startswith(j)]
        if items:
            rows.append(f"- API changes in `{j}`: {len(items)} ({status_counts(items)})")
    out += (rows or ["- No difference."]) + [""]

    # 3. Maven projects depending on non-shaded artifacts.
    out.append("### Maven projects that depend on the non-shaded artifacts\n")
    rows = []
    if ds and "differences" in ds:
        per = collections.defaultdict(lambda: collections.defaultdict(list))
        for d in ds["differences"]:
            scenario = d["subject"].split("/", 1)[0]
            per[scenario][d["kind"]].append(d)
        for scenario in sorted(per):
            parts = []
            for kind in sorted(per[scenario]):
                items = per[scenario][kind]
                projects = {d["subject"].split("|")[0] for d in items}
                parts.append(f"{kind}: {len(items)} in {len(projects)} projects ({status_counts(items)})")
            rows.append(f"- `{scenario}`: " + "; ".join(parts))
        dup = (ds.get("summary") or {}).get("duplicates")
        if dup:
            newly = {}
            for d in ds["differences"]:
                if d["kind"] == "downstream-dup-added":
                    newly.setdefault(d["subject"].split("|")[0], set()).add(d["subject"].split("|")[1])
            before = {d["subject"].split("|")[0] for d in ds["differences"]
                      if d["kind"] == "downstream-dup-removed"}
            fresh = sorted(p for p in newly if p not in before)
            if fresh:
                rows.append(f"- Projects that had no duplicate classes in these packages and now have "
                            f"them ({len(fresh)}): " + ", ".join(f"`{p}`" for p in fresh))
    out += (rows or ["- No difference, or downstream projects were not resolved."]) + [""]

    # 4. Accepted but never announced.
    silent = []
    for name, items in (("API", blocking),
                        ("downstream", (ds or {}).get("differences", [])),
                        ("artifacts", [d for d in (art or {}).get("differences", [])
                                       if client_jar(d["subject"]) or "/lib/" in d["subject"]])):
        for d in items:
            if d.get("status") == "EXPECTED" and not announced(d.get("reason")):
                silent.append((name, d))
    if silent:
        reasons = collections.Counter((name, d.get("reason") or "") for name, d in silent)
        out += [f"### Accepted user-visible differences without an announcement ({len(silent)})\n",
                "| Check | Rule reason | Differences |", "|---|---|---|"]
        out += [f"| {n} | {r} | {k} |" for (n, r), k in reasons.most_common()]
        out.append("")
    with open(os.path.join(cmp_dir, "impact.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"impact: written {os.path.join(cmp_dir, 'impact.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
