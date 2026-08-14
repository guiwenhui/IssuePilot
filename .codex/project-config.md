# IssuePilot Dev Flow Configuration

- root_path: `/Users/gui.w.leo/Documents/workplace/IssuePilot`
- architecture: single-repo
- tech_stack.frontend: Next.js App Router + TypeScript
- tech_stack.backend: FastAPI + Python
- database: PostgreSQL
- git.main_branch: `main`
- git.branch_naming.format: `{type}/{issue_key}`
- git.commit_format: Conventional Commits
- test.frontend: `npm run lint`, `npm run typecheck`, `npm run build`
- test.backend: `pytest`

## Milestone rules

- M1 implements task creation, PostgreSQL persistence, task lookup, and browser polling only.
- Later milestone capabilities must not be implemented early.
- Development changes remain uncommitted until explicit user approval.
