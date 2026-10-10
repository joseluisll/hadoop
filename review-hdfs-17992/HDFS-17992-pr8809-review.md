# Draft review: apache/hadoop#8809 (HDFS-17992)

Status: DRAFT, not posted. Reviewed head 7a79f383da3 (state checked 2026-10-10: PR open,
Yetus +1, no reviews; JIRA Open, unassigned). Linux test results added 2026-10-10.

---

Thanks for the clear write-up and the focused fix. I built the PR locally (Linux, JDK 21) and
checked the claims in the description:

- `TestFileChecksumHelper` on the PR: `Tests run: 6, Failures: 0, Errors: 0`.
- The same test file against trunk's `FileChecksumHelper` (main code reverted): 3 of 6 fail
  exactly as described:
  - `testCompositeCrcOfZeroLengthFileWithEmptyBlock`:
    `ArrayIndexOutOfBoundsException: readInt out of bounds: buf.length=0, offset=0`
  - `testCompositeCrcSkipsEmptyBlockInTheMiddle`:
    `expected: <COMPOSITE-CRC32C:0xf1f974d9> but was: <COMPOSITE-CRC32C:0xd0c33523>`
  - `testPopulateEmptyCompositeBlockChecksumWithDebugLogging`:
    `IllegalArgumentException: Unexpected byte[] length '0' for single CRC. Contents: []`
- No regressions in hadoop-hdfs, which Yetus does not run for this PR because only
  hadoop-hdfs-client changed:
  - `TestFileChecksum`: `Tests run: 70, Failures: 0, Errors: 0, Skipped: 0`
  - `TestGetFileChecksum`: `Tests run: 2, Failures: 0, Errors: 0, Skipped: 0`
- End to end with a real empty replica on a MiniDFSCluster (tests below): both pass on the PR.
  Against trunk's `FileChecksumHelper`, both fail with the reported
  `ArrayIndexOutOfBoundsException: readInt out of bounds: buf.length=0, offset=0` at
  `FileChecksumHelper$FileChecksumComputer.makeCompositeCrcResult`. For the erasure-coded
  case the DataNode replies `blockChecksum=empty` for the RS-6-3-1024k block group, and the PR
  logs `Skipped empty block index 0`.

The DataNode side matches the premise: `BlockChecksumHelper#computeCompositeCrc` and
`#reassembleNonStripedCompositeCrc` compose nothing for a 0-length block, so
`CrcComposer#digest()` returns `byte[0]`. For files without empty blocks the new loop gives
the same result as the old one.

A few comments:

**1. Interaction with HDFS-17803 / #8322.** Both PRs rewrite the empty-file branch of
`compute()`. Applying #8322 on top of this PR conflicts in that one hunk of
`FileChecksumHelper.java`; `TestGetFileChecksum.java` merges cleanly. The natural resolution
is to move #8322's COMPOSITE_CRC branch into `makeEmptyFileChecksum()`, which then also covers
the "all blocks empty" case:

```java
FileChecksum makeEmptyFileChecksum() {
  if (combineMode == ChecksumCombineMode.COMPOSITE_CRC) {
    ChecksumOpt checksumOpt = client.getConf().getDefaultChecksumOpt();
    return new CompositeCrcFileChecksum(
        0, checksumOpt.getChecksumType(), checksumOpt.getBytesPerChecksum());
  }
  ... // existing MD5 magic value
}
```

With that resolution, the MiniDFSCluster tests pass: `TestGetFileChecksum` reports
`Tests run: 4, Failures: 0, Errors: 0`, which includes #8322's `testEmptyFileChecksumType` and
the empty-block test below. The EC test also passes. However, the new unit test
`TestFileChecksumHelper#testCompositeCrcOfZeroLengthFileWithEmptyBlock` fails
(`Tests run: 6, Failures: 0, Errors: 1`):

