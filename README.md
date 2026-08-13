# IssuePilot Web

IssuePilot 的前端模板，使用 Next.js App Router、React 和 TypeScript 构建。

当前仓库只包含品牌化静态首页和 M0 设计文档，尚未连接 FastAPI、数据库或任何 Agent 工作流。任务创建、状态轮询等 M1 功能均未实现。

## 当前范围

- 展示 IssuePilot 的产品定位与里程碑进度
- 展示请求链、检索链、Agent 链和失败链的目标概览
- 为 M1 的任务创建与状态查询保留清晰的前端边界

## 本地运行

首次运行前需要在项目根目录安装依赖，然后启动 Next.js 开发服务器：

```bash
npm install
npm run dev
```

浏览器访问 `http://localhost:3000`。

> 本次模板重建未执行依赖安装、构建或开发服务器命令，因此仓库中不包含 `package-lock.json`。

## 常用命令

```bash
npm run dev
npm run lint
npm run build
npm run start
```

## 后续里程碑

M1 将接入 FastAPI 和 PostgreSQL，实现任务创建、持久化以及页面轮询任务状态。当前页面上的状态均为静态设计内容。
