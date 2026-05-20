# Projection Format Reference

The exact shape of the PR comment posted by `persist-rp1-artifact`. Two implementations following this reference should produce byte-identical comment bodies.

## Template

```
<!-- rp1-artifact: {{rp1_doc_id}} -->
## 📋 rp1 Artifact: {{Title}}

| Field | Value |
|-------|-------|
| Producer | `{{producer}}` |
| Artifact type | `{{artifact}}` |
| Issue ID | `{{issue_id | —}}` |
| Status | `{{status | —}}` |
| Generated | {{date | —}} |
| Doc ID | `{{rp1_doc_id}}` |
| Source path | `{{relative_path}}` (gitignored, local to author) |

{{incomplete_banner}}

### Executive Summary

{{summary_section_body}}

<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

{{rest_of_body}}

</details>

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
```

## Fill-in rules

| Placeholder | Source | Rules |
|---|---|---|
| `{{rp1_doc_id}}` | frontmatter `rp1_doc_id` | Required. Refuse if absent. |
| `{{Title}}` | derived from `artifact` + `issue_id` | See `artifact-frontmatter.md` § Title derivation. |
| `{{producer}}`, `{{artifact}}` | frontmatter | Required. |
| `{{issue_id}}`, `{{status}}`, `{{date}}` | frontmatter | If absent, render as `—` (em dash, U+2014). |
| `{{relative_path}}` | input arg | Convert absolute path to repo-relative (use `git rev-parse --show-toplevel` to find repo root). |
| `{{incomplete_banner}}` | frontmatter `status` | If `status == "incomplete"`, render `\n> ⚠️ **This artifact is marked \`incomplete\`.** Reviewers: the analysis below may evolve.\n`. Otherwise empty string (no blank line). |
| `{{summary_section_body}}` | first matching H2 section | See § Top-summary extraction. |
| `{{rest_of_body}}` | everything after the summary section | Verbatim, including all subsequent H2/H3 sections, tables, code blocks. |

## Top-summary extraction

The "summary section" is the first H2 whose heading matches this regex (case-insensitive, multiline):

```
^##\s+(\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$
```

Matches:
- `## Executive Summary`
- `## 1. Executive Summary`
- `## summary`
- `## TL;DR`

Capture the section body from after the heading line up to (but not including) the next `^## ` line.

**Fallback:** if no heading matches, use the *first* H2 section in the document and emit a warning to stderr: `WARNING: no Executive Summary section found; falling back to first H2 ("<heading>")`.

## Deterministic rules

1. The HTML marker `<!-- rp1-artifact: <doc_id> -->` is **always line 1**. No leading whitespace, no BOM, nothing else before it.
2. Missing frontmatter fields render as `—` (em dash, U+2014), never blank.
3. Body content is **never re-paraphrased or rewritten**. Pure markdown slicing — a typo in the artifact stays a typo in the comment.
4. Trailing newlines are normalized to exactly one at end of body.
