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
"""Hermetic unit tests for the scanner internals.

    python selftest.py

These cover the constructs that actually broke while building the scanner
against Hadoop trunk: interface fields with no modifiers, names split across
lines, nested-interface scoping, ``substring``-derived keys, and concatenation
fragments.  The end-to-end check is ``scan.py oracle``, which validates the
extraction against Hadoop's own tests.
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hdfsconfscan import (  # noqa: E402
    assess, callsites, e2_literals, e3_xml, inventory, javalex, javamodel, pipeline,
)
from hdfsconfscan.semantics import is_partial_property, is_valid_property_name  # noqa: E402
from hdfsconfscan.symbols import UNRESOLVED, FileIndex, SymbolTable  # noqa: E402


def write(directory: str, name: str, body: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(body))
    return path


class TestLexer(unittest.TestCase):
    def test_views_have_equal_length_and_mask_correctly(self):
        source = 'class A { /* dfs.in.comment */ String k = "dfs.real"; // dfs.trailing\n}'
        lexed = javalex.lex(source)
        self.assertEqual(len(lexed.raw), len(lexed.code))
        self.assertEqual(len(lexed.raw), len(lexed.struct))
        self.assertNotIn("dfs.in.comment", lexed.code)
        self.assertNotIn("dfs.trailing", lexed.code)
        self.assertIn("dfs.real", lexed.code)
        # String contents are masked in the structural view only.
        self.assertNotIn("dfs.real", lexed.struct)

    def test_braces_inside_literals_do_not_affect_structure(self):
        source = 'class A { String s = "}{"; int x = 1; }'
        lexed = javalex.lex(source)
        self.assertEqual(lexed.struct.count("{"), 1)
        self.assertEqual(lexed.struct.count("}"), 1)

    def test_unescape(self):
        self.assertEqual(javalex.unescape_java_string(r'"a\tb"'), "a\tb")
        self.assertEqual(javalex.unescape_java_string(r'"A"'), "A")


class TestFieldParsing(unittest.TestCase):
    def test_interface_fields_are_implicitly_public_static_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "I.java", """
                package p;
                public interface I {
                  String KEY = "dfs.i.key";
                }
                """)
            jfile = javamodel.parse_file(path)
            decl = jfile.types["p.I"]
            self.assertTrue(decl.fields["KEY"].public_static_final)

    def test_nested_types_get_qualified_names_and_own_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "O.java", """
                package p;
                public interface O {
                  String PREFIX = "dfs.o.";
                  interface Inner {
                    String KEY = PREFIX + "inner";
                  }
                }
                """)
            jfile = javamodel.parse_file(path)
            self.assertIn("p.O.Inner", jfile.types)
            self.assertIn("KEY", jfile.types["p.O.Inner"].fields)
            # getDeclaredFields semantics: the outer type does not own KEY.
            self.assertNotIn("KEY", jfile.types["p.O"].fields)

    def test_each_field_gets_its_own_javadoc(self):
        # Anchoring on the raw statement start would give every field the
        # comment belonging to the field above it.
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "C.java", """
                package p;
                public class C {
                  /**
                   * Path to the whitelist file.
                   */
                  public static final String FILE = "dfs.x.file";
                  /**
                   * Seconds between refreshes of the whitelist file.
                   */
                  public static final String CACHE_SECS = "dfs.x.cache.secs";
                }
                """)
            fields = javamodel.parse_file(path).types["p.C"].fields
            self.assertIn("Path to the whitelist file", fields["FILE"].doc)
            self.assertIn("Seconds between refreshes", fields["CACHE_SECS"].doc)

    def test_deprecated_annotation_is_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "D.java", """
                package p;
                public class D {
                  @Deprecated
                  public static final String OLD = "dfs.old";
                }
                """)
            jfile = javamodel.parse_file(path)
            self.assertTrue(jfile.types["p.D"].fields["OLD"].deprecated)


class TestConstantFolding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self._tmp.name
        write(tmp, "A.java", """
            package p;
            public interface A {
              long MS_PER_SECOND = 1000L;
              String PREFIX = "dfs.a.";
              String KEY = PREFIX + "key";
              interface Read {
                String PREFIX = A.PREFIX + "read.";
                String KEY = PREFIX.substring(0, PREFIX.length() - 1);
              }
            }
            """)
        write(tmp, "B.java", """
            package p;
            import p.A;
            import java.util.concurrent.TimeUnit;
            public class B {
              public static final String SPLIT_NAME = A
                  .KEY;
              public static final String NESTED = A.Read.KEY;
              public static final long MINUTE = 60 * A.MS_PER_SECOND;
              public static final long BLOCK = 128 * 1024 * 1024;
              public static final long FIVE_MIN = TimeUnit.MINUTES.toMillis(5);
              public static final String CALLED = compute();
            }
            """)
        self.symtab = SymbolTable(FileIndex([tmp]))
        self.decl = self.symtab.load_class("p.B")

    def tearDown(self):
        self._tmp.cleanup()

    def value(self, name):
        return self.symtab.value_of_field(self.decl.fields[name])

    def test_name_split_across_lines(self):
        self.assertEqual(self.value("SPLIT_NAME"), "dfs.a.key")

    def test_nested_interface_and_substring(self):
        # PREFIX is "dfs.a.read." so KEY trims the trailing dot.
        self.assertEqual(self.value("NESTED"), "dfs.a.read")

    def test_numeric_expressions(self):
        self.assertEqual(self.value("MINUTE"), 60000)
        self.assertEqual(self.value("BLOCK"), 134217728)

    def test_time_unit_conversion(self):
        self.assertEqual(self.value("FIVE_MIN"), 300000)

    def test_method_call_is_unresolved_not_guessed(self):
        self.assertIs(self.value("CALLED"), UNRESOLVED)


class TestSemantics(unittest.TestCase):
    def test_valid_property_names(self):
        self.assertTrue(is_valid_property_name("dfs.namenode.rpc-address"))
        self.assertFalse(is_valid_property_name("nodots"))
        self.assertFalse(is_valid_property_name("1leading.digit"))

    def test_partial_properties(self):
        self.assertTrue(is_partial_property("dfs.client."))
        self.assertTrue(is_partial_property("hdfs-default.xml"))
        self.assertFalse(is_partial_property("dfs.client.foo"))


class TestLiteralScan(unittest.TestCase):
    def test_concatenation_fragments_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "C.java", """
                package p;
                public class C {
                  public static final String WHOLE = "dfs.whole.key";
                  public static final String PART =
                      "dfs.split.policy"
                          + ".suffix-part";
                  void f(Configuration conf) {
                    conf.getInt("dfs.accessor.key", 42);
                  }
                }
                """)
            records = e2_literals.scan_file(path, "test", "java")
            by_key = {r.key: r for r in records}
            self.assertFalse(by_key["dfs.whole.key"].concat_fragment)
            self.assertTrue(by_key["dfs.split.policy"].concat_fragment)
            self.assertEqual(by_key["dfs.accessor.key"].accessor, "getInt")
            self.assertEqual(by_key["dfs.accessor.key"].inline_default, "42")

    def test_comments_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "E.java", """
                package p;
                /** Mentions dfs.documented.only in javadoc. */
                public class E {
                  // and dfs.commented.out here
                  public static final String REAL = "dfs.real.key";
                }
                """)
            keys = {r.key for r in e2_literals.scan_file(path, "test", "java")}
            self.assertEqual(keys, {"dfs.real.key"})


class TestAccessorCoverage(unittest.TestCase):
    """The accessor list must keep up with Configuration's real API.

    E2's second tier only sees call sites whose method it recognises, so an
    accessor added upstream and not classified here would silently go
    unscanned.  This turns that into a test failure.
    """

    CONFIGURATION = os.path.join(
        "hadoop-common-project", "hadoop-common", "src", "main", "java",
        "org", "apache", "hadoop", "conf", "Configuration.java")

    def test_every_string_keyed_accessor_is_classified(self):
        import re
        repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        path = os.path.join(repo, self.CONFIGURATION)
        if not os.path.isfile(path):
            self.skipTest("Hadoop checkout not found; run from within a checkout")
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        api = set(m.group(1) for m in re.finditer(
            r"public\s+(?:synchronized\s+)?(?:<[^>]+>\s+)?[\w\[\]<>,.?\s]+?\s+"
            r"(get\w*|set\w*|unset)\s*\(\s*String\s+\w+", source))
        classified = set(e2_literals.ACCESSORS) | set(e2_literals.NON_PROPERTY_ACCESSORS)
        unclassified = sorted(api - classified)
        self.assertEqual(unclassified, [], "Configuration accessors are neither scanned "
                                          "nor explicitly excluded: " + ", ".join(unclassified))

    def test_no_phantom_accessors(self):
        import re
        repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        path = os.path.join(repo, self.CONFIGURATION)
        if not os.path.isfile(path):
            self.skipTest("Hadoop checkout not found; run from within a checkout")
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        declared = set(re.findall(r"\b(get\w*|set\w*|unset)\s*\(", source))
        phantom = sorted(a for a in e2_literals.ACCESSORS if a not in declared)
        self.assertEqual(phantom, [], "accessors that do not exist on Configuration: "
                                      + ", ".join(phantom))


class TestCallSites(unittest.TestCase):
    """Resolution of the key argument at configuration accessor call sites."""

    def _scan(self, body: str):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = self._tmp.name
        write(tmp, "Keys.java", """
            package p;
            public class Keys {
              public static final String PREFIX = "dfs.family.";
              public static final String PLAIN = "dfs.plain.key";
            }
            """)
        path = write(tmp, "User.java", body)
        symtab = SymbolTable(FileIndex([tmp]))
        return callsites.CallSiteScanner(symtab).scan_file(path, "test")

    def tearDown(self):
        if getattr(self, "_tmp", None):
            self._tmp.cleanup()

    def test_resolutions(self):
        sites = self._scan("""
            package p;
            import p.Keys;
            public class User {
              void go(Configuration conf, String nsId) {
                conf.getInt(Keys.PLAIN, 1);
                conf.get(Keys.PREFIX + nsId);
                conf.get(someRuntimeKey);
                conf.getPropsWithPrefix(Keys.PREFIX);
              }
            }
            """)
        by_res = {}
        for site in sites:
            by_res.setdefault(site.resolution, []).append(site)
        self.assertEqual([s.key for s in by_res["exact"]], ["dfs.plain.key"])
        self.assertEqual(sorted(s.pattern for s in by_res["pattern"]),
                         ["dfs.family.", "dfs.family."])
        self.assertEqual(len(by_res["dynamic"]), 1)
        self.assertNotIn("unresolved", by_res)

    def test_indirect_helper_read_is_found(self):
        sites = self._scan("""
            package p;
            import p.Keys;
            public class User {
              void go(Configuration conf) {
                long v = getUnitTestLong(conf, Keys.PLAIN, 5L);
              }
            }
            """)
        keys = [s.key for s in sites if s.key]
        self.assertIn("dfs.plain.key", keys,
                      "helper(conf, KEY, default) reads must be detected")

    def test_static_helper_named_like_an_accessor_is_found(self):
        # DFSUtil.getPassword(conf, KEY) is skipped by the direct scan (DFSUtil
        # is not a Configuration) and must not be skipped here just because
        # "getPassword" is also an accessor name.
        sites = self._scan("""
            package p;
            import p.Keys;
            public class User {
              void go(Configuration conf) {
                String pw = DFSUtil.getPassword(conf, Keys.PLAIN);
              }
            }
            """)
        self.assertIn("dfs.plain.key", [s.key for s in sites if s.key])

    def test_resource_filenames_are_not_properties(self):
        sites = self._scan("""
            package p;
            public class User {
              void go(Configuration conf) {
                conf.get("hdfs-site.xml");
              }
            }
            """)
        self.assertEqual([s.key for s in sites if s.key], [])
        self.assertEqual([s.resolution for s in sites], ["not-a-property"])

    def test_write_sites_are_distinguished(self):
        sites = self._scan("""
            package p;
            import p.Keys;
            public class User {
              void go(Configuration conf) {
                conf.setInt(Keys.PLAIN, 3);
              }
            }
            """)
        site = next(s for s in sites if s.key == "dfs.plain.key")
        self.assertTrue(site.is_write)
        self.assertFalse(site.is_read)


class TestClassification(unittest.TestCase):
    """The classifier must prefer author intent over raw usage counts."""

    def _entry(self, **kwargs):
        entry = inventory.Entry(key=kwargs.pop("key", "dfs.some.key"))
        for name, value in kwargs.items():
            setattr(entry, name, value)
        return entry

    def _classify(self, entry, skipped=(), deprecated=None, deprecated_constants=()):
        return inventory._classify(entry, entry.key, set(skipped),
                                   deprecated or {}, set(deprecated_constants))

    def test_visible_for_testing_beats_production_read(self):
        entry = self._entry(read_main=1, internal_marker="@VisibleForTesting")
        self.assertEqual(self._classify(entry), inventory.INTERNAL_PRIVATE)

    def test_package_private_is_internal(self):
        entry = self._entry(read_main=1, visibility="package-private")
        self.assertEqual(self._classify(entry), inventory.INTERNAL_PRIVATE)

    def test_public_undocumented_read_is_a_candidate(self):
        entry = self._entry(read_main=1, visibility="public")
        self.assertEqual(self._classify(entry), inventory.ACTIVE_UNDOCUMENTED)

    def test_test_only_writes_do_not_mask_a_production_read(self):
        entry = self._entry(read_main=1, write_test=5, visibility="public")
        self.assertEqual(self._classify(entry), inventory.ACTIVE_UNDOCUMENTED)

    def test_declaration_literal_alone_is_not_production_usage(self):
        entry = self._entry(literal_sites=1, write_test=2, visibility="public")
        self.assertEqual(self._classify(entry), inventory.TEST_ONLY)

    def test_private_comment_marks_internal(self):
        entry = self._entry(read_main=1, visibility="public",
                            declaring_comment="The following are private configurations")
        self.assertEqual(self._classify(entry), inventory.INTERNAL_PRIVATE)

    def test_deprecated_alias_wins(self):
        entry = self._entry(read_main=1, visibility="public")
        self.assertEqual(self._classify(entry, deprecated={entry.key: ["new.key"]}),
                         inventory.DEPRECATED_ALIAS)


class TestDescriptionSourcing(unittest.TestCase):
    """Descriptions must be derived from evidence, or left as TODO."""

    def _guide(self, body: str, key: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "Guide.md", body)
            return assess._from_guide(tmp, "Guide.md:2", key)

    def test_table_row_description_is_used(self):
        text = self._guide(
            "| Property | Description |\n"
            "| `nfs.superuser` | The user allowed to access any file on HDFS. |\n",
            "nfs.superuser")
        self.assertEqual(text, "The user allowed to access any file on HDFS.")

    def test_xml_example_is_rejected(self):
        # A guide showing <name>key</name> is an example, not a description.
        text = self._guide("intro\n  <name>nfs.superuser</name>\n", "nfs.superuser")
        self.assertEqual(text, "")

    def test_prose_mentioning_the_key_is_rejected(self):
        text = self._guide("intro\nSet nfs.superuser if you need this behaviour.\n",
                           "nfs.superuser")
        self.assertEqual(text, "")

    def test_markdown_emphasis_is_unwrapped_not_dropped(self):
        self.assertEqual(assess._clean("*Note this matters* here"),
                         "Note this matters here.")

    def test_foreign_namespace_is_not_ours_to_document(self):
        entry = inventory.Entry(key="mapreduce.task.attempt.id", read_main=1,
                                visibility="public")
        status = inventory._classify(entry, entry.key, set(), {}, set())
        self.assertEqual(status, inventory.EXTERNAL)


class TestPipelineEdits(unittest.TestCase):
    """The runner's source edits, which must be exact or the build breaks."""

    TEST_SRC = textwrap.dedent("""
        package p;

        import org.apache.hadoop.conf.TestConfigurationFieldsBase;
        import org.apache.hadoop.hdfs.DFSConfigKeys;

        public class TestHdfsConfigFields extends TestConfigurationFieldsBase {
          public void initializeMemberVariables() {
            xmlFilename = "hdfs-default.xml";
            configurationClasses = new Class[] { DFSConfigKeys.class};
          }
        }
        """)

    def test_classes_are_added_with_imports(self):
        out = pipeline._add_classes_to_test(
            self.TEST_SRC, ["org.apache.hadoop.hdfs.protocol.datatransfer.Whitelist"])
        self.assertIn("import org.apache.hadoop.hdfs.protocol.datatransfer.Whitelist;", out)
        self.assertIn("Whitelist.class", out)
        self.assertIn("DFSConfigKeys.class", out)   # existing entry survives

    def test_adding_twice_is_idempotent(self):
        once = pipeline._add_classes_to_test(self.TEST_SRC, ["p.Foo"])
        twice = pipeline._add_classes_to_test(once, ["p.Foo"])
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("Foo.class"), 1)

    def test_property_is_inserted_after_its_anchor(self):
        xml = ("<configuration>\n<property>\n  <name>a.b</name>\n  <value>1</value>\n"
               "</property>\n<property>\n  <name>c.d</name>\n</property>\n</configuration>")
        out = pipeline._insert_property(xml, "a.b", "<property>\n  <name>new.key</name>\n"
                                                    "</property>")
        self.assertLess(out.index("new.key"), out.index("c.d"))
        self.assertGreater(out.index("new.key"), out.index("a.b"))

    def test_missing_anchor_raises_rather_than_appending_blindly(self):
        with self.assertRaises(ValueError):
            pipeline._insert_property("<configuration></configuration>", "nope", "<property/>")


