#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Usage: jsr311-scan.sh [options]
#
# Scans a Hadoop tree for JAX-RS 1.1 use and exits non-zero when the 1.1 API
# can still reach a classpath. The target change removes the duplicate
# javax.ws.rs:jsr311-api:1.1.1 declaration from
# hadoop-yarn-server-timelineservice-hbase-tests, which also gets JAX-RS 2.1
# (jakarta.ws.rs:jakarta.ws.rs-api, javax.ws.rs packages) through jersey-server
# at test scope; until then both jars provided javax.ws.rs and the classpath
# order picked the winner. Deleting the declaration does not prove the jar is
# gone, because a third-party dependency can bring jsr311-api back. This script
# is the proof, and what a reviewer can run.
#
# Options:
#   --root <dir>      tree to scan (default: this script's ../..)
#   --json            one JSON object per finding (JSONL), no prose
#   --explain         explain what a failure of each check means
#   --verbose         list each history match (release changelogs, jdiff)
#   --skip-pom        skip the POM scan
#   --skip-source     skip the source scan
#   --classpath       also run the classpath scan (runs Maven; opt-in only)
#   --module <path>   module for --classpath (repeatable, relative to --root)
#   -h, --help        show this help
#
# Checks:
#   1. POM scan (offline, no Maven). Every pom.xml is checked for
#      <artifactId>jsr311-api</artifactId> and for dependencies whose
#      <groupId> is javax.ws.rs (a 1.x API or provider coordinate; the 2.1
#      artifact is jakarta.ws.rs:jakarta.ws.rs-api). A declaration inside an
#      <exclusion> is reported as "exclusion", not "hit": it is what stops the
#      jar coming back. DependencyManagement declarations are included and
#      labelled "managed". Any "hit" fails the run.
#   2. Source scan (offline, no Maven). Every .java file's javax.ws.rs imports
#      are classified: "2.x-only" for packages/classes JAX-RS 1.1 does not
#      have (client, container, sse, Feature/Configurable/Configuration, Link,
#      the 2.x exception subclasses), which proves that source
#      needs JAX-RS 2.x and a 1.1 jar on its classpath is the wrong API; and
#      "ambiguous" for imports present in both 1.1 and 2.x, which work against
#      either jar and are where dropping 1.1 could silently change behaviour.
#      Findings are grouped by the nearest ancestor pom.xml (the module), with
#      a per-module count. Neither category fails the run.
#   3. Reference scan (offline, always on). Every tracked text file, whatever
#      its name or extension, is searched for javax.ws.rs and jsr311, and each
#      match is classified:
#        source      .java files are covered by the source scan, not here;
#        history     release changelogs under src/site/markdown/release/ and
#                    jdiff API baselines under dev-support/jdiff/: they describe
#                    past releases, so they are counted, not failed (listed one
#                    by one with --verbose);
#        reference   anything else (resources, META-INF/services, .properties,
#                    non-POM .xml, .sh, .md, config): it names the API but is
#                    informational;
#        build-input a non-POM file under a module's src/main/resources or
#                    src/test/resources: it can change what a build puts on the
#                    classpath or in the artifact, so it is called out, but it
#                    does not fail the run.
#      dev-support/jetty12-phase-a/ is excluded on purpose: this scanner's own
#      pattern strings and the harness's class-loading lists are not API use.
#      git ls-files supplies the files where --root is a git work tree, so
#      .gitignore is honoured and POMs and .java files (scanned above) are left
#      out; binary files are skipped.
#   4. Artifact scan (offline, always on). Finds built jars under target/ and
#      compiled class trees in target/classes. A jar is a hit when its path or
#      its META-INF/maven/javax.ws.rs/jsr311-api/pom.properties names
#      jsr311-api (listed with unzip, zipinfo or jar tf). A target/classes
#      tree with javax/ws/rs classes is a hit when a target/ pom.properties or
#      maven-status names jsr311-api, and otherwise "ambiguous-artifact": its
#      source jar cannot be proven to be 2.1, so it is informational. With no
#      built artifacts the scan says so and does not fail. find is used, not
#      git ls-files, because target/ is ignored; .git/ and .claude/ are
#      pruned (other worktrees live under .claude/worktrees/ and their
#      target/ belongs to a different tree), as is build/ outside a git work
#      tree.
#   5. Classpath scan (--classpath only; runs Maven, so it never runs by
#      default). For each --module, runs
#      mvn -q -o dependency:tree -Dincludes=javax.ws.rs:jsr311-api
#      and fails if jsr311-api resolves, at any scope. -o makes it work from a
#      warm local repository; extra Maven arguments go in MAVEN_ARGS.
#
# Exit status: 0 when no hit, 1 when any hit (a POM declaration, a --classpath
# resolution, or a jsr311-api artifact), 2 when a requested check could not run
# (an inconclusive scan must not pass). reference, history, build-input and
# ambiguous-artifact findings never fail the run, nor does any .java
# classification.
#
# Uses git ls-files for the POM, source and reference scans when --root is
# inside a git work tree, so .gitignore is honoured and .claude/ and target/
# are skipped; otherwise it falls back to find, pruning .git, .claude, target
# and build. The artifact scan always uses find, since target/ is ignored,
# and prunes .git/, .claude/ (other worktrees) and, outside a git work tree,
# build/. Every scan resolves file paths against --root, so it does not
# matter which directory the script is run from. No Python dependency.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROOT="${SCRIPT_DIR}/../.."
JSON=false
EXPLAIN=false
VERBOSE=false
POM_SCAN=true
SOURCE_SCAN=true
CLASSPATH_SCAN=false
declare -a MODULES=()

