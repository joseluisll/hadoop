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

# HDFS: file system and admin commands, WebHDFS REST (namenode redirects,
# datanode data transfer, JSON error bodies), web UIs of the namenode,
# datanode, secondary namenode and journalnode, image transfer.

COMPONENT=hdfs-cli
D=/e2e/hdfs
LOCAL="${RUN}/tmp/hdfs"
mkdir -p "${LOCAL}"
seq 1 20000 > "${LOCAL}/numbers.txt"
head -c 3000000 /dev/zero | tr '\0' 'x' > "${LOCAL}/three-mb.txt"

cli report --expect-regex 'Live datanodes \((\d+)\)' -- hdfs dfsadmin -report
cli safemode --expect-regex 'Safe mode is (\w+)' -- hdfs dfsadmin -safemode get
cli mkdir -- hadoop fs -mkdir -p "${D}/dir" "${D}/acl" "${D}/snap"
cli put -- hadoop fs -put -f "${LOCAL}/numbers.txt" "${LOCAL}/three-mb.txt" "${D}/dir/"
cli ls-recursive --shape lines -- sh -c "hadoop fs -ls -R ${D} | awk '{print \$1, \$8}'"
cli cat --shape sha256 -- hadoop fs -cat "${D}/dir/numbers.txt"
cli get -- hadoop fs -get -f "${D}/dir/numbers.txt" "${LOCAL}/numbers.copy"
check get-roundtrip "$(cmp -s "${LOCAL}/numbers.txt" "${LOCAL}/numbers.copy" && echo true || echo false)"
cli checksum --expect-regex '(MD5-of-\S+\s+\S+)' -- hadoop fs -checksum "${D}/dir/numbers.txt"
cli du --shape lines -- hadoop fs -du "${D}/dir"
cli count --shape lines -- hadoop fs -count -q "${D}"
cli df -- hadoop fs -df -h /
cli stat --expect-regex '^(\S+ \S+)' -- hadoop fs -stat '%b %r' "${D}/dir/numbers.txt"
cli setrep -- hadoop fs -setrep 1 "${D}/dir/numbers.txt"
cli chmod -- hadoop fs -chmod 750 "${D}/dir"
cli chown -- hadoop fs -chown "${USER_NAME}:supergroup" "${D}/dir"
cli truncate -- hadoop fs -truncate -w 100 "${D}/dir/three-mb.txt"
cli append -- hadoop fs -appendToFile "${LOCAL}/numbers.txt" "${D}/dir/three-mb.txt"
cli mv -- hadoop fs -mv "${D}/dir/three-mb.txt" "${D}/dir/moved.txt"
cli cp -- hadoop fs -cp "${D}/dir/numbers.txt" "${D}/dir/numbers2.txt"
cli text --shape sha256 -- hadoop fs -text "${D}/dir/numbers2.txt"
cli touchz -- hadoop fs -touchz "${D}/dir/empty"
cli test-exists -- hadoop fs -test -e "${D}/dir/empty"
cli rm-trash -- hadoop fs -rm "${D}/dir/empty"
cli setfacl -- hadoop fs -setfacl -m user:nobody:r-x "${D}/acl"
cli getfacl --shape lines -- hadoop fs -getfacl "${D}/acl"
cli setfattr -- hadoop fs -setfattr -n user.jetty12 -v phase-a "${D}/acl"
cli getfattr --shape lines -- hadoop fs -getfattr -d "${D}/acl"
cli allow-snapshot -- hdfs dfsadmin -allowSnapshot "${D}/snap"
cli snapshot-1 -- hdfs dfs -createSnapshot "${D}/snap" s1
cli snap-put -- hadoop fs -put "${LOCAL}/numbers.txt" "${D}/snap/after-s1.txt"
cli snapshot-2 -- hdfs dfs -createSnapshot "${D}/snap" s2
cli snapshot-diff --shape lines -- hdfs snapshotDiff "${D}/snap" s1 s2
cli snapshottable --shape none -- hdfs lsSnapshottableDir
cli quota -- hdfs dfsadmin -setSpaceQuota 1g "${D}/snap"
cli storage-policies --shape lines -- hdfs storagepolicies -listPolicies
cli set-storage-policy -- hdfs storagepolicies -setStoragePolicy -path "${D}/dir" -policy HOT
cli ec-policies --shape lines -- hdfs ec -listPolicies
cli cache-pool -- hdfs cacheadmin -addPool jetty12pool
cli cache-directive -- hdfs cacheadmin -addDirective -path "${D}/dir/numbers.txt" -pool jetty12pool
cli cache-list --shape none -- hdfs cacheadmin -listDirectives
cli fsck --expect-regex 'is (HEALTHY)' -- hdfs fsck "${D}" -files -blocks
cli getconf -- hdfs getconf -namenodes
cli fetch-image -- hdfs dfsadmin -fetchImage "${LOCAL}"
img=$(ls -t "${LOCAL}"/fsimage_* 2>/dev/null | head -1)
cli oiv-xml -- hdfs oiv -p XML -i "${img}" -o "${LOCAL}/fsimage.xml"
cli oiv-delimited -- hdfs oiv -p Delimited -i "${img}" -o "${LOCAL}/fsimage.tsv"
cli roll-edits -- hdfs dfsadmin -rollEdits
edits=$(ls -t "${RUN}"/data/nn/current/edits_0* 2>/dev/null | head -1)
cli oev -- hdfs oev -i "${edits}" -o "${LOCAL}/edits.xml"
cli save-namespace-enter -- hdfs dfsadmin -safemode enter
cli save-namespace -- hdfs dfsadmin -saveNamespace
cli save-namespace-leave -- hdfs dfsadmin -safemode leave
cli balancer --expect-rc 0 -- hdfs balancer -threshold 10
cli mover -- hdfs mover -p "${D}/dir"
cli diskbalancer-report --shape none -- hdfs diskbalancer -report
cli webhdfs-client-ls --shape lines -- sh -c "hadoop fs -ls webhdfs://${HOST}:${P_NN_HTTP}${D}/dir | awk '{print \$1, \$5, \$8}'"
cli webhdfs-client-cat --shape sha256 -- hadoop fs -cat "webhdfs://${HOST}:${P_NN_HTTP}${D}/dir/numbers.txt"
cli webhdfs-client-put -- hadoop fs -put -f "${LOCAL}/numbers.txt" "webhdfs://${HOST}:${P_NN_HTTP}${D}/dir/via-webhdfs.txt"
same_checksum webhdfs-client-roundtrip "${D}/dir/numbers.txt" "${D}/dir/via-webhdfs.txt"

