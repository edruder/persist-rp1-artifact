# `persist-rp1-artifact` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal user-level Claude skill at `~/.claude/skills/persist-rp1-artifact/` that publishes rp1 artifacts (e.g. investigation reports under `.rp1/work/`) as idempotent PR comments without committing the artifacts to the repo.

**Architecture:** Pure-markdown skill — no compiled code, no test framework. SKILL.md defines a deterministic procedure the agent executes using its built-in `Bash` (for `gh`), `Read`, and `Grep` tools. Reference docs lock down the projection format and edge cases; example fixture pairs (input ↔ expected output) serve as the "contract" the procedure must satisfy.

**Tech Stack:** Markdown · `gh` CLI · standard Unix tools (`awk`, `sed`, `grep`) accessed via the agent's Bash tool · Python 3 (`python3 -c`) for YAML frontmatter parsing — pre-installed on every supported macOS/Linux dev machine.

**Non-goals (per spec):** Multi-comment chunking, stacked-PR fan-out, comment-back-to-file hydration, type-aware projection, retrofit automation. Documented as v2.

**Spec:** `~/.claude/skills/persist-rp1-artifact/DESIGN.md`

---

## Conventions used in this plan

- **"Save the file."** Replaces "commit" steps. `~/.claude/` is not a git repo (per spec); we save files in place and rely on the user's filesystem snapshots for recovery.
- **"Verify rendering."** Where a task produces markdown that will appear in GitHub PR comments or render in Claude Code's skill listing, the verification step is to either (a) preview locally with `glow` or `bat`, or (b) eyeball-diff against an expected fixture. Both methods are explicit per task.
- **Fixture-driven.** The primary investigation-report fixture pair (Task 2) is the contract. Every subsequent SKILL.md task must, after completion, allow a careful manual reading of SKILL.md applied to the input fixture to produce the expected output byte-for-byte.

---

## Task 1: Lay down all three reference docs

**Files:**
- Create: `~/.claude/skills/persist-rp1-artifact/references/artifact-frontmatter.md`
- Create: `~/.claude/skills/persist-rp1-artifact/references/projection-format.md`
- Create: `~/.claude/skills/persist-rp1-artifact/references/edge-cases.md`

These docs are prescriptive — they encode the spec decisions. Writing all three up front means subsequent procedural tasks can reference them by path without forward-declaration churn.

- [ ] **Step 1: Create the references directory**

```bash
mkdir -p ~/.claude/skills/persist-rp1-artifact/references
```

Run: `ls ~/.claude/skills/persist-rp1-artifact/references`
Expected: empty listing (directory exists, no files yet).

- [ ] **Step 2: Write `references/artifact-frontmatter.md`**

Write this exact content to the file:

````markdown
# Artifact Frontmatter Reference

rp1 artifacts begin with a YAML frontmatter block delimited by `---` on its own line at the start and end. The skill reads this block to:

- Identify the artifact type and producer (for the header table)
- Resolve the idempotency key (`rp1_doc_id`)
- Detect `status: incomplete` for banner emission

## Required fields

| Field | Type | Purpose |
|---|---|---|
| `producer` | string | Name of the rp1 agent that produced the artifact (e.g. `bug-investigator`). Renders into the header table. |
| `artifact` | string | Artifact type slug (e.g. `investigation-report`, `feature-design`, `code-audit`). Used to derive the comment title. |
| `rp1_doc_id` | UUID string | **Idempotency key.** Used to find/update the comment on re-runs. Must be present — absent → skill refuses to publish. |

## Optional fields (rendered if present, otherwise show `—`)

| Field | Type | Purpose |
|---|---|---|
| `issue_id` | string | Issue identifier (e.g. `node-20-upgrade`). Used in title. |
| `status` | string | `complete` or `incomplete`. `incomplete` triggers a banner. |
| `date` | string (YYYY-MM-DD) | Generation date. |

## Unknown fields

Pass through into the header table verbatim (key as-typed, value as-typed). The skill is **not** strict — we don't want to break when a new rp1 agent adds a field.

## Title derivation

The comment title is built from `artifact` (kebab-case slug) and `issue_id`:

- Convert `artifact` from kebab-case to Title Case: `investigation-report` → `Investigation Report`
- Join with em-dash + `issue_id`: `Investigation Report — node-20-upgrade`

If `issue_id` is absent, drop the em-dash and trailing portion: just `Investigation Report`.

## Canonical example

This is the frontmatter from the `.rp1/work/issues/node-20-upgrade/investigation_report.md` artifact that originally motivated this skill:

```yaml
---
producer: bug-investigator
artifact: investigation-report
issue_id: node-20-upgrade
status: complete
date: 2026-05-12
rp1_doc_id: 9f27673c-7480-4770-8aaa-c390669cffb9
---
```

## Parsing implementation note

Frontmatter parsing uses Python 3's stdlib only (no PyYAML dependency):

```bash
python3 - <<'PY' "$ARTIFACT_PATH"
import sys, re
path = sys.argv[1]
with open(path) as f:
    txt = f.read()
m = re.match(r'^---\n(.*?)\n---\n', txt, re.DOTALL)
if not m:
    sys.exit("ERROR: no frontmatter block found")
fm = {}
for line in m.group(1).splitlines():
    if ':' in line:
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip()
# fm is a flat dict of string -> string
for k, v in fm.items():
    print(f"{k}={v}")
PY
```

This is sufficient for rp1 artifact frontmatter, which is always flat key-value (no nested dicts, no lists). Reject the artifact if the regex doesn't match.
````

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/references/artifact-frontmatter.md`
Expected: line count > 50 (the file is non-trivial).

- [ ] **Step 3: Write `references/projection-format.md`**

Write this exact content to the file:

````markdown
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
| `{{incomplete_banner}}` | frontmatter `status` | If `status == "incomplete"`, render `\n> ⚠️ **This artifact is marked `incomplete`.** Reviewers: the analysis below may evolve.\n`. Otherwise empty string (no blank line). |
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
````

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/references/projection-format.md`
Expected: line count > 60.

- [ ] **Step 4: Write `references/edge-cases.md`**

Write this exact content to the file:

````markdown
# Edge Cases Reference

