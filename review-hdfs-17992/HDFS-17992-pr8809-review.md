# Draft review: apache/hadoop#8809 (HDFS-17992)

Status: DRAFT, not posted. Reviewed head 7a79f383da3 (state checked 2026-10-10: PR open,
Yetus +1, no reviews; JIRA Open, unassigned).

---

Thanks for the clear write-up and the focused fix. I built the PR locally and checked the
claims in the description:

- `TestFileChecksumHelper` on the PR: `Tests run: 6, Failures: 0, Errors: 0`.
- The same test file against trunk's `FileChecksumHelper` (main code reverted): 3 of 6 fail
  exactly as described:
  - `testCompositeCrcOfZeroLengthFileWithEmptyBlock`:
    `ArrayIndexOutOfBoundsException: readInt out of bounds: buf.length=0, offset=0`
  - `testCompositeCrcSkipsEmptyBlockInTheMiddle`:
    `expected: <COMPOSITE-CRC32C:0xf1f974d9> but was: <COMPOSITE-CRC32C:0xd0c33523>`
  - `testPopulateEmptyCompositeBlockChecksumWithDebugLogging`:
    `IllegalArgumentException: Unexpected byte[] length '0' for single CRC. Contents: []`

The DataNode side matches the premise: `BlockChecksumHelper#computeCompositeCrc` and
`#reassembleNonStripedCompositeCrc` compose nothing for a 0-length block, so
`CrcComposer#digest()` returns `byte[0]`. For files without empty blocks the new loop gives
the same result as the old one.

A few comments:

**1. Interaction with HDFS-17803 / #8322.** Both PRs rewrite the empty-file branch of
`compute()`. Merging #8322 on top of this PR conflicts in that one hunk
(`git merge-tree` reports `CONFLICT (content)` in `FileChecksumHelper.java`;
`TestGetFileChecksum.java` merges cleanly). The natural resolution is to move #8322's
COMPOSITE_CRC branch into `makeEmptyFileChecksum()`, which then also covers the
"all blocks empty" case:

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

With that resolution, the new `testCompositeCrcOfZeroLengthFileWithEmptyBlock` fails:
`NullPointerException: Cannot invoke "org.apache.hadoop.hdfs.DFSClient.getConf()" because
"this.client" is null`. `FakeChecksumComputer` passes `client = null`. Could the fake pass a
(mocked) `DFSClient` with a `DfsClientConf`, so the test survives whichever PR lands second?

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

**4. Test nits.**
- `assertNotEquals(null, computer.populateBlockChecksumBuf(response))` should be
  `assertNotNull(...)`.
- `GenericTestUtils.setLogLevel(FileChecksumHelper.LOG, Level.DEBUG)` is never restored.
  Please save the old level and restore it in `finally` or `@AfterEach`.
- `testCompositeCrcSkipsTrailingEmptyBlock` also passes on trunk, because it reads 4 zero bytes
  past the valid data, as the JIRA says. So it documents behaviour but does not guard the fix.
  Making it fail on trunk would need a check like the one in point 2.
- All tests use the fake computer. An end-to-end MiniDFSCluster test with a real empty replica
  would cover the DataNode side as well. A sketch is below. I compiled it, but I could not run
  it in my environment, so please treat it as a suggestion only:

```java
@Test
public void testCompositeCrcOfZeroLengthFileWithEmptyBlock() throws Exception {
  DFSClient client = dfs.getClient();
  ClientProtocol nn = client.getNamenode();
  String src = "/zeroLengthWithEmptyBlock";
  HdfsFileStatus stat = nn.create(src, FsPermission.getFileDefault(),
      client.getClientName(),
      new EnumSetWritable<>(EnumSet.of(CreateFlag.CREATE)), true,
      (short) 1, BLOCKSIZE, null, null, null);
  LocatedBlock lb = nn.addBlock(src, client.getClientName(), null, null,
      stat.getFileId(), null, null);
  // A real, empty, finalized replica, as lease recovery leaves when a writer
  // dies after setting up the pipeline but before sending data.
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

(It would go in `TestGetFileChecksum`. An erasure-coded variant with RS-6-3-1024k would
match the production report more closely.)

Overall the change looks correct to me. Points 1 and 4 are the ones I'd like addressed before
merge; 2 and 3 are suggestions.

---

## Reviewer notes (not for posting)

- Not verified locally: `TestFileChecksum` / `TestGetFileChecksum` regressions (hadoop-hdfs)
  and the MiniDFSCluster sketch above. On this Windows host MiniDFSCluster fails in `setUp`:
  `Hadoop bin directory does not exist: ...hadoop-common\target\bin` (no winutils). Docker
  and WSL are not installed. Yetus only runs tests for changed modules (hadoop-hdfs-client), so
  the +1 does NOT cover hadoop-hdfs's `TestFileChecksum` / `TestGetFileChecksum` either.
- Artifacts: `merge8322-resolution.diff`, `candidate-minicluster-test.diff` (same scratchpad).
