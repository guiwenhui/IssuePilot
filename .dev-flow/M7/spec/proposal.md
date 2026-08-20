# Proposal: M7 隔离 Patch 与白名单测试

> status: approved
>
> approved_at: 2026-08-17
>
> doc_version: 1
>
> spec_deltas: `[]`

## 背景与目标

M6 已把计划审批、版本和恢复做成可审计流程，但 `approved` 不产生文件副作用。M7 要在不改变来源仓库的前提下，把已批准计划转成可查看的本地 Unified Diff，并在用户看过 Patch 后，通过受限 Runner 执行真实 `pytest`，保存命令、退出码、耗时和输出证据。

## 用户价值

- 用户能从批准计划继续生成真实代码修改，而不是只看到模型建议。
- 修改只发生在固定 Commit 的隔离 Git Worktree，来源仓库始终可核对且保持 clean。
- 页面先展示标准 Unified Diff，再由用户明确授权执行测试。
- 测试成功或失败都保存真实证据；M7 不把 LLM 文本当成完成证明。

## 范围

### 范围内

- 从最新 approved Plan 创建幂等 Implementation Run。
- 三方核对业务表、Checkpoint 和来源 Worktree 后，从固定 Commit 创建隔离 Worktree。
- 本机 `qwen3:8b` 生成受限、结构化的完整文件替换；后端校验后原子写入隔离 Worktree。
- 仅允许修改批准计划引用的现存 tracked 普通 UTF-8 `.py` 文件。
- Git 生成并保存标准 Unified Diff、SHA256、文件清单和变更统计。
- Patch 页面暂停，用户再次明确授权后才执行固定 `python -m pytest -q`。
- Test Runner 使用固定镜像、无网络、非 root、只读仓库挂载和资源限制；不可用时不降级到宿主机。
- 新增业务 migration、M7 Graph/Checkpoint、内存队列启动恢复、API、前端、测试与文档。

### 范围外

- 新建、删除、重命名文件，修改文件模式、二进制、符号链接或 Submodule。
- 用户自定义命令、Shell、在线安装依赖或执行仓库脚本。
- Reviewer、自动修复、有限重试和质量 Gate（M8）。
- Commit、Push、PR、GitHub 写权限或用户身份绑定。
- 多实例共享 Worker、Redis/RQ、生产级容器编排。

## 验收标准

- **AC1 — 显式 Patch 授权**：只有 `approved` 任务可提交版本化、幂等的 Implementation 请求；M6 approval 不自动产生文件副作用。
- **AC2 — 三方一致性**：开始和恢复时同时核对 approved Plan/业务记录、M7 Checkpoint、Snapshot/Index/Retrieval/Planning Commit 以及来源 Worktree HEAD/clean/hash；不一致进入 `recovery_blocked`。
- **AC3 — 隔离 Worktree**：Worktree 从固定 Commit 创建；来源仓库前后 HEAD、clean 和 tracked digest 不变。
- **AC4 — 受限模型输入输出**：只向 loopback `qwen3:8b` 发送 Issue、approved Plan 和允许文件；输出必须满足严格 FileReplacement Schema。
- **AC5 — Patch 安全**：只修改批准范围内现存 tracked 普通 `.py`；拒绝 traversal、绝对路径、`.git`、symlink、submodule、非 UTF-8、原 hash 不匹配和资源超限。
- **AC6 — 规范 Diff**：最终 Patch 必须由 Git 从真实 Worktree 生成；持久化 Diff hash、文件清单、增删统计，读取时再次与 Worktree 核对。
- **AC7 — 显式测试授权**：Patch 落地后 Graph 暂停；只有携带 expected patch hash 的幂等测试请求才能恢复。
- **AC8 — 测试安全**：固定 argv，不经过 Shell；固定镜像 digest、无网络、非 root、cap-drop、no-new-privileges、CPU/内存/PID/超时/输出限制；Runner 不可用时停止而不在宿主机执行。
- **AC9 — 真实证据**：保存测试 argv、镜像、状态、退出码、超时、耗时、截断输出和完整输出 hash；失败 Patch 仍可查看。
- **AC10 — 恢复幂等**：重启不会重复创建 Worktree、重复写 Patch 或重复执行已完成测试；无法证明副作用状态时 `recovery_blocked`。
- **AC11 — API/UI**：页面显示 Patch、修改统计和测试证据；活跃状态轮询，`patch_ready/tested/test_failed/recovery_blocked/failed` 停止轮询。
- **AC12 — 里程碑边界**：M7 不 Review、不自动修复、不 Commit/Push/PR；编码完成后项目分支保持未 Commit、未 Push等待验收。

## 影响模块

- `backend/app/agents/`：独立 Implementation Graph、Patch review Interrupt 和测试 Command。
- `backend/app/models/`、`backend/migrations/`：Implementation/Patch/Test 业务记录。
- `backend/app/schemas/`：结构化模型输出、请求、响应和证据 DTO。
- `backend/app/services/`：一致性核对、Worktree、Patch、Runner 和持久化。
- `backend/app/workers/`：Implementation 单消费者队列与 pending 恢复。
- `backend/app/api/`、`backend/app/main.py`：API、依赖、生命周期和错误契约。
- `app/`、`components/`、`lib/`：生成 Patch、Diff 展示、测试授权和轮询。
- `docs/`、`.codex/project-config.md`：架构、调用链、安全边界、ADR 和里程碑状态。

## 回滚原则

关闭 `IMPLEMENTATION_ENABLED` 后拒绝新 M7 请求，保留 M6 approved 读取和所有 M7 证据。停止 Worker 不自动删除有歧义的 Worktree。业务 migration 可回退，但 Worktree 与 Checkpoint 清理必须在核对 task/run/hash 后另行批准。
