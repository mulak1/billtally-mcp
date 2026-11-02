# GEMINI.md — Anthro-Skill (ECC v2.2.3) Workspace Rules

This workspace is governed by `anthro-skill` (the Gemini/Antigravity equivalent of `affaan-m/ECC`).

## Core Engineering Loop
`plan -> test -> implement -> review -> verify -> remember -> improve`

## Mandatory Standards
1. **Right-Sized Orchestration (`orch-pipeline`):** Classify every task as `Trivial`, `Small`, `Standard`, or `Large`. For `Standard` and `Large` tasks, pause at **Gate 1 (Plan Approval)** before writing production code and **Gate 2 (Commit Confirmation)** before committing.
2. **Test-Driven Development (`tdd-workflow`):** Write failing tests first (RED), implement minimal code to pass (GREEN), refactor cleanly, and maintain 80%+ test coverage.
3. **Immutability & Modularity (`coding-style.md`):** Never mutate state in-place; keep functions `<50` lines, files `<800` lines (`200-400` typical), and nesting `<=4` levels.
4. **Security-First (`security.md`):** Validate all external inputs at system boundaries, never hardcode secrets, use parameterized queries, and never silently swallow errors.
5. **Verification Before Completion (`verification-loop`):** Run `bash ~/.gemini/config/skills/anthro-skill/scripts/anthro_verify.sh` before marking any feature or bugfix complete.

## Installed Rule Packs (`.agents/rules/`)
- `.agents/rules/ecc-common-agents.md`
- `.agents/rules/ecc-common-code-review.md`
- `.agents/rules/ecc-common-coding-style.md`
- `.agents/rules/ecc-common-development-workflow.md`
- `.agents/rules/ecc-common-git-workflow.md`
- `.agents/rules/ecc-common-hooks.md`
- `.agents/rules/ecc-common-patterns.md`
- `.agents/rules/ecc-common-performance.md`
- `.agents/rules/ecc-common-security.md`
- `.agents/rules/ecc-common-testing.md`
- `.agents/rules/ecc-python-coding-style.md`
- `.agents/rules/ecc-python-fastapi.md`
- `.agents/rules/ecc-python-hooks.md`
- `.agents/rules/ecc-python-patterns.md`
- `.agents/rules/ecc-python-security.md`
- `.agents/rules/ecc-python-testing.md`
