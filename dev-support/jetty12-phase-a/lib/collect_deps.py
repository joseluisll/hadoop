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

"""Merge every module's target/jetty12-deps.txt into one sorted TSV.

Usage: collect_deps.py <source tree>

Output lines: <module path><TAB><group:artifact:type[:classifier]:version:scope>
"""

import os
import re
import sys

# "   org.eclipse.jetty:jetty-http:jar:9.4.58:compile -- module org.eclipse.jetty.http"
COORD = re.compile(r"^\s+([\w.\-]+:[\w.\-]+:[\w.\-]+(?::[\w.\-]+)?:[\w.\-]+:[a-z]+)")


def main(root):
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "src")]
        if os.path.basename(dirpath) != "target" or "jetty12-deps.txt" not in filenames:
            continue
        module = os.path.relpath(os.path.dirname(dirpath), root)
        with open(os.path.join(dirpath, "jetty12-deps.txt"), encoding="utf-8") as f:
            for line in f:
                m = COORD.match(line)
                if m:
                    rows.append((module, m.group(1)))
    for module, coord in sorted(set(rows)):
        print(f"{module}\t{coord}")


if __name__ == "__main__":
    main(sys.argv[1])
