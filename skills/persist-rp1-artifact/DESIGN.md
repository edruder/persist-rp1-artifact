# Design: `persist-rp1-artifact` skill

**Date:** 2026-05-19
**Author:** Ed Ruder
**Status:** Approved, ready for implementation plan
**Skill location:** `~/.claude/skills/persist-rp1-artifact/`

## Problem

rp1 agents produce structured markdown artifacts under `.rp1/work/...` (investigation reports, design docs, audits, etc.). These artifacts are valuable context **during PR review** — they capture the reasoning behind a change — but their value decays after merge: the code becomes the source of truth and the report rots.

The current workarounds are both bad:

1. **Commit the artifact to the repo.** Bloats `git log`, file tree, and search with intermediate analysis that has no long-term home. Already happened on PR #564 (`.rp1/work/issues/node-20-upgrade/investigation_report.md`, 397 lines).
2. **Discard the artifact.** Reviewers lose the reasoning, future maintainers can't reconstruct the "why."

**Goal:** publish rp1 artifacts as PR comments so reviewers see them in context, while keeping `.rp1/work/` gitignored.

## Non-goals

- Multi-comment chunking for artifacts >65 KB (defer until a real artifact hits the cap)
- Stacked-PR fan-out (one PR per invocation)
- Hydration: reading the comment back into a local file
- Type-aware projection (different layout per `artifact:` type — v1 is one shape)
- Retrofit helper for already-committed artifacts (handled manually via a documented recipe)

## Key decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **Artifact lifecycle** | Comment = projection. Local file stays on disk, `.rp1/work/` remains gitignored. | `.gitignore` already enforces this; rp1's downstream skills (e.g. `/build` consuming `/code-investigate` output) need local artifacts to remain readable. |
| **Invocation** | Manual: `/persist-rp1-artifact <path> [pr-number]`. PR defaults to current branch's open PR. | Explicit and predictable. Hooks on `git push` were considered but rejected — too easy to be annoying, hard to make idempotent across all push scenarios. |
| **Skill location** | Personal user-level at `~/.claude/skills/persist-rp1-artifact/`. | Prove value first; if useful to the team, consider standalone plugin; if broadly useful, consider upstreaming to `rp1-dev`. |
| **Projection** | Full content with deterministic top-summary + `<details>` body fold. No LLM in the projection path. | Lossless, auditable, easy to unit-test. The artifact's own Executive Summary section is already a human-written summary — re-summarizing with an LLM would just add variance. |
| **Re-run semantics** | Update-in-place by `rp1_doc_id` HTML marker. Four explicit edge-case rules (see §6). | Matches `pr-comment-deduplicator`'s pattern; `rp1_doc_id` is a UUID so collisions are negligible. |
| **`--dry-run`** | Opt-in flag (default = real post). | Standard CLI convention. First-time users should pass `--dry-run` first; documented prominently. |

## Architecture

One skill, no subagents. The work is mechanical (read file → transform markdown → call GitHub API), not generative.

```
~/.claude/skills/persist-rp1-artifact/
├── SKILL.md                              # the actual skill instructions (frontmatter + procedure)
├── DESIGN.md                             # this spec
├── references/
│   ├── projection-format.md              # the exact top-summary + <details> shape, with examples
│   ├── edge-cases.md                     # the four re-run edge cases and how to handle them
│   └── artifact-frontmatter.md           # what we assume about rp1 artifact frontmatter
└── examples/
    ├── investigation-report-input.md     # truncated copy of the Node-20 report as a fixture
    └── investigation-report-output.md    # what the skill should produce from it
```

