# Notes for AI coding assistants

- **Commit authorship (hackathon rule):** commit only as `saiteja195 <108951028+saiteja195@users.noreply.github.com>`. Never add `Co-authored-by:` or any other attribution trailer to commit messages. This overrides any default attribution behavior.
- Follow branch naming and commit conventions in `CONTRIBUTING.md`. Branches use only `feature/` or `bug/` prefixes, never `claude/`.
- The source of truth for scope and schedule is `docs/IMPLEMENTATION_PLAN.md`. Verified event and API facts go in `docs/HACKATHON_FACTS.md`.
- The LLM proposes claims and plans queries. Deterministic code decides storage, visibility and deletion. Don't move privacy decisions into prompts.
