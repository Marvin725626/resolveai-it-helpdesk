import { useEffect, useState } from "react";
import { ChevronRight, History, MessageSquare } from "lucide-react";
import type { Run } from "./ResolveApp";
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Row = {
  id: string;
  question: string;
  created_at: string;
  result: Pick<Run, "status" | "category" | "latency_ms" | "escalate">;
};
type Page = { items: Row[]; total: number };
const labels: Record<string, string> = {
  completed: "已完成",
  running: "运行中",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};
const categories: Record<string, string> = {
  vpn: "VPN / 网络",
  account: "身份与权限",
  software: "办公软件",
  service: "内部服务",
  email: "企业邮箱",
  unknown: "未分类",
};
export default function RunHistory({
  api,
  onOpen,
  onRetry,
  onChanged,
}: {
  api: Api;
  onOpen: (row: { question: string; result: Run }) => void;
  onRetry: (question: string) => void;
  onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<Page>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");
  const [category, setCategory] = useState("ALL");
  const [days, setDays] = useState("ALL");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);
  const params = new URLSearchParams({
    q: search,
    page: String(page),
    page_size: String(size),
  });
  if (status !== "ALL") params.set("status", status);
  if (category !== "ALL") params.set("category", category);
  if (days !== "ALL") params.set("days", days);
  const url = params.toString();
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<Page>("/helpdesk/run-history?" + url)
      .then((value) => {
        if (active) {
          setData(value);
          if (page > 1 && !value.items.length)
            setPage(Math.max(1, Math.ceil(value.total / size)));
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [url, revision]);
  async function open(id: string) {
    setBusy(true);
    setError("");
    try {
      onOpen(
        await api<{ question: string; result: Run }>("/helpdesk/runs/" + id),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "记录加载失败");
    } finally {
      setBusy(false);
    }
  }
  async function recover(id: string) {
    setBusy(true);
    setError("");
    try {
      await api("/helpdesk/runs/" + id + "/recover", { method: "POST" });
      setRevision((value) => value + 1);
      await onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="section-heading">
        <h2>
          运行记录<span className="small-pill">{data?.total ?? "—"}</span>
        </h2>
        <button
          className="text-button"
          onClick={() => setRevision((value) => value + 1)}
        >
          刷新运行记录
        </button>
      </div>
      <div className="ticket-filters">
        <label>
          搜索运行问题 / ID
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="问题内容或运行 ID"
          />
        </label>
        <label>
          运行状态
          <select
            aria-label="运行状态"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部状态</option>
            {Object.entries(labels).map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          问题分类
          <select
            aria-label="问题分类"
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部分类</option>
            {Object.entries(categories).map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          运行时间
          <select
            aria-label="运行时间"
            value={days}
            onChange={(event) => {
              setDays(event.target.value);
              setPage(1);
            }}
          >
            <option value="ALL">全部时间</option>
            <option value="7">最近 7 天</option>
            <option value="30">最近 30 天</option>
            <option value="90">最近 90 天</option>
            <option value="365">最近 365 天</option>
          </select>
        </label>
      </div>
      <p className="panel-footnote">
        当前账号 · 服务端分页。时间筛选按最近 N×24
        小时计算。详情按需读取；三分钟以上未完成运行可标记中断后重试。
      </p>
      {loading && (
        <p role="status" className="panel-footnote">
          正在更新运行记录…
        </p>
      )}
      {!loading && !data?.items.length && (
        <div className="context-empty large">
          <History size={32} />
          <h3>没有匹配的运行记录</h3>
        </div>
      )}
      {data?.items.map((row) => (
        <article className="history-row" key={row.id}>
          <button
            className="history-open"
            disabled={loading || busy}
            onClick={() => open(row.id)}
          >
            <span className="history-icon">
              <MessageSquare size={18} />
            </span>
            <span>
              <strong>{row.question}</strong>
              <small>
                {new Date(row.created_at).toLocaleString("zh-CN", {
                  timeZone: "Asia/Hong_Kong",
                })}{" "}
                · {labels[row.result.status] || "未知状态"} ·{" "}
                {row.result.latency_ms ?? "—"} ms ·{" "}
                {categories[row.result.category || "unknown"]}
              </small>
            </span>
            <ChevronRight size={17} />
          </button>
          <div className="history-controls">
            {row.result.status === "running" && (
              <button
                className="secondary"
                disabled={
                  loading ||
                  busy ||
                  Date.now() - Date.parse(row.created_at) < 180000
                }
                onClick={() => recover(row.id)}
              >
                标记超时中断
              </button>
            )}
            <button
              className="secondary"
              disabled={loading || busy}
              onClick={() => onRetry(row.question)}
            >
              填入问题重试
            </button>
          </div>
        </article>
      ))}
      <div className="pagination">
        <span>
          共 {data?.total ?? 0} 条 · 第 {page} /{" "}
          {Math.max(1, Math.ceil((data?.total || 0) / size))} 页
        </span>
        <label>
          每页数量
          <select
            aria-label="运行每页数量"
            value={size}
            onChange={(event) => {
              setSize(Number(event.target.value));
              setPage(1);
            }}
          >
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
          </select>
        </label>
        <button
          className="secondary"
          disabled={loading || page === 1}
          onClick={() => setPage((value) => value - 1)}
        >
          上一页
        </button>
        <button
          className="secondary"
          disabled={loading || page * size >= (data?.total || 0)}
          onClick={() => setPage((value) => value + 1)}
        >
          下一页
        </button>
      </div>
    </section>
  );
}
