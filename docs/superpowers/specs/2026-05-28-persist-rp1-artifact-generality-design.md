# persist-rp1-artifact — generality redesign

**Date:** 2026-05-28
**Status:** proposed
**Supersedes:** the frontmatter contract in `skills/persist-rp1-artifact/DESIGN.md` and `references/artifact-frontmatter.md` (v1)

## Problem

The skill was built and validated against one artifact shape — the "rich" investigation
report that produced the comment on `anvilco/pdf-service#564`. That artifact carried
`rp1_doc_id`, `artifact`, `issue_id`, `status`, `date`. The skill made those fields
*required* and hard-fails without them.

A survey of real rp1 artifacts on this machine (across pdf-service, pdf-signer, anvil,
usage-meter, bannans.org) shows that shape is the exception, not the rule:

| Shape | `rp1_doc_id` | `artifact`/`issue_id`/`status`/`date` | frontmatter | H1 |
|---|---|---|---|---|
| Rich (legacy, → #564) | ✅ | ✅ | yes | ✅ |
| Routing + doc_id (common) | ✅ | ❌ | routing fields | ✅ |
| Routing only (the failer) | ❌ | ❌ | routing fields | ✅ |
| None (e.g. anvil audit report) | ❌ | ❌ | absent | ✅ |

Two concrete failures motivated this redesign:

1. **Routing-only artifact rejected.** Running on
   `.rp1/work/issues/node-20-upgrade/opencv4nodejs-customallocator-investigation.md`
   (routing-only) failed the required-field checks for `rp1_doc_id` and `artifact`.
2. **Issue target rejected.** The second positional arg was a GitHub *issue* URL
   (`…/issues/576`); the skill assumes a PR number and runs `gh pr view`.

**Empirical invariant:** the `artifact`/`issue_id`/`status`/`date` fields appear on
exactly one artifact in the corpus. The **H1 heading is the only identity signal present
in 100% of artifacts** — even the one with no frontmatter at all.

## Goal

Make the skill work with **as many rp1 artifacts as possible**: any markdown file under
`.rp1/work/` (frontmatter optional), targeting either a PR or an issue, by number or URL.
Preserve byte-for-byte backward compatibility for the rich shape so re-running on #564
still updates the same comment in place.

## Design

### 1. Frontmatter: optional everywhere (decision: "any markdown under .rp1/work")

- **No required fields. No required frontmatter block.** Step 2 no longer exits when the
  leading `---` block is absent — it sets `fm = {}` and treats the whole file as body.
- When a frontmatter block *is* present, parse it to a flat `str→str` dict as today.
- Every field becomes a graceful-default lookup (`field(key)` → value or `—`).

### 2. Title derivation (precedence)

1. If `fm['artifact']` present → `TitleCase(artifact)` + (` — {issue_id}` if `issue_id`).
   *(Legacy path — keeps #564's "Investigation Report — node-20-upgrade" byte-stable.)*
2. Else if the body has a first H1 (`^# (.+)`) → use its text verbatim.
   *(The universal path — covers routing-only and no-frontmatter artifacts.)*
3. Else if `fm['producer']` → `TitleCase(producer)`.
4. Else → `TitleCase(filename-stem)`.

H1-stripping from `rest_body` (drop a leading `# …` before the first `## `) stays as in v1,
so the title is never duplicated inside the collapsible body.

### 3. Header table: render only the rows that have a value

Rows are emitted in this fixed order, but **a row whose value is absent is skipped
entirely** (no `—` placeholder). `Source path` is always computed, so the table always has
at least one row — there is no empty-table case.

| Row (if value present) | Source |
|---|---|
| Producer | `fm.producer` |
| Artifact type | `fm.artifact` → else `fm.type` |
| Issue ID | `fm.issue_id` |
| Status | `fm.status` |
| Generated | `fm.date` |
| Doc ID | `fm.rp1_doc_id` |
| Source path | `{relative_path}` (gitignored, local to author) — always shown |

The rich shape (#564) has every field, so all 7 rows render and the output stays
**byte-identical** to `investigation-report-output.md`. Leaner shapes simply emit fewer
rows: the routing-only artifact shows Producer, Artifact type (`document`), Doc ID (if
present), and Source path; a no-frontmatter doc shows only Source path.

`incomplete` banner emits only when `fm.status` lower-cases to `incomplete` (unchanged).

### 4. Idempotency key: `rp1_doc_id` when present, else repo-relative path

```
key    = fm['rp1_doc_id']  if present and non-empty
       else f"path:{relative_path}"
marker = f"<!-- rp1-artifact: {key} -->"
```

- Rich/doc_id artifacts keep the bare-UUID marker → **#564 re-runs PATCH the same comment,
  zero migration.**
- The `path:` prefix namespaces the fallback so a path can never collide with a UUID and
  the marker is self-documenting.
- The artifact file is still **never modified** (read-only invariant preserved — we do not
  inject a generated doc_id).
- Trade-off (documented, not mitigated in v2): renaming/moving a doc-id-less artifact
  orphans its old comment. Acceptable; the user can delete the stale comment.

All of Step 5's match logic keys off `body.startswith(marker)` — unchanged.

### 5. Target resolution: PR or issue, number or URL

Replace the PR-only logic in Step 1 with a resolver producing
`{owner, repo, number, kind, state, base?, head?}`:

- **Full URL** `https://github.com/{owner}/{repo}/(pull|issues)/{n}` → parse owner/repo/n;
  `kind` = `pr` if `/pull/`, `issue` if `/issues/`.
- **Bare integer** → `number = arg`; owner/repo from `gh repo view --json nameWithOwner`.
  Resolve `kind` with one probe: `gh api repos/{o}/{r}/issues/{n} --jq .pull_request` —
  non-null ⇒ PR, null ⇒ issue. (The issues API returns a `pull_request` object iff the
  number is a PR.)
- **No target arg** → current branch's open PR (unchanged v1 behavior): `kind = pr`.
- **Neither URL nor integer** → exit: `Target must be a PR/issue number or a GitHub URL.`

**State check** (the closed/merged → `--force` gate, generalized):

- `kind == pr`: `gh pr view {n} --json state,baseRefName,headRefName`. `CLOSED`/`MERGED`
  without `--force` → exit.
- `kind == issue`: `gh issue view {n} --json state`. `CLOSED` without `--force` → exit.

**Comments / POST / PATCH** already use `repos/{o}/{r}/issues/{n}/comments` and
`repos/{o}/{r}/issues/comments/{id}`, which the GitHub API treats identically for PRs and
issues — so these calls are **unchanged**. This is why the issue-576 intent was always
feasible; only the front-door check blocked it.

**Dry-run diagnostic header**: show `kind`; emit `base`/`head` only when `kind == pr`.

### 6. Summary extraction: deterministic precedence ladder

Step 3 currently exits if the body has neither a summary-named H2 nor any H2. Replace the
hard exit with a **deterministic** ladder that degrades through whatever structure the body
actually has. Determinism is non-negotiable: the skill is run by the main agent, but the
split must be reproducible and fixture-testable — **no LLM judgment on the breakpoint**, so
`--dry-run`, the real post, and every re-run produce identical bytes.

All operations run on the body *after* the leading-H1 strip. Two split shapes:

- **Section shape** (rungs 1–2): `summary_body` = the named/first H2 section's content;
  `rest_body` = everything from the *next* H2 onward.
- **Lead shape** (rungs 3–6): `summary_body` = the lead content *before* the breakpoint;
  `rest_body` = everything from the breakpoint onward.

Ladder (first match wins):

1. **Summary-named H2** — `^##\s+(?:\d+\.\s+)?(Executive Summary|Summary|Overview|TL;DR)\s*$`
   (multiline, case-insensitive). Section shape. *(primary, unchanged)*
2. **First H2** (`^## `). Section shape. Warn on stderr that no summary heading was found.
   *(unchanged fallback)*
3. **First heading of any depth** (`^#{3,6}\s` — only reachable when no H2 exists). Lead
   shape: split immediately before that heading.
4. **First thematic break** (`^(?:---|\*\*\*|___)\s*$`). Lead shape: split at the break;
   the break line itself goes into `rest_body`.
5. **First paragraph boundary** (first blank line separating the lead block from the rest).
   Lead shape: the lead paragraph(s) become `summary_body`, the remainder `rest_body`.
6. **Single block** (no heading, no break, no blank line). `summary_body` = whole body,
   `rest_body = ''` → no `<details>` collapsible.

Rungs 2–6 each emit a one-line stderr warning naming which rung fired (so a dry-run shows
*why* the split landed where it did). The existing rule — omit the `<details>` block when
`rest_body` is empty — applies to every rung.

## Backward compatibility

- `examples/investigation-report-input.md → output.md` (rich shape) must remain
  **byte-identical** after the change — it is the regression anchor. Title via the
  `artifact` field, marker via the UUID: both unchanged.
- The live #564 comment's marker is the bare UUID; re-running PATCHes it in place.

## Fixtures (the contract, expanded)

| Pair | Shape exercised |
|---|---|
| `investigation-report-{input,output}.md` | rich (regression anchor — unchanged) |
| `incomplete-status-{input,output}.md` | `status: incomplete` banner (unchanged) |
| `no-summary-{input,output}.md` | summary-heading fallback to first H2 (unchanged) |
| `no-doc-id-{input,output}.md` | **repurposed**: routing-only / no `rp1_doc_id` → `path:` marker, title from H1 |
| `routing-only-{input,output}.md` *(new)* | the opencv failer shape — routing fields, no doc_id, no `artifact` |
| `no-frontmatter-{input,output}.md` *(new)* | no frontmatter block at all (audit-report shape) |
| `lead-split-{input,output}.md` *(new)* | no-H2 ladder: a body whose summary comes from a lead paragraph (rung 5) and whose collapsed remainder begins at the breakpoint; doubles as single-block coverage (rung 6) via a second input with one block |

`no-doc-id-input.md` currently exists to "prove the skill refuses"; its body text and the
absence of an output pair both flip — it becomes a positive fixture.

## Docs to update

- `references/artifact-frontmatter.md`: rewrite to describe the **real** schema — routing
  fields (`scope`/`path_pattern`/`producer`/`type`/`description`/`strictness`) as the
  common set, the rich fields as legacy-optional, *all* optional. Kill the "Required
  fields" framing and the "absent → skill refuses" line.
- `SKILL.md`:
  - "When NOT to invoke" — remove the "lacks `rp1_doc_id` → refuse" bullet.
  - Step 1 — new target resolver (PR/issue, number/URL).
  - Step 2 — frontmatter optional; no required-field table.
  - Step 3 — title precedence + no-H2 fallback.
  - Step 4 — key precedence (`rp1_doc_id` else `path:`).
  - Inputs table — `[pr-number]` → `[target]` (PR/issue number or URL).
- `references/edge-cases.md`: add issue-target rows; document the `path:`-key
  rename-orphan trade-off.
- `README.md`: update the usage line and the "what counts as an artifact" framing.

## Non-goals (YAGNI)

- Injecting a generated `rp1_doc_id` into the artifact (breaks read-only invariant; the
  path key is sufficient).
- Multi-comment chunking for >65 KB bodies (still out of scope; existing hard error stays).
- Cross-repo URL targeting beyond what `gh` already authenticates.
