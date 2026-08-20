# Design: M7 隔离 Patch 与白名单测试

> source: approved M7 proposal
>
> doc_version: 1
>
> spec_deltas: `[]`

## 决策摘要

| 决策 | 理由 | 不选方案 |
|---|---|---|
| M6 approval 后另设“生成 Patch”动作 | M6 明确只确认计划；文件副作用需要新的可审计授权 | approval 后自动写文件会改变既有安全语义 |
| 独立 Implementation Graph/Checkpoint thread | M6 Planning Graph 已结束；M7 副作用需要独立恢复边界 | 修改旧 thread 会混淆规划与实现状态 |
| 模型输出 FileReplacement，Git 生成 Diff | Schema/hash/范围容易确定性校验，Diff 来自真实文件 | 直接执行模型 Diff 容易出现无效 hunk 和路径攻击 |
| 只修改已有 tracked UTF-8 `.py` | 与 M5 evidence/plan path 契约一致，缩小首版写权限 | 新建/删除/重命名需要新的计划路径语义 |
| Patch 后 Interrupt，再授权测试 | 用户可先看精确修改，pytest 执行不可信代码需更强确认 | 自动测试扩大一次点击的副作用范围 |
| 固定无网络容器 Runner | pytest 会执行任意仓库代码，普通子进程不构成安全边界 | 宿主机运行会暴露文件、网络和本机凭据 |
| 无 Reviewer、无重试 | M7 只证明 Patch/Test 链；修复与 Gate 属 M8 | 自动修复会提前进入下一里程碑 |

## 状态流

```text
approved
  -> implementation_pending
  -> generating_patch
  -> patch_ready
  -> test_pending
  -> testing
  -> tested | test_failed

任一事实不一致 -> recovery_blocked
不可恢复的生成/持久化/Runner错误 -> failed（保留已有证据）
```

`patch_ready` 是用户测试授权暂停点，`tested` 只表示 pytest exit 0，不表示 M8 Review 已通过或项目完成。

## Graph 与恢复

Implementation Graph v1：

```text
START
 -> reconcile
 -> prepare_worktree
 -> generate_replacements
 -> validate_and_apply
 -> persist_patch
 -> interrupt(test approval)
 -> run_tests
 -> persist_test_result
 -> END
```

Checkpoint thread 使用 `implementation:{implementation_run_id}`，与 M6 `task_id` Planning thread 分离。业务表保存用户请求、Run、Patch/Test 证据；Checkpoint 只保存节点位置；Worktree 保存真实文件。每个副作用节点以 Run 状态和 artifact hash 幂等：存在且一致则复用，不一致则阻断。

## 数据模型

### implementation_runs

- `id/task_id/planning_run_id/plan_id/plan_version`
- `idempotency_key`，唯一 `(task_id,idempotency_key)`
- `base_commit/graph_version/prompt_version/provider/model`
- `checkpoint_thread_id/worktree_relpath/status`
- `failure_code/failure_message/created_at/updated_at`
- 每个 task 最多一个非失败 Implementation Run；M7 不重试生成。

### patch_artifacts

- `implementation_run_id` 主外键
- `unified_diff/diff_sha256/file_manifest`
- `file_count/insertions/deletions/created_at`

### test_runs

- `id/implementation_run_id/idempotency_key`
- 唯一 `(implementation_run_id,idempotency_key)`，M7 每个 Patch 最多一次真实执行
- `expected_patch_sha256/status/command_argv/runner_image`
- `exit_code/timed_out/duration_ms/stdout/stderr/output_sha256/output_truncated`
- `created_at/finished_at`

## API

- `POST /api/v1/tasks/{task_id}/implementation`
  - body: `expected_plan_version`, `idempotency_key`
  - 新建或幂等返回 Implementation Run，`202`，no-store。
- `GET /api/v1/tasks/{task_id}/implementation`
  - 返回 Run、Patch 和 Test；每次读取核对来源 HEAD/clean、base Commit 和 Patch hash。
- `POST /api/v1/tasks/{task_id}/implementation/tests`
  - body: `expected_patch_sha256`, `idempotency_key`
  - 只允许 `patch_ready`；保存 pending Test Run 后入队，`202`。

