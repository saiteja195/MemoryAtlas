# Contributing

The full rules are in [`CONTRIBUTING.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/CONTRIBUTING.md). The essentials:

## Authorship rule (hackathon, required)

Every commit is authored and committed by **saiteja195** only. **No `Co-authored-by:` or other attribution trailers** in commit messages.

```bash
git config user.name "saiteja195"
git config user.email "108951028+saiteja195@users.noreply.github.com"
```

## Branches

Only two prefixes, followed by a short kebab-case name. No tool or agent prefixes.

| Prefix | Use for |
|---|---|
| `feature/` | Anything new, including docs, tests and tooling |
| `bug/` | Fixing something broken |

Branch from `main`, keep branches short, merge by pull request.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) with the component as scope, for example `feat(privacy): recompute claim support with least fixpoint on revoke`.

Scopes: `scaffold`, `capture`, `compiler`, `graph`, `recall`, `privacy`, `llm`, `ui`, `eval`, `fixtures`, `docs`.

## Working on the code

```bash
make setup     # backend venv + frontend deps
make test      # frontend check, then backend tests
make dev       # API on :8000 and the UI together
```

## Project principles

- **The model proposes; code decides.** Don't move a privacy decision (storage, visibility, deletion) into a prompt.
- **Keep it text-only.** Nothing may store raw media.
- **State limits plainly.** Verified API facts go in `docs/HACKATHON_FACTS.md`; scope and schedule live in `docs/IMPLEMENTATION_PLAN.md`.
- **Never expose or commit the API key.** Don't paste it into chat or an issue.
- **Changing a prompt or tool output invalidates recorded model responses.** Re-record the affected demo responses and re-run the tests.
- **Don't tune on the held-out day.** Report what it shows; fix defects in a separate change afterwards.