```
java.lang.NullPointerException: Cannot invoke "org.apache.hadoop.hdfs.DFSClient.getConf()" because "this.client" is null
	at org.apache.hadoop.hdfs.FileChecksumHelper$FileChecksumComputer.makeEmptyFileChecksum(FileChecksumHelper.java:259)
	at org.apache.hadoop.hdfs.FileChecksumHelper$FileChecksumComputer.compute(FileChecksumHelper.java:244)
	at org.apache.hadoop.hdfs.TestFileChecksumHelper.compositeChecksum(TestFileChecksumHelper.java:121)
```

`FakeChecksumComputer` passes `client = null`. Could the fake pass a (mocked) `DFSClient` with
a `DfsClientConf`, so the test survives whichever PR lands second?

**2. Detecting an empty block.** The loop decides that a block has no CRC from
`consumedLength == 0`, which comes from the NameNode's block length (or the requested range).
The thing that actually matters is whether the DataNode returned 0 or 4 bytes for that block.
These normally agree, but if they ever disagree, the offsets shift silently again. That is the
same failure mode this PR fixes. An option is to record each block's returned checksum length
in `populateBlockChecksumBuf` and walk that list, or at least check that `checksumOffset`
ends equal to `blockChecksumBuf.getLength()` and fail loudly if it doesn't. Optional; the
current approach is fine for the reported cases.

**3. Return type when every block is empty.** Returning `makeEmptyFileChecksum()` (the legacy
`MD5MD5CRC32GzipFileChecksum`) keeps a zero-length file with an empty block equal to one with
no blocks. That is what DistCp needs: the source and target compare equal. It is worth stating
that this deliberately inherits the HDFS-17803 behaviour, and that HDFS-17803 is the place to
change both cases together. Point 1 shows how.

**4. Tests.**
- `assertNotEquals(null, computer.populateBlockChecksumBuf(response))` should be
  `assertNotNull(...)`.
- `GenericTestUtils.setLogLevel(FileChecksumHelper.LOG, Level.DEBUG)` is never restored.
  Please save the old level and restore it in `finally` or `@AfterEach`.
- `testCompositeCrcSkipsTrailingEmptyBlock` also passes on trunk, because it reads 4 zero bytes
  past the valid data, as the JIRA says. So it documents behaviour but does not guard the fix.
  Making it fail on trunk would need a check like the one in point 2.
- All tests use the fake computer. Please consider adding end-to-end tests with a real empty
  replica, which cover the DataNode side too. They also keep working after #8322 lands, unlike
  the unit test in point 1. These two pass on this PR and fail on trunk with the reported
  AIOOBE:

In `TestGetFileChecksum` (replicated):

```java
/**
 * HDFS-17992: a zero-length file that keeps one empty, finalized block must
 * get the same COMPOSITE_CRC checksum as a zero-length file without blocks.
 */
@Test
public void testCompositeCrcOfZeroLengthFileWithEmptyBlock()
    throws Exception {
  DFSClient client = dfs.getClient();
  ClientProtocol nn = client.getNamenode();
  String src = "/zeroLengthWithEmptyBlock";
  HdfsFileStatus stat = nn.create(src, FsPermission.getFileDefault(),
      client.getClientName(),
      new EnumSetWritable<>(EnumSet.of(CreateFlag.CREATE)), true,
      (short) 1, BLOCKSIZE, CryptoProtocolVersion.supported(), null, null);
  LocatedBlock lb = nn.addBlock(src, client.getClientName(), null, null,
      stat.getFileId(), null, null);
  // Give the block a real, empty, finalized replica, as lease recovery does
  // when a writer dies after setting up the pipeline but before sending data.
  DataNode dn = cluster.getDataNode(lb.getLocations()[0].getIpcPort());
  Replica replica =
      cluster.getFsDatasetTestUtils(dn).createFinalizedReplica(lb.getBlock());
  dn.notifyNamenodeReceivedBlock(lb.getBlock(), null,
      replica.getStorageUuid(), false);
  while (!nn.complete(src, client.getClientName(), lb.getBlock(),
      stat.getFileId())) {
    Thread.sleep(100);
  }
  assertEquals(1, client.getLocatedBlocks(src, 0).locatedBlockCount());
  assertEquals(0, dfs.getFileStatus(new Path(src)).getLen());

  Path noBlocks = new Path("/zeroLengthWithoutBlocks");
  dfs.create(noBlocks).close();

  Configuration crcConf = new Configuration(conf);
  crcConf.set(HdfsClientConfigKeys.DFS_CHECKSUM_COMBINE_MODE_KEY, "COMPOSITE_CRC");
  try (FileSystem crcFs = FileSystem.newInstance(dfs.getUri(), crcConf)) {
    assertEquals(crcFs.getFileChecksum(noBlocks),
        crcFs.getFileChecksum(new Path(src)));
  }
}
```