Behavior at every decision point that could be ambiguous, destructive, or non-idempotent.

## Re-run lookup outcomes

After fetching all comments on the PR and grepping for `<!-- rp1-artifact: <doc_id> -->`:

| Matches | Author of match | Behavior |
|---|---|---|
| 0 | n/a | **POST** new comment via `gh api`. |
| 1 | == current `gh` user | **PATCH** existing comment. GitHub's "edited" badge surfaces the change. |
| 1 | != current `gh` user | **Refuse unless `--force`.** Print: `Comment is owned by @<login>. Pass --force to overwrite, or coordinate with them.` |
| ≥ 2 | any | **Refuse.** Print all matching comment URLs. Tell user to delete duplicates manually. Never auto-pick. |

To resolve the current `gh` user: `gh api user --jq .login`.
To get a comment's author: the `user.login` field on each comment object.

## Marker dropped from existing comment

If someone manually edited the canonical comment and removed the `<!-- rp1-artifact: ... -->` line, the lookup finds 0 matches → we POST a new comment. **Print a warning to stderr:**

```
WARNING: idempotency was broken for this artifact (no marker found in existing PR comments).
A new comment will be posted, leaving the pre-existing comment orphaned.
Consider deleting the old comment manually.
```

## Error conditions

Principle: **fail loud, never destructive, never silent.** All errors exit non-zero.

| Failure | Detection | Exit message |
|---|---|---|
| `gh` not installed | `command -v gh` fails | `gh CLI not found. Install: https://cli.github.com` |
| `gh` not authenticated | `gh auth status` exits non-zero | `gh is not authenticated. Run: gh auth login` |
| Path doesn't exist | `test -f "$path"` fails | `Artifact not found: <absolute-path>` |
| Path not under `.rp1/work/` | prefix check on `$path` | **WARN, continue.** `WARNING: <path> is outside .rp1/work/. Idempotency requires rp1_doc_id frontmatter.` |
| No frontmatter block | regex `^---\n.*?\n---\n` fails | `Artifact has no YAML frontmatter block.` |
| `rp1_doc_id` absent | frontmatter parsing | `Artifact is missing rp1_doc_id. Regenerate via the producing rp1 skill.` |
| `producer` or `artifact` absent | frontmatter parsing | `Artifact is missing required field: <field>.` |
| No PR for branch + no `pr-number` arg | `gh pr view` returns no PR | `No open PR for current branch. Push and open a PR, or pass an explicit PR number.` |
| PR closed or merged | `gh pr view --json state` | **WARN, allow only with `--force`.** `PR #<n> is <state>. Pass --force to comment anyway.` |
| Comment body > 65 536 chars | `wc -c` after assembly | `Comment body exceeds GitHub's 65 KB cap (<size> bytes). Multi-comment chunking is not yet supported.` |
| Network / GitHub API error | non-zero exit from `gh api` | Bubble up the `gh` error verbatim. Local artifact is unchanged. |
| No recognizable summary section | regex misses all variants | **WARN, fall back to first H2.** `WARNING: no Executive Summary section found; falling back to first H2 ("<heading>").` |
| `status: incomplete` in frontmatter | frontmatter parsing | Publish with the `⚠️ marked incomplete` banner (see projection-format.md). Not an error. |
| Local artifact `mtime` older than existing comment `updated_at` | `stat` vs `gh api` `updated_at` | **WARN, allow.** `WARNING: local artifact is older than the existing comment. Continuing — pass --force to suppress this warning.` |

## --force flag effects

A single flag that loosens three guard rails at once:
1. Overwriting another user's comment (one match, different author).
2. Posting to a closed/merged PR.
3. Suppressing the "local older than comment" warning.

`--force` does **not** loosen:
- Multiple-match refusal (still requires manual dedup)
- Missing `rp1_doc_id` refusal (no idempotency = no go, even with force)
- Body-size cap (65 KB is a GitHub-side limit)

## --dry-run flag effects

Runs procedure steps 1–5 (resolve PR, read, parse, project, lookup existing). Stops before any `POST`/`PATCH`. Prints to stdout:

```
=== persist-rp1-artifact (dry run) ===
Artifact: <relative-path>
Doc ID:   <rp1_doc_id>
PR:       #<n> (<state>, base: <base>, head: <head>)
Size:     <bytes> / 65536 bytes
Action:   would <POST|PATCH> (matched comment: <url-or-none>)

--- projected comment body ---
<full body>
--- end body ---
```

