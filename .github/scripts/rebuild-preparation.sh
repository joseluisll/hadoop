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
# Fork-only helper: rebuilds the fork's base branch (PREPARATION) as
# apache/hadoop trunk plus a single commit that carries the fork's .github/
# (workflows and scripts), taken as is from the current base branch.
#
# Everything else on the base branch (merged JIRA pull requests) is dropped;
# their upstream branches are built when they are merged, so nothing is lost.
#
# Usage: rebuild-preparation.sh [<target-branch>]
#   <target-branch> defaults to the fork base branch name (PREPARATION).
#
# Environment:
#   FORK_REMOTE      remote of this fork            (default: origin)
#   FORK_BASE        fork base branch               (default: PREPARATION)
#   UPSTREAM_REMOTE  remote of apache/hadoop        (default: apache)
#   UPSTREAM_URL     URL used to add that remote    (default: https://github.com/apache/hadoop.git)
#   UPSTREAM_BRANCH  apache/hadoop branch to build on (default: trunk)
#   SOURCE_COMMIT    take .github/ from this commit instead of fetching
#                    FORK_BASE
#
# The new branch is only created locally; push it yourself once reviewed:
#   git push --force-with-lease=PREPARATION:<old commit> origin <target-branch>:PREPARATION
#
# Exit status: 0 created, 3 the base branch is already up to date, other on error.

set -euo pipefail

if [[ $# -gt 1 || "${1:-}" == -* ]]; then
  sed -n '20,42p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

fork_remote=${FORK_REMOTE:-origin}
fork_base=${FORK_BASE:-PREPARATION}
target=${1:-${fork_base}}
upstream_remote=${UPSTREAM_REMOTE:-apache}
upstream_url=${UPSTREAM_URL:-https://github.com/apache/hadoop.git}
upstream_branch=${UPSTREAM_BRANCH:-trunk}

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: the working tree has uncommitted changes; commit or stash them first." >&2
  exit 1
fi

if ! git remote get-url "${upstream_remote}" >/dev/null 2>&1; then
  git remote add "${upstream_remote}" "${upstream_url}"
fi
git fetch --quiet --no-tags "${upstream_remote}" "${upstream_branch}"
upstream_ref="${upstream_remote}/${upstream_branch}"

if [[ -n "${SOURCE_COMMIT:-}" ]]; then
  source_ref=${SOURCE_COMMIT}
else
  git fetch --quiet "${fork_remote}" "${fork_base}"
  source_ref="${fork_remote}/${fork_base}"
fi

if [[ -z "$(git ls-tree -d "${source_ref}" .github)" ]]; then
  echo "ERROR: ${source_ref} has no .github/ directory." >&2
  exit 1
fi

# The tree we want: upstream with .github/ replaced by the fork's.
git checkout --quiet -B "${target}" "${upstream_ref}"
git rm -r -q --ignore-unmatch .github
git checkout "${source_ref}" -- .github

if git diff --quiet --cached "${source_ref}"; then
  # Put the local branch back where the base branch is; nothing to push.
  git checkout --quiet -B "${target}" "${source_ref}"
  echo "Nothing to do: ${source_ref} is already ${upstream_ref} plus the fork's .github/."
  exit 3
fi

upstream_commit=$(git rev-parse --short "${upstream_ref}")
source_commit=$(git rev-parse --short "${source_ref}")
git commit --quiet -m "Fork-only: GitHub workflows and scripts.

${fork_base} rebuilt as ${upstream_ref} ${upstream_commit} plus .github/ from
${fork_base} ${source_commit}."

echo "Created ${target} on ${upstream_ref}:"
git log --oneline -1
git diff --stat "${upstream_ref}" "${target}"

# What the old base branch had outside .github/ that is now gone.
dropped=$(git diff --stat "${upstream_ref}...${source_ref}" -- . ':(exclude).github')
if [[ -n "${dropped}" ]]; then
  echo "Dropped from ${fork_base} (not in ${upstream_ref}):"
  echo "${dropped}" | sed 's/^/  /'
  git log --oneline --no-merges "${upstream_ref}..${source_ref}" -- . ':(exclude).github' \
    | sed 's/^/  /'
fi