In `TestFileChecksum` (erasure-coded, RS-6-3-1024k, reusing the class's `ecDir`, cluster and
`setup()`):

```java
/**
 * HDFS-17992: a zero-length erasure-coded file that keeps one empty,
 * finalized block group must get the same COMPOSITE_CRC checksum as a
 * zero-length erasure-coded file without blocks.
 */
@Test
@Timeout(value = 90)
public void testStripedCompositeCrcOfZeroLengthFileWithEmptyBlockGroup()
    throws Exception {
  setup(ChecksumCombineMode.COMPOSITE_CRC.name());
  ClientProtocol nn = client.getNamenode();
  String src = ecDir + "/zeroLengthWithEmptyBlockGroup";
  HdfsFileStatus stat = nn.create(src, FsPermission.getFileDefault(),
      client.getClientName(),
      new EnumSetWritable<>(EnumSet.of(CreateFlag.CREATE)), true,
      (short) 1, blockSize, CryptoProtocolVersion.supported(), null, null);
  LocatedStripedBlock bg = (LocatedStripedBlock) nn.addBlock(src,
      client.getClientName(), null, null, stat.getFileId(), null, null);
  // Give every internal block a real, empty, finalized replica, as lease
  // recovery does when a writer dies before sending any data.
  for (int i = 0; i < bg.getLocations().length; i++) {
    ExtendedBlock internal = StripedBlockUtil.constructInternalBlock(
        bg.getBlock(), ecPolicy, bg.getBlockIndices()[i]);
    DataNode dn = cluster.getDataNode(bg.getLocations()[i].getIpcPort());
    Replica replica =
        cluster.getFsDatasetTestUtils(dn).createFinalizedReplica(internal);
    dn.notifyNamenodeReceivedBlock(internal, null,
        replica.getStorageUuid(), false);
  }
  while (!nn.complete(src, client.getClientName(), bg.getBlock(),
      stat.getFileId())) {
    Thread.sleep(100);
  }
  assertEquals(1, client.getLocatedBlocks(src, 0).locatedBlockCount());
  assertEquals(0, fs.getFileStatus(new Path(src)).getLen());

  Path noBlocks = new Path(ecDir + "/zeroLengthWithoutBlocks");
  fs.create(noBlocks).close();

  assertEquals(fs.getFileChecksum(noBlocks),
      fs.getFileChecksum(new Path(src)));
}
```

(Imports needed: `CryptoProtocolVersion`, `CreateFlag`, `FsPermission`, `ClientProtocol`,
`HdfsFileStatus`, `LocatedBlock`/`LocatedStripedBlock`, `ExtendedBlock`, `DataNode`, `Replica`,
`StripedBlockUtil`, `EnumSetWritable`, `EnumSet`, and `FileSystem` and `Test` where missing.
The full diff against this PR is attached below or available on request.)

Overall the change looks correct to me. Points 1 and 4 are the ones I'd like addressed before
merge; 2 and 3 are suggestions.

---

## Reviewer notes (not for posting)

