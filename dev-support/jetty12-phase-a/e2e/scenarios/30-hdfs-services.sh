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

# HDFS services that run their own web servers: the RBF router, HttpFS
# (HADOOP-20016 declares jetty-http in it), KMS with encryption zones, and
# the NFS gateway.

LOCAL="${RUN}/tmp/services"
mkdir -p "${LOCAL}"
seq 1 5000 > "${LOCAL}/data.txt"
U="user.name=${USER_NAME}"

# ------------------------------------------------------------------ RBF
if daemon_up dfsrouter; then
  COMPONENT=hdfs-rbf
  R_URL="http://${HOST}:${P_ROUTER_HTTP}"
  RFS="hdfs://${HOST}:${P_ROUTER_RPC}"
  hadoop fs -mkdir -p /e2e/rbf-target
  hadoop fs -put -f "${LOCAL}/data.txt" /e2e/rbf-target/data.txt
  cli mount-add -- hdfs dfsrouteradmin -add /rbf ns0 /e2e/rbf-target
  # The router reads new mounts from its state store on refresh.
  hdfs dfsrouteradmin -refresh >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    hdfs dfsrouteradmin -ls /rbf 2>/dev/null | grep -q "^/rbf " && break
    sleep 1
  done
  cli mount-ls --shape lines -- hdfs dfsrouteradmin -ls /rbf
  # The router refreshes its mount table cache periodically; ask now.
  cli mount-refresh -- hdfs dfsrouteradmin -refresh
  cli safemode --expect-regex 'Safe Mode: (\w+)' -- hdfs dfsrouteradmin -safemode get
  cli rpc-ls --shape lines -- sh -c "hadoop fs -ls ${RFS}/rbf | awk '{print \$1, \$5, \$8}'"
  cli rpc-cat --shape sha256 -- hadoop fs -cat "${RFS}/rbf/data.txt"
  cli rpc-put -- hadoop fs -put -f "${LOCAL}/data.txt" "${RFS}/rbf/via-router.txt"
  same_checksum rpc-roundtrip /e2e/rbf-target/data.txt /e2e/rbf-target/via-router.txt
  http webhdfs-liststatus "${R_URL}/webhdfs/v1/rbf?op=LISTSTATUS&${U}" --expect-regex '"FileStatuses"'
  http webhdfs-open "${R_URL}/webhdfs/v1/rbf/data.txt?op=OPEN&${U}" --follow --shape sha256
  http webhdfs-not-found "${R_URL}/webhdfs/v1/rbf/none?op=GETFILESTATUS&${U}" --expect-status 404
  http federationhealth "${R_URL}/federationhealth.html"
  http router-index "${R_URL}/index.html" --expect-status any
  http router-info "${R_URL}/jmx?qry=Hadoop:service=Router,name=Router" --expect-status any
  http router-federation "${R_URL}/jmx?qry=Hadoop:service=Router,name=FederationState" \
    --expect-status any
  http router-namenodes "${R_URL}/jmx?qry=Hadoop:service=Router,name=Router*" --expect-status any

