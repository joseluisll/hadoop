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
# (downloaded file names are lowercased by the plugin, so match lowercase)
slug() {
  local name
  name="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
  case "$name" in
    "the apache software license, version 2.0") echo "apache-2.0" ;;
    "mit license")                              echo "mit" ;;
    "bsd 2-clause license")                     echo "bsd-2-clause" ;;
    "revised bsd"|"bsd-3-clause")               echo "bsd-3-clause" ;;
    "bsd license"|"the bsd license")            echo "bsd" ;;
    "eclipse public license - version 1.0")     echo "epl-1.0" ;;
    "epl 2.0")                                  echo "epl-2.0" ;;
    "edl 1.0")                                  echo "edl-1.0" ;;
    "cddl + gplv2 with classpath exception")    echo "cddl-gplv2-ce" ;;
    "mpl 1.1")                                  echo "mpl-1.1" ;;
    "lgpl 2.1")                                 echo "lgpl-2.1" ;;
    "the go license")                           echo "go" ;;
    "bouncy castle licence")                    echo "bouncycastle" ;;
    "w3c license")                              echo "w3c" ;;
    "public domain")                            echo "public-domain" ;;
    "jquery license")                           echo "jquery" ;;
    "json")                                     echo "json" ;;
    # fallback: keep alphanumerics
    *) echo "$name" | tr -cd 'a-z0-9' | cut -c1-40 ;;
  esac
}

shopt -s nullglob
for f in "$src_dir"/*; do
  base="$(basename "$f")"
  # downloaded files are named "<license name> - <original file>";
  # strip the last separator only: license names can contain " - "
  license_name="${base% - *}"
  # prefer .txt sources when both html and txt exist for the same license
  s="$(slug "$license_name")"
  dest="$out_dir/LICENSE-$s.txt"
  if [[ -f "$dest" && "$f" == *.html ]]; then
    continue
  fi
  cp "$f" "$dest"
done

echo "Normalized $(ls "$out_dir" | wc -l) license files into $out_dir"
