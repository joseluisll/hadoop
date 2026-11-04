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

"""One allowlist of '<kind> <regex>  # reason' rules.

Shared by the comparison modules (lib/artifact_diff.py imports Allowlist from
here) and by replay.py, so that a rule file replayed against an old report
means exactly what it means during a comparison. A kind and a regex are both
regexes; each must match the whole kind or subject. The reason starts at a
'#' with whitespace on both sides (or at the start of the line), so a regex
may contain '#', as API subjects do ('Class#method').

A rule may end with '@arch=<arch>[,<arch>...]' after its reason (T37): it then
applies only in those architectures (simple, secure, ha, mixed, federated).
Elsewhere it does not match, and it is not reported as unused there.
"""

import re


class Allowlist:
    COMMENT = re.compile(r"(^|\s)#(\s|$)")
    ARCH = re.compile(r"\s*@arch=([a-z]+(?:,[a-z]+)*)\s*$")

    def __init__(self, path):
        self.rules = []
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                m = self.COMMENT.search(line)
                body, reason = (line[:m.start()], line[m.end():]) if m else (line, "")
                body = body.strip()
                if not body:
                    continue
                kind, _, regex = body.partition(" ")
                reason = reason.strip()
                archs = None
                m = self.ARCH.search(reason)
                if m:
                    archs = m.group(1).split(",")
                    reason = reason[:m.start()].strip()
                self.rules.append({"kind": kind, "kind_re": re.compile(kind),
                                   "regex": re.compile(regex.strip()),
                                   "pattern": regex.strip(), "reason": reason,
                                   "archs": archs, "line": n, "hits": 0})

    def match(self, kind, subject, arch=None):
        for r in self.rules:
            if r["archs"] and arch not in r["archs"]:
                continue
            if r["kind_re"].fullmatch(kind) and r["regex"].fullmatch(subject):
                r["hits"] += 1
                return r
        return None

    def reset(self):
        """Zero every rule's hits, to replay the rules against another report."""
        for r in self.rules:
            r["hits"] = 0

    def unused(self, arch=None):
        """Rules that matched nothing, as reported by every comparison. A rule
        limited to other architectures is not unused here."""
        return [f"line {r['line']}: {r['kind']} {r['pattern']}" for r in self.rules
                if r["hits"] == 0 and not (r["archs"] and arch not in r["archs"])]