Then exit 0. **Stdout is the projected body for piping/diffing.** Diagnostic line ("Action:" etc.) goes to stderr so `--dry-run | diff expected.md -` works.
````

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/references/edge-cases.md`
Expected: line count > 60.

- [ ] **Step 5: Save the files and verify all three exist**

Run: `ls -la ~/.claude/skills/persist-rp1-artifact/references/`
Expected: three files (`artifact-frontmatter.md`, `projection-format.md`, `edge-cases.md`), each non-empty.

---

## Task 2: Build the primary fixture pair (investigation-report)

**Files:**
- Create: `~/.claude/skills/persist-rp1-artifact/examples/investigation-report-input.md`
- Create: `~/.claude/skills/persist-rp1-artifact/examples/investigation-report-output.md`

This pair is **the contract.** Every subsequent SKILL.md task must, after manual execution, produce the output fixture byte-for-byte from the input fixture.

We use the real Node-20 investigation report (commit `0a5d58fc` in `pdf-service`) as source material, **truncated** to keep the fixture readable (~80 lines vs 397). The truncation is principled: keep frontmatter exactly, keep Executive Summary verbatim (this is what the projection extracts), drop later sections except enough to prove the `<details>` collapse logic.

- [ ] **Step 1: Create the examples directory**

```bash
mkdir -p ~/.claude/skills/persist-rp1-artifact/examples
```

- [ ] **Step 2: Write `examples/investigation-report-input.md`**

Write this exact content (faithful truncation of the real artifact):

````markdown
---
producer: bug-investigator
artifact: investigation-report
issue_id: node-20-upgrade
status: complete
date: 2026-05-12
rp1_doc_id: 9f27673c-7480-4770-8aaa-c390669cffb9
---

# Investigation Report — Node 16 → 18 → 20 Upgrade Path

## 1. Executive Summary

The pdf-service repo is currently pinned to Node 16.14.0 across `.nvmrc`, two Dockerfiles, two `package.json` `engines` fields, and one Babel target. Node 16 went EOL in September 2023; Node 18 EOL was April 2025; only Node 20 (Active LTS until Apr 2026) and Node 22 are currently in support.

**The single biggest risk is `node-java` (currently pinned at `^0.12.1`).** This is a native module that builds from source via node-gyp/nan; the installed `nan@2.14.1` does not compile on Node 20.x. Upstream fixed this in `java@0.14.0`.

**Recommended sequence**: three checkpoints — (A) bump `java` to 0.15.x on Node 16 first; (B) move to Node 18.20-alpine; (C) move to Node 20.x. Effort estimate: 3–7 focused sessions assuming no exotic surprises.

## 2. Investigation Process

### Sources consulted

- GitHub issue #499 (full body + 4 comments)
- Codebase audit — all Node-version pinpoints read directly
- npm registry — `npm view <pkg> engines` for ~12 packages

### Hypotheses tested

| # | Hypothesis | Verdict |
|---|-----------|---------|
| H1 | `node-java` at the pinned version cannot compile against Node 20's V8 headers. | **Confirmed** |
| H2 | OpenSSL 3 (Node 17+) breaks signing or some MD5/SHA1 path in JS. | **Mostly rejected** |
| H3 | The hard-coded image-hash health checks will drift after the upgrade. | **Likely, low certainty** |

## 3. Recommended Sequence

1. **PR A**: `java` bump on Node 16 (isolate native build risk)
2. **PR B**: Node 18.20-alpine (toolchain churn — alpine 3.20, python3, libvips)
3. **PR C**: Node 20.x (last hop, easiest if A and B are clean)
````

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/examples/investigation-report-input.md`
Expected: ~35 lines.

- [ ] **Step 3: Write `examples/investigation-report-output.md`**

This is the byte-exact expected projection. Write this exact content:

````markdown
<!-- rp1-artifact: 9f27673c-7480-4770-8aaa-c390669cffb9 -->
## 📋 rp1 Artifact: Investigation Report — node-20-upgrade

| Field | Value |
|-------|-------|
| Producer | `bug-investigator` |
| Artifact type | `investigation-report` |
| Issue ID | `node-20-upgrade` |
| Status | `complete` |
| Generated | 2026-05-12 |
| Doc ID | `9f27673c-7480-4770-8aaa-c390669cffb9` |
| Source path | `examples/investigation-report-input.md` (gitignored, local to author) |

### Executive Summary

The pdf-service repo is currently pinned to Node 16.14.0 across `.nvmrc`, two Dockerfiles, two `package.json` `engines` fields, and one Babel target. Node 16 went EOL in September 2023; Node 18 EOL was April 2025; only Node 20 (Active LTS until Apr 2026) and Node 22 are currently in support.

**The single biggest risk is `node-java` (currently pinned at `^0.12.1`).** This is a native module that builds from source via node-gyp/nan; the installed `nan@2.14.1` does not compile on Node 20.x. Upstream fixed this in `java@0.14.0`.

**Recommended sequence**: three checkpoints — (A) bump `java` to 0.15.x on Node 16 first; (B) move to Node 18.20-alpine; (C) move to Node 20.x. Effort estimate: 3–7 focused sessions assuming no exotic surprises.

<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

## 2. Investigation Process

### Sources consulted

- GitHub issue #499 (full body + 4 comments)
- Codebase audit — all Node-version pinpoints read directly
- npm registry — `npm view <pkg> engines` for ~12 packages

### Hypotheses tested

| # | Hypothesis | Verdict |
|---|-----------|---------|
| H1 | `node-java` at the pinned version cannot compile against Node 20's V8 headers. | **Confirmed** |
| H2 | OpenSSL 3 (Node 17+) breaks signing or some MD5/SHA1 path in JS. | **Mostly rejected** |
| H3 | The hard-coded image-hash health checks will drift after the upgrade. | **Likely, low certainty** |

## 3. Recommended Sequence

1. **PR A**: `java` bump on Node 16 (isolate native build risk)
2. **PR B**: Node 18.20-alpine (toolchain churn — alpine 3.20, python3, libvips)
3. **PR C**: Node 20.x (last hop, easiest if A and B are clean)

