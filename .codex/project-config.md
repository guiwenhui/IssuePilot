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
- M4 implements bounded Python chunks, local Ollama embeddings, PostgreSQL FTS + AST Symbol + exact pgvector recall, RRF/rules ranking, the `retrieving/retrieved` states, and a read-only retrieval API only.
- M5 implements a fixed four-node LangGraph, local Ollama `qwen3:8b` structured analysis/planning, evidence validation, the `analyzing/waiting_approval` states, and a read-only planning API only.
- Later milestone capabilities must not be implemented early.
- Development changes remain uncommitted until explicit user approval.