COMPONENT=hdfs-webhdfs
W="${NN_URL}/webhdfs/v1"
U="user.name=${USER_NAME}"
http liststatus "${W}${D}/dir?op=LISTSTATUS&${U}" --expect-regex '"FileStatuses"'
http liststatus-batch "${W}${D}/dir?op=LISTSTATUS_BATCH&${U}" --expect-regex '"DirectoryListing"'
http getfilestatus "${W}${D}/dir/numbers.txt?op=GETFILESTATUS&${U}" --expect-regex '"FileStatus"'
http getfilestatus-xml "${W}${D}/dir/numbers.txt?op=GETFILESTATUS&${U}" \
  --header 'Accept: application/xml' --expect-status any
http contentsummary "${W}${D}?op=GETCONTENTSUMMARY&${U}"
http quotausage "${W}${D}?op=GETQUOTAUSAGE&${U}"
http filechecksum "${W}${D}/dir/numbers.txt?op=GETFILECHECKSUM&${U}" --expect-status 200,307
http homedir "${W}/?op=GETHOMEDIRECTORY&${U}" --expect-regex '"Path"'
http trashroot "${W}${D}?op=GETTRASHROOT&${U}"
http serverdefaults "${W}/?op=GETSERVERDEFAULTS&${U}"
http aclstatus "${W}${D}/acl?op=GETACLSTATUS&${U}" --expect-regex 'user:nobody:r-x'
http xattrs "${W}${D}/acl?op=GETXATTRS&encoding=text&${U}" --expect-regex 'user.jetty12'
http listxattrs "${W}${D}/acl?op=LISTXATTRS&${U}"
http storagepolicies "${W}/?op=GETALLSTORAGEPOLICY&${U}"
http storagepolicy "${W}${D}/dir?op=GETSTORAGEPOLICY&${U}"
http ecpolicy "${W}${D}/dir?op=GETECPOLICY&${U}" --expect-status any
http snapshotdiff "${W}${D}/snap?op=GETSNAPSHOTDIFF&oldsnapshotname=s1&snapshotname=s2&${U}"
http snapshottable "${W}/?op=GETSNAPSHOTTABLEDIRECTORYLIST&${U}"
http snapshotlist "${W}${D}/snap?op=GETSNAPSHOTLIST&${U}"
http status "${W}${D}/dir/numbers.txt?op=GETSTATUS&${U}" --expect-status any
http blocklocations "${W}${D}/dir/numbers.txt?op=GETFILEBLOCKLOCATIONS&${U}"
http open-redirect "${W}${D}/dir/numbers.txt?op=OPEN&${U}" --expect-status 307
http open-follow "${W}${D}/dir/numbers.txt?op=OPEN&${U}" --follow --shape sha256
http open-range "${W}${D}/dir/numbers.txt?op=OPEN&offset=10&length=20&${U}" --follow --shape sha256
http mkdirs "${W}${D}/rest?op=MKDIRS&permission=755&${U}" --method PUT --expect-regex '"boolean":true'
http create-redirect "${W}${D}/rest/a.txt?op=CREATE&overwrite=true&${U}" --method PUT \
  --expect-status 307 --data ''
