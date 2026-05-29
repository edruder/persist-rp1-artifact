import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)

import project  # noqa: E402


class TestSplitFrontmatter(unittest.TestCase):
    def test_rich_block(self):
        fm, body = project.split_frontmatter(
            "---\nproducer: bug-investigator\nrp1_doc_id: abc\n---\n# Title\n\nbody\n"
        )
        self.assertEqual(fm["producer"], "bug-investigator")
        self.assertEqual(fm["rp1_doc_id"], "abc")
        self.assertEqual(body, "# Title\n\nbody\n")

    def test_no_block(self):
        fm, body = project.split_frontmatter("# Just a heading\n\ntext\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# Just a heading\n\ntext\n")

    def test_quoted_and_indented_continuation_ignored(self):
        # A multi-line quoted value whose continuation contains a colon must not
        # create a bogus key, and surrounding quotes are stripped.
        text = (
            "---\n"
            'description: "Root cause of the Check failed: marking_done_ crash\n'
            "  spanning two lines."
            '"\n'
            "producer: bug-investigator\n"
            "---\n"
            "body\n"
        )
        fm, _ = project.split_frontmatter(text)
        self.assertEqual(fm["producer"], "bug-investigator")
        self.assertNotIn("Check failed", fm)  # continuation line not parsed as a key
        self.assertTrue(fm["description"].startswith("Root cause"))


class TestTitle(unittest.TestCase):
    def test_artifact_field_with_issue(self):
        fm = {"artifact": "investigation-report", "issue_id": "node-20-upgrade"}
        self.assertEqual(
            project.derive_title(fm, "# Anything\n", "/x/y.md"),
            "Investigation Report — node-20-upgrade",
        )

    def test_artifact_field_no_issue(self):
        self.assertEqual(
            project.derive_title({"artifact": "code-audit"}, "# H\n", "/x/y.md"),
            "Code Audit",
        )

    def test_h1_fallback(self):
        fm = {"producer": "bug-investigator"}  # no artifact field
        body = "# Follow-up: fix the thing\n\nbody\n"
        self.assertEqual(project.derive_title(fm, body, "/x/y.md"), "Follow-up: fix the thing")

    def test_producer_fallback(self):
        self.assertEqual(
            project.derive_title({"producer": "bug-investigator"}, "no heading\n", "/x/y.md"),
            "Bug Investigator",
        )

    def test_filename_fallback(self):
        self.assertEqual(
            project.derive_title({}, "no heading here\n", "/a/b/opencv_notes.md"),
            "Opencv Notes",
        )


class TestStripH1(unittest.TestCase):
    def test_strips_leading_h1_line_only(self):
        self.assertEqual(
            project.strip_leading_h1("\n# Title\n\n## Section\n\nx\n"),
            "## Section\n\nx\n",
        )

    def test_no_h1_unchanged(self):
        self.assertEqual(project.strip_leading_h1("## Section\n\nx\n"), "## Section\n\nx\n")


if __name__ == "__main__":
    unittest.main()
