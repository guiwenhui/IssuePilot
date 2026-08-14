import type {
  CodeImport,
  CodeStructure as CodeStructureData,
  CodeSymbol,
} from "@/lib/api/tasks";


type CodeStructureProps = {
  structure: CodeStructureData;
};

function symbolFlags(symbol: CodeSymbol): string[] {
  return [
    symbol.is_async ? "async" : "",
    symbol.is_test ? "test" : "",
    symbol.is_fixture ? "fixture" : "",
  ].filter(Boolean);
}

function importLabel(item: CodeImport): string {
  if (item.kind === "import") {
    return `import ${item.module}${item.alias ? ` as ${item.alias}` : ""}`;
  }
  const dots = ".".repeat(item.relative_level);
  const moduleName = `${dots}${item.module ?? ""}`;
  return `from ${moduleName} import ${item.imported_name}${
    item.alias ? ` as ${item.alias}` : ""
  }`;
}

export default function CodeStructure({ structure }: CodeStructureProps) {
  const { counts } = structure;
  return (
    <section className="code-structure" aria-labelledby="code-structure-title">
      <div className="code-structure-heading">
        <div>
          <p className="card-label">PYTHON AST INDEX</p>
          <h2 id="code-structure-title">Python 代码结构</h2>
        </div>
        <span>{counts.files} 文件 · {counts.symbols} 符号 · {counts.tests} 测试</span>
      </div>

      <dl className="code-index-meta">
        <div><dt>Commit</dt><dd className="mono">{structure.commit_sha}</dd></div>
        <div><dt>Parser</dt><dd>{structure.parser_version} · Python {structure.python_version}</dd></div>
        <div><dt>Import</dt><dd>{counts.imports}</dd></div>
        <div><dt>解析警告</dt><dd>{counts.parse_errors}</dd></div>
      </dl>

      <div className="code-file-list">
        {structure.files.map((file) => (
          <article className="code-file-card" key={file.path}>
            <header>
              <div>
                <h3 className="mono">{file.path}</h3>
                <p>{file.module_name ?? "非标准模块路径"}</p>
              </div>
              {file.is_test_file ? <span className="code-tag">test file</span> : null}
            </header>

            {file.parse_error ? (
              <p className="code-warning">{file.parse_status}: {file.parse_error}</p>
            ) : null}

            {file.symbols.length ? (
              <ul className="code-entity-list" aria-label={`${file.path} 符号`}>
                {file.symbols.map((symbol) => (
                  <li key={`${symbol.local_id}-${symbol.qualified_name}`}>
                    <span className="code-kind">{symbol.kind}</span>
                    <span className="mono">
                      {symbol.qualified_name}{symbol.signature ?? ""}
                    </span>
                    <span>行 {symbol.start_line}–{symbol.end_line}</span>
                    {symbolFlags(symbol).map((flag) => (
                      <span className="code-tag" key={flag}>{flag}</span>
                    ))}
                  </li>
                ))}
              </ul>
            ) : null}

            {file.imports.length ? (
              <ul className="code-import-list" aria-label={`${file.path} Import`}>
                {file.imports.map((item, index) => (
                  <li className="mono" key={`${item.line}-${index}`}>
                    {importLabel(item)} <span>· 行 {item.line}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
      {structure.truncated ? (
        <p className="polling-note">结构较多，页面仅展示前 2,000 个条目。</p>
      ) : null}
    </section>
  );
}