class TestXmlExtraction(unittest.TestCase):
    def test_duplicates_and_empty_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "x-default.xml", """
                <?xml version="1.0"?>
                <configuration>
                  <property><name>a.b</name><value>1</value></property>
                  <property><name>a.b</name><value>2</value></property>
                  <property><name>c.d</name><value></value></property>
                  <property><name>e.f</name></property>
                </configuration>
                """.lstrip())
            extract = e3_xml.extract(path)
            self.assertEqual(extract.duplicates, ["a.b"])
            self.assertEqual(len(extract.properties), 4)
            by_name = extract.by_name()
            # Last definition wins, as Configuration does.
            self.assertEqual(by_name["a.b"].value, "2")
            self.assertTrue(by_name["c.d"].empty_value)
            self.assertFalse(by_name["e.f"].has_value_tag)

    def test_line_numbers_survive_comments_and_wrapped_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "y-default.xml", """
                <?xml version="1.0"?>
                <configuration>
                  <!--
                    Example only:
                    <property><name>commented.out</name><value>x</value></property>
                  -->
                  <property>
                    <name>
                      wrapped.name
                    </name>
                    <value>1</value>
                  </property>
                  <property><name>after.comment</name><value>2</value></property>
                </configuration>
                """.lstrip())
            extract = e3_xml.extract(path)
            self.assertEqual([p.name for p in extract.properties],
                             ["wrapped.name", "after.comment"])
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
            for prop in extract.properties:
                self.assertIn(prop.name, lines[prop.line - 1],
                              f"{prop.name} not on recorded line {prop.line}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