die() {
  printf 'jsr311-scan: ERROR: %s\n' "$*" >&2
  exit 2
}

usage() {
  sed -n '/^# Usage:/,/^# Exit status:/p' "${BASH_SOURCE[0]}" \
    | sed -e '$d' -e 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --root)      [[ $# -ge 2 ]] || die "--root needs a directory"; ROOT=$2; shift 2 ;;
    --module)    [[ $# -ge 2 ]] || die "--module needs a path"; MODULES+=("$2"); shift 2 ;;
    --json)      JSON=true; shift ;;
    --explain)   EXPLAIN=true; shift ;;
    --verbose)   VERBOSE=true; shift ;;
    --skip-pom)  POM_SCAN=false; shift ;;
    --skip-source) SOURCE_SCAN=false; shift ;;
    --classpath) CLASSPATH_SCAN=true; shift ;;
    -h|--help)   usage; exit 0 ;;
    *)           die "unknown option: $1 (see --help)" ;;
  esac
done

ROOT="$(cd "${ROOT}" 2>/dev/null && pwd -P)" || die "no such directory: ${ROOT}"

# Counters. POM_HITS, CP_HITS and ARTIFACT_HITS decide the exit status, as do
# CP_ERRORS and ARTIFACT_ERRORS (inconclusive); the rest are reported.
POM_HITS=0
POM_EXCLUSIONS=0
TWO_X=0
AMBIGUOUS=0
REFERENCE=0
BUILD_INPUT=0
HISTORY=0
ARTIFACT_HITS=0
AMBIGUOUS_ARTIFACTS=0
CP_HITS=0
CP_ERRORS=0
ARTIFACT_ERRORS=0

json_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\t'/\\t}
  printf '%s' "${s}"
}

# list_files <name>: files with that basename, relative to ROOT, sorted.
# In a git tree git's own ignore rules apply (this also skips .claude/ and
# target/); outside one, the generated directories are pruned explicitly.
list_files() {
  local pattern=$1
  if git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local specs
    if [[ "${pattern}" == pom.xml ]]; then
      specs=('pom.xml' '**/pom.xml')
    else
      specs=("${pattern}")
    fi
    git -C "${ROOT}" ls-files -z --cached --others --exclude-standard \
      -- "${specs[@]}" \
      | tr '\0' '\n' \
      | grep -Ev '(^|/)(\.claude|target|\.git)/' || true
  else
    ( cd "${ROOT}" && find . -type d \
        \( -name .git -o -name .claude -o -name target -o -name build \) -prune \
        -o -type f -name "${pattern}" -print ) \
      | sed 's#^\./##' \
      | grep -Ev '(^|/)(\.claude|target|\.git)/' || true
  fi
}

