<!---
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License. See accompanying LICENSE file.
-->

# Harness requirements review, 2026-11-02 00:12

This review checks `HARNESS-REQUIREMENTS.md` and `README.md` against the code
on `feat/HARNESS` at `3094001a345`, in the context of
`JETTY12-MIGRATION-PLAN.md`. Paths are relative to this directory unless they
start with `.github/`. It is a snapshot: no harness code or requirement was
changed for it.

## Verdict

The requirements document describes the harness accurately overall, but the
harness is not ready to trust yet. The newest code has a bug that fails every
normal run, and that code has never run in CI.

| AS-IS result | Count | Requirements |
|---|---|---|
| Met | 58 | All others |
| Partly met | 16 | R2, R10, R14, R30, R34, R37, R42, R52, R57, R64, R67, R69, R70, R76, R78, R79 |
| Not met | 3 | R41, R54, R63 |
| Process rule, cannot be checked from code | 3 | R3, R65, R66 |

R45 is counted as met because it does what it says; what it leaves out is under
"Gaps with no requirement or TO-BE item".

How each finding was established:

- **Reproduced:** the harness's own code was run on synthetic inputs or on the
  live git refs.
- **From reading:** the conclusion comes from reading the code and was not
  executed.

## Serious findings

### R54: every normal run reports FAIL (reproduced)

`lib/ancestry.py:93` writes the verdict `CONTAINED`, but `lib/report.py:99-100`
only accepts `PASS` or `NOT RUN`. With every check green, the report said
`Overall: FAIL` and exited 1. Without `ancestry.json` the same results gave
`PASS` and exit 0.

Until this is fixed, a `run-broken-*` self-check proves nothing, because it
fails regardless of the breakage. The fix is one line.

### R78 to R80 have never run in CI

The latest runs of all five architectures are at `0b2e0bc55`, before
`beb58ec400b` added these checks, and no run branch or tag contains that
commit. The plan requires all five architectures to run after each step, so
step 1 has not met its own rule.

At that commit `simple` 17, `secure` 9, `ha` 5 and `mixed` 6 succeeded and
`federated` 7 failed, so no commit has had all five pass.

Run locally on the live refs:

| Check | Result |
|---|---|
| `lib/ancestry.py` | `CONTAINED` |
| `lib/compare_plan.py`, branch order of the workflow | `PASS`, 51 candidate files, 51 PR files |
| `lib/compare_plan.py`, branch order of the migration plan | `PASS`, 51 candidate files, 51 PR files |

So the candidate equals the PR branches today. What is unproven is that these
checks work in the compare job.

### R41: an empty results file passes (reproduced)

`e2e/run.sh` creates `observations.jsonl` empty, and `lib/compare_e2e.py:180`
only checks that the file exists.

| Baseline | Candidate | Verdict | Should be |
|---|---|---|---|
| Empty | Empty | PASS | NOT RUN |
| Empty | One failing observation | PASS | NOT RUN |

### R63: some rules are too broad

- `obsfield [a-z0-9:-]+/headers/vary` in `e2e/expected-e2e-differences.txt`
  names no ticket. It accepts a `Vary` change on nearly any response, not just
  static files, and that is a difference Jetty 12 could plausibly introduce.
- `classjar` and `class-source-changed` subjects do not contain the destination
  jar, so their rules accept `javax.servlet` classes loaded from any jar. A
  stray new jar would still show in `dist-file-added`.

## Partly met

| Req | Gap |
|---|---|
| R2 | It says every other difference fails, but R37, R38 and R45 list exceptions. The wording should admit them. |
| R10 | Symlinks are also skipped (`dist_files` in `lib/artifact_diff.py`), which is not documented. |
| R14 | A public class removed outright gets no API finding: pairs need the class on both sides. Only check 1 sees it. |
| R30 | "The CORS headers" means three of them; `allow-credentials`, `expose-headers` and `max-age` are compared by name only. |
| R34 | "Every recorded field" is too strong: header values and TLS fields are not masked. |
| R37 | FIXED and candidate-only observations are counted in the report but not listed. |
| R42 | README test lists differ from `unit-tests.sh`, and `quick` runs whole modules for entries with no test list. |
| R52 | With results on one side only, the verdict is NOT RUN and overall INCOMPLETE, not a failure (reproduced). |
| R57 | A project with an existing, unchanged duplicate can be reported as having had none (from reading). |
| R64 | Unannounced rules remain, already tracked by T7 and T21. |
| R67 | The `Vary` rule names no issue, and the job-counter rule names the wrong one (T24). |
| R69 | Nothing asserts that the intended check failed, so a broken run that wrongly passes shows green. |
| R70 | Each job resolves `PREPARATION` separately. If it is rebuilt mid-run, R78 and R79 check a different baseline from the one built (from reading, not observed). |
| R76 | The README gives `PR_BRANCHES` a default, but none exists, so local runs skip the plan check. |
| R78 | "Counts as contained" only works if the whole file matches, so a cherry-pick onto a file the patch also changes is reported as missing (from reading). |
| R79 | See below. |

