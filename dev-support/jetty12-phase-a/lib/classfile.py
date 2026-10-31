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

"""Read the API of a Java class file, and the JPMS module name of a jar.

Only what binary and source compatibility depend on: class flags, super
class and interfaces, the non-private fields and methods with their flags and
erased descriptors, the class's annotation types (for Hadoop's
InterfaceAudience) and the class-file version. No JVM is needed, so whole
jars can be read quickly.
"""

import re
import struct
import zipfile

ACC_PUBLIC, ACC_PRIVATE, ACC_PROTECTED, ACC_STATIC = 0x0001, 0x0002, 0x0004, 0x0008
ACC_FINAL, ACC_SYNTHETIC, ACC_BRIDGE = 0x0010, 0x1000, 0x0040
ACC_INTERFACE, ACC_ABSTRACT, ACC_ANNOTATION, ACC_ENUM = 0x0200, 0x0400, 0x2000, 0x4000


class ClassInfo:
    """name, super, interfaces, flags, major, fields and methods.

    fields: {name: (flags, descriptor)}; methods: {name + descriptor: flags},
    both without private and synthetic members. annotations: set of the
    class's annotation type names (java form)."""

    def __init__(self, name, super_name, interfaces, flags, major, fields, methods, annotations):
        self.name, self.super, self.interfaces = name, super_name, interfaces
        self.flags, self.major = flags, major
        self.fields, self.methods, self.annotations = fields, methods, annotations

    @property
    def is_interface(self):
        return bool(self.flags & ACC_INTERFACE)

    @property
    def visible(self):
        """Public: usable from other packages. Nested classes declared
        protected are public in the class file, private ones package-private."""
        return bool(self.flags & ACC_PUBLIC)


def _java(name):
    return name.replace("/", ".") if name else None


def parse(data):
    """ClassInfo for the bytes of a class file (raises ValueError if not one)."""
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    minor, major, count = struct.unpack_from(">HHH", data, 4)
    pos, cp, i = 10, [None] * count, 1
    while i < count:
        tag = data[pos]
        if tag == 1:  # Utf8
            n = struct.unpack_from(">H", data, pos + 1)[0]
            cp[i] = data[pos + 3:pos + 3 + n].decode("utf-8", "replace")
            pos += 3 + n
        elif tag in (3, 4):  # Integer, Float
            pos += 5
        elif tag in (5, 6):  # Long, Double take two slots
            pos += 9
            i += 1
        elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
            cp[i] = ("ref", struct.unpack_from(">H", data, pos + 1)[0])
            pos += 3
        elif tag in (9, 10, 11, 12, 17, 18):  # refs, NameAndType, (Invoke)Dynamic
            pos += 5
        elif tag == 15:  # MethodHandle
            pos += 4
        else:
            raise ValueError(f"bad constant pool tag {tag}")
        i += 1

    def utf(idx):
        return cp[idx] if isinstance(cp[idx], str) else None

    def ref(idx):
        e = cp[idx]
        return utf(e[1]) if isinstance(e, tuple) else None

    flags, this_i, super_i, n_if = struct.unpack_from(">HHHH", data, pos)
    pos += 8
    interfaces = []
    for _ in range(n_if):
        interfaces.append(_java(ref(struct.unpack_from(">H", data, pos)[0])))
        pos += 2

    def members(pos):
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        out = []
        for _ in range(n):
            mf, ni, di, na = struct.unpack_from(">HHHH", data, pos)
            pos += 8
            for _ in range(na):
                pos += 6 + struct.unpack_from(">I", data, pos + 2)[0]
            out.append((mf, utf(ni), utf(di)))
        return out, pos

    raw_fields, pos = members(pos)
    raw_methods, pos = members(pos)
    annotations = set()
    n_attr = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    for _ in range(n_attr):
        ai, length = struct.unpack_from(">HI", data, pos)
        body = data[pos + 6:pos + 6 + length]
        if utf(ai) in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
            annotations |= _annotation_types(body, utf)
        pos += 6 + length
    hidden = ACC_PRIVATE | ACC_SYNTHETIC
    fields = {n: (f, d) for f, n, d in raw_fields if not f & hidden}
    methods = {n + d: f for f, n, d in raw_methods
               if not f & (hidden | ACC_BRIDGE) and n != "<clinit>"}
    return ClassInfo(_java(ref(this_i)), _java(ref(super_i)) if super_i else None,
                     interfaces, flags, major, fields, methods, annotations)


