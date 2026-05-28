# persist-rp1-artifact Generality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `persist-rp1-artifact` work on any markdown under `.rp1/work/` (frontmatter fully optional), targeting a PR *or* an issue by number or URL, while keeping the rich-shape #564 comment byte-identical.

**Architecture:** Extract the prose-only projection logic into one pure, network-free Python script (`scripts/project.py`) that emits the comment body to stdout; make the `examples/*` fixtures byte-exact golden tests against it (`tests/test_project.py`, stdlib `unittest`). A second pure helper (`scripts/parse_target.py`) parses a PR/issue number-or-URL. `SKILL.md` becomes thin orchestration: `gh` preflight, target resolution, call the scripts, find/post/patch the comment.

**Tech Stack:** Python 3 stdlib only (no PyYAML, no pytest), `gh` CLI, bash. macOS/Linux.

**Spec:** `docs/superpowers/specs/2026-05-28-persist-rp1-artifact-generality-design.md`

---

## File Structure

```
skills/persist-rp1-artifact/
  scripts/
    project.py          # NEW — pure projection: (artifact path, source path) -> comment body on stdout
    parse_target.py     # NEW — pure: target string + current "owner/repo" -> JSON {owner,repo,number,kind}
  tests/
    test_project.py     # NEW — unit tests + byte-exact golden tests vs examples/*-output.md
    test_parse_target.py# NEW — unit tests for target parsing
  examples/
    investigation-report-{input,output}.md   # unchanged (regression anchor)
    incomplete-status-{input,output}.md       # unchanged (banner)
    no-summary-{input,output}.md              # unchanged (first-H2 fallback)
    no-doc-id-{input,output}.md               # REPURPOSED: was "proves refusal", now path: marker
    routing-only-{input,output}.md            # NEW — opencv shape (routing fields, no doc_id/artifact)
    no-frontmatter-{input,output}.md          # NEW — no frontmatter block at all
    lead-split-{input,output}.md              # NEW — no-H2 ladder (rung 5) + single-block (rung 6)
  references/
    artifact-frontmatter.md   # rewritten: real schema, all fields optional
    projection-format.md      # rewritten: skip-absent rows, key precedence, ladder
    edge-cases.md             # updated: issue targets, path-key orphan note
  SKILL.md                    # rewritten procedure (target resolution; calls scripts)
README.md                     # usage line + "what counts as an artifact"
```

`project.py` is the only place projection logic lives (kills the SKILL.md ↔ artifact-frontmatter.md duplication). It takes an explicit `--source-path` so output is deterministic regardless of CWD/repo — the golden tests pass `examples/<name>-input.md` to reproduce the existing fixtures exactly.

**Public API of `project.py` (used by tests):**
```python
project(artifact_path: str, source_path: str) -> tuple[str, list[str]]
# returns (comment_body, warnings). Pure: no network, no exit. Body always ends in one "\n".
```

---

## Task 1: Scaffold script + optional frontmatter parsing

**Files:**
- Create: `skills/persist-rp1-artifact/scripts/project.py`
- Create: `skills/persist-rp1-artifact/tests/test_project.py`

- [ ] **Step 1: Create the test file with failing frontmatter tests**

