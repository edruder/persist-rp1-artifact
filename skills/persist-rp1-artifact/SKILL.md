---
name: persist-rp1-artifact
description: Use when the user has an rp1 artifact under .rp1/work/ (e.g. investigation report, design doc, audit) and wants to publish it as a PR comment instead of committing the file to the repo. Idempotent — re-runs update the same comment in place via an HTML doc-id marker. Invoke when the user says "post rp1 artifact to PR", "publish investigation report as PR comment", "persist rp1 artifact", or runs `/persist-rp1-artifact`.
---

# persist-rp1-artifact

Publish an rp1 artifact (frontmatter-bearing markdown under `.rp1/work/`) as a PR comment without committing the artifact file to the repo. Re-running updates the same comment in place.

**The artifact file is never modified by this skill** — it is read-only on the local side, write-only on the GitHub side.

> ### ⚠️ Always `--dry-run` first on a real PR
>
> The skill writes to a real GitHub PR comment by default. Before invoking against a PR you care about (especially one with active reviewers), always do a dry-run first:
>
> ```
> /persist-rp1-artifact <path> [pr-number] --dry-run
> ```
>
> Dry-run runs every step of the procedure except the GitHub write, prints the projected comment body to stdout and a diagnostic block to stderr (telling you whether the next run would `POST` or `PATCH`), and exits 0. Once the projection looks right, re-run without `--dry-run` to actually post. This is the v1 safety net while the projection logic is stabilizing.

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

### Step 2: Load + parse the artifact

**Split frontmatter from body.** Use Python 3 (always available on macOS/Linux dev machines):

```bash
python3 - <<'PY' "$path"
import sys, re
with open(sys.argv[1]) as f:
    txt = f.read()
m = re.match(r'^---\n(.*?)\n---\n(.*)$', txt, re.DOTALL)
if not m:
    sys.exit("ERROR: artifact has no YAML frontmatter block.")
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

### Step 3: Extract the top-summary section

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
    summary_body = body[start:end].lstrip('\n').rstrip() + '\n'
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
    summary_body = body[start:end].lstrip('\n').rstrip() + '\n'
    rest_body = body[end:].lstrip('\n').rstrip() + '\n' if end < len(body) else ''
```

**Strip the artifact's H1 title** from `rest_body`. The artifact body typically begins with `# Investigation Report — ...` — we don't want to duplicate it in the comment (the comment already has its own `## 📋 rp1 Artifact: ...` header). If `body` starts with `^# ` before the first `^## `, drop everything from start-of-body up to (but not including) the first `^## ` heading.

After extraction:

- `summary_body` is the verbatim content of the Executive Summary (or fallback) section, ending in exactly one newline.
- `rest_body` is everything after that section, ending in exactly one newline (or empty string if the artifact had only one H2).

### Step 4: Assemble the projected comment body

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
diff <(persist-rp1-artifact-projection examples/investigation-report-input.md) examples/investigation-report-output.md
```

If the diff is non-empty, the projection logic has drifted from the spec — fix it before proceeding.

### Step 5: Find any existing comment for this artifact

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
    # Soft-detection: search for any comment by the current user containing the skill's
    # footer string. If present without a matching marker, warn about broken idempotency.
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
        from datetime import datetime
        local_mtime = os.path.getmtime(path)
        comment_dt = datetime.fromisoformat(only['updated_at'].rstrip('Z')).timestamp()
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

After this step you have `action` ∈ {`POST`, `PATCH`} and `target_comment_id` (None for POST, comment id for PATCH).

### Step 6: Post or update (honoring `--dry-run`)

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

## Spec

See `DESIGN.md` for the spec this skill implements.
