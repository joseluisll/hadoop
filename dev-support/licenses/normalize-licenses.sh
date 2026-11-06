#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Normalize the license texts downloaded by license-maven-plugin into the
# project's LICENSE-<name>.txt convention.
#
# Usage: normalize-licenses.sh <downloaded-licenses-dir> <output-dir>
set -euo pipefail

src_dir="$1"
out_dir="$2"
mkdir -p "$out_dir"

# canonical merged license name -> project file slug
slug() {
  case "$1" in
    "The Apache Software License, Version 2.0") echo "apache-2.0" ;;
    "MIT License")                            echo "mit" ;;
    "BSD 2-Clause License")                   echo "bsd-2-clause" ;;
    "Revised BSD")                            echo "bsd-3-clause" ;;
    "BSD License")                            echo "bsd" ;;
    "Eclipse Public License - Version 1.0")   echo "epl-1.0" ;;
    "EPL 2.0")                                echo "epl-2.0" ;;
    "EDL 1.0")                                echo "edl-1.0" ;;
    "CDDL + GPLv2 with classpath exception")  echo "cddl-gplv2-ce" ;;
    "MPL 1.1")                                echo "mpl-1.1" ;;
    "LGPL 2.1")                               echo "lgpl-2.1" ;;
    "The Go License")                         echo "go" ;;
    "Bouncy Castle Licence")                  echo "bouncycastle" ;;
    "W3C License")                            echo "w3c" ;;
    "Public Domain")                          echo "public-domain" ;;
    "jQuery License")                         echo "jquery" ;;
    "JSON")                                   echo "json" ;;
    # fallback: lowercase, keep alphanumerics
    *) echo "$1" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9' | cut -c1-40 ;;
  esac
}

shopt -s nullglob
for f in "$src_dir"/*; do
  base="$(basename "$f")"
  # downloaded files are named "<license name> - <original file>"
  license_name="${base%% - *}"
  # prefer .txt sources when both html and txt exist for the same license
  s="$(slug "$license_name")"
  dest="$out_dir/LICENSE-$s.txt"
  if [[ -f "$dest" && "$f" == *.html ]]; then
    continue
  fi
  cp "$f" "$dest"
done

echo "Normalized $(ls "$out_dir" | wc -l) license files into $out_dir"
