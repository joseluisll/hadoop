<!--
   Licensed to the Apache Software Foundation (ASF) under one or more
   contributor license agreements.  See the NOTICE file distributed with
   this work for additional information regarding copyright ownership.
   The ASF licenses this file to you under the Apache License, Version 2.0
   (the "License"); you may not use this file except in compliance with
   the License.  You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.-->
# R7 non-Maven assets, stages A+B: curation fix + source-tree gate, 2026-11-08 ~09:30

Requirement 7 (non-Maven assets in the inventory) gets a staged
implementation. Stages A and B landed here; the archive-side asset
gate (stage C) is open.

## What the audit found (evidence: source tree + the untarred archive
of ground-truth run 42374519973-full)

The curated asset curation traces back to the hand-maintained root
`LICENSE.txt` and had rotted in three places, all invisible to the jar
gates because none of it is a jar:

1. **Stale webapp assets, listed yet absent** — `nvd3-1.8.5.*`,
   `angular-1.6.4.min.js`, `angular-nvd3-1.0.9.min.js`,
   `angular-route-1.6.4.min.js` and `d3-3.5.17.min.js` are listed in
   `LICENSE.txt` and `manifest-assets.txt` but were removed from
   `hadoop-hdfs/src/main/webapps/static/` upstream long ago. The
   generated `LICENSE-binary` inherited all five (the
   listed-yet-absent class of the pjfanning audit, mirrored).
2. **Shipped asset, unlisted** — the source tree (and therefore the
   tarball) carries `d3-v4.1.1.min.js` (added by HDFS-10534); neither
   `LICENSE.txt` nor `LICENSE-binary` stated its BSD-3-Clause license.
3. **Stale native curation with an unlisted replacement** —
   HADOOP-17292 (2020) removed hadoop-common's bundled lz4 sources;
   `Lz4Codec` now uses the Maven `at.yawk.lz4:lz4-java` dependency
   (covered jar-side). But `libnativetask.so` SHIPS in
   `lib/native/` and bundles
   `hadoop-mapreduce-client-nativetask/.../native/lz4/lz4.{c,h}`
   (BSD-2) — unlisted anywhere.

## Stage A — curation fix

- `LICENSE.txt`: nvd3 line removed from the Apache-2.0 section;
  `d3-3.5.17.min.js` replaced by `d3-v4.1.1.min.js` under BSD-3-Clause;
  the three angular lines removed from MIT.
- `manifest-assets.txt`: the same five stale entries pruned, d3 replaced
  by the v4.1.1 path, and the stale hadoop-common lz4 brace path
  replaced by the nativetask lz4.c path (116 entries remain).
- `LICENSE-binary` regenerated (302 g:a / 316 version lines unchanged;
  116 asset lines): -nvd3, d3 swap, -angular x3, lz4 path swap.
- `licenses/LICENSE-angular.txt`, `LICENSE-angular-nvd3.txt`,
  `LICENSE-nvd3.txt` deleted — their assets no longer exist (d3.txt
  stays: v4.1.1 is still BSD-3-Clause, same text).

## Stage B — source-tree gate (per-push)

`dev-support/licenses/check-asset-manifest.py` parses
`manifest-assets.txt` and requires every path-style entry to resolve to
at least one file or directory in the source tree (brace `{a,b}` and
`{a|b}` alternation, trailing globs, trailing parenthetical notes
stripped). Package-style entries ("leveldb v1.13",
"atlaskit/... 1.7.4") have no source-tree path and are skipped — they
are validated by the stage C archive gate. Fail-closed: zero parsed
entries, a malformed (non-tab) line, an unreadable manifest, or any
zero-match path entry exits 1 with a listing. Wired into
`licenses.yml` after the R10 drift gate. Verified: bogus entry exits 1;
the fixed manifest exits 0 (25 path-style entries, 91 package-style).

This gate would have caught every finding above the moment the file
was removed.

## Open — stage C (archive-side asset gate)

Enumerate non-jar asset files in the assembled archives and match them
against `manifest-assets.txt`, fail-closed — the archive twin of the
jar enumeration (R36). Two findings drive its design: the d3-v4.1.1
class (a file on disk in the archive whose license the manifest does
not state) and the yarn class (assets embedded INSIDE
`hadoop-yarn-common.jar`, invisible to file-level scans — Hadoop's own
UI code must not be flagged). Design decision pending: scan jars for
embedded webapps/static resources vs curate the jar-embedded set.
