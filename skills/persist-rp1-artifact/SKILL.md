---
name: persist-rp1-artifact
description: Use when the user has an rp1 artifact under .rp1/work/ (e.g. investigation report, design doc, audit) and wants to publish it as a PR or issue comment instead of committing the file to the repo. Idempotent — re-runs update the same comment in place via an HTML marker. Invoke when the user says "post rp1 artifact to PR", "publish investigation report as a PR or issue comment", "persist rp1 artifact", or runs `/persist-rp1-artifact`.
---

# persist-rp1-artifact

Publish an rp1 artifact (markdown under `.rp1/work/`; frontmatter optional) as a PR or issue comment without committing the artifact file to the repo. Re-running updates the same comment in place.

**The artifact file is never modified by this skill** — it is read-only on the local side, write-only on the GitHub side.

> ### ⚠️ Always `--dry-run` first on a real PR or issue
>
> The skill writes to a real GitHub PR/issue comment by default. Before invoking against a real PR/issue you care about (especially one with active reviewers), always do a dry-run first:
>
> ```
> /persist-rp1-artifact <path> [target] --dry-run
> ```
>
> Dry-run runs every step of the procedure except the GitHub write, prints the projected comment body to stdout and a diagnostic block to stderr (telling you whether the next run would `POST` or `PATCH`), and exits 0. Once the projection looks right, re-run without `--dry-run` to actually post. This is the v1 safety net while the projection logic is stabilizing.

## When to invoke

- User explicitly runs `/persist-rp1-artifact <path> [target]`.
- User has just produced an rp1 artifact and asks how to share it on a PR or issue without committing it.
- User asks to "summarize an rp1 investigation report into a PR or issue comment."

## When NOT to invoke

- The file is not an rp1 work artifact at all (not under `.rp1/work/` and unrelated to rp1). This skill publishes rp1 artifacts; frontmatter is optional, but the file should be an rp1 work product.
- The user wants to keep the artifact in the repo. This skill is for the *don't commit it* case.

## Inputs

| Arg | Required | Default |
|---|---|---|
| `<path>` | yes | — |
| `[target]` | no | current branch's open PR (`gh pr view --json number -q .number`). May be a PR or issue **number**, or a full GitHub PR/issue **URL**. |
| `--dry-run` | no | false (real post). First-time runs on real targets should pass `--dry-run` first. |
| `--force` | no | false. See `references/edge-cases.md`. |

## References (read these — they encode the spec)

- `references/artifact-frontmatter.md` — required/optional frontmatter fields, parsing implementation, title derivation rule.
- `references/projection-format.md` — exact comment template and fill-in rules. **The output is byte-deterministic.**
- `references/edge-cases.md` — re-run dedup logic, error table, `--force`/`--dry-run` semantics.

## Fixtures (the contract)

The `examples/*-input.md` ↔ `examples/*-output.md` pairs are byte-exact golden tests for
`scripts/project.py`, run by `tests/test_project.py`. After any change to the projection:

    python3 -m unittest discover -s skills/persist-rp1-artifact/tests

A failing golden test means the projection drifted from the contract — fix the script, not
the fixtures.

## Procedure

This procedure is executed by the main agent using `Read`, `Bash` (for `gh`), and `Grep`. Each step has explicit failure modes — refer to `references/edge-cases.md`.

### Step 1: Resolve inputs

**Skill directory.** Set `SKILL_DIR` to this skill's directory (the folder containing this `SKILL.md`). The script-calling snippets in Steps 1–2 reference `$SKILL_DIR` and `$SKILL_DIR/scripts`, so compute it once here.

**Arguments parsing.** The skill is invoked as `/persist-rp1-artifact <path> [target] [--dry-run] [--force]`. Parse positional args first, then flags. Treat anything starting with `--` as a flag. The second positional, if present, becomes `target`.

**Pre-flight checks** (in order; fail fast):

1. `command -v gh >/dev/null` — if absent, exit with: `gh CLI not found. Install: https://cli.github.com`.
2. `gh auth status >/dev/null 2>&1` — if non-zero, exit with: `gh is not authenticated. Run: gh auth login`.
3. `test -f "$path"` — if absent, exit with: `Artifact not found: $(realpath "$path" 2>/dev/null || echo "$path")`.

**Path warning.** Compute the path's prefix:

```bash
case "$(realpath "$path")" in
  */.rp1/work/*) ;;  # OK
  *) echo "WARNING: $path is outside .rp1/work/. The path-based idempotency key still works; this is informational." >&2 ;;
esac
```

