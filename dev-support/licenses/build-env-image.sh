#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied.  See the License for the specific
# language governing permissions and limitations under the License.
#
# Provide the Docker build-env image as "hadoop-build" for the archive
# ground-truth workflow (licenses-archive-build.yml, reusable), from a
# content-addressed
# GHCR cache: the tag is the hash of every file the image build
# consumes, so a hit is an image built from this commit's exact inputs.
#
# On a miss, an EARLIER run of the same workflow may be building the
# same image right now (two pushes close together). Rather than build
# it twice, wait while an earlier in-flight run's image step
# ("$IMAGE_STEP") is still running, polling the registry, and pull the
# image once it appears; when no earlier run is building (or it built a
# different image, or the wait times out), build and push it here.
# A workflow concurrency group is deliberately NOT used: GitHub keeps one
# pending run per group and cancels the rest, and a cancelled archive run
# fails the per-push R10 drift gate for that commit.
#
# The wait is an optimisation only: any GitHub API failure ends it and
# the image is built, never skipped.
#
# Environment (all set by GitHub Actions except the tuning knobs):
#   GITHUB_REPOSITORY, GITHUB_REPOSITORY_OWNER, GITHUB_RUN_ID, GH_TOKEN
#   IMAGE_STEP          name of the workflow step that runs this script
#   WAIT_MAX_SECONDS    longest wait for an earlier build (default 2400)
#   WAIT_POLL_SECONDS   registry poll interval (default 30)
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
docker_dir="$root/dev-support/docker"
step="${IMAGE_STEP:?IMAGE_STEP must name the workflow step running this script}"
wait_max="${WAIT_MAX_SECONDS:-2400}"
poll="${WAIT_POLL_SECONDS:-30}"

owner="$(tr '[:upper:]' '[:lower:]' <<<"${GITHUB_REPOSITORY_OWNER}")"
image="ghcr.io/${owner}/hadoop-build-ubuntu_24"
hash="$(cat "$docker_dir/Dockerfile_ubuntu_24" \
             "$docker_dir"/pkg-resolver/* \
             "$docker_dir/hadoop_env_checks.sh" \
   | sha256sum | cut -d' ' -f1)"
tag="${image}:cache-${hash}"

use_cached() {
  docker pull -q "$tag" >/dev/null 2>&1 || return 1
  docker tag "$tag" hadoop-build
}

# Ids of earlier runs of this workflow whose image step is still running.
# Prints nothing on any API error (the caller then builds).
earlier_builders() {
  local wf runs id
  wf="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}" \
          --jq .workflow_id 2>/dev/null)" || return 0
  runs="$(gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/${wf}/runs?status=in_progress&per_page=50" \
            --jq ".workflow_runs[] | select(.id < ${GITHUB_RUN_ID}) | .id" 2>/dev/null)" || return 0
  for id in $runs; do
    gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${id}/jobs" \
      --jq ".jobs[].steps[]? | select(.name == \"${step}\" and .status == \"in_progress\") | .name" \
      2>/dev/null | grep -q . && echo "$id"
  done
  return 0
}

if use_cached; then
  echo "Cache hit: using ${tag}"
  exit 0
fi

waited=0
while builders="$(earlier_builders)"; [[ -n "$builders" ]]; do
  if (( waited >= wait_max )); then
    echo "Waited ${waited}s for earlier run(s) $(tr '\n' ' ' <<<"$builders")to build the image; building it here"
    break
  fi
  echo "Cache miss, but earlier run(s) $(tr '\n' ' ' <<<"$builders")are building the build-env image; waiting (${waited}s)"
  sleep "$poll"
  waited=$((waited + poll))
  if use_cached; then
    echo "Cache hit after waiting ${waited}s: using ${tag}"
    exit 0
  fi
done

# the earlier build may have finished between the last poll and its exit
if use_cached; then
  echo "Cache hit: using ${tag}"
  exit 0
fi

echo "Cache miss: building the build-env image, pushing ${tag}"
docker build --platform linux/amd64 -t hadoop-build \
  -f "$docker_dir/Dockerfile_ubuntu_24" "$docker_dir"
docker tag hadoop-build "$tag"
docker push -q "$tag"