# POM scan: an awk state machine per file, so a jsr311-api artifact is tied to
# the groupId of its enclosing dependency or the exclusion it sits in.
scan_poms() {
  local pom kind line gid aid managed module pretty
  while IFS= read -r pom; do
    [[ -n "${pom}" ]] || continue
    module=$(dirname "${pom}")
    while IFS='|' read -r kind line gid aid managed; do
      [[ -n "${kind}" ]] || continue
      if [[ "${kind}" == exclusion ]]; then
        POM_EXCLUSIONS=$((POM_EXCLUSIONS + 1))
      else
        POM_HITS=$((POM_HITS + 1))
      fi
      if [[ "${JSON}" == true ]]; then
        local mj=false
        if [[ "${managed}" == managed ]]; then mj=true; fi
        printf '{"check":"pom","kind":"%s","file":"%s","line":%s,"module":"%s","groupId":"%s","artifactId":"%s","managed":%s}\n' \
          "${kind}" "$(json_escape "${pom}")" "${line}" "$(json_escape "${module}")" \
          "$(json_escape "${gid}")" "$(json_escape "${aid}")" "${mj}"
      else
        pretty=HIT
        [[ "${kind}" == exclusion ]] && pretty=EXCLUSION
        printf '%-9s %s:%s  %s:%s%s\n' "${pretty}" "${pom}" "${line}" \
          "${gid:-?}" "${aid}" "${managed:+ (managed)}"
      fi
    done < <(awk '
      BEGIN { dep = 0; excl = 0; managed = 0; g = ""; a = ""; gl = 0; al = 0;
              eg = ""; ea = ""; egl = 0; eal = 0 }
      function setfield(line, tag) {
        if (match(line, "<" tag ">[^<]*</" tag ">")) {
          fv = substr(line, RSTART, RLENGTH)
          sub("^<" tag ">", "", fv)
          sub("</" tag ">", "", fv)
          gsub(/^[ \t]+|[ \t]+$/, "", fv)
          return 1
        }
        return 0
      }
      {
        if ($0 ~ /<dependencyManagement>/) {
          managed = 1
        } else if ($0 ~ /<\/dependencyManagement>/) {
          managed = 0
        } else if ($0 ~ /<exclusion>/) {
          excl = 1; eg = ""; ea = ""; egl = 0; eal = 0
        } else if ($0 ~ /<\/exclusion>/) {
          if (eg == "javax.ws.rs" || ea == "jsr311-api")
            printf "exclusion|%d|%s|%s|%s\n", (eal ? eal : egl), eg, ea,
                   (managed ? "managed" : "")
          excl = 0
        } else if ($0 ~ /<dependency>/) {
          dep = 1; g = ""; a = ""; gl = 0; al = 0
        } else if ($0 ~ /<\/dependency>/) {
          if (a == "jsr311-api" ||
              (g == "javax.ws.rs" && a != "jakarta.ws.rs-api"))
            printf "hit|%d|%s|%s|%s\n", (al ? al : gl), g, a,
                   (managed ? "managed" : "")
          dep = 0; g = ""; a = ""; gl = 0; al = 0
        }
        if (dep) {
          if (setfield($0, "groupId")) {
            if (excl) { eg = fv; egl = NR } else { g = fv; gl = NR }
          }
          if (setfield($0, "artifactId")) {
            if (excl) { ea = fv; eal = NR } else { a = fv; al = NR }
          }
        }
      }
    ' "${ROOT}/${pom}" || true)
  done < <(list_files pom.xml)
}

# The classes JAX-RS 1.1 does not have. RuntimeDelegate is not listed:
# jsr311-api 1.1.1 ships javax/ws/rs/ext/RuntimeDelegate.class, so an import
# of it does not prove the source needs 2.x; it falls through to ambiguous.
is_2x_only() {
  case "$1" in
    javax.ws.rs.client.*|javax.ws.rs.container.*|javax.ws.rs.sse.*|\
    javax.ws.rs.core.Feature|javax.ws.rs.core.FeatureContext|\
    javax.ws.rs.core.Configurable|javax.ws.rs.core.Configuration|\
    javax.ws.rs.core.Link|javax.ws.rs.core.Link.Builder|\
    javax.ws.rs.BadRequestException|javax.ws.rs.ProcessingException|\
    javax.ws.rs.ForbiddenException|javax.ws.rs.InternalServerErrorException|\
    javax.ws.rs.NotAcceptableException|javax.ws.rs.NotAllowedException|\
    javax.ws.rs.NotAuthorizedException|javax.ws.rs.NotFoundException|\
    javax.ws.rs.NotSupportedException|javax.ws.rs.ServiceUnavailableException)
      return 0 ;;
    *) return 1 ;;
  esac
}

