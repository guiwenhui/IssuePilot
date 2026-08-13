# IssuePilot 调用链

## 文档说明

以下是目标调用链及其逐步落地计划。M0 仅记录设计，M1 首先实现请求链的最小闭环；检索、Agent、恢复等能力在后续里程碑引入。

## 1. 请求链

首次落地：M1。

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Next.js TaskForm
    participant API as FastAPI POST /api/v1/tasks
    participant Service as TaskService.create_task()
    participant DB as PostgreSQL tasks

    User->>Web: 输入公开仓库 URL 与 Issue
    Web->>API: 提交 JSON 请求
    API->>API: Pydantic 校验
    alt 输入合法
        API->>Service: 创建任务命令
        Service->>DB: INSERT task(status=created)
        DB-->>Service: task_id
        Service-->>API: Task DTO
        API-->>Web: 201 + task_id + status
        loop M1 轮询
            Web->>API: GET /api/v1/tasks/{task_id}
            API->>Service: 查询任务
            Service->>DB: SELECT task
            DB-->>Service: 当前任务记录
            Service-->>API: Task DTO
            API-->>Web: 当前任务状态
        end
    else 输入非法
        API-->>Web: 422 + 结构化校验错误
    end
```

输入是仓库 URL 和 Issue；输出是可持久化查询的 `task_id`、状态和错误契约。M1 不克隆仓库，也不启动 Agent。后续若加入 SSE，仍由 FastAPI 推送事件，数据库继续作为权威状态来源。

## 2. 检索链

结构化代码首次落地：M3；完整混合检索首次落地：M4。

```mermaid
flowchart LR
    Issue["Issue 文本"] --> Query["查询构造"]
    Query --> Keyword["关键词召回"]
    Query --> Symbol["AST 符号召回"]
    Query --> Vector["Embedding 向量召回"]
    Keyword --> Fusion["结果融合与去重"]
    Symbol --> Fusion
    Vector --> Fusion
    Fusion --> Ranker["Reranker 重排"]
    Ranker --> Context["相关文件、符号、代码片段与引用依据"]
```

正常输出必须带文件路径、符号与来源，不能只返回模型总结。若召回不足，系统可在限定次数内扩大查询或 Top-K；仍不足则保存检索证据并进入 `failed` 或人工处理，而不是臆造代码上下文。

## 3. Agent 链

分析与规划首次落地：M5；审批与恢复首次落地：M6；Patch 和测试首次落地：M7；审查修复环首次落地：M8。

```mermaid
flowchart TD
    Retrieve["retrieve_code\n检索依据"] --> Analyze["analyze_requirement\n需求与验收标准"]
    Analyze --> Plan["create_plan\n实施计划与测试策略"]
    Plan --> Save["保存 Checkpoint"]
    Save --> Approval{"Interrupt：人工审批"}
    Approval -->|"修改"| Plan
    Approval -->|"拒绝"| Cancelled["cancelled"]
    Approval -->|"批准"| Patch["generate_and_apply_patch\n隔离 Worktree"]
    Patch --> Test["run_pytest\n白名单命令"]
    Test --> Review["review_patch\n审查变更"]
    Review --> Gate{"质量 Gate"}
    Gate -->|"通过"| Complete["completed"]
    Gate -->|"可修复且未超限"| Retry["retrying"]
    Retry --> Patch
    Gate -->|"超限"| Failed["failed + 人工升级"]
```

LangGraph 节点不是让多个角色自由聊天，而是让每一步的输入、输出和下一步显式可见。审批节点通过 Interrupt 暂停；用户决定后从 Checkpoint 恢复。

## 4. 失败链

基本错误契约从 M1 开始；跨节点 Checkpoint 恢复在 M6 落地；有限修复循环在 M8 落地。

```mermaid
flowchart TD
    Error["节点或工具异常"] --> Classify["分类：输入 / 暂时性 / 代码 / 测试 / 权限 / 安全"]
    Classify --> Retryable{"允许重试？"}
    Retryable -->|"否"| Persist["保存错误证据与最后成功节点"]
    Retryable -->|"是"| Limit{"是否低于该类型上限？"}
    Limit -->|"是"| Retrying["状态设为 retrying\n记录 attempt 与原因"]
    Retrying --> Resume["从安全 Checkpoint 恢复"]
    Resume --> Verify["验证结果"]
    Verify -->|"成功"| Continue["返回原执行阶段"]
    Verify -->|"再次失败"| Classify
    Limit -->|"否"| Persist
    Persist --> Failed["failed"]
    Failed --> Human["人工查看证据并决定恢复、修改或取消"]
```

恢复不是还原模型当时的思考，而是读取持久化状态、文件、事件与最后成功节点，再安全地继续。对可能产生副作用的步骤，恢复前必须检查幂等性并在需要时再次请求批准。

## 状态与证据约定

每次状态变化至少记录：

- `task_id`
- 原状态与新状态
- 当前节点或阶段
- 事件时间
- 尝试次数
- 错误类型与摘要（如有）
- 最后成功节点（如有）
- 测试命令、退出码与输出摘要（测试阶段）

页面展示的“成功”必须来自已持久化的执行证据，不能只来自 LLM 文本。