</details>

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
````

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/examples/investigation-report-output.md`
Expected: ~45 lines.

- [ ] **Step 4: Save the files and verify byte-exactness invariants**

Run: `head -1 ~/.claude/skills/persist-rp1-artifact/examples/investigation-report-output.md`
Expected: `<!-- rp1-artifact: 9f27673c-7480-4770-8aaa-c390669cffb9 -->`
This proves rule #1 (HTML marker on line 1, no leading whitespace).

Run: `grep -c '^—$\|—' ~/.claude/skills/persist-rp1-artifact/examples/investigation-report-output.md`
Expected: at least 1 match (em-dash used in title and bullets, proving U+2014 is preserved).

---

## Task 3: Scaffold SKILL.md with frontmatter + structure

**Files:**
- Create: `~/.claude/skills/persist-rp1-artifact/SKILL.md`

Establish the skill's identity (so Claude Code can list and invoke it) and the procedure skeleton. Later tasks fill in each procedure step.

- [ ] **Step 1: Write the SKILL.md scaffold**

Write this exact content:

````markdown
---
name: persist-rp1-artifact
description: Use when the user has an rp1 artifact under .rp1/work/ (e.g. investigation report, design doc, audit) and wants to publish it as a PR comment instead of committing the file to the repo. Idempotent — re-runs update the same comment in place via an HTML doc-id marker. Invoke when the user says "post rp1 artifact to PR", "publish investigation report as PR comment", "persist rp1 artifact", or runs `/persist-rp1-artifact`.
---

# persist-rp1-artifact

Publish an rp1 artifact (frontmatter-bearing markdown under `.rp1/work/`) as a PR comment without committing the artifact file to the repo. Re-running updates the same comment in place.

**The artifact file is never modified by this skill** — it is read-only on the local side, write-only on the GitHub side.

## When to invoke

- User explicitly runs `/persist-rp1-artifact <path> [pr-number]`.
- User has just produced an rp1 artifact and asks how to share it on a PR without committing it.
- User asks to "summarize an rp1 investigation report into a PR comment."

## When NOT to invoke

- The "artifact" lacks rp1 frontmatter (no `rp1_doc_id`). Suggest the user regenerate via the producing rp1 skill, or that they post manually.
- The user wants to keep the artifact in the repo. This skill is for the *don't commit it* case.

## Inputs

| Arg | Required | Default |
|---|---|---|
| `<path>` | yes | — |
| `[pr-number]` | no | current branch's open PR (`gh pr view --json number -q .number`) |
| `--dry-run` | no | false (real post). First-time runs on real PRs should pass `--dry-run` first. |
| `--force` | no | false. See `references/edge-cases.md` for what `--force` loosens. |

## References (read these — they encode the spec)

- `references/artifact-frontmatter.md` — required/optional frontmatter fields, parsing implementation, title derivation rule.
- `references/projection-format.md` — exact comment template and fill-in rules. **The output is byte-deterministic.**
- `references/edge-cases.md` — re-run dedup logic, error table, `--force`/`--dry-run` semantics.

## Fixtures (the contract)

`examples/investigation-report-input.md` ↔ `examples/investigation-report-output.md` is the primary fixture pair. After any procedural change to this skill, manually walk through the input and verify the output matches byte-for-byte.

## Procedure

This procedure is executed by the main agent using `Read`, `Bash` (for `gh`), and `Grep`. Each step has explicit failure modes — refer to `references/edge-cases.md`.

### Step 1: Resolve inputs

> _Filled in by Task 4 of the plan._

### Step 2: Load + parse the artifact

> _Filled in by Task 5 of the plan._

### Step 3: Extract the top-summary section

> _Filled in by Task 6 of the plan._

### Step 4: Assemble the projected comment body

> _Filled in by Task 7 of the plan._

### Step 5: Find any existing comment for this artifact

> _Filled in by Task 8 of the plan._

### Step 6: Post or update (honoring `--dry-run`)

> _Filled in by Task 9 of the plan._

## Spec

See `DESIGN.md` for the spec this skill implements.
````

- [ ] **Step 2: Save and verify the skill is discoverable**

Run: `cat ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -3`
Expected: starts with `---`, then `name: persist-rp1-artifact`, then `description:` line.

The skill will be picked up by Claude Code on the next session. (No restart needed for an immediate self-test against the procedure — the main agent can `Read` SKILL.md directly.)

---

## Task 4: SKILL.md Procedure Step 1 — Resolve inputs

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 1" placeholder)

- [ ] **Step 1: Replace the Step 1 placeholder**

In `SKILL.md`, find the line `### Step 1: Resolve inputs` and the following placeholder `> _Filled in by Task 4 of the plan._`. Replace the placeholder line with this exact content:

````markdown
**Arguments parsing.** The skill is invoked as `/persist-rp1-artifact <path> [pr-number] [--dry-run] [--force]`. Parse positional args first, then flags. Treat anything starting with `--` as a flag.

**Pre-flight checks** (in order; fail fast):

1. `command -v gh >/dev/null` — if absent, exit with: `gh CLI not found. Install: https://cli.github.com`.
2. `gh auth status >/dev/null 2>&1` — if non-zero, exit with: `gh is not authenticated. Run: gh auth login`.
3. `test -f "$path"` — if absent, exit with: `Artifact not found: $(realpath "$path" 2>/dev/null || echo "$path")`.

**Path warning.** Compute the path's prefix:

```bash
case "$(realpath "$path")" in
  */.rp1/work/*) ;;  # OK
  *) echo "WARNING: $path is outside .rp1/work/. Idempotency requires rp1_doc_id frontmatter." >&2 ;;
esac
```

This is a warning only — continue.

**Repo-relative path.** Compute for use in the projection's "Source path" row:

```bash
repo_root="$(git -C "$(dirname "$path")" rev-parse --show-toplevel)"
relative_path="${path#$repo_root/}"
```

If `git rev-parse` fails (not in a repo), use `$path` as-is and warn.

**PR resolution.** If `pr-number` was passed positionally, use it. Otherwise:

```bash
pr_number="$(gh pr view --json number --jq .number 2>/dev/null)"
```

If empty, exit with: `No open PR for current branch. Push and open a PR, or pass an explicit PR number.`

**PR state check.**

```bash
pr_state="$(gh pr view "$pr_number" --json state --jq .state)"
```

If `pr_state` is `CLOSED` or `MERGED`:
- Without `--force`: exit with `PR #$pr_number is $pr_state. Pass --force to comment anyway.`
- With `--force`: continue, no warning.

**Repo identification.** For subsequent `gh api repos/...` calls, capture `owner` and `repo`:

```bash
repo_full="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"  # "owner/repo"
```
````

- [ ] **Step 2: Verify the section is well-formed**

Run: `grep -A 2 '^### Step 1: Resolve inputs' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: shows the heading and the first paragraph of new content (not the placeholder).

---

## Task 5: SKILL.md Procedure Step 2 — Load + parse the artifact

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 2" placeholder)

- [ ] **Step 1: Replace the Step 2 placeholder**

Find `### Step 2: Load + parse the artifact` and replace the following placeholder with:

````markdown
**Split frontmatter from body.** Use Python 3 (always available on macOS/Linux dev machines):

```bash
python3 - <<'PY' "$path"
import sys, re
with open(sys.argv[1]) as f:
    txt = f.read()
m = re.match(r'^---\n(.*?)\n---\n(.*)$', txt, re.DOTALL)
if not m:
    sys.exit("ERROR: artifact has no YAML frontmatter block.")
# Print frontmatter on stdout up to a delimiter, then body
print("===FRONTMATTER===")
print(m.group(1))
print("===BODY===")
print(m.group(2), end="")
PY
```

Pipe this into the agent's working memory. Refuse the artifact (non-zero exit) if the regex doesn't match.

**Parse frontmatter into a flat dict.** The dict is `key -> string-value`. rp1 frontmatter never has nested dicts or lists (see `references/artifact-frontmatter.md`).

