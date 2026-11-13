# Trunk curation rehearsal — adapting the license system to upstream trunk (T00026 successor evidence)

The pre-PR question this answers: "what does adapting a release line
cost?" — measured on **upstream apache/hadoop trunk**, not on our
fork lines. Run 2026-11-13.

## Method

1. Fresh worktree at trunk tip `891a3202da6` (3.6.0-SNAPSHOT).
2. Applied exactly what the hypothetical initial PR carries: the
   `dev-support/licenses/` tooling directory and the root-pom
   `licenses` profile (135-line pom patch, applied cleanly with
   `git apply` — no conflicts against current trunk).
3. Full reactor build + collection (the source-gates job's own
   commands, natively on this host): `mvn install -DskipTests` +
   `mvn -Plicenses aggregate-add-third-party` — both BUILD SUCCESS.
4. `resolve-licenses.sh --strict` against the fork's `texts/` store.

## Results

| Measure | Value |
|---|---|
| Trunk dependency lines | 321 |
| Trunk distinct g:a | 303 |
| Strict resolve (every license name → local text) | **PASS, exit 0** |
| Store texts resolved | 16 (apache-2.0, bouncycastle, bsd-2/3, cddl-gplv2-ce, edl-1.0, epl-1.0/2.0, go, gplv2-ce, jquery, lgpl-2.1, mit, mpl-1.1, public-domain, w3c) |
| g:a delta vs our curated 3.6.0 RC inventory | **0 / 0** (303 = 303, identical sets) |

## Interpretation

- The license-NAME layer — the part strict resolve tests — covers
  trunk completely with zero additions: 12 distinct license names in
  trunk's dependency set, all mapped by the store (directly or via
  the existing name→slug mappings).
- The g:a identity with our 3.6.0 RC inventory is expected (the fork
  prototype tracks this trunk line) but still removes the main
  unknown: no new coordinates, no unmapped licenses, no curation pass
  needed for this snapshot.
- What this rehearsal does NOT measure: the ARCHIVE-side curation
  (jar-name mappings for unnameable jars, NOTICE exceptions, asset
  manifest) — those need a trunk dist archive build (hours) and are
  exactly what the create-release hook runs at RC time. The 3.5.0 and
  3.6.0 fork passes suggest the magnitude (single-digit mappings/rows
  per line).
- Trunk moves daily: the number to quote in the PR is the METHOD cost
  (one collection + one strict resolve, minutes), not today's zero
  delta.

## Reproduce

Commands above; the rehearsal tree is at
`~/.hermes/cache/scratch/trunk-rehearsal` (delete freely — evidence
regenerable in ~40 min).
