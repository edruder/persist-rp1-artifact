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
