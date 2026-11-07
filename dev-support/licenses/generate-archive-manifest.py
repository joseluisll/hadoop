#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to you under the Apache License, Version 2.0
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
"""R40 archive-derived manifest generator.

Derives LICENSE-binary from the distributed archives' enumerated
contents (the archive-jars.tsv files produced by
enumerate-archive-jars.py), resolving each third-party artifact's
license from the collected dependency inventory and applying the
curated multi-license policy (dev-support/licenses/Multi-License-Policy.md).

Fail-closed by design: an archive artifact absent from the inventory,
a partial row that resists normalization, an uncurated multi-license
set, a malformed TSV row, or a zero-row enumeration is a hard error,
never a silent omission.

NOTICE-binary is NOT generated here: its per-component attribution
corpus is curated prose that cannot be derived from jar metadata. It
stays hand-maintained and is validated by the R10 drift gate.

Usage (from anywhere; curated-file defaults resolve next to this
script):
  generate-archive-manifest.py --inventory THIRD-PARTY.txt \
      --archive-tsv tsv1 [tsv2 ...] --out LICENSE-binary
"""

import argparse
import collections
import os
import re
import sys
from typing import NoReturn

# The inventory line: "(License) (License2) Name (g:a:v - url)" — the
# license field may carry several paren groups (multi-license POMs).
INVENTORY_LINE = re.compile(
    r'^\s*(?P<lics>(?:\([^)]+\)\s*)+)'
    r'(?P<name>.+?)\s'
    r'\((?P<g>[^:()]+):(?P<a>[^:()]+):(?P<v>[^)\s]+)'
    r'(?:\s-\s.*)?\)\s*$'
)
LICENSE_GROUPS = re.compile(r'\(([^)]+)\)')

# Manifest section order and headers. The apache section has no title —
# its template (manifest-template.txt) carries the ASF preamble and the
# Apache-2.0 text. Every other section references its text in the
# licenses-binary/ store shipped next to the manifest.
SECTIONS = [
    ('apache', None),
    ('bsd2', 'BSD 2-Clause'),
    ('bsd3', 'BSD 3-Clause'),
    ('mit', 'MIT License'),
    ('cddl', 'CDDL 1.1 + GPLv2 with classpath exception'),
    ('edl', 'Eclipse Distribution License (EDL) 1.0'),
    ('epl1', 'Eclipse Public License 1.0'),
    ('epl2', 'Eclipse Public License (EPL) 2.0'),
    ('combined',
     'Eclipse Public License (EPL) 2.0 with some parts being\n'
     'GNU General Public License (GPL), Version 2, With Classpath Exception,\n'
     'Apache License, 2.0 or Public Domain'),
    ('jdom', 'JDOM License'),
    ('isc', 'ISC License'),
    ('pd', 'Public Domain'),
    ('dom4j', 'Dom4J license'),
]

SECTION_KEYS = {key for key, _ in SECTIONS}

# The combined (jersey/hk2) section carries a fixed attribution note.
SECTION_NOTES = {
    'combined': 'See also https://github.com/eclipse-ee4j/jersey/blob/master/NOTICE.md',
}

# Line emitted once between the Apache section and the other sections.
INTERLUDE = [
    'This product bundles various third-party components under other open source',
    'licenses. This section summarizes those components and their licenses.',
    'See licenses-binary/ for text of these licenses.',
]

# Inventory license name -> section (single-license resolution).
NAME_TO_SECTION = {
    'The Apache Software License, Version 2.0': 'apache',
    'BSD 2-Clause License': 'bsd2',
    'Revised BSD': 'bsd3',
    'The Go license': 'bsd3',  # Google's BSD-3-clause-style Go license (re2j)
    'MIT License': 'mit',
    'Bouncy Castle Licence': 'mit',
    'CDDL + GPLv2 with classpath exception': 'cddl',
    'EDL 1.0': 'edl',
    'Eclipse Public License - Version 1.0': 'epl1',
    'EPL 2.0': 'epl2',
    'Public Domain': 'pd',
}

# Multi-license policy (R28), applied in order to the license-name SET:
# 1. Apache-2.0 present -> apache section.
# 2. EDL 1.0 present -> edl section.
# 3. EPL 2.0 present -> epl2 section.
# Exceptions ahead of the rules:
#   - the jersey/hk2 runtime keeps the combined section (their NOTICE.md
#     requires the mixed statement),
#   - named per-artifact sections (jdom2, dom4j) keep their own text,
#   - hdrhistogram (BSD-2 + Public Domain) keeps BSD-2 — the concrete
#     permissive text (R28 rule 4).
# Keys are GROUP prefixes: the group matches exactly or starts with
# key + '.'.
FAMILY_EXCEPTIONS = {
    'org.glassfish.jersey': 'combined',
    'org.glassfish.hk2': 'combined',
    'org.jdom': 'jdom',
    'org.dom4j': 'dom4j',
    'org.hdrhistogram': 'bsd2',
}


