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
"""What to scan: modules, their config classes, XML files and comparison tests.

The ``hdfs`` and ``rbf`` class lists mirror ``configurationClasses`` in
``TestHdfsConfigFields`` and ``TestRBFConfigFields`` exactly, including the
choice of nested types.  That correspondence is what makes the oracle
meaningful, so the lists must be kept in step with those tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

HDFS_PROJECT = "hadoop-hdfs-project"
COMMON_PROJECT = "hadoop-common-project"

_CLIENT = "org.apache.hadoop.hdfs.client.HdfsClientConfigKeys"

#: Mirrors TestHdfsConfigFields#initializeMemberVariables configurationClasses.
HDFS_CONFIG_CLASSES = [
    _CLIENT,
    _CLIENT + ".Failover",
    _CLIENT + ".StripedRead",
    "org.apache.hadoop.hdfs.DFSConfigKeys",
    _CLIENT + ".BlockWrite",
    _CLIENT + ".Write",
    _CLIENT + ".Read",
    _CLIENT + ".HedgedRead",
    _CLIENT + ".ShortCircuit",
    _CLIENT + ".Retry",
    _CLIENT + ".Mmap",
    _CLIENT + ".BlockWrite.ReplaceDatanodeOnFailure",
    _CLIENT + ".Write.ECRedundancy",
]

RBF_CONFIG_CLASSES = ["org.apache.hadoop.hdfs.server.federation.router.RBFConfigKeys"]
NFS_CONFIG_CLASSES = ["org.apache.hadoop.hdfs.nfs.conf.NfsConfigKeys"]


@dataclass
class ModuleSpec:
    """One HDFS subproject and how its properties are declared/documented."""
    key: str
    name: str
    module_path: str
    config_classes: List[str] = field(default_factory=list)
    xml_path: Optional[str] = None
    test_path: Optional[str] = None
    #: True when a Test*ConfigFields subclass enforces xml/class agreement.
    has_comparison_test: bool = False
    notes: str = ""
    #: Where this module's properties are *documented*, when that is not its
    #: own file.  Client and NFS properties belong in hdfs-default.xml, so a
    #: client key documented there is properly documented, not "elsewhere".
    doc_xml: Optional[str] = None

    @property
    def documentation_xml(self) -> Optional[str]:
        return self.doc_xml or self.xml_path


MODULES: List[ModuleSpec] = [
    ModuleSpec(
        key="hdfs",
        name="hadoop-hdfs",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs",
        config_classes=HDFS_CONFIG_CLASSES,
        xml_path=f"{HDFS_PROJECT}/hadoop-hdfs/src/main/resources/hdfs-default.xml",
        test_path=f"{HDFS_PROJECT}/hadoop-hdfs/src/test/java/org/apache/hadoop/tools/"
                  "TestHdfsConfigFields.java",
        has_comparison_test=True,
    ),
    ModuleSpec(
        key="client",
        name="hadoop-hdfs-client",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs-client",
        # HdfsClientConfigKeys and its nested types are already listed under
        # the hdfs module (mirroring TestHdfsConfigFields); repeating them here
        # would double-count.  This entry exists so the module's ~300 sources
        # are scanned for literals and accessor call sites - without it, keys
        # read only by the client (DfsClientConf, ObserverReadProxyProvider)
        # look unused.
        config_classes=[],
        xml_path=None,
        doc_xml=f"{HDFS_PROJECT}/hadoop-hdfs/src/main/resources/hdfs-default.xml",
        test_path=None,
        has_comparison_test=False,
        notes="Client-side reads of keys documented in hdfs-default.xml.",
    ),
    ModuleSpec(
        key="rbf",
        name="hadoop-hdfs-rbf",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs-rbf",
        config_classes=RBF_CONFIG_CLASSES,
        xml_path=f"{HDFS_PROJECT}/hadoop-hdfs-rbf/src/main/resources/hdfs-rbf-default.xml",
        test_path=f"{HDFS_PROJECT}/hadoop-hdfs-rbf/src/test/java/org/apache/hadoop/hdfs/"
                  "server/federation/router/TestRBFConfigFields.java",
        has_comparison_test=True,
    ),
    ModuleSpec(
        key="nfs",
        name="hadoop-hdfs-nfs",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs-nfs",
        config_classes=NFS_CONFIG_CLASSES,
        xml_path=None,
        doc_xml=f"{HDFS_PROJECT}/hadoop-hdfs/src/main/resources/hdfs-default.xml",
        test_path=None,
        has_comparison_test=False,
        notes="No comparison test exists; nfs.* keys are only partly documented "
              "in hdfs-default.xml.",
    ),
    ModuleSpec(
        key="httpfs",
        name="hadoop-hdfs-httpfs",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs-httpfs",
        config_classes=[],
        xml_path=f"{HDFS_PROJECT}/hadoop-hdfs-httpfs/src/main/resources/httpfs-default.xml",
        test_path=None,
        has_comparison_test=False,
        notes="No comparison test, and deliberately no config_classes: HttpFS "
              "composes property names at runtime.  FileSystemAccessService "
              "declares AUTHENTICATION_TYPE = \"authentication.type\" and reads it "
              "from a service-prefixed sub-Configuration, so the real property is "
              "httpfs.hadoop.authentication.type.  Feeding these classes to E1 "
              "would emit bare suffixes as if they were property names; HttpFS "
              "needs call-site reconstruction (E6) instead.",
    ),
    ModuleSpec(
        key="native",
        name="hadoop-hdfs-native-client",
        module_path=f"{HDFS_PROJECT}/hadoop-hdfs-native-client",
        config_classes=[],
        xml_path=None,
        test_path=None,
        has_comparison_test=False,
        notes="libhdfs/libhdfs++/fuse-dfs read dfs.* and hadoop.* keys from C/C++.",
    ),
]

MODULES_BY_KEY = {m.key: m for m in MODULES}

#: Config files owned by other components that HDFS code nonetheless reads.
#: Without these, properties such as ssl.server.keystore.type (owned by
#: ssl-server.xml) or mapreduce.task.attempt.id look like HDFS is failing to
#: document them, when documenting them here would be wrong.
OTHER_XML_FILES = [
    f"{COMMON_PROJECT}/hadoop-common/src/main/resources/core-default.xml",
    "hadoop-tools/hadoop-federation-balance/src/main/resources/hdfs-fedbalance-default.xml",
    f"{COMMON_PROJECT}/hadoop-common/src/main/conf/ssl-server.xml.example",
    "hadoop-mapreduce-project/hadoop-mapreduce-client/hadoop-mapreduce-client-core/"
    "src/main/resources/mapred-default.xml",
    "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-common/src/main/resources/yarn-default.xml",
]

#: Sources parsed for deprecation registries (E4).  Configuration.java carries
#: core's own table, which deprecates names HDFS code still reads (fs.default.name).
DEPRECATION_SOURCES = [
    f"{HDFS_PROJECT}/hadoop-hdfs-client/src/main/java/org/apache/hadoop/hdfs/"
    "HdfsConfiguration.java",
    f"{HDFS_PROJECT}/hadoop-hdfs-nfs/src/main/java/org/apache/hadoop/hdfs/nfs/conf/"
    "NfsConfiguration.java",
    f"{COMMON_PROJECT}/hadoop-common/src/main/java/org/apache/hadoop/conf/"
    "Configuration.java",
]

#: Roots walked to build the class-name index used for constant resolution.
INDEX_ROOTS = [HDFS_PROJECT, COMMON_PROJECT]

#: Site guides scanned for property mentions (E7).
DOC_ROOTS = [
    f"{HDFS_PROJECT}/hadoop-hdfs/src/site",
    f"{HDFS_PROJECT}/hadoop-hdfs-rbf/src/site",
    f"{HDFS_PROJECT}/hadoop-hdfs-httpfs/src/site",
]


def resolve(repo: str, relative: str) -> str:
    return os.path.join(repo, *relative.split("/"))