`skills/persist-rp1-artifact/tests/test_project.py`:
```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests; verify import failure**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests` (from repo root)
Expected: FAIL — `ModuleNotFoundError: No module named 'project'` (the script doesn't exist yet).

- [ ] **Step 3: Create `project.py` with the parser**

`skills/persist-rp1-artifact/scripts/project.py`:
```python
#!/usr/bin/env python3
"""Project an rp1 artifact into a deterministic PR/issue comment body.

Pure and network-free: given an artifact file and the repo-relative source path
to display, emit the exact comment body on stdout. Warnings go to stderr.
This module never calls GitHub and never modifies the artifact.
"""
import argparse
import os
import re
import sys

MAX_BYTES = 65536

# A frontmatter key line: starts at column 0, identifier-ish key, then ": ".
# Indented continuation lines (multi-line quoted values) never match, so a colon
# inside a wrapped value cannot create a bogus key.
_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s?(.*)$")


def split_frontmatter(text):
    """Return (fm_dict, body). The frontmatter block is OPTIONAL.

    If the text does not open with a '---' block, fm is {} and body is the whole
    text. Values keep their first-line content; surrounding quotes are stripped.
    """
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        km = _KEY_RE.match(line)
        if not km:
            continue
        key, val = km.group(1).strip(), km.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        fm[key] = val
    return fm, m.group(2)
```

- [ ] **Step 4: Run tests; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/persist-rp1-artifact/scripts/project.py skills/persist-rp1-artifact/tests/test_project.py
git commit -m "feat: project.py with optional frontmatter parsing

Co-authored by Claude Code"
```

---

## Task 2: Title derivation + leading-H1 strip

**Files:**
- Modify: `skills/persist-rp1-artifact/scripts/project.py`
- Modify: `skills/persist-rp1-artifact/tests/test_project.py`

- [ ] **Step 1: Add failing tests**

Append to `test_project.py` (before the `if __name__` line):
```python
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
```

- [ ] **Step 2: Run; verify fail**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: FAIL — `AttributeError: module 'project' has no attribute 'derive_title'`.

- [ ] **Step 3: Implement**

Append to `project.py`:
```python
def _title_case(slug):
    words = slug.replace("_", "-").split("-")
    return " ".join(w.capitalize() for w in words if w)


def _first_h1(body):
    m = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return m.group(1) if m else None


def derive_title(fm, body, artifact_path):
    """Title precedence: artifact field -> first H1 -> producer -> filename stem."""
    art = fm.get("artifact", "").strip()
    if art:
        title = _title_case(art)
        issue = fm.get("issue_id", "").strip()
        return f"{title} — {issue}" if issue else title  # em-dash U+2014
    h1 = _first_h1(body)
    if h1:
        return h1
    prod = fm.get("producer", "").strip()
    if prod:
        return _title_case(prod)
    stem = os.path.splitext(os.path.basename(artifact_path))[0]
    return _title_case(stem)


def strip_leading_h1(body):
    """Drop a single leading '# ...' line (and the blank lines around it)."""
    b = body.lstrip("\n")
    if b.startswith("# "):
        nl = b.find("\n")
        b = b[nl + 1:] if nl != -1 else ""
    return b.lstrip("\n")
```

- [ ] **Step 4: Run; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/persist-rp1-artifact/scripts/project.py skills/persist-rp1-artifact/tests/test_project.py
git commit -m "feat: title derivation + leading-H1 strip

Co-authored by Claude Code"
```

---

## Task 3: Summary extraction ladder (6 rungs)

**Files:**
- Modify: `skills/persist-rp1-artifact/scripts/project.py`
- Modify: `skills/persist-rp1-artifact/tests/test_project.py`

The ladder operates on the H1-stripped body and returns `((summary_body, rest_body), warning_or_None)`. Both bodies end in exactly one `\n` (or `rest_body == ""`).

- [ ] **Step 1: Add failing tests**

Append to `test_project.py`:
```python
class TestSummaryLadder(unittest.TestCase):
    def _run(self, body):
        return project.extract_summary(body)

    def test_rung1_named_summary(self):
        body = "## Executive Summary\n\nlead\n\n## Details\n\nmore\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "lead\n")
        self.assertEqual(rest, "## Details\n\nmore\n")
        self.assertIsNone(warn)

    def test_rung1_numbered_named_summary(self):
        body = "## 1. Executive Summary\n\nlead\n\n## 2. Details\n\nmore\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "lead\n")
        self.assertEqual(rest, "## 2. Details\n\nmore\n")

    def test_rung2_first_h2(self):
        body = "## Background\n\nb\n\n## Other\n\no\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "b\n")
        self.assertEqual(rest, "## Other\n\no\n")
        self.assertIn("falling back to first H2", warn)

    def test_rung3_subheading(self):
        body = "intro text\n\n### Sub\n\ndetail\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "intro text\n")
        self.assertEqual(rest, "### Sub\n\ndetail\n")
        self.assertIn("rung 3", warn)

    def test_rung4_thematic_break(self):
        body = "lead para\n\n---\n\nafter break\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "lead para\n")
        self.assertEqual(rest, "---\n\nafter break\n")
        self.assertIn("rung 4", warn)

    def test_rung5_paragraph(self):
        body = "first paragraph\n\nsecond paragraph\n\nthird\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "first paragraph\n")
        self.assertEqual(rest, "second paragraph\n\nthird\n")
        self.assertIn("rung 5", warn)

    def test_rung6_single_block(self):
        body = "just one block of text\nwith no blank line\n"
        (summ, rest), warn = self._run(body)
        self.assertEqual(summ, "just one block of text\nwith no blank line\n")
        self.assertEqual(rest, "")
        self.assertIn("rung 6", warn)
```

- [ ] **Step 2: Run; verify fail**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: FAIL — `extract_summary` missing.

- [ ] **Step 3: Implement**

Append to `project.py`:
```python
SUMMARY_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _norm(s):
    """Normalize a slice to: stripped of edge blank lines, ending in one newline."""
    s = s.lstrip("\n").rstrip()
    return s + "\n" if s else ""


def _section_after(body, heading_match):
    """Section shape: content after a heading line up to the next '## '."""
    start = heading_match.end() + 1  # skip the newline after the heading line
    nxt = re.search(r"^## ", body[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(body)
    summary = _norm(body[start:end])
    rest = _norm(body[end:]) if end < len(body) else ""
    return summary, rest


def _lead_split(body, idx):
    """Lead shape: content before idx is the summary, idx onward is the rest."""
    summary = _norm(body[:idx])
    rest = _norm(body[idx:])
    return summary, rest


def extract_summary(body):
    """Deterministic 6-rung ladder. Returns ((summary, rest), warning_or_None)."""
    m = SUMMARY_RE.search(body)
    if m:  # rung 1
        return _section_after(body, m), None
    m = re.search(r"^## .*$", body, re.MULTILINE)
    if m:  # rung 2
        heading = m.group(0)[3:].strip()
        return _section_after(body, m), (
            f'WARNING: no Executive Summary section found; falling back to first H2 ("{heading}").'
        )
    m = re.search(r"^#{3,6}\s", body, re.MULTILINE)
    if m:  # rung 3
        return _lead_split(body, m.start()), "WARNING: no H2 found; splitting before first subheading (rung 3)."
    m = re.search(r"^(?:---|\*\*\*|___)\s*$", body, re.MULTILINE)
    if m:  # rung 4
        return _lead_split(body, m.start()), "WARNING: no headings found; splitting at first thematic break (rung 4)."
    m = re.search(r"\n[ \t]*\n", body)
    if m:  # rung 5 — split at the first blank line
        return _lead_split(body, m.start() + 1), "WARNING: no structure found; using lead paragraph as summary (rung 5)."
    # rung 6 — single block
    return (_norm(body), ""), "WARNING: single-block body; posting whole body as summary (rung 6)."
```

- [ ] **Step 4: Run; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS. (If `test_rung5_paragraph` rest/summary boundary is off by a newline, the failure message shows the exact strings — adjust `m.start() + 1` accordingly and re-run.)

- [ ] **Step 5: Commit**

```bash
git add -A skills/persist-rp1-artifact
git commit -m "feat: deterministic 6-rung summary extraction ladder

Co-authored by Claude Code"
```

---

## Task 4: Header table (skip absent), banner, marker key

**Files:**
- Modify: `skills/persist-rp1-artifact/scripts/project.py`
- Modify: `skills/persist-rp1-artifact/tests/test_project.py`

- [ ] **Step 1: Add failing tests**

Append to `test_project.py`:
```python
class TestTableBannerKey(unittest.TestCase):
    def test_table_full(self):
        fm = {
            "producer": "bug-investigator", "artifact": "investigation-report",
            "issue_id": "node-20-upgrade", "status": "complete", "date": "2026-05-12",
            "rp1_doc_id": "9f27673c",
        }
        rows = project.build_table_rows(fm, "examples/x-input.md")
        self.assertEqual(rows[0], "| Field | Value |")
        self.assertEqual(rows[1], "|-------|-------|")
        self.assertIn("| Producer | `bug-investigator` |", rows)
        self.assertIn("| Artifact type | `investigation-report` |", rows)
        self.assertIn("| Doc ID | `9f27673c` |", rows)
        self.assertIn("| Source path | `examples/x-input.md` (gitignored, local to author) |", rows)
        self.assertEqual(len(rows), 9)  # header + sep + 7 data rows

    def test_table_routing_only_skips_absent(self):
        fm = {"producer": "bug-investigator", "type": "document"}
        rows = project.build_table_rows(fm, "examples/r-input.md")
        self.assertIn("| Producer | `bug-investigator` |", rows)
        self.assertIn("| Artifact type | `document` |", rows)  # falls back to `type`
        self.assertNotIn("Issue ID", "\n".join(rows))
        self.assertNotIn("Status", "\n".join(rows))
        self.assertNotIn("Doc ID", "\n".join(rows))
        # header + sep + producer + artifact-type + source path
        self.assertEqual(len(rows), 5)

    def test_table_no_frontmatter_only_source(self):
        rows = project.build_table_rows({}, "examples/n-input.md")
        self.assertEqual(len(rows), 3)  # header + sep + source path only

    def test_banner_incomplete(self):
        self.assertEqual(
            project.build_banner({"status": "incomplete"}),
            "> ⚠️ **This artifact is marked `incomplete`.** Reviewers: the analysis below may evolve.",
        )

    def test_banner_absent(self):
        self.assertIsNone(project.build_banner({"status": "complete"}))
        self.assertIsNone(project.build_banner({}))

    def test_key_prefers_doc_id(self):
        self.assertEqual(project.marker_key({"rp1_doc_id": "abc"}, "examples/x.md"), "abc")

    def test_key_falls_back_to_path(self):
        self.assertEqual(project.marker_key({}, "examples/x.md"), "path:examples/x.md")
```

- [ ] **Step 2: Run; verify fail**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: FAIL — `build_table_rows` missing.

- [ ] **Step 3: Implement**

Append to `project.py`:
```python
BANNER = (
    "> ⚠️ **This artifact is marked `incomplete`.** "
    "Reviewers: the analysis below may evolve."
)


def build_table_rows(fm, source_path):
    """Header table rows, skipping any field that has no value. Source path always shown."""
    rows = ["| Field | Value |", "|-------|-------|"]
    producer = fm.get("producer", "").strip()
    atype = fm.get("artifact", "").strip() or fm.get("type", "").strip()
    issue = fm.get("issue_id", "").strip()
    status = fm.get("status", "").strip()
    date = fm.get("date", "").strip()
    doc = fm.get("rp1_doc_id", "").strip()
    if producer:
        rows.append(f"| Producer | `{producer}` |")
    if atype:
        rows.append(f"| Artifact type | `{atype}` |")
    if issue:
        rows.append(f"| Issue ID | `{issue}` |")
    if status:
        rows.append(f"| Status | `{status}` |")
    if date:
        rows.append(f"| Generated | {date} |")
    if doc:
        rows.append(f"| Doc ID | `{doc}` |")
    rows.append(f"| Source path | `{source_path}` (gitignored, local to author) |")
    return rows


def build_banner(fm):
    """Return the incomplete banner line, or None."""
    if fm.get("status", "").strip().lower() == "incomplete":
        return BANNER
    return None


def marker_key(fm, source_path):
    """Idempotency key: rp1_doc_id when present, else path:<source_path>."""
    doc = fm.get("rp1_doc_id", "").strip()
    return doc if doc else f"path:{source_path}"
```

- [ ] **Step 4: Run; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A skills/persist-rp1-artifact
git commit -m "feat: skip-absent header table, incomplete banner, marker key

Co-authored by Claude Code"
```

---

## Task 5: Assemble + size check + CLI

**Files:**
- Modify: `skills/persist-rp1-artifact/scripts/project.py`
- Modify: `skills/persist-rp1-artifact/tests/test_project.py`

The exact line layout was reverse-engineered from `investigation-report-output.md` (no banner, has rest) and `incomplete-status-output.md` (banner present, no rest). Both are reproduced byte-for-byte by `assemble()` below.

- [ ] **Step 1: Add failing tests**

Append to `test_project.py`:
```python
class TestAssembleAndProject(unittest.TestCase):
    def test_assemble_no_banner_with_rest(self):
        rows = ["| Field | Value |", "|-------|-------|", "| Producer | `p` |",
                "| Source path | `examples/x.md` (gitignored, local to author) |"]
        out = project.assemble("doc1", "Title", rows, None, "lead\n", "## Rest\n\nmore\n")
        self.assertTrue(out.startswith("<!-- rp1-artifact: doc1 -->\n## \U0001F4CB rp1 Artifact: Title\n\n"))
        self.assertIn("\n\n### Executive Summary\n\nlead\n\n<details>\n", out)
        self.assertIn("\n</details>\n\n---\n<sub>", out)
        self.assertTrue(out.endswith("</sub>\n"))

    def test_assemble_banner_no_rest(self):
        rows = ["| Field | Value |", "|-------|-------|",
                "| Source path | `examples/x.md` (gitignored, local to author) |"]
        out = project.assemble("doc1", "T", rows, project.BANNER, "only summary\n", "")
        self.assertIn(project.BANNER + "\n\n### Executive Summary\n", out)
        self.assertNotIn("<details>", out)

    def test_size_check(self):
        self.assertIsNone(project.check_size("x" * 10))
        msg = project.check_size("x" * (project.MAX_BYTES + 1))
        self.assertIn("exceeds GitHub's 65 KB cap", msg)


class TestGolden(unittest.TestCase):
    EX = os.path.join(HERE, "..", "examples")
    CASES = [
        ("investigation-report", "examples/investigation-report-input.md"),
        ("incomplete-status", "examples/incomplete-status-input.md"),
        ("no-summary", "examples/no-summary-input.md"),
    ]

    def test_golden(self):
        for name, source in self.CASES:
            with self.subTest(name=name):
                inp = os.path.join(self.EX, f"{name}-input.md")
                outp = os.path.join(self.EX, f"{name}-output.md")
                body, _ = project.project(inp, source)
                with open(outp, encoding="utf-8") as f:
                    expected = f.read()
                self.assertEqual(body, expected)
```

- [ ] **Step 2: Run; verify fail**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: FAIL — `assemble`/`project`/`check_size` missing.

- [ ] **Step 3: Implement**

Append to `project.py`:
```python
FOOTER_RULE = "---"
FOOTER_SUB = (
    "<sub>\U0001F916 Posted by `persist-rp1-artifact`. Re-run the skill to update "
    "this comment in place. Local artifact is gitignored and may be edited by "
    "`rp1` agents.</sub>"
)


def assemble(key, title, table_rows, banner, summary_body, rest_body):
    """Build the exact comment body. summary_body/rest_body end in one \\n (rest may be '')."""
    lines = [f"<!-- rp1-artifact: {key} -->", f"## \U0001F4CB rp1 Artifact: {title}", ""]
    lines += table_rows
    lines.append("")
    if banner:
        lines.append(banner)
        lines.append("")
    lines.append("### Executive Summary")
    lines.append("")
    lines += summary_body.rstrip("\n").split("\n")
    if rest_body:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary><strong>Full artifact</strong> (click to expand)</summary>")
        lines.append("")
        lines += rest_body.rstrip("\n").split("\n")
        lines.append("")
        lines.append("</details>")
    lines.append("")
    lines.append(FOOTER_RULE)
    lines.append(FOOTER_SUB)
    return "\n".join(lines) + "\n"


def check_size(body):
    """Return an error message if body exceeds GitHub's cap, else None."""
    n = len(body.encode("utf-8"))
    if n > MAX_BYTES:
        return f"Comment body exceeds GitHub's 65 KB cap ({n} bytes). Multi-comment chunking is not yet supported."
    return None


def project(artifact_path, source_path):
    """Pure projection. Returns (comment_body, warnings)."""
    with open(artifact_path, encoding="utf-8") as f:
        text = f.read()
    fm, body = split_frontmatter(text)
    title = derive_title(fm, body, artifact_path)
    body1 = strip_leading_h1(body)
    (summary_body, rest_body), warn = extract_summary(body1)
    warnings = [warn] if warn else []
    rows = build_table_rows(fm, source_path)
    banner = build_banner(fm)
    key = marker_key(fm, source_path)
    out = assemble(key, title, rows, banner, summary_body, rest_body)
    return out, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Project an rp1 artifact into a PR/issue comment body.")
    ap.add_argument("artifact_path")
    ap.add_argument("--source-path", required=True,
                    help="repo-relative path to display in the Source path row and path: key")
    args = ap.parse_args(argv)
    body, warnings = project(args.artifact_path, args.source_path)
    for w in warnings:
        print(w, file=sys.stderr)
    err = check_size(body)
    if err:
        print(err, file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run; verify pass (including golden)**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS, including `TestGolden.test_golden` — the three existing fixtures reproduce byte-identical. If a golden subTest fails, the assertion prints the exact differing strings; fix `assemble()` spacing or the ladder, do **not** edit the fixtures (they are the contract).

- [ ] **Step 5: Smoke-test the CLI**

Run: `python3 skills/persist-rp1-artifact/scripts/project.py skills/persist-rp1-artifact/examples/investigation-report-input.md --source-path examples/investigation-report-input.md | diff - skills/persist-rp1-artifact/examples/investigation-report-output.md`
Expected: no output (empty diff), exit 0.

- [ ] **Step 6: Commit**

```bash
git add -A skills/persist-rp1-artifact
git commit -m "feat: assemble + size check + CLI; existing fixtures pass byte-exact

Co-authored by Claude Code"
```

---

## Task 6: New + repurposed fixtures

Now that the regression anchors pass, add the leaner-shape fixtures. **Generate each output by running the CLI**, then eyeball it before committing — the CLI is now the source of truth, and these fixtures lock its behavior on the new shapes.

**Files:**
- Modify: `skills/persist-rp1-artifact/examples/no-doc-id-input.md` (rewrite body text)
- Create: `skills/persist-rp1-artifact/examples/no-doc-id-output.md`
- Create: `skills/persist-rp1-artifact/examples/routing-only-input.md` + `-output.md`
- Create: `skills/persist-rp1-artifact/examples/no-frontmatter-input.md` + `-output.md`
- Create: `skills/persist-rp1-artifact/examples/lead-split-input.md` + `-output.md`
- Modify: `skills/persist-rp1-artifact/tests/test_project.py` (extend golden CASES)

- [ ] **Step 1: Repurpose `no-doc-id-input.md`**

Replace its body so it no longer claims the skill refuses. New full file:
```markdown
---
producer: bug-investigator
artifact: investigation-report
issue_id: missing-doc-id-test
status: complete
date: 2026-05-19
---

# Test Artifact

## Executive Summary

This artifact has rich fields but no `rp1_doc_id`, so the comment is keyed off the
repo-relative path instead. The skill still publishes it.

## Details

Body content that lands in the collapsible section.
```

- [ ] **Step 2: Create `routing-only-input.md`** (models the opencv failer: routing fields only, no doc_id, no artifact)
```markdown
---
scope: workRoot
path_pattern: issues/node-20-upgrade/opencv4nodejs-customallocator-investigation.md
producer: bug-investigator
type: document
description: "Follow-up investigation target for the Node 20 V8 marking_done_
  crash. This document scopes the structural fix."
strictness: flexible
---

# Follow-up: address `@u4/opencv4nodejs`'s `CustomMatAllocator` re-entrant GC trigger

## Executive Summary

Step 0 attributed the re-entrant GC to a `CustomMatAllocator` calling
`AdjustAmountOfExternalAllocatedMemory` from a Nan callback. This scopes the fix.

## Proposed Fix

Detail that lands in the collapsible section.
```

- [ ] **Step 3: Create `no-frontmatter-input.md`** (no frontmatter block at all)
```markdown
# Anvil Code Quality Audit Report

## Executive Summary

The codebase is broadly healthy with a few hotspots noted below.

## Findings

Detail that lands in the collapsible section.
```

- [ ] **Step 4: Create `lead-split-input.md`** (no H2 anywhere → ladder rung 5, then rung 6)
```markdown
# Quick Handoff Note

This is the lead paragraph that should become the visible summary.

This second paragraph and everything after it belongs in the collapsible body.
```

- [ ] **Step 5: Generate the four output fixtures from the CLI**

```bash
cd skills/persist-rp1-artifact
for n in no-doc-id routing-only no-frontmatter lead-split; do
  python3 scripts/project.py "examples/$n-input.md" --source-path "examples/$n-input.md" > "examples/$n-output.md"
done
cd -
```
Then **read each generated `-output.md`** and confirm: marker is `path:examples/<n>-input.md` for routing-only/no-frontmatter/no-doc-id (no `rp1_doc_id` in those); title is the H1 for routing-only/no-frontmatter/lead-split and "Investigation Report — missing-doc-id-test" for no-doc-id; absent rows are skipped; lead-split's summary is the first paragraph with the rest collapsed.

- [ ] **Step 6: Extend the golden test**

In `test_project.py`, extend `TestGolden.CASES`:
```python
    CASES = [
        ("investigation-report", "examples/investigation-report-input.md"),
        ("incomplete-status", "examples/incomplete-status-input.md"),
        ("no-summary", "examples/no-summary-input.md"),
        ("no-doc-id", "examples/no-doc-id-input.md"),
        ("routing-only", "examples/routing-only-input.md"),
        ("no-frontmatter", "examples/no-frontmatter-input.md"),
        ("lead-split", "examples/lead-split-input.md"),
    ]
```

- [ ] **Step 7: Run; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS (7 golden subtests).

- [ ] **Step 8: Commit**

```bash
git add -A skills/persist-rp1-artifact
git commit -m "test: fixtures for routing-only, no-frontmatter, lead-split, no-doc-id shapes

Co-authored by Claude Code"
```

---

## Task 7: `parse_target.py` — PR/issue, number or URL

**Files:**
- Create: `skills/persist-rp1-artifact/scripts/parse_target.py`
- Create: `skills/persist-rp1-artifact/tests/test_parse_target.py`

Pure parsing only. The network-dependent step (probing whether a bare number is a PR or an issue) stays in `SKILL.md`; this script resolves what it can from the string alone and reports `kind: "unknown"` for a bare number.

- [ ] **Step 1: Failing tests**

`skills/persist-rp1-artifact/tests/test_parse_target.py`:
```python
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import parse_target  # noqa: E402


class TestParseTarget(unittest.TestCase):
    def test_pr_url(self):
        r = parse_target.parse("https://github.com/anvilco/pdf-service/pull/564", "x/y")
        self.assertEqual(r, {"owner": "anvilco", "repo": "pdf-service", "number": 564, "kind": "pr"})

    def test_issue_url(self):
        r = parse_target.parse("https://github.com/anvilco/pdf-service/issues/576", "x/y")
        self.assertEqual(r, {"owner": "anvilco", "repo": "pdf-service", "number": 576, "kind": "issue"})

    def test_bare_number_uses_current_repo_kind_unknown(self):
        r = parse_target.parse("573", "anvilco/pdf-service")
        self.assertEqual(r, {"owner": "anvilco", "repo": "pdf-service", "number": 573, "kind": "unknown"})

    def test_url_with_trailing_segment(self):
        r = parse_target.parse("https://github.com/o/r/pull/12/files", "x/y")
        self.assertEqual(r["number"], 12)
        self.assertEqual(r["kind"], "pr")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_target.parse("not-a-target", "x/y")

    def test_empty_current_repo_for_bare_number_raises(self):
        with self.assertRaises(ValueError):
            parse_target.parse("573", "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; verify fail**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: FAIL — no module `parse_target`.

- [ ] **Step 3: Implement**

`skills/persist-rp1-artifact/scripts/parse_target.py`:
```python
#!/usr/bin/env python3
"""Parse a PR/issue target (bare number or GitHub URL) into structured fields.

Pure: no network. A bare number yields kind="unknown" — the caller probes
whether it is a PR or an issue. A URL yields kind from its /pull/ or /issues/ path.
"""
import argparse
import json
import re
import sys

_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<kind>pull|issues)/(?P<number>\d+)"
)


