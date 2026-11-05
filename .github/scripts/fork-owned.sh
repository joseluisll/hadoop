#!/usr/bin/env bash
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# Fork-only helper: reads .github/FORK-OWNED, the list of paths this fork
# owns. Sourced by make-upstream-branch.sh and rebuild-preparation.sh.
#
# The list is read from a commit, so a branch newer than PREPARATION is read
# with its own list rather than with PREPARATION's.

# @description  Print the paths .github/FORK-OWNED of <ref> claims, one per
#               line: what a rebuild replaces and what never goes upstream.
#               A directory prefix claims everything under it.
# @param $1     commit-ish holding the list
function fork_owned_prefixes()
{
  git show "${1}:.github/FORK-OWNED" 2>/dev/null \
    | sed -e 's/[[:space:]]*#.*//' -e '/^[[:space:]]*$/d'
}
