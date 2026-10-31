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
# by merging that base (fork workflows, other JIRAs) is left out. Changes to
# the fork's own .github/ files are dropped as well: those PREPARATION adds or
# changes on top of the trunk it is built on, and those that "Fork-only"
# commits in the feature's history touch (older PREPARATIONs). Changes to
# other .github/ files (e.g. .github/gha-tests/) are kept. The result is
# applied on top of apache/hadoop trunk as a single commit.
#
# Usage: make-upstream-branch.sh <feature-branch> [<upstream-branch>]
#   <feature-branch> is feat/<name> (e.g. feat/HADOOP-12345).
#   <upstream-branch> defaults to <name> (e.g. HADOOP-12345).
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
#   UPSTREAM_AUTHOR  author and committer, as "Name <email>"
#                    (default: git config user.name and user.email)
#
# The commit message joins the feature's commits that start with its JIRA
# (the start of <name>, e.g. HADOOP-12345) and change something outside the
# fork's own files (or else takes its oldest commit), without Claude-Session
# lines, and with Claude as co-author. The new branch is only created
# locally; push it yourself once reviewed.
#
# Exit status: 0 created, 3 nothing outside the fork's own files to send,
# other on error.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  sed -n '20,57p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

feature=$1
name=${feature#feat/}
target=${2:-${name}}
# The JIRA the feature's commits start with.
if [[ "${name}" =~ ^[A-Z][A-Z0-9]*-[0-9]+ ]]; then
  jira=${BASH_REMATCH[0]}
else
  jira=${name}
fi
fork_remote=${FORK_REMOTE:-origin}
fork_base=${FORK_BASE:-PREPARATION}
upstream_remote=${UPSTREAM_REMOTE:-apache}
upstream_url=${UPSTREAM_URL:-https://github.com/apache/hadoop.git}
upstream_branch=${UPSTREAM_BRANCH:-trunk}
author=${UPSTREAM_AUTHOR:-"$(git config user.name || true) <$(git config user.email || true)>"}
co_author="Co-Authored-By: Claude <noreply@anthropic.com>"

if [[ ! "${author}" =~ ^([^<>]*[^<>[:space:]])\ \<([^<>[:space:]]+@[^<>[:space:]]+)\>$ ]]; then
  echo "ERROR: no author; set UPSTREAM_AUTHOR=\"Name <email>\" or git config user.name/user.email." >&2
  exit 1
fi
author_name=${BASH_REMATCH[1]}
author_email=${BASH_REMATCH[2]}

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

# The fork's own .github/ files, which never go to apache/hadoop: those the
# current PREPARATION adds or changes on top of the trunk it is built on, and
# those that "Fork-only" commits in the feature's history touch.
git fetch --quiet "${fork_remote}" "${fork_base}"
fork_ref="${fork_remote}/${fork_base}"
fork_files=$( {
  git diff --name-only "$(git merge-base "${upstream_ref}" "${fork_ref}")" "${fork_ref}" -- .github
  git log --format= --name-only -E --grep='^Fork-only' "${base_ref}..${feature_ref}" -- .github
} | sed '/^$/d' | sort -u)
fork_excludes=()
while read -r path; do
  if [[ -n "${path}" ]]; then fork_excludes+=(":(exclude,literal)${path}"); fi
done <<< "${fork_files}"

# Only the feature branch's own changes, without the fork's own files.
patch=$(mktemp)
trap 'rm -f "${patch}"' EXIT
git diff --binary "${base_ref}...${feature_ref}" -- . "${fork_excludes[@]}" > "${patch}"
if [[ ! -s "${patch}" ]]; then
  echo "Nothing to do: ${feature} has no changes outside the fork's own files relative to its base."
  exit 3
fi

# The message comes from the feature's own commits: those that name its JIRA
# and change something outside the fork's own files, oldest first, so
# empty "re-trigger CI" commits are skipped. Once PREPARATION is rebuilt,
# commits that came in by merging an older PREPARATION are in this range too.
commits=()
while read -r commit; do
  if ! git diff --quiet "${commit}^" "${commit}" -- . "${fork_excludes[@]}"; then
    commits+=("${commit}")
  fi
done < <(git rev-list --reverse --no-merges -E --grep="^${jira}([^0-9]|$)" \
  "${base_ref}..${feature_ref}")
if [[ ${#commits[@]} -eq 0 ]]; then
  commits=("$(git rev-list --reverse --no-merges "${base_ref}..${feature_ref}" | head -n 1)")
fi

# A commit's body without its trailers and Claude session links.
body_of() {
  git log -1 --format=%b "$1" \
    | grep -v -i -E '^(Co-Authored-By|Claude-Session):|claude\.ai/code/session' \
    | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' || true
}

# The oldest commit's subject and body, then each later commit's subject
# (without the JIRA prefix) and body.
message=$(git log -1 --format=%s "${commits[0]}")
body=$(body_of "${commits[0]}")
if [[ -n "${body}" ]]; then message+=$'\n\n'"${body}"; fi
for commit in "${commits[@]:1}"; do
  subject=$(git log -1 --format=%s "${commit}" | sed -E "s/^${jira}[.:]?[[:space:]]*//")
  message+=$'\n\n'"${subject}"
  body=$(body_of "${commit}")
  if [[ -n "${body}" ]]; then message+=$'\n\n'"${body}"; fi
done

# Their Co-Authored-By trailers, once each; Claude stays as co-author.
trailers=$(for commit in "${commits[@]}"; do
  git log -1 --format=%B "${commit}" | grep -i '^Co-Authored-By:' || true
done | awk '!seen[tolower($0)]++')
if ! grep -q -i -E '^Co-Authored-By: Claude( .*)? <noreply@anthropic\.com>$' <<< "${trailers}"; then
  trailers=$(printf '%s\n%s' "${trailers}" "${co_author}" | sed '/^$/d')
fi
message+=$'\n\n'"${trailers}"

git checkout --quiet -B "${target}" "${upstream_ref}"
git apply --index --3way "${patch}"
GIT_AUTHOR_NAME="${author_name}" GIT_AUTHOR_EMAIL="${author_email}" \
  GIT_COMMITTER_NAME="${author_name}" GIT_COMMITTER_EMAIL="${author_email}" \
  git commit --quiet -m "${message}"

echo "Created ${target} on ${upstream_ref}:"
git log --oneline -1
git diff --stat "${upstream_ref}" "${target}"
dropped=$(git diff --name-only "${base_ref}...${feature_ref}" -- .github \
  | grep -F -x -f <(printf '%s\n' "${fork_files}") || true)
if [[ -n "${dropped}" ]]; then
  echo "Left out (fork-only):"
  echo "${dropped}" | sed 's/^/  /'
fi
