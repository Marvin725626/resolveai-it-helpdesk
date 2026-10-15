import { useEffect, useRef, useState, type FormEvent } from "react";
import { Flag } from "lucide-react";
type Api = <T>(path: string, init?: RequestInit) => Promise<T>;
type PriorityData = {
  priority: string;
  can_change: boolean;
  created_at: string;
  updated_at: string;
  target_hours_by_priority: Record<string, number>;
  sla: { due_at: string; target_hours: number; state: string };
};
const labels: Record<string, string> = {
  LOW: "低",
  MEDIUM: "普通",
  HIGH: "高",
  URGENT: "紧急",
};
const time = (value: string | number) =>
  new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong" });
export default function TicketPriority({
  api,
  ticketId,
  updatedAt,
  disabled = false,
  onBusyChange,
  onChanged,
}: {
  api: Api;
  ticketId: string;
  updatedAt: string;
  disabled?: boolean;
  onBusyChange: (busy: boolean) => void;
  onChanged: () => Promise<void>;
}) {
  const [data, setData] = useState<PriorityData>();
  const [priority, setPriority] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(false),
    [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const pending = useRef<{ key: string; body: string } | undefined>(undefined);
  useEffect(() => {
    generation.current++;
    pending.current = undefined;
    setRetry(false);
    setData(undefined);
    setReason("");
    setNotice("");
    setError("");
    return () => {
      generation.current++;
    };
  }, [ticketId]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api<PriorityData>(`/helpdesk/tickets/${ticketId}/priority`)
      .then((value) => {
        if (active) {
          setData(value);
          if (!pending.current) setPriority(value.priority);
        }
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [ticketId, updatedAt, revision]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!data || busy || disabled || reason.trim().length < 2) return;
    const key = JSON.stringify([priority, reason.trim()]);
    if (!pending.current || pending.current.key !== key)
      pending.current = {
        key,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          expected_updated_at: data.updated_at,
          priority,
          reason: reason.trim(),
        }),
      };
    const current = generation.current;
    setBusy(true);
    onBusyChange(true);
    setRetry(true);
    setError("");
    setNotice("");
    try {
      const saved = await api<PriorityData>(
        `/helpdesk/tickets/${ticketId}/priority`,
        { method: "POST", body: pending.current.body },
      );
      if (generation.current !== current) return;
      pending.current = undefined;
      setRetry(false);
      setData(saved);
      setPriority(saved.priority);
      setReason("");
      setNotice("优先级已更新，演示时限仍从原创建时间计算。");
      await onChanged();
    } catch (e) {
      if (generation.current !== current) return;
      const status = (e as Error & { status?: number }).status;
      if (status && status < 500) {
        pending.current = undefined;
        setRetry(false);
      }
      setError(
        e instanceof Error ? e.message : "提交结果未确认，可以重试原请求。",
      );
      if (status === 409) {
        setRevision((v) => v + 1);
        try {
          await onChanged();
          setNotice("工单已刷新，请核对当前优先级后再提交。");
        } catch {
          setNotice("刷新未完成，请重新打开工单后再试。");
        }
      }
    } finally {
      if (generation.current === current) setBusy(false);
      onBusyChange(false);
    }
  }
  const hours = data?.target_hours_by_priority[priority];
  const due =
    data && hours !== undefined
      ? new Date(data.created_at).getTime() + hours * 3600000
      : undefined;
  return (
    <section className="ticket-priority-panel" aria-label="优先级调整">
      <h3>
        <Flag size={16} />
        工单优先级
      </h3>
      {loading && (
        <p role="status" className="panel-footnote">
          正在读取优先级…
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          {error}
          <button
            className="text-button"
            disabled={busy || disabled}
            onClick={() => setRevision((v) => v + 1)}
          >
            刷新优先级
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="panel-footnote">
          {notice}
        </p>
      )}
      {data && (
        <p className="panel-footnote">
          当前：{labels[data.priority]}优先级 · 演示目标 {data.sla.target_hours}{" "}
          小时 · 截止 {time(data.sla.due_at)}
        </p>
      )}
      {data && (data.can_change || retry) ? (
        <form className="priority-form" onSubmit={submit}>
          <label htmlFor={`priority-target-${ticketId}`}>
            新优先级
            <select
              id={`priority-target-${ticketId}`}
              value={priority}
              disabled={busy || disabled || loading}
              onChange={(e) => {
                setPriority(e.target.value);
                pending.current = undefined;
                setRetry(false);
              }}
            >
              {Object.entries(labels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {due !== undefined && (
            <div className="priority-preview" role="status">
              <strong>调整后演示目标：{hours} 小时</strong>
              <p>
                仍从 {time(data.created_at)} 起算，截止 {time(due)}。
              </p>
              <p>
                {due <= Date.now()
                  ? "按新目标当前已经逾期，请及时跟进。"
                  : "新目标不会重置工单创建时间；缩短时限可能使工单立即逾期。"}
              </p>
            </div>
          )}
          <label htmlFor={`priority-reason-${ticketId}`}>
            调整原因（仅支持团队可见）
            <textarea
              id={`priority-reason-${ticketId}`}
              value={reason}
              disabled={busy || disabled}
              minLength={2}
              maxLength={1000}
              required
              onChange={(e) => {
                setReason(e.target.value);
                pending.current = undefined;
                setRetry(false);
              }}
              placeholder="说明为何调整处理优先级…"
            />
          </label>
          <button
            className="secondary"
            disabled={
              busy ||
              disabled ||
              loading ||
              reason.trim().length < 2 ||
              (!retry && priority === data.priority)
            }
          >
            {busy ? "正在保存…" : retry ? "重试原优先级请求" : "保存优先级调整"}
          </button>
        </form>
      ) : (
        data && (
          <p className="panel-footnote">
            只有当前接手人或管理员可调整未完成工单的优先级。
          </p>
        )
      )}
    </section>
  );
}
