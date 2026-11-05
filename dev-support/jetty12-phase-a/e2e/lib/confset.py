#!/usr/bin/env python3
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

"""Set properties in a Hadoop configuration file, creating it if needed.

Usage: confset.py <file> name=value [name=value ...]

An existing property of the same name is replaced; "name=" with an empty
value is kept as an empty value, "name" without "=" removes the property.
"""

import os
import sys
import xml.etree.ElementTree as ET


def main(path, pairs):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        tree = ET.parse(path)
        root = tree.getroot()
    else:
        root = ET.Element("configuration")
        tree = ET.ElementTree(root)
    for pair in pairs:
        name, eq, value = pair.partition("=")
        for p in list(root.findall("property")):
            if p.findtext("name") == name:
                root.remove(p)
        if eq:
            p = ET.SubElement(root, "property")
            ET.SubElement(p, "name").text = name
            ET.SubElement(p, "value").text = value
    ET.indent(tree)
    tree.write(path, xml_declaration=True, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
