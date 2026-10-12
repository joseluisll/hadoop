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
# Fork-only helper: builds a branch for an apache/hadoop pull request from a
# feature branch of this fork, leaving out everything that should stay in
# the fork.
#
# The feature branch's own changes are taken relative to the fork's base
# branch (PREPARATION by default), so anything that reached the feature branch
# by merging that base (fork workflows, other JIRAs) is left out. Changes
# under .github/ are dropped as well. The result is applied on top of
# apache/hadoop trunk as a single commit.
#
# Usage: make-upstream-branch.sh <feature-branch> [<upstream-branch>]
#   <upstream-branch> defaults to <feature-branch>-upstream.
#
# Environment:
#   FORK_REMOTE      remote of this fork            (default: origin)
#   FORK_BASE        fork base branch               (default: PREPARATION)
#   UPSTREAM_REMOTE  remote of apache/hadoop        (default: apache)
#   UPSTREAM_URL     URL used to add that remote    (default: https://github.com/apache/hadoop.git)
#   UPSTREAM_BRANCH  apache/hadoop branch to target (default: trunk)
#   BASE_COMMIT      use this commit as the fork base instead of fetching
#                    FORK_BASE (e.g. the base before a PR was merged)
#   FEATURE_COMMIT   use this commit as the feature instead of fetching
#                    <feature-branch> (e.g. a merged PR's head)
#
# The commit keeps the message and author of the feature's oldest commit that
# starts with the feature branch name (its JIRA), or else of its oldest
# commit. The new branch is only created locally; push it yourself once
# reviewed.
#
# Exit status: 0 created, 3 nothing outside .github/ to send, other on error.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  sed -n '20,49p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

feature=$1
target=${2:-${feature}-upstream}
fork_remote=${FORK_REMOTE:-origin}
fork_base=${FORK_BASE:-PREPARATION}
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

if [[ -n "${BASE_COMMIT:-}" ]]; then
  base_ref=${BASE_COMMIT}
else
  git fetch --quiet "${fork_remote}" "${fork_base}"
  base_ref="${fork_remote}/${fork_base}"
fi
if [[ -n "${FEATURE_COMMIT:-}" ]]; then
  feature_ref=${FEATURE_COMMIT}
else
  git fetch --quiet "${fork_remote}" "${feature}"
  feature_ref="${fork_remote}/${feature}"
fi

# Only the feature branch's own changes, without .github/.
patch=$(mktemp)
trap 'rm -f "${patch}"' EXIT
git diff --binary "${base_ref}...${feature_ref}" -- . ':(exclude).github' > "${patch}"
if [[ ! -s "${patch}" ]]; then
  echo "Nothing to do: ${feature} has no changes outside .github/ relative to its base."
  exit 3
fi

# Reuse the message of the oldest commit of the feature branch that names its
# JIRA (the branch name): once PREPARATION is rebuilt, commits that came in by
# merging an older PREPARATION are in this range too.
first_commit=$(git rev-list --reverse --no-merges -E --grep="^${feature}([^0-9]|$)" \
  "${base_ref}..${feature_ref}" | head -n 1)
if [[ -z "${first_commit}" ]]; then
  first_commit=$(git rev-list --reverse --no-merges "${base_ref}..${feature_ref}" | head -n 1)
fi
message=$(git log -1 --format=%B "${first_commit}")
author=$(git log -1 --format='%an <%ae>' "${first_commit}")

git checkout --quiet -B "${target}" "${upstream_ref}"
git apply --index --3way "${patch}"
git commit --quiet --author="${author}" -m "${message}"

echo "Created ${target} on ${upstream_ref}:"
git log --oneline -1
git diff --stat "${upstream_ref}" "${target}"
dropped=$(git diff --name-only "${base_ref}...${feature_ref}" -- .github)
if [[ -n "${dropped}" ]]; then
  echo "Left out (fork-only):"
  echo "${dropped}" | sed 's/^/  /'
fi