```python
fm = {}
for line in frontmatter_text.splitlines():
    if ':' in line:
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip()
```

**Validate required fields.** All three must be present and non-empty:

| Field | Missing → exit message |
|---|---|
| `rp1_doc_id` | `Artifact is missing rp1_doc_id. Regenerate via the producing rp1 skill.` |
| `producer` | `Artifact is missing required field: producer.` |
| `artifact` | `Artifact is missing required field: artifact.` |

**Derive the title.** Per `references/artifact-frontmatter.md` § Title derivation:

```python
import re
def title_case(slug):
    return ' '.join(w.capitalize() for w in slug.split('-'))
artifact_title = title_case(fm['artifact'])  # "investigation-report" -> "Investigation Report"
issue = fm.get('issue_id', '').strip()
if issue:
    title = f"{artifact_title} — {issue}"  # em-dash U+2014
else:
    title = artifact_title
```

**Capture optional fields with em-dash defaults** for the header table:

```python
def field(key):
    v = fm.get(key, '').strip()
    return v if v else '—'  # em-dash U+2014
```
````

- [ ] **Step 2: Verify the section is well-formed**

Run: `grep -A 2 '^### Step 2: Load' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: shows the heading and first content paragraph.

---

## Task 6: SKILL.md Procedure Step 3 — Extract the top-summary

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 3" placeholder)

- [ ] **Step 1: Replace the Step 3 placeholder**

Find `### Step 3: Extract the top-summary section` and replace the placeholder with:

````markdown
**Find the summary heading.** Apply this regex against the body text (multiline, case-insensitive):

```
^##\s+(\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$
```

Implementation:

```python
import re
SUMMARY_RE = re.compile(
    r'^##\s+(?:\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$',
    re.MULTILINE | re.IGNORECASE
)
match = SUMMARY_RE.search(body)
```

**On match:** capture from the line *after* the matched heading up to (but not including) the next `^## ` line.

```python
if match:
    start = match.end() + 1  # skip the newline after the heading
    next_h2 = re.search(r'^## ', body[start:], re.MULTILINE)
    end = start + next_h2.start() if next_h2 else len(body)
    summary_body = body[start:end].rstrip() + '\n'
    rest_body = body[end:].lstrip('\n').rstrip() + '\n' if end < len(body) else ''
```

**On miss:** fall back to the first H2 in the document. Emit a warning to stderr:

```python
else:
    first_h2 = re.search(r'^## (.+)$', body, re.MULTILINE)
    if not first_h2:
        sys.exit("Artifact body has no H2 headings; cannot extract a summary section.")
    print(f"WARNING: no Executive Summary section found; falling back to first H2 (\"{first_h2.group(1)}\").", file=sys.stderr)
    start = first_h2.end() + 1
    next_h2 = re.search(r'^## ', body[start:], re.MULTILINE)
    end = start + next_h2.start() if next_h2 else len(body)
    summary_body = body[start:end].rstrip() + '\n'
    rest_body = body[end:].lstrip('\n').rstrip() + '\n' if end < len(body) else ''
```

**Strip the artifact's H1 title** from `rest_body`. The artifact body typically begins with `# Investigation Report — ...` — we don't want to duplicate it in the comment (the comment already has its own `## 📋 rp1 Artifact: ...` header). If `body` starts with `^# ` before the first `^## `, drop everything from start-of-body up to (but not including) the first `^## ` heading.

After extraction:
- `summary_body` is the verbatim content of the Executive Summary (or fallback) section, ending in exactly one newline.
- `rest_body` is everything after that section, ending in exactly one newline (or empty string if the artifact had only one H2).
````

- [ ] **Step 2: Verify well-formed**

Run: `grep -A 2 '^### Step 3' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: shows the heading and first content line.

---

## Task 7: SKILL.md Procedure Step 4 — Assemble the projection

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 4" placeholder)

- [ ] **Step 1: Replace the Step 4 placeholder**

Find `### Step 4: Assemble the projected comment body` and replace the placeholder with:

````markdown
**Build the incomplete banner string.** If `field('status') == 'incomplete'` (case-insensitive), set:

```python
banner = "\n> ⚠️ **This artifact is marked `incomplete`.** Reviewers: the analysis below may evolve.\n"
```

Otherwise `banner = ''` (empty string, no newline).

**If `rest_body` is empty**, omit the `<details>` block entirely — emit only the summary section. This avoids an empty collapsible that looks broken.

**Render the comment body** by interpolation against the template in `references/projection-format.md`:

```python
doc_id   = fm['rp1_doc_id']
producer = fm['producer']
artifact = fm['artifact']

body_out = f"""<!-- rp1-artifact: {doc_id} -->
## 📋 rp1 Artifact: {title}

| Field | Value |
|-------|-------|
| Producer | `{producer}` |
| Artifact type | `{artifact}` |
| Issue ID | `{field('issue_id')}` |
| Status | `{field('status')}` |
| Generated | {field('date')} |
| Doc ID | `{doc_id}` |
| Source path | `{relative_path}` (gitignored, local to author) |
{banner}
### Executive Summary

{summary_body}"""

if rest_body:
    body_out += f"""
<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

{rest_body}
</details>
"""

body_out += """
---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
"""
```

**Body-size check.** If `len(body_out.encode('utf-8')) > 65536`, exit with: `Comment body exceeds GitHub's 65 KB cap (<bytes> bytes). Multi-comment chunking is not yet supported.`

**Validate the fixture contract.** When invoked on `examples/investigation-report-input.md`, this assembly **must** produce a body byte-identical to `examples/investigation-report-output.md`. Diff with:

```bash
diff <(<this skill applied to examples/investigation-report-input.md>) examples/investigation-report-output.md
```

If the diff is non-empty, the projection logic has drifted from the spec — fix it before proceeding.
````

- [ ] **Step 2: Verify**

Run: `grep -A 2 '^### Step 4' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: shows heading and first content line.

---

## Task 8: SKILL.md Procedure Step 5 — Find existing comment

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 5" placeholder)

- [ ] **Step 1: Replace the Step 5 placeholder**

Find `### Step 5: Find any existing comment for this artifact` and replace with:

````markdown
**Fetch all PR comments.**

