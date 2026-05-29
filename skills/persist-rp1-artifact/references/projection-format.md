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
