# ADR-011：M7 隔离 Patch 与固定测试 Runner

- Status: Accepted
- Date: 2026-08-17

## Context

M6 的 `approved` 只确认计划，不授权写文件。M7 需要把已批准计划转成真实代码差异并执行测试，但模型输出、文件系统写入和 pytest 都是不同风险级别的副作用。pytest 会执行仓库代码，普通宿主机子进程不能阻止它读取凭据、访问网络或修改其他文件。Checkpoint、业务表与文件系统又无法组成单一原子事务，因此服务重启后不能只信任其中一个来源。

## Decision

M6 approval 后新增独立、幂等的 Implementation 授权。系统从批准计划绑定的固定 Commit 创建隔离 Git Worktree，来源仓库保持只读和 clean。Implementation Graph 使用独立 Checkpoint thread；业务表保存 Run 与证据，Checkpoint 保存图节点位置，来源仓库和 Implementation Worktree 保存磁盘真实状态。恢复必须同时核对三类事实，不一致或无法证明已开始副作用的结果时进入 `recovery_blocked`。

本机 `qwen3:8b` 不直接输出或执行 Diff，而输出严格的 `path/original_sha256/content` 完整文件替换。后端只允许实施步骤与测试目标路径交集中的现存 tracked UTF-8 `.py` 文件，验证路径 containment、文件类型、原 hash、文件/字节/变更行数上限后原子写入。规范 Unified Diff、文件清单和统计一律由 Git 从真实 Worktree 生成并持久化；读取和测试前再次生成并核对 Patch SHA256。

Patch 保存后 Graph 通过 Interrupt 停在 `patch_ready`。用户查看精确 Diff 后，以预期 Patch SHA256 和另一幂等键独立授权测试。Runner 只执行服务端固定的 `python -m pytest -q -p no:cacheprovider`，使用固定 Docker 镜像 digest、无网络、非 root、只读 Worktree mount、cap-drop、no-new-privileges、CPU/内存/PID/宿主机与容器内双层超时/输出限制。只允许本机 Unix Docker socket；服务启动会清理并确认遗留的确定性容器名。Runner 不安装仓库依赖，不接受用户或模型命令，Docker 不可用时绝不回退宿主机。

M7 实现模型沿用 loopback Ollama，但与 M5 规划使用不同资源预算：32K context、16K 输出 token、256 KiB 响应上限和 300 秒超时。这样不会放宽 M5 证据预算；较大完整文件替换仍可能慢或失败。

## Alternatives

### 直接执行模型生成的 Unified Diff

输出更短，但 hunk 上下文、路径和 mode/binary 语义更难可靠解析，容易出现部分应用和路径攻击。结构化完整文件替换更容易用 Schema、原 hash 和资源上限做确定性校验，最终 Diff 仍由 Git 权威生成。

### 在宿主机运行 pytest 或动态安装仓库依赖

启动更快、更多项目可能直接通过，但会让不可信仓库代码接触本机文件、网络、凭据或安装脚本。M7 选择诚实报告缺依赖的 `test_failed`，不以通过率换取安全边界。

### 计划批准后自动生成 Patch 并自动测试

交互更少，但把“认可方案”“允许写文件”和“允许执行代码”合并成一次授权，用户无法在执行测试前审查真实变更。M7 保留两个显式副作用 Gate。

### 使用容器内项目专属依赖镜像

可提高测试可运行性，但需要可信 lockfile、构建缓存、供应链策略和镜像生命周期。首版只固定 pytest 基础镜像；依赖解析与可复现项目环境需要后续独立设计。

## Consequences

- 来源仓库不会被 M7 修改，所有 Patch 只存在于服务端控制的 Implementation Worktree。
- Patch 与测试授权幂等且可审计；页面显示的结果必须能由数据库、Checkpoint 和真实文件重新核对。
- `test_failed` 可能表示断言失败、超时或缺少项目依赖；它是有效执行证据，不等于平台故障。
- Docker daemon 仍是高权限基础设施，服务只拼装固定 argv、镜像和受控路径，不能把仓库文本变成 Docker 参数。
- 完整文件替换对大文件消耗较多模型时间和输出；M7 用严格上限停止，不做自动修复。
- M7 的 `tested` 只表示固定 pytest exit code 为 0；Reviewer、质量 Gate、有限重试属于 M8。
- 关闭 `IMPLEMENTATION_ENABLED` 可退回 M6，现有数据库证据、Checkpoint 和 Worktree 保留供人工审计，不自动删除。