```bash
gh api -X GET "repos/$repo_full/issues/$pr_number/comments" --paginate \
  --jq '[.[] | {id: .id, body: .body, user_login: .user.login, html_url: .html_url, updated_at: .updated_at}]'
```

This returns a JSON array. Save it to a variable.

**Grep for the marker.** The marker is `<!-- rp1-artifact: <doc_id> -->` and is **always on line 1** of any comment this skill posts:

```python
marker = f"<!-- rp1-artifact: {doc_id} -->"
matches = [c for c in all_comments if c['body'].startswith(marker)]
```

**Apply the edge-case decision table** (full text in `references/edge-cases.md`):

```python
me = subprocess.check_output(['gh', 'api', 'user', '--jq', '.login']).decode().strip()

if len(matches) == 0:
    action = 'POST'
    target_comment_id = None
    # Check the "marker dropped" case: search for ANY comment by the current user that
    # was posted by this skill (footer string), as a soft idempotency hint.
    soft_match_footer = "Posted by `persist-rp1-artifact`"
    soft_matches = [c for c in all_comments if soft_match_footer in c['body'] and c['user_login'] == me]
    if soft_matches:
        print(f"WARNING: found {len(soft_matches)} prior persist-rp1-artifact comment(s) but no marker for doc_id {doc_id}. Idempotency is broken — a new comment will be posted, orphaning the old one(s).", file=sys.stderr)

elif len(matches) == 1:
    only = matches[0]
    if only['user_login'] == me:
        action = 'PATCH'
        target_comment_id = only['id']
        # mtime vs updated_at check (warn, allow)
        local_mtime = os.path.getmtime(path)
        comment_dt = isoparse(only['updated_at']).timestamp()
        if local_mtime < comment_dt and not force:
            print(f"WARNING: local artifact is older than the existing comment ({only['html_url']}). Continuing — pass --force to suppress this warning.", file=sys.stderr)
    else:
        if not force:
            sys.exit(f"Comment is owned by @{only['user_login']} ({only['html_url']}). Pass --force to overwrite, or coordinate with them.")
        action = 'PATCH'
        target_comment_id = only['id']

else:  # 2 or more matches
    urls = '\n  '.join(c['html_url'] for c in matches)
    sys.exit(f"Found {len(matches)} comments matching doc_id {doc_id}:\n  {urls}\nDelete duplicates manually, then re-run.")
```

Note: `isoparse` comes from `python-dateutil`. If unavailable, parse the ISO 8601 string with `datetime.datetime.fromisoformat()` after stripping the trailing `Z`:

```python
from datetime import datetime
comment_dt = datetime.fromisoformat(only['updated_at'].rstrip('Z')).timestamp()
```

After this step you have `action` ∈ {`POST`, `PATCH`} and `target_comment_id` (None for POST, comment id for PATCH).
````

- [ ] **Step 2: Verify**

Run: `grep -A 2 '^### Step 5' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: heading + first content line.

---

## Task 9: SKILL.md Procedure Step 6 — Post or update (incl. `--dry-run`)

**Files:**
- Modify: `~/.claude/skills/persist-rp1-artifact/SKILL.md` (replace "Step 6" placeholder)

- [ ] **Step 1: Replace the Step 6 placeholder**

Find `### Step 6: Post or update (honoring \`--dry-run\`)` and replace with:

````markdown
**If `--dry-run`** is set, emit the diagnostic block to stderr and the body to stdout, then exit 0:

```python
if dry_run:
    matched_url = matches[0]['html_url'] if matches else 'none'
    size_bytes = len(body_out.encode('utf-8'))
    sys.stderr.write(f"""=== persist-rp1-artifact (dry run) ===
Artifact: {relative_path}
Doc ID:   {doc_id}
PR:       #{pr_number} ({pr_state}, base: {base_ref}, head: {head_ref})
Size:     {size_bytes} / 65536 bytes
Action:   would {action} (matched comment: {matched_url})

--- projected comment body ---
""")
    sys.stdout.write(body_out)
    sys.stderr.write("--- end body ---\n")
    sys.exit(0)
```

Stdout receives only the projected body (so `--dry-run | diff expected.md -` works); stderr receives the diagnostic header.

**Real run — POST:**

```bash
echo "$body_out" > /tmp/persist-rp1-artifact-body.md
gh api -X POST "repos/$repo_full/issues/$pr_number/comments" \
  -F body=@/tmp/persist-rp1-artifact-body.md \
  --jq '.html_url'
```

The `-F body=@<file>` form (capital `F`, raw-field) is necessary because (a) the body can exceed command-line length limits for large artifacts and (b) markdown content containing tokens like `true`, `false`, or numeric strings must be preserved literally, not type-inferred as `-f`/`--field` would do.

**Real run — PATCH:**

```bash
gh api -X PATCH "repos/$repo_full/issues/comments/$target_comment_id" \
  -F body=@/tmp/persist-rp1-artifact-body.md \
  --jq '.html_url'
```

Note the URL path difference: `POST` goes to `/issues/{pr_number}/comments` (creates on the issue/PR), but `PATCH` goes to `/issues/comments/{comment_id}` (no PR number — comment IDs are unique across the repo).

**Final output to the user.**

```
✓ <Posted|Updated> rp1 artifact on PR #<pr_number>
  Artifact: <artifact-type> / <issue-id> (doc_id <doc-id>)
  Comment:  <html_url>
  Size:     <kb-formatted> / 65 KB cap
```

Where `<Posted|Updated>` matches the action, and `<kb-formatted>` shows like `24.8 KB`.

**Cleanup.** `rm -f /tmp/persist-rp1-artifact-body.md` (always, even on failure).
````

- [ ] **Step 2: Verify**

Run: `grep -A 2 '^### Step 6' ~/.claude/skills/persist-rp1-artifact/SKILL.md | head -5`
Expected: heading + first content line.

- [ ] **Step 3: Verify SKILL.md is now fully filled in**

Run: `grep -c '_Filled in by Task' ~/.claude/skills/persist-rp1-artifact/SKILL.md`
Expected: `0` — no placeholders remain.

---

## Task 10: Edge-case fixtures