`404` 为 task/run 不存在，`409` 为状态/版本/hash/三方不一致或功能关闭，`422` 为字段非法，`503` 为数据库、Checkpoint、队列或 Runner 不可用。

## Patch 输入、校验与写入

`FileReplacementDraft` 包含 `path/original_sha256/content`。允许路径来自 approved Plan 所有 step paths 与 test target paths 的交集，并必须存在于 Snapshot tracked 普通文件集合。

限制默认值：最多 4 文件；单文件 80 KiB；总输入 160 KiB；Diff 100 KiB；变更 2,000 行。路径使用 PurePosixPath 规范化，拒绝绝对路径、空段、`.`、`..`、`.git`；打开/写入前后核对 resolved containment、文件类型和原 hash。临时文件位于相同父目录并原子 replace。

写入后 Git 固定 argv 生成 `--no-ext-diff --no-renames --unified=3` Diff。再次读取 `git status` 和 `git diff --numstat`，拒绝范围外路径、删除、重命名、mode/binary 变化和超限。业务表保存精确 Diff；GET 时从 Worktree 重新生成并比对 hash。

## Test Runner

Runner 接口只接受服务端构造的 `TestRunSpec`，不接收用户或模型命令。Docker 实现使用参数数组：固定 digest 镜像、`--network none`、`--read-only`、`--user 65534:65534`、`--cap-drop ALL`、`no-new-privileges`、CPU/内存/PID 限制、只读 Worktree mount 与 tmpfs `/tmp`；只接受本机 Unix Docker socket。容器内监督进程提供独立硬超时并固定执行：

```text
python -m pytest -q -p no:cacheprovider
```

默认宿主机超时 120 秒，容器内硬超时额外保底；服务恢复时按确定性名称清理并确认遗留容器不存在。stdout/stderr 各自受限，读取时持续计算完整流 hash，只保存展示片段。Runner 或固定镜像不可用映射 `TEST_RUNNER_UNAVAILABLE`，不回退宿主机。容器内不安装依赖、不访问网络；缺依赖作为环境失败证据呈现。

## 前端

- `approved` 显示“生成本地 Patch”，明确只改隔离 Worktree。
- Patch 生成期轮询；`patch_ready` 展示文件统计和受限 Diff。
- 用户确认 Diff 后点击“运行 pytest”；按钮复用同一幂等键直到得到响应。
- `tested/test_failed/failed/recovery_blocked` 停止轮询并展示结构化证据。
- 页面不展示宿主机绝对 Worktree 路径、完整环境变量或未截断日志。

## 测试策略

- TDD：Schema、状态机、幂等、路径/Hash/资源限制、Diff 校验、Runner argv 与错误分类。
- Git 集成：临时仓库真实创建 Worktree、写文件和生成 Diff；来源 HEAD/clean/digest 不变。
- PostgreSQL：migration、唯一键、并发幂等、pending 恢复、Patch/Test 原子持久化。
- Checkpoint：跨 Factory/Runtime 在 Patch Interrupt 和 test pending 恢复，不重复副作用。
- 容器：固定 fixture 在无网络非 root Runner 真实 pass/fail/timeout；Docker 不可用不降级。
- 本机模型：一个小型 Python fixture 生成结构化 replacement，范围/hash/Diff 均通过。
- 浏览器：approved -> patch_ready -> testing -> tested/test_failed；刷新、停止轮询和 console。
- 全量：后端 branch coverage >=80%；前端 test/lint/typecheck/build；migration roundtrip；`git diff --check`。

## 风险与回滚

- pytest 是主动代码执行：容器边界是硬前置，不能以子进程替代。
- Docker daemon 权限高：仅拼装固定 argv、固定镜像和受控路径，不把仓库文本放入 Docker 参数。
- 全文件替换可能产生大 Diff：严格文件/字节/行限制，用户先审查再测试。
- Checkpoint 与文件系统无法原子提交：节点以业务状态和 hash 重放；有歧义就阻断。
- 关闭 `IMPLEMENTATION_ENABLED` 回到 M6；已有 Worktree/Patch/Test 保留供审计，不自动删除。
