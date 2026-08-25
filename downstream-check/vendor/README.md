# vendor/checkcompatibility.py

A copy of Hadoop's `dev-support/bin/checkcompatibility.py`, taken at commit
`a0f8f7e6dc34c8fb6eb70723a36cf7c5721b782d`, with the changes rung 1 needs.

It is a copy rather than a patch because this harness is not proposed as a Hadoop
contribution — see `../PLAN.md`. The Hadoop working trees stay clean for the
changes actually under review. The fixes below are separable and stand on their
own merits; if they prove useful here they are worth their own JIRA.

## Changes from upstream

**`--java-acc-dir DIR`** — use an existing japi-compliance-checker checkout
instead of downloading one. Upstream fetches a hardcoded GitHub archive URL,
which returns 403 through the egress proxies common in build environments; a
`git clone` of the same repository works. The download path also now fails with
an actionable message instead of a traceback.

**`--src-dir DIR` / `--dst-dir DIR`** — compare trees that are already built. The
harness builds each Hadoop ref once and installs it; without this the script
would check out and build both sides again, roughly doubling the most expensive
part of a run.

**`--repo-dir DIR` and `--work-dir DIR`** — upstream derives every path from the
script's own location inside the Hadoop tree, which a copy kept outside it cannot
do.

**`--keep-internal`** — pass `-keep-internal` through to the checker. By default
it silently drops every package named `impl` or `internal`, announcing it only as
a warning in the middle of its output. For a surface the ecosystem uses despite
its `@InterfaceAudience` marking, that is a blind spot rather than a
simplification.

**Exit codes.** The checker exits 1 when it finds an incompatibility — a result,
not a failure — and upstream's `check_call` turns that into a stack trace, so the
script crashes precisely when it has something to say. Now:

| Code | Meaning |
| --- | --- |
| 0 | No incompatibilities found |
| 2 | Incompatibilities found; see the report |
| 1 | The checker itself failed to run |

## Getting the checker

```
git clone -b 1.8 https://github.com/lvc/japi-compliance-checker <dir>
```

Version 1.8 is what upstream pins, and it is the version to use — not because it
is what Hadoop specifies, but because the newer ones do not work here.

| Version | One jar | 86–90 jars |
| --- | --- | --- |
| **1.8** | works, 62 s | **works** |
| 2.0 – 2.3 | works, 28 s | **deadlocks** |
| 2.4 | `ERROR: internal error in parser` | — |

2.4 fails under JDK 21 on a two-class toy jar, so it is not Hadoop-specific.
2.0–2.3 run javap through `open3(*IN, *OUT, *ERR, @Cmd)` in
`Internals/APIDump.pm` and the parser reads only `<OUT>`, never draining
`<ERR>`, with no `select()`. Once javap fills the 64 KB stderr pipe buffer it
blocks writing while perl blocks reading stdout, and neither ever wakes. 1.8
does not use pipes at all — `system($Cmd." ".$Input." >\"$Output\"
2>\"$TMP_DIR/warn\"")` sends both streams to files — so it cannot deadlock.

One line fixes 2.3, should a faster checker be wanted later, but it is unverified
at scale:

```perl
my $Pid = open3(*IN, *OUT, ">&STDERR", @Cmd);
```

## Example

```
python3 vendor/checkcompatibility.py \
    --repo-dir     /path/to/hadoop \
    --work-dir     runs/<date>/rung1 \
    --java-acc-dir /path/to/japi-compliance-checker \
    --src-dir      refs/trunk/src \
    --dst-dir      refs/candidate/src \
    --include-file 'hadoop.*' \
    --keep-internal \
    --annotation org.apache.hadoop.classification.InterfaceAudience.Public \
    --annotation org.apache.hadoop.classification.InterfaceAudience.LimitedPrivate \
    trunk HADOOP-19972
```