def fail(message) -> NoReturn:
    sys.stderr.write('FAIL: %s\n' % message)
    sys.exit(2)


def open_or_fail(path, what):
    try:
        return open(path)
    except OSError as err:
        fail('cannot read %s (%s): %s' % (what, path, err))


def section_for(ga, licenses):
    """Resolve the manifest section for one artifact. Fail-closed."""
    group = ga.split(':', 1)[0]
    for prefix, sec in FAMILY_EXCEPTIONS.items():
        if group == prefix or group.startswith(prefix + '.'):
            return sec
    names = set(licenses)
    if 'The Apache Software License, Version 2.0' in names:
        return 'apache'  # R28 rule 1 (jetty, jna, javassist, ...)
    if 'EDL 1.0' in names:
        return 'edl'     # R28 rule 2 (eclipse-collections, EclipseLink)
    if 'EPL 2.0' in names:
        return 'epl2'    # R28 rule 3 (jakarta duals)
    if len(names) == 1:
        name = next(iter(names))
        if name in NAME_TO_SECTION:
            return NAME_TO_SECTION[name]
    fail('unresolvable license for %s: %r — add a rule to '
         'Multi-License-Policy.md and the generator tables'
         % (ga, sorted(names)))


def version_is_own(group):
    return (group.lower() == 'org.apache.hadoop'
            or group.lower().startswith('org.apache.hadoop.'))


def stem_from_filename(path_field):
    """Right-to-left digit-segment scan: drop everything from the last
    trailing segment that starts with a digit (the version). None when
    no version-looking segment exists (the row resists normalization)."""
    base = path_field.split('/')[-1]
    if base.endswith('.jar'):
        base = base[:-4]
    segments = base.split('-')
    for i in range(len(segments) - 1, 0, -1):
        if segments[i][:1].isdigit():
            return '-'.join(segments[:i]).lower()
    return None


def load_mappings(path, what):
    mapping = {}
    for line in open_or_fail(path, what):
        stripped = line.split('#')[0].split()
        if len(stripped) >= 2:
            mapping[stripped[0].lower()] = stripped[1].lower()
    return mapping


def load_archive_ga_versions(paths, mappings_path):
    """g:a -> set of shipping versions, from enumeration TSVs with the
    archive-jar-mappings promotion applied (same rule as the gate).
    Partial rows that resist normalization are collected and reported —
    the gate's R36 failure class, never dropped silently."""
    mapping = load_mappings(mappings_path, 'archive-jar-mappings')
    ga_versions = collections.defaultdict(set)
    total = 0
    unresolved = []
    for path in paths:
        for lineno, line in enumerate(open_or_fail(path, 'archive TSV'),
                                      start=1):
            fields = line.rstrip('\n').split('\t')
            if len(fields) != 5:
                fail('%s:%d: malformed TSV row (need 5 tab-separated '
                     'fields path/group/artifact/version/source, got %d): %r'
                     % (path, lineno, len(fields), line.rstrip('\n')))
            jar_path, group, artifact, version, _source = fields
            if group and not artifact:
                fail('%s:%d: malformed TSV row (group without artifact): %r'
                     % (path, lineno, fields))
            if not version:
                fail('%s:%d: TSV row without a version: %r'
                     % (path, lineno, fields))
            if not group:
                # Partial row: identify via the curated mapping, from the
                # manifest/filename stem. A row that still resists is the
                # gate's R36 failure class — collect, never drop.
                stem = (artifact or '').lower()
                if not stem:
                    stem = stem_from_filename(jar_path)
                if not stem or stem not in mapping:
                    unresolved.append('%s:%d  %s (stem %r)'
                                      % (path, lineno, jar_path, stem))
                    continue
                group, artifact = mapping[stem].split(':')[:2]
            if version_is_own(group):
                continue  # own jars are covered by the top-level LICENSE
            ga_versions[(group + ':' + artifact).lower()].add(version)
            total += 1
    if total == 0:
        fail('zero enumerated third-party jars across %d TSV(s) — '
             'refusing to generate an empty manifest' % len(paths))
    if unresolved:
        sys.stderr.write(
            'FAIL: jars in the archive that resist g:a normalization '
            '(add a curated mapping to archive-jar-mappings):\n')
        for row in unresolved:
            sys.stderr.write('  %s\n' % row)
        sys.exit(2)
    return ga_versions