**Files:**
- Create: `~/.claude/skills/persist-rp1-artifact/examples/no-doc-id-input.md`
- Create: `~/.claude/skills/persist-rp1-artifact/examples/no-summary-input.md`
- Create: `~/.claude/skills/persist-rp1-artifact/examples/no-summary-output.md`
- Create: `~/.claude/skills/persist-rp1-artifact/examples/incomplete-status-input.md`
- Create: `~/.claude/skills/persist-rp1-artifact/examples/incomplete-status-output.md`

Each fixture proves one edge case in the procedure.

- [ ] **Step 1: Write `no-doc-id-input.md`** (proves the refusal path)

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

This artifact intentionally omits `rp1_doc_id` to prove the skill refuses to publish.
```

**Expected behavior:** when applied to this fixture, the skill exits non-zero with: `Artifact is missing rp1_doc_id. Regenerate via the producing rp1 skill.`

- [ ] **Step 2: Write `no-summary-input.md`** (proves the fallback path)

```markdown
---
producer: feature-architect
artifact: feature-design
issue_id: no-summary-test
status: complete
date: 2026-05-19
rp1_doc_id: 11111111-2222-3333-4444-555555555555
---

# Feature Design — No Summary Test

## Background

This artifact has no Executive Summary, Summary, Overview, or TL;DR heading. The skill must fall back to the first H2 ("Background") and emit a warning to stderr.

## Proposed Design

Body of the design section.
```

- [ ] **Step 3: Write `no-summary-output.md`** (expected projection from the above)

```markdown
<!-- rp1-artifact: 11111111-2222-3333-4444-555555555555 -->
## 📋 rp1 Artifact: Feature Design — no-summary-test

| Field | Value |
|-------|-------|
| Producer | `feature-architect` |
| Artifact type | `feature-design` |
| Issue ID | `no-summary-test` |
| Status | `complete` |
| Generated | 2026-05-19 |
| Doc ID | `11111111-2222-3333-4444-555555555555` |
| Source path | `examples/no-summary-input.md` (gitignored, local to author) |

### Executive Summary

This artifact has no Executive Summary, Summary, Overview, or TL;DR heading. The skill must fall back to the first H2 ("Background") and emit a warning to stderr.

<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

## Proposed Design

Body of the design section.

</details>

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
```

Note: the "### Executive Summary" header is **always** that string in the projection — the fallback only changes *which body section is captured*, not the header label.

- [ ] **Step 4: Write `incomplete-status-input.md`** (proves the banner)

```markdown
---
producer: bug-investigator
artifact: investigation-report
issue_id: incomplete-status-test
status: incomplete
date: 2026-05-19
rp1_doc_id: 22222222-3333-4444-5555-666666666666
---

# Investigation — Incomplete

## Executive Summary

Initial findings only; investigation is ongoing.
```

- [ ] **Step 5: Write `incomplete-status-output.md`**

```markdown
<!-- rp1-artifact: 22222222-3333-4444-5555-666666666666 -->
## 📋 rp1 Artifact: Investigation Report — incomplete-status-test

| Field | Value |
|-------|-------|
| Producer | `bug-investigator` |
| Artifact type | `investigation-report` |
| Issue ID | `incomplete-status-test` |
| Status | `incomplete` |
| Generated | 2026-05-19 |
| Doc ID | `22222222-3333-4444-5555-666666666666` |
| Source path | `examples/incomplete-status-input.md` (gitignored, local to author) |

> ⚠️ **This artifact is marked `incomplete`.** Reviewers: the analysis below may evolve.

### Executive Summary

