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

`<type>/<short-kebab-description>`, branched from `main`, kept short-lived, merged back via pull request.

| Type | Use for | Example |
|---|---|---|
| `feat/` | New capability | `feat/privacy-revocation` |
| `fix/` | Bug fix | `fix/last-seen-ordering` |
| `test/` | Tests only | `test/revocation-properties` |
| `eval/` | Benchmark and baseline work | `eval/baseline-and-benchmark` |
| `docs/` | Documentation | `docs/submission` |
| `chore/` | Tooling, scaffolding, deps | `chore/project-scaffold` |

The planned branches for each day are listed in `docs/IMPLEMENTATION_PLAN.md` §8.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) with the component as scope:

```
feat(privacy): recompute claim support with least fixpoint on revoke
fix(recall): reject answers citing claims not returned by tools
```

Scopes: `capture`, `compiler`, `graph`, `recall`, `privacy`, `llm`, `ui`, `eval`, `fixtures`, `docs`.

## Releases

Tag the final submission commit on `main` as `v1.0-submission`.
