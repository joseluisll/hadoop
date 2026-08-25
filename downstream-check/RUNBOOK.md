# Runbook

How to actually run this. Written against the first run; measured numbers are
from a 2026-08-25 run on a 4-core container with a cold Maven cache.

## Prerequisites

| Need | Detail |
| --- | --- |
| Maven **3.9.15 or newer** | The root POM enforces `[3.9.15,)`. Older Maven fails in ~17 s on the enforcer, before compiling anything. 3.9.11 is not enough. At the time of writing 3.9.15 is the newest on Central. |
| JDK 17 or newer | The root POM enforces `[17,)`. Runs so far used JDK 21. |
| ~30 GB free disk | Each built tree is ~2.6 GB and is deleted after installing. The shared artifact tail settles around 1.4 GB, each ref's repo around 380 MB. |
| japi-compliance-checker 1.8 | `git clone -b 1.8 https://github.com/lvc/japi-compliance-checker`. Do not rely on the script's download — see `vendor/README.md`. |
| Perl | For the checker. |

`protoc` is *not* needed: the build resolves it as a Maven artifact.

## Work directory layout

Kept outside the Hadoop repository:

```
<work>/
  tools/apache-maven-3.9.15/     # if the system Maven is too old
  tools/japi-compliance-checker/ # 1.8 checkout
  m2-tail/                       # third-party artifacts, shared by every ref
  refs/<name>/src/               # git worktree, deleted after installing
  refs/<name>/repo/              # that ref's org/apache/hadoop artifacts only
  logs/<name>-install.log
```

## Building a ref

```
git worktree add --detach <work>/refs/<name>/src <sha>
cd <work>/refs/<name>/src            # see the trap below — this line matters
<work>/tools/apache-maven-3.9.15/bin/mvn -B install -DskipTests \
    -Dmaven.javadoc.skip=true -Dspotbugs.skip=true \
    -Dcheckstyle.skip=true -Drat.skip=true \
    -Dmaven.repo.local=<work>/refs/<name>/repo \
    -Dmaven.repo.local.tail=<work>/m2-tail
```

Roughly **27 minutes** for 119 modules with a cold cache; less once the tail is
warm. Afterwards, move everything that is not `org/apache/hadoop` from the ref's
repo into `m2-tail`, then delete `refs/<name>/src`. The installed jars are all
rung 1 needs, and five build trees do not fit on disk.

## Rung 1 — API signatures

Point it at the installed repositories, not the source trees:

```
python3 vendor/checkcompatibility.py \
    --repo-dir     /path/to/hadoop \
    --work-dir     <work>/runs/<date>/rung1 \
    --java-acc-dir <work>/tools/japi-compliance-checker \
    --src-dir      <work>/refs/<baseline>/repo/org/apache/hadoop \
    --dst-dir      <work>/refs/<candidate>/repo/org/apache/hadoop \
    --include-file 'hadoop.*' \
    --keep-internal \
    --annotation org.apache.hadoop.classification.InterfaceAudience.Public \
    --annotation org.apache.hadoop.classification.InterfaceAudience.LimitedPrivate \
    <baseline-label> <candidate-label>
```

Exit 0 clean, 2 findings, 1 the checker itself failed.

## Rung 2 — shaded client invariants

Nothing to run. `hadoop-client-check-invariants` and
`hadoop-client-check-test-invariants` are in the default reactor, so the install
above already ran them. Read the result out of the log:

```
bin/rung2-summary --ref <name> <work>/logs/<name>-install.log
```

Trunk at `d57814e3`: build SUCCESS, 12 invariant rules, 0 failed.

## How many refs to build

**Two.** A baseline and the candidate. The Jetty branches stack —
`jetty-phase-c` contains `phase-b` contains `phase-a` — so phase-c alone carries
all three JIRAs, and one comparison answers whether the work breaks anyone.

Building phases a and b up front buys only *attribution*: which of the three
JIRAs caused a finding. That is worth nothing unless a finding appears, and it
is fully recoverable afterwards by building the one phase in question. Build
them when there is something to attribute, not before.

The branches also carry four commits that are not part of these JIRAs —
HADOOP-19951, 19967, 19968, 19969 (jetty-util-ajax removal, Jackson, log4j,
httpcore5). They sit below the Jetty work, so they are inside any
trunk → phase-c delta. For rung 1 that is mostly harmless, since dependency
bumps rarely move Hadoop's own annotated signatures. For a dependency-closure
delta they must be subtracted, by using `2add9630` as the baseline instead of
trunk.

## Traps

**Build in the worktree.** Maven builds whatever is in the current directory. A
script that creates a worktree and then runs `mvn` without `cd`-ing into it will
build the main working tree instead, install it under the ref's name, and log
nothing unusual. This produced a full run of mislabelled artifacts on the first
attempt. Verify before trusting a build:

```
git -C <work>/refs/<name>/src log -1 --format=%h
```

**The checker exits non-zero on a finding.** That is a result, not a failure.
The vendored copy separates the two; the in-tree script does not.

**`--keep-internal` is not the default.** Without it the checker silently drops
every package named `impl` or `internal`, announcing it only as a warning in the
middle of its output.

**`pkill -f` matches your own shell.** Use a pattern that cannot match itself.