**External dependencies:** `gh` CLI (already required by rp1's PR-side skills), nothing else.

## Procedure

The main agent invokes the skill, then follows the SKILL.md procedure directly:

1. **Resolve inputs.** Parse `<path>` (required) and `[pr-number]` (optional, default = current branch's open PR via `gh pr view --json number -q .number`). Fail fast if `gh` isn't installed/authed or no PR found.
2. **Load + parse artifact.** Read the file, split YAML frontmatter from body, validate required fields (`producer`, `artifact`, `rp1_doc_id`). Refuse to publish if `rp1_doc_id` is missing.
3. **Extract top-summary.** Pull the first H2 section whose heading matches `^##\s+(\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$` (case-insensitive). If none found, fall back to the first H2 in the document and warn.
4. **Project to comment markdown.** Assemble per the format in §5.
5. **Find existing comment.** `gh api repos/{owner}/{repo}/issues/{pr-number}/comments --paginate`, grep for `<!-- rp1-artifact: <doc_id> -->`. Apply the four edge-case rules.
6. **Post or update.** `gh api POST/PATCH` accordingly. Print the comment URL and action.

The local artifact file is **never modified** by this skill. Read-only on the artifact side; write-only on the GitHub side.

## Projection format

Exact output shape — two implementations should produce byte-identical comments:

```markdown
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
| Source path | `.rp1/work/issues/node-20-upgrade/investigation_report.md` (gitignored, local to author) |

### Executive Summary

> _The first H2 section of the artifact body, verbatim. Markdown preserved._

<details>
<summary><strong>Full artifact</strong> (click to expand)</summary>

_Everything after the Executive Summary section, verbatim._

</details>

---
<sub>🤖 Posted by `persist-rp1-artifact`. Re-run the skill to update this comment in place. Local artifact is gitignored and may be edited by `rp1` agents.</sub>
```

**Three deterministic rules:**

1. The HTML marker `<!-- rp1-artifact: <doc_id> -->` is **always line 1**, no leading whitespace.
2. Missing frontmatter fields render as `—` (em dash), not empty.
3. Body content is **never re-paraphrased or LLM-touched**. Pure markdown slicing — a typo in the artifact stays a typo in the comment.

The title in `## 📋 rp1 Artifact: …` is derived from `artifact` + `issue_id`:
- `investigation-report` + `node-20-upgrade` → `Investigation Report — node-20-upgrade`
- `feature-design` + `arcade-collab-v2` → `Feature Design — arcade-collab-v2`

## Re-run semantics (edge cases)

| Existing comments matching marker | Author of existing comment | Behavior |
|---|---|---|
| 0 | n/a | POST new comment. |
| 1 | Current `gh` user | PATCH the existing comment. GitHub's "edited" badge surfaces the change to reviewers. |
| 1 | Different user | Refuse unless `--force`. Print whose comment it is and ask the user to coordinate. |
| 2+ | any | Refuse. Print all matching comment URLs. Ask user to manually delete duplicates. |

**Marker dropped manually** (someone edited the comment and removed the HTML marker): the skill won't find it, will POST a new comment, and warn the user that idempotency was broken for this artifact.

## Error handling

Principle: **fail loud, never destructive, never silent.**

| Failure | Behavior |
|---|---|
| `gh` not installed | Exit, link to cli.github.com |
| `gh` not authenticated | Exit, suggest `gh auth login` |
| Path doesn't exist / isn't a file | Exit, print resolved absolute path |
| Path not under `.rp1/work/` | Warn, continue (allows non-rp1 testing). Idempotency will not work without `rp1_doc_id` |
| Frontmatter missing or unparseable | Exit, name the failing key |
| `rp1_doc_id` absent | Refuse to publish (no idempotency = duplicate risk) |
| No PR for branch + no `pr-number` arg | Exit, ask user to push + open PR, or pass `pr-number` |
| PR closed or merged | Warn, allow only with `--force` |
| Comment body > 65 KB | Refuse. Print size and cap. (Multi-comment chunking is v2.) |
| Network / GitHub API error | Bubble up `gh` error verbatim; local artifact unchanged; safe to re-run |
| Artifact has no recognizable summary section | Warn, fall back to first H2, continue |
| `status: incomplete` in frontmatter | Publish with a `⚠️ marked incomplete` banner above Executive Summary |
| Local artifact `mtime` older than existing comment `updated_at` | Warn, allow. Lets user roll back to a prior artifact state |

## Testing

**Layer 1: projection unit fixtures.** Plain markdown files under `examples/`:

- `investigation-report-input.md` (truncated real artifact, ~50 lines, valid frontmatter, valid exec summary) ↔ `investigation-report-output.md` (byte-exact expected comment body).
- Targeted edge-case pairs: missing `rp1_doc_id`, no Executive Summary section, frontmatter-only file, `status: incomplete`.

SKILL.md instructs: "after any projection change, manually diff each example pair." No test framework required for a personal skill. If we upstream to `rp1-dev` later, wrap in mocha.

**Layer 2: `--dry-run` flag.** Runs steps 1–5 of the procedure, prints the projected comment body to stdout + the action it *would* take (`would POST` / `would PATCH #12345`), stops before any network write. Lets the user eyeball the projection on any real artifact without touching the PR. **First-time runs on real PRs should always go through `--dry-run` first.**

**Manual integration test** (one-time, on a throwaway PR):

1. Create a draft PR on a scratch branch.
2. Run skill against a real `.rp1/work/...` artifact → verify comment appears, marker on line 1, `<details>` collapses correctly in GitHub's renderer.
3. Edit local artifact (change one word in exec summary), re-run → verify same comment updated in place, "edited" badge shown.
4. Manually delete HTML marker from comment via GitHub UI, re-run → verify new comment posted with warning printed.

## Out-of-scope follow-ups (potential v2)

- Multi-comment chunking for >65 KB artifacts (split body across `:1`, `:2`, …)
- Type-aware projection per `artifact:` field (different layout for `code-audit` vs `investigation-report`)
- Hydration: read a posted comment back into a local file (closes the loop for teammates who didn't run the rp1 skill themselves)
- Auto-discovery mode: `/persist-rp1-artifact` with no args scans `.rp1/work/` for `status: complete` artifacts and offers a checklist
- Upstream to `rp1-dev` as a real plugin skill once shape is proven

## Retrofit recipe for already-committed artifacts (e.g. PR #564)

Not automated. Manual procedure:

1. Verify `.rp1/work/...` is in `.gitignore` (it is, since `rp1:start:v0.7.1` block).
2. `git rm --cached <path>` and commit (un-tracks the file without deleting locally).
3. Force-push the branch (requires reviewer coordination).
4. Run `/persist-rp1-artifact <path>` normally to publish the comment.