def parse(target, current_repo):
    """Return {owner, repo, number:int, kind:'pr'|'issue'|'unknown'}.

    current_repo is "owner/repo" for bare-number targets. Raises ValueError on
    unrecognizable input or a bare number with no current_repo.
    """
    m = _URL_RE.match(target.strip())
    if m:
        return {
            "owner": m.group("owner"),
            "repo": m.group("repo"),
            "number": int(m.group("number")),
            "kind": "pr" if m.group("kind") == "pull" else "issue",
        }
    if re.fullmatch(r"\d+", target.strip()):
        if "/" not in current_repo:
            raise ValueError("bare number requires a current repo (owner/repo)")
        owner, repo = current_repo.split("/", 1)
        return {"owner": owner, "repo": repo, "number": int(target), "kind": "unknown"}
    raise ValueError(f"Target must be a PR/issue number or a GitHub URL: {target!r}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--current-repo", default="", help='"owner/repo" for bare-number targets')
    args = ap.parse_args(argv)
    try:
        print(json.dumps(parse(args.target, args.current_repo)))
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run; verify pass**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A skills/persist-rp1-artifact
git commit -m "feat: parse_target.py for PR/issue number-or-URL targets

Co-authored by Claude Code"
```

---

## Task 8: Rewrite the `SKILL.md` procedure

**Files:**
- Modify: `skills/persist-rp1-artifact/SKILL.md`

This is prose the main agent follows; verification is a real dry-run (Task 11), not a unit test. Replace these regions precisely.

- [ ] **Step 1: Update the Inputs table**

Replace the `| `[pr-number]` |` row and the surrounding table so the second positional is `[target]`:
```markdown
| Arg | Required | Default |
|---|---|---|
| `<path>` | yes | — |
| `[target]` | no | current branch's open PR (`gh pr view --json number -q .number`). May be a PR or issue **number**, or a full GitHub PR/issue **URL**. |
| `--dry-run` | no | false (real post). First-time runs on real targets should pass `--dry-run` first. |
| `--force` | no | false. See `references/edge-cases.md`. |
```

- [ ] **Step 2: Replace "When NOT to invoke" first bullet**

Change:
```markdown
- The "artifact" lacks rp1 frontmatter (no `rp1_doc_id`). Suggest the user regenerate via the producing rp1 skill, or that they post manually.
```
to:
```markdown
- The file is not an rp1 work artifact at all (not under `.rp1/work/` and unrelated to rp1). This skill publishes rp1 artifacts; frontmatter is optional, but the file should be an rp1 work product.
```

- [ ] **Step 3: Replace Step 1 (Resolve inputs) — target resolution**

Replace the entire **PR resolution / PR state check / Repo identification** portion of Step 1 with:
````markdown
**Repo identification.** Capture the current repo for bare-number targets and for API calls:

```bash
repo_full="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"  # "owner/repo"
```

**Target resolution.** If no `target` arg was passed, default to the current branch's open PR:

```bash
if [ -z "$target" ]; then
  number="$(gh pr view --json number --jq .number 2>/dev/null)"
  [ -z "$number" ] && { echo "No open PR for current branch. Push and open a PR, or pass an explicit PR/issue number or URL." >&2; exit 1; }
  owner="${repo_full%/*}"; repo="${repo_full#*/}"; kind="pr"
