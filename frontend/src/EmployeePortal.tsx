import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, RefreshCw, Search, Ticket } from "lucide-react";
import "./portal.css";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type Field = {
  key: string;
  label: string;
  type: "text" | "textarea" | "select";
  required: boolean;
  options?: string[];
};
type Service = {
  id: string;
  code: string;
  title: string;
  summary: string;
  category: string;
  version: number;
};
type ServiceDetail = Service & { fields: Field[] };
type RequestItem = {
  id: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string;
};
type Overview = {
  statuses: Record<string, number>;
  total: number;
  active: number;
  resolved_awaiting_confirmation: number;
  closed: number;
  latest: RequestItem[];
};
type ApiError = Error & { status?: number };
const statusLabels: Record<string, string> = {
  OPEN: "待处理",
  ESCALATED: "转人工",
  IN_PROGRESS: "处理中",
  WAITING_FOR_CUSTOMER: "等待反馈",
  RESOLVED: "待确认",
  CLOSED: "已关闭",
};

export default function EmployeePortal({
  api,
  onOpenTicket,
  onCreated,
  showPersonalOverview = true,
}: {
  api: Api;
  onOpenTicket: (id?: string) => void;
  onCreated?: (id: string) => void;
  showPersonalOverview?: boolean;
}) {
  const [overview, setOverview] = useState<Overview>();
  const [overviewBusy, setOverviewBusy] = useState(true);
  const [overviewError, setOverviewError] = useState("");
  const [catalog, setCatalog] = useState<Service[]>([]);
  const [catalogBusy, setCatalogBusy] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ServiceDetail>();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [detailBusy, setDetailBusy] = useState(false);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [versionStale, setVersionStale] = useState(false);
  const requestRef = useRef<{ signature: string; id: string } | undefined>(
    undefined,
  );

  async function loadOverview() {
    setOverviewBusy(true);
    setOverviewError("");
    try {
      setOverview(await api<Overview>("/helpdesk/portal/overview"));
    } catch (e) {
      setOverviewError(e instanceof Error ? e.message : "暂时无法加载个人请求");
    } finally {
      setOverviewBusy(false);
    }
  }
  async function loadCatalog() {
    setCatalogBusy(true);
    setCatalogError("");
    try {
      const result = await api<{ items: Service[] }>(
        "/helpdesk/service-catalog",
      );
      setCatalog(result.items || []);
    } catch (e) {
      setCatalogError(e instanceof Error ? e.message : "暂时无法加载服务目录");
    } finally {
      setCatalogBusy(false);
    }
  }
  useEffect(() => {
    if (showPersonalOverview) void loadOverview();
    void loadCatalog();
  }, []);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return catalog
      .slice(0, 20)
      .filter(
        (item) =>
          !needle ||
          `${item.title} ${item.summary} ${item.category}`
            .toLocaleLowerCase()
            .includes(needle),
      );
  }, [catalog, query]);

  async function openService(id: string, preserveAnswers = false) {
    setDetailBusy(true);
    setSubmitError("");
    setVersionStale(false);
    try {
      const result = await api<{ item: ServiceDetail }>(
        `/helpdesk/service-catalog/${encodeURIComponent(id)}`,
      );
      setSelected(result.item);
      setAnswers((current) =>
        preserveAnswers
          ? Object.fromEntries(
              result.item.fields
                .filter((field) => field.key in current)
                .map((field) => [field.key, current[field.key]]),
            )
          : {},
      );
      requestRef.current = undefined;
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "无法打开服务");
    } finally {
      setDetailBusy(false);
    }
  }
  function updateAnswer(key: string, value: string) {
    setAnswers((current) => {
      const next = { ...current, [key]: value };
      requestRef.current = undefined;
      return next;
    });
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || submitBusy) return;
    const signature = JSON.stringify([selected.id, selected.version, answers]);
    if (!requestRef.current || requestRef.current.signature !== signature)
      requestRef.current = { signature, id: crypto.randomUUID() };
    setSubmitBusy(true);
    setSubmitError("");
    setVersionStale(false);
    try {
      const result = await api<{
        ticket_id: string;
        request_id: string;
        replayed: boolean;
      }>(
        `/helpdesk/service-catalog/${encodeURIComponent(selected.id)}/submit`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: requestRef.current.id,
            expected_version: selected.version,
            answers,
          }),
        },
      );
      if (onCreated) onCreated(result.ticket_id);
      else onOpenTicket(result.ticket_id);
    } catch (e) {
      const error = e as ApiError;
      const stale =
        error.status === 409 || /409|版本|更新后/.test(error.message || "");
      setVersionStale(stale);
      setSubmitError(
        stale
          ? "此服务模板已更新。请重新加载服务后再提交；你填写的内容已保留。"
          : error.message || "提交失败，请重试。",
      );
    } finally {
      setSubmitBusy(false);
    }
  }

  return (
    <div className="portal-stack">
      {showPersonalOverview && (
        <section className="portal-stats" aria-label="我的请求统计">
          {[
            ["待处理请求", overview?.active],
            ["待我确认", overview?.resolved_awaiting_confirmation],
            ["全部请求", overview?.total],
          ].map(([label, value]) => (
            <div className="portal-stat" key={String(label)}>
              <span>{label}</span>
              <strong>{overviewBusy ? "…" : (value ?? "—")}</strong>
            </div>
          ))}
        </section>
      )}
      <section className="panel portal-panel">
        <div className="section-heading">
          <h2>服务大厅</h2>
          <span className="micro-label">选择服务并填写申请</span>
        </div>
        {selected ? (
          <>
            <button
              className="portal-back"
              type="button"
              onClick={() => {
                setSelected(undefined);
                setSubmitError("");
              }}
            >
              <ArrowLeft size={15} />
              返回服务列表
            </button>
            <div className="portal-service-heading">
              <span className="source-code">
                {selected.category || selected.code}
              </span>
              <h3>{selected.title}</h3>
              <p>{selected.summary}</p>
            </div>
            {versionStale && (
              <div className="portal-alert" role="alert">
                <span>{submitError}</span>
                <button
                  className="secondary"
                  type="button"
                  disabled={detailBusy || submitBusy}
                  onClick={() => void openService(selected.id, true)}
                >
                  {detailBusy ? "正在加载…" : "重新加载服务"}
                </button>
              </div>
            )}
            {!versionStale && submitError && (
              <div className="error" role="alert">
                {submitError}
              </div>
            )}
            <form className="portal-form" onSubmit={submit}>
              {selected.fields.map((field) => (
                <label className="portal-field" key={field.key}>
                  <span>
                    {field.label}
                    {field.required && <b> · 必填</b>}
                  </span>
                  {field.type === "textarea" ? (
                    <textarea
                      aria-label={`服务申请-${field.label}`}
                      value={answers[field.key] || ""}
                      onChange={(e) => updateAnswer(field.key, e.target.value)}
                      required={field.required}
                      maxLength={4000}
                      disabled={submitBusy}
                      rows={4}
                    />
                  ) : field.type === "select" ? (
                    <select
                      aria-label={`服务申请-${field.label}`}
                      value={answers[field.key] || ""}
                      onChange={(e) => updateAnswer(field.key, e.target.value)}
                      required={field.required}
                      disabled={submitBusy}
                    >
                      <option value="">请选择</option>
                      {field.options?.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      aria-label={`服务申请-${field.label}`}
                      value={answers[field.key] || ""}
                      onChange={(e) => updateAnswer(field.key, e.target.value)}
                      required={field.required}
                      maxLength={500}
                      disabled={submitBusy}
                    />
                  )}
                </label>
              ))}
              <p className="portal-privacy">请勿填写密码、验证码或访问令牌。</p>
              <button
                className="primary"
                type="submit"
                disabled={submitBusy || detailBusy}
              >
                {submitBusy ? "正在提交…" : "提交服务申请"}
                <ArrowRight size={16} />
              </button>
            </form>
          </>
        ) : (
          <>
            <label className="portal-search">
              <Search size={17} />
              <span className="sr-only">搜索服务</span>
              <input
                aria-label="搜索服务"
                placeholder="搜索服务"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={100}
              />
            </label>
            {catalogError && (
              <div className="error" role="alert">
                {catalogError}
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void loadCatalog()}
                >
                  重试
                </button>
              </div>
            )}
            {catalogBusy ? (
              <p className="portal-message" role="status">
                正在加载已发布服务…
              </p>
            ) : catalogError ? null : catalog.length === 0 ? (
              <div className="portal-empty">
                <h3>暂时没有已发布的服务</h3>
                <p>请联系工作区管理员了解服务开放情况。</p>
              </div>
            ) : filtered.length === 0 ? (
              <p className="portal-message">没有找到匹配的服务。</p>
            ) : (
              <div className="portal-catalog">
                {filtered.map((item) => (
                  <article className="portal-service-card" key={item.id}>
                    <span className="source-code">
                      {item.category || item.code}
                    </span>
                    <h3>{item.title}</h3>
                    <p>{item.summary}</p>
                    <button
                      className="secondary"
                      type="button"
                      onClick={() => void openService(item.id)}
                      disabled={detailBusy}
                    >
                      {detailBusy ? "正在打开…" : "查看并申请"}
                      <ArrowRight size={15} />
                    </button>
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </section>
      {showPersonalOverview && (
        <section className="panel portal-panel">
          <div className="section-heading">
            <h2>
              <Ticket size={17} />
              最近请求
            </h2>
            <button
              className="text-button"
              type="button"
              onClick={() => void loadOverview()}
              disabled={overviewBusy}
            >
              <RefreshCw size={14} />
              刷新
            </button>
          </div>
          {overviewError ? (
            <div className="error" role="alert">
              {overviewError}
              <button
                className="text-button"
                type="button"
                onClick={() => void loadOverview()}
              >
                重试
              </button>
            </div>
          ) : overviewBusy ? (
            <p className="portal-message" role="status">
              正在加载你的请求…
            </p>
          ) : overview?.latest.length ? (
            <div className="portal-requests">
              {overview.latest.map((ticket) => (
                <button
                  className="portal-request"
                  type="button"
                  key={ticket.id}
                  onClick={() => onOpenTicket(ticket.id)}
                >
                  <span>
                    <strong>{ticket.subject}</strong>
                    <small>
                      #{ticket.id.slice(0, 8)} ·{" "}
                      {new Date(ticket.created_at).toLocaleDateString("zh-CN", {
                        timeZone: "Asia/Hong_Kong",
                      })}
                    </small>
                  </span>
                  <span
                    className={
                      ticket.status === "CLOSED"
                        ? "small-pill green"
                        : "small-pill amber"
                    }
                  >
                    {statusLabels[ticket.status] || ticket.status}
                  </span>
                  <ArrowRight size={16} />
                </button>
              ))}
            </div>
          ) : (
            <div className="portal-empty">
              <p>你还没有提交请求。</p>
              <button
                className="text-button"
                type="button"
                onClick={() => onOpenTicket()}
              >
                报告其他 IT 问题
                <ArrowRight size={15} />
              </button>
            </div>
          )}
          <div className="portal-general">
            <span>遇到目录中没有的 IT 问题？</span>
            <button
              className="secondary"
              type="button"
              onClick={() => onOpenTicket()}
            >
              报告其他 IT 问题
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
