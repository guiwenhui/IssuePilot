import TaskCreateForm from "@/components/task-create-form";

const callChains = [
  {
    index: "01",
    title: "请求链",
    summary: "浏览器 → FastAPI → Queue → Git → 隔离工作区",
    description: "把任务转换为经过校验、可追踪的公开仓库快照。",
  },
  {
    index: "02",
    title: "检索链",
    summary: "Issue → 查询构造 → 混合召回 → 重排 → 上下文",
    description: "从代码仓库定位真正影响需求的文件与符号。",
  },
  {
    index: "03",
    title: "Agent 链",
    summary: "分析 → 规划 → 审批 → Patch → 测试 → 审查",
    description: "通过显式节点和人工确认控制研发工作流。",
  },
  {
    index: "04",
    title: "失败链",
    summary: "异常 → 分类 → 有限重试 → 恢复 → 人工升级",
    description: "保留执行证据，在安全边界内处理失败与恢复。",
  },
];

export default function Home() {
  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="IssuePilot 首页">
          <span className="brand-mark" aria-hidden="true">IP</span>
          <span>IssuePilot</span>
        </a>
        <span className="phase-badge">M3 · Python AST</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Agentic software delivery · Learning project</p>
          <h1>让一次 Issue 的交付过程，<br />清晰、可控、可恢复。</h1>
          <p className="lead">
            IssuePilot 面向小型 Python 开源仓库，将代码检索、需求规划、人工审批、
            Patch、测试和审查组织成可追踪的工作流。
          </p>
          <div className="hero-actions" aria-label="项目当前状态">
            <span className="status-pill success"><span className="dot" />API 契约已接入</span>
            <span className="status-pill">PostgreSQL 权威状态</span>
          </div>
        </div>

        <aside className="milestone-card" aria-labelledby="milestone-title">
          <p className="card-label">BUILD PROGRESS</p>
          <h2 id="milestone-title">从架构基线开始</h2>
          <div className="progress-track" aria-label="项目完成进度 40%">
            <span />
          </div>
          <div className="milestone-list">
            <div className="milestone done">
              <span className="milestone-number">M0</span>
              <div><strong>项目设计</strong><small>范围、架构与安全边界</small></div>
              <span className="state">完成</span>
            </div>
            <div className="milestone done">
              <span className="milestone-number">M1</span>
              <div><strong>最小闭环</strong><small>任务创建、保存与状态展示</small></div>
              <span className="state">完成</span>
            </div>
            <div className="milestone done">
              <span className="milestone-number">M2</span>
              <div><strong>仓库隔离</strong><small>安全校验、浅克隆与文件树</small></div>
              <span className="state">完成</span>
            </div>
            <div className="milestone next">
              <span className="milestone-number">M3</span>
              <div><strong>Python 结构</strong><small>AST、符号、Import 与测试结构</small></div>
              <span className="state">验收中</span>
            </div>
          </div>
        </aside>
      </section>

      <section className="task-entry" aria-labelledby="task-entry-title">
        <div className="task-entry-copy">
          <p className="eyebrow">M3 · INDEX PYTHON STRUCTURE</p>
          <h2 id="task-entry-title">看清仓库里的 Python 结构</h2>
          <p>
            后台固定仓库 Commit，再在隔离进程提取文件、类、函数、Import 和测试结构。
          </p>
          <div className="scope-note">
            <strong>M3 边界</strong>
            <span>只解析 tracked Python 文件；不做向量检索、不导入或执行仓库代码。</span>
          </div>
        </div>
        <TaskCreateForm />
      </section>

      <section className="chains" aria-labelledby="chains-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">TARGET CALL CHAINS</p>
            <h2 id="chains-title">四条链，解释一次完整交付</h2>
          </div>
          <p>当前为目标架构概览。能力将在后续里程碑逐步接入，并以真实测试证据验收。</p>
        </div>
        <div className="chain-grid">
          {callChains.map((chain) => (
            <article className="chain-card" key={chain.index}>
              <span className="chain-index">{chain.index}</span>
              <h3>{chain.title}</h3>
              <p className="chain-summary">{chain.summary}</p>
              <p>{chain.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="boundary" aria-labelledby="boundary-title">
        <div>
          <p className="eyebrow">CURRENT BOUNDARY</p>
          <h2 id="boundary-title">代码结构已经可见，代码执行仍保持关闭。</h2>
        </div>
        <p>
          页面现在可以核对固定 Commit 下的 Python AST 结构，但不会导入或执行仓库模块。
          关键词、向量检索和 Agent 工作流会在后续里程碑逐项通过审批接入。
        </p>
      </section>

      <footer>
        <span>IssuePilot</span>
        <span>Built milestone by milestone.</span>
      </footer>
    </main>
  );
}