else
  parsed="$(python3 "$SKILL_DIR/scripts/parse_target.py" "$target" --current-repo "$repo_full")" \
    || { echo "$parsed" >&2; exit 1; }
  owner="$(echo "$parsed" | python3 -c 'import json,sys;print(json.load(sys.stdin)["owner"])')"
  repo="$(echo "$parsed"  | python3 -c 'import json,sys;print(json.load(sys.stdin)["repo"])')"
  number="$(echo "$parsed"| python3 -c 'import json,sys;print(json.load(sys.stdin)["number"])')"
  kind="$(echo "$parsed" | python3 -c 'import json,sys;print(json.load(sys.stdin)["kind"])')"
fi
repo_full="$owner/$repo"
```

**Resolve `kind` for bare numbers** (the issues API returns a `pull_request` object iff the number is a PR):

```bash
if [ "$kind" = "unknown" ]; then
  if [ "$(gh api "repos/$repo_full/issues/$number" --jq '.pull_request != null' 2>/dev/null)" = "true" ]; then
    kind="pr"
  else
    kind="issue"
  fi
fi
```

**State check** (the closed/merged → `--force` gate):

```bash
if [ "$kind" = "pr" ]; then
  read -r state base_ref head_ref < <(gh pr view "$number" --json state,baseRefName,headRefName \
    --jq '[.state,.baseRefName,.headRefName]|@tsv')
  case "$state" in
    CLOSED|MERGED) [ -n "$force" ] || { echo "PR #$number is $state. Pass --force to comment anyway." >&2; exit 1; } ;;
  esac
