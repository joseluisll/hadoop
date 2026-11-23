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
# apache/hadoop trunk plus a single commit that carries the paths
# .github/FORK-OWNED lists (the fork's .github/ and dev-support material),
# taken as is from the branch that keeps them up to date.
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
#   SOURCE_BRANCH    branch the fork's own paths are taken from
#                    (default: feat/HARNESS). These are the prefixes in
#                    .github/FORK-OWNED of that branch.
#   SOURCE_COMMIT    take those paths from this commit instead of fetching
#                    SOURCE_BRANCH
#
# The new branch is only created locally; push it yourself once reviewed:
#   git push --force-with-lease=PREPARATION:<old commit> origin <target-branch>:PREPARATION
#
# Exit status: 0 created, 3 the base branch is already up to date, other on error.

set -euo pipefail

# The paths .github/FORK-OWNED of <ref> claims, one per line: what a rebuild
# replaces and what never goes upstream. A directory prefix claims everything
# under it. Inlined in every script that needs it: the workflows run them from
# $RUNNER_TEMP, where no sibling file is copied along.
function fork_owned_prefixes()
{
  git show "${1}:.github/FORK-OWNED" 2>/dev/null \
    | sed -e 's/[[:space:]]*#.*//' -e '/^[[:space:]]*$/d'
}

if [[ $# -gt 1 || "${1:-}" == -* ]]; then
  sed -n '20,46p' "$0" | sed 's/^# \{0,1\}//'
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
  source_branch=${SOURCE_BRANCH:-feat/HARNESS}
  git fetch --quiet "${fork_remote}" "${source_branch}"
  source_ref="${fork_remote}/${source_branch}"
fi

fork_prefixes=$(fork_owned_prefixes "${source_ref}")
if [[ -z "${fork_prefixes}" ]]; then
  echo "ERROR: ${source_ref} has no .github/FORK-OWNED, or it claims no paths." >&2
  exit 1
fi

# The tree we want: upstream with the fork's own paths taken from the source.
git checkout --quiet -B "${target}" "${upstream_ref}"
while IFS= read -r prefix; do
  git rm -r -q --ignore-unmatch -- "${prefix}"
  git checkout "${source_ref}" -- "${prefix}"
done <<< "${fork_prefixes}"

# The old base branch, to tell a real change from a rebuild of the same tree.
git fetch --quiet "${fork_remote}" "${fork_base}"
base_ref="${fork_remote}/${fork_base}"

if git diff --quiet --cached "${base_ref}"; then
  # Put the local branch back where the base branch is; nothing to push.
  git checkout --quiet -B "${target}" "${base_ref}"
  echo "Nothing to do: ${base_ref} is already ${upstream_ref} plus the fork's own paths."
  exit 3
fi

upstream_commit=$(git rev-parse --short "${upstream_ref}")
source_commit=$(git rev-parse --short "${source_ref}")
git commit --quiet -m "Fork-only: the fork's own files.

${fork_base} rebuilt as ${upstream_ref} ${upstream_commit} plus the fork's own
paths from ${source_ref} ${source_commit}."

echo "Created ${target} on ${upstream_ref}:"
git log --oneline -1
git diff --stat "${upstream_ref}" "${target}"

# What the old base branch had outside the fork's own paths that is now gone.
fork_excludes=()
while IFS= read -r prefix; do
  fork_excludes+=(":(exclude)${prefix}")
done <<< "${fork_prefixes}"
dropped=$(git diff --stat "${upstream_ref}...${base_ref}" -- . "${fork_excludes[@]}")
if [[ -n "${dropped}" ]]; then
  echo "Dropped from ${fork_base} (not in ${upstream_ref}):"
  echo "${dropped}" | sed 's/^/  /'
  git log --oneline --no-merges "${upstream_ref}..${base_ref}" -- . "${fork_excludes[@]}" \
    | sed 's/^/  /'
fi
