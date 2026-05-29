# Design: `persist-rp1-artifact` skill

**Status: SUPERSEDED (2026-05-28).**

The v1 design described here required rich rp1 frontmatter (`rp1_doc_id`, `artifact`, …)
and refused to publish without it, and targeted PRs only. That contract no longer matches
the skill: frontmatter is now optional, the idempotency key falls back to the repo-relative
path, and the target may be a PR **or** an issue (by number or URL).

The current design and rationale live in:

- **Spec:** [`../../docs/superpowers/specs/2026-05-28-persist-rp1-artifact-generality-design.md`](../../docs/superpowers/specs/2026-05-28-persist-rp1-artifact-generality-design.md)
- **Implementation plan:** [`../../docs/superpowers/plans/2026-05-28-persist-rp1-artifact-generality.md`](../../docs/superpowers/plans/2026-05-28-persist-rp1-artifact-generality.md)

The original v1 design text is preserved in git history (see this file prior to the
commit on 2026-05-28).
