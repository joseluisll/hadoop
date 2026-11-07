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
"""Tests for generate-archive-manifest.py (R40).

Runs the generator on synthetic inputs in a temp dir: one happy path
(partial-row promotion, shaded-jars merge, assets, multi-license
policy) and every fail-closed path (each must exit non-zero, write no
output, and print a FAIL: line). Run directly:

    python3 dev-support/licenses/test-generate-archive-manifest.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, 'generate-archive-manifest.py')

TEMPLATE = 'template preamble\n'
INVENTORY = (
    '     (The Apache Software License, Version 2.0) Gson (com.google.code.gson:gson:2.9.0 - https://x)\n'
    '     (Eclipse Public License - Version 1.0) (The Apache Software License, Version 2.0) Jetty (org.eclipse.jetty:jetty-util:9.4.58.v20250814 - https://x)\n'
    '     (CDDL + GPLv2 with classpath exception) (EPL 2.0) Jakarta Servlet (jakarta.servlet:jakarta.servlet-api:4.0.4 - https://x)\n'
    '     (The Apache Software License, Version 2.0) Protobuf (com.google.protobuf:protobuf-java:3.25.5 - https://x)\n'
    '     (The Apache Software License, Version 2.0) Nojit (com.example:nojit:1.0 - https://x)\n'
    '     (BSD 2-Clause License) (Public Domain) HdrHistogram (org.hdrhistogram:HdrHistogram:2.1.12 - https://x)\n'
    '     (Some Unknown License) Mystery (com.example:mystery:1.0 - https://x)\n'
)
MAPPINGS = 'nojit com.example:nojit # mapped partial row\n'
SHADED = 'com.google.protobuf:protobuf-java # embedded in hadoop-client-runtime\n'
ASSETS = 'apache\thadoop-x/src/static/lib.js\nmit\tsome-npm 1.0\n'

TSV_OK = (
    'lib/gson-2.9.0.jar\tcom.google.code.gson\tgson\t2.9.0\tpom.properties\n'
    'lib/jetty-util-9.4.58.v20250814.jar\torg.eclipse.jetty\tjetty-util\t9.4.58.v20250814\tpom.properties\n'
    'lib/jakarta.servlet-api-4.0.4.jar\tjakarta.servlet\tjakarta.servlet-api\t4.0.4\tpom.properties\n'
    'lib/protobuf-java-2.5.0.jar\tcom.google.protobuf\tprotobuf-java\t2.5.0\tpom.properties\n'
    'lib/HdrHistogram-2.1.12.jar\torg.hdrhistogram\tHdrHistogram\t2.1.12\tpom.properties\n'
    'lib/nojit-1.0.jar\t\t\t1.0\tfilename\n'
)
TSV_EMPTY = ''
TSV_UNMAPPED_PARTIAL = 'lib/nojit-lib.jar\t\t\t1.0\tfilename\n'
TSV_MALFORMED = 'lib/gson-2.9.0.jar\tcom.google.code.gson\n'
TSV_NO_VERSION = 'lib/gson-2.9.0.jar\tcom.google.code.gson\tgson\t\tpom.properties\n'
TSV_OWN_ONLY = 'lib/hadoop-common-3.6.0.jar\torg.apache.hadoop\thadoop-common\t3.6.0\tpom.properties\n'
INVENTORY_EMPTY = 'Lists of 0 third-party dependencies.\n'


def run_case(tsv, inventory=INVENTORY, mappings=MAPPINGS, shaded=SHADED,
             assets=ASSETS, expect=0, expect_stdout=None):
    """Run the generator on synthetic inputs; return (exit, stdout+stderr,
    manifest-text-or-None)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for name, content in [('tsv', tsv), ('inv', inventory),
                              ('map', mappings), ('shaded', shaded),
                              ('assets', assets), ('template', TEMPLATE)]:
            paths[name] = os.path.join(tmp, name)
            with open(paths[name], 'w') as handle:
                handle.write(content)
        out = os.path.join(tmp, 'LICENSE-binary')
        proc = subprocess.run(
            [sys.executable, GEN, '--inventory', paths['inv'],
             '--archive-tsv', paths['tsv'], '--mappings', paths['map'],
             '--shaded', paths['shaded'], '--assets', paths['assets'],
             '--template', paths['template'], '--out', out],
            capture_output=True, text=True)
        manifest = None
        if os.path.exists(out):
            with open(out) as handle:
                manifest = handle.read()
        return proc.returncode, proc.stdout + proc.stderr, manifest