# module_of <file>: sets MODULE to the closest ancestor with a pom.xml.
# Pure bash: a dirname per level per finding is thousands of forks and made
# this scan take ~50s.
module_of() {
  local d=${1%/*}
  [[ "${d}" == "$1" ]] && d=.
  while :; do
    if [[ -n "${MODULE_OF_DIR[${d}]:-}" ]]; then MODULE=${d}; return 0; fi
    [[ "${d}" == "." || "${d}" == "/" ]] && { MODULE=${d}; return 0; }
    local nd=${d%/*}
    [[ "${nd}" == "${d}" ]] && nd=.
    d=${nd}
  done
}

scan_sources() {
  local -a files=()
  local -a findings=()
  mapfile -t files < <(list_files '*.java')
  ((${#files[@]} > 0)) || return 0

  # Module dirs, for grouping. Done here so --skip-pom still groups sources.
  declare -gA MODULE_OF_DIR=()
  local pom md
  while IFS= read -r pom; do
    [[ -n "${pom}" ]] || continue
    md=${pom%/*}
    [[ "${md}" == "${pom}" ]] && md=.
    MODULE_OF_DIR[${md}]=1
  done < <(list_files pom.xml)

  # list_files gives paths relative to ROOT while grep resolves them against
  # the caller's directory: cd into ROOT so --root is honoured.
  local file line imp module kind rest
  while IFS= read -r rest; do
    file=${rest%%:*}
    rest=${rest#*:}
    line=${rest%%:*}
    imp=${rest#*:}
    imp=${imp#import }
    imp=${imp#static }
    imp=${imp%;}
    imp=${imp%$'\r'}
    if is_2x_only "${imp}"; then kind=2.x-only; else kind=ambiguous; fi
    module_of "${file}"
    module=${MODULE}
    if [[ "${kind}" == 2.x-only ]]; then
      TWO_X=$((TWO_X + 1))
    else
      AMBIGUOUS=$((AMBIGUOUS + 1))
    fi
    findings+=("${module}|${kind}|${file}|${line}|${imp}")
  done < <(cd "${ROOT}" && printf '%s\0' "${files[@]}" \
    | xargs -0 grep -HnE '^import (static )?javax\.ws\.rs\.' 2>/dev/null || true)
  ((${#findings[@]} > 0)) || return 0

  if [[ "${JSON}" == true ]]; then
    local i
    for i in "${!findings[@]}"; do
      IFS='|' read -r module kind file line imp <<< "${findings[${i}]}"
      printf '{"check":"source","kind":"%s","file":"%s","line":%s,"module":"%s","import":"%s"}\n' \
        "${kind}" "$(json_escape "${file}")" "${line}" \
        "$(json_escape "${module}")" "$(json_escape "${imp}")"
    done
    return 0
  fi

  local cur="" m2 ma
  m2=0 ma=0
  while IFS='|' read -r module kind file line imp; do
    if [[ "${module}" != "${cur}" ]]; then
      if [[ -n "${cur}" ]]; then
        printf '  summary: 2.x-only=%d ambiguous=%d\n' "${m2}" "${ma}"
        printf '\n'
      fi
      printf 'module %s\n' "${module}"
      cur=${module}
      m2=0 ma=0
    fi
    if [[ "${kind}" == 2.x-only ]]; then
      m2=$((m2 + 1))
      printf '  2.x-only   %s:%s  %s\n' "${file}" "${line}" "${imp}"
    else
      ma=$((ma + 1))
      printf '  ambiguous  %s:%s  %s\n' "${file}" "${line}" "${imp}"
    fi
  done < <(printf '%s\n' "${findings[@]}" \
    | sort -t'|' -k1,1 -k2,2 -k4,4n)
  if [[ -n "${cur}" ]]; then
    printf '  summary: 2.x-only=%d ambiguous=%d\n' "${m2}" "${ma}"
  fi
}

# list_reference_files: every tracked text file, relative to ROOT, minus
# dev-support/jetty12-phase-a/ (this scanner's own pattern strings and the
# harness's class-loading lists are not API use), POMs and .java files (both
# scanned above). git ls-files with no --others keeps to tracked files, which
# also respects .gitignore; outside a git work tree, find prunes the generated
# directories.
list_reference_files() {
  if git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${ROOT}" ls-files -z | tr '\0' '\n'
  else
    ( cd "${ROOT}" && find . -type d \
        \( -name .git -o -name .claude -o -name target -o -name build \) -prune \
        -o -type f -print ) \
      | sed 's#^\./##'
  fi | grep -Ev '^(dev-support/jetty12-phase-a/|.*\.java$|(^|.*/)pom\.xml$)' || true
}

