# Contributing to MemoryAtlas

## Hackathon authorship rule (required)

Every commit must be authored and committed by **saiteja195** only.

- No `Co-authored-by:` trailers and no other attribution trailers in commit messages.
- Configure the identity once per clone:

```bash
git config user.name "saiteja195"
git config user.email "108951028+saiteja195@users.noreply.github.com"
```

- Check before pushing:

```bash
git log --format='%an <%ae> | %cn <%ce>' | sort -u
```

```bash
git log --format=%B | grep -i 'co-authored' || echo "clean"
```

## Branch naming

Only two prefixes are allowed, followed by a short kebab-case name, with no tool or agent prefixes (never `claude/...`):

| Prefix | Use for | Examples |
|---|---|---|
| `feature/` | Anything new, including docs, tests and tooling | `feature/scaffold`, `feature/revocation`, `feature/atlas-ui` |
| `bug/` | Fixing something broken | `bug/last-seen-ordering` |

Branch from `main`, keep branches short-lived, and merge by pull request. The phase branches are listed in `docs/IMPLEMENTATION_PLAN.md` §8.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) with the component as scope:

```
feat(privacy): recompute claim support with least fixpoint on revoke
fix(recall): reject answers citing claims not returned by tools
```

Scopes: `scaffold`, `capture`, `compiler`, `graph`, `recall`, `privacy`, `llm`, `ui`, `eval`, `fixtures`, `docs`.

## Releases

Tag the final submission commit on `main` as `v1.0-submission`.
