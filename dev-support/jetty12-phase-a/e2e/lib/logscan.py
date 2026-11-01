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

"""Find class loading, linkage and JAX-RS provider errors in Hadoop logs.

Usage: logscan.py <log dir> <results dir>

Scans every daemon log, .out file, container log under the log dir, and the
scenario logs under <results dir>/scenarios. Prints JSON:
{"<source>": {"<normalized message>": count}}, where source is the daemon
or "containers" / "scenarios". Messages are normalized (ids, numbers,
timestamps masked) so the two sides can be compared.
"""

import collections
import json
import os
import re
import sys

PATTERN = re.compile(
    r"(NoClassDefFoundError|ClassNotFoundException|NoSuchMethodError|NoSuchFieldError"
    r"|LinkageError|AbstractMethodError|IncompatibleClassChangeError"
    r"|ExceptionInInitializerError|UnsupportedClassVersionError|ServiceConfigurationError"
    r"|MessageBodyProviderNotFoundException|MessageBodyWriter not found"
    r"|MessageBodyReader not found|NoContentException|ModelValidationException"
    r"|Could not instantiate|WebApplicationException|IllegalAccessError"
    r"|java\.lang\.VerifyError|ClassCastException)[^\n]{0,300}")
MASKS = [
    (re.compile(r"application_\d+_\d+"), "application_ID"),
    (re.compile(r"container_(e\d+_)?\d+_\d+_\d+_\d+"), "container_ID"),
    (re.compile(r"(job|task|attempt)_\d+_\d+\S*"), r"\1_ID"),
    (re.compile(r"@[0-9a-f]{4,}"), "@HASH"),
    (re.compile(r"\b\d+\b"), "N"),
]


def normalize(msg):
    for regex, repl in MASKS:
        msg = regex.sub(repl, msg)
    return msg.strip()


def source_of(path, log_dir):
    rel = os.path.relpath(path, log_dir)
    if rel.startswith("userlogs" + os.sep):
        return "containers"
    base = os.path.basename(rel)
    # hadoop-<instance>-<daemon>-<host>.log / .out (the harness sets
    # HADOOP_IDENT_STRING to the instance name)
    m = re.match(r"hadoop-([A-Za-z0-9_]+)-", base)
    return m.group(1) if m else base


def scan(path, counts, source):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                for m in PATTERN.finditer(line):
                    counts[source][normalize(m.group(0))] += 1
    except OSError:
        pass


def main(log_dir, res_dir):
    counts = collections.defaultdict(collections.Counter)
    for root in (log_dir, os.path.join(res_dir, "scenarios")):
        for dirpath, _, files in os.walk(root):
            for name in files:
                path = os.path.join(dirpath, name)
                src = "scenarios" if root != log_dir else source_of(path, log_dir)
                scan(path, counts, src)
    print(json.dumps({s: dict(sorted(c.items())) for s, c in sorted(counts.items())},
                     indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