# classify_ref <file>: sets REF_KIND. History is release notes and jdiff
# baselines, which describe past releases; a file under a resources tree can
# change a build's classpath or artifact and is called out as build-input.
classify_ref() {
  case "$1" in
    */src/site/markdown/release/*|src/site/markdown/release/*) REF_KIND=history ;;
    */dev-support/jdiff/*|dev-support/jdiff/*) REF_KIND=history ;;
    */src/main/resources/*|src/main/resources/*|\
    */src/test/resources/*|src/test/resources/*) REF_KIND=build-input ;;
    *) REF_KIND=reference ;;
  esac
}

# Whole-tree reference scan: -I skips binary files, so a tracked image or jar
# cannot make grep print its bytes. History matches are counted unless
# --verbose; reference and build-input matches are always listed because a
# reviewer wants to see them, and none of the three fails the run.
scan_references() {
  local -a relfiles=() files=()
  local f
  mapfile -t relfiles < <(list_reference_files)
  ((${#relfiles[@]} > 0)) || return 0
  # grep runs from the caller's directory, so give it absolute paths; the
  # findings are printed back relative to ROOT.
  for f in "${relfiles[@]}"; do files+=("${ROOT}/${f}"); done

  local rec file line text kind
  while IFS= read -r rec; do
    file=${rec%%:*}
    file=${file#"${ROOT}/"}
    rec=${rec#*:}
    line=${rec%%:*}
    text=${rec#*:}
    # Drop control characters (a stray CR from a CRLF file, a form feed in a
    # config): they cannot be trimmed or JSON-escaped, and raw ones would make
    # a --json line invalid.
    text=${text//[[:cntrl:]]/}
    text="${text#"${text%%[![:space:]]*}"}"
    text="${text%"${text##*[![:space:]]}"}"
    classify_ref "${file}"
    kind=${REF_KIND}
    case "${kind}" in
      history)     HISTORY=$((HISTORY + 1)) ;;
      build-input) BUILD_INPUT=$((BUILD_INPUT + 1)) ;;
      *)           REFERENCE=$((REFERENCE + 1)) ;;
    esac
    if [[ "${JSON}" == true ]]; then
      printf '{"check":"reference","kind":"%s","file":"%s","line":%s,"text":"%s"}\n' \
        "${kind}" "$(json_escape "${file}")" "${line}" "$(json_escape "${text}")"
    elif [[ "${kind}" != history || "${VERBOSE}" == true ]]; then
      printf '  %-11s %s:%s  %s\n' "${kind}" "${file}" "${line}" "${text}"
    fi
  done < <(printf '%s\0' "${files[@]}" \
    | xargs -0 grep -HnIE 'javax\.ws\.rs|jsr311' 2>/dev/null | LC_ALL=C sort || true)

  if [[ "${JSON}" != true ]]; then
    printf 'reference: %d reference(s), %d build-input(s), %d history reference(s)\n' \
      "${REFERENCE}" "${BUILD_INPUT}" "${HISTORY}"
    if ((HISTORY > 0)) && [[ "${VERBOSE}" != true ]]; then
      printf '  history: past releases only, not listed (--verbose to list)\n'
    fi
  fi
}

# archive_entries <jar>: list the archive, or return 2 when none of unzip,
# zipinfo and jar is on PATH (an uninspectable jar makes the scan
# inconclusive, so the caller counts an error rather than guessing).
archive_entries() {
  if command -v unzip >/dev/null 2>&1; then
    unzip -l "$1" 2>/dev/null
  elif command -v zipinfo >/dev/null 2>&1; then
    zipinfo -1 "$1" 2>/dev/null
  elif command -v jar >/dev/null 2>&1; then
    jar tf "$1" 2>/dev/null
  else
    return 2
  fi
}

# target_names_jsr311 <target>: whether a target/ file proves the classes
# under it came from the 1.1 jar. Only pom.properties and maven-status are
# read: the rest of target/ is compiled output, too big to grep per module.
target_names_jsr311() {
  grep -rIls 'jsr311' "$1" --include='pom.properties' 2>/dev/null \
    | head -1 | grep -q . && return 0
  [[ -d "$1/maven-status" ]] \
    && grep -rIls 'jsr311' "$1/maven-status" 2>/dev/null \
       | head -1 | grep -q . && return 0
  return 1
}

# Artifact scan: what a built tree carries, which a POM scan cannot see.
# find, not git ls-files: target/ is ignored. A jar with jsr311-api in its
# path or Maven metadata is a hit; a class tree with javax/ws/rs classes whose
# source jar is not proven to be 2.1 is ambiguous-artifact, not a hit.
scan_artifacts() {
  local jar jarp entries rc jars=0 trees=0 kind why
  # Other worktrees live under .claude/worktrees/, each with its own target/:
  # they are different trees with different patches, so reading their jars is
  # both wrong and slow (thousands of jars on a real checkout). .git/ is
  # pruned too; build/ is pruned only outside a git work tree, as in the
  # offline scans. target/ itself is never pruned: it is where jars live.
  local -a prune=( -name .git -o -name .claude )
  if ! git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    prune+=( -o -name build )
  fi

  while IFS= read -r jar; do
    [[ -n "${jar}" ]] || continue
    jarp=${jar#"${ROOT}/"}
    jars=$((jars + 1))
    kind=""
    why=""
    if [[ "${jarp}" == *jsr311-api* ]]; then
      kind=hit; why="jsr311-api in the path"
    else
      rc=0
      entries=$(archive_entries "${jar}") || rc=$?
      if ((rc == 2)); then
        ARTIFACT_ERRORS=$((ARTIFACT_ERRORS + 1))
        kind=error; why="cannot list jar: unzip, zipinfo and jar are all missing"
      elif ((rc != 0)); then
        ARTIFACT_ERRORS=$((ARTIFACT_ERRORS + 1))
        kind=error; why="cannot list jar contents"
      elif grep -q 'META-INF/maven/javax\.ws\.rs/jsr311-api/' <<< "${entries}"; then
        kind=hit; why="META-INF/maven/javax.ws.rs/jsr311-api/pom.properties"
      fi
    fi
    case "${kind}" in
      hit)
        ARTIFACT_HITS=$((ARTIFACT_HITS + 1))
        if [[ "${JSON}" == true ]]; then
          printf '{"check":"artifact","kind":"hit","file":"%s","why":"%s"}\n' \
            "$(json_escape "${jarp}")" "$(json_escape "${why}")"
        else
          printf 'HIT        %s  %s\n' "${jarp}" "${why}"
        fi ;;
      error)
        if [[ "${JSON}" == true ]]; then
          printf '{"check":"artifact","kind":"error","file":"%s","why":"%s"}\n' \
            "$(json_escape "${jarp}")" "$(json_escape "${why}")"
        else
          printf 'ERROR      %s  %s; scan inconclusive\n' "${jarp}" "${why}"
        fi ;;
    esac
  done < <(find "${ROOT}" -type d \( "${prune[@]}" \) -prune \
    -o -type f -name '*.jar' -path '*/target/*' -print 2>/dev/null \
    | LC_ALL=C sort)

  local classes target
  while IFS= read -r classes; do
    [[ -d "${classes}/javax/ws/rs" ]] || continue
    find "${classes}/javax/ws/rs" -name '*.class' -print -quit 2>/dev/null \
      | grep -q . || continue
    trees=$((trees + 1))
    target=${classes%/classes}
    if target_names_jsr311 "${target}"; then
      ARTIFACT_HITS=$((ARTIFACT_HITS + 1))
      jarp=${classes#"${ROOT}/"}
      if [[ "${JSON}" == true ]]; then
        printf '{"check":"artifact","kind":"hit","file":"%s","why":"%s"}\n' \
          "$(json_escape "${jarp}")" 'target pom.properties or maven-status names jsr311-api'
      else
        printf 'HIT        %s  target pom.properties or maven-status names jsr311-api\n' \
          "${jarp}"
      fi
    else
      AMBIGUOUS_ARTIFACTS=$((AMBIGUOUS_ARTIFACTS + 1))
      jarp=${classes#"${ROOT}/"}
      if [[ "${JSON}" == true ]]; then
        printf '{"check":"artifact","kind":"ambiguous-artifact","file":"%s"}\n' \
          "$(json_escape "${jarp}")"
      else
        printf 'ambiguous-artifact  %s  javax/ws/rs classes, source jar not proven to be 2.1\n' \
          "${jarp}"
      fi
    fi
  done < <(find "${ROOT}" -type d \( "${prune[@]}" \) -prune \
    -o -type d -path '*/target/classes' -print 2>/dev/null \
    | LC_ALL=C sort)

  if [[ "${JSON}" != true ]]; then
    if ((jars == 0 && trees == 0)); then
      printf 'artifacts: none found (build the tree to scan jars)\n'
    fi
    printf 'artifact: %d hit(s), %d ambiguous-artifact(s), %d error(s)\n' \
      "${ARTIFACT_HITS}" "${AMBIGUOUS_ARTIFACTS}" "${ARTIFACT_ERRORS}"
  fi
}