Initial findings only; investigation is ongoing.

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
```

Note: no `<details>` block — the artifact has only the summary section, no rest_body.

- [ ] **Step 6: Verify all five files exist and are non-empty**

Run: `ls -la ~/.claude/skills/persist-rp1-artifact/examples/`
Expected: 7 files total (2 from Task 2, 5 from this task).

Run: `wc -l ~/.claude/skills/persist-rp1-artifact/examples/*.md`
Expected: each file has at least 10 lines, except possibly `no-doc-id-input.md` which can be ~12.

---

## Task 11: Dry-run self-test against PR #564 artifact

**Files:**
- No files modified — this is an integration validation against real data.

The Node-20 investigation report is committed in `pdf-service` PR #564 at git ref `0a5d58fc`. We don't have it locally (the gitignore would have prevented it from showing up in `.rp1/work/` in this workspace anyway), so we fetch the file content from git and run the dry-run procedure against it.

- [ ] **Step 1: Extract the artifact to a scratch path**

```bash
cd /Users/edruder/conductor/workspaces/pdf-service/surat
mkdir -p /tmp/persist-rp1-artifact-selftest
git cat-file -p 0a5d58fc:.rp1/work/issues/node-20-upgrade/investigation_report.md \
  > /tmp/persist-rp1-artifact-selftest/investigation_report.md
wc -l /tmp/persist-rp1-artifact-selftest/investigation_report.md
```

Expected: ~397 lines.

- [ ] **Step 2: Mentally execute the SKILL.md procedure with `--dry-run`**

This task is **the agent reading `SKILL.md` end-to-end and following the procedure** against `/tmp/persist-rp1-artifact-selftest/investigation_report.md`, with `--dry-run` semantics (no actual POST/PATCH).

The agent should:

1. Read SKILL.md fully (including the three reference docs).
2. Apply Steps 1–5 of the procedure.
3. Emit the projected body to stdout, diagnostics to stderr.

- [ ] **Step 3: Validate the projection**

The expected output for this artifact should:

- Start with `<!-- rp1-artifact: 9f27673c-7480-4770-8aaa-c390669cffb9 -->` on line 1.
- Have title `📋 rp1 Artifact: Investigation Report — node-20-upgrade`.
- Have a header table with all six frontmatter fields populated.
- Include the full Executive Summary section verbatim (multiple paragraphs, including the "Three things most likely to go wrong" enumeration).
- Have a `<details>` block containing sections 2 through 9 of the artifact.
- End with the `🤖 Posted by...` footer.
- Total size between 20 KB and 30 KB.

- [ ] **Step 4: Verify the size is under cap**

```bash
# After projection
test "$body_size" -lt 65536 || echo "FAIL: body exceeds 65 KB cap"
```

Expected: passes (no FAIL output).

- [ ] **Step 5: Clean up the scratch file**

```bash
rm -rf /tmp/persist-rp1-artifact-selftest
```

---

## Task 12: Manual integration test on a throwaway PR

**Files:**
- No files modified — this is a real, network-touching end-to-end test.

We need to validate against GitHub for real. Use a throwaway branch + draft PR on a personal scratch repo (not `anvilco/pdf-service`).

- [ ] **Step 1: Pick or create a scratch repo with a throwaway PR**

If you have a personal sandbox repo with at least one open (or easily-openable) PR, use that. Otherwise:

```bash
# In a tmp dir:
mkdir /tmp/persist-rp1-scratch && cd /tmp/persist-rp1-scratch
git init && echo "scratch" > README.md && git add . && git commit -m "init"
gh repo create --private --source . --remote origin --push
git checkout -b throwaway/persist-rp1-test
echo "change" >> README.md && git commit -am "change"
git push -u origin throwaway/persist-rp1-test
gh pr create --draft --title "throwaway: persist-rp1-artifact test" --body "scratch"
```

Save the PR number; call it `$TESTPR`.

- [ ] **Step 2: Create a minimal rp1 artifact in `/tmp/`**

```bash
mkdir -p /tmp/persist-rp1-scratch/.rp1/work/issues/throwaway-test
cat > /tmp/persist-rp1-scratch/.rp1/work/issues/throwaway-test/investigation_report.md <<'EOF'
---
producer: bug-investigator
artifact: investigation-report
issue_id: throwaway-test
status: complete
date: 2026-05-19
rp1_doc_id: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
---

# Throwaway Test

## Executive Summary

A minimal artifact used to validate the `persist-rp1-artifact` skill end-to-end on a real PR.

## Details

Body content for the `<details>` collapse.
EOF
```

- [ ] **Step 3: Run with `--dry-run` first**

```bash
cd /tmp/persist-rp1-scratch
# Invoke the skill:
/persist-rp1-artifact .rp1/work/issues/throwaway-test/investigation_report.md --dry-run
```

Expected: stderr shows the diagnostic block (`would POST`, matched comment: none, size <2 KB); stdout shows the projected body.

- [ ] **Step 4: Run for real**

```bash
/persist-rp1-artifact .rp1/work/issues/throwaway-test/investigation_report.md
```

Expected: outputs `✓ Posted rp1 artifact on PR #$TESTPR` with the comment URL. Visit the URL; verify:

- HTML comment `<!-- rp1-artifact: aaaaaaaa-... -->` is present (view source or "Quote reply" to see raw markdown).
- Header table renders correctly.
- Executive Summary appears at top.
- `<details>` block collapses by default and expands on click.
- Footer shows the `🤖 Posted by...` line.

- [ ] **Step 5: Edit the artifact and re-run (update-in-place test)**

```bash
# Change one word in the Executive Summary
sed -i.bak 's/minimal artifact/sample artifact/' \
  /tmp/persist-rp1-scratch/.rp1/work/issues/throwaway-test/investigation_report.md
/persist-rp1-artifact .rp1/work/issues/throwaway-test/investigation_report.md
```

Expected: outputs `✓ Updated rp1 artifact on PR #$TESTPR` (note "Updated", not "Posted") with the same comment URL as before. Visit GitHub; verify "edited" badge appears next to the timestamp.

- [ ] **Step 6: Test the broken-marker path**

In the GitHub UI, edit the comment manually and remove the `<!-- rp1-artifact: ... -->` line. Save.

Re-run:

```bash
/persist-rp1-artifact .rp1/work/issues/throwaway-test/investigation_report.md
```

Expected:
- A WARNING line on stderr: `WARNING: found 1 prior persist-rp1-artifact comment(s) but no marker for doc_id ...`.
- A *new* comment is posted (the old, marker-less one stays in place orphaned).

- [ ] **Step 7: Cleanup**

```bash
gh pr close $TESTPR
# Optionally:
gh repo delete <owner>/persist-rp1-scratch --yes
rm -rf /tmp/persist-rp1-scratch
```

---

## Final state

After Task 12, the skill is:

- Installed at `~/.claude/skills/persist-rp1-artifact/` with `SKILL.md`, three references, six example fixtures, and the spec.
- Verified deterministic against the primary investigation-report fixture.
- Verified end-to-end against a real GitHub PR (post, update-in-place, broken-marker fallback).
- Documented in `DESIGN.md` for future contributors and as the basis for a v2 / upstream contribution to `rp1-dev`.

The user can now run `/persist-rp1-artifact` against their real `.rp1/work/...` artifacts on `pdf-service` PRs.

---

## Self-review (post-write)

**1. Spec coverage:**

| Spec section | Implementing task(s) |
|---|---|
| Problem statement | (informational only — no task) |
| Non-goals | Documented in PLAN intro and SKILL.md "When NOT to invoke" |
| Lifecycle (B) | Task 4 (no file modification), Task 1 references |
| Invocation `/persist-rp1-artifact <path> [pr-number]` | Task 4 (resolve inputs) |
| Skill location `~/.claude/skills/persist-rp1-artifact/` | All tasks |
| Projection format | Task 1 (reference), Task 2 (fixture), Task 7 (assembly) |
| Re-run / edge cases | Task 1 (reference), Task 8 (apply) |
| `--dry-run` opt-in | Task 9 (Step 1 of new content) |
| Error handling table | Task 1 (`edge-cases.md`), enforced across Tasks 4–9 |
| Testing layer 1 (fixtures) | Tasks 2, 10 |
| Testing layer 2 (dry-run) | Tasks 9, 11 |
| Manual integration test | Task 12 |
| Retrofit recipe | Spec §10 (documentation only, no task) |

**2. Placeholder scan:** searched the plan for "TBD", "TODO", "later", "Similar to Task" — none found. Each task's code blocks are concrete (literal markdown content or literal Python/bash). ✓

**3. Type consistency:** function and variable names used across tasks (`fm`, `summary_body`, `rest_body`, `body_out`, `doc_id`, `relative_path`, `action`, `target_comment_id`, `matches`, `me`) appear consistently. The frontmatter dict is always `fm` and always `str -> str`. ✓

No issues found.