R79 details:

- A file deleted by a PR branch fails the plan check by mistake (reproduced in
  a throwaway repository). No branch deletes one today.
- `NOTICE-binary` is checked only for certain lines, so an extra edit no branch
  made passes (reproduced in a throwaway repository).
- A single branch's change goes through a three-way merge, not the "tip blob
  applied whole" the text describes.
- The branch order differs from the migration plan (20013 before 20014), though
  both orders pass today.

## Documentation out of date

- **`JETTY12-MIGRATION-PLAN.md`:** it says `ha` run 5 was still running, but it
  succeeded. It also says the `federated` run 7 regression is unidentified,
  while `README.md` and R77 attribute a failure in that run to
  `TestFederationInterceptor#testSubClusterTimeOut`.
- **`README.md`:** the opening table leaves out HADOOP-19970, the largest change
  in scope. It also says the workflow leaves `PR_BRANCHES` empty for `-run-aa-`
  runs, but `&& '' ||` in a GitHub expression returns the branch list. That is
  harmless, because `compare.sh` skips both checks when the two sides are one
  commit.
- **`lib/compare_plan.py`:** the docstring mentions a config file that does not
  exist, and an unused-entry report that does not work as described.

## Gaps with no requirement or TO-BE item

- **Pass to skipped:** a test that passes on the baseline and is skipped on the
  candidate goes unnoticed (reproduced), which could hide a feature that stopped
  working.
- **Maven exit code:** it is ignored when a module has some reports, so a crash
  can silently shrink what gets compared (reproduced with exit 1).
- **Scenarios that die early:** only a timeout is recorded. If a scenario dies
  the same way on both sides, its observations vanish with no failure. A timeout
  on one side is also just a candidate-only observation, which does not fail.
- **Late ancestry check:** R78 runs in the final job, after hours of work, so it
  should also run first.
- **Self-checks:** only `simple` has `aa` or `broken` runs. The last `aa` was on
  2026-11-01, the last broken run on 2026-10-14, and the other four architectures
  show none in their run history.
- **Tests for the comparators:** only the probe has a self-test
  (`e2e/lib/test_probe.py`), which is how the R54 bug got through.
- **As PRs land:** nothing says what to do when one merges. From reading, a
  squash-merged branch would show as `missing` and stop every run until it is
  removed from `PR_BRANCHES`.
- **Plan coverage:** no requirement checks the umbrella's exit criteria, such as
  no Jetty 9.4 artifact left. JDK 21 and 25 and mixed-version runs have no T
  number, and it is undecided whether the harness extends to stages 3 and 4,
  which change behaviour on purpose.
- **Check 4 has no allowlist:** a one-sided flake like `testSubClusterTimeOut`
  fails the run, so "all five pass" depends on luck or a manual exception.

## TO-BE items

Of the 22 open items, T8 and T9 are unconfirmed because their scenarios were not
read. The other 20 show no sign of being implemented, with this confidence:

| Evidence | Items |
|---|---|
| Searched for or reproduced | T1, T2, T3, T13, T14, T20, T21, T24, T25 |
| Nothing seen in the code read, not searched individually | T4, T7, T10, T11, T12, T15, T17, T18, T19, T22, T23 |

`probe.py raw` (R31) exists and `e2e/lib/test_probe.py` exercises it, but
`e2e/lib/env.sh` has no helper for it and no scenario uses it, as T1 says.

## Recommended order

Add a new first item to step 1: fix R54, R41 and the pass-to-skipped gap, then
run all five architectures plus an `aa` and a `broken` run. Step 2 detection work
should wait until verdicts can be trusted.

Step 0 decisions:

| Item | Recommendation |
|---|---|
| T3 | Report these classes first, and make them fail only after T10 and T25 remove the noise. |
| T17 | Yes for merge-order runs on checks 1, 2 and 5, because each ticket ships on its own. |
| T18 | No for now: a manual check at release-note time is enough. |
| T7 with T21 | Announce the HADOOP-20013 jar removal in its release note. The HADOOP-20014 changes are only shaded test classes, so one line there is enough. |

## What this review did not cover

- The scenario scripts, `e2e/lib/conf.sh` and the `ha`, `federated` and `mixed`
  architecture files were not read in full. R23 and R25 are checked on structure
  and scenario lists, not on each scenario's content.
- R80 ran only on synthetic data, because no real reports were downloaded. The
  53 and 61 counts in T7 and T21 are unconfirmed.
- No Maven build, cluster or CI job was run.
