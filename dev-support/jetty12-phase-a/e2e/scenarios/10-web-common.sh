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

# The servlets and behaviour HttpServer2 gives every daemon's web server.
# This is the layer the Jetty migration touches: request routing, filters,
# response headers, error pages, directory listings, HTTP methods.

while read -r line; do
  # shellcheck disable=SC2086
  set -- ${line}
  name=$1 url=$5
  [[ "${url}" == "-" ]] && continue
  if ! grep -qx "${name} up" "${RES}/daemons.txt"; then
    COMPONENT="web:${name}" check daemon-up false "$(grep "^${name} " "${RES}/daemons.txt")"
    continue
  fi
  base=${url%/jmx}
  COMPONENT="web:${name}"

  http root "${base}/" --expect-status any
  http jmx "${base}/jmx" --shape none --expect-regex '"beans"'
  http jmx-runtime "${base}/jmx?qry=java.lang:type=Runtime" --expect-regex 'java.lang:type=Runtime'
  http jmx-get-attr "${base}/jmx?get=java.lang:type=Memory::HeapMemoryUsage"
  http jmx-jsonp "${base}/jmx?qry=java.lang:type=Runtime&callback=cb" --shape none \
    --expect-regex '^cb\('
  http jmx-bad-query "${base}/jmx?qry=not%20a%20bean" --expect-status any
  http jmx-head "${base}/jmx" --method HEAD --head-only
  http jmx-options "${base}/jmx" --method OPTIONS --expect-status any --shape none
  http jmx-trace "${base}/jmx" --method TRACE --expect-status any --shape none
  http jmx-post "${base}/jmx" --method POST --data '' --expect-status any --shape none
  http conf-xml "${base}/conf" --expect-regex '<configuration'
  http conf-json "${base}/conf?format=json" --expect-regex '"properties"'
  http conf-name "${base}/conf?name=fs.defaultFS&format=json" --expect-regex 'fs.defaultFS'
  http conf-bad-format "${base}/conf?format=yaml" --expect-status any
  http stacks "${base}/stacks" --shape none --expect-regex 'Thread'
  http loglevel-get "${base}/logLevel?log=org.apache.hadoop" --expect-regex 'org.apache.hadoop'
  http loglevel-set "${base}/logLevel?log=org.apache.hadoop.jetty12probe&level=DEBUG" \
    --expect-regex 'DEBUG'
  http logs-listing "${base}/logs/" --expect-status any
  http logs-missing "${base}/logs/no-such-file.log" --expect-status any
  http logs-traversal "${base}/logs/..%2f..%2fetc%2fpasswd" --expect-status any --shape none \
    --reject-regex 'root:x:0:0'
  http prometheus "${base}/prom" --shape none --expect-status any
  http static-dir "${base}/static/" --expect-status any
  http not-found "${base}/no/such/path" --expect-status any
  http not-found-dotdot "${base}/static/../jmx" --expect-status any --shape none
  http isactive "${base}/isActive" --expect-status any
done < <(all_daemons)
