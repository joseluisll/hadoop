# Draft inline review comments: apache/hadoop#8809 (HDFS-17992)

Status: DRAFT, for the reviewer to think about. Nothing has been posted to GitHub or JIRA.
Line numbers are against PR head 7a79f383da3 (right side of the diff). The evidence for each
comment is in `HDFS-17992-pr8809-review.md`, under "Reviewer notes".

Each comment has:
- **Severity**: blocking, suggestion, or nit.
- **Open question**: what to decide before posting.

---

## Review summary (top-level body)

> Thanks for the clear write-up and the focused fix. I built it on Linux (JDK 21) and checked:
>
> - `TestFileChecksumHelper` passes on the PR. On trunk's helper, 3 of 6 fail as described.
> - No regressions in hadoop-hdfs, which Yetus doesn't run here: `TestFileChecksum` 70/70 and
>   `TestGetFileChecksum` 2/2.
> - MiniDFSCluster tests with a real empty replica, replicated and RS-6-3-1024k, pass on the PR
>   and fail on trunk with the reported `readInt out of bounds: buf.length=0, offset=0`.
>
> The change looks correct to me. I've left two things I'd like addressed (the #8322
> interaction and an end-to-end test) and a few suggestions and nits inline.

**Open question:** Approve with comments, or "Comment" only? You are not a committer, so an
approval doesn't count toward merge, but it signals that you tested the change.

---

## C1: `TestFileChecksumHelper.java` line 71 (`super(..., null, null, mode)`)

**Severity:** blocking (soft). It only breaks once #8322 lands, but it will break.

> `client` is passed as `null` here. HDFS-17803 / #8322 makes `makeEmptyFileChecksum()` read
> `client.getConf().getDefaultChecksumOpt()` in COMPOSITE_CRC mode. With #8322 applied on top of
> this PR (resolving the one conflicting hunk by moving its branch into
> `makeEmptyFileChecksum()`), `testCompositeCrcOfZeroLengthFileWithEmptyBlock` fails:
>
> ```
> NullPointerException: Cannot invoke "org.apache.hadoop.hdfs.DFSClient.getConf()" because "this.client" is null
>   at ...FileChecksumHelper$FileChecksumComputer.makeEmptyFileChecksum(FileChecksumHelper.java:259)
>   at ...FileChecksumHelper$FileChecksumComputer.compute(FileChecksumHelper.java:244)
> ```
>
> Could the fake take a mocked `DFSClient` that returns a real `DfsClientConf`, so this test
> survives whichever of the two PRs lands second?

**Open questions:**
- Do you also want to propose the merge resolution on #8322? You already commented on
  HDFS-17803.
- The NPE comes from the no-blocks reference checksum (`compute()` line 244), not from the
  empty-block path. Is that worth mentioning, or is it noise?

---

## C2: `FileChecksumHelper.java` line 326 (`if (consumedLength == 0)`)

**Severity:** suggestion.

> This infers "the DataNode returned no CRC" from the NameNode's block length. They agree
> today, but if they ever diverge (a stale length, or a DN that returns 4 bytes for an empty
> block), the offsets shift silently, which is the failure mode this PR fixes. Could
> `populateBlockChecksumBuf` record each block's returned checksum length so this loop walks
> that list instead? Or, at minimum, after the loop check that
> `checksumOffset == blockChecksumBuf.getLength()` and throw if it doesn't, so a mismatch fails
> loudly.

**Open questions:**
- Is "at minimum, the post-loop check" the actual ask? It's cheap, and it is also what would
  make the trailing-empty-block test (C5) meaningful.
- Watch out for the range-query path (`length < file length`): there the last block's CRC
  covers a prefix, but the DN still returns 4 bytes. The check must still hold there. Verify
  before suggesting it.

---

## C3: `FileChecksumHelper.java` lines 341–344 (`if (sumBlockLengths == 0) return makeEmptyFileChecksum();`)

**Severity:** suggestion, documentation only.

> Returning the legacy MD5 magic value here keeps "zero-length with an empty block" equal to
> "zero-length with no blocks", which is what DistCp needs. Could the comment say that this
> deliberately follows the no-blocks case, and that HDFS-17803 will change both together?

**Open question:** Is this worth a comment at all, given that C1 already links the two PRs?
You could fold it into C1.

---

## C4: `TestFileChecksumHelper.java` line 199 (`assertNotEquals(null, ...)`)

**Severity:** nit.

> `assertNotNull(computer.populateBlockChecksumBuf(response))` reads better.

---

## C5: `TestFileChecksumHelper.java` line 187 (`setLogLevel(..., Level.DEBUG)`)

**Severity:** nit.

> The DEBUG level is never restored, so it leaks into later tests in the same JVM. Could you
> save the previous level and restore it in `finally`?

---

## C6: `TestFileChecksumHelper.java` line 150 (`testCompositeCrcSkipsTrailingEmptyBlock`)

**Severity:** nit / observation.

> This also passes on trunk: the old code reads 4 bytes past the valid data, and they happen
> to be zeros (as the JIRA notes). So it documents behaviour but doesn't guard the fix. With
> the check from C2 it would.

**Open question:** Drop this if you drop C2. On its own it is only an observation.

---

## C7: top-level or `TestFileChecksumHelper.java` line 64 (`FakeChecksumComputer`)

**Severity:** blocking (soft). This is the main test-coverage ask.

> All the new tests use the fake computer, so the DataNode side (that an empty replica really
> yields an empty block checksum) isn't covered. Could you add a MiniDFSCluster test with a real
> empty finalized replica? I have two that pass on this PR and fail on trunk with the reported
> AIOOBE: one replicated (`TestGetFileChecksum`) and one RS-6-3-1024k (`TestFileChecksum`).
> They also keep passing with #8322 merged, unlike the unit test in C1. Diff: <link or attach>.

**Open questions:**
- How do you share the tests: inline code (long), a gist, an attachment on HDFS-17992, or a
  suggested commit? The diff is `candidate-minicluster-test.diff` (~16k characters).
- Should this be blocking? Yetus +1 plus the unit tests may be enough for some committers.
  Asking is reasonable, but "nice to have" is also defensible.
- The EC test relies on `TestFileChecksum.setup()`, which sets `FileChecksumHelper.LOG` to
  DEBUG. On trunk it therefore fails with the debug-path `IllegalArgumentException` rather than
  the AIOOBE. Mention it, or leave it out?

---

## Not included (considered and dropped)

- The `crcBytes.length == 0 ? "empty"` change at line 470 is correct and needs no comment.
- The loop now uses `consumedLength` for every block instead of `getBlockSize()` for all but
  the last. This is equivalent for non-last blocks, so there's nothing to say.
