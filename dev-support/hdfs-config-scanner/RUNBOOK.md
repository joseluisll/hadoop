<!--
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

# Runbook: regenerate the HDFS configuration analysis

Re-runs the whole HDFS-11039 analysis and rewrites the reports.
Takes about **30 seconds**. Reads your checkout; writes nothing to it.

---

## 1. Check you have what you need

| Need | Check with | Expected |
| --- | --- | --- |
| Python 3 | `python --version` | `Python 3.x` (tested on 3.13) |
| A Hadoop checkout | `ls hadoop-hdfs-project` | a directory listing |

No Maven, no Java, no build. Nothing is downloaded.

<details>
<summary>Starting from nothing? Get a checkout first</summary>

```bash
git clone https://github.com/apache/hadoop.git
```

On Windows, run this **before** cloning or the checkout fails on long paths:

```bash
git config --global core.longpaths true
```
</details>

---

## 2. Run it

From the scanner directory:

```bash
cd dev-support/hdfs-config-scanner && python scan.py pipeline
```

If the scanner lives outside the checkout, point it at one:

```bash
python scan.py pipeline --repo /path/to/hadoop
```

---

## 3. Check the result

Look at the last line, or the exit code (`echo $?`).

**Success** — every stage says `ok`:

```
[M1] static extraction (E1-E5) - ok
    oracle hdfs: PASS (656 constants vs 656 xml properties compared)
    oracle rbf: PASS (107 constants vs 107 xml properties compared)
[M2] call-site sweep + inventory (E6) - ok
    1157 properties classified; 33 undocumented
[M3] assessment + proposed xml (E7) - ok
[M4] apply documentation batches - ok
```

Exit code `0`. The numbers will differ as Hadoop changes — that is normal and
is the point of re-running.

**Failure** — a stage says `FAILED`, the run stops there, exit code is `1`:

```
[M1] static extraction (E1-E5) - FAILED
    oracle hdfs: FAIL (656 constants vs 657 xml properties compared)
        xml property with no constant: zzz.bogus.key
Stages failed: M1
```

The offending property is always named. Nothing was written to your checkout.

---

## 4. Collect the reports

Four files, rewritten on every run, in `dev-support/hdfs-config-scanner/out/`:

| File | What it is | Who reads it |
| --- | --- | --- |
| `hdfs-config-inventory.md` | Every property, classified, with the evidence | anyone |
| `hdfs-config-inventory.csv` | The same, one row per property | for sorting and filtering |
| `hdfs-11039-assessment.md` | The undocumented ones, grouped into review batches | reviewers |
| `hdfs-11039-proposed-additions.xml` | Ready-to-paste `<property>` blocks | whoever writes the patch |

Start with the **Summary** table in `hdfs-config-inventory.md`, then the
**Candidates for documentation** section — that is the answer to "which
properties are missing from `hdfs-default.xml`".

---

## 5. If it fails

| Message | Meaning | What to do |
| --- | --- | --- |
| `does not look like a Hadoop checkout` | wrong directory | pass `--repo /path/to/hadoop` |
| `oracle ... FAIL` + `xml property with no constant` | a property is documented but its Java constant is not in the test's class list | expected if you just edited an xml — add the declaring class to `configurationClasses`, see step 7 |
| `oracle ... FAIL` + `constant not in xml` | a Java constant has no xml entry | a property was added to the code and not documented — a real finding |
| `call sites could not be parsed` | the scanner met Java it cannot read | report it; the file and line are printed |
| `plain-literal keys missed by E2` | internal inconsistency | report it — this should never happen |

A failure in M1 means the scanner and Hadoop's own tests disagree, so **stop and
resolve it**. Everything downstream is built on that agreement.

---

## 6. Optional: run one step at a time

Same code, same results — useful when you only want part of it:

```bash
python scan.py step M1      # validate extraction against Hadoop's tests
python scan.py step M2      # classify every property, write the inventory
python scan.py step M3      # write the assessment and the proposed xml
python scan.py step M4      # show which batches are ready to apply
```

---

## 7. Optional: apply the documentation

**This edits tracked Hadoop files.** Commit or stash your work first, and do it
on a branch.

```bash
git checkout -b HDFS-11039-document-config-properties
python scan.py pipeline --apply
```

It only writes batches where every property already has a description, and it
skips properties already present, so it is safe to re-run. After each batch it
re-checks Hadoop's comparison test and **rolls that batch back** if it fails, so
a run never leaves your tree half-patched.

Review what changed before committing:

```bash
git diff
```

Then confirm the real Java tests pass — the scanner predicts them, it does not
replace them:

```bash
mvn test -Dtest=TestHdfsConfigFields -pl hadoop-hdfs-project/hadoop-hdfs
mvn test -Dtest=TestRBFConfigFields  -pl hadoop-hdfs-project/hadoop-hdfs-rbf
```

---

## 8. What the tool will not do for you

The run ends with a **Needs a human** list. Those items are not failures; they
are the parts no tool can decide:

- **Properties with no description anywhere.** The tool writes `TODO` rather
  than inventing text, because a wrong description in `hdfs-default.xml` is
  worse than a missing one — operators act on it. Someone who knows the
  subsystem must write these before their batch can be applied.
- **Properties marked `NEEDS_REVIEW`.** The evidence was ambiguous, so a person
  decides whether each is really a configuration property.
- **Where a new property belongs in the xml.** Insertion points are listed in
  `PLACEMENTS` in `hdfsconfscan/pipeline.py`; a batch with no entry is skipped
  rather than dumped at the end of the file.

---

## 9. Check the tool itself

If you suspect the scanner rather than Hadoop:

```bash
python selftest.py          # 41 unit tests, under a second
python scan.py verify       # every reported file:line really contains what is claimed
```
