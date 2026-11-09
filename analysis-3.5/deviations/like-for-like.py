#!/usr/bin/env python3
# Deviation analysis: jars shipped in the official hadoop-3.5.0 binary
# tarball vs the g:a pairs its hand-maintained LICENSE-binary lists.
# Uses the same partial-row promotion rule as the archive gate
# (check-archive-licenses.sh): an empty group is promoted from the
# artifact stem or the filename base via archive-jar-mappings.
import re
import sys
from collections import defaultdict

TSV = "../sources/system/archive-jars.tsv"
MANIFEST = "../sources/system/LICENSE-binary"
MAPPINGS = "../../dev-support/licenses/archive-jar-mappings"
SHADED = "../../dev-support/licenses/shaded-jars"

# --- mappings: "stem g:a" lines (whitespace-separated); the gate's
# promotion table
mappings = {}
for line in open(MAPPINGS):
    line = line.split("#")[0].rstrip()
    if not line.strip():
        continue
    parts = line.split(None, 2)
    if len(parts) >= 2:
        mappings[parts[0].strip().lower()] = parts[1].strip().lower()

shaded = set()
for line in open(SHADED):
    line = line.split("#")[0].strip()
    if line:
        g, a = line.split(":")[:2]
        shaded.add(f"{g.lower()}:{a.lower()}")

# --- enumerate the shipped jars (TSV columns: path, group, artifact, version, source)
shipped = {}  # ga -> [versions]
promoted = []
for line in open(TSV):
    line = line.rstrip("\n")
    if not line:
        continue
    path, group, artifact, version, source = (line.split("\t") + [""] * 5)[:5]
    if not group:
        # promotion: the artifact field carries the clean stem when
        # present; only a filename-derived stem needs the version
        # suffix stripped (split on '-', drop trailing non-digit-first
        # segments — the gate's rule)
        if artifact:
            stem = artifact.lower()
        else:
            stem = path.rsplit("/", 1)[-1]
            stem = stem[:-4] if stem.endswith(".jar") else stem
            parts = stem.split("-")
            while parts and not parts[-1][:1].isdigit():
                parts.pop()
            stem = "-".join(parts).lower()
        ga = mappings.get(stem)
        if ga:
            promoted.append((path, ga))
        else:
            ga = f"<unpromoted:{stem}>"
            promoted.append((path, ga))
        group, artifact = ga.split(":")[:2]
    ga = f"{group.lower()}:{artifact.lower()}"
    shipped.setdefault(ga, set()).add(version)

# --- the manual manifest's g:a set
manifest_ga = set()
coord = re.compile(r"^([\w.\-]+):([\w.\-]+):([\w.\-]+)$")
for line in open(MANIFEST):
    m = coord.match(line.strip())
    if m:
        manifest_ga.add(f"{m.group(1).lower()}:{m.group(2).lower()}")

own = {ga for ga in shipped if ga.startswith("org.apache.hadoop")}
third_party_shipped = {ga: v for ga, v in shipped.items() if ga not in own}

unlisted = sorted(ga for ga in third_party_shipped if ga not in manifest_ga)
unshipped = sorted(manifest_ga - set(third_party_shipped))
unshipped_shaded = sorted(ga for ga in unshipped if ga in shaded)
unshipped_plain = sorted(ga for ga in unshipped if ga not in shaded)

print(f"shipped jars (TSV rows): {sum(1 for _ in open(TSV)) - 1}")
print(f"promoted from partial rows: {sum(1 for p, ga in promoted if not ga.startswith('<unpromoted'))}"
      f"  unpromoted: {sum(1 for p, ga in promoted if ga.startswith('<unpromoted'))}")
print(f"distinct shipped third-party g:a: {len(third_party_shipped)}"
      f"  (own org.apache.hadoop jars excluded: {len(own)})")
print(f"manual LICENSE-binary g:a entries: {len(manifest_ga)}")
print()

# coordinate drift: a shipped g:a whose artifactId IS listed, but under
# a different group (the manual manifest names the artifact under a
# stale coordinate)
listed_by_artifact = defaultdict(list)
for ga in manifest_ga:
    listed_by_artifact[ga.split(":")[1]].append(ga)
drift = []
unlisted_real = []
for ga in unlisted:
    art = ga.split(":")[1]
    if art in listed_by_artifact:
        drift.append((ga, sorted(listed_by_artifact[art])))
    else:
        unlisted_real.append(ga)

print(f"== SHIPPED BUT NOT LISTED in the manual LICENSE-binary: {len(unlisted)}")
print(f"   of which COORDINATE DRIFT (artifact listed under another group): {len(drift)}")
for ga, alts in drift:
    print(f"   {ga}  ships; manual lists: {', '.join(alts)}")
print(f"   NOT LISTED UNDER ANY COORDINATE: {len(unlisted_real)}")
for ga in unlisted_real:
    print(f"   {ga}  (ships at: {', '.join(sorted(third_party_shipped[ga]))})")
print()

# version staleness: g:a in both sets whose manual version differs from
# every shipped version
stale = []
form = []
for ga in sorted(set(manifest_ga) & set(third_party_shipped)):
    mver = {coord.match(l.strip()).group(3).lower()
            for l in open(MANIFEST)
            if (m2 := coord.match(l.strip()))
            and f"{m2.group(1).lower()}:{m2.group(2).lower()}" == ga}
    shipped_versions = {v.lower() for v in third_party_shipped[ga]}
    if mver == shipped_versions:
        continue
    if mver & shipped_versions:
        form.append((ga, sorted(mver), sorted(shipped_versions)))
    else:
        stale.append((ga, sorted(mver), sorted(shipped_versions)))
print(f"== VERSION DRIFT between manual manifest and shipped jars: "
      f"{len(stale)} stale + {len(form)} enumerated-form-only")
for ga, mv, sv in stale:
    print(f"   {ga}: manual {mv} vs shipped {sv}")
for ga, mv, sv in form:
    print(f"   {ga}: manual {mv} vs shipped {sv} (subset/form)")
print()

print(f"== LISTED BUT NOT SHIPPED (declared-but-not-shipped): {len(unshipped_plain)}"
      f"  (+{len(unshipped_shaded)} embedded-only/shaded entries, expected)")
for ga in unshipped_plain:
    print(f"   {ga}")
print()
unpromoted_paths = [p for p, ga in promoted if ga.startswith("<unpromoted")]
if unpromoted_paths:
    print(f"== jars whose stem has NO mapping promotion rule: {len(unpromoted_paths)}")
    for p in unpromoted_paths[:40]:
        print(f"   {p}")
