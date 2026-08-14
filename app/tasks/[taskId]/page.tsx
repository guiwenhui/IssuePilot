import Link from "next/link";

import TaskStatusPanel from "@/components/task-status-panel";


type TaskPageProps = {
  params: Promise<{ taskId: string }>;
};

export default async function TaskPage({ params }: TaskPageProps) {
  const { taskId } = await params;

  return (
    <main>
      <header className="topbar">
        <Link className="brand" href="/" aria-label="返回 IssuePilot 首页">
          <span className="brand-mark" aria-hidden="true">IP</span>
          <span>IssuePilot</span>
        </Link>
        <span className="phase-badge">M2 · 仓库快照</span>
      </header>

      <section className="task-page" aria-label="任务状态">
        <TaskStatusPanel taskId={taskId} />
        <Link className="text-link" href="/">创建另一个任务</Link>
      </section>
    </main>
  );
}