else
  state="$(gh issue view "$number" --json state --jq .state)"
  base_ref=""; head_ref=""
  case "$state" in
    CLOSED) [ -n "$force" ] || { echo "Issue #$number is $state. Pass --force to comment anyway." >&2; exit 1; } ;;
  esac
fi
```

`$SKILL_DIR` is this skill's directory (the folder containing `SKILL.md`). Compute it once at the top of Step 1.
````

- [ ] **Step 4: Replace Step 2 + Step 3 + Step 4 with a single "call project.py" step**

Steps 2–4 previously inlined frontmatter parsing, summary extraction, and assembly. Replace all three with:
````markdown
### Step 2: Project the comment body

Compute the repo-relative source path, then run the projection script. It is pure and
deterministic — it reads the artifact, never modifies it, and never calls GitHub.

```bash
repo_root="$(git -C "$(dirname "$path")" rev-parse --show-toplevel 2>/dev/null)"
if [ -n "$repo_root" ]; then relative_path="${path#$repo_root/}"; else relative_path="$path"; fi

body_out="$(python3 "$SKILL_DIR/scripts/project.py" "$path" --source-path "$relative_path")" || {
  # project.py exits non-zero only on the 65 KB size cap; its stderr message is already shown.
  exit 1
}
doc_key="$(python3 - "$path" "$relative_path" <<'PY'
import sys; sys.path.insert(0, "SKILL_DIR_SCRIPTS"); import project
fm, _ = project.split_frontmatter(open(sys.argv[1], encoding="utf-8").read())
print(project.marker_key(fm, sys.argv[2]))
PY
)"
```

Substitute `SKILL_DIR_SCRIPTS` with `$SKILL_DIR/scripts`. `body_out` is the exact comment
body; `doc_key` is the idempotency key (the `rp1_doc_id`, or `path:<relative_path>` when
absent). Warnings from the projection (summary-ladder rung, etc.) are printed to stderr for
the user to see.

The byte-exact contract is enforced by `tests/test_project.py` (run
`python3 -m unittest -s skills/persist-rp1-artifact/tests`), not by manual walkthrough.
````

- [ ] **Step 5: Update Step 5 (find existing comment) to key off `doc_key`**

In the marker step, the marker is now built from `doc_key` (not a raw `rp1_doc_id`):
```python
marker = f"<!-- rp1-artifact: {doc_key} -->"
```
And the comments fetch uses `repo_full` and `number` (unchanged endpoint, now also valid for issues):
```bash
gh api -X GET "repos/$repo_full/issues/$number/comments" --paginate \
  --jq '[.[] | {id: .id, body: .body, user_login: .user.login, html_url: .html_url, updated_at: .updated_at}]'