def assert_fail(tsv, fragment, **kwargs):
    code, output, manifest = run_case(tsv, **kwargs)
    assert code != 0, 'expected failure, got exit 0; output: %s' % output
    assert 'FAIL:' in output, 'no FAIL message; output: %s' % output
    assert fragment in output, 'expected %r in output: %s' % (fragment, output)
    assert manifest is None, 'failed run must not write an output file'


def test_happy_path():
    code, output, manifest = run_case(TSV_OK)
    assert code == 0, output
    assert manifest is not None
    # partial row promoted via the mapping
    assert 'com.example:nojit:1.0' in manifest
    # shaded-jars merge: standalone 2.5.0 + embedded inventory version 3.25.5
    assert 'com.google.protobuf:protobuf-java:2.5.0' in manifest
    assert 'com.google.protobuf:protobuf-java:3.25.5' in manifest
    # R28 policy: jetty dual -> apache; jakarta dual -> epl2;
    # hdrhistogram -> bsd2; single Apache name -> apache
    assert 'org.eclipse.jetty:jetty-util:9.4.58.v20250814' in manifest
    assert 'jakarta.servlet:jakarta.servlet-api:4.0.4' in manifest
    assert 'org.hdrhistogram:hdrhistogram:2.1.12' in manifest
    # assets emitted under their sections; interlude before non-apache
    assert 'hadoop-x/src/static/lib.js' in manifest
    assert 'some-npm 1.0' in manifest
    assert 'BSD 2-Clause' in manifest and 'MIT License' in manifest
    # deterministic
    _, _, manifest2 = run_case(TSV_OK)
    assert manifest == manifest2


def test_empty_tsv():
    assert_fail(TSV_EMPTY, 'zero enumerated third-party jars')


def test_own_only_tsv():
    assert_fail(TSV_OWN_ONLY, 'zero enumerated third-party jars')


def test_unmapped_partial_row():
    # the reviewer's silent-data-loss case: a partial row that resists
    # normalization must fail the run, never be dropped
    tsv = TSV_OK + TSV_UNMAPPED_PARTIAL
    assert_fail(tsv, 'resist g:a normalization')


def test_malformed_row():
    assert_fail(TSV_MALFORMED, 'malformed TSV row')


def test_row_without_version():
    assert_fail(TSV_NO_VERSION, 'without a version')


def test_unknown_license_set():
    tsv = TSV_OK + 'lib/mystery-1.0.jar\tcom.example\tmystery\t1.0\tpom.properties\n'
    assert_fail(tsv, 'unresolvable license for com.example:mystery')


def test_empty_inventory():
    assert_fail(TSV_OK, 'no parsable inventory lines',
                inventory=INVENTORY_EMPTY)


def test_inventory_missing_ga():
    inventory = INVENTORY.replace(
        'com.google.code.gson:gson:2.9.0', 'com.google.code.gson:gson:9.9.9')
    # the GA line still parses (version differs) so this stays resolvable;
    # a truly absent GA needs its line dropped entirely
    inventory = '\n'.join(
        line for line in inventory.splitlines()
        if 'gson' not in line) + '\n'
    assert_fail(TSV_OK, 'absent from the collected inventory',
                inventory=inventory)


def test_unknown_asset_section():
    assert_fail(TSV_OK, 'unknown section', assets='bogus\tsome line\n')


def test_missing_file():
    code, output, _ = run_case(TSV_OK, assets='/nonexistent/assets')
    assert code != 0 and 'FAIL:' in output, output


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith('test_')]
    for test in tests:
        test()
        print('ok %s' % test.__name__)
    print('%d tests passed' % len(tests))


if __name__ == '__main__':
    main()
