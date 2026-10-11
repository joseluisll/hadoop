#!/usr/bin/env bash
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
#
# The new branch is only created locally; push it yourself once reviewed.

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
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
git fetch --quiet "${fork_remote}" "${fork_base}" "${feature}"

base_ref="${fork_remote}/${fork_base}"
feature_ref="${fork_remote}/${feature}"
upstream_ref="${upstream_remote}/${upstream_branch}"

# Only the feature branch's own changes, without .github/.
patch=$(mktemp)
trap 'rm -f "${patch}"' EXIT
git diff --binary "${base_ref}...${feature_ref}" -- . ':(exclude).github' > "${patch}"
if [[ ! -s "${patch}" ]]; then
  echo "ERROR: ${feature} has no changes outside .github/ relative to ${fork_base}." >&2
  exit 1
fi

# Reuse the message of the oldest commit of the feature branch.
first_commit=$(git rev-list --reverse --no-merges "${base_ref}..${feature_ref}" | head -n 1)
message=$(git log -1 --format=%B "${first_commit}")

git checkout --quiet -B "${target}" "${upstream_ref}"
git apply --index --3way "${patch}"
git commit --quiet -m "${message}"

echo "Created ${target} on ${upstream_ref}:"
git log --oneline -1
git diff --stat "${upstream_ref}" "${target}"
dropped=$(git diff --name-only "${base_ref}...${feature_ref}" -- .github)
if [[ -n "${dropped}" ]]; then
  echo "Left out (fork-only):"
  echo "${dropped}" | sed 's/^/  /'
fi