Environment: Claude cloud session, Linux, OpenJDK 21.0.12.1, Maven 3.9.11. Worktree at PR head
7a79f383da3; #8322 head 643ac96b5d5; trunk d07707b418e.

Practical issues with the environment (none affect the results):
- Maven Central returned HTTP 429 (rate-limited IP) through the session proxy, so the builds
  used the Google mirror `https://maven-central.storage-download.googleapis.com/maven2/` via a
  scratch `settings.xml` (`-s`).
- The enforcer requires Maven >= 3.9.15, and the host has 3.9.11, so builds ran with
  `-Denforcer.skip=true`.
- `mvn surefire:test` on its own leaves `@{argLine}` unresolved and the fork dies. Use the
  `test` phase instead.

Commands (run from the module directory; `$S` is the scratch settings):
1. Build: `mvn -s $S -pl hadoop-hdfs-project/hadoop-hdfs -am install -DskipTests
   -Dmaven.javadoc.skip=true -Denforcer.skip=true` gave `BUILD SUCCESS` in 05:02 min.
2. Regressions: `mvn -s $S test -Denforcer.skip=true -Dtest='TestFileChecksum,TestGetFileChecksum'
   -Dmaven.test.failure.ignore=false` gave `Tests run: 72, Failures: 0, Errors: 0, Skipped: 0`
   (`TestFileChecksum` 70 in 322.4 s, `TestGetFileChecksum` 2). The results were confirmed in
   `target/surefire-reports`.
3. The e2e tests from `candidate-minicluster-test.diff` (updated):
   - The original sketch was wrong: `nn.create(..., supportedVersions=null, ...)` fails in the
     NameNode with `NullPointerException: Cannot read the array length because "versions" is
     null`. Fixed by passing `CryptoProtocolVersion.supported()`. With that, the block
     completes and the replica is seen (`locatedBlockCount() == 1`, length 0).
   - On the PR, both tests pass (`Tests run: 2, Failures: 0, Errors: 0`).
   - With trunk's `FileChecksumHelper` (`git checkout apache/trunk -- .../FileChecksumHelper.java`,
     which is identical at the PR's merge-base, then hadoop-hdfs-client reinstalled), both fail:
     - Replicated: `ArrayIndexOutOfBoundsException: readInt out of bounds: buf.length=0, offset=0`
       at `makeCompositeCrcResult(FileChecksumHelper.java:333)`.
     - EC, as written: `IllegalArgumentException: Unexpected byte[] length '0' for single CRC`
       at `populateBlockChecksumBuf(FileChecksumHelper.java:456)`. This happens because
       `TestFileChecksum.setup()` sets `FileChecksumHelper.LOG` to DEBUG, so trunk dies even
       earlier in the debug-only path.
     - EC, in a one-off run with the logger at INFO (production path; the temporary change was
       reverted): the same AIOOBE at `makeCompositeCrcResult(FileChecksumHelper.java:333)`.
4. EC variant: done (above).
5. With #8322 applied, using `git cherry-pick -n` because the shallow clone can't `git merge`
   ("unrelated histories"); #8322 is a single commit, so the content is the same:
   - `FileChecksumHelper.java` conflicted (1 hunk) and was resolved with
     `merge8322-resolution.diff`. The result has blob `acac75c310`, as recorded.
   - `TestFileChecksumHelper`: `Tests run: 6, Failures: 0, Errors: 1`, with the NPE shown in
     point 1. Correction to the earlier note: the NPE comes from the no-blocks reference
     checksum (`compute():244`), not from the empty-block path, but the cause is the same
     (`client == null`).
   - `TestGetFileChecksum` (including #8322's `testEmptyFileChecksumType` and the e2e test) plus
     the EC test: `Tests run: 5, Failures: 0, Errors: 0`.
- Artifacts in this directory: `merge8322-resolution.diff`; `candidate-minicluster-test.diff`,
  updated to the final, working version of both e2e tests against PR head 7a79f383da3.
- Before posting, decide whether to attach the test diff to the PR comment or to JIRA.