loc=$(curl -s -i --noproxy '*' -X PUT "${W}${D}/rest/a.txt?op=CREATE&overwrite=true&${U}" \
  | tr -d '\r' | sed -n 's/^Location: //Ip')
http create-datanode "${loc}" --method PUT --data-file "${LOCAL}/numbers.txt" \
  --header 'Content-Type: application/octet-stream' --expect-status 201
same_checksum webhdfs-create-roundtrip "${D}/dir/numbers.txt" "${D}/rest/a.txt"
loc=$(curl -s -i --noproxy '*' -X POST "${W}${D}/rest/a.txt?op=APPEND&${U}" \
  | tr -d '\r' | sed -n 's/^Location: //Ip')
http append-datanode "${loc}" --method POST --data 'appended' \
  --header 'Content-Type: application/octet-stream'
http rename "${W}${D}/rest/a.txt?op=RENAME&destination=${D}/rest/b.txt&${U}" --method PUT \
  --expect-regex '"boolean":true'
http setpermission "${W}${D}/rest/b.txt?op=SETPERMISSION&permission=640&${U}" --method PUT
http setowner "${W}${D}/rest/b.txt?op=SETOWNER&owner=${USER_NAME}&${U}" --method PUT
http setreplication "${W}${D}/rest/b.txt?op=SETREPLICATION&replication=1&${U}" --method PUT
http settimes "${W}${D}/rest/b.txt?op=SETTIMES&modificationtime=1700000000000&${U}" --method PUT
http setxattr "${W}${D}/rest?op=SETXATTR&xattr.name=user.rest&xattr.value=%22v%22&flag=CREATE&${U}" \
  --method PUT
http createsnapshot "${W}${D}/snap?op=CREATESNAPSHOT&snapshotname=s3&${U}" --method PUT
http deletesnapshot "${W}${D}/snap?op=DELETESNAPSHOT&snapshotname=s3&${U}" --method DELETE
http truncate "${W}${D}/rest/b.txt?op=TRUNCATE&newlength=5&${U}" --method POST
http delegation-token "${W}/?op=GETDELEGATIONTOKEN&${U}"
http delete "${W}${D}/rest?op=DELETE&recursive=true&${U}" --method DELETE \
  --expect-regex '"boolean":true'
