import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, FileCheck2, RefreshCw, X } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Draft = {
  id: string;
  ticket_id: string;
  resolution_id: string;
  title: string;
  content: string;
  keywords: string;
  status: "DRAFT" | "PUBLISHED" | "REJECTED";
  version: number;
  author_id: string | null;
  author_name: string;
  reviewer_name?: string | null;
  review_note?: string | null;
  published_code?: string | null;
  published_version?: number | null;
  created_at: string;
  updated_at: string;
};
type Page = {
  items: Draft[];
  page: number;
  page_size: number;
  has_more: boolean;
  can_review: boolean;
  can_create: boolean;
};
type Detail = {
  draft: Draft;
  resolution: {
    id: string;
    category: string;
    summary: string;
    steps: string | string[];
    author_name: string;
    resolved_at: string;
  } | null;
  can_edit: boolean;
  can_review: boolean;
};
const stepList = (steps: string | string[]) =>
  Array.isArray(steps)
    ? steps
    : steps
        .split(/\r?\n/)
        .map((step) => step.trim())
        .filter(Boolean);
const statusLabel = {
  DRAFT: "待审核",
  PUBLISHED: "已发布",
  REJECTED: "已驳回",
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-HK", { timeZone: "Asia/Hong_Kong" });

export default function KnowledgeDraftsPanel({
  api,
  onPublished,
}: {
  api: Api;
  onPublished?: () => Promise<void>;
}) {
  const [page, setPage] = useState<Page>();
  const [pageNumber, setPageNumber] = useState(1);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail>();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [keywords, setKeywords] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const detailGeneration = useRef(0);
  async function loadList() {
    const data = await api<Page>(
      `/helpdesk/knowledge-drafts?page=${pageNumber}&page_size=20${filter ? `&status=${filter}` : ""}`,
    );
    setPage(data);
    if (!selected && data.items[0]) setSelected(data.items[0].id);
    if (
      selected &&
      !data.items.some((row) => row.id === selected) &&
      data.items[0]
    )
      setSelected(data.items[0].id);
  }
  async function loadDetail(id = selected) {
    if (!id) return;
    const generation = ++detailGeneration.current;
    const data = await api<Detail>(`/helpdesk/knowledge-drafts/${id}`);
    if (generation !== detailGeneration.current) return;
    setDetail(data);
    setTitle(data.draft.title);
    setContent(data.draft.content);
    setKeywords(data.draft.keywords);
    setNote(data.draft.review_note || "");
  }
  useEffect(() => {
    loadList().catch((e) => setError(e.message));
  }, [pageNumber, filter]);
  useEffect(() => {
    loadDetail().catch((e) => setError(e.message));
  }, [selected]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!detail || busy || !detail.can_edit) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api(`/helpdesk/knowledge-drafts/${detail.draft.id}`, {
        method: "PUT",
        body: JSON.stringify({
          expected_version: detail.draft.version,
          title,
          content,
          keywords,
        }),
      });
      await loadDetail();
      await loadList();
      setMessage("草稿已保存；已驳回的草稿回到待审核状态。");
    } catch (e) {
      setError(e instanceof Error ? e.message : "草稿保存失败");
    } finally {
      setBusy(false);
    }
  }
  async function review(action: "publish" | "reject") {
    if (
      !detail ||
      !detail.can_review ||
      detail.draft.status !== "DRAFT" ||
      busy
    )
      return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<{
        source_code?: string;
        source_version?: number;
      }>(`/helpdesk/knowledge-drafts/${detail.draft.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ expected_version: detail.draft.version, note }),
      });
      if (action === "publish") await onPublished?.();
      await loadDetail();
      await loadList();
      setMessage(
        action === "publish"
          ? `草稿已发布为 ${result.source_code} v${result.source_version}，并已更新检索索引。`
          : "草稿已驳回；作者可以修改后重新提交。",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "审核操作失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="knowledge-drafts-panel panel">
      <div className="section-heading">
        <h2>
          <FileCheck2 size={18} />
          知识草稿审核
        </h2>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => {
            setError("");
            loadList()
              .then(() => loadDetail())
              .catch((e) => setError(e.message));
          }}
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      <p className="panel-footnote">
        草稿不会参与检索；发布后才会创建知识版本与索引。
      </p>
      {error && (
        <div className="error" role="alert">
          {error}
          {error.includes("更新") && (
            <button
              className="text-button"
              onClick={() => {
                loadList()
                  .then(() => loadDetail())
                  .catch((e) => setError(e.message));
              }}
            >
              刷新草稿
            </button>
          )}
        </div>
      )}
      {message && (
        <p className="success-message" role="status">
          {message}
        </p>
      )}
      <div className="knowledge-drafts-layout">
        <div className="knowledge-drafts-list">
          <label>
            状态筛选
            <select
              disabled={busy}
              value={filter}
              onChange={(event) => {
                detailGeneration.current++;
                setFilter(event.target.value);
                setPageNumber(1);
                setSelected("");
                setDetail(undefined);
              }}
            >
              <option value="">全部</option>
              <option value="DRAFT">待审核</option>
              <option value="PUBLISHED">已发布</option>
              <option value="REJECTED">已驳回</option>
            </select>
          </label>
          {!page?.items.length && (
            <p className="context-empty">当前没有可查看的知识草稿。</p>
          )}
          {page?.items.map((row) => (
            <button
              className={
                selected === row.id
                  ? "knowledge-draft-row active"
                  : "knowledge-draft-row"
              }
              key={row.id}
              disabled={busy}
              onClick={() => {
                detailGeneration.current++;
                setDetail(undefined);
                setSelected(row.id);
              }}
            >
              <strong>{row.title}</strong>
              <span>
                {statusLabel[row.status]} · v{row.version}
              </span>
              <small>
                {row.author_name} · {time(row.updated_at)}
              </small>
            </button>
          ))}
          {pageNumber > 1 && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setPageNumber((value) => value - 1)}
            >
              上一页
            </button>
          )}
          {page?.has_more && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setPageNumber((value) => value + 1)}
            >
              下一页
            </button>
          )}
        </div>
        {detail && (
          <div className="knowledge-draft-detail">
            <div className="knowledge-draft-meta">
              <span>{statusLabel[detail.draft.status]}</span>
              <span>来源工单 #{detail.draft.ticket_id.slice(0, 8)}</span>
              <span>作者 {detail.draft.author_name}</span>
              <span>版本 v{detail.draft.version}</span>
            </div>
            {detail.resolution && (
              <details className="knowledge-draft-resolution">
                <summary>解决快照 · {detail.resolution.category}</summary>
                <p>{detail.resolution.summary}</p>
                <ol>
                  {stepList(detail.resolution.steps).map((step, index) => (
                    <li key={`${index}-${step}`}>{step}</li>
                  ))}
                </ol>
              </details>
            )}
            {detail.can_edit ? (
              <form className="knowledge-draft-form" onSubmit={save}>
                <label>
                  草稿标题
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    minLength={2}
                    maxLength={200}
                    required
                    disabled={busy}
                  />
                </label>
                <label>
                  知识正文
                  <textarea
                    value={content}
                    onChange={(event) => setContent(event.target.value)}
                    minLength={20}
                    maxLength={15000}
                    required
                    disabled={busy}
                  />
                </label>
                <label>
                  检索关键词
                  <input
                    value={keywords}
                    onChange={(event) => setKeywords(event.target.value)}
                    maxLength={500}
                    disabled={busy}
                  />
                </label>
                <button className="secondary" disabled={busy}>
                  保存草稿
                </button>
              </form>
            ) : (
              <div className="knowledge-draft-readonly">
                <h3>{detail.draft.title}</h3>
                <p>{detail.draft.content}</p>
                <small>{detail.draft.keywords}</small>
              </div>
            )}
            {detail.draft.status === "REJECTED" && (
              <p className="error">
                驳回说明：{detail.draft.review_note || "未提供说明"}
              </p>
            )}
            {detail.can_review && detail.draft.status === "DRAFT" && (
              <div className="knowledge-draft-review">
                <label>
                  审核说明
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    maxLength={1000}
                    disabled={busy}
                    placeholder="驳回原因（必填）或发布说明"
                  />
                </label>
                <div>
                  <button
                    className="secondary"
                    disabled={busy || !note.trim()}
                    onClick={() => review("reject")}
                  >
                    <X size={14} />
                    驳回
                  </button>
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      title !== detail.draft.title ||
                      content !== detail.draft.content ||
                      keywords !== detail.draft.keywords
                    }
                    onClick={() => review("publish")}
                  >
                    <Check size={14} />
                    审核并发布
                  </button>
                </div>
                {(title !== detail.draft.title ||
                  content !== detail.draft.content ||
                  keywords !== detail.draft.keywords) && (
                  <p className="panel-footnote">
                    草稿有未保存修改，请先保存后再发布。
                  </p>
                )}
              </div>
            )}
            {detail.draft.status === "PUBLISHED" && (
              <p className="success-message">
                已发布：{detail.draft.published_code} v
                {detail.draft.published_version}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
