import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  BookOpen,
  FileUp,
  History,
  Plus,
  Search,
} from "lucide-react";
type Source = {
  code: string;
  title: string;
  content: string;
  keywords: string;
  active: boolean;
  version: number;
  author?: string;
  updated_at?: string;
};
type Revision = {
  version: number;
  action: string;
  author: string;
  created_at: string;
  snapshot: Source;
};
type Evidence = {
  code: string;
  title: string;
  content: string;
  overlap: number;
  rrf_score: number;
};
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
const blank: Source = {
  code: "",
  title: "",
  content: "",
  keywords: "",
  active: true,
  version: 0,
};
export default function KnowledgePanel({
  api,
  onChanged,
}: {
  api: Api;
  onChanged: () => Promise<void>;
}) {
  const selection = useRef(0);
  const [sources, setSources] = useState<Source[]>([]);
  const [admin, setAdmin] = useState(false);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<Source>();
  const [isNew, setIsNew] = useState(false);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Evidence[]>();
  async function load() {
    setSources(await api<Source[]>("/helpdesk/knowledge"));
  }
  useEffect(() => {
    Promise.all([
      load(),
      api<{ role: string }>("/auth/me").then((user) =>
        setAdmin(["TENANT_OWNER", "TENANT_ADMIN"].includes(user.role)),
      ),
    ]).catch((e) => setError(e.message));
  }, []);
  async function select(source: Source) {
    const selected = ++selection.current;
    setEditing({ ...source });
    setIsNew(false);
    setRevisions([]);
    setError("");
    setMessage("");
    try {
      const rows = await api<Revision[]>(
        `/helpdesk/knowledge/${source.code}/revisions`,
      );
      if (selected === selection.current) setRevisions(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "版本加载失败");
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(
        isNew ? "/helpdesk/knowledge" : `/helpdesk/knowledge/${editing.code}`,
        {
          method: isNew ? "POST" : "PUT",
          body: JSON.stringify({
            ...editing,
            expected_version: editing.version,
          }),
        },
      );
      setResults(undefined);
      await load();
      await onChanged();
      setEditing(undefined);
      setRevisions([]);
      setMessage("知识已保存，检索索引已同步更新。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
      await load().catch(() => {});
    } finally {
      setBusy(false);
    }
  }
  async function toggle(source: Source) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(`/helpdesk/knowledge/${source.code}`, {
        method: "PUT",
        body: JSON.stringify({
          ...source,
          active: !source.active,
          expected_version: source.version,
        }),
      });
      setResults(undefined);
      await load();
      await onChanged();
      if (editing?.code === source.code) setEditing(undefined);
      setMessage(
        source.active
          ? "知识已停用，不再参与检索；历史诊断引用保留。"
          : "知识已启用并重新建立索引。",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新失败");
    } finally {
      setBusy(false);
    }
  }
  async function restore(version: number) {
    if (!editing || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/helpdesk/knowledge/${editing.code}/restore`, {
        method: "POST",
        body: JSON.stringify({ version, expected_version: editing.version }),
      });
      setResults(undefined);
      await load();
      await onChanged();
      setEditing(undefined);
      setRevisions([]);
      setMessage("已将历史内容保存为一个新版本。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  }
  async function importText(file?: File) {
    if (!file || !editing) return;
    try {
      if (!/\.(md|txt)$/i.test(file.name) || file.size > 65536)
        throw new Error("仅支持不超过 64KB 的 Markdown / TXT 文件");
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      if (content.length > 15000 || content.includes("\u0000"))
        throw new Error("正文不得超过 15000 字符，文件需为 UTF-8 文本");
      setEditing({
        ...editing,
        content,
        title: editing.title || file.name.replace(/\.(md|txt)$/i, ""),
      });
      setMessage("正文已导入编辑器，请填写来源代码并保存后入库。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    }
  }
  async function search(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setResults(undefined);
    try {
      setResults(
        (
          await api<{ results: Evidence[] }>("/helpdesk/knowledge/search", {
            method: "POST",
            body: JSON.stringify({ query }),
          })
        ).results,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败");
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    try {
      const data = await api("/helpdesk/knowledge/export");
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "resolveai-knowledge.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    }
  }
  const visible = sources.filter((source) =>
    `${source.code} ${source.title} ${source.keywords}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  return (
    <div className="knowledge-workspace">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {message && (
        <p className="success-message" role="status">
          {message}
        </p>
      )}
      <section className="panel">
        <div className="section-heading">
          <h2>
            <BookOpen size={18} />
            知识来源管理
            <span className="small-pill">
              {sources.filter((source) => source.active).length} 启用 /{" "}
              {sources.length} 总计
            </span>
          </h2>
          {admin && (
            <div className="knowledge-toolbar">
              <button className="secondary" onClick={download}>
                <ArrowDownToLine size={15} />
                导出知识
              </button>
              <button
                className="primary"
                disabled={busy}
                onClick={() => {
                  selection.current++;
                  setEditing({ ...blank });
                  setIsNew(true);
                  setRevisions([]);
                  setMessage("");
                  setError("");
                }}
              >
                <Plus size={16} />
                新增来源
              </button>
            </div>
          )}
        </div>
        <label>
          搜索知识来源
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="标题、关键词或来源代码"
          />
        </label>
        <div className="source-list">
          {visible.map((source) => (
            <article className="source-row" key={source.code}>
              <span className="source-code">{source.code}</span>
              <div>
                <h3>{source.title}</h3>
                <p>{source.content.slice(0, 95)}…</p>
                <small>
                  {source.version === 0
                    ? "旧知识 · 尚无编辑版本"
                    : `v${source.version} · ${source.author}`}{" "}
                  · {source.active ? "参与检索" : "已停用"}
                </small>
              </div>
              <div className="source-actions">
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => select(source)}
                >
                  {admin ? "编辑 / 版本" : "查看内容"}
                </button>
                {admin && (
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() => toggle(source)}
                  >
                    {source.active ? "停用" : "启用"}
                  </button>
                )}
              </div>
            </article>
          ))}
          {!visible.length && (
            <p className="context-empty">没有匹配的知识来源。</p>
          )}
        </div>
      </section>
      {editing && (
        <section className="panel source-editor">
          <div className="section-heading">
            <h2>
              {isNew
                ? "新增知识来源"
                : `编辑 ${editing.code} · v${editing.version}`}
            </h2>
            <button
              className="text-button"
              onClick={() => {
                selection.current++;
                setEditing(undefined);
              }}
            >
              关闭编辑器
            </button>
          </div>
          <form className="knowledge-form" onSubmit={save}>
            <label>
              来源代码
              <input
                value={editing.code}
                disabled={!isNew || !admin || busy}
                pattern="[A-Z]{2,10}-[0-9]{3,5}"
                required
                onChange={(event) =>
                  setEditing({ ...editing, code: event.target.value })
                }
              />
            </label>
            <label>
              知识标题
              <input
                value={editing.title}
                disabled={!admin || busy}
                minLength={2}
                maxLength={200}
                required
                onChange={(event) =>
                  setEditing({ ...editing, title: event.target.value })
                }
              />
            </label>
            <label className="wide">
              检索关键词
              <input
                value={editing.keywords}
                disabled={!admin || busy}
                maxLength={500}
                onChange={(event) =>
                  setEditing({ ...editing, keywords: event.target.value })
                }
              />
            </label>
            {admin && (
              <label className="wide file-import">
                <FileUp size={16} />
                导入 Markdown / TXT
                <input
                  type="file"
                  accept=".md,.txt"
                  disabled={busy}
                  onChange={(event) => {
                    importText(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
              </label>
            )}
            <label className="wide">
              知识正文
              <textarea
                aria-label="知识正文"
                value={editing.content}
                disabled={!admin || busy}
                minLength={20}
                maxLength={15000}
                required
                onChange={(event) =>
                  setEditing({ ...editing, content: event.target.value })
                }
              />
            </label>
            {admin && (
              <button className="primary" disabled={busy}>
                {busy ? "正在保存…" : "保存并更新索引"}
              </button>
            )}
          </form>
          {!isNew && (
            <div className="revision-list">
              <h3>
                <History size={16} />
                最近 30 个版本
              </h3>
              {!revisions.length && (
                <p className="panel-footnote">
                  首次编辑时会保存当前旧内容快照；不补造历史作者或编辑时间。
                </p>
              )}
              {revisions.map((revision) => (
                <details key={revision.version}>
                  <summary>
                    v{revision.version} ·{" "}
                    {revision.action === "legacy_snapshot"
                      ? "旧内容快照"
                      : revision.action}{" "}
                    · {revision.author} ·{" "}
                    {new Date(revision.created_at).toLocaleString("zh-CN", {
                      timeZone: "Asia/Hong_Kong",
                    })}
                  </summary>
                  <pre>{revision.snapshot.content}</pre>
                  {admin && revision.version !== editing.version && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      onClick={() => restore(revision.version)}
                    >
                      恢复该版本为新版本
                    </button>
                  )}
                </details>
              ))}
            </div>
          )}
        </section>
      )}
      <section className="panel retrieval-lab">
        <div className="section-heading">
          <h2>
            <Search size={18} />
            检索测试台
          </h2>
          <span className="micro-label">不创建诊断或工单</span>
        </div>
        <form onSubmit={search}>
          <label>
            检索测试问题
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              minLength={4}
              maxLength={2000}
              placeholder="例如：VPN 认证失败怎么检查？"
              required
            />
          </label>
          <button
            className="secondary"
            disabled={busy || query.trim().length < 4}
          >
            测试检索
          </button>
        </form>
        {results && (
          <div className="retrieval-results">
            {results.length ? (
              results.map((item, index) => (
                <article key={`${item.code}-${index}`}>
                  <span className="source-code">
                    #{index + 1} [{item.code}]
                  </span>
                  <h3>{item.title}</h3>
                  <p>{item.content}</p>
                  <small>
                    词项覆盖 {Math.round(item.overlap * 100)}% · RRF{" "}
                    {item.rrf_score}
                  </small>
                </article>
              ))
            ) : (
              <p className="context-empty">当前启用知识没有检索结果。</p>
            )}
          </div>
        )}
        <p className="panel-footnote">
          使用与诊断相同的混合检索流程。这里只展示候选证据，不判断答案正确性。
        </p>
      </section>
    </div>
  );
}
