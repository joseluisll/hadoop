<!--
  Licensed to the Apache Software Foundation (ASF) under one or more
  contributor license agreements.  See the NOTICE file distributed with
  this work for additional information regarding copyright ownership.
  The ASF licenses this file to You under the Apache License, Version 2.0
  (the "License"); you may not use this file except in compliance with
  the License.  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->
# T00022 — collect runs red on a missing MIT slug: resolver maps the full azure-keyvault-core name (2026-11-09 22:36 CET)

## Symptom

Every collect run on this branch failed on two step classes: the
documented-by-design R48 LICENSE.txt findings (9 problems, the manual
baseline is the comparison baseline) and, on top of them, the
"Resolve license texts from the local store" step:

    MISSING local license texts:
      - The MIT License (MIT) (LICENSE-themitlicensemit.txt)

(e.g. collect run 42695882992 on `99b3f00c43a`; same failure on
42692330283 and 42691435653.)

## Root cause

azure-keyvault-core 1.0.0's POM declares the license name
`The MIT License (MIT)`. THIRD-PARTY.txt line for it:

    (The MIT License (MIT)) Microsoft Azure SDK for Key Vault Core
    (com.microsoft.azure:azure-keyvault-core:1.0.0 - ...)

The bash name extractor in `resolve-licenses.sh` balances parentheses,
so it extracts the FULL name `The MIT License (MIT)`;
`license-slugs.sh` had no case for it and the alphanumeric fallback
produced the slug `themitlicensemit`, which has no store text —
`--strict` fails. The commit `254e6b6fa31` generator fix mapped only
the TRUNCATED form (`The MIT License (MIT`), which is what the Python
generator's parser sees; the two parsers see different spellings of
the same name, and the bash side was left unmapped.

## Fix

One-line exact-string mapping in `license-slugs.sh` (the helper shared
by `resolve-licenses.sh` and `normalize-licenses.sh`):

    "the mit license (mit)")                     echo "mit" ;;

It points at the existing generic `texts/LICENSE-mit.txt`; nothing new
ships, the R53 shipped-texts gate is unaffected (LICENSE-binary
already references the `mit` section text via the generator mapping).

## Validation

Against the failed run's real artifact (collect run 42695882992's
THIRD-PARTY.txt, downloaded from CI):

- unpatched resolver: exit 1, the MISSING line above;
- patched resolver: exit 0, 16 texts resolved, 0 missing.

`bash -n` on the modified helper. Landed on `feat/LICENSES` first
(79bd0c6e764, defensive — no trunk dependency declares that name) and
here, so `dev-support/licenses/` stays identical across the tooling
and comparison branches.
