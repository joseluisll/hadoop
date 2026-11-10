We have drafted the adoption path and the release-manager documentation for this proposal, and would value input from [~pjfanning] and from the release managers who ran the 3.4.x and 3.5.x releases (Mukund Thakur, Steve Loughran — the hadoop-release-support maintainers).

The two new documents, in the analysis-3.5 package on the feat/LICENSES-3.5 branch:

* adoption-proposal.md — https://github.com/joseluisll/hadoop/blob/feat/LICENSES-3.5/analysis-3.5/adoption-proposal.md — the proposed adoption path in two increments:
  ** Increment 1 (no process change): optional, secret-free GitHub Actions workflows — verify a staged RC publicly (GPG against the project KEYS, SHA-512, license checks on the downloaded tarballs), and optionally produce an unsigned RC bundle (build + license checks in CI) so the release manager does not need to maintain a Docker build host for the heavy part. Everything credential-bearing (signing, staging, Nexus, tagging) stays with the RM, offline.
  ** Increment 2 (the ask): the same license check runs inside create-release on the RC build and fails it unless the license files match the tarballs being voted on. The RM's command line and procedure are unchanged; the RC carries two extra artifacts (THIRD-PARTY.txt and the generated license files), and the vote email links the public verification run.
  ** A documented optional evolution afterwards: create-release downloads a CI-produced unsigned bundle, re-verifies it locally, signs and stages it — the open question there is the Nexus maven staging.
* rm-runbook.md — https://github.com/joseluisll/hadoop/blob/feat/LICENSES-3.5/analysis-3.5/rm-runbook.md — the day-of-release experience from the RM's operator viewpoint, with the evidence each claim rests on.

Questions where your experience would correct our assumptions:

1. Does the runbook's flow match how you actually run a release (create-release on the Docker host, hadoop-release-support for staging and validation)? What did we get wrong?
2. Is release time — inside create-release, after tarball assembly and before signing/staging — the right point to run the license checks? Or would you prefer them elsewhere (a CI check on the staged RC, or a validation target in hadoop-release-support)?
3. Do the increment-1 workflows look useful, or like machinery an RM would never use? They run secret-free on hosted runners; is there an ASF/INFRA constraint we have missed?
4. Is the host-free evolution (CI builds the RC, create-release downloads/signs/stages) worth pursuing, or does the Nexus maven staging make it not worth it?
5. Any objection to the checks failing the RC build (fail closed, with messages naming the exact entries to fix) rather than reporting only?

Happy to adapt the proposal to how you actually run releases — and we can demonstrate the full flow on a fork prototype (create-release in its unsigned mode) before anything lands upstream.