```
The soft-detection, ownership, and ≥2-match logic are unchanged.

- [ ] **Step 6: Update Step 6 (dry-run header + post) for issues**

Dry-run header: show `kind`; emit base/head only for PRs:
```python
target_line = f"#{number} ({state}, base: {base_ref}, head: {head_ref})" if kind == "pr" else f"#{number} ({state}, issue)"
```
POST/PATCH commands change `$pr_number` → `$number` and use `$repo_full`:
```bash
gh api -X POST "repos/$repo_full/issues/$number/comments" -F body=@/tmp/persist-rp1-artifact-body.md --jq '.html_url'
gh api -X PATCH "repos/$repo_full/issues/comments/$target_comment_id" -F body=@/tmp/persist-rp1-artifact-body.md --jq '.html_url'
```
Write `body_out` to the temp file before POST/PATCH: `printf '%s' "$body_out" > /tmp/persist-rp1-artifact-body.md`. Final-output line: `✓ <Posted|Updated> rp1 artifact on <PR|issue> #<number>`.

- [ ] **Step 7: Remove the dead fixture-diff command**

Delete the SKILL.md block referencing `persist-rp1-artifact-projection` (it never existed). Replace the "Fixtures (the contract)" section with:
```markdown
## Fixtures (the contract)

The `examples/*-input.md` ↔ `examples/*-output.md` pairs are byte-exact golden tests for
`scripts/project.py`, run by `tests/test_project.py`. After any change to the projection:

    python3 -m unittest -s skills/persist-rp1-artifact/tests

A failing golden test means the projection drifted from the contract — fix the script, not
the fixtures.
```

- [ ] **Step 8: Commit**

```bash
git add -A skills/persist-rp1-artifact/SKILL.md
git commit -m "refactor: SKILL.md calls project.py/parse_target.py; PR-or-issue targets

Co-authored by Claude Code"
```

---

## Task 9: Rewrite the reference docs + README

**Files:**
- Modify: `skills/persist-rp1-artifact/references/artifact-frontmatter.md`
- Modify: `skills/persist-rp1-artifact/references/projection-format.md`
- Modify: `skills/persist-rp1-artifact/references/edge-cases.md`
- Modify: `README.md`

- [ ] **Step 1: Rewrite `artifact-frontmatter.md`** — full replacement:
```markdown
# Artifact Frontmatter Reference

rp1 artifacts are markdown under `.rp1/work/`. A YAML frontmatter block (delimited by
`---`) is **optional** — some rp1 docs have none. Every field is optional too; the skill
degrades gracefully and never refuses an artifact for a missing field.

## Fields the skill reads (all optional)

| Field | Common on | Used for |
|---|---|---|
| `producer` | every templated rp1 doc | Header table "Producer" row. |
| `type` | every templated rp1 doc (`document`) | Header "Artifact type" when `artifact` is absent. |
| `artifact` | legacy/rich artifacts only | Header "Artifact type"; legacy title derivation. |
| `rp1_doc_id` | many persisted artifacts | Idempotency key when present (see projection-format.md). |
| `issue_id` | legacy/rich artifacts only | Legacy title suffix; "Issue ID" row. |
| `status` | legacy/rich artifacts only | `incomplete` → banner; "Status" row. |
| `date` | legacy/rich artifacts only | "Generated" row. |

Routing fields `scope`, `path_pattern`, `description`, `strictness` are present on most rp1
templated docs but are **not** rendered — the skill ignores them. Any other field is ignored too.

## Real shapes seen in the wild

- **Rich (legacy):** `producer`, `artifact`, `issue_id`, `status`, `date`, `rp1_doc_id`.
- **Routing + doc_id (common):** `scope`, `path_pattern`, `producer`, `type`, `description`,
  `strictness`, `rp1_doc_id`.
- **Routing only:** the same minus `rp1_doc_id`.
- **None:** no frontmatter block at all.

## Title derivation (precedence)

1. `artifact` field → Title-Case, plus ` — {issue_id}` if `issue_id` present.
2. else the document's first H1 heading (verbatim).
3. else `producer` → Title-Case.
4. else the filename stem → Title-Case.

## Parsing note

`scripts/project.py` parses frontmatter with Python stdlib only. A key line must start at
column 0 (`^key: value`); indented continuation lines of multi-line quoted values are not
parsed as keys, so a colon inside a wrapped `description` cannot create a bogus key.
```

- [ ] **Step 2: Rewrite `projection-format.md`** — full replacement:
```markdown
# Projection Format Reference

The exact comment body is produced by `scripts/project.py` and pinned byte-for-byte by the
golden tests in `tests/test_project.py`. This document describes the format; the script is
the source of truth.

## Template

```
<!-- rp1-artifact: {{key}} -->
## 📋 rp1 Artifact: {{Title}}

| Field | Value |
|-------|-------|
{{header rows — only those with a value; Source path always present}}

{{incomplete_banner — present only if status == incomplete, followed by a blank line}}
### Executive Summary

{{summary_body}}

<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

{{rest_of_body}}

</details>

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
```

## Key (idempotency marker)

`{{key}}` = `rp1_doc_id` when present and non-empty, else `path:{{relative_path}}`. The
marker `<!-- rp1-artifact: {{key}} -->` is **always line 1**. Re-runs find the comment by
this exact marker.

## Header table

One row per field **that has a value** — absent fields are omitted entirely (no `—`
placeholder). Order: Producer, Artifact type (`artifact` else `type`), Issue ID, Status,
Generated, Doc ID, Source path. Source path is always shown, so the table is never empty.

## Summary extraction (deterministic ladder)

Operates on the body after the leading H1 is stripped. First match wins:

1. Summary-named H2 (`Executive Summary|Summary|Overview|TL;DR`, optional `N.` prefix).
2. First H2.
3. First subheading H3–H6 (no H2 present).
4. First thematic break (`---` / `***` / `___`).
5. First paragraph boundary (lead paragraph is the summary).
6. Single block (whole body is the summary; no collapsible).

Rungs 2–6 emit a one-line stderr warning. When `rest_body` is empty the `<details>` block
is omitted.

## Deterministic rules

1. The HTML marker is always line 1 — no leading whitespace, no BOM.
2. Body content is never re-paraphrased — pure markdown slicing.
3. The body always ends in exactly one newline.
4. The artifact file is never modified.
```

- [ ] **Step 3: Update `edge-cases.md`**

Replace the "No frontmatter block", "`rp1_doc_id` absent", and "`producer` or `artifact` absent" rows of the Error-conditions table with a single non-error note, and add issue rows. Specifically:

Remove these three rows:
```markdown
| No frontmatter block | regex `^---\n.*?\n---\n` fails | `Artifact has no YAML frontmatter block.` |
| `rp1_doc_id` absent | frontmatter parsing | `Artifact is missing rp1_doc_id. Regenerate via the producing rp1 skill.` |
| `producer` or `artifact` absent | frontmatter parsing | `Artifact is missing required field: <field>.` |
```
Add this row:
```markdown
| Frontmatter or any field absent | n/a | **Not an error.** Frontmatter is optional; absent fields are skipped; the idempotency key falls back to `path:<relative-path>`. |
| Target is an issue (not a PR) | `kind` resolution | **Not an error.** Comments use `/issues/{n}/comments`, valid for both. State checked via `gh issue view`. |
| Closed issue | `gh issue view --json state` | **WARN, allow only with `--force`.** `Issue #<n> is CLOSED. Pass --force to comment anyway.` |
```

Update the `--force` "does not loosen" list: replace `Missing rp1_doc_id refusal (no idempotency = no go, even with force)` with `(there is no missing-field refusal anymore — frontmatter is optional)`.

Add to the "Path not under `.rp1/work/`" row note: the path-based key still works outside `.rp1/work/`; the warning is informational.

Add a new short section:
```markdown
## Path-based idempotency key

When an artifact has no `rp1_doc_id`, the marker is keyed off the repo-relative path
(`<!-- rp1-artifact: path:<relative-path> -->`). Stable across re-runs; the skill never
writes to the artifact. Trade-off: **renaming or moving the artifact orphans its old
comment** (a fresh comment is posted). Delete the stale comment manually if that happens.
```

Update the `--dry-run` block header to use the target line that includes `kind` (PR shows base/head; issue does not).

- [ ] **Step 4: Update `README.md`**

Find the usage/synopsis and the "what is an artifact" framing. Update the synopsis to `/persist-rp1-artifact <path> [target] [--dry-run] [--force]` where `[target]` is a PR/issue number or URL. Replace any statement that the artifact must contain `rp1_doc_id` (or rich frontmatter) with: frontmatter is optional; works on any markdown under `.rp1/work/`; idempotency uses `rp1_doc_id` when present, else the repo-relative path. (Grep first: `grep -n "rp1_doc_id\|pr-number\|frontmatter" README.md`.)

- [ ] **Step 5: Commit**

```bash
git add -A skills/persist-rp1-artifact/references README.md
git commit -m "docs: rewrite references + README for optional frontmatter and issue targets

Co-authored by Claude Code"
```

---

## Task 10: End-to-end dry-run verification on real artifacts

No code — prove the whole pipeline on the two artifacts that defined the problem. Uses real
`gh`, so it requires auth and network. **Dry-run only — no real posts.**

- [ ] **Step 1: Idempotency regression — #564 rich artifact**

The live #564 comment's marker is `9f27673c-7480-4770-8aaa-c390669cffb9`. Confirm a dry-run
against the rich artifact still resolves to **PATCH** that same comment:
```bash
python3 skills/persist-rp1-artifact/scripts/project.py \
  /Users/edruder/Development/pdf-service/.rp1/work/issues/node-20-upgrade/investigation_report.md \
  --source-path .rp1/work/issues/node-20-upgrade/investigation_report.md | head -1
```
Expected line 1: `<!-- rp1-artifact: 9f27673c-7480-4770-8aaa-c390669cffb9 -->` (matches the
live comment's marker → a real run would PATCH, not orphan).

- [ ] **Step 2: The original failer — routing-only artifact, projection works**

```bash
python3 skills/persist-rp1-artifact/scripts/project.py \
  /Users/edruder/Development/pdf-service/.rp1/work/issues/node-20-upgrade/opencv4nodejs-customallocator-investigation.md \
  --source-path .rp1/work/issues/node-20-upgrade/opencv4nodejs-customallocator-investigation.md | head -20
```
Expected: line 1 is `<!-- rp1-artifact: path:.rp1/work/issues/node-20-upgrade/opencv4nodejs-customallocator-investigation.md -->`; title is the H1 ("Follow-up: address …"); header table shows Producer + Artifact type (`document`) + Source path only; no crash.

- [ ] **Step 3: parse_target resolves the issue URL**

```bash
python3 skills/persist-rp1-artifact/scripts/parse_target.py https://github.com/anvilco/pdf-service/issues/576 --current-repo anvilco/pdf-service
```
Expected: `{"owner": "anvilco", "repo": "pdf-service", "number": 576, "kind": "issue"}`.

- [ ] **Step 4: Full test suite green**

Run: `python3 -m unittest -v -s skills/persist-rp1-artifact/tests`
Expected: all unit + golden tests PASS.

- [ ] **Step 5: Commit any fixups, then summarize**

If steps 1–3 surfaced a bug, fix it (with a regression test) and re-run. Otherwise the
branch is ready. Final commit if anything changed:
```bash
git add -A && git commit -m "test: verify dry-run pipeline on real rich/routing-only/issue targets

Co-authored by Claude Code"
```

---

## Self-Review

**Spec coverage:**
- §1 frontmatter optional, any markdown → Task 1 (optional block), Task 6 (no-frontmatter fixture). ✓
- §2 title from H1/artifact/producer/filename → Task 2. ✓
- §3 header skip-absent rows → Task 4. ✓
- §4 key = rp1_doc_id else path: → Task 4 (`marker_key`), Task 8 (`doc_key` wiring). ✓
- §5 target PR/issue, number/URL → Task 7 (`parse_target`), Task 8 (resolution + kind probe + state). ✓
- §6 6-rung summary ladder → Task 3. ✓
- Fixtures expansion → Task 6. ✓
- Docs (artifact-frontmatter, projection-format, edge-cases, SKILL.md, README) → Tasks 8–9. ✓
- Backward compat (#564 byte-identical) → Task 5 golden anchor + Task 10 Step 1. ✓
- Non-goal: no doc_id injection (read-only preserved) — `marker_key` never writes. ✓

**Placeholder scan:** No TBD/TODO. The only intentional substitution tokens are
`SKILL_DIR_SCRIPTS` / `$SKILL_DIR` in Task 8, with explicit substitution instructions.

**Type consistency:** `project()`, `split_frontmatter()`, `derive_title()`,
`strip_leading_h1()`, `extract_summary()`, `build_table_rows()`, `build_banner()`,
`marker_key()`, `assemble()`, `check_size()`, `main()` — names used identically in tests
and implementation. `parse_target.parse()` returns the same dict keys (`owner/repo/number/kind`)
used by SKILL.md Step 3. Golden `CASES` tuples are `(name, source_path)` throughout.
```