fi
# ---------------------------------------------------------------- HttpFS
if daemon_up httpfs; then
  COMPONENT=httpfs
  H="${HTTPFS_URL}/webhdfs/v1"
  hadoop fs -mkdir -p /e2e/httpfs
  hadoop fs -put -f "${LOCAL}/data.txt" /e2e/httpfs/data.txt
  http liststatus "${H}/e2e/httpfs?op=LISTSTATUS&${U}" --expect-regex '"FileStatuses"'
  http getfilestatus "${H}/e2e/httpfs/data.txt?op=GETFILESTATUS&${U}" --expect-regex '"FileStatus"'
  http contentsummary "${H}/e2e/httpfs?op=GETCONTENTSUMMARY&${U}"
  http quotausage "${H}/e2e/httpfs?op=GETQUOTAUSAGE&${U}" --expect-status any
  http filechecksum "${H}/e2e/httpfs/data.txt?op=GETFILECHECKSUM&${U}"
  http homedir "${H}/?op=GETHOMEDIRECTORY&${U}"
  http trashroot "${H}/e2e/httpfs?op=GETTRASHROOT&${U}"
  http serverdefaults "${H}/?op=GETSERVERDEFAULTS&${U}" --expect-status any
  http aclstatus "${H}/e2e/httpfs?op=GETACLSTATUS&${U}"
  http storagepolicies "${H}/?op=GETALLSTORAGEPOLICY&${U}"
  http open "${H}/e2e/httpfs/data.txt?op=OPEN&${U}" --shape sha256
  http open-range "${H}/e2e/httpfs/data.txt?op=OPEN&offset=5&length=50&${U}" --shape sha256
  http mkdirs "${H}/e2e/httpfs/sub?op=MKDIRS&${U}" --method PUT --expect-regex '"boolean":true'
  http create-noredirect "${H}/e2e/httpfs/sub/new.txt?op=CREATE&overwrite=true&${U}" \
    --method PUT --data '' --expect-status 307
  http create-data "${H}/e2e/httpfs/sub/new.txt?op=CREATE&data=true&overwrite=true&${U}" \
    --method PUT --data-file "${LOCAL}/data.txt" \
    --header 'Content-Type: application/octet-stream' --expect-status 201
  same_checksum create-roundtrip /e2e/httpfs/data.txt /e2e/httpfs/sub/new.txt
  http append-data "${H}/e2e/httpfs/sub/new.txt?op=APPEND&data=true&${U}" --method POST \
    --data 'more' --header 'Content-Type: application/octet-stream'
  http rename "${H}/e2e/httpfs/sub/new.txt?op=RENAME&destination=/e2e/httpfs/sub/renamed.txt&${U}" \
    --method PUT --expect-regex '"boolean":true'
  http setpermission "${H}/e2e/httpfs/sub/renamed.txt?op=SETPERMISSION&permission=600&${U}" \
    --method PUT
  http setxattr "${H}/e2e/httpfs/sub?op=SETXATTR&xattr.name=user.h&xattr.value=%22v%22&flag=CREATE&${U}" \
    --method PUT
  http getxattrs "${H}/e2e/httpfs/sub?op=GETXATTRS&encoding=text&${U}"
  http delete "${H}/e2e/httpfs/sub?op=DELETE&recursive=true&${U}" --method DELETE \
    --expect-regex '"boolean":true'
  http err-not-found "${H}/e2e/httpfs/none?op=GETFILESTATUS&${U}" --expect-status 404 \
    --expect-regex 'FileNotFoundException'
  http err-bad-op "${H}/e2e/httpfs?op=NOSUCHOP&${U}" --expect-status any
  http err-no-user "${H}/e2e/httpfs?op=LISTSTATUS" --expect-status any
  http err-permission "${H}/e2e/httpfs?op=MKDIRS&user.name=nobody" --method PUT \
    --expect-status any
  http index "${HTTPFS_URL}/index.html" --expect-status any
  http static-index "${HTTPFS_URL}/static/index.html" --expect-status any
  cli webhdfs-client-ls --shape lines -- sh -c "hadoop fs -ls ${HTTPFS_FS}/e2e/httpfs | awk '{print \$1, \$5, \$8}'"
  cli webhdfs-client-cat --shape sha256 -- hadoop fs -cat "${HTTPFS_FS}/e2e/httpfs/data.txt"

