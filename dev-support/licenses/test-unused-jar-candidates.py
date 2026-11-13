#!/usr/bin/env python3
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
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied.  See the License for the specific
# language governing permissions and limitations under the License.
"""Synthetic self-test for unused-jar-candidates.py. Run: python3 <this file>"""

import io
import os
import struct
import subprocess
import sys
import tempfile
import zipfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "unused-jar-candidates.py")


def cls(*utf8s):
    """A class file whose constant pool holds a long and these strings."""
    pool = b"\x05" + struct.pack(">q", 42)  # long: takes two slots
    for s in utf8s:
        b = s.encode()
        pool += b"\x01" + struct.pack(">H", len(b)) + b
    count = 1 + 2 + len(utf8s)
    # bytes after the pool that a parser miscounting the long's two slots
    # would read as one more Utf8 naming a class (a false reference)
    trailer = b"\x01\x00\x0acom/y/Nope"
    return (b"\xca\xfe\xba\xbe\x00\x00\x00\x3d" + struct.pack(">H", count)
            + pool + trailer)


def zbytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def write(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


LIB = "h/share/hadoop/common/lib/"
OWN = "h/share/hadoop/common/hadoop-common-1.jar"
WAR = "h/share/hadoop/yarn/app.war"
TOOLS = "h/share/hadoop/tools/lib/"
TLS = "h/share/hadoop/yarn/timelineservice/"

JARS = {
    OWN: ("org.apache.hadoop", "hadoop-common", {
        "org/apache/hadoop/A.class": cls("(Lcom/x/Used;)V", "com.s.ByName",
                                         "com/sh/Shared", "com/a/Api",
                                         "com/ma/Api",
                                         "com/r/schema.xsd",
                                         "/com/r2/conf.properties",
                                         "/bare.properties"),
        "META-INF/native-image/x/reflect-config.json": b'["com.m.M"]',
    }),
    LIB + "used-1.jar": ("com.x", "used", {"com/x/Used.class": cls()}),
    LIB + "unused-1.jar": ("com.y", "unused",
                           {"com/y/Nope.class": cls("com/y/Nope")}),
    # a duplicate copy of unused (hdfs/lib repeats common/lib): the jar's
    # classes reference themselves, and the copies' shared scan sets make
    # each copy's references resolve to BOTH copies — that is still not
    # use: both copies stay zero-inbound candidates
    "h/share/hadoop/hdfs/lib/unused-1.jar": ("com.y", "unused",
                                             {"com/y/Nope.class": cls("com/y/Nope")}),
    LIB + "svc-1.jar": ("com.z", "svc", {
        "com/z/D.class": cls("com/z/D"), "META-INF/services/java.sql.Driver": b"com.z.D\n"}),
    LIB + "proc-1.jar": ("com.p", "proc", {
        "com/p/P.class": cls(),
        "META-INF/services/javax.annotation.processing.Processor": b"com.p.P\n"}),
    LIB + "str-1.jar": ("com.s", "str", {"com/s/ByName.class": cls()}),
    LIB + "meta-1.jar": ("com.m", "meta", {"com/m/M.class": cls()}),
    LIB + "native-1.jar": ("com.n", "native", {"libfoo.so": b"\x7fELF"}),
    LIB + "cfg-1.jar": ("com.c", "cfg", {"com/c/Cfg.class": cls()}),
    LIB + "kept-1.jar": ("com.k", "kept", {"com/k/K.class": cls()}),
    # used only for a resource, by path (with and without a leading
    # slash); a bare file name, even with a leading slash, does not count
    LIB + "res-1.jar": ("com.r", "res", {"com/r/R.class": cls(),
                                         "com/r/schema.xsd": b"<xs/>"}),
    LIB + "res2-1.jar": ("com.r2", "res2", {"com/r2/R.class": cls(),
                                            "com/r2/conf.properties": b"k=v"}),
    LIB + "bare-1.jar": ("com.bare", "bare", {"com/bare/B.class": cls(),
                                              "bare.properties": b"k=v"}),
    # same class as the WAR's inwar jar: the WAR's reference resolves to
    # its own copy, so this one is unused
    LIB + "mainw-1.jar": ("com.mw", "mainw", {"com/w/InWar.class": cls()}),
    # optional features: a tool, the timeline service and a test jar each
    # need their own library; "shared" is needed by core and a tool
    TOOLS + "hadoop-kafka-1.0.jar": ("org.apache.hadoop", "hadoop-kafka", {
        "org/apache/hadoop/kafka/K.class": cls("com/kc/Client", "com/sh/Shared",
                                               "com/z/D")}),
    TOOLS + "kclient-1.jar": ("com.kc", "kclient", {"com/kc/Client.class": cls()}),
    # a JDK service provider in tools/lib is on the tools' class path only
    TOOLS + "tdrv-1.jar": ("com.td", "tdrv", {
        "com/td/Drv.class": cls(), "META-INF/services/java.sql.Driver": b"com.td.Drv\n"}),
    LIB + "shared-1.jar": ("com.sh", "shared", {"com/sh/Shared.class": cls()}),
    TLS + "hadoop-yarn-server-timelineservice-1.0.jar": (
        "org.apache.hadoop", "hadoop-yarn-server-timelineservice", {
            "org/apache/hadoop/ts/T.class": cls("com/hb/HBase")}),
    TLS + "lib/hbase-1.jar": ("com.hb", "hbase", {"com/hb/HBase.class": cls()}),
    "h/share/hadoop/common/hadoop-common-1.0-tests.jar": (
        "org.apache.hadoop", "hadoop-common", {
            "org/apache/hadoop/T.class": cls("com/tl/TestLib")}),
    LIB + "testlib-1.jar": ("com.tl", "testlib", {"com/tl/TestLib.class": cls()}),
    # a service whose interface ships: used interface -> provider used
    LIB + "api-1.jar": ("com.a", "api", {"com/a/Api.class": cls()}),
    LIB + "mapi-1.jar": ("com.ma", "mapi", {"com/ma/Api.class": cls()}),
    LIB + "impl-1.jar": ("com.ai", "impl", {
        "com/ai/Impl.class": cls(), "META-INF/services/com.a.Api": b"com.ai.Impl\n"}),
}
WAR_JARS = {
    "WEB-INF/lib/inwar-1.jar": ("com.w", "inwar", {"com/w/InWar.class": cls()}),
    "WEB-INF/lib/warunused-1.jar": ("com.v", "warunused", {"com/v/V.class": cls()}),
    # a JDK service provider inside the WAR is loaded only when the WAR
    # is: it and what it uses belong to the WAR's feature, not to core
    "WEB-INF/lib/warsvc-1.jar": ("com.ws", "warsvc", {
        "com/ws/Drv.class": cls("com/wd/Dep"),
        "META-INF/services/java.sql.Driver": b"com.ws.Drv\n"}),
    "WEB-INF/lib/wardep-1.jar": ("com.wd", "wardep", {"com/wd/Dep.class": cls()}),
    # provider of an interface that ships on the main class path only (see
    # mapi): found only by the WAR's class loader, so it is the WAR's
    "WEB-INF/lib/used-1.jar": ("com.x", "used", {"com/x/Used.class": cls()}),
    "WEB-INF/lib/wprov-1.jar": ("com.wp", "wprov", {
        "com/wp/P.class": cls(), "META-INF/services/com.ma.Api": b"com.wp.P\n"}),
}


def build(d):
    root, rows = os.path.join(d, "untarred"), []
    for path, (g, a, entries) in JARS.items():
        write(root, path, zbytes(entries))
        rows.append("%s\t%s\t%s\t1\tpom.properties" % (path, g, a))
    war = {"WEB-INF/classes/W.class": cls("com/w/InWar", "com/x/Used")}
    for inner, (g, a, entries) in WAR_JARS.items():
        war[inner] = zbytes(entries)
        rows.append("%s#%s\t%s\t%s\t1\tpom.properties" % (WAR, inner, g, a))
    write(root, WAR, zbytes(war))
    write(root, "h/etc/hadoop/core-site.xml", b"<value>com.c.Cfg</value>")
    tsv = os.path.join(d, "archive-jars.tsv")
    open(tsv, "w").write("\n".join(rows) + "\n")
    keep = os.path.join(d, "keep")
    open(keep, "w").write("com.k:kept  # loaded by name\ncom.gone:gone  # stale\n")
    # a source tree for the pulled-in-by attribution: two module poms, one
    # declaring in <dependencyManagement> only
    src = os.path.join(d, "src")
    write(src, "hadoop-common-project/hadoop-common/pom.xml",
          b"<project><dependencies><dependency>"
          b"<groupId>com.x</groupId><artifactId>used</artifactId></dependency>"
          b"<dependency><groupId>com.sh</groupId><artifactId>shared</artifactId>"
          b"</dependency></dependencies></project>")
    write(src, "hadoop-assemblies/pom.xml",
          b"<project><dependencies><dependency>"
          b"<groupId>com.x</groupId><artifactId>used</artifactId>"
          b"</dependency></dependencies></project>")
    write(src, "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-app/pom.xml",
          b"<project><dependencyManagement><dependencies><dependency>"
          b"<groupId>com.kc</groupId><artifactId>kclient</artifactId>"
          b"</dependency></dependencies></dependencyManagement></project>")
    return root, tsv, keep, src


def main():
    with tempfile.TemporaryDirectory() as d:
        root, tsv, keep, src = build(d)
        maps = os.path.join(d, "maps")
        open(maps, "w").write("")
        p = subprocess.run([sys.executable, "-I", SCRIPT, root, tsv,
                            "--keep", keep, "--mappings", maps],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        out = p.stdout

        def section(title):
            body = out.split("## " + title, 1)[1].split("\n## ", 1)[0]
            return {l.split("\t")[0] for l in body.splitlines()[1:] if l}

        # never referenced: plain, metadata-only (native-image) and
        # compile-only service providers; inside a WAR too
        assert section("candidates") == {
            "com.y:unused:1", "com.m:meta:1", "com.p:proc:1",
            "com.v:warunused:1", "com.mw:mainw:1", "com.bare:bare:1"}, out
        # descriptor, string constant, JDK service, etc/ config and
        # WEB-INF/classes references all count as use
        cands = section("candidates")
        for used in ("com.x:used", "com.s:str", "com.z:svc", "com.c:cfg",
                     "com.w:inwar", "com.r:res", "com.r2:res2", "com.kc:kclient",
                     "com.hb:hbase", "com.tl:testlib", "com.sh:shared",
                     "com.ai:impl"):
            assert not any(c.startswith(used + ":") for c in cands), (used, out)
        # used only by optional features, named by feature; core-reached
        # jars (shared, used) are not listed
        opt = out.split("## used only by optional features", 1)[1].split("\n## ", 1)[0]
        rows = {l.split("\t")[0]: l.split("\t")[2] for l in opt.splitlines()
                if l.count("\t") == 2}
        assert "(9 jar files; 8 g:a that only these features need, " \
               "1 private copies of g:a core uses too)" in opt, opt
        assert rows.pop("com.x:used:1") == "app.war; copy: core uses this g:a too", out
        assert rows == {"com.w:inwar:1": "app.war",
                        "com.ws:warsvc:1": "app.war",
                        "com.wd:wardep:1": "app.war",
                        "com.wp:wprov:1": "app.war",
                        "com.kc:kclient:1": "tools:hadoop-kafka",
                        "com.td:tdrv:1": "tools/lib",
                        "com.hb:hbase:1": "yarn-timelineservice",
                        "com.tl:testlib:1": "tests"}, out
        assert section("no class files") == {"com.n:native:1"}, out
        assert section("keep-listed") == {"com.k:kept:1"}, out
        assert section("stale keep rows") == {"com.gone:gone"}, out
        # unreadable input fails closed
        p = subprocess.run([sys.executable, "-I", SCRIPT, d + "/missing", tsv,
                            "--keep", keep, "--mappings", maps],
                           capture_output=True, text=True)
        assert p.returncode == 2 and "cannot read" in p.stderr, p.stderr

        # the per-jar TSV: every third-party jar file, inbound counts,
        # verdicts and pom attribution
        tsv_out = os.path.join(d, "pruning-report.tsv")
        p = subprocess.run([sys.executable, "-I", SCRIPT, root, tsv,
                            "--keep", keep, "--mappings", maps,
                            "--poms", src, "-t", tsv_out],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        lines = open(tsv_out).read().splitlines()
        header = [l for l in lines if not l.startswith("#")]
        assert header[0] == ("g:a:v\tpath\tclasses\tinbound_hadoop\t"
                             "inbound_other\tverdict\tpulled_in_by"), header[0]
        data = {}
        for l in header[1:]:
            f = l.split("\t")
            data[f[1]] = f  # by path
        # 22 main third-party files + 6 WAR-nested = 28 rows
        assert len(data) == 28, len(data)
        def row(gav):
            hits = [f for f in data.values() if f[0] == gav]
            assert len(hits) == 1, (gav, hits)
            return hits[0]
        def row_path(suffix):
            hits = [f for f in data.values() if f[1].endswith(suffix)]
            assert len(hits) == 1, (suffix, hits)
            return hits[0]
        # duplicate copies: same bytes in another lib dir reference each
        # other, and that is not use — both stay zero-inbound candidates
        f = row_path("common/lib/unused-1.jar")
        assert f[0] == "com.y:unused:1" and f[2:] == [
            "1", "0", "0", "candidate", "transitive"], f
        f = row_path("hdfs/lib/unused-1.jar")
        assert f[0] == "com.y:unused:1" and f[2:] == [
            "1", "0", "0", "candidate", "transitive"], f
        # direct inbound from Hadoop's own jar; the WAR's reference to the
        # same class resolves to the WAR's own copy, not this one
        # two declaring modules, listed sorted
        f = row_path("common/lib/used-1.jar")
        assert f[0] == "com.x:used:1" and f[2:] == [
            "1", "1", "0", "used",
            "hadoop-assemblies;hadoop-common-project/hadoop-common"], f
        # the WAR's private copy of the same g:a: referenced by the WAR's
        # own classes (Hadoop's side), used only by the WAR feature;
        # attribution is per g:a, so it names the declaring module too
        f = row_path("app.war#WEB-INF/lib/used-1.jar")
        assert f[0] == "com.x:used:1" and f[2:] == [
            "1", "1", "0", "used-optional:app.war",
            "hadoop-assemblies;hadoop-common-project/hadoop-common"], f
        # service edge: the interface's jar (third-party) pulls the provider
        assert row("com.ai:impl:1")[2:] == [
            "1", "0", "1", "used", "transitive"], row("com.ai:impl:1")
        # a third-party jar referenced by another third-party jar
        assert row("com.wd:wardep:1")[2:] == [
            "1", "0", "1", "used-optional:app.war", "transitive"], \
            row("com.wd:wardep:1")
        # config-text references count as one inbound from Hadoop's side
        assert row("com.c:cfg:1")[2:] == [
            "1", "1", "0", "used", "transitive"], row("com.c:cfg:1")
        # a jar whose class references itself: the self-edge is not inbound
        assert row("com.z:svc:1")[2:] == [
            "1", "1", "0", "used", "transitive"], row("com.z:svc:1")
        # no class files / keep-listed verdicts
        assert row("com.n:native:1")[4] == "0" and row("com.n:native:1")[5] == \
            "no-class", row("com.n:native:1")
        assert row("com.k:kept:1")[5] == "kept", row("com.k:kept:1")
        # attribution from a dependencyManagement-only declaration; the
        # referencing jar (hadoop-kafka) is Hadoop's own
        assert row("com.kc:kclient:1")[2:] == [
            "1", "1", "0", "used-optional:tools:hadoop-kafka",
            "hadoop-yarn-project/hadoop-yarn/hadoop-yarn-app"], \
            row("com.kc:kclient:1")
        # a no-class jar with no declarer stays transitive (informational)
        assert row("com.n:native:1")[6] == "transitive"
        # a keep row for a reached jar is stale in the text report, so the
        # TSV says used, not kept
        keep2 = os.path.join(d, "keep2")
        open(keep2, "w").write("com.x:used  # reached anyway\n")
        p = subprocess.run([sys.executable, "-I", SCRIPT, root, tsv,
                            "--keep", keep2, "--mappings", maps,
                            "--tsv", tsv_out], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert "\tused\t-" in [l for l in open(tsv_out).read().splitlines()
                               if "common/lib/used-1.jar" in l][0]
        # --poms with no pom anywhere fails closed
        empty = os.path.join(d, "empty-src")
        os.makedirs(empty)
        p = subprocess.run([sys.executable, "-I", SCRIPT, root, tsv,
                            "--keep", keep, "--mappings", maps,
                            "--poms", empty, "-t", tsv_out],
                           capture_output=True, text=True)
        assert p.returncode == 2 and "no pom.xml" in p.stderr, p.stderr
    print("test-unused-jar-candidates: OK")


if __name__ == "__main__":
    main()
