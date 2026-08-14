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
- M2 implements strict GitHub URL validation, an in-process single-consumer clone queue, isolated shallow clones, persisted repository snapshots, and a file-tree API only.
- M3 implements isolated Python AST parsing, normalized code structure persistence, the `indexing/indexed` states, and a read-only code structure API only.
- Later milestone capabilities must not be implemented early.
- Development changes remain uncommitted until explicit user approval.
