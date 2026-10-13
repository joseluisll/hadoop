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

# The servlets and behaviour HttpServer2 gives every daemon's web server,
# for every daemon instance of the architecture. This is the layer the
# Jetty migration touches: request routing, filters, authentication,
# response headers, error pages, directory listings, HTTP methods, TLS.

# KMS and HttpFS authenticate every request; user.name is ignored by the
# others (and under Kerberos the SPNEGO identity wins).
U="user.name=${USER_NAME}"

for line in "${INSTANCES[@]}"; do
  # shellcheck disable=SC2086
  set -- ${line}
  name=$1 url=$5
  [[ "${url}" == "-" ]] && continue
  COMPONENT="web:${name}"
  if ! daemon_up "${name}"; then
    check daemon-up false "$(grep "^${name} " "${RES}/daemons.txt")"
    continue
  fi
  base=${url%/jmx}

  http root "${base}/" --expect-status any
  http jmx "${base}/jmx?${U}" --shape none --expect-regex '"beans"'
  http jmx-runtime "${base}/jmx?qry=java.lang:type=Runtime&${U}" \
    --expect-regex 'java.lang:type=Runtime'
  http jmx-get-attr "${base}/jmx?get=java.lang:type=Memory::HeapMemoryUsage&${U}"
  http jmx-callback "${base}/jmx?qry=java.lang:type=Runtime&callback=cb&${U}" --shape none \
    --reject-regex '^cb\('
  http jmx-bad-query "${base}/jmx?qry=not%20a%20bean&${U}" --expect-status any
  http jmx-no-user "${base}/jmx" --expect-status any --shape none
  http jmx-head "${base}/jmx?${U}" --method HEAD --head-only
  http jmx-options "${base}/jmx?${U}" --method OPTIONS --expect-status any --shape none
  http jmx-trace "${base}/jmx?${U}" --method TRACE --expect-status any --shape none
  http jmx-post "${base}/jmx?${U}" --method POST --data '' --expect-status any --shape none
  http conf-xml "${base}/conf?${U}" --expect-regex '<configuration'
  http conf-json "${base}/conf?${U}" --header 'Accept: application/json' \
    --expect-regex '"properties"'
  http conf-name "${base}/conf?name=fs.defaultFS&${U}" --header 'Accept: application/json' \
    --expect-regex 'fs.defaultFS'
  http conf-bad-name "${base}/conf?name=no.such.property&${U}" --expect-status any
  http stacks "${base}/stacks?${U}" --shape none --expect-regex 'Thread'
  http loglevel-get "${base}/logLevel?log=org.apache.hadoop&${U}" --expect-regex 'org.apache.hadoop'
  http loglevel-set "${base}/logLevel?log=org.apache.hadoop.jetty12probe&level=DEBUG&${U}" \
    --expect-regex 'DEBUG'
  http logs-listing "${base}/logs/?${U}" --expect-status any
  http logs-missing "${base}/logs/no-such-file.log?${U}" --expect-status any
  http logs-traversal "${base}/logs/..%2f..%2fetc%2fpasswd?${U}" --expect-status any --shape none \
    --reject-regex 'root:x:0:0'
  http prometheus "${base}/prom?${U}" --shape none --expect-status any
  http static-dir "${base}/static/?${U}" --expect-status any
  http not-found "${base}/no/such/path?${U}" --expect-status any
  http not-found-dotdot "${base}/static/../jmx?${U}" --expect-status any --shape none
  http isactive "${base}/isActive?${U}" --expect-status any
  # The other scheme: under HTTPS_ONLY the plain HTTP port must be closed.
  if [[ "${base}" == https://* ]]; then
    http plain-http "http://${base#https://}/jmx" --expect-status any --shape none --allow-error
    http no-credentials "${base}/jmx" --no-auth --expect-status 401 --shape none
  fi
done