# Error responses: status code, content type and JSON exception body.
http err-not-found "${W}${D}/no-such-file?op=GETFILESTATUS&${U}" --expect-status 404 \
  --expect-regex 'FileNotFoundException'
http err-bad-op "${W}${D}?op=NOSUCHOP&${U}" --expect-status 400
http err-bad-param "${W}${D}?op=LISTSTATUS&permission=999x&${U}" --expect-status any
http err-wrong-method "${W}${D}?op=MKDIRS&${U}" --expect-status any
http err-permission "${W}${D}/dir?op=LISTSTATUS&user.name=nobody" --expect-status 403 \
  --expect-regex 'AccessControlException'
http err-not-dir "${W}${D}/dir/numbers.txt/child?op=MKDIRS&${U}" --method PUT --expect-status any
http no-user "${W}${D}/dir?op=LISTSTATUS" --expect-status any

COMPONENT=hdfs-web
http nn-index "${NN_URL}/index.html" --expect-status any
http nn-dfshealth "${NN_URL}/dfshealth.html"
http nn-explorer "${NN_URL}/explorer.html"
http nn-dfshealth-js "${NN_URL}/dfshealth.js" --shape sha256
http nn-static-css "${NN_URL}/static/hadoop.css" --shape sha256
http nn-static-bootstrap "${NN_URL}/static/bootstrap-3.4.1/css/bootstrap.min.css" \
  --shape sha256 --expect-status any
http nn-info "${NN_URL}/jmx?qry=Hadoop:service=NameNode,name=NameNodeInfo" \
  --expect-regex '"LiveNodes"'
http nn-status "${NN_URL}/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus" \
  --expect-regex '"State" : "active"'
http nn-fsstate "${NN_URL}/jmx?qry=Hadoop:service=NameNode,name=FSNamesystemState"
http nn-startup "${NN_URL}/startupProgress" --expect-regex '"phases"'
http nn-fsck-servlet "${NN_URL}/fsck?ugi=${USER_NAME}&path=${D}" --expect-regex 'HEALTHY'
http nn-imagetransfer-noargs "${NN_URL}/imagetransfer" --expect-status any
http nn-imagetransfer-image "${NN_URL}/imagetransfer?getimage=1&txid=latest" \
  --shape none --expect-status 200
http nn-getdelegationtoken "${NN_URL}/getDelegationToken" --expect-status any
dn_url="http://${HOST}:${P_DN_HTTP}"
http dn-index "${dn_url}/index.html" --expect-status any
http dn-datanode-html "${dn_url}/datanode.html"
http dn-info "${dn_url}/jmx?qry=Hadoop:service=DataNode,name=DataNodeInfo" \
  --expect-regex '"Version"'
http dn-webhdfs-direct "${dn_url}/webhdfs/v1${D}/dir/numbers.txt?op=OPEN&namenoderpcaddress=${HOST}:${P_NN_RPC}&${U}" \
  --shape sha256
http dn-webhdfs-bad "${dn_url}/webhdfs/v1${D}/dir/numbers.txt?op=OPEN&${U}" --expect-status any
snn_url="http://${HOST}:${P_SNN_HTTP}"
http snn-status "${snn_url}/status.html" --expect-status any
http snn-info "${snn_url}/jmx?qry=Hadoop:service=SecondaryNameNode,name=SecondaryNameNodeInfo" \
  --expect-status any
jn_url="http://${HOST}:${P_JN_HTTP}"
http jn-index "${jn_url}/index.html" --expect-status any
http jn-journal-html "${jn_url}/journal.html" --expect-status any
http jn-getjournal-noargs "${jn_url}/getJournal" --expect-status any
http jn-info "${jn_url}/jmx?qry=Hadoop:service=JournalNode,name=JournalNodeInfo" \
  --expect-status any
