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

# Secure architecture: TLS as each web server negotiates it, SPNEGO and
# its refusals, the hadoop.auth cookie, Kerberos diagnostics (KDiag), RPC
# without credentials, and the WebHDFS delegation token life cycle (get,
# use without Kerberos, renew, cancel, refused after cancel).

D=/e2e/secure
U="user.name=${USER_NAME}"
hadoop fs -mkdir -p "${D}"
seq 1 2000 | hadoop fs -put -f - "${D}/data.txt"

COMPONENT=secure-tls
for line in "${INSTANCES[@]}"; do
  # shellcheck disable=SC2086
  set -- ${line}
  [[ "$5" == https://* ]] && daemon_up "$1" || continue
  python3 -I "${PROBE}" tls --obs "${OBS}" --component "${COMPONENT}" --id "$1" --url "$5"
done

COMPONENT=secure-spnego
http nn-no-credentials "${NN_URL}/webhdfs/v1/?op=LISTSTATUS" --no-auth --expect-status 401
http nn-negotiate "${NN_URL}/webhdfs/v1/?op=LISTSTATUS" --expect-status 200
http nn-cookie "${NN_URL}/jmx?qry=java.lang:type=Runtime" --expect-status 200 --shape none
http rm-no-credentials "${RM_URL}/ws/v1/cluster/info" --no-auth --expect-status 401
http rm-negotiate "${RM_URL}/ws/v1/cluster/info" --expect-regex '"clusterInfo"'
http kms-no-credentials "${KMS_URL}/kms/v1/keys/names" --no-auth --expect-status 401
http httpfs-no-credentials "${HTTPFS_URL}/webhdfs/v1/?op=LISTSTATUS" --no-auth --expect-status 401
http jhs-no-credentials "${JHS_URL}/ws/v1/history/info" --no-auth --expect-status 401
http ahs-no-credentials "${AHS_URL}/ws/v1/timeline" --no-auth --expect-status any
http bad-token-cookie "${NN_URL}/jmx" --no-auth --header 'Cookie: hadoop.auth="u=x&p=x&t=kerberos&e=1&s=forged"' \
  --expect-status 401 --shape none

COMPONENT=secure-kerberos
cli kdiag --merge-stderr --expect-regex '(?m)^== (Kerberos Diagnostics scan)' -- \
  hadoop org.apache.hadoop.security.KDiag --keytab "${KEYTAB}" --principal "nn/${HOST}@${REALM}"
cli whoami --expect-regex '(\S+)' -- hadoop org.apache.hadoop.security.UserGroupInformation
cli rpc-without-ticket --merge-stderr --expect-rc 1 \
  --expect-regex '(Client cannot authenticate via|GSS initiate failed|SIMPLE authentication is not enabled)' \
  -- env KRB5CCNAME="FILE:${RUN}/tmp/no-such-ccache" hadoop fs -ls /
# A token fetched over HTTPS is for SWEBHDFS; RPC needs one fetched over RPC.
cli fetchdt-web -- hdfs fetchdt --webservice "${NN_URL}" "${RUN}/tmp/web.token"
cli fetchdt-web-print --expect-regex '(SWEBHDFS delegation token)' -- \
  hdfs fetchdt --print "${RUN}/tmp/web.token"
cli fetchdt -- hdfs fetchdt "${RUN}/tmp/hdfs.token"
cli fetchdt-print --expect-regex '(HDFS_DELEGATION_TOKEN)' -- hdfs fetchdt --print "${RUN}/tmp/hdfs.token"
cli rpc-with-token-file --shape sha256 -- \
  env KRB5CCNAME="FILE:${RUN}/tmp/no-such-ccache" HADOOP_TOKEN_FILE_LOCATION="${RUN}/tmp/hdfs.token" \
  hadoop fs -cat "${D}/data.txt"

COMPONENT=secure-webhdfs-token
W="${NN_URL}/webhdfs/v1"
http get-token "${W}/?op=GETDELEGATIONTOKEN&renewer=${USER_NAME}" --expect-regex '"urlString"' \
  --out "${RUN}/tmp/webhdfs-token.json"
TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["Token"]["urlString"])' \
  "${RUN}/tmp/webhdfs-token.json" 2>/dev/null || echo none)
http open-with-token "${W}${D}/data.txt?op=OPEN&delegation=${TOKEN}" --no-auth --follow --shape sha256
http status-with-token "${W}${D}/data.txt?op=GETFILESTATUS&delegation=${TOKEN}" --no-auth \
  --expect-regex '"FileStatus"'
http renew-token "${W}/?op=RENEWDELEGATIONTOKEN&token=${TOKEN}" --method PUT --data '' \
  --expect-regex '"long"'
http cancel-token "${W}/?op=CANCELDELEGATIONTOKEN&token=${TOKEN}" --method PUT --data '' \
  --expect-status 200
http open-with-cancelled-token "${W}${D}/data.txt?op=GETFILESTATUS&delegation=${TOKEN}" --no-auth \
  --expect-status 401,403
http httpfs-get-token "${HTTPFS_URL}/webhdfs/v1/?op=GETDELEGATIONTOKEN" --expect-regex '"urlString"'
http kms-get-token "${KMS_URL}/kms/v1/?op=GETDELEGATIONTOKEN&renewer=${USER_NAME}" --expect-status any