This is a warning only — continue.

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
  parsed="$(python3 "$SKILL_DIR/scripts/parse_target.py" "$target" --current-repo "$repo_full" 2>&1)" \
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

`$SKILL_DIR` is this skill's directory (the folder containing `SKILL.md`), computed at the top of this step.

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
doc_key="$(python3 - "$SKILL_DIR/scripts" "$path" "$relative_path" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import project
fm, _ = project.split_frontmatter(open(sys.argv[2], encoding="utf-8").read())
print(project.marker_key(fm, sys.argv[3]))
PY
)"
```

`body_out` is the exact comment body; `doc_key` is the idempotency key (the `rp1_doc_id`,
or `path:<relative_path>` when absent). The scripts path and file paths are passed as
heredoc arguments (outside the quoted `<<'PY'` delimiter) so the shell expands them.
Warnings from the projection (summary-ladder rung, etc.) are printed to stderr for the
user to see.

The byte-exact contract is enforced by `tests/test_project.py` (run
`python3 -m unittest discover -s skills/persist-rp1-artifact/tests`), not by manual walkthrough.

### Step 3: Find any existing comment for this artifact

**Fetch all comments on the target.** The endpoint is the same for PRs and issues:

```bash
gh api -X GET "repos/$repo_full/issues/$number/comments" --paginate \
  --jq '[.[] | {id: .id, body: .body, user_login: .user.login, html_url: .html_url, updated_at: .updated_at}]'
```

This returns a JSON array. Save it to a variable.

**Grep for the marker.** The marker is `<!-- rp1-artifact: <doc_key> -->` and is **always on line 1** of any comment this skill posts:

```python
marker = f"<!-- rp1-artifact: {doc_key} -->"
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
        print(f"WARNING: found {len(soft_matches)} prior persist-rp1-artifact comment(s) but no marker for doc_key {doc_key}. Idempotency is broken — a new comment will be posted, orphaning the old one(s).", file=sys.stderr)

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
    sys.exit(f"Found {len(matches)} comments matching doc_key {doc_key}:\n  {urls}\nDelete duplicates manually, then re-run.")
```

After this step you have `action` ∈ {`POST`, `PATCH`} and `target_comment_id` (None for POST, comment id for PATCH).

### Step 4: Post or update (honoring `--dry-run`)

**If `--dry-run`** is set, emit the diagnostic block to stderr and the body to stdout, then exit 0:

```python
if dry_run:
    matched_url = matches[0]['html_url'] if matches else 'none'
    size_bytes = len(body_out.encode('utf-8'))
    target_line = f"#{number} ({state}, base: {base_ref}, head: {head_ref})" if kind == "pr" else f"#{number} ({state}, issue)"
    sys.stderr.write(f"""=== persist-rp1-artifact (dry run) ===
Artifact: {relative_path}
Doc key:  {doc_key}
Target:   {target_line}
Size:     {size_bytes} / 65536 bytes
Action:   would {action} (matched comment: {matched_url})

--- projected comment body ---
""")
    sys.stdout.write(body_out)
    sys.stderr.write("--- end body ---\n")
    sys.exit(0)
```

Stdout receives only the projected body (so `--dry-run | diff expected.md -` works); stderr receives the diagnostic header.

**Write the body to a temp file** (used by whichever of POST/PATCH runs). `printf '%s\n'` restores the single trailing newline that `$(...)` strips from `body_out`, so the posted bytes match project.py's output and the golden fixtures:

```bash
printf '%s\n' "$body_out" > /tmp/persist-rp1-artifact-body.md
```

**Real run — POST:**

```bash
gh api -X POST "repos/$repo_full/issues/$number/comments" \
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

Note the URL path difference: `POST` goes to `/issues/{number}/comments` (creates on the PR or issue), but `PATCH` goes to `/issues/comments/{comment_id}` (no number — comment IDs are unique across the repo).

**Final output to the user.**

```
✓ <Posted|Updated> rp1 artifact on <PR|issue> #<number>
  Artifact: <artifact-type> / <issue-id> (doc_key <doc-key>)
  Comment:  <html_url>
  Size:     <kb-formatted> / 65 KB cap
```

Where `<Posted|Updated>` matches the action, `<PR|issue>` matches `kind`, and `<kb-formatted>` shows like `24.8 KB`.

**Cleanup.** `rm -f /tmp/persist-rp1-artifact-body.md` (always, even on failure).

## Spec

See [`docs/superpowers/specs/2026-05-28-persist-rp1-artifact-generality-design.md`](../../docs/superpowers/specs/2026-05-28-persist-rp1-artifact-generality-design.md) for the spec this skill implements. (`DESIGN.md` is the superseded v1 design.)