scan_classpath() {
  ((${#MODULES[@]} > 0)) || die "--classpath needs at least one --module"
  command -v mvn >/dev/null 2>&1 || die "--classpath needs mvn on PATH"
  local m out rc
  for m in "${MODULES[@]}"; do
    m=${m#./}
    [[ -f "${ROOT}/${m}/pom.xml" ]] || die "no pom.xml in module: ${m}"
    out=$(mktemp "${TMPDIR:-/tmp}/jsr311-tree.XXXXXX")
    rc=0
    # -q keeps the log quiet; the tree goes to outputFile instead, because -q
    # would otherwise hide the INFO-level tree output and every module would
    # look clean. MAVEN_ARGS is deliberately word-split.
    # shellcheck disable=SC2086
    ( cd "${ROOT}/${m}" && mvn -q -o ${MAVEN_ARGS:-} \
        dependency:tree -Dincludes=javax.ws.rs:jsr311-api \
        -DoutputFile="${out}" ) || rc=$?
    if ((rc != 0)) || [[ ! -f "${out}" ]]; then
      CP_ERRORS=$((CP_ERRORS + 1))
      if [[ "${JSON}" == true ]]; then
        printf '{"check":"classpath","kind":"error","module":"%s","exit":%s}\n' \
          "$(json_escape "${m}")" "${rc}"
      else
        printf 'ERROR      %s  mvn dependency:tree exited %s; scan inconclusive\n' \
          "${m}" "${rc}"
      fi
    elif grep -q 'javax\.ws\.rs:jsr311-api' "${out}"; then
      CP_HITS=$((CP_HITS + 1))
      if [[ "${JSON}" == true ]]; then
        printf '{"check":"classpath","kind":"hit","module":"%s","groupId":"javax.ws.rs","artifactId":"jsr311-api"}\n' \
          "$(json_escape "${m}")"
      else
        printf 'HIT        %s  javax.ws.rs:jsr311-api resolves (all scopes)\n' "${m}"
      fi
    elif [[ "${JSON}" != true ]]; then
      printf 'ok         %s  jsr311-api is not on the resolved tree\n' "${m}"
    fi
    rm -f "${out}"
  done
}

if [[ "${EXPLAIN}" == true ]]; then
  # Keep stdout JSONL-clean when --json is also given.
  explain() {
    cat <<'EOF'
explain pom: a hit means a pom still declares the JAX-RS 1.1 API (jsr311-api) or another javax.ws.rs-coordinate jar, so the duplicate can still reach a classpath; an exclusion is the opposite and is only reported.
explain source: a 2.x-only import proves the source needs JAX-RS 2.x, so a 1.1 jar beside it is the wrong API and the duplicate is harmful, not merely redundant; ambiguous imports work against either jar and are where dropping 1.1 could silently change behaviour.
explain reference: reference, history and build-input matches are informational and never fail the run; history files describe past releases, and a resource naming the API only changes a build's input, not a declared dependency.
explain artifact: a hit means a built jar or class tree in the tree actually carries jsr311-api, which a POM scan cannot see after the declaration is gone; an ambiguous-artifact is a target/classes tree with javax/ws/rs classes whose source jar cannot be proven to be 2.1.
explain classpath: a hit means jsr311-api resolves transitively for that module, so deleting the pom declaration was not enough.
EOF
  }
  if [[ "${JSON}" == true ]]; then explain >&2; else explain; fi
fi

[[ "${JSON}" == true ]] || printf 'jsr311-scan: root %s\n' "${ROOT}"

if [[ "${POM_SCAN}" == true ]]; then
  [[ "${JSON}" == true ]] || printf '== POM scan (offline) ==\n'
  scan_poms
  if [[ "${JSON}" != true ]]; then
    printf 'pom: %d hit(s), %d exclusion(s)\n' "${POM_HITS}" "${POM_EXCLUSIONS}"
  fi
fi

if [[ "${SOURCE_SCAN}" == true ]]; then
  [[ "${JSON}" == true ]] || printf '== Source scan (offline) ==\n'
  scan_sources
  if [[ "${JSON}" != true ]]; then
    printf 'source: %d 2.x-only import(s), %d ambiguous import(s)\n' \
      "${TWO_X}" "${AMBIGUOUS}"
  fi
fi

[[ "${JSON}" == true ]] || printf '== Reference scan (offline, whole tree) ==\n'
scan_references

[[ "${JSON}" == true ]] || printf '== Artifact scan (offline) ==\n'
scan_artifacts

if [[ "${CLASSPATH_SCAN}" == true ]]; then
  [[ "${JSON}" == true ]] || printf '== Classpath scan (Maven) ==\n'
  scan_classpath
  if [[ "${JSON}" != true ]]; then
    printf 'classpath: %d hit(s), %d error(s)\n' "${CP_HITS}" "${CP_ERRORS}"
  fi
fi

if ((CP_ERRORS + ARTIFACT_ERRORS > 0)); then
  [[ "${JSON}" == true ]] \
    || printf 'FAIL: %d check(s) could not run (classpath=%d artifact=%d)\n' \
         "$((CP_ERRORS + ARTIFACT_ERRORS))" "${CP_ERRORS}" "${ARTIFACT_ERRORS}"
  exit 2
fi
if ((POM_HITS + CP_HITS + ARTIFACT_HITS > 0)); then
  [[ "${JSON}" == true ]] \
    || printf 'FAIL: JAX-RS 1.1 API still present (%d hit(s))\n' \
         "$((POM_HITS + CP_HITS + ARTIFACT_HITS))"
  exit 1
fi
[[ "${JSON}" == true ]] || printf 'PASS: no JAX-RS 1.1 hit\n'
exit 0

# Self-check (run from a Hadoop checkout; the quoted output is real, taken
# from the trees this script was written in).
#
# On a tree before the POM change, exactly one POM hit is expected (a warm run
# of the offline scans takes about 4s; a cold page cache can be slower). The
# reference scan finds no live use: the only non-Java matches are release
# changelogs and jdiff baselines, which are history and never fail. Nothing has
# been built under target/, so the artifact scan says so:
#
#   $ bash dev-support/jetty12-phase-a/jsr311-scan.sh
#   jsr311-scan: root <repo>
#   == POM scan (offline) ==
#   EXCLUSION hadoop-project/pom.xml:1898  javax.ws.rs:javax.ws.rs-api (managed)
#   HIT       hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice-hbase-tests/pom.xml:249  javax.ws.rs:jsr311-api
#   pom: 1 hit(s), 1 exclusion(s)
#   == Source scan (offline) ==
#   ...
#   module hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice-hbase-tests
#     2.x-only   .../TestTimelineReaderWebServicesHBaseStorage.java:26  javax.ws.rs.client.Client
#     2.x-only   .../AbstractTimelineReaderHBaseTestBase.java:27  javax.ws.rs.client.Client
#     2.x-only   .../AbstractTimelineReaderHBaseTestBase.java:28  javax.ws.rs.client.ClientBuilder
#     ...
#     summary: 2.x-only=3 ambiguous=48
#   ...
#   source: 183 2.x-only import(s), 864 ambiguous import(s)
#   == Reference scan (offline, whole tree) ==
#   reference: 0 reference(s), 0 build-input(s), 127 history reference(s)
#     history: past releases only, not listed (--verbose to list)
#   == Artifact scan (offline) ==
#   artifacts: none found (build the tree to scan jars)
#   artifact: 0 hit(s), 0 ambiguous-artifact(s), 0 error(s)
#   FAIL: JAX-RS 1.1 API still present (1 hit(s))
#   exit status 1
#
# With the HADOOP-20000 change applied (the PR tree unpacked at
# /tmp/jsr311-20000), zero hits and exit 0. The hadoop-project exclusion and
# all 127 history matches stay, and still do not fail:
#
#   $ bash dev-support/jetty12-phase-a/jsr311-scan.sh --root /tmp/jsr311-20000
#   jsr311-scan: root /tmp/jsr311-20000
#   == POM scan (offline) ==
#   EXCLUSION hadoop-project/pom.xml:1898  javax.ws.rs:javax.ws.rs-api (managed)
#   pom: 0 hit(s), 1 exclusion(s)
#   ...
#   source: 183 2.x-only import(s), 864 ambiguous import(s)
#   reference: 0 reference(s), 0 build-input(s), 127 history reference(s)
#   artifacts: none found (build the tree to scan jars)
#   PASS: no JAX-RS 1.1 hit
#   exit status 0
#
# The source scan resolves paths against --root too, so a tree elsewhere is
# read (here: one 2.x-only import and no POM):
#
#   $ bash dev-support/jetty12-phase-a/jsr311-scan.sh --root /tmp/jsr311-small --skip-pom
#   jsr311-scan: root /tmp/jsr311-small
#   == Source scan (offline) ==
#   module .
#     2.x-only   m/src/test/java/A.java:1  javax.ws.rs.client.Client
#     summary: 2.x-only=1 ambiguous=0
#   source: 1 2.x-only import(s), 0 ambiguous import(s)
#   == Reference scan (offline, whole tree) ==
#   == Artifact scan (offline) ==
#   artifacts: none found (build the tree to scan jars)
#   artifact: 0 hit(s), 0 ambiguous-artifact(s), 0 error(s)
#   PASS: no JAX-RS 1.1 hit
#   exit status 0
#
# A copy of that tree with a jsr311-api dependency added back to
# hadoop-common and the line "client.class=javax.ws.rs.client.Client" in
# src/main/resources/jsr311-injected.properties must exit 1 for the POM, and
# list the resource as build-input without failing on it alone:
#
#   $ bash dev-support/jetty12-phase-a/jsr311-scan.sh --root /tmp/jsr311-inject2
#   == POM scan (offline) ==
#   HIT       hadoop-common-project/hadoop-common/pom.xml:400  javax.ws.rs:jsr311-api
#   EXCLUSION hadoop-project/pom.xml:1898  javax.ws.rs:javax.ws.rs-api (managed)
#   pom: 1 hit(s), 1 exclusion(s)
#   ...
#   == Reference scan (offline, whole tree) ==
#     build-input hadoop-common-project/hadoop-common/src/main/resources/jsr311-injected.properties:1  client.class=javax.ws.rs.client.Client
#   reference: 0 reference(s), 1 build-input(s), 127 history reference(s)
#     history: past releases only, not listed (--verbose to list)
#   ...
#   FAIL: JAX-RS 1.1 API still present (1 hit(s))
#   exit status 1
#
# The artifact scan fires on a built tree, which the two trees above do not
# have. A fixture under target/ with a jsr311-api path, a jar carrying
# META-INF/maven/javax.ws.rs/jsr311-api/pom.properties, a target/pom.properties
# naming jsr311-api and a bare target/classes/javax/ws/rs class tree prints:
#
#   HIT        hadoop-common-project/hadoop-common/target/jsr311-api-1.1.1.jar  jsr311-api in the path
#   HIT        hadoop-yarn-project/hadoop-yarn/target/ordinary.jar  META-INF/maven/javax.ws.rs/jsr311-api/pom.properties
#   ambiguous-artifact  hadoop-hdfs-project/hadoop-hdfs/target/classes  javax/ws/rs classes, source jar not proven to be 2.1
#   HIT        hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-core/target/classes  target pom.properties or maven-status names jsr311-api
#   artifact: 3 hit(s), 1 ambiguous-artifact(s), 0 error(s)
#   FAIL: JAX-RS 1.1 API still present (4 hit(s))
#   exit status 1
#
# Removing the three hit fixtures leaves the class trees, the injected
# resource and the history matches; the run then exits 0:
#
#   ambiguous-artifact  hadoop-hdfs-project/hadoop-hdfs/target/classes  javax/ws/rs classes, source jar not proven to be 2.1
#   ...
#   artifact: 0 hit(s), 2 ambiguous-artifact(s), 0 error(s)
#   PASS: no JAX-RS 1.1 hit
#   exit status 0
#
# The artifact scan prunes .claude/, so it never reads another worktree's
# target/. A fixture with the same jar under .claude/worktrees/x/target/ and
# under module/target/ reports only the latter:
#
#   HIT        module/target/jsr311-api-1.1.1.jar  jsr311-api in the path
#   artifact: 1 hit(s), 0 ambiguous-artifact(s), 0 error(s)
#   FAIL: JAX-RS 1.1 API still present (1 hit(s))
#   exit status 1
#
# With the jar only under .claude/worktrees/x/target/, there is no hit:
#
#   artifacts: none found (build the tree to scan jars)
#   artifact: 0 hit(s), 0 ambiguous-artifact(s), 0 error(s)
#   PASS: no JAX-RS 1.1 hit
#   exit status 0
#
# Machine-readable: --json emits one object per finding and nothing else.
# The classpath mode is opt-in and runs Maven, e.g.:
#
#   $ MAVEN_ARGS="-Dmaven.repo.local=$HOME/.m2" \
#       ./dev-support/jetty12-phase-a/jsr311-scan.sh --classpath \
#       --module hadoop-yarn-project/hadoop-yarn/hadoop-yarn-server/hadoop-yarn-server-timelineservice-hbase-tests