def load_inventory(path):
    """g:a -> (license names, inventory-resolved version)."""
    inventory = {}
    for line in open_or_fail(path, 'inventory'):
        match = INVENTORY_LINE.match(line.rstrip('\n'))
        if match:
            licenses = LICENSE_GROUPS.findall(match.group('lics'))
            inventory[(match.group('g') + ':' + match.group('a')).lower()] = (
                licenses, match.group('v'))
    if not inventory:
        fail('no parsable inventory lines in %s' % path)
    return inventory


def load_assets(path):
    """section<TAB>line — non-jar entries (native/source/webapp paths,
    npm packages) listed per section, in curated order."""
    assets = collections.defaultdict(list)
    for line in open_or_fail(path, 'assets file'):
        stripped = line.rstrip('\n')
        if not stripped or stripped.lstrip().startswith('#'):
            continue
        sec, _, text = stripped.partition('\t')
        if sec not in SECTION_KEYS:
            fail('assets file names unknown section %r' % sec)
        if not text:
            fail('assets line without tab-separated section: %r' % stripped)
        assets[sec].append(text)
    return assets


def load_embedded(path):
    """g:a coordinates embedded unrelocated in a shipping jar (R37);
    their licenses apply although no standalone jar is enumerated."""
    embedded = []
    for line in open_or_fail(path, 'shaded-jars'):
        stripped = line.split('#')[0].strip()
        if stripped:
            embedded.append(stripped.split()[0].lower())
    return embedded


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True,
                        help='THIRD-PARTY.txt from the collected-licenses artifact')
    parser.add_argument('--archive-tsv', required=True, nargs='+',
                        help='archive-jars.tsv files (one or more archives)')
    parser.add_argument('--mappings',
                        default=os.path.join(here, 'archive-jar-mappings'),
                        help='archive-jar-mappings curation file')
    parser.add_argument('--shaded', default=os.path.join(here, 'shaded-jars'),
                        help='shaded-jars curation file (embedded coordinates)')
    parser.add_argument('--assets', default=os.path.join(here, 'manifest-assets.txt'),
                        help='non-jar entries, "section<TAB>line" per line')
    parser.add_argument('--template', default=os.path.join(here, 'manifest-template.txt'),
                        help='content emitted before the artifact lists '
                             '(ASF preamble + Apache-2.0 text + bundle wording)')
    parser.add_argument('--out', required=True, help='output LICENSE-binary path')
    args = parser.parse_args()

    ga_versions = load_archive_ga_versions(args.archive_tsv, args.mappings)
    inventory = load_inventory(args.inventory)
    assets = load_assets(args.assets)

    # Shaded-jar embedded coordinates (R37): artifacts whose classes ship
    # unrelocated inside a top-level jar. Some also ship standalone in
    # another tree — possibly at a different version (protobuf-java 2.5.0
    # standalone, 3.25.5 embedded in hadoop-client-runtime) — so the
    # inventory-resolved version merges into the shipping-version set
    # rather than being skipped when the GA is already enumerated.
    for ga in load_embedded(args.shaded):
        if ga not in inventory:
            fail('shaded-jars lists %s but the inventory does not know it' % ga)
        licenses, version = inventory[ga]
        ga_versions.setdefault(ga, set()).add(version)

    sections = collections.defaultdict(list)
    for ga in sorted(ga_versions):
        if ga not in inventory:
            fail('%s ships in an archive but is absent from the collected '
                 'inventory — the graph never saw it' % ga)
        licenses, _ = inventory[ga]
        sections[section_for(ga, licenses)].append(
            (ga, sorted(ga_versions[ga])))

    try:
        out = open(args.out, 'w')
    except OSError as err:
        fail('cannot write output (%s): %s' % (args.out, err))
    with out:
        for line in open_or_fail(args.template, 'template'):
            out.write(line)
        first_section = True
        for key, title in SECTIONS:
            entries = sections.get(key, [])
            if not entries and key not in assets:
                continue
            if key == 'apache':
                out.write('\nThe following components are included:\n\n')
            else:
                if first_section:
                    out.write('\n'.join(INTERLUDE) + '\n')
                out.write('\n%s\n%s\n' % (title, '-' * max(len(title), 4)))
            if key in SECTION_NOTES:
                out.write('\n%s\n' % SECTION_NOTES[key])
            if key in assets:
                out.write('\n')
                for text in assets[key]:
                    out.write(text + '\n')
            if entries:
                out.write('\n')
            for ga, versions in entries:
                for version in versions:
                    out.write('%s:%s\n' % (ga, version))
            first_section = False
    ga_count = sum(len(v) for v in sections.values())
    version_count = sum(len(versions)
                        for entries in sections.values()
                        for _, versions in entries)
    print('generated %s: %d g:a (%d version lines), %d asset lines, '
          '%d sections' % (args.out, ga_count, version_count,
                           sum(len(v) for v in assets.values()),
                           len(sections)))


if __name__ == '__main__':
    main()