def _annotation_types(body, utf):
    """Type names of the top-level annotations in an annotations attribute."""
    out = set()
    try:
        n = struct.unpack_from(">H", body, 0)[0]
        pos = 2
        for _ in range(n):
            t = utf(struct.unpack_from(">H", body, pos)[0])
            if t and t.startswith("L") and t.endswith(";"):
                out.add(t[1:-1].replace("/", ".").replace("$", "."))
            pos = _skip_annotation(body, pos)
    except (struct.error, IndexError):
        pass
    return out


def _skip_annotation(b, pos):
    pairs = struct.unpack_from(">H", b, pos + 2)[0]
    pos += 4
    for _ in range(pairs):
        pos = _skip_value(b, pos + 2)
    return pos


def _skip_value(b, pos):
    tag = chr(b[pos])
    pos += 1
    if tag in "BCDFIJSZsc":
        return pos + 2
    if tag == "e":
        return pos + 4
    if tag == "@":
        return _skip_annotation(b, pos)
    if tag == "[":
        n = struct.unpack_from(">H", b, pos)[0]
        pos += 2
        for _ in range(n):
            pos = _skip_value(b, pos)
        return pos
    raise ValueError(f"bad element value tag {tag}")


def module_name(path):
    """(name, how) of a jar as a JPMS module: its module descriptor, its
    Automatic-Module-Name, or the name the JDK derives from the file name."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        descriptors = ["module-info.class"] + sorted(
            n for n in names if re.fullmatch(r"META-INF/versions/\d+/module-info\.class", n))
        for d in descriptors:
            if d in names:
                name = _descriptor_name(z.read(d))
                if name:
                    return name, "module-info"
        if "META-INF/MANIFEST.MF" in names:
            for line in z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace").splitlines():
                if line.startswith("Automatic-Module-Name:"):
                    return line.split(":", 1)[1].strip(), "Automatic-Module-Name"
    return derived_module_name(path), "derived from the file name"


def derived_module_name(path):
    """java.lang.module.ModuleFinder's rule for an automatic module."""
    name = re.sub(r"\.jar$", "", path.rsplit("/", 1)[-1])
    m = re.search(r"-(\d+(\.|$))", name)
    if m:
        name = name[:m.start()]
    name = re.sub(r"[^A-Za-z0-9]", ".", name)
    name = re.sub(r"\.+", ".", name).strip(".")
    return name


def _descriptor_name(data):
    """The module name in a module-info.class (its this_class is 'module-info';
    the name is in the Module attribute's first entry)."""
    try:
        if data[:4] != b"\xca\xfe\xba\xbe":
            return None
        count = struct.unpack_from(">H", data, 8)[0]
        pos, cp, i = 10, [None] * count, 1
        while i < count:
            tag = data[pos]
            if tag == 1:
                n = struct.unpack_from(">H", data, pos + 1)[0]
                cp[i] = data[pos + 3:pos + 3 + n].decode("utf-8", "replace")
                pos += 3 + n
            elif tag in (3, 4):
                pos += 5
            elif tag in (5, 6):
                pos += 9
                i += 1
            elif tag in (7, 8, 16, 19, 20):
                cp[i] = ("ref", struct.unpack_from(">H", data, pos + 1)[0])
                pos += 3
            elif tag in (9, 10, 11, 12, 17, 18):
                pos += 5
            elif tag == 15:
                pos += 4
            else:
                return None
            i += 1
        pos += 6
        pos += 2 + 2 * struct.unpack_from(">H", data, pos)[0]
        for _ in range(2):  # fields, methods: none in a descriptor, but skip them anyway
            n = struct.unpack_from(">H", data, pos)[0]
            pos += 2
            for _ in range(n):
                na = struct.unpack_from(">H", data, pos + 6)[0]
                pos += 8
                for _ in range(na):
                    pos += 6 + struct.unpack_from(">I", data, pos + 2)[0]
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(n):
            ai, length = struct.unpack_from(">HI", data, pos)
            if cp[ai] == "Module":
                mod = cp[struct.unpack_from(">H", data, pos + 6)[0]]
                return cp[mod[1]] if isinstance(mod, tuple) else None
            pos += 6 + length
    except (struct.error, IndexError, TypeError):
        return None
    return None
