import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { CheckCircle2, Send, Star } from "lucide-react";

type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
export type Resolution = {
  id: string;
  ticket_id: string;
  category: string;
  summary: string;
  steps: string;
  author_name: string;
  resolved_at: string;
  created_at: string;
};
type Satisfaction = {
  id: string;
  resolution_id: string;
  rating: number;
  comment: string;
  created_at: string;
};
type ResolutionPage = {
  resolution: Resolution | null;
  current: boolean;
  can_resolve: boolean;
  updated_at: string;
  satisfaction: Satisfaction | null;
};
type Props = {
  api: Api;
  ticketId: string;
  updatedAt: string;
  disabled?: boolean;
  onBusyChange: (value: boolean) => void;
  onChanged: () => Promise<void>;
};
const categories: Record<string, string> = {
  configuration: "配置调整",
  account_access: "账号与权限",
  software: "软件处理",
  service: "服务恢复",
  guidance: "操作指导",
  other: "其他",
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong" });

function useResolution(api: Api, path: string, updatedAt: string) {
  const [data, setData] = useState<ResolutionPage>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setData(undefined);
    setError("");
    return () => {
      generation.current++;
    };
  }, [path]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api<ResolutionPage>(path)
      .then((page) => {
        if (active) {
          setData(page);
          setError("");
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
  }, [path, updatedAt]);
  return { data, setData, loading, error, setError, generation };
}
export function ResolutionView({ data }: { data: ResolutionPage }) {
  const row = data.resolution;
  if (!row)
    return (
      <p className="panel-footnote">
        尚未填写公开解决记录；历史工单仍可按原流程确认。
      </p>
    );
  return (
    <div className="resolution-summary">
      <h3>
        <CheckCircle2 size={16} />
        {data.current ? "本轮解决记录" : "上一轮解决记录"}
      </h3>
      <p className="panel-footnote">
        {categories[row.category] || row.category} · {row.author_name} ·{" "}
        {time(row.resolved_at)}
        {!data.current && " · 当前工单已重新处理"}
      </p>
      <strong>公开解决摘要</strong>
      <p className="resolution-steps">{row.summary}</p>
      {row.steps && (
        <>
          <strong>公开排查步骤</strong>
          <p className="resolution-steps">{row.steps}</p>
        </>
      )}
      {data.satisfaction && (
        <div className="resolution-satisfaction">
          <strong>本轮评价：{data.satisfaction.rating} / 5</strong>
          {data.satisfaction.comment && (
            <p className="resolution-steps">{data.satisfaction.comment}</p>
          )}
          <small>{time(data.satisfaction.created_at)}</small>
        </div>
      )}
    </div>
  );
}
export function SupportResolution({
  api,
  ticketId,
  updatedAt,
  disabled = false,
  onBusyChange,
  onChanged,
  renderCurrent,
}: Props & { renderCurrent?: (resolutionId: string) => ReactNode }) {
  const { data, setData, loading, error, setError, generation } = useResolution(
    api,
    `/helpdesk/tickets/${ticketId}/resolution`,
    updatedAt,
  );
  const [category, setCategory] = useState("configuration");
  const [summary, setSummary] = useState("");
  const [steps, setSteps] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef<{ key: string; body: string } | undefined>(undefined);
  useEffect(() => {
    pending.current = undefined;
    setSummary("");
    setSteps("");
    setNotice("");
  }, [ticketId]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!data || busy || disabled || summary.trim().length < 2) return;
    const key = JSON.stringify([category, summary.trim(), steps.trim()]);
    if (!pending.current || pending.current.key !== key)
      pending.current = {
        key,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_updated_at: data.updated_at,
          category,
          summary: summary.trim(),
          steps: steps.trim(),
        }),
      };
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      const saved = await api<{
        resolution: Resolution;
        updated_at: string;
        cached: boolean;
      }>(`/helpdesk/tickets/${ticketId}/resolve`, {
        method: "POST",
        body: pending.current.body,
      });
      if (generation.current !== current) return;
      pending.current = undefined;
      setSummary("");
      setSteps("");
      setData({
        resolution: saved.resolution,
        current: true,
        can_resolve: false,
        updated_at: saved.updated_at,
        satisfaction: null,
      });
      setNotice("公开解决记录已保存，工单已标记解决。");
      await onChanged();
    } catch (e) {
      if (generation.current !== current) return;
      const status = (e as Error & { status?: number }).status;
      setError(
        e instanceof Error ? e.message : "提交结果未确认，可重试原请求。",
      );
      if (status && status < 500) pending.current = undefined;
      if (status === 409) {
        try {
          await onChanged();
          setNotice("工单已刷新，请核对后重新提交。");
        } catch {
          setNotice("刷新未完成，请重新打开工单后再试。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  return (
    <section className="ticket-resolution" aria-label="解决记录">
      {loading && (
        <p className="panel-footnote" role="status">
          正在读取解决记录…
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="panel-footnote" role="status">
          {notice}
        </p>
      )}
      {data && <ResolutionView data={data} />}
      {data?.current && data.resolution && renderCurrent?.(data.resolution.id)}
      {data?.can_resolve && (
        <form className="note-form resolution-form" onSubmit={submit}>
          <h3>填写公开解决记录</h3>
          <p className="panel-footnote">
            以下分类、摘要和步骤对报障人可见，请仅填写可公开的处理结论。保存后标记解决。
          </p>
          <label htmlFor={`resolution-category-${ticketId}`}>
            解决分类
            <select
              id={`resolution-category-${ticketId}`}
              value={category}
              disabled={busy || disabled}
              onChange={(e) => setCategory(e.target.value)}
            >
              {Object.entries(categories).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor={`resolution-summary-${ticketId}`}>
            公开解决摘要
            <textarea
              id={`resolution-summary-${ticketId}`}
              value={summary}
              minLength={2}
              maxLength={2000}
              required
              disabled={busy || disabled}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="说明问题如何解决，以及报障人应了解的结论…"
            />
          </label>
          <label htmlFor={`resolution-steps-${ticketId}`}>
            公开排查步骤（可选）
            <textarea
              id={`resolution-steps-${ticketId}`}
              value={steps}
              maxLength={5000}
              disabled={busy || disabled}
              onChange={(e) => setSteps(e.target.value)}
              placeholder="按顺序记录可公开的检查和处理步骤…"
            />
          </label>
          <button
            className="primary"
            disabled={busy || disabled || loading || summary.trim().length < 2}
          >
            <CheckCircle2 size={15} />
            {busy ? "正在保存…" : "保存解决记录并标记解决"}
          </button>
        </form>
      )}
    </section>
  );
}
export function RequesterResolution({
  api,
  ticketId,
  updatedAt,
  status,
  disabled = false,
  onBusyChange,
  onChanged,
}: Props & { status: string }) {
  const { data, setData, loading, error, setError, generation } = useResolution(
    api,
    `/helpdesk/my-tickets/${ticketId}/resolution`,
    updatedAt,
  );
  const [rating, setRating] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef<{ key: string; body: string } | undefined>(undefined);
  useEffect(() => {
    pending.current = undefined;
    setRating("");
    setComment("");
    setNotice("");
  }, [ticketId, data?.resolution?.id]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!data?.resolution || !rating || busy || disabled) return;
    const key = JSON.stringify([data.resolution.id, rating, comment.trim()]);
    if (!pending.current || pending.current.key !== key)
      pending.current = {
        key,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          resolution_id: data.resolution.id,
          rating: Number(rating),
          comment: comment.trim(),
        }),
      };
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    try {
      const saved = await api<{
        satisfaction: Satisfaction;
        updated_at: string;
      }>(`/helpdesk/my-tickets/${ticketId}/satisfaction`, {
        method: "POST",
        body: pending.current.body,
      });
      if (generation.current !== current) return;
      pending.current = undefined;
      setData({
        ...data,
        satisfaction: saved.satisfaction,
        updated_at: saved.updated_at,
      });
      setNotice("本轮评价已保存，感谢反馈。");
      await onChanged();
    } catch (e) {
      if (generation.current !== current) return;
      const code = (e as Error & { status?: number }).status;
      if (code && code < 500) pending.current = undefined;
      setError(
        e instanceof Error ? e.message : "提交结果未确认，可重试原请求。",
      );
      if (code === 409) {
        try {
          await onChanged();
        } catch {
          setNotice("刷新未完成，请重新打开工单后再试。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  return (
    <section className="ticket-resolution" aria-label="公开解决与验收评价">
      {loading && (
        <p role="status" className="panel-footnote">
          正在读取解决记录…
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="panel-footnote" role="status">
          {notice}
        </p>
      )}
      {data && <ResolutionView data={data} />}
      {status === "CLOSED" &&
        data?.current &&
        data.resolution &&
        !data.satisfaction && (
          <form className="note-form resolution-form" onSubmit={submit}>
            <h3>
              <Star size={16} /> 为本轮处理评分（可选）
            </h3>
            <p className="panel-footnote">
              评分和短评对本工单支持团队可见，仅对应这一次解决记录。每轮只能提交一次。
            </p>
            <label htmlFor={`resolution-rating-${ticketId}`}>
              本轮满意度
              <select
                id={`resolution-rating-${ticketId}`}
                value={rating}
                required
                disabled={busy || disabled}
                onChange={(e) => setRating(e.target.value)}
              >
                <option value="">请选择评分</option>
                {[1, 2, 3, 4, 5].map((value) => (
                  <option value={value} key={value}>
                    {value} 分
                    {value === 1 ? " · 不满意" : value === 5 ? " · 很满意" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label htmlFor={`resolution-comment-${ticketId}`}>
              评价短评（可选）
              <textarea
                id={`resolution-comment-${ticketId}`}
                value={comment}
                maxLength={1000}
                disabled={busy || disabled}
                onChange={(e) => setComment(e.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={busy || disabled || loading || !rating}
            >
              <Send size={15} />
              {busy ? "正在提交…" : "提交本轮评价"}
            </button>
          </form>
        )}
    </section>
  );
}
