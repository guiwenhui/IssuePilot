import type { RepositoryTree as RepositoryTreeData } from "@/lib/api/tasks";


type RepositoryTreeProps = {
  tree: RepositoryTreeData;
};

function formatBytes(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    style: "unit",
    unit: "byte",
    unitDisplay: "narrow",
  }).format(value);
}

export default function RepositoryTree({ tree }: RepositoryTreeProps) {
  return (
    <section className="repository-tree" aria-labelledby="repository-tree-title">
      <div className="repository-tree-heading">
        <div>
          <p className="card-label">ISOLATED SNAPSHOT</p>
          <h2 id="repository-tree-title">仓库文件树</h2>
        </div>
        <span>{tree.file_count} 个条目 · {formatBytes(tree.total_bytes)}</span>
      </div>

      <dl className="snapshot-meta">
        <div>
          <dt>固定 Commit</dt>
          <dd className="mono">{tree.commit_sha}</dd>
        </div>
        <div>
          <dt>规范地址</dt>
          <dd>{tree.canonical_url}</dd>
        </div>
      </dl>

      <ul className="file-tree-list">
        {tree.entries.map((entry) => (
          <li key={entry.path}>
            <span className={`tree-kind ${entry.kind}`}>{entry.kind}</span>
            <span className="mono">{entry.path}</span>
            <span>{entry.size_bytes === null ? "—" : formatBytes(entry.size_bytes)}</span>
          </li>
        ))}
      </ul>
      {tree.truncated ? (
        <p className="polling-note">文件较多，页面仅展示前 2,000 个条目。</p>
      ) : null}
    </section>
  );
}