fi
# ------------------------------------------------------------------- KMS
if daemon_up kms; then
  COMPONENT=kms
  KP="${KMS_PROVIDER}"
  K="${KMS_URL}/kms/v1"
  cli key-create -- hadoop key create jetty12key -provider "${KP}" -size 128
  cli key-create-ez -- hadoop key create ezkey -provider "${KP}"
  cli key-list --shape lines -- hadoop key list -provider "${KP}"
  cli key-list-metadata --shape none --expect-regex '(jetty12key) : cipher: (\S+), length: (\d+)' \
    -- hadoop key list -provider "${KP}" -metadata
  cli key-roll -- hadoop key roll jetty12key -provider "${KP}"
  cli key-invalidate-cache -- hadoop key invalidateCache jetty12key -provider "${KP}"
  http keys-names "${K}/keys/names?${U}" --expect-regex 'jetty12key'
  http keys-metadata "${K}/keys/metadata?key=jetty12key&key=ezkey&${U}"
  http key-metadata "${K}/key/jetty12key/_metadata?${U}" --expect-regex '"cipher"'
  http key-current "${K}/key/jetty12key/_currentversion?${U}" --expect-regex '"material"'
  http key-versions "${K}/key/jetty12key/_versions?${U}"
  http key-eek-generate "${K}/key/jetty12key/_eek?eek_op=generate&num_keys=2&${U}" \
    --expect-regex '"encryptedKeyVersion"' --out "${LOCAL}/eek.json"
  # Decrypt takes the key name, the IV and the encrypted material.
  eek=$(python3 -c 'import json, sys
e = json.load(open(sys.argv[1]))[0]
print(json.dumps({"name": "jetty12key", "iv": e["iv"],
                  "material": e["encryptedKeyVersion"]["material"]}))' "${LOCAL}/eek.json" 2>/dev/null \
    || echo '{}')
  versionname=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[0]["versionName"])' \
    "${LOCAL}/eek.json" 2>/dev/null || echo none)
  http key-eek-decrypt "${K}/keyversion/${versionname}/_eek?eek_op=decrypt&${U}" --method POST \
    --data "${eek}" --header 'Content-Type: application/json' --expect-regex '"material"'
  http key-create-rest "${K}/keys?${U}" --method POST --header 'Content-Type: application/json' \
    --data '{"name":"restkey","cipher":"AES/CTR/NoPadding","length":128}' --expect-status 201
  http key-delete-rest "${K}/key/restkey?${U}" --method DELETE
  http err-unknown-key "${K}/key/nosuchkey/_metadata?${U}" --expect-status any
  http err-bad-json "${K}/keys?${U}" --method POST --header 'Content-Type: application/json' \
    --data '{not json' --expect-status any
  http err-no-user "${K}/keys/names" --expect-status any
  http kms-index "${KMS_URL}/index.html" --expect-status any
  COMPONENT=hdfs-encryption
  hadoop fs -mkdir -p /e2e/ez
  cli create-zone -- hdfs crypto -createZone -keyName ezkey -path /e2e/ez
  cli list-zones --shape lines -- hdfs crypto -listZones
  cli ez-put -- hadoop fs -put -f "${LOCAL}/data.txt" /e2e/ez/secret.txt
  cli ez-cat --shape sha256 -- hadoop fs -cat /e2e/ez/secret.txt
  cli ez-file-info --expect-regex '(keyName: \S+)' -- hdfs crypto -getFileEncryptionInfo -path /e2e/ez/secret.txt
  cli ez-raw-differs --shape none -- sh -c "! hadoop fs -cat /.reserved/raw/e2e/ez/secret.txt | cmp -s - ${LOCAL}/data.txt"
  http ez-webhdfs-open "${NN_URL}/webhdfs/v1/e2e/ez/secret.txt?op=OPEN&${U}" --follow --shape sha256
  http ez-httpfs-open "${H}/e2e/ez/secret.txt?op=OPEN&${U}" --shape sha256

fi
# ------------------------------------------------------------------- NFS
if grep -q '^nfs3 ' "${RES}/daemons.txt"; then
  COMPONENT=hdfs-nfs
  if grep -qx 'nfs3 up' "${RES}/daemons.txt"; then
    http nfs-info "http://${HOST}:${P_NFS_HTTP}/jmx?qry=Hadoop:service=Nfs3,*" --expect-status any
    if command -v rpcinfo >/dev/null; then
      cli rpcinfo --expect-regex '(mountd)' --expect-regex '(nfs)' -- rpcinfo -p "${HOST}"
    fi
    if command -v showmount >/dev/null; then
      cli showmount --shape lines -- showmount -e "${HOST}"
    fi
  else
    check nfs3-up false "$(grep -E '^(portmap|nfs3) ' "${RES}/daemons.txt" | tr '\n' ' ')"
  fi
fi
